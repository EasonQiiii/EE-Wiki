"""Serve processed documents and assets for citation links."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ee_wiki.api.deps import get_config
from ee_wiki.common.config import AppConfig

router = APIRouter(prefix="/v1", tags=["sources"])


def _resolve_processed_path(config: AppConfig, rel_path: str) -> Path:
    """Resolve a processed-relative path safely under ``data/processed/``."""
    cleaned = rel_path.lstrip("/")
    if not cleaned or cleaned.startswith(".."):
        raise HTTPException(status_code=404, detail="Not found")

    processed_dir = config.processed_dir.resolve()
    candidate = (processed_dir / cleaned).resolve()
    if not candidate.is_relative_to(processed_dir):
        raise HTTPException(status_code=404, detail="Not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return candidate


@router.get("/sources/{file_path:path}")
def get_source_document(
    file_path: str,
    config: AppConfig = Depends(get_config),
) -> FileResponse:
    """Return a processed Markdown or text document for citation links."""
    path = _resolve_processed_path(config, file_path)
    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "text/markdown",
        filename=path.name,
    )


@router.get("/assets/{file_path:path}")
def get_processed_asset(
    file_path: str,
    config: AppConfig = Depends(get_config),
) -> FileResponse:
    """Return an image or other asset stored under ``data/processed/``."""
    path = _resolve_processed_path(config, file_path)
    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        filename=path.name,
    )
