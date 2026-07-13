"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ee_wiki.api.auth import warn_if_ingest_unprotected
from ee_wiki.api.deps import get_config, warmup_rag_service
from ee_wiki.api.routes.chat import router as chat_router
from ee_wiki.api.routes.components import router as components_router
from ee_wiki.api.routes.health import router as health_router
from ee_wiki.api.routes.ingest import router as ingest_router
from ee_wiki.api.routes.projects import router as projects_router
from ee_wiki.api.routes.query import router as query_router
from ee_wiki.api.routes.sources import router as sources_router
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    config = get_config()
    warn_if_ingest_unprotected(config)
    if config.api.warmup_on_startup:
        warmup_rag_service()
    yield


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns:
        Configured FastAPI app with health, query, and chat routes.
    """
    app = FastAPI(title="EE-Wiki", version="0.1.0", lifespan=_lifespan)
    app.include_router(health_router)
    app.include_router(sources_router)
    app.include_router(query_router)
    app.include_router(components_router)
    app.include_router(projects_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    logger.info("EE-Wiki API application created")
    return app
