from __future__ import annotations

import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error

from vn_event_dw.socialdata import (
    DEFAULT_GOOGLE_SCOPES,
    SocialDataClient,
    load_socialdata_config,
    parse_usession_from_set_cookie,
    read_graphql_variables,
    read_query_text,
)


class SocialDataTests(unittest.TestCase):
    def test_parse_usession_from_set_cookie(self) -> None:
        headers = [
            "other_cookie=abc; Path=/; HttpOnly",
            "usession=socialdata_token_example; Path=/; HttpOnly; Secure",
        ]
        self.assertEqual(parse_usession_from_set_cookie(headers), "socialdata_token_example")

    def test_read_query_text_prefers_inline_query(self) -> None:
        self.assertEqual(read_query_text(query="query { __typename }"), "query { __typename }")

    def test_read_query_text_reads_file_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            query_path = Path(tmpdir) / "query.graphql"
            query_path.write_text("query { __typename }", encoding="utf-8")
            self.assertEqual(read_query_text(query_file=query_path), "query { __typename }")

    def test_read_graphql_variables_supports_json_and_file(self) -> None:
        self.assertEqual(read_graphql_variables(variables_json='{"slug":"pubg"}'), {"slug": "pubg"})

        with tempfile.TemporaryDirectory() as tmpdir:
            variables_path = Path(tmpdir) / "variables.json"
            variables_path.write_text(json.dumps({"slug": "mlbb"}), encoding="utf-8")
            self.assertEqual(read_graphql_variables(variables_file=variables_path), {"slug": "mlbb"})

    def test_load_socialdata_config_builds_graphql_url(self) -> None:
        config = load_socialdata_config(
            base_url="https://socialdata.garena.vn/",
            usession="cookie123",
            google_service_account_file="/tmp/socialdata.json",
            timeout_seconds=45,
        )
        self.assertEqual(config.base_url, "https://socialdata.garena.vn")
        self.assertEqual(config.graphql_url, "https://socialdata.garena.vn/graphql")
        self.assertEqual(config.usession, "cookie123")
        self.assertEqual(config.google_service_account_file, "/tmp/socialdata.json")
        self.assertEqual(config.google_scopes, DEFAULT_GOOGLE_SCOPES)
        self.assertEqual(config.timeout_seconds, 45)

    def test_load_socialdata_config_supports_google_scope_override(self) -> None:
        config = load_socialdata_config(google_scopes=["scope-a,scope-b", "scope-a"])
        self.assertEqual(config.google_scopes, ("scope-a", "scope-b"))

    def test_auth_check_query_can_be_built_with_explicit_usession(self) -> None:
        client = SocialDataClient(base_url="https://socialdata.garena.vn", usession="cookie123")
        self.assertEqual(client.usession, "cookie123")

    def test_resolve_google_access_token_prefers_explicit_token(self) -> None:
        client = SocialDataClient(base_url="https://socialdata.garena.vn", google_access_token="token123")
        self.assertEqual(client.resolve_google_access_token(), "token123")

    def test_resolve_google_access_token_can_refresh_from_service_account_file(self) -> None:
        client = SocialDataClient(
            base_url="https://socialdata.garena.vn",
            google_service_account_file="/tmp/socialdata.json",
        )
        with patch.object(client, "refresh_google_access_token_from_service_account", return_value="fresh-token"):
            self.assertEqual(client.resolve_google_access_token(), "fresh-token")

    def test_mint_google_access_token_from_service_account_returns_structured_result(self) -> None:
        client = SocialDataClient(
            base_url="https://socialdata.garena.vn",
            google_service_account_file="/tmp/socialdata.json",
        )
        fake_result = object()
        fake_credentials = type(
            "FakeCredentials",
            (),
            {
                "service_account_email": "socialdata-reader@example.com",
                "token": "minted-token",
                "expiry": None,
                "refresh": lambda self, req: None,
            },
        )()
        with patch("vn_event_dw.socialdata.Path.is_file", return_value=True), patch(
            "google.oauth2.service_account.Credentials.from_service_account_file",
            return_value=fake_credentials,
        ) as from_service_account_file, patch("google.auth.transport.requests.Request", return_value=fake_result):
            result = client.mint_google_access_token_from_service_account()
        from_service_account_file.assert_called_once_with(
            Path("/tmp/socialdata.json"),
            scopes=list(DEFAULT_GOOGLE_SCOPES),
        )
        self.assertEqual(result.service_account_email, "socialdata-reader@example.com")
        self.assertEqual(result.access_token, "minted-token")
        self.assertIsNone(result.expiry_iso)
        self.assertEqual(result.google_scopes, DEFAULT_GOOGLE_SCOPES)

    def test_debug_google_token_exchange_reports_http_error_details(self) -> None:
        client = SocialDataClient(base_url="https://socialdata.garena.vn", google_access_token="token123")

        class _FakeHeaders:
            def get_all(self, name: str):
                if name.lower() == "set-cookie":
                    return None
                return None

            def get(self, name: str):
                return None

        class _FakeOpener:
            def open(self, req, timeout=60):
                raise error.HTTPError(
                    req.full_url,
                    400,
                    "Bad Request",
                    _FakeHeaders(),
                    io.BytesIO(b'{"message":"Invalid Email"}'),
                )

        with patch("vn_event_dw.socialdata.request.build_opener", return_value=_FakeOpener()):
            result = client.debug_google_token_exchange()
        self.assertEqual(result.token_source, "explicit_access_token")
        self.assertEqual(result.access_token_length, 8)
        self.assertEqual(result.access_token_prefix, "token123")
        self.assertEqual(result.access_token_suffix, "token123")
        self.assertEqual(result.http_status, 400)
        self.assertEqual(result.response_body, '{"message":"Invalid Email"}')
        self.assertIsNone(result.usession)


if __name__ == "__main__":
    unittest.main()
