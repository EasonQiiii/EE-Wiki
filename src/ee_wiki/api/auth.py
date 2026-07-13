"""Optional API-key checks for admin HTTP routes."""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request

from ee_wiki.api.deps import get_config
from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

_UNAUTHORIZED_DETAIL = "Invalid or missing ingest API key"


def extract_ingest_api_key(request: Request) -> str | None:
    """Read the ingest API key from ``X-API-Key`` or ``Authorization: Bearer``.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Presented key string, or ``None`` when neither header provides one.
    """
    header_key = request.headers.get("x-api-key")
    if header_key is not None and header_key.strip():
        return header_key.strip()

    authorization = request.headers.get("authorization")
    if authorization is None:
        return None
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


def require_ingest_api_key(
    request: Request,
    config: AppConfig = Depends(get_config),
) -> None:
    """Enforce ``EE_WIKI_INGEST_API_KEY`` when configured.

    When ``config.api.ingest_api_key`` is unset, the request is allowed (open
    ingest for local development). When set, the client must send a matching
    ``X-API-Key`` or ``Authorization: Bearer`` header.

    Args:
        request: Incoming FastAPI request.
        config: Application configuration.

    Raises:
        HTTPException: 401 when a key is required but missing or incorrect.
    """
    expected = config.api.ingest_api_key
    if not expected:
        return

    presented = extract_ingest_api_key(request)
    if presented is None or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED_DETAIL)


def warn_if_ingest_unprotected(config: AppConfig) -> None:
    """Log a warning when ingest is open on a LAN-facing bind address.

    Args:
        config: Application configuration.
    """
    if config.api.ingest_api_key:
        return
    host = (config.api.host or "").strip().lower()
    if host in {"0.0.0.0", "::", "[::]"}:
        logger.warning(
            "POST /v1/ingest is open (EE_WIKI_INGEST_API_KEY unset) while "
            "api.host=%s; set EE_WIKI_INGEST_API_KEY before exposing on LAN.",
            config.api.host,
        )
