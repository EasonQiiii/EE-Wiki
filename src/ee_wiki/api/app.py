"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from ee_wiki.api.routes.chat import router as chat_router
from ee_wiki.api.routes.health import router as health_router
from ee_wiki.api.routes.query import router as query_router
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns:
        Configured FastAPI app with health, query, and chat routes.
    """
    app = FastAPI(title="EE-Wiki", version="0.1.0")
    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(chat_router)
    logger.info("EE-Wiki API application created")
    return app
