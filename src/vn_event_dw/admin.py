from __future__ import annotations

import hmac
import html
import json
import os
import secrets
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .api_service import fetch_game_detail
from .admin_config import (
    AdminConfigError,
    AdminGameInput,
    add_game_to_payload,
    build_game_preview,
    load_config_payload,
    validate_payload_has_required_targets,
    write_config_payload_atomic,
)
from .etl import open_connection


ADMIN_COOKIE_NAME = "vn_event_dw_admin"
# The shared market-data domain reserves /admin for the centralized Portal.
# Keep this operational UI within the Event service namespace so the VM router
# can forward it alongside the Event API.
ADMIN_ROUTE_PREFIX = "/api/events/admin"


@dataclass(frozen=True, slots=True)
class AdminSettings:
    enabled: bool
    password: str
    config_path: Path
    db_path: Path
    job_dir: Path
    repo_root: Path
    repo_config_path: str
    git_branch: str
    git_enabled: bool
    git_user_name: str
    git_user_email: str
    github_token: str
    backfill_lookback_days: int
    api_verify_url: str


class AdminJobStore:
    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self._lock = threading.Lock()
        self.job_dir.mkdir(parents=True, exist_ok=True)

    def create(self, *, title: str, metadata: dict[str, Any]) -> str:
        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(4)
        payload = {
            "job_id": job_id,
            "title": title,
            "status": "queued",
            "metadata": metadata,
            "created_at": _utc_now(),
            "started_at": None,
            "finished_at": None,
            "error": None,
            "log": [],
        }
        self._write(job_id, payload)
        (self.job_dir / "latest.txt").write_text(job_id + "\n", encoding="utf-8")
        return job_id

    def read(self, job_id: str) -> dict[str, Any]:
        path = self.job_dir / f"{job_id}.json"
        if not path.exists():
            raise KeyError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def latest_job_id(self) -> str | None:
        path = self.job_dir / "latest.txt"
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8").strip()
        return text or None

    def update(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            payload = self.read(job_id)
            payload.update(updates)
            self._write(job_id, payload)

    def append_log(self, job_id: str, text: str) -> None:
        with self._lock:
            payload = self.read(job_id)
            payload.setdefault("log", []).append(text.rstrip())
            self._write(job_id, payload)

    def _write(self, job_id: str, payload: dict[str, Any]) -> None:
        path = self.job_dir / f"{job_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def admin_enabled_from_env() -> bool:
    return os.getenv("ADMIN_UI_ENABLED", "").strip().lower() in {"1", "true", "yes", "y"}


def load_admin_settings(*, db_path: Path) -> AdminSettings:
    config_path = Path(os.getenv("ADMIN_CONFIG_PATH", "/app/examples/config.json"))
    repo_root = Path(os.getenv("ADMIN_REPO_ROOT", "/repo"))
    if not repo_root.exists():
        repo_root = config_path.parents[1] if len(config_path.parents) > 1 else Path.cwd()
    return AdminSettings(
        enabled=admin_enabled_from_env(),
        password=os.getenv("ADMIN_PASSWORD", "").strip(),
        config_path=config_path,
        db_path=Path(os.getenv("ADMIN_DB_PATH", str(db_path))),
        job_dir=Path(os.getenv("ADMIN_JOB_DIR", "/app/data/admin_jobs")),
        repo_root=repo_root,
        repo_config_path=os.getenv("ADMIN_REPO_CONFIG_PATH", "examples/config.json").strip()
        or "examples/config.json",
        git_branch=os.getenv("ADMIN_GIT_BRANCH", "main").strip() or "main",
        git_enabled=os.getenv("ADMIN_GIT_ENABLED", "1").strip().lower() not in {"0", "false", "no", "n"},
        git_user_name=os.getenv("ADMIN_GIT_USER_NAME", "VN Event DW Admin").strip()
        or "VN Event DW Admin",
        git_user_email=os.getenv("ADMIN_GIT_USER_EMAIL", "vn-event-dw-admin@localhost").strip()
        or "vn-event-dw-admin@localhost",
        github_token=os.getenv("ADMIN_GITHUB_TOKEN", "").strip(),
        backfill_lookback_days=int(os.getenv("ADMIN_BACKFILL_LOOKBACK_DAYS", "30")),
        api_verify_url=os.getenv("ADMIN_API_VERIFY_URL", "http://127.0.0.1:8765/api/games").strip()
        or "http://127.0.0.1:8765/api/games",
    )


def create_admin_router(*, db_path: Path) -> APIRouter:
    settings = load_admin_settings(db_path=db_path)
    store = AdminJobStore(settings.job_dir)
    router = APIRouter(prefix=ADMIN_ROUTE_PREFIX)

    def require_admin(request_obj: Request) -> None:
        if not settings.enabled:
            raise HTTPException(status_code=404, detail="Admin UI is disabled.")
        if not settings.password:
            raise HTTPException(status_code=503, detail="ADMIN_PASSWORD is required when admin UI is enabled.")
        cookie_value = request_obj.cookies.get(ADMIN_COOKIE_NAME, "")
        if not _valid_cookie(cookie_value, settings.password):
            raise HTTPException(status_code=401, detail="Admin login required.")

    @router.get("", response_class=HTMLResponse)
    def admin_home(request_obj: Request) -> Response:
        if _is_authenticated(request_obj, settings.password):
            return RedirectResponse(f"{ADMIN_ROUTE_PREFIX}/games", status_code=303)
        return _html_response(_render_login_page(settings=settings))

    @router.post("/login")
    async def admin_login(request_obj: Request) -> Response:
        form = await _read_urlencoded_form(request_obj)
        if not settings.enabled:
            raise HTTPException(status_code=404, detail="Admin UI is disabled.")
        if not settings.password:
            return _html_response(_render_login_page(settings=settings, error="ADMIN_PASSWORD is not configured."), status_code=503)
        if not hmac.compare_digest(form.get("password", ""), settings.password):
            return _html_response(_render_login_page(settings=settings, error="Wrong password."), status_code=401)
        response = RedirectResponse(f"{ADMIN_ROUTE_PREFIX}/games", status_code=303)
        response.set_cookie(
            ADMIN_COOKIE_NAME,
            _cookie_value(settings.password),
            httponly=True,
            samesite="lax",
            secure=False,
        )
        return response

    @router.post("/logout")
    def admin_logout() -> Response:
        response = RedirectResponse(ADMIN_ROUTE_PREFIX, status_code=303)
        response.delete_cookie(ADMIN_COOKIE_NAME)
        return response

    @router.get("/games", response_class=HTMLResponse)
    def admin_games(request_obj: Request) -> Response:
        require_admin(request_obj)
        payload = load_config_payload(settings.config_path)
        latest_job_id = store.latest_job_id()
        latest_job = None
        if latest_job_id:
            try:
                latest_job = store.read(latest_job_id)
            except KeyError:
                latest_job = None
        return _html_response(_render_games_page(settings=settings, payload=payload, latest_job=latest_job))

    @router.post("/games/preview", response_class=HTMLResponse)
    async def admin_games_preview(request_obj: Request) -> Response:
        require_admin(request_obj)
        form = await _read_urlencoded_form(request_obj)
        try:
            payload = load_config_payload(settings.config_path)
            preview = build_game_preview(payload, _game_input_from_form(form))
            validate_payload_has_required_targets(add_game_to_payload(payload, preview), preview.unified_app_id)
        except (AdminConfigError, json.JSONDecodeError) as exc:
            current_payload = load_config_payload(settings.config_path)
            return _html_response(
                _render_games_page(settings=settings, payload=current_payload, latest_job=None, form=form, error=str(exc)),
                status_code=400,
            )
        return _html_response(_render_preview_page(settings=settings, preview=preview, form=form))

    @router.post("/games/apply")
    async def admin_games_apply(request_obj: Request) -> Response:
        require_admin(request_obj)
        form = await _read_urlencoded_form(request_obj)
        payload = load_config_payload(settings.config_path)
        preview = build_game_preview(payload, _game_input_from_form(form))
        updated_payload = add_game_to_payload(payload, preview)
        validate_payload_has_required_targets(updated_payload, preview.unified_app_id)
        job_id = store.create(
            title=f"Add tracked game: {preview.app_name}",
            metadata={
                "unified_app_id": preview.unified_app_id,
                "app_name": preview.app_name,
                "fb_page_id": preview.fb_page_id,
            },
        )
        thread = threading.Thread(
            target=_run_apply_job,
            kwargs={
                "settings": settings,
                "store": store,
                "job_id": job_id,
                "updated_payload": updated_payload,
                "preview": preview,
                "db_path": db_path,
            },
            daemon=True,
        )
        thread.start()
        return RedirectResponse(f"{ADMIN_ROUTE_PREFIX}/jobs/{job_id}", status_code=303)

    @router.get("/jobs/{job_id}", response_class=HTMLResponse)
    def admin_job(request_obj: Request, job_id: str) -> Response:
        require_admin(request_obj)
        try:
            job = store.read(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Admin job not found.") from exc
        return _html_response(_render_job_page(job))

    @router.post("/jobs/{job_id}/resolve")
    async def admin_job_resolve(request_obj: Request, job_id: str) -> Response:
        require_admin(request_obj)
        form = await _read_urlencoded_form(request_obj)
        try:
            job = store.read(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Admin job not found.") from exc
        if job.get("status") not in {"failed", "manually_resolved"}:
            raise HTTPException(status_code=400, detail="Only failed jobs can be manually resolved.")
        note = form.get("note", "").strip()
        resolved_at = _utc_now()
        resolved_message = "Marked manually resolved"
        if note:
            resolved_message += f": {note}"
        store.append_log(job_id, f"[{resolved_at}] {resolved_message}")
        store.update(
            job_id,
            status="manually_resolved",
            finished_at=job.get("finished_at") or resolved_at,
            manual_resolution={
                "resolved_at": resolved_at,
                "note": note,
            },
        )
        return RedirectResponse(f"{ADMIN_ROUTE_PREFIX}/jobs/{job_id}", status_code=303)

    return router


def _run_apply_job(
    *,
    settings: AdminSettings,
    store: AdminJobStore,
    job_id: str,
    updated_payload: dict[str, Any],
    preview: Any,
    db_path: Path,
) -> None:
    store.update(job_id, status="running", started_at=_utc_now())
    pre_head = None
    git_pushed = not settings.git_enabled
    try:
        if settings.git_enabled:
            pre_head = _run_git_preflight(settings=settings, store=store, job_id=job_id)

        _job_log(store, job_id, f"Saving config: {settings.config_path}")
        write_config_payload_atomic(settings.config_path, updated_payload)

        _run_command(store, job_id, [sys.executable, "-m", "json.tool", str(settings.config_path)])

        if settings.git_enabled:
            _run_git_flow(settings=settings, store=store, job_id=job_id, app_name=preview.app_name)
            git_pushed = True
        else:
            _job_log(store, job_id, "Skipping git commit/push because ADMIN_GIT_ENABLED=0.")

        _run_targeted_backfill(settings=settings, store=store, job_id=job_id, unified_app_id=preview.unified_app_id)

        _job_log(store, job_id, "API restart skipped: sync step reloads config into config_app_mapping; config is bind-mounted.")
        _verify_api(store=store, job_id=job_id, db_path=db_path, unified_app_id=preview.unified_app_id)
        store.update(job_id, status="succeeded", finished_at=_utc_now())
    except Exception as exc:
        if settings.git_enabled and not git_pushed and pre_head:
            _rollback_git_change(settings=settings, store=store, job_id=job_id, pre_head=pre_head)
        _job_log(store, job_id, f"ERROR: {exc}")
        store.update(job_id, status="failed", finished_at=_utc_now(), error=str(exc))


def _git_command(settings: AdminSettings) -> list[str]:
    return [
        "git",
        "-c",
        f"safe.directory={settings.repo_root}",
        "-c",
        f"user.name={settings.git_user_name}",
        "-c",
        f"user.email={settings.git_user_email}",
    ]


def _run_git_preflight(*, settings: AdminSettings, store: AdminJobStore, job_id: str) -> str:
    if not (settings.repo_root / ".git").exists():
        raise RuntimeError(f"Git repo not found at {settings.repo_root}. Set ADMIN_REPO_ROOT to the mounted repo.")
    if not settings.github_token:
        raise RuntimeError("ADMIN_GITHUB_TOKEN is required when ADMIN_GIT_ENABLED=1.")
    git = _git_command(settings)
    _job_log(store, job_id, f"GitHub token configured: {'yes' if settings.github_token else 'no'}")
    _job_log(store, job_id, f"Git branch: {settings.git_branch}")
    remote = _run_command(store, job_id, [*git, "remote", "get-url", "origin"], cwd=settings.repo_root)
    _job_log(store, job_id, f"Git remote origin: {_redact_git_remote(remote.stdout.strip())}")
    status_result = _run_command(
        store,
        job_id,
        [*git, "status", "--porcelain", "--", settings.repo_config_path],
        cwd=settings.repo_root,
    )
    if status_result.stdout.strip():
        raise RuntimeError(
            f"{settings.repo_config_path} has uncommitted changes. Roll back or commit them before using the admin UI."
        )
    pre_head = _run_command(store, job_id, [*git, "rev-parse", "HEAD"], cwd=settings.repo_root)
    return pre_head.stdout.strip()


def _run_git_flow(*, settings: AdminSettings, store: AdminJobStore, job_id: str, app_name: str) -> None:
    git = _git_command(settings)
    _run_command(store, job_id, [*git, "status", "--short"], cwd=settings.repo_root)
    _run_command(store, job_id, [*git, "add", settings.repo_config_path], cwd=settings.repo_root)
    message = f"Add tracked game: {app_name}"
    commit = _run_command(
        store,
        job_id,
        [*git, "commit", "-m", message],
        cwd=settings.repo_root,
        allow_return_codes={0, 1},
    )
    if commit.returncode == 1 and "nothing to commit" in (commit.stdout + commit.stderr).lower():
        _job_log(store, job_id, "No git commit created because config was already committed.")
    elif commit.returncode != 0:
        raise RuntimeError(f"git commit failed with exit code {commit.returncode}")
    _run_git_push_with_token(settings=settings, store=store, job_id=job_id, git=git)


def _run_git_push_with_token(
    *,
    settings: AdminSettings,
    store: AdminJobStore,
    job_id: str,
    git: list[str],
) -> None:
    askpass_path = settings.job_dir / f"{job_id}_git_askpass.sh"
    askpass_path.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *Username*) printf '%s\\n' \"x-access-token\" ;;\n"
        "  *) printf '%s\\n' \"$ADMIN_GITHUB_TOKEN\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    askpass_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    env = {
        **os.environ,
        "GIT_ASKPASS": str(askpass_path),
        "GIT_TERMINAL_PROMPT": "0",
        "ADMIN_GITHUB_TOKEN": settings.github_token,
    }
    try:
        _run_command(
            store,
            job_id,
            [*git, "push", "origin", settings.git_branch],
            cwd=settings.repo_root,
            env=env,
        )
    finally:
        askpass_path.unlink(missing_ok=True)


def _rollback_git_change(*, settings: AdminSettings, store: AdminJobStore, job_id: str, pre_head: str) -> None:
    git = _git_command(settings)
    _job_log(store, job_id, f"Rolling back local config/Git state to {pre_head}.")
    try:
        _run_command(store, job_id, [*git, "reset", "--soft", pre_head], cwd=settings.repo_root)
        _run_command(store, job_id, [*git, "restore", "--staged", settings.repo_config_path], cwd=settings.repo_root)
        _run_command(store, job_id, [*git, "restore", settings.repo_config_path], cwd=settings.repo_root)
    except Exception as rollback_error:
        _job_log(store, job_id, f"Rollback failed: {rollback_error}")


def _redact_git_remote(remote: str) -> str:
    if "@" not in remote or "://" not in remote:
        return remote
    scheme, rest = remote.split("://", 1)
    return f"{scheme}://<redacted>@{rest.split('@', 1)[1]}"


def _run_targeted_backfill(*, settings: AdminSettings, store: AdminJobStore, job_id: str, unified_app_id: str) -> None:
    lookback = str(settings.backfill_lookback_days)
    config = str(settings.config_path)
    db = str(settings.db_path)
    _run_command(
        store,
        job_id,
        [
            sys.executable,
            "-m",
            "vn_event_dw.cli",
            "sync-socialdata-posts",
            "--db",
            db,
            "--config",
            config,
            "--lookback-days",
            lookback,
            "--unified-app-id",
            unified_app_id,
        ],
    )
    _run_command(
        store,
        job_id,
        [
            sys.executable,
            "-m",
            "vn_event_dw.cli",
            "diagnose-socialdata-game",
            "--db",
            db,
            "--config",
            config,
            "--lookback-days",
            lookback,
            "--unified-app-id",
            unified_app_id,
            "--limit",
            "10",
            "--fail-on-missing",
        ],
    )
    _run_command(
        store,
        job_id,
        [
            sys.executable,
            "-m",
            "vn_event_dw.cli",
            "sync-sensortower-raw",
            "--config",
            config,
            "--lookback-days",
            lookback,
            "--unified-app-id",
            unified_app_id,
        ],
    )
    _run_command(
        store,
        job_id,
        [sys.executable, "-m", "vn_event_dw.cli", "load-sensortower-raw", "--db", db],
    )
    for month in _target_months():
        _run_command(
            store,
            job_id,
            [
                sys.executable,
                "-m",
                "vn_event_dw.cli",
                "build-unified-events-llm",
                "--db",
                db,
                "--month",
                month,
                "--unified-app-id",
                unified_app_id,
            ],
        )


def _verify_api(*, store: AdminJobStore, job_id: str, db_path: Path, unified_app_id: str) -> None:
    _job_log(store, job_id, f"Verifying DB registration for unified_app_id={unified_app_id}")
    conn = open_connection(db_path)
    try:
        result = fetch_game_detail(conn, unified_app_id=unified_app_id)
    finally:
        conn.close()
    if result is None:
        raise RuntimeError(f"DB verification did not find unified_app_id={unified_app_id}")
    _job_log(store, job_id, f"DB verification passed: {result['app_name']}")


def _run_command(
    store: AdminJobStore,
    job_id: str,
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    allow_return_codes: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    allowed = allow_return_codes or {0}
    command_text = " ".join(command)
    _job_log(store, job_id, f"$ {command_text}")
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if result.stdout:
        _job_log(store, job_id, result.stdout)
    if result.stderr:
        _job_log(store, job_id, result.stderr)
    if result.returncode not in allowed:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {command_text}")
    return result


def _target_months() -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    current = today.strftime("%Y-%m")
    first_day = today.replace(day=1)
    previous_day = first_day.fromordinal(first_day.toordinal() - 1)
    previous = previous_day.strftime("%Y-%m")
    if previous == current:
        return (current,)
    return (previous, current)


def _game_input_from_form(form: dict[str, str]) -> AdminGameInput:
    return AdminGameInput(
        app_name=form.get("app_name", ""),
        fb_page_id=form.get("fb_page_id", ""),
        android_app_id=form.get("android_app_id", ""),
        ios_app_id=form.get("ios_app_id", ""),
        country=form.get("country", "VN"),
        unified_app_id=form.get("unified_app_id", ""),
    )


async def _read_urlencoded_form(request_obj: Request) -> dict[str, str]:
    body = (await request_obj.body()).decode("utf-8", errors="replace")
    parsed = parse.parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _cookie_value(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"vn-event-dw-admin", "sha256").hexdigest()


def _valid_cookie(cookie_value: str, password: str) -> bool:
    return bool(password) and hmac.compare_digest(cookie_value, _cookie_value(password))


def _is_authenticated(request_obj: Request, password: str) -> bool:
    return _valid_cookie(request_obj.cookies.get(ADMIN_COOKIE_NAME, ""), password)


def _job_log(store: AdminJobStore, job_id: str, text: str) -> None:
    store.append_log(job_id, f"[{_utc_now()}] {text}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _html_response(content: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(content, status_code=status_code)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ --ink:#16211f; --muted:#66736f; --line:#d8e1de; --brand:#156f5a; --paper:#fbfaf4; --card:#ffffff; --bad:#ad2f2f; }}
    body {{ margin:0; font-family: Georgia, 'Times New Roman', serif; color:var(--ink); background:linear-gradient(135deg,#f7f2df,#edf7f4); }}
    main {{ max-width:1040px; margin:32px auto; padding:0 20px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:24px; box-shadow:0 18px 60px rgba(27,54,49,.10); margin-bottom:18px; }}
    h1 {{ margin:0 0 8px; font-size:34px; }}
    h2 {{ margin:0 0 16px; font-size:22px; }}
    p {{ color:var(--muted); }}
    label {{ display:block; font-weight:700; margin:12px 0 6px; }}
    input {{ width:100%; box-sizing:border-box; border:1px solid var(--line); border-radius:12px; padding:12px; font:inherit; }}
    button, .button {{ display:inline-block; border:0; border-radius:999px; padding:11px 18px; background:var(--brand); color:white; font-weight:700; text-decoration:none; cursor:pointer; }}
    .ghost {{ background:#eef4f1; color:var(--ink); }}
    .danger {{ color:var(--bad); font-weight:700; }}
    table {{ width:100%; border-collapse:collapse; }}
    th, td {{ text-align:left; border-bottom:1px solid var(--line); padding:10px; vertical-align:top; }}
    code, pre {{ background:#f3f0e6; border-radius:10px; }}
    pre {{ padding:14px; overflow:auto; white-space:pre-wrap; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media (max-width: 720px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>{body}</main>
</body>
</html>"""


def _render_login_page(*, settings: AdminSettings, error: str | None = None) -> str:
    status = "" if settings.enabled else "<p class='danger'>Admin UI is disabled.</p>"
    error_html = f"<p class='danger'>{html.escape(error)}</p>" if error else ""
    return _page(
        "VN Event DW Admin",
        f"""
        <section class="card">
          <h1>VN Event DW Admin</h1>
          <p>Add tracked games without touching the VM terminal.</p>
          {status}
          {error_html}
          <form method="post" action="{ADMIN_ROUTE_PREFIX}/login">
            <label>Password</label>
            <input type="password" name="password" autofocus>
            <p><button type="submit">Log in</button></p>
          </form>
        </section>
        """,
    )


def _render_games_page(
    *,
    settings: AdminSettings,
    payload: dict[str, Any],
    latest_job: dict[str, Any] | None,
    form: dict[str, str] | None = None,
    error: str | None = None,
) -> str:
    mappings = [item for item in payload.get("app_mappings", []) if isinstance(item, dict)]
    rows = "\n".join(
        f"<tr><td>{html.escape(str(item.get('app_name', '')))}</td><td><code>{html.escape(str(item.get('unified_app_id', '')))}</code></td><td>{html.escape(str(item.get('fb_page_id', '')))}</td></tr>"
        for item in mappings
    )
    latest_html = ""
    if latest_job:
        status = str(latest_job["status"])
        if status == "manually_resolved":
            status_label = "manually resolved"
        else:
            status_label = status
        latest_html = (
            f"<p>Latest job: <a class='button ghost' href='{ADMIN_ROUTE_PREFIX}/jobs/{html.escape(str(latest_job['job_id']))}'>"
            f"{html.escape(status_label)} - {html.escape(str(latest_job['title']))}</a></p>"
        )
    values = form or {}
    error_html = f"<p class='danger'>{html.escape(error)}</p>" if error else ""
    return _page(
        "Tracked Games Admin",
        f"""
        <section class="card">
          <h1>Tracked Games</h1>
          <p>Config source: <code>{html.escape(str(settings.config_path))}</code></p>
          {latest_html}
          <form method="post" action="{ADMIN_ROUTE_PREFIX}/logout"><button class="ghost" type="submit">Log out</button></form>
        </section>
        <section class="card">
          <h2>Add New Game</h2>
          {error_html}
          <form method="post" action="{ADMIN_ROUTE_PREFIX}/games/preview">
            <div class="grid">
              <div><label>Game name</label><input name="app_name" value="{html.escape(values.get('app_name', ''))}" required></div>
              <div><label>Facebook page ID</label><input name="fb_page_id" value="{html.escape(values.get('fb_page_id', ''))}" required></div>
              <div><label>Android SensorTower app/package ID</label><input name="android_app_id" value="{html.escape(values.get('android_app_id', ''))}" required></div>
              <div><label>iOS SensorTower app ID</label><input name="ios_app_id" value="{html.escape(values.get('ios_app_id', ''))}" required></div>
              <div><label>Country</label><input name="country" value="{html.escape(values.get('country', 'VN'))}" required></div>
              <div><label>Unified app ID (optional)</label><input name="unified_app_id" value="{html.escape(values.get('unified_app_id', ''))}"></div>
            </div>
            <p><button type="submit">Preview Change</button></p>
          </form>
        </section>
        <section class="card">
          <h2>Current Games ({len(mappings)})</h2>
          <table><thead><tr><th>Game</th><th>Unified App ID</th><th>FB Page ID</th></tr></thead><tbody>{rows}</tbody></table>
        </section>
        """,
    )


def _render_preview_page(*, settings: AdminSettings, preview: Any, form: dict[str, str]) -> str:
    hidden = "\n".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
        for key, value in form.items()
    )
    preview_json = json.dumps(
        {
            "app_mapping": preview.app_mapping,
            "sensortower_targets": list(preview.sensortower_targets),
        },
        ensure_ascii=False,
        indent=2,
    )
    return _page(
        "Preview New Game",
        f"""
        <section class="card">
          <h1>Preview Change</h1>
          <p>This will add <strong>{html.escape(preview.app_name)}</strong> and then run a targeted {settings.backfill_lookback_days}-day backfill.</p>
          <pre>{html.escape(preview_json)}</pre>
          <form method="post" action="{ADMIN_ROUTE_PREFIX}/games/apply">
            {hidden}
            <button type="submit">Apply, Commit, Push, And Backfill</button>
            <a class="button ghost" href="{ADMIN_ROUTE_PREFIX}/games">Cancel</a>
          </form>
        </section>
        """,
    )


def _render_job_page(job: dict[str, Any]) -> str:
    log = "\n".join(str(item) for item in job.get("log", []))
    refresh = "<script>setTimeout(function(){ window.location.reload(); }, 10000);</script>" if job.get("status") in {"queued", "running"} else ""
    resolution = job.get("manual_resolution") if isinstance(job.get("manual_resolution"), dict) else None
    resolution_html = ""
    if resolution:
        resolution_html = (
            "<p><strong>Manual resolution:</strong> "
            f"{html.escape(str(resolution.get('resolved_at', '')))}"
            f" - {html.escape(str(resolution.get('note', '')))}</p>"
        )
    resolve_html = ""
    if job.get("status") == "failed":
        resolve_html = """
          <form method="post" action="{ADMIN_ROUTE_PREFIX}/jobs/{job_id}/resolve">
            <label>Manual resolution note</label>
            <input name="note" placeholder="Example: Finished targeted backfill manually from VM terminal.">
            <p><button type="submit">Mark Manually Resolved</button></p>
          </form>
        """.format(job_id=html.escape(str(job.get("job_id", ""))))
    return _page(
        "Admin Job",
        f"""
        {refresh}
        <section class="card">
          <h1>{html.escape(str(job.get('title', 'Admin job')))}</h1>
          <p>Status: <strong>{html.escape(str(job.get('status', 'unknown')))}</strong></p>
          <p>Created: {html.escape(str(job.get('created_at')))} | Started: {html.escape(str(job.get('started_at')))} | Finished: {html.escape(str(job.get('finished_at')))}</p>
          {resolution_html}
          {resolve_html}
          <p><a class="button ghost" href="{ADMIN_ROUTE_PREFIX}/games">Back to games</a></p>
        </section>
        <section class="card">
          <h2>Log</h2>
          <pre>{html.escape(log)}</pre>
        </section>
        """,
    )
