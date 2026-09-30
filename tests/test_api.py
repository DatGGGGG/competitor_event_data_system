from __future__ import annotations

import unittest
import json
from pathlib import Path
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient

from vn_event_dw.api import create_app
from vn_event_dw.api_keys import add_api_key
from vn_event_dw.etl import init_db, open_connection


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = DATA_DIR / f"test_api_{uuid.uuid4().hex}.db"
        if self.db_path.exists():
            self.db_path.unlink()
        conn = open_connection(self.db_path)
        try:
            init_db(conn)
            self._seed_data(conn)
            conn.commit()
        finally:
            conn.close()
        self.client = TestClient(create_app(db_path=self.db_path))

    def tearDown(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()

    def _seed_data(self, conn) -> None:
        conn.execute(
            """
            INSERT INTO config_app_mapping (unified_app_id, fb_page_id, app_name, is_active)
            VALUES
                ('app_a', 'page_a', 'Game A', 1),
                ('app_b', 'page_b', 'Game B', 1),
                ('app_c', 'page_c', 'Game C', 1),
                ('mlbb_app', 'page_mlbb', 'Mobile Legends: Bang Bang', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO unified_events (
                unified_event_id, unified_app_id, month_bucket, canonical_event_name, event_category,
                estimated_start_date, estimated_end_date, canonical_event_description,
                anchor_source_type, merge_confidence, merge_model, prompt_version, created_at, updated_at
            )
            VALUES
                ('event_a1', 'app_a', '2026-04', 'Alpha Login Bonus', 'Retention / Free Rewards',
                 '2026-04-10', '2026-04-20', 'Login to claim rewards.', 'fb_post', 0.91, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z'),
                ('event_a2', 'app_a', '2026-04', 'April Patch Launch', 'Release / Update Rollout',
                 NULL, NULL, 'Version rollout campaign.', 'st_app_update_event', 0.88, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z'),
                ('event_a3', 'app_a', '2026-04', 'Single Day Trial', 'Gameplay / Content Activation',
                 NULL, '2026-04-15', 'Try the event mode.', 'fb_post', 0.76, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z'),
                ('event_a4', 'app_a', '2026-05', 'May Social Push', 'Community Participation',
                 '2026-05-03', '2026-05-07', 'Share screenshots for rewards.', 'fb_post', 0.72, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z'),
                ('event_b1', 'app_b', '2026-04', 'Bravo Pass', 'Progression / Season Systems',
                 '2026-04-01', '2026-04-30', 'Monthly pass rewards.', 'st_version_event', 0.84, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z'),
                ('event_b2', 'app_b', '2026-04', 'Naruto Shadow Clash', 'Collaboration / IP Events',
                 '2026-04-05', '2026-04-16', 'Naruto crossover missions and rewards.', 'fb_post', 0.89, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z'),
                ('event_c1', 'app_c', '2026-04', 'Crimson Reboot', 'Release / Update Rollout',
                 '2026-04-01', '2026-04-10', 'System reboot update.', 'st_version_event', 0.81, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z'),
                ('event_mlbb1', 'mlbb_app', '2026-04', 'Academy Frenzy', 'Collaboration / IP Events',
                 '2026-04-08', '2026-04-18', 'Naruto-inspired academy crossover rewards.', 'fb_post', 0.93, 'gpt-5.4', 'v1', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO unified_event_sources (
                unified_event_id, source_type, source_id, source_time, source_post_id, source_confidence
            )
            VALUES
                ('event_a1', 'fb_post', 'post_a1', '2026-04-09T08:00:00Z', 'post_a1', 0.8),
                ('event_a1', 'fb_post', 'post_a2', '2026-04-21T08:00:00Z', 'post_a2', 0.7),
                ('event_a1', 'st_app_update_event', 'st_app_a1', '2026-04-10T00:00:00Z', NULL, 1.0),
                ('event_a2', 'st_app_update_event', 'st_app_a2', '2026-04-04T00:00:00Z', NULL, 1.0),
                ('event_a3', 'fb_post', 'post_a3', '2026-04-15T09:00:00Z', 'post_a3', 0.6),
                ('event_a4', 'fb_post', 'post_a4', '2026-05-04T09:00:00Z', 'post_a4', 0.6),
                ('event_b1', 'st_version_event', 'st_ver_b1', '2026-04-01T00:00:00Z', NULL, 1.0),
                ('event_b2', 'fb_post', 'post_b2', '2026-04-06T07:00:00Z', 'post_b2', 0.9),
                ('event_c1', 'st_version_event', 'st_ver_c1', '2026-04-02T00:00:00Z', NULL, 1.0),
                ('event_mlbb1', 'fb_post', 'post_mlbb1', '2026-04-09T10:00:00Z', 'post_mlbb1', 0.95)
            """
        )
        conn.execute(
            """
            INSERT INTO raw_fb_posts (
                source_post_id, unified_app_id, fb_page_id, channel_id, channel_name, post_type,
                post_description, duration, link, publish_time, hashtag, engagement, reaction,
                comment, share, view, source_file, ingested_at
            )
            VALUES
                ('post_a1', 'app_a', 'page_a', 'channel_a', 'Game A Page', 'photo',
                 'Alpha event launch', '', 'https://example.com/a1', '2026-04-09T08:00:00Z', '', '120', '10', '2', '1', '100', 'seed.csv', '2026-06-12T00:00:00Z'),
                ('post_a2', 'app_a', 'page_a', 'channel_a', 'Game A Page', 'photo',
                 'Alpha reminder', '', 'https://example.com/a2', '2026-04-21T08:00:00Z', '', '80', '5', '3', '0', '30', 'seed.csv', '2026-06-12T00:00:00Z'),
                ('post_a3', 'app_a', 'page_a', 'channel_a', 'Game A Page', 'video',
                 'Single day mode', '', 'https://example.com/a3', '2026-04-15T09:00:00Z', '', '1,000', '100', '20', '5', '500', 'seed.csv', '2026-06-12T00:00:00Z'),
                ('post_a4', 'app_a', 'page_a', 'channel_a', 'Game A Page', 'video',
                 'May social push', '', 'https://example.com/a4', '2026-05-04T09:00:00Z', '', '70', '8', '4', '2', '10', 'seed.csv', '2026-06-12T00:00:00Z'),
                ('post_b2', 'app_b', 'page_b', 'channel_b', 'Game B Page', 'video',
                 'Naruto crossover reveal', '', 'https://example.com/b2', '2026-04-06T07:00:00Z', '', '450', '40', '10', '4', '200', 'seed.csv', '2026-06-12T12:00:00Z'),
                ('post_mlbb1', 'mlbb_app', 'page_mlbb', 'channel_mlbb', 'MLBB Page', 'photo',
                 'Academy crossover teaser', '', 'https://example.com/mlbb1', '2026-04-09T10:00:00Z', '', '260', '30', '6', '3', '90', 'seed.csv', '2026-06-11T20:00:00Z'),
                ('post_a5', 'app_a', 'page_a', 'channel_a', 'Game A Page', 'photo',
                 'August raw post without event link', '', 'https://example.com/a5', '2026-08-05T09:30:00Z', '', '300', '50', '7', '2', '180', 'seed.csv', '2026-08-05T10:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO st_app_update_events (
                st_update_event_id, event_id, source_row_id, unified_app_id, event_name,
                estimated_start_date, estimated_end_date, event_description, source_refs
            )
            VALUES
                ('st_app_a1', 'alpha_login_bonus', 'raw_st_update_a1', 'app_a', 'Alpha Login Bonus',
                 '2026-04-10', '2026-04-20', 'Login to claim rewards.', '[]'),
                ('st_app_a2', 'april_patch_launch', 'raw_st_update_a2', 'app_a', 'April Patch Launch',
                 NULL, NULL, 'Version rollout campaign.', '[]')
            """
        )
        conn.execute(
            """
            INSERT INTO st_version_events (
                st_version_event_id, source_row_id, unified_app_id, event_name,
                estimated_start_date, estimated_end_date, event_description, source_refs
            )
            VALUES
                ('st_ver_b1', 'raw_st_version_b1', 'app_b', 'Bravo Pass',
                 '2026-04-01', '2026-04-30', 'Monthly pass rewards.', '[]'),
                ('st_ver_c1', 'raw_st_version_c1', 'app_c', 'Crimson Reboot',
                 '2026-04-01', '2026-04-10', 'System reboot update.', '[]')
            """
        )

    def test_get_events_groups_by_app_and_returns_metrics(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("unified_app_id", "app_b"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 2)

        app_a = payload["results"][0]
        self.assertEqual(app_a["unified_app_id"], "app_a")
        self.assertEqual([event["canonical_event_name"] for event in app_a["events"]], [
            "April Patch Launch",
            "Alpha Login Bonus",
            "Single Day Trial",
        ])

        alpha_event = next(event for event in app_a["events"] if event["unified_event_id"] == "event_a1")
        self.assertEqual(alpha_event["fb_post_count"], 2)
        self.assertEqual(alpha_event["st_app_update_event_count"], 1)
        self.assertEqual(alpha_event["total_reaction_fb"], 15)
        self.assertEqual(alpha_event["total_comment_fb"], 5)
        self.assertEqual(alpha_event["total_share_fb"], 1)
        self.assertEqual(alpha_event["total_view_fb"], 130)
        self.assertEqual(alpha_event["social_score"], 180)

        app_b = payload["results"][1]
        self.assertEqual([event["unified_event_id"] for event in app_b["events"]], ["event_b1", "event_b2"])

    def test_get_events_supports_top_ranking_by_social_score(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("top", "2"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        events = response.json()["results"][0]["events"]
        self.assertEqual([event["unified_event_id"] for event in events], ["event_a3", "event_a1"])

    def test_get_events_compact_returns_compact_event_rows(self) -> None:
        response = self.client.get(
            "/api/events/compact",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        events = response.json()["results"][0]["events"]
        self.assertEqual(
            events,
            [
                {
                    "unified_event_id": "event_a2",
                    "canonical_event_name": "April Patch Launch",
                    "event_category": "Release / Update Rollout",
                },
                {
                    "unified_event_id": "event_a1",
                    "canonical_event_name": "Alpha Login Bonus",
                    "event_category": "Retention / Free Rewards",
                },
                {
                    "unified_event_id": "event_a3",
                    "canonical_event_name": "Single Day Trial",
                    "event_category": "Gameplay / Content Activation",
                },
            ],
        )

    def test_get_games_lists_known_games(self) -> None:
        response = self.client.get("/api/games")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [
                {"unified_app_id": "app_a", "app_name": "Game A"},
                {"unified_app_id": "app_b", "app_name": "Game B"},
                {"unified_app_id": "app_c", "app_name": "Game C"},
                {"unified_app_id": "mlbb_app", "app_name": "Mobile Legends: Bang Bang"},
            ],
        )

    def test_get_games_supports_search_and_acronym_search(self) -> None:
        response = self.client.get("/api/games", params={"q": "game a"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [{"unified_app_id": "app_a", "app_name": "Game A"}])

        response = self.client.get("/api/games", params={"q": "MLBB"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [{"unified_app_id": "mlbb_app", "app_name": "Mobile Legends: Bang Bang"}],
        )

    def test_api_key_is_not_required_when_env_is_unset(self) -> None:
        with patch.dict("os.environ", {"VN_EVENT_DW_API_KEY": "", "VN_EVENT_DW_API_KEYS_FILE": ""}, clear=False):
            client = TestClient(create_app(db_path=self.db_path))
            response = client.get("/api/v2/health")
        self.assertEqual(response.status_code, 200)

    def test_api_key_protects_legacy_and_v2_api_routes(self) -> None:
        with patch.dict("os.environ", {"VN_EVENT_DW_API_KEY": "test-secret", "VN_EVENT_DW_API_KEYS_FILE": ""}, clear=False):
            client = TestClient(create_app(db_path=self.db_path))

            public_health = client.get("/api/v2/health")
            self.assertEqual(public_health.status_code, 200)

            missing = client.get("/api/games")
            self.assertEqual(missing.status_code, 401)

            invalid = client.get("/api/v2/games", headers={"X-API-Key": "wrong"})
            self.assertEqual(invalid.status_code, 403)

            namespaced_invalid = client.get("/api/events/v2/games", headers={"X-API-Key": "wrong"})
            self.assertEqual(namespaced_invalid.status_code, 403)

            legacy = client.get("/api/games", headers={"X-API-Key": "test-secret"})
            self.assertEqual(legacy.status_code, 200)

            v2 = client.get("/api/v2/games", headers={"Authorization": "Bearer test-secret"})
            self.assertEqual(v2.status_code, 200)

            namespaced_v2 = client.get("/api/events/v2/games", headers={"Authorization": "Bearer test-secret"})
            self.assertEqual(namespaced_v2.status_code, 200)

    def test_api_key_store_protects_read_routes(self) -> None:
        keys_file = DATA_DIR / f"test_api_keys_{uuid.uuid4().hex}.json"
        generated = add_api_key(keys_file, name="alice")
        try:
            with patch.dict(
                "os.environ",
                {"VN_EVENT_DW_API_KEY": "", "VN_EVENT_DW_API_KEYS_FILE": str(keys_file)},
                clear=False,
            ):
                client = TestClient(create_app(db_path=self.db_path))

                public_health = client.get("/api/v2/health")
                self.assertEqual(public_health.status_code, 200)

                missing = client.get("/api/v2/games")
                self.assertEqual(missing.status_code, 401)

                invalid = client.get("/api/v2/games", headers={"X-API-Key": "wrong"})
                self.assertEqual(invalid.status_code, 403)

                valid = client.get("/api/v2/games", headers={"X-API-Key": generated.key})
                self.assertEqual(valid.status_code, 200)

                namespaced_valid = client.get("/api/events/v2/games", headers={"X-API-Key": generated.key})
                self.assertEqual(namespaced_valid.status_code, 200)
        finally:
            if keys_file.exists():
                keys_file.unlink()

    def test_get_events_uses_month_bucket_filtering(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-15"),
                ("time_range_end", "2026-04-15"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        events = response.json()["results"][0]["events"]
        self.assertEqual({event["unified_event_id"] for event in events}, {"event_a1", "event_a2", "event_a3"})

    def test_get_event_summary_returns_counts_and_top_events(self) -> None:
        response = self.client.get(
            "/api/events/summary",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        statistics = response.json()["results"][0]["statistics"]
        self.assertEqual(statistics["event_count_total"], 3)
        self.assertEqual(statistics["event_count_st_app_update"], 2)
        self.assertEqual(statistics["event_count_st_version"], 0)
        self.assertEqual(statistics["event_count_fb"], 2)
        self.assertEqual(statistics["total_engagement_fb"], 1200)
        self.assertEqual(statistics["total_reaction_fb"], 115)
        self.assertEqual(statistics["total_comment_fb"], 25)
        self.assertEqual(statistics["total_share_fb"], 6)
        self.assertEqual(statistics["total_view_fb"], 630)
        self.assertEqual(
            [event["unified_event_id"] for event in statistics["top_socially_active_events"]],
            ["event_a3", "event_a1", "event_a2"],
        )
        self.assertEqual(statistics["top_socially_active_events"][0]["social_score"], 785)

    def test_get_event_detail_returns_full_event_payload(self) -> None:
        response = self.client.get("/api/events/event_a1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["unified_event_id"], "event_a1")
        self.assertEqual(payload["app_name"], "Game A")
        self.assertEqual(payload["canonical_event_name"], "Alpha Login Bonus")
        self.assertEqual(payload["fb_post_count"], 2)
        self.assertEqual(payload["social_score"], 180)

    def test_get_event_post_stats_returns_fb_statistics_only(self) -> None:
        response = self.client.get("/api/events/event_a1/post-stats")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["unified_event_id"], "event_a1")
        self.assertEqual(payload["fb_post_count"], 2)
        self.assertEqual(payload["total_reaction_fb"], 15)
        self.assertEqual(payload["social_score"], 180)

    def test_get_event_top_posts_returns_ranked_posts(self) -> None:
        response = self.client.get("/api/events/event_a1/top-posts", params={"top": 1})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["posts"][0]["source_post_id"], "post_a1")
        self.assertEqual(payload["posts"][0]["social_score"], 131)

    def test_get_event_posts_returns_compact_post_list(self) -> None:
        response = self.client.get("/api/events/event_a1/posts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["posts"],
            [
                {
                    "source_post_id": "post_a1",
                    "publish_time": "2026-04-09T08:00:00Z",
                    "engagement_num": 120,
                    "reaction_num": 10,
                    "comment_num": 2,
                    "share_num": 1,
                    "view_num": 100,
                    "social_score": 131,
                },
                {
                    "source_post_id": "post_a2",
                    "publish_time": "2026-04-21T08:00:00Z",
                    "engagement_num": 80,
                    "reaction_num": 5,
                    "comment_num": 3,
                    "share_num": 0,
                    "view_num": 30,
                    "social_score": 49,
                },
            ],
        )

    def test_get_post_detail_returns_full_post_payload(self) -> None:
        response = self.client.get("/api/posts/post_a3")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source_post_id"], "post_a3")
        self.assertEqual(payload["app_name"], "Game A")
        self.assertEqual(payload["engagement_num"], 1000)
        self.assertEqual(payload["social_score"], 785)

    def test_old_endpoints_are_removed(self) -> None:
        self.assertEqual(self.client.get("/api/events-light").status_code, 404)
        self.assertEqual(self.client.get("/api/event-statistics").status_code, 404)
        self.assertEqual(self.client.get("/api/events/event_a1/sources").status_code, 404)

    def test_event_category_filter_supports_single_and_multi_value(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("event_category", "Release / Update Rollout"),
            ],
        )
        self.assertEqual(
            [event["unified_event_id"] for event in response.json()["results"][0]["events"]],
            ["event_a2"],
        )

        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("event_category", "Release / Update Rollout"),
                ("event_category", "Retention / Free Rewards"),
            ],
        )
        self.assertEqual(
            [event["unified_event_id"] for event in response.json()["results"][0]["events"]],
            ["event_a2", "event_a1"],
        )

    def test_source_type_filter_supports_single_and_multi_value(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("source_type", "fb_post"),
            ],
        )
        self.assertEqual(
            [event["unified_event_id"] for event in response.json()["results"][0]["events"]],
            ["event_a1", "event_a3"],
        )

        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("source_type", "st_app_update_event"),
                ("source_type", "fb_post"),
            ],
        )
        self.assertEqual(
            [event["unified_event_id"] for event in response.json()["results"][0]["events"]],
            ["event_a2", "event_a1", "event_a3"],
        )

    def test_min_social_score_and_has_fb_posts_filters_work(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("min_social_score", "100"),
            ],
        )
        self.assertEqual(
            [event["unified_event_id"] for event in response.json()["results"][0]["events"]],
            ["event_a1", "event_a3"],
        )

        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("has_fb_posts", "false"),
            ],
        )
        self.assertEqual(
            [event["unified_event_id"] for event in response.json()["results"][0]["events"]],
            ["event_a2"],
        )

    def test_combined_filters_apply_to_events_compact_and_summary(self) -> None:
        compact_response = self.client.get(
            "/api/events/compact",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("source_type", "fb_post"),
                ("min_social_score", "200"),
            ],
        )
        self.assertEqual(compact_response.status_code, 200)
        self.assertEqual(
            compact_response.json()["results"][0]["events"],
            [
                {
                    "unified_event_id": "event_a3",
                    "canonical_event_name": "Single Day Trial",
                    "event_category": "Gameplay / Content Activation",
                }
            ],
        )

        summary_response = self.client.get(
            "/api/events/summary",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("source_type", "fb_post"),
                ("min_social_score", "200"),
            ],
        )
        self.assertEqual(summary_response.status_code, 200)
        statistics = summary_response.json()["results"][0]["statistics"]
        self.assertEqual(statistics["event_count_total"], 1)
        self.assertEqual(statistics["top_socially_active_events"][0]["unified_event_id"], "event_a3")

    def test_event_coverage_supports_no_filters_and_scoped_filters(self) -> None:
        response = self.client.get("/api/events/coverage")
        self.assertEqual(response.status_code, 200)
        results = {item["unified_app_id"]: item for item in response.json()["results"]}
        self.assertEqual(results["app_a"]["min_month_bucket"], "2026-04")
        self.assertEqual(results["app_a"]["max_month_bucket"], "2026-05")
        self.assertEqual(results["app_a"]["months_available"], 2)
        self.assertEqual(results["app_a"]["event_count"], 4)
        self.assertEqual(results["app_a"]["fb_post_count"], 4)
        self.assertEqual(results["app_a"]["latest_ingested_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(results["app_c"]["fb_post_count"], 0)
        self.assertIsNone(results["app_c"]["latest_ingested_at"])

        response = self.client.get("/api/events/coverage", params=[("unified_app_id", "mlbb_app")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["event_count"], 1)

        response = self.client.get(
            "/api/events/coverage",
            params={"time_range_start": "2026-05-01", "time_range_end": "2026-05-31"},
        )
        self.assertEqual(response.status_code, 200)
        may_results = {item["unified_app_id"]: item for item in response.json()["results"]}
        self.assertEqual(may_results["app_a"]["event_count"], 1)
        self.assertEqual(may_results["app_b"]["event_count"], 0)

        response = self.client.get(
            "/api/events/coverage",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-05-01"),
                ("time_range_end", "2026-05-31"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        app_a = response.json()["results"][0]
        self.assertEqual(app_a["event_count"], 1)
        self.assertEqual(app_a["fb_post_count"], 1)

    def test_event_search_supports_exact_and_substring_matches(self) -> None:
        response = self.client.get("/api/events/search", params={"q": "Alpha Login Bonus"})
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(results[0]["unified_event_id"], "event_a1")
        self.assertEqual(results[0]["match_scope"], "scoped_game")

        response = self.client.get("/api/events/search", params={"q": "Single Day"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["unified_event_id"], "event_a3")

    def test_event_search_supports_description_assisted_scoped_match(self) -> None:
        response = self.client.get(
            "/api/events/search",
            params=[
                ("q", "Naruto"),
                ("unified_app_id", "mlbb_app"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["unified_event_id"], "event_mlbb1")
        self.assertEqual(result["match_scope"], "scoped_game")

    def test_event_search_falls_back_cross_game_when_scoped_game_misses(self) -> None:
        response = self.client.get(
            "/api/events/search",
            params=[
                ("q", "Bravo Pass"),
                ("unified_app_id", "mlbb_app"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["unified_event_id"], "event_b1")
        self.assertEqual(result["match_scope"], "cross_game_fallback")

    def test_event_search_respects_date_window_and_top_limit(self) -> None:
        response = self.client.get(
            "/api/events/search",
            params=[
                ("q", "May Social"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

        response = self.client.get("/api/events/search", params=[("q", "Naruto"), ("top", "1")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_event_search_returns_empty_when_no_matches_exist(self) -> None:
        response = self.client.get("/api/events/search", params={"q": "zzzz-not-found"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_event_detail_and_post_endpoints_return_404_for_unknown_resources(self) -> None:
        self.assertEqual(self.client.get("/api/events/unknown_event").status_code, 404)
        self.assertEqual(self.client.get("/api/events/unknown_event/post-stats").status_code, 404)
        self.assertEqual(self.client.get("/api/posts/unknown_post").status_code, 404)

    def test_returns_empty_blocks_for_valid_app_without_matches(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_b"),
                ("time_range_start", "2026-06-01"),
                ("time_range_end", "2026-06-30"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        block = response.json()["results"][0]
        self.assertEqual(block["app_name"], "Game B")
        self.assertEqual(block["events"], [])

    def test_v2_health_and_games_include_metadata(self) -> None:
        response = self.client.get("/api/v2/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"]["status"], "ok")
        self.assertEqual(payload["meta"]["api_version"], "v2")
        self.assertIn("GET /api/events/v2/games/{unified_app_id}/posts", payload["result"]["endpoints"])
        self.assertIn("Legacy alias: GET /api/v2/...", payload["result"]["endpoints"])

        response = self.client.get("/api/v2/games", params={"q": "MLBB"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [{"unified_app_id": "mlbb_app", "app_name": "Mobile Legends: Bang Bang"}])
        self.assertEqual(payload["meta"]["semantics"], "registered_games")
        self.assertEqual(payload["meta"]["count"], 1)

    def test_openapi_exposes_only_the_canonical_portal_contract(self) -> None:
        admin_job_dir = self.db_path.parent / f"test_openapi_admin_jobs_{self.db_path.stem}"
        with patch.dict(
            "os.environ",
            {
                "VN_EVENT_DW_API_KEY": "test-secret",
                "VN_EVENT_DW_API_KEYS_FILE": "",
                "ADMIN_UI_ENABLED": "1",
                "ADMIN_PASSWORD": "test-admin-password",
                "ADMIN_JOB_DIR": str(admin_job_dir),
            },
            clear=False,
        ):
            client = TestClient(create_app(db_path=self.db_path))
            response = client.get("/openapi.json")

        if admin_job_dir.exists():
            admin_job_dir.rmdir()

        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertTrue(schema["openapi"].startswith("3."))
        self.assertEqual(schema["info"]["x-portal-source"], "events")
        self.assertEqual(schema["info"]["x-portal-contract-version"], 1)
        self.assertIn("EventApiKey", schema["components"]["securitySchemes"])
        self.assertEqual(schema["components"]["securitySchemes"]["EventApiKey"]["name"], "X-API-Key")

        canonical_paths = {
            "/api/events/v2/health",
            "/api/events/v2/games",
            "/api/events/v2/games/{unified_app_id}",
            "/api/events/v2/games/{unified_app_id}/events",
            "/api/events/v2/games/{unified_app_id}/events/summary",
            "/api/events/v2/games/{unified_app_id}/events/search",
            "/api/events/v2/games/{unified_app_id}/events/coverage",
            "/api/events/v2/games/{unified_app_id}/posts",
            "/api/events/v2/events/{unified_event_id}",
            "/api/events/v2/events/{unified_event_id}/post-stats",
            "/api/events/v2/events/{unified_event_id}/posts",
            "/api/events/v2/posts/{source_post_id}",
        }
        self.assertEqual(set(schema["paths"]), canonical_paths)
        for path in canonical_paths:
            operation = schema["paths"][path]["get"]
            self.assertTrue(operation["x-portal-public"])
            self.assertTrue(operation["operationId"])
            self.assertTrue(operation["summary"])
            self.assertTrue(operation["description"])
            self.assertIn("200", operation["responses"])
            self.assertIn("schema", operation["responses"]["200"]["content"]["application/json"])

        self.assertNotIn("/api/v2/games", schema["paths"])
        self.assertNotIn("/api/games", schema["paths"])
        self.assertFalse(any(path.startswith("/api/events/admin") for path in schema["paths"]))
        self.assertFalse(any(path.startswith("/workspaces/tracked-games/events") for path in schema["paths"]))
        self.assertNotIn("test-secret", json.dumps(schema))
        self.assertNotIn("test-admin-password", json.dumps(schema))

    def test_events_v2_namespace_alias_matches_legacy_v2(self) -> None:
        legacy_response = self.client.get(
            "/api/v2/games/app_a/posts",
            params={"publish_start": "2026-08-01", "publish_end": "2026-08-31"},
        )
        namespaced_response = self.client.get(
            "/api/events/v2/games/app_a/posts",
            params={"publish_start": "2026-08-01", "publish_end": "2026-08-31"},
        )

        self.assertEqual(legacy_response.status_code, 200)
        self.assertEqual(namespaced_response.status_code, 200)
        legacy_payload = legacy_response.json()
        namespaced_payload = namespaced_response.json()
        self.assertEqual(namespaced_payload["results"], legacy_payload["results"])
        self.assertEqual(namespaced_payload["meta"]["semantics"], legacy_payload["meta"]["semantics"])
        self.assertEqual(namespaced_payload["meta"]["scope"], legacy_payload["meta"]["scope"])

        detail_response = self.client.get("/api/events/v2/posts/post_a1")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["result"]["source_post_id"], "post_a1")

    def test_v2_game_detail_returns_registered_game(self) -> None:
        response = self.client.get("/api/v2/games/app_a")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"]["app_name"], "Game A")
        self.assertEqual(payload["result"]["fb_page_ids"], ["page_a"])
        self.assertTrue(payload["result"]["is_active"])

    def test_v2_events_use_explicit_month_bucket_filters(self) -> None:
        response = self.client.get("/api/v2/games/app_a/events", params=[("month", "2026-04")])
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["semantics"], "event_month_bucket")
        self.assertEqual([event["unified_event_id"] for event in payload["results"]], ["event_a2", "event_a1", "event_a3"])

        response = self.client.get(
            "/api/v2/games/app_a/events",
            params={"start_month": "2026-04", "end_month": "2026-05"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual({event["month_bucket"] for event in response.json()["results"]}, {"2026-04", "2026-05"})

    def test_v2_event_summary_and_search_are_scoped_to_game(self) -> None:
        response = self.client.get("/api/v2/games/app_a/events/summary", params=[("month", "2026-04")])
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"]["event_count_total"], 3)
        self.assertEqual(payload["result"]["event_count_fb"], 2)
        self.assertEqual(payload["meta"]["semantics"], "event_month_bucket")

        response = self.client.get(
            "/api/v2/games/mlbb_app/events/search",
            params=[("q", "Naruto"), ("month", "2026-04")],
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["unified_event_id"], "event_mlbb1")
        self.assertEqual(result["match_scope"], "scoped_game")

    def test_v2_event_coverage_uses_exact_month_bucket_scope(self) -> None:
        response = self.client.get("/api/v2/games/app_a/events/coverage", params=[("month", "2026-05")])
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"]["event_count"], 1)
        self.assertEqual(payload["result"]["fb_post_count"], 1)
        self.assertEqual(payload["result"]["min_month_bucket"], "2026-05")
        self.assertEqual(payload["meta"]["semantics"], "event_month_bucket_coverage")

    def test_v2_raw_game_posts_use_publish_time_not_event_month_bucket(self) -> None:
        response = self.client.get(
            "/api/v2/games/app_a/posts",
            params={"publish_start": "2026-08-01", "publish_end": "2026-08-31"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["semantics"], "raw_fb_post_publish_time")
        self.assertEqual([post["source_post_id"] for post in payload["results"]], ["post_a5"])
        self.assertEqual(payload["results"][0]["reaction_count"], 50)
        self.assertEqual(payload["results"][0]["comment_count"], 7)
        self.assertEqual(payload["results"][0]["linked_events"], [])

    def test_v2_raw_game_posts_default_to_latest_posts_and_support_text_search(self) -> None:
        response = self.client.get("/api/v2/games/app_a/posts", params={"limit": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["source_post_id"], "post_a5")

        response = self.client.get("/api/v2/games/app_a/posts", params={"q": "reminder"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([post["source_post_id"] for post in response.json()["results"]], ["post_a2"])

    def test_v2_post_detail_includes_linked_events_and_count_fields(self) -> None:
        response = self.client.get("/api/v2/posts/post_a1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["result"]
        self.assertEqual(payload["source_post_id"], "post_a1")
        self.assertEqual(payload["engagement_count"], 120)
        self.assertEqual(payload["linked_events"][0]["unified_event_id"], "event_a1")
        self.assertEqual(payload["linked_events"][0]["month_bucket"], "2026-04")

    def test_v2_event_linked_posts_use_count_field_names(self) -> None:
        response = self.client.get("/api/v2/events/event_a1/posts")
        self.assertEqual(response.status_code, 200)
        posts = response.json()["result"]["posts"]
        self.assertEqual(posts[0]["source_post_id"], "post_a1")
        self.assertEqual(posts[0]["engagement_count"], 120)
        self.assertNotIn("engagement_num", posts[0])

    def test_v2_validation_and_not_found_cases(self) -> None:
        self.assertEqual(self.client.get("/api/v2/games/unknown_app").status_code, 404)

        response = self.client.get("/api/v2/games/app_a/events", params={"month": "2026-13"})
        self.assertEqual(response.status_code, 400)

        response = self.client.get(
            "/api/v2/games/app_a/events",
            params={"start_month": "2026-05", "end_month": "2026-04"},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.get(
            "/api/v2/games/app_a/posts",
            params={"publish_start": "2026-08-31", "publish_end": "2026-08-01"},
        )
        self.assertEqual(response.status_code, 400)

    def test_validation_failures_return_expected_status_codes(self) -> None:
        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-30"),
                ("time_range_end", "2026-04-01"),
            ],
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.get(
            "/api/events",
            params={"time_range_start": "2026-04-01", "time_range_end": "2026-04-30"},
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "not-a-date"),
                ("time_range_end", "2026-04-30"),
            ],
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("source_type", "bad_source"),
            ],
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            "/api/events",
            params=[
                ("unified_app_id", "app_a"),
                ("time_range_start", "2026-04-01"),
                ("time_range_end", "2026-04-30"),
                ("has_fb_posts", "not-a-bool"),
            ],
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get("/api/events/search")
        self.assertEqual(response.status_code, 422)

        response = self.client.get("/api/events/coverage", params={"time_range_start": "2026-04-01"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
