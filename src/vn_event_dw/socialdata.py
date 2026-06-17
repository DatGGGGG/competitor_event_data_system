from __future__ import annotations

import json
import os
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_SOCIALDATA_BASE_URL = "https://socialdata.garena.vn"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_GOOGLE_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
DEFAULT_GOOGLE_SCOPES = (DEFAULT_GOOGLE_SCOPE,)

# Standard GraphQL introspection query.
INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      kind
      name
      description
      fields(includeDeprecated: true) {
        name
        description
        args {
          name
          description
          type {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
                ofType {
                  kind
                  name
                }
              }
            }
          }
          defaultValue
        }
        type {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
              }
            }
          }
        }
        isDeprecated
        deprecationReason
      }
      inputFields {
        name
        description
        type {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
            }
          }
        }
        defaultValue
      }
      interfaces {
        kind
        name
        ofType {
          kind
          name
        }
      }
      enumValues(includeDeprecated: true) {
        name
        description
        isDeprecated
        deprecationReason
      }
      possibleTypes {
        kind
        name
        ofType {
          kind
          name
        }
      }
    }
    directives {
      name
      description
      locations
      args {
        name
        description
        type {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
            }
          }
        }
        defaultValue
      }
    }
  }
}
""".strip()


@dataclass(frozen=True, slots=True)
class SocialDataAuthResult:
    usession: str
    set_cookie_headers: tuple[str, ...]
    exchange_url: str


@dataclass(frozen=True, slots=True)
class SocialDataGoogleAccessTokenResult:
    service_account_email: str
    access_token: str
    expiry_iso: str | None = None
    google_scopes: tuple[str, ...] = DEFAULT_GOOGLE_SCOPES


@dataclass(frozen=True, slots=True)
class SocialDataGoogleTokenExchangeDebugResult:
    token_source: str
    service_account_email: str | None
    google_scopes: tuple[str, ...] | None
    access_token_length: int
    access_token_prefix: str
    access_token_suffix: str
    exchange_endpoint: str
    http_status: int
    response_body: str | None
    set_cookie_headers: tuple[str, ...]
    location: str | None
    usession: str | None


@dataclass(frozen=True, slots=True)
class SocialDataConfig:
    base_url: str
    graphql_url: str
    timeout_seconds: int
    usession: str | None = None
    google_access_token: str | None = None
    google_service_account_file: str | None = None
    google_scopes: tuple[str, ...] = DEFAULT_GOOGLE_SCOPES


@dataclass(frozen=True, slots=True)
class SocialDataApp:
    id: int
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class SocialDataChannel:
    id: int
    plat: int | None
    sub: str | None
    alias: str | None
    name: str
    url: str | None
    status: int | None
    created_at: str | None
    tags: str | None
    metrics: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class SocialDataPost:
    id: int
    channel_id: int | None
    sub: str | None
    alias: str | None
    type: int | None
    name: str
    url: str | None
    tags: str | None
    created_at: str | None
    thumbnail: str | None
    metrics: dict[str, Any] | None


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _load_json_value(raw: str | None) -> dict[str, Any] | None:
    cleaned = _normalize_text(raw)
    if not cleaned:
        return None
    loaded = json.loads(cleaned)
    if loaded is None:
        return None
    if not isinstance(loaded, dict):
        raise ValueError("GraphQL variables JSON must decode to an object.")
    return loaded


def _parse_google_scopes(scopes: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if scopes is None:
        raw_scopes = _normalize_text(os.getenv("SOCIALDATA_GOOGLE_SCOPES"))
        if not raw_scopes:
            return DEFAULT_GOOGLE_SCOPES
        scopes = raw_scopes
    if isinstance(scopes, str):
        candidates = scopes.replace(",", " ").split()
    else:
        candidates = []
        for scope in scopes:
            candidates.extend(scope.replace(",", " ").split())
    resolved = tuple(dict.fromkeys(scope.strip() for scope in candidates if scope.strip()))
    return resolved or DEFAULT_GOOGLE_SCOPES


def load_socialdata_config(
    *,
    base_url: str | None = None,
    usession: str | None = None,
    google_access_token: str | None = None,
    google_service_account_file: str | None = None,
    google_scopes: str | list[str] | tuple[str, ...] | None = None,
    timeout_seconds: int | None = None,
) -> SocialDataConfig:
    resolved_base = (
        _normalize_text(base_url)
        or _normalize_text(os.getenv("SOCIALDATA_BASE_URL"))
        or DEFAULT_SOCIALDATA_BASE_URL
    ).rstrip("/")
    resolved_timeout = timeout_seconds or int(os.getenv("SOCIALDATA_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    return SocialDataConfig(
        base_url=resolved_base,
        graphql_url=f"{resolved_base}/graphql",
        timeout_seconds=resolved_timeout,
        usession=_normalize_text(usession) or _normalize_text(os.getenv("SOCIALDATA_USESSION")),
        google_access_token=(
            _normalize_text(google_access_token) or _normalize_text(os.getenv("SOCIALDATA_GOOGLE_ACCESS_TOKEN"))
        ),
        google_service_account_file=(
            _normalize_text(google_service_account_file)
            or _normalize_text(os.getenv("SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE"))
        ),
        google_scopes=_parse_google_scopes(google_scopes),
    )


def parse_usession_from_set_cookie(set_cookie_headers: list[str] | tuple[str, ...]) -> str:
    for header_value in set_cookie_headers:
        cookie = SimpleCookie()
        cookie.load(header_value)
        if "usession" in cookie:
            return cookie["usession"].value
    raise RuntimeError("Socialdata auth response did not include a usession cookie.")


def _token_prefix(token: str, *, width: int = 16) -> str:
    return token[:width]


def _token_suffix(token: str, *, width: int = 16) -> str:
    return token[-width:] if len(token) > width else token


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class SocialDataClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        usession: str | None = None,
        google_access_token: str | None = None,
        google_service_account_file: str | None = None,
        google_scopes: str | list[str] | tuple[str, ...] | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.config = load_socialdata_config(
            base_url=base_url,
            usession=usession,
            google_access_token=google_access_token,
            google_service_account_file=google_service_account_file,
            google_scopes=google_scopes,
            timeout_seconds=timeout_seconds,
        )

    @property
    def usession(self) -> str | None:
        return self.config.usession

    def with_usession(self, usession: str) -> "SocialDataClient":
        return SocialDataClient(
            base_url=self.config.base_url,
            usession=usession,
            google_service_account_file=self.config.google_service_account_file,
            google_scopes=self.config.google_scopes,
            timeout_seconds=self.config.timeout_seconds,
        )

    def refresh_google_access_token_from_service_account(self) -> str:
        return self.mint_google_access_token_from_service_account().access_token

    def mint_google_access_token_from_service_account(self) -> SocialDataGoogleAccessTokenResult:
        service_account_file = self.config.google_service_account_file
        if not service_account_file:
            raise RuntimeError(
                "A Google service-account credential file is required. "
                "Set SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE or pass --google-service-account-file."
            )

        credential_path = Path(service_account_file)
        if not credential_path.is_file():
            raise RuntimeError(f"Socialdata Google service-account file was not found: {credential_path}")

        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover - depends on runtime install
            raise RuntimeError(
                "google-auth is required for Socialdata service-account authentication. "
                "Install project dependencies again so the package is available."
            ) from exc

        credentials = service_account.Credentials.from_service_account_file(
            credential_path,
            scopes=list(self.config.google_scopes),
        )
        credentials.refresh(Request())
        token = _normalize_text(credentials.token)
        if not token:
            raise RuntimeError(
                "Google service-account authentication completed, but no access token was returned."
            )
        expiry_iso = credentials.expiry.isoformat() if credentials.expiry is not None else None
        return SocialDataGoogleAccessTokenResult(
            service_account_email=str(credentials.service_account_email),
            access_token=token,
            expiry_iso=expiry_iso,
            google_scopes=self.config.google_scopes,
        )

    def resolve_google_access_token(self, access_token: str | None = None) -> str:
        token = _normalize_text(access_token) or self.config.google_access_token
        if token:
            return token
        return self.refresh_google_access_token_from_service_account()

    def debug_google_token_exchange(
        self,
        access_token: str | None = None,
    ) -> SocialDataGoogleTokenExchangeDebugResult:
        explicit_token = _normalize_text(access_token) or self.config.google_access_token
        service_account_email: str | None = None
        token_source = "explicit_access_token"
        if explicit_token:
            token = explicit_token
        else:
            minted = self.mint_google_access_token_from_service_account()
            token = minted.access_token
            service_account_email = minted.service_account_email
            google_scopes: tuple[str, ...] | None = minted.google_scopes
            token_source = "service_account_file"
        if explicit_token:
            google_scopes = None

        exchange_endpoint = f"{self.config.base_url}/connect/google/callback"
        exchange_url = f"{exchange_endpoint}?{parse.urlencode({'access_token': token})}"
        req = request.Request(exchange_url, method="GET")
        opener = request.build_opener(_NoRedirectHandler)

        http_status = 0
        response_body: str | None = None
        set_cookie_headers: tuple[str, ...] = ()
        location: str | None = None
        try:
            with opener.open(req, timeout=self.config.timeout_seconds) as response:
                http_status = getattr(response, "status", 200)
                set_cookie_headers = tuple(response.headers.get_all("Set-Cookie") or ())
                location = response.headers.get("Location")
                try:
                    response_body = response.read().decode("utf-8", errors="replace")
                except Exception:
                    response_body = None
        except error.HTTPError as exc:
            http_status = exc.code
            response_body = exc.read().decode("utf-8", errors="replace")
            set_cookie_headers = tuple(exc.headers.get_all("Set-Cookie") or ())
            location = exc.headers.get("Location")
        except error.URLError as exc:
            response_body = str(exc.reason)

        try:
            usession = parse_usession_from_set_cookie(set_cookie_headers)
        except RuntimeError:
            usession = None

        return SocialDataGoogleTokenExchangeDebugResult(
            token_source=token_source,
            service_account_email=service_account_email,
            google_scopes=google_scopes,
            access_token_length=len(token),
            access_token_prefix=_token_prefix(token),
            access_token_suffix=_token_suffix(token),
            exchange_endpoint=exchange_endpoint,
            http_status=http_status,
            response_body=response_body,
            set_cookie_headers=set_cookie_headers,
            location=location,
            usession=usession,
        )

    def exchange_google_access_token(self, access_token: str | None = None) -> SocialDataAuthResult:
        token = self.resolve_google_access_token(access_token)
        if not token:
            raise RuntimeError(
                "A Google access token is required. Pass --google-access-token, "
                "set SOCIALDATA_GOOGLE_ACCESS_TOKEN, or configure SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE."
            )

        exchange_url = f"{self.config.base_url}/connect/google/callback?{parse.urlencode({'access_token': token})}"
        req = request.Request(exchange_url, method="GET")
        opener = request.build_opener(_NoRedirectHandler)
        try:
            with opener.open(req, timeout=self.config.timeout_seconds) as response:
                set_cookie_headers = tuple(response.headers.get_all("Set-Cookie") or ())
        except error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                set_cookie_headers = tuple(exc.headers.get_all("Set-Cookie") or ())
                usession = parse_usession_from_set_cookie(set_cookie_headers)
                return SocialDataAuthResult(
                    usession=usession,
                    set_cookie_headers=set_cookie_headers,
                    exchange_url=exchange_url,
                )
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Socialdata Google token exchange failed with HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Socialdata Google token exchange failed: {exc.reason}") from exc

        usession = parse_usession_from_set_cookie(set_cookie_headers)
        return SocialDataAuthResult(
            usession=usession,
            set_cookie_headers=set_cookie_headers,
            exchange_url=exchange_url,
        )

    def ensure_usession(self) -> str:
        if self.config.usession:
            return self.config.usession
        auth_result = self.exchange_google_access_token()
        return auth_result.usession

    def graphql(
        self,
        *,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
        usession: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query, "variables": variables or {}}
        if operation_name:
            payload["operationName"] = operation_name
        body = json.dumps(payload).encode("utf-8")

        cookie_value = _normalize_text(usession) or self.ensure_usession()
        req = request.Request(
            self.config.graphql_url,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "cookie": f"usession={cookie_value}",
            },
        )

        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Socialdata GraphQL request failed with HTTP {exc.code}: {body_text or exc.reason}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Socialdata GraphQL request failed: {exc.reason}") from exc

        parsed = json.loads(raw_body)
        if not isinstance(parsed, dict):
            raise RuntimeError("Socialdata GraphQL response was not a JSON object.")
        return parsed

    def auth_check(self, *, usession: str | None = None) -> dict[str, Any]:
        return self.graphql(query="query { __typename }", usession=usession)

    def introspect_schema(self, *, usession: str | None = None) -> dict[str, Any]:
        return self.graphql(query=INTROSPECTION_QUERY, usession=usession)

    @staticmethod
    def _require_object_field(response: dict[str, Any], field_name: str) -> dict[str, Any]:
        data = response.get("data")
        if isinstance(data, dict):
            payload = data.get(field_name)
            if isinstance(payload, dict):
                return payload
        errors = response.get("errors")
        if errors:
            raise RuntimeError(f"Socialdata GraphQL returned errors for {field_name}: {json.dumps(errors, ensure_ascii=False)}")
        raise RuntimeError(f"Socialdata GraphQL returned no object payload for {field_name}.")

    def app_by_slug(self, slug: str, *, usession: str | None = None) -> SocialDataApp:
        response = self.graphql(
            query="""
            query AppBySlug($slug: String!) {
              appBySlug(slug: $slug) {
                id
                slug
                name
              }
            }
            """,
            variables={"slug": slug},
            operation_name="AppBySlug",
            usession=usession,
        )
        payload = response.get("data", {}).get("appBySlug")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Socialdata appBySlug returned an unexpected payload for slug={slug!r}.")
        return SocialDataApp(
            id=int(payload["id"]),
            slug=str(payload["slug"]),
            name=str(payload["name"]),
        )

    def list_channels(
        self,
        *,
        app_id: int,
        page: int = 0,
        per_page: int = 100,
        sort_field: str | None = None,
        sort_order: str = "ASC",
        filter: dict[str, Any] | None = None,
        usession: str | None = None,
    ) -> tuple[list[SocialDataChannel], int]:
        response = self.graphql(
            query="""
            query ListChannels(
              $appId: UInt32!,
              $page: UInt32!,
              $perPage: UInt16!,
              $sortField: String,
              $sortOrder: OrderEnum,
              $filter: JSON
            ) {
              listChannel(
                appId: $appId,
                page: $page,
                perPage: $perPage,
                sortField: $sortField,
                sortOrder: $sortOrder,
                filter: $filter
              ) {
                total
                results {
                  id
                  plat
                  sub
                  alias
                  name
                  url
                  status
                  createdAt
                  tags
                  metrics
                }
              }
            }
            """,
            variables={
                "appId": app_id,
                "page": page,
                "perPage": per_page,
                "sortField": sort_field,
                "sortOrder": sort_order,
                "filter": filter,
            },
            operation_name="ListChannels",
            usession=usession,
        )
        payload = self._require_object_field(response, "listChannel")
        rows = payload.get("results") or []
        channels = [self._parse_channel(row) for row in rows if isinstance(row, dict)]
        return channels, int(payload.get("total") or 0)

    def iter_channels(
        self,
        *,
        app_id: int,
        per_page: int = 100,
        sort_field: str | None = None,
        sort_order: str = "ASC",
        filter: dict[str, Any] | None = None,
        usession: str | None = None,
    ) -> list[SocialDataChannel]:
        channels: list[SocialDataChannel] = []
        page = 0
        total = None
        while total is None or len(channels) < total:
            batch, batch_total = self.list_channels(
                app_id=app_id,
                page=page,
                per_page=per_page,
                sort_field=sort_field,
                sort_order=sort_order,
                filter=filter,
                usession=usession,
            )
            if total is None:
                total = batch_total
            if not batch:
                break
            channels.extend(batch)
            page += 1
        return channels

    def list_posts(
        self,
        *,
        app_id: int,
        page: int = 0,
        per_page: int = 100,
        sort_field: str | None = None,
        sort_order: str = "ASC",
        filter: dict[str, Any] | None = None,
        usession: str | None = None,
    ) -> tuple[list[SocialDataPost], int]:
        response = self.graphql(
            query="""
            query ListPosts(
              $appId: UInt32!,
              $page: UInt32!,
              $perPage: UInt16!,
              $sortField: String,
              $sortOrder: OrderEnum,
              $filter: JSON
            ) {
              listPost(
                appId: $appId,
                page: $page,
                perPage: $perPage,
                sortField: $sortField,
                sortOrder: $sortOrder,
                filter: $filter
              ) {
                total
                results {
                  id
                  channelId
                  sub
                  alias
                  type
                  name
                  url
                  tags
                  createdAt
                  thumbnail
                  metrics
                }
              }
            }
            """,
            variables={
                "appId": app_id,
                "page": page,
                "perPage": per_page,
                "sortField": sort_field,
                "sortOrder": sort_order,
                "filter": filter,
            },
            operation_name="ListPosts",
            usession=usession,
        )
        payload = self._require_object_field(response, "listPost")
        rows = payload.get("results") or []
        posts = [self._parse_post(row) for row in rows if isinstance(row, dict)]
        return posts, int(payload.get("total") or 0)

    def get_post(
        self,
        *,
        app_id: int,
        post_id: int,
        with_metrics: bool = True,
        metric_duration: int | None = None,
        usession: str | None = None,
    ) -> SocialDataPost:
        response = self.graphql(
            query="""
            query GetPost(
              $appId: UInt32!,
              $id: UInt32!,
              $withMetrics: Boolean,
              $metricDuration: UInt8
            ) {
              getPost(
                appId: $appId,
                id: $id,
                withMetrics: $withMetrics,
                metricDuration: $metricDuration
              ) {
                id
                channelId
                sub
                alias
                type
                name
                url
                tags
                createdAt
                thumbnail
                metrics
              }
            }
            """,
            variables={
                "appId": app_id,
                "id": post_id,
                "withMetrics": with_metrics,
                "metricDuration": metric_duration,
            },
            operation_name="GetPost",
            usession=usession,
        )
        payload = self._require_object_field(response, "getPost")
        return self._parse_post(payload)

    def _parse_channel(self, payload: dict[str, Any]) -> SocialDataChannel:
        metrics = payload.get("metrics")
        return SocialDataChannel(
            id=int(payload["id"]),
            plat=int(payload["plat"]) if payload.get("plat") is not None else None,
            sub=_normalize_text(str(payload["sub"])) if payload.get("sub") is not None else None,
            alias=_normalize_text(str(payload["alias"])) if payload.get("alias") is not None else None,
            name=str(payload.get("name") or ""),
            url=_normalize_text(str(payload["url"])) if payload.get("url") is not None else None,
            status=int(payload["status"]) if payload.get("status") is not None else None,
            created_at=_normalize_text(str(payload["createdAt"])) if payload.get("createdAt") is not None else None,
            tags=_normalize_text(str(payload["tags"])) if payload.get("tags") is not None else None,
            metrics=metrics if isinstance(metrics, dict) else None,
        )

    def _parse_post(self, payload: dict[str, Any]) -> SocialDataPost:
        metrics = payload.get("metrics")
        return SocialDataPost(
            id=int(payload["id"]),
            channel_id=int(payload["channelId"]) if payload.get("channelId") is not None else None,
            sub=_normalize_text(str(payload["sub"])) if payload.get("sub") is not None else None,
            alias=_normalize_text(str(payload["alias"])) if payload.get("alias") is not None else None,
            type=int(payload["type"]) if payload.get("type") is not None else None,
            name=str(payload.get("name") or ""),
            url=_normalize_text(str(payload["url"])) if payload.get("url") is not None else None,
            tags=_normalize_text(str(payload["tags"])) if payload.get("tags") is not None else None,
            created_at=_normalize_text(str(payload["createdAt"])) if payload.get("createdAt") is not None else None,
            thumbnail=_normalize_text(str(payload["thumbnail"])) if payload.get("thumbnail") is not None else None,
            metrics=metrics if isinstance(metrics, dict) else None,
        )


def read_query_text(*, query: str | None = None, query_file: str | Path | None = None) -> str:
    direct_query = _normalize_text(query)
    if direct_query:
        return direct_query
    if query_file is None:
        raise ValueError("A GraphQL query is required. Pass --query or --query-file.")
    return Path(query_file).read_text(encoding="utf-8")


def read_graphql_variables(
    *,
    variables_json: str | None = None,
    variables_file: str | Path | None = None,
) -> dict[str, Any] | None:
    if variables_file is not None:
        payload = json.loads(Path(variables_file).read_text(encoding="utf-8"))
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("GraphQL variables file must contain a JSON object.")
        return payload
    return _load_json_value(variables_json)
