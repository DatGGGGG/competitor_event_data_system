from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from vn_event_dw.admin import AdminJobStore, load_admin_settings
from vn_event_dw import admin
from vn_event_dw.api import create_app
from vn_event_dw.etl import init_db, open_connection


class AdminApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "warehouse.db"
        self.config_path = self.root / "config.json"
        self.job_dir = self.root / "admin_jobs"
        self.config_path.write_text(
            json.dumps(
                {
                    "rule_keywords": ["release"],
                    "app_mappings": [
                        {
                            "unified_app_id": "existing_app",
                            "fb_page_id": "existing_page",
                            "app_name": "Existing Game",
                            "is_active": True,
                        }
                    ],
                    "sensortower_targets": [
                        {
                            "unified_app_id": "existing_app",
                            "os": "android",
                            "app_id": "com.existing.game",
                            "country": "VN",
                        },
                        {
                            "unified_app_id": "existing_app",
                            "os": "ios",
                            "app_id": "123456789",
                            "country": "VN",
                        },
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        conn = open_connection(self.db_path)
        try:
            init_db(conn)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _client(self) -> TestClient:
        env = {
            "ADMIN_UI_ENABLED": "1",
            "ADMIN_PASSWORD": "secret",
            "ADMIN_SESSION_SECRET": "test-admin-session-secret",
            "ADMIN_COOKIE_SECURE": "0",
            "ADMIN_CONFIG_PATH": str(self.config_path),
            "ADMIN_JOB_DIR": str(self.job_dir),
            "ADMIN_GIT_ENABLED": "0",
        }
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app(db_path=self.db_path))

    def _csrf_token(self, client: TestClient) -> str:
        response = client.get("/api/events/admin/games")
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(match)
        assert match is not None
        return match.group(1)

    def test_admin_games_rejects_unauthenticated_request(self) -> None:
        client = self._client()

        response = client.get("/api/events/admin/games")

        self.assertEqual(response.status_code, 401)

    def test_correct_password_allows_access(self) -> None:
        client = self._client()

        login = client.post("/api/events/admin/login", data="password=secret", headers={"content-type": "application/x-www-form-urlencoded"})
        response = client.get("/api/events/admin/games")

        self.assertEqual(login.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Existing Game", response.text)

    def test_admin_password_flow_does_not_require_read_api_key(self) -> None:
        env = {
            "ADMIN_UI_ENABLED": "1",
            "ADMIN_PASSWORD": "secret",
            "ADMIN_SESSION_SECRET": "test-admin-session-secret",
            "ADMIN_COOKIE_SECURE": "0",
            "ADMIN_CONFIG_PATH": str(self.config_path),
            "ADMIN_JOB_DIR": str(self.job_dir),
            "ADMIN_GIT_ENABLED": "0",
            "VN_EVENT_DW_API_KEY": "read-api-key",
        }
        with patch.dict(os.environ, env, clear=False):
            client = TestClient(create_app(db_path=self.db_path))
            login = client.post(
                "/api/events/admin/login",
                data="password=secret",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            response = client.get("/api/events/admin/games")

        self.assertEqual(login.status_code, 200)
        self.assertEqual(response.status_code, 200)

    def test_add_game_preview_returns_expected_diff(self) -> None:
        client = self._client()
        client.post("/api/events/admin/login", data="password=secret", headers={"content-type": "application/x-www-form-urlencoded"})
        csrf_token = self._csrf_token(client)

        response = client.post(
            "/api/events/admin/games/preview",
            data=(
                "app_name=Preview+Game&"
                "fb_page_id=preview_page&"
                "android_app_id=com.preview.game&"
                "ios_app_id=987654321&"
                f"country=VN&csrf_token={csrf_token}"
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Preview Game", response.text)
        self.assertIn("com.preview.game", response.text)
        self.assertIn("987654321", response.text)

    def test_mutating_form_rejects_missing_csrf_token(self) -> None:
        client = self._client()
        client.post("/api/events/admin/login", data="password=secret", headers={"content-type": "application/x-www-form-urlencoded"})

        response = client.post(
            "/api/events/admin/games/preview",
            data="app_name=Preview+Game&fb_page_id=preview_page&android_app_id=com.preview.game&ios_app_id=987654321&country=VN",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        self.assertEqual(response.status_code, 403)

    def test_portal_exchange_creates_workspace_scoped_session(self) -> None:
        env = {
            "ADMIN_UI_ENABLED": "1",
            "ADMIN_AUTH_MODE": "portal",
            "ADMIN_SESSION_SECRET": "test-admin-session-secret",
            "ADMIN_COOKIE_SECURE": "0",
            "ADMIN_ROUTE_PREFIX": "/workspaces/tracked-games/events",
            "PORTAL_GRANT_CONSUME_URL": "http://portal.test/api/v1/internal/workspace-grants/consume",
            "EVENT_WORKSPACE_SERVICE_TOKEN": "workspace-secret",
            "ADMIN_CONFIG_PATH": str(self.config_path),
            "ADMIN_JOB_DIR": str(self.job_dir),
            "ADMIN_GIT_ENABLED": "0",
        }

        class PortalResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return None

            def read(self):
                return b'{"user_id":4,"email":"admin@garena.com","display_name":"Portal Admin","role":"admin"}'

        with patch.dict(os.environ, env, clear=False), patch("vn_event_dw.admin.request.urlopen", return_value=PortalResponse()) as open_mock:
            client = TestClient(create_app(db_path=self.db_path))
            response = client.get("/workspaces/tracked-games/events/auth/exchange?code=one-time-code", follow_redirects=False)
            landing = client.get("/workspaces/tracked-games/events/games")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/workspaces/tracked-games/events/games")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertIn("Path=/workspaces/tracked-games/events", response.headers["set-cookie"])
        self.assertEqual(landing.status_code, 200)
        self.assertIn("Existing Game", landing.text)
        outbound = open_mock.call_args.args[0]
        self.assertEqual(outbound.get_header("Authorization"), "Bearer workspace-secret")

    def test_admin_settings_include_default_git_identity(self) -> None:
        env = {
            "ADMIN_CONFIG_PATH": str(self.config_path),
            "ADMIN_JOB_DIR": str(self.job_dir),
        }
        with patch.dict(os.environ, env, clear=False):
            settings = load_admin_settings(db_path=self.db_path)

        self.assertEqual(settings.git_user_name, "VN Event DW Admin")
        self.assertEqual(settings.git_user_email, "vn-event-dw-admin@localhost")

    def test_git_preflight_requires_github_token_before_config_write(self) -> None:
        repo_root = self.root / "repo"
        (repo_root / ".git").mkdir(parents=True)
        env = {
            "ADMIN_CONFIG_PATH": str(self.config_path),
            "ADMIN_JOB_DIR": str(self.job_dir),
            "ADMIN_REPO_ROOT": str(repo_root),
            "ADMIN_REPO_CONFIG_PATH": "examples/config.json",
            "ADMIN_GIT_ENABLED": "1",
            "ADMIN_GITHUB_TOKEN": "",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = load_admin_settings(db_path=self.db_path)
        store = AdminJobStore(self.job_dir)
        job_id = store.create(title="Add tracked game: Token Test", metadata={})

        with self.assertRaisesRegex(RuntimeError, "ADMIN_GITHUB_TOKEN"):
            admin._run_git_preflight(settings=settings, store=store, job_id=job_id)

    def test_git_push_uses_token_without_logging_it(self) -> None:
        env = {
            "ADMIN_CONFIG_PATH": str(self.config_path),
            "ADMIN_JOB_DIR": str(self.job_dir),
            "ADMIN_REPO_ROOT": str(self.root),
            "ADMIN_GITHUB_TOKEN": "super-secret-token",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = load_admin_settings(db_path=self.db_path)
        store = AdminJobStore(self.job_dir)
        job_id = store.create(title="Add tracked game: Push Test", metadata={})

        completed = admin.subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")
        with patch("vn_event_dw.admin.subprocess.run", return_value=completed) as run_mock:
            admin._run_git_push_with_token(settings=settings, store=store, job_id=job_id, git=["git"])

        logged_job = store.read(job_id)
        rendered_log = "\n".join(logged_job["log"])
        self.assertIn("git push origin main", rendered_log)
        self.assertNotIn("super-secret-token", rendered_log)
        self.assertEqual(run_mock.call_args.kwargs["env"]["ADMIN_GITHUB_TOKEN"], "super-secret-token")

    def test_targeted_backfill_runs_socialdata_diagnostic_before_expensive_steps(self) -> None:
        env = {
            "ADMIN_CONFIG_PATH": str(self.config_path),
            "ADMIN_JOB_DIR": str(self.job_dir),
            "ADMIN_BACKFILL_LOOKBACK_DAYS": "30",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = load_admin_settings(db_path=self.db_path)
        store = AdminJobStore(self.job_dir)
        job_id = store.create(title="Add tracked game: Diagnostic Test", metadata={})
        commands: list[list[str]] = []

        def fake_run_command(*args, **kwargs):
            commands.append(args[2])
            return admin.subprocess.CompletedProcess(args=args[2], returncode=0, stdout="", stderr="")

        with patch("vn_event_dw.admin._run_command", side_effect=fake_run_command):
            admin._run_targeted_backfill(
                settings=settings,
                store=store,
                job_id=job_id,
                unified_app_id="new_game",
            )

        command_names = [command[3] for command in commands]
        self.assertEqual(command_names[:2], ["sync-socialdata-posts", "diagnose-socialdata-game"])
        self.assertIn("--fail-on-missing", commands[1])
        self.assertLess(command_names.index("diagnose-socialdata-game"), command_names.index("sync-sensortower-raw"))

    def test_failed_job_can_be_marked_manually_resolved(self) -> None:
        client = self._client()
        client.post("/api/events/admin/login", data="password=secret", headers={"content-type": "application/x-www-form-urlencoded"})
        csrf_token = self._csrf_token(client)
        self.job_dir.mkdir(parents=True, exist_ok=True)
        job_id = "job_failed"
        (self.job_dir / "latest.txt").write_text(job_id + "\n", encoding="utf-8")
        (self.job_dir / f"{job_id}.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "title": "Add tracked game: Example",
                    "status": "failed",
                    "metadata": {},
                    "created_at": "2026-08-05T00:00:00+00:00",
                    "started_at": "2026-08-05T00:00:00+00:00",
                    "finished_at": "2026-08-05T00:01:00+00:00",
                    "error": "boom",
                    "log": ["failed"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        response = client.post(
            f"/api/events/admin/jobs/{job_id}/resolve",
            data=f"note=Finished+from+terminal&csrf_token={csrf_token}",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        job_page = client.get(f"/api/events/admin/jobs/{job_id}")
        games_page = client.get("/api/events/admin/games")

        self.assertEqual(response.status_code, 200)
        self.assertIn("manually_resolved", job_page.text)
        self.assertIn("Finished from terminal", job_page.text)
        self.assertIn("manually resolved - Add tracked game: Example", games_page.text)


if __name__ == "__main__":
    unittest.main()
