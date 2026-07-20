"""Canonicalize REST ``product`` / ``project`` / ``build`` query or body filters."""

from __future__ import annotations

from fastapi import HTTPException

from ee_wiki.common.config import AppConfig
from ee_wiki.common.errors import ScopeValidationError
from ee_wiki.common.project_aliases import canonicalize_scope_filters


def resolve_request_scope(
    config: AppConfig,
    product: str | None,
    project: str | None,
    build: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Apply ``data_layout.project_aliases`` and reject ambiguous partial scopes.

    Fully unscoped requests (all ``None``) remain allowed for inventory / global
    search. A request that sets ``project`` or ``build`` without ``product`` is
    rejected with HTTP 400.

    Args:
        config: Loaded application configuration.
        product: Optional product from the HTTP request.
        project: Optional project from the HTTP request.
        build: Optional build from the HTTP request.

    Returns:
        Canonical ``(product, project, build)`` for retrieval / graph / rules.

    Raises:
        HTTPException: 400 when ``project``/``build`` is set without ``product``.
    """
    try:
        return canonicalize_scope_filters(
            product,
            project,
            build,
            aliases=config.data_layout.project_aliases,
            require_product=True,
        )
    except ScopeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
