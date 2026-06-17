from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import uvicorn

from .api import create_app
from .config import default_sensortower_raw_dir, load_pipeline_config
from .etl import open_connection, init_db, reload_fb_posts, run_etl, summarize_db
from .environment import load_environment_files
from .fb_event_pipeline import (
    build_fb_event_detection,
    build_fb_event_objects,
    build_fb_events,
    build_fb_events_with_llm_merge,
    build_fb_raw_events,
    build_unified_events_with_llm_merge,
    preview_fb_event_dedup,
    rerun_unified_step5,
)
from .ngrok_service import serve_api_with_ngrok
from .sensortower_raw import (
    SensorTowerClient,
    extract_sensortower_raw,
    load_pending_sensortower_raw_manifests,
    load_sensortower_raw_manifest,
    resolve_raw_window,
    resolve_tracked_targets,
)
from .socialdata import SocialDataClient, read_graphql_variables, read_query_text
from .socialdata_sync import DEFAULT_SOCIALDATA_PAGE_SIZE, sync_socialdata_posts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vn-event-dw", description="Mini event data warehouse ETL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Create the warehouse schema")
    init_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")

    run_parser = subparsers.add_parser("run", help="Run the full ETL pipeline")
    run_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    run_parser.add_argument("--config", required=True, type=Path, help="JSON config path")
    run_parser.add_argument("--input-dir", required=True, type=Path, help="Directory with CSV inputs")

    reload_fb_parser = subparsers.add_parser(
        "reload-fb-posts",
        help="Reload only the FB post landing tables from the FB CSV folder.",
    )
    reload_fb_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    reload_fb_parser.add_argument("--config", required=True, type=Path, help="JSON config path")
    reload_fb_parser.add_argument(
        "--input-dir",
        required=True,
        type=Path,
        help="Directory containing the fb_posts folder or legacy fb_posts.csv.",
    )

    detect_fb_parser = subparsers.add_parser(
        "build-fb-event-detection",
        help="Run LLM binary event detection for Facebook posts.",
    )
    detect_fb_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    detect_fb_parser.add_argument("--fb-page-id", default=None, help="Optional FB page id scope.")
    detect_fb_parser.add_argument("--game-name", default=None, help="Optional canonical game name scope.")
    detect_fb_parser.add_argument("--page-name", default=None, help="Optional page name scope.")
    detect_fb_parser.add_argument("--limit", type=int, default=None, help="Optional max posts to process.")

    extract_fb_parser = subparsers.add_parser(
        "build-fb-event-objects",
        help="Run LLM event object extraction for detected Facebook event posts.",
    )
    extract_fb_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    extract_fb_parser.add_argument("--fb-page-id", default=None, help="Optional FB page id scope.")
    extract_fb_parser.add_argument("--game-name", default=None, help="Optional canonical game name scope.")
    extract_fb_parser.add_argument("--page-name", default=None, help="Optional page name scope.")
    extract_fb_parser.add_argument("--limit", type=int, default=None, help="Optional max posts to process.")

    raw_events_fb_parser = subparsers.add_parser(
        "build-fb-raw-events",
        help="Run FB detection + extraction only, producing non-deduplicated raw events.",
    )
    raw_events_fb_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    raw_events_fb_parser.add_argument("--fb-page-id", default=None, help="Optional FB page id scope.")
    raw_events_fb_parser.add_argument("--game-name", default=None, help="Optional canonical game name scope.")
    raw_events_fb_parser.add_argument("--page-name", default=None, help="Optional page name scope.")
    raw_events_fb_parser.add_argument("--limit", type=int, default=None, help="Optional max posts to process.")

    dedup_fb_parser = subparsers.add_parser(
        "build-fb-events",
        help="Deduplicate extracted Facebook event objects into canonical FB events.",
    )
    dedup_fb_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    dedup_fb_parser.add_argument("--fb-page-id", default=None, help="Optional FB page id scope.")
    dedup_fb_parser.add_argument("--game-name", default=None, help="Optional canonical game name scope.")
    dedup_fb_parser.add_argument("--page-name", default=None, help="Optional page name scope.")

    llm_merge_fb_parser = subparsers.add_parser(
        "build-fb-events-llm",
        help="Merge and deduplicate raw Facebook event objects into canonical FB events with an LLM.",
    )
    llm_merge_fb_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    llm_merge_fb_parser.add_argument("--fb-page-id", default=None, help="Optional FB page id scope.")
    llm_merge_fb_parser.add_argument("--game-name", default=None, help="Optional canonical game name scope.")
    llm_merge_fb_parser.add_argument("--page-name", default=None, help="Optional page name scope.")
    llm_merge_fb_parser.add_argument("--limit", type=int, default=None, help="Optional max raw event objects to merge.")

    unified_merge_parser = subparsers.add_parser(
        "build-unified-events-llm",
        help="Build final unified cross-source events directly from raw FB posts plus ST deterministic events.",
    )
    unified_merge_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    unified_merge_parser.add_argument("--unified-app-id", default=None, help="Optional unified_app_id scope.")
    unified_merge_parser.add_argument("--month", default=None, help="Optional YYYY-MM scope.")
    unified_merge_parser.add_argument(
        "--limit-source-rows",
        type=int,
        default=None,
        help="Optional max normalized source rows to merge, for testing only.",
    )

    rerun_step5_parser = subparsers.add_parser(
        "rerun-unified-step5",
        help="Rerun only the final step-5 unified consolidation from saved step-3 and step-4 candidate snapshots.",
    )
    rerun_step5_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    rerun_step5_parser.add_argument("--unified-app-id", required=True, help="Scoped unified_app_id.")
    rerun_step5_parser.add_argument("--month", required=True, help="Scoped YYYY-MM month.")
    rerun_step5_parser.add_argument(
        "--source-run-id",
        default=None,
        help="Optional saved full-build run_id to reuse as the step-3/4 snapshot source.",
    )

    serve_api_parser = subparsers.add_parser(
        "serve-api",
        help="Serve the read-only warehouse HTTP API.",
    )
    serve_api_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    serve_api_parser.add_argument("--host", default="127.0.0.1", help="Bind host. Defaults to 127.0.0.1.")
    serve_api_parser.add_argument("--port", type=int, default=8000, help="Bind port. Defaults to 8000.")

    ngrok_api_parser = subparsers.add_parser(
        "serve-api-ngrok",
        help="Serve the read-only warehouse HTTP API and expose it through a temporary ngrok tunnel.",
    )
    ngrok_api_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    ngrok_api_parser.add_argument("--host", default="127.0.0.1", help="Bind host. Defaults to 127.0.0.1.")
    ngrok_api_parser.add_argument("--port", type=int, default=8765, help="Bind port. Defaults to 8765.")
    ngrok_api_parser.add_argument(
        "--ngrok-authtoken",
        default=None,
        help="Optional ngrok authtoken. Falls back to NGROK_AUTHTOKEN if omitted.",
    )
    ngrok_api_parser.add_argument(
        "--ngrok-domain",
        default=None,
        help="Optional reserved ngrok domain, for example api-name.ngrok.app. Falls back to NGROK_DOMAIN if omitted.",
    )

    preview_fb_parser = subparsers.add_parser(
        "preview-fb-event-dedup",
        help="Preview how many FB event-object pairs will be rule-merged, rule-rejected, or sent to the LLM judge.",
    )
    preview_fb_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    preview_fb_parser.add_argument("--fb-page-id", default=None, help="Optional FB page id scope.")
    preview_fb_parser.add_argument("--game-name", default=None, help="Optional canonical game name scope.")
    preview_fb_parser.add_argument("--page-name", default=None, help="Optional page name scope.")

    raw_parser = subparsers.add_parser(
        "sync-sensortower-raw",
        help="Fetch raw SensorTower JSON snapshots for the tracked unified_app_id registry.",
    )
    raw_parser.add_argument("--config", required=True, type=Path, help="JSON config path")
    raw_window = raw_parser.add_mutually_exclusive_group(required=False)
    raw_window.add_argument("--since", type=date.fromisoformat, default=None, help="Start date in YYYY-MM-DD format.")
    raw_window.add_argument("--lookback-days", type=int, default=None, help="Rolling window in days.")
    raw_parser.add_argument("--until", type=date.fromisoformat, default=None, help="Optional end date in YYYY-MM-DD.")
    raw_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for raw SensorTower snapshots. Defaults to data_ingest/sensortower/raw.",
    )
    raw_parser.add_argument(
        "--unified-app-id",
        dest="unified_app_ids",
        action="append",
        default=None,
        help="Optional tracked unified_app_id to limit extraction. Repeatable.",
    )

    load_raw_parser = subparsers.add_parser(
        "load-sensortower-raw",
        help="Load pending raw SensorTower manifests and rebuild deterministic ST update events.",
    )
    load_raw_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    load_raw_parser.add_argument(
        "--input-dir",
        default=None,
        help="Root directory containing raw SensorTower runs. Defaults to data_ingest/sensortower/raw.",
    )
    load_raw_parser.add_argument(
        "--manifest-path",
        default=None,
        help="Optional specific manifest.json to load instead of scanning the raw root.",
    )
    load_raw_parser.add_argument("--force", action="store_true", help="Reload a manifest even if it was already loaded.")

    summary_parser = subparsers.add_parser("summary", help="Print warehouse table counts")
    summary_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")

    socialdata_auth_parser = subparsers.add_parser(
        "socialdata-auth-check",
        help="Verify Socialdata authentication by calling a minimal GraphQL query.",
    )
    socialdata_auth_parser.add_argument(
        "--socialdata-base-url",
        default=None,
        help="Optional Socialdata base URL. Defaults to SOCIALDATA_BASE_URL or https://socialdata.garena.vn.",
    )
    socialdata_auth_parser.add_argument(
        "--usession",
        default=None,
        help="Optional existing Socialdata usession cookie value. Falls back to SOCIALDATA_USESSION.",
    )
    socialdata_auth_parser.add_argument(
        "--google-access-token",
        default=None,
        help="Optional Google access token used to exchange for a Socialdata usession cookie.",
    )
    socialdata_auth_parser.add_argument(
        "--google-service-account-file",
        default=None,
        help=(
            "Optional Google service-account JSON credential file used to mint a short-lived access token "
            "for Socialdata auth. Falls back to SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE."
        ),
    )
    socialdata_auth_parser.add_argument(
        "--google-scope",
        action="append",
        default=None,
        help=(
            "Optional Google OAuth scope for service-account token minting. Repeatable. "
            "Defaults to SOCIALDATA_GOOGLE_SCOPES or https://www.googleapis.com/auth/userinfo.email."
        ),
    )
    socialdata_auth_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Optional request timeout. Defaults to SOCIALDATA_TIMEOUT_SECONDS or 60.",
    )

    socialdata_mint_token_parser = subparsers.add_parser(
        "socialdata-mint-google-access-token",
        help="Mint a Google access token from a service-account JSON file for manual Socialdata auth debugging.",
    )
    socialdata_mint_token_parser.add_argument(
        "--google-service-account-file",
        default=None,
        help=(
            "Optional Google service-account JSON credential file used to mint the token. "
            "Falls back to SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE."
        ),
    )
    socialdata_mint_token_parser.add_argument(
        "--socialdata-base-url",
        default=None,
        help="Optional Socialdata base URL. Included for config consistency; not required to mint the token.",
    )
    socialdata_mint_token_parser.add_argument(
        "--google-scope",
        action="append",
        default=None,
        help=(
            "Optional Google OAuth scope for service-account token minting. Repeatable. "
            "Defaults to SOCIALDATA_GOOGLE_SCOPES or https://www.googleapis.com/auth/userinfo.email."
        ),
    )
    socialdata_mint_token_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Optional request timeout. Defaults to SOCIALDATA_TIMEOUT_SECONDS or 60.",
    )
    socialdata_mint_token_parser.add_argument(
        "--token-only",
        action="store_true",
        help="Print only the access token, with no JSON wrapper.",
    )
    socialdata_mint_token_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the output.",
    )

    socialdata_debug_exchange_parser = subparsers.add_parser(
        "socialdata-debug-token-exchange",
        help="Mint or reuse a Google access token, call the Socialdata callback, and print explicit debug output.",
    )
    socialdata_debug_exchange_parser.add_argument(
        "--socialdata-base-url",
        default=None,
        help="Optional Socialdata base URL. Defaults to SOCIALDATA_BASE_URL or https://socialdata.garena.vn.",
    )
    socialdata_debug_exchange_parser.add_argument(
        "--google-access-token",
        default=None,
        help="Optional already-minted Google access token to reuse for the callback test.",
    )
    socialdata_debug_exchange_parser.add_argument(
        "--google-service-account-file",
        default=None,
        help=(
            "Optional Google service-account JSON credential file used to mint the token. "
            "Falls back to SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE."
        ),
    )
    socialdata_debug_exchange_parser.add_argument(
        "--google-scope",
        action="append",
        default=None,
        help=(
            "Optional Google OAuth scope for service-account token minting. Repeatable. "
            "Defaults to SOCIALDATA_GOOGLE_SCOPES or https://www.googleapis.com/auth/userinfo.email."
        ),
    )
    socialdata_debug_exchange_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Optional request timeout. Defaults to SOCIALDATA_TIMEOUT_SECONDS or 60.",
    )
    socialdata_debug_exchange_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the JSON response.",
    )

    socialdata_graphql_parser = subparsers.add_parser(
        "socialdata-graphql",
        help="Run an arbitrary authenticated Socialdata GraphQL query.",
    )
    socialdata_graphql_parser.add_argument(
        "--socialdata-base-url",
        default=None,
        help="Optional Socialdata base URL. Defaults to SOCIALDATA_BASE_URL or https://socialdata.garena.vn.",
    )
    socialdata_graphql_parser.add_argument(
        "--usession",
        default=None,
        help="Optional existing Socialdata usession cookie value. Falls back to SOCIALDATA_USESSION.",
    )
    socialdata_graphql_parser.add_argument(
        "--google-access-token",
        default=None,
        help="Optional Google access token used to exchange for a Socialdata usession cookie.",
    )
    socialdata_graphql_parser.add_argument(
        "--google-service-account-file",
        default=None,
        help=(
            "Optional Google service-account JSON credential file used to mint a short-lived access token "
            "for Socialdata auth. Falls back to SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE."
        ),
    )
    socialdata_graphql_parser.add_argument(
        "--google-scope",
        action="append",
        default=None,
        help=(
            "Optional Google OAuth scope for service-account token minting. Repeatable. "
            "Defaults to SOCIALDATA_GOOGLE_SCOPES or https://www.googleapis.com/auth/userinfo.email."
        ),
    )
    socialdata_graphql_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Optional request timeout. Defaults to SOCIALDATA_TIMEOUT_SECONDS or 60.",
    )
    socialdata_graphql_parser.add_argument("--query", default=None, help="Inline GraphQL query text.")
    socialdata_graphql_parser.add_argument("--query-file", type=Path, default=None, help="Path to a GraphQL query file.")
    socialdata_graphql_parser.add_argument(
        "--variables-json",
        default=None,
        help="Optional JSON object string for GraphQL variables.",
    )
    socialdata_graphql_parser.add_argument(
        "--variables-file",
        type=Path,
        default=None,
        help="Optional JSON file containing GraphQL variables.",
    )
    socialdata_graphql_parser.add_argument(
        "--operation-name",
        default=None,
        help="Optional GraphQL operation name.",
    )
    socialdata_graphql_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the JSON response.",
    )

    socialdata_introspect_parser = subparsers.add_parser(
        "socialdata-introspect",
        help="Run GraphQL schema introspection against Socialdata.",
    )
    socialdata_introspect_parser.add_argument(
        "--socialdata-base-url",
        default=None,
        help="Optional Socialdata base URL. Defaults to SOCIALDATA_BASE_URL or https://socialdata.garena.vn.",
    )
    socialdata_introspect_parser.add_argument(
        "--usession",
        default=None,
        help="Optional existing Socialdata usession cookie value. Falls back to SOCIALDATA_USESSION.",
    )
    socialdata_introspect_parser.add_argument(
        "--google-access-token",
        default=None,
        help="Optional Google access token used to exchange for a Socialdata usession cookie.",
    )
    socialdata_introspect_parser.add_argument(
        "--google-service-account-file",
        default=None,
        help=(
            "Optional Google service-account JSON credential file used to mint a short-lived access token "
            "for Socialdata auth. Falls back to SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE."
        ),
    )
    socialdata_introspect_parser.add_argument(
        "--google-scope",
        action="append",
        default=None,
        help=(
            "Optional Google OAuth scope for service-account token minting. Repeatable. "
            "Defaults to SOCIALDATA_GOOGLE_SCOPES or https://www.googleapis.com/auth/userinfo.email."
        ),
    )
    socialdata_introspect_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Optional request timeout. Defaults to SOCIALDATA_TIMEOUT_SECONDS or 60.",
    )
    socialdata_introspect_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the introspection JSON response.",
    )

    socialdata_sync_parser = subparsers.add_parser(
        "sync-socialdata-posts",
        help="Incrementally load FB post metrics from Socialdata into raw_fb_posts.",
    )
    socialdata_sync_parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    socialdata_sync_parser.add_argument("--config", required=True, type=Path, help="JSON config path")
    socialdata_sync_parser.add_argument(
        "--app-slug",
        default=None,
        help="Socialdata team/app slug. Defaults to SOCIALDATA_APP_SLUG or srcvn.",
    )
    socialdata_sync_parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="Optional UTC date cutoff in YYYY-MM-DD format. Overrides --lookback-days.",
    )
    socialdata_sync_parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="Rolling overlap window in days. Defaults to 10 when --since is omitted.",
    )
    socialdata_sync_parser.add_argument(
        "--unified-app-id",
        dest="unified_app_ids",
        action="append",
        default=None,
        help="Optional unified_app_id filter. Repeatable.",
    )
    socialdata_sync_parser.add_argument(
        "--per-page",
        type=int,
        default=DEFAULT_SOCIALDATA_PAGE_SIZE,
        help="Socialdata page size for listPost/listChannel requests. Defaults to 100.",
    )
    socialdata_sync_parser.add_argument(
        "--socialdata-base-url",
        default=None,
        help="Optional Socialdata base URL. Defaults to SOCIALDATA_BASE_URL or https://socialdata.garena.vn.",
    )
    socialdata_sync_parser.add_argument(
        "--usession",
        default=None,
        help="Optional existing Socialdata usession cookie value. Falls back to SOCIALDATA_USESSION.",
    )
    socialdata_sync_parser.add_argument(
        "--google-access-token",
        default=None,
        help="Optional Google access token used to exchange for a Socialdata usession cookie.",
    )
    socialdata_sync_parser.add_argument(
        "--google-service-account-file",
        default=None,
        help=(
            "Optional Google service-account JSON credential file used to mint a short-lived access token "
            "for Socialdata auth. Falls back to SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE."
        ),
    )
    socialdata_sync_parser.add_argument(
        "--google-scope",
        action="append",
        default=None,
        help=(
            "Optional Google OAuth scope for service-account token minting. Repeatable. "
            "Defaults to SOCIALDATA_GOOGLE_SCOPES or https://www.googleapis.com/auth/userinfo.email."
        ),
    )
    socialdata_sync_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Optional request timeout. Defaults to SOCIALDATA_TIMEOUT_SECONDS or 60.",
    )

    return parser


def _load_sensortower_token() -> str:
    token = os.getenv("SENSOR_TOWER_AUTH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SENSOR_TOWER_AUTH_TOKEN is missing.")
    return token


def _build_socialdata_client(args: argparse.Namespace) -> SocialDataClient:
    return SocialDataClient(
        base_url=getattr(args, "socialdata_base_url", None),
        usession=getattr(args, "usession", None),
        google_access_token=getattr(args, "google_access_token", None),
        google_service_account_file=getattr(args, "google_service_account_file", None),
        google_scopes=getattr(args, "google_scope", None),
        timeout_seconds=getattr(args, "timeout_seconds", None),
    )


def _emit_json_output(payload: dict[str, object], *, output_path: Path | None = None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_path is not None:
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote JSON response to {output_path}")
        return
    print(rendered)


def run_sensortower_raw_extract(
    *,
    config_path: Path,
    since: date | None,
    until: date | None,
    lookback_days: int | None,
    output_dir: str | None,
    unified_app_ids: list[str] | None,
) -> None:
    config = load_pipeline_config(config_path)
    targets = resolve_tracked_targets(config, unified_app_ids)
    if not targets:
        raise RuntimeError("No SensorTower targets matched the requested unified_app_ids.")

    window = resolve_raw_window(
        since=since,
        until=until,
        lookback_days=lookback_days,
    )
    client = SensorTowerClient(
        base_url=os.getenv("SENSOR_TOWER_BASE_URL", "https://api.sensortower.com").rstrip("/"),
        auth_token=_load_sensortower_token(),
    )
    summary = extract_sensortower_raw(
        client=client,
        targets=targets,
        window=window,
        output_dir=Path(output_dir) if output_dir else default_sensortower_raw_dir(),
    )
    print(
        "sensortower_raw_extract: "
        f"run_id={summary.run_id} "
        f"snapshot_count={summary.snapshot_count} "
        f"manifest_path={summary.manifest_path}"
    )


def load_sensortower_raw(*, db_path: Path, input_dir: str | None, manifest_path: str | None, force: bool) -> None:
    conn = open_connection(db_path)
    try:
        if manifest_path:
            summaries = [load_sensortower_raw_manifest(conn, manifest_path=Path(manifest_path), force=force)]
        else:
            summaries = load_pending_sensortower_raw_manifests(
                conn,
                raw_root=Path(input_dir) if input_dir else default_sensortower_raw_dir(),
                force=force,
            )
    finally:
        conn.close()

    if not summaries:
        print("No pending SensorTower raw manifests found.")
        return

    for summary in summaries:
        print(
            "sensortower_raw_load: "
            f"manifest_path={summary.manifest_path} "
            f"loaded_snapshots={summary.loaded_snapshots} "
            f"skipped_snapshots={summary.skipped_snapshots} "
            f"update_rows={summary.update_rows} "
            f"version_rows={summary.version_rows} "
            f"st_update_event_rows={summary.st_update_event_rows} "
            f"st_version_event_rows={summary.st_version_event_rows}"
        )


def main() -> int:
    load_environment_files()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        conn = open_connection(args.db)
        try:
            init_db(conn)
        finally:
            conn.close()
        print(f"Initialized warehouse schema at {args.db}")
        return 0

    if args.command == "run":
        stats = run_etl(args.db, args.config, args.input_dir)
        print(
            "ETL completed: "
            f"raw_fb_posts={stats.raw_fb_posts}, "
            f"raw_app_updates={stats.raw_app_updates}, "
            f"raw_versions={stats.raw_versions}, "
            f"st_app_update_events_loaded={stats.st_app_update_events_loaded}, "
            f"st_version_events_loaded={stats.st_version_events_loaded}"
        )
        return 0

    if args.command == "reload-fb-posts":
        stats = reload_fb_posts(args.db, args.config, args.input_dir)
        print(
            "FB reload completed: "
            f"raw_fb_posts={stats.raw_fb_posts}, "
            f"st_app_update_events_loaded={stats.st_app_update_events_loaded}, "
            f"st_version_events_loaded={stats.st_version_events_loaded}"
        )
        return 0

    if args.command == "build-fb-event-detection":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            print("fb_event_detection_started")
            stats = build_fb_event_detection(
                conn,
                fb_page_id=args.fb_page_id,
                game_name=args.game_name,
                page_name=args.page_name,
                limit=args.limit,
                progress=print,
            )
        finally:
            conn.close()
        print(
            "fb_event_detection_completed: "
            f"processed_posts={stats.processed_posts} "
            f"detected_posts={stats.detected_posts}"
        )
        return 0

    if args.command == "build-fb-event-objects":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            print("fb_event_objects_started")
            stats = build_fb_event_objects(
                conn,
                fb_page_id=args.fb_page_id,
                game_name=args.game_name,
                page_name=args.page_name,
                limit=args.limit,
                progress=print,
            )
        finally:
            conn.close()
        print(
            "fb_event_objects_completed: "
            f"processed_posts={stats.processed_posts} "
            f"extracted_objects={stats.extracted_objects}"
        )
        return 0

    if args.command == "build-fb-raw-events":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            print("fb_raw_events_started")
            stats = build_fb_raw_events(
                conn,
                fb_page_id=args.fb_page_id,
                game_name=args.game_name,
                page_name=args.page_name,
                limit=args.limit,
                progress=print,
            )
        finally:
            conn.close()
        print(
            "fb_raw_events_completed: "
            f"detection_processed_posts={stats.detection_processed_posts} "
            f"detected_posts={stats.detected_posts} "
            f"extraction_processed_posts={stats.extraction_processed_posts} "
            f"extracted_objects={stats.extracted_objects}"
        )
        return 0

    if args.command == "build-fb-events":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            print("fb_events_started")
            stats = build_fb_events(
                conn,
                fb_page_id=args.fb_page_id,
                game_name=args.game_name,
                page_name=args.page_name,
                progress=print,
            )
        finally:
            conn.close()
        print(
            "fb_events_completed: "
            f"candidate_pairs={stats.candidate_pairs} "
            f"judged_pairs={stats.judged_pairs} "
            f"fb_events={stats.fb_events}"
        )
        return 0

    if args.command == "build-fb-events-llm":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            print("fb_events_llm_started")
            stats = build_fb_events_with_llm_merge(
                conn,
                fb_page_id=args.fb_page_id,
                game_name=args.game_name,
                page_name=args.page_name,
                limit=args.limit,
                progress=print,
            )
        finally:
            conn.close()
        print(
            "fb_events_llm_completed: "
            f"merge_groups={stats.merge_groups} "
            f"source_objects={stats.source_objects} "
            f"merged_events={stats.merged_events}"
        )
        return 0

    if args.command == "build-unified-events-llm":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            print("unified_events_llm_started")
            stats = build_unified_events_with_llm_merge(
                conn,
                unified_app_id=args.unified_app_id,
                month=args.month,
                limit_source_rows=args.limit_source_rows,
                progress=print,
            )
        finally:
            conn.close()
        print(
            "unified_events_llm_completed: "
            f"merge_scopes={stats.merge_scopes} "
            f"source_rows={stats.source_rows} "
            f"merged_events={stats.merged_events}"
        )
        return 0

    if args.command == "rerun-unified-step5":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            print("unified_step5_rerun_started")
            stats = rerun_unified_step5(
                conn,
                unified_app_id=args.unified_app_id,
                month=args.month,
                source_run_id=args.source_run_id,
                progress=print,
            )
        finally:
            conn.close()
        print(
            "unified_step5_rerun_completed: "
            f"merge_scopes={stats.merge_scopes} "
            f"source_rows={stats.source_rows} "
            f"merged_events={stats.merged_events}"
        )
        return 0

    if args.command == "serve-api":
        conn = open_connection(args.db)
        try:
            init_db(conn)
        finally:
            conn.close()
        uvicorn.run(create_app(db_path=args.db), host=args.host, port=args.port)
        return 0

    if args.command == "serve-api-ngrok":
        conn = open_connection(args.db)
        try:
            init_db(conn)
        finally:
            conn.close()
        serve_api_with_ngrok(
            db_path=args.db,
            host=args.host,
            port=args.port,
            ngrok_authtoken=args.ngrok_authtoken,
            ngrok_domain=args.ngrok_domain,
            progress=print,
        )
        return 0

    if args.command == "preview-fb-event-dedup":
        conn = open_connection(args.db)
        try:
            init_db(conn)
            stats = preview_fb_event_dedup(
                conn,
                fb_page_id=args.fb_page_id,
                game_name=args.game_name,
                page_name=args.page_name,
            )
        finally:
            conn.close()
        print(
            "fb_event_dedup_preview: "
            f"candidate_pairs={stats.candidate_pairs} "
            f"rule_merge_pairs={stats.rule_merge_pairs} "
            f"rule_reject_pairs={stats.rule_reject_pairs} "
            f"llm_judge_pairs={stats.llm_judge_pairs}"
        )
        return 0

    if args.command == "sync-sensortower-raw":
        run_sensortower_raw_extract(
            config_path=args.config,
            since=args.since,
            until=args.until,
            lookback_days=args.lookback_days,
            output_dir=args.output_dir,
            unified_app_ids=args.unified_app_ids,
        )
        return 0

    if args.command == "load-sensortower-raw":
        load_sensortower_raw(
            db_path=args.db,
            input_dir=args.input_dir,
            manifest_path=args.manifest_path,
            force=args.force,
        )
        return 0

    if args.command == "summary":
        summary = summarize_db(args.db)
        for table_name, count in summary.items():
            print(f"{table_name}: {count}")
        return 0

    if args.command == "socialdata-auth-check":
        client = _build_socialdata_client(args)
        auth_check_response = client.auth_check()
        print("socialdata_auth_check_completed")
        _emit_json_output(auth_check_response)
        return 0

    if args.command == "socialdata-mint-google-access-token":
        client = _build_socialdata_client(args)
        result = client.mint_google_access_token_from_service_account()
        if args.token_only:
            if args.output is not None:
                args.output.write_text(result.access_token + "\n", encoding="utf-8")
                print(f"Wrote Google access token to {args.output}")
                return 0
            print(result.access_token)
            return 0
        _emit_json_output(
            {
                "service_account_email": result.service_account_email,
                "access_token": result.access_token,
                "expiry_iso": result.expiry_iso,
                "google_scopes": list(result.google_scopes),
            },
            output_path=args.output,
        )
        return 0

    if args.command == "socialdata-debug-token-exchange":
        client = _build_socialdata_client(args)
        result = client.debug_google_token_exchange(access_token=args.google_access_token)
        _emit_json_output(
            {
                "token_source": result.token_source,
                "service_account_email": result.service_account_email,
                "google_scopes": list(result.google_scopes) if result.google_scopes is not None else None,
                "access_token_length": result.access_token_length,
                "access_token_prefix": result.access_token_prefix,
                "access_token_suffix": result.access_token_suffix,
                "exchange_endpoint": result.exchange_endpoint,
                "http_status": result.http_status,
                "response_body": result.response_body,
                "set_cookie_headers": list(result.set_cookie_headers),
                "location": result.location,
                "usession": result.usession,
            },
            output_path=args.output,
        )
        return 0

    if args.command == "socialdata-graphql":
        client = _build_socialdata_client(args)
        query_text = read_query_text(query=args.query, query_file=args.query_file)
        variables = read_graphql_variables(
            variables_json=args.variables_json,
            variables_file=args.variables_file,
        )
        response = client.graphql(
            query=query_text,
            variables=variables,
            operation_name=args.operation_name,
        )
        _emit_json_output(response, output_path=args.output)
        return 0

    if args.command == "socialdata-introspect":
        client = _build_socialdata_client(args)
        response = client.introspect_schema()
        _emit_json_output(response, output_path=args.output)
        return 0

    if args.command == "sync-socialdata-posts":
        client = _build_socialdata_client(args)
        stats = sync_socialdata_posts(
            db_path=args.db,
            config_path=args.config,
            client=client,
            app_slug=args.app_slug,
            since=args.since,
            lookback_days=args.lookback_days,
            unified_app_ids=args.unified_app_ids,
            per_page=args.per_page,
            progress=print,
        )
        _emit_json_output(
            {
                "app_slug": stats.app_slug,
                "app_id": stats.app_id,
                "cutoff_iso": stats.cutoff_iso,
                "matched_channels": stats.matched_channels,
                "listed_posts": stats.listed_posts,
                "upserted_posts": stats.upserted_posts,
                "channel_stats": [
                    {
                        "channel_id": item.channel_id,
                        "fb_page_id": item.fb_page_id,
                        "channel_name": item.channel_name,
                        "listed_posts": item.listed_posts,
                        "upserted_posts": item.upserted_posts,
                        "stopped_on_cutoff": item.stopped_on_cutoff,
                    }
                    for item in stats.channel_stats
                ],
            }
        )
        return 0

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
