"""Serve FA exports and cached Flames/Radar artifacts for browser download."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ee_wiki.api.deps import get_config
from ee_wiki.common.config import AppConfig

router = APIRouter(prefix="/v1", tags=["exports"])


def _resolve_under(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` safely under ``root``."""
    cleaned = rel_path.lstrip("/")
    if not cleaned or cleaned.startswith(".."):
        raise HTTPException(status_code=404, detail="Not found")
    base = root.resolve()
    candidate = (base / cleaned).resolve()
    if not candidate.is_relative_to(base):
        raise HTTPException(status_code=404, detail="Not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return candidate


@router.get("/exports/{file_path:path}")
def get_export_file(
    file_path: str,
    config: AppConfig = Depends(get_config),
) -> FileResponse:
    """Download a file under ``data/exports/`` (e.g. FA Keynote summary).

    Typical FA path: ``/v1/exports/fa/{radar_id}/FA_summary.key``.
    """
    path = _resolve_under(config.exports_dir, file_path)
    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        filename=path.name,
    )


@router.get("/cache/{file_path:path}")
def get_cache_file(
    file_path: str,
    config: AppConfig = Depends(get_config),
) -> FileResponse:
    """Download a cached FA artifact under ``data/cache/`` (e.g. Flames logs).

    Typical path: ``/v1/cache/fa/{radar_id}/smt_ict.log``.
    """
    path = _resolve_under(config.cache_dir, file_path)
    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        filename=path.name,
    )
