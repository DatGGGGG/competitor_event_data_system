from __future__ import annotations

import unittest
from pathlib import Path

from vn_event_dw.cli import build_parser


class CliTests(unittest.TestCase):
    def test_sync_sensortower_raw_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["sync-sensortower-raw", "--config", "examples/config.json"])
        self.assertEqual(args.command, "sync-sensortower-raw")
        self.assertEqual(args.config, Path("examples/config.json"))
        self.assertIsNone(args.since)
        self.assertIsNone(args.until)
        self.assertIsNone(args.lookback_days)
        self.assertIsNone(args.output_dir)
        self.assertIsNone(args.unified_app_ids)

    def test_load_sensortower_raw_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["load-sensortower-raw", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "load-sensortower-raw")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertIsNone(args.input_dir)
        self.assertIsNone(args.manifest_path)
        self.assertFalse(args.force)

    def test_reload_fb_posts_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "reload-fb-posts",
                "--db",
                "data/warehouse.db",
                "--config",
                "examples/config.json",
                "--input-dir",
                "examples",
            ]
        )
        self.assertEqual(args.command, "reload-fb-posts")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertEqual(args.config, Path("examples/config.json"))
        self.assertEqual(args.input_dir, Path("examples"))

    def test_build_fb_event_detection_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["build-fb-event-detection", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "build-fb-event-detection")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertIsNone(args.fb_page_id)
        self.assertIsNone(args.game_name)
        self.assertIsNone(args.page_name)
        self.assertIsNone(args.limit)

    def test_build_fb_event_objects_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["build-fb-event-objects", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "build-fb-event-objects")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertIsNone(args.fb_page_id)
        self.assertIsNone(args.game_name)
        self.assertIsNone(args.page_name)
        self.assertIsNone(args.limit)

    def test_build_fb_raw_events_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["build-fb-raw-events", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "build-fb-raw-events")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertIsNone(args.fb_page_id)
        self.assertIsNone(args.game_name)
        self.assertIsNone(args.page_name)
        self.assertIsNone(args.limit)

    def test_build_fb_events_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["build-fb-events", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "build-fb-events")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertIsNone(args.fb_page_id)
        self.assertIsNone(args.game_name)
        self.assertIsNone(args.page_name)

    def test_preview_fb_event_dedup_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["preview-fb-event-dedup", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "preview-fb-event-dedup")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertIsNone(args.fb_page_id)
        self.assertIsNone(args.game_name)
        self.assertIsNone(args.page_name)

    def test_build_unified_events_llm_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["build-unified-events-llm", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "build-unified-events-llm")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertIsNone(args.unified_app_id)
        self.assertIsNone(args.month)
        self.assertIsNone(args.limit_source_rows)

    def test_rerun_unified_step5_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "rerun-unified-step5",
                "--db",
                "data/warehouse.db",
                "--unified-app-id",
                "57955d280211a6718a000002",
                "--month",
                "2026-04",
            ]
        )
        self.assertEqual(args.command, "rerun-unified-step5")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertEqual(args.unified_app_id, "57955d280211a6718a000002")
        self.assertEqual(args.month, "2026-04")
        self.assertIsNone(args.source_run_id)

    def test_serve_api_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve-api", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "serve-api")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)

    def test_serve_api_ngrok_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve-api-ngrok", "--db", "data/warehouse.db"])
        self.assertEqual(args.command, "serve-api-ngrok")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertIsNone(args.ngrok_authtoken)
        self.assertIsNone(args.ngrok_domain)

    def test_sync_socialdata_posts_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "sync-socialdata-posts",
                "--db",
                "data/warehouse.db",
                "--config",
                "examples/config.json",
            ]
        )
        self.assertEqual(args.command, "sync-socialdata-posts")
        self.assertEqual(args.db, Path("data/warehouse.db"))
        self.assertEqual(args.config, Path("examples/config.json"))
        self.assertIsNone(args.app_slug)
        self.assertIsNone(args.since)
        self.assertIsNone(args.lookback_days)
        self.assertIsNone(args.unified_app_ids)
        self.assertEqual(args.per_page, 100)
        self.assertIsNone(args.socialdata_base_url)
        self.assertIsNone(args.usession)
        self.assertIsNone(args.google_access_token)
        self.assertIsNone(args.google_service_account_file)
        self.assertIsNone(args.google_scope)
        self.assertIsNone(args.timeout_seconds)

    def test_socialdata_mint_google_access_token_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["socialdata-mint-google-access-token"])
        self.assertEqual(args.command, "socialdata-mint-google-access-token")
        self.assertIsNone(args.google_service_account_file)
        self.assertIsNone(args.socialdata_base_url)
        self.assertIsNone(args.google_scope)
        self.assertIsNone(args.timeout_seconds)
        self.assertFalse(args.token_only)
        self.assertIsNone(args.output)

    def test_socialdata_mint_google_access_token_parser_supports_scope_override(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "socialdata-mint-google-access-token",
                "--google-scope",
                "scope-a",
                "--google-scope",
                "scope-b",
            ]
        )
        self.assertEqual(args.google_scope, ["scope-a", "scope-b"])

    def test_socialdata_debug_token_exchange_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["socialdata-debug-token-exchange"])
        self.assertEqual(args.command, "socialdata-debug-token-exchange")
        self.assertIsNone(args.socialdata_base_url)
        self.assertIsNone(args.google_access_token)
        self.assertIsNone(args.google_service_account_file)
        self.assertIsNone(args.google_scope)
        self.assertIsNone(args.timeout_seconds)
        self.assertIsNone(args.output)


if __name__ == "__main__":
    unittest.main()
