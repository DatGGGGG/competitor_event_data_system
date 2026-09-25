from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from .api_keys import key_matches_store

API_KEY_ENV_VAR = "VN_EVENT_DW_API_KEY"
API_KEYS_FILE_ENV_VAR = "VN_EVENT_DW_API_KEYS_FILE"
API_KEY_HEADER = "X-API-Key"
PUBLIC_API_PATHS = {"/api/v2/health", "/api/events/v2/health"}
PUBLIC_SCHEMA_PATHS = {"/openapi.json"}
ADMIN_UI_PREFIX = "/api/events/admin"
WORKSPACE_ADMIN_PREFIX = "/workspaces/tracked-games/events"


def api_key_from_env() -> str:
    return os.getenv(API_KEY_ENV_VAR, "").strip()


def api_keys_file_from_env() -> Path | None:
    value = os.getenv(API_KEYS_FILE_ENV_VAR, "").strip()
    return Path(value) if value else None


def api_key_auth_enabled() -> bool:
    return bool(api_key_from_env() or api_keys_file_from_env())


def _request_api_key(request: Request) -> str:
    header_key = request.headers.get(API_KEY_HEADER, "").strip()
    if header_key:
        return header_key

    auth_header = request.headers.get("Authorization", "").strip()
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return ""


def _is_valid_api_key(provided_key: str) -> bool:
    expected_key = api_key_from_env()
    if expected_key and secrets.compare_digest(provided_key, expected_key):
        return True

    keys_file = api_keys_file_from_env()
    if keys_file is not None and keys_file.exists():
        return key_matches_store(keys_file, api_key=provided_key)
    return False


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Protect public read APIs when an API key env setting is configured."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # The Portal imports this schema server-to-server. It contains only
        # public contract metadata; credentials and runtime configuration are
        # never inserted into it.
        if request.url.path in PUBLIC_SCHEMA_PATHS:
            return await call_next(request)
        # The operational admin UI has its own password session and lives in
        # the Event namespace to avoid colliding with the central Portal.
        if request.url.path.startswith((ADMIN_UI_PREFIX, WORKSPACE_ADMIN_PREFIX)):
            return await call_next(request)
        if not api_key_auth_enabled() or not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.url.path in PUBLIC_API_PATHS:
            return await call_next(request)

        provided_key = _request_api_key(request)
        if not provided_key:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Missing API key. Send it in the {API_KEY_HEADER} header."},
                headers={"WWW-Authenticate": "ApiKey"},
            )
        if not _is_valid_api_key(provided_key):
            return JSONResponse(status_code=403, content={"detail": "Invalid API key."})

        return await call_next(request)
