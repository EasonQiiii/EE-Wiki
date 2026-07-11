"""Admin ingest route — orchestrates raw → processed → index."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ee_wiki.api.deps import get_config
from ee_wiki.api.models import IngestIssueModel, IngestRequest, IngestResponse
from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.pipeline import IngestionError, IngestRunResult, ingest_path
from ee_wiki.knowledge.indexer import build_index_from_processed

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["ingest"])


def _resolve_one_raw_path(path_str: str, config: AppConfig) -> Path:
    """Resolve a user path to an absolute path under ``config.raw_dir``.

    Args:
        path_str: Relative path, ``data/raw/...`` label, or absolute path.
        config: Application configuration.

    Returns:
        Resolved absolute path under the configured raw directory.

    Raises:
        IngestionError: If the path is outside ``raw_dir``.
    """
    raw_dir = config.raw_dir.resolve()
    stripped = path_str.strip()
    if not stripped:
        raise IngestionError("Path must not be empty")

    candidate = Path(stripped)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    elif stripped.startswith("data/raw/"):
        resolved = (config.repo_root / stripped).resolve()
    else:
        resolved = (raw_dir / stripped).resolve()

    try:
        resolved.relative_to(raw_dir)
    except ValueError as exc:
        raise IngestionError(
            f"Path must be under {raw_dir}: {path_str}"
        ) from exc
    return resolved


def resolve_ingest_targets(body: IngestRequest, config: AppConfig) -> list[Path]:
    """Map request filters to one or more ingest roots under ``data/raw/``.

    Args:
        body: Ingest request with optional path, paths, project, or build filters.
        config: Application configuration.

    Returns:
        Absolute paths to ingest (files or directories).

    Raises:
        IngestionError: If path resolution fails or filters conflict.
    """
    if body.path and body.paths:
        raise IngestionError("Provide either path or paths, not both")

    if body.paths:
        return [_resolve_one_raw_path(item, config) for item in body.paths]

    if body.path:
        return [_resolve_one_raw_path(body.path, config)]

    raw_dir = config.raw_dir.resolve()
    if body.project:
        if body.build:
            return [raw_dir / body.project / body.build]
        return [raw_dir / body.project]

    return [raw_dir]


def _merge_ingest_runs(runs: list[IngestRunResult]) -> IngestRunResult:
    """Combine multiple ingest runs into one aggregate result."""
    ingested = [item for run in runs for item in run.ingested]
    skipped = [item for run in runs for item in run.skipped]
    removed = [item for run in runs for item in run.removed]
    failed = [item for run in runs for item in run.failed]
    warnings = [item for run in runs for item in run.warnings]
    return IngestRunResult(
        ingested=ingested,
        skipped=skipped,
        removed=removed,
        failed=failed,
        warnings=warnings,
    )


def _issue_models(
    items: list,
    *,
    raw_dir: Path,
) -> list[IngestIssueModel]:
    """Map ingest failures or warnings to API issue models."""
    models: list[IngestIssueModel] = []
    for item in items:
        try:
            label = str(item.raw_path.resolve().relative_to(raw_dir.resolve()))
        except ValueError:
            label = item.raw_path.name
        models.append(IngestIssueModel(path=label, message=item.message))
    return models


def _run_ingest_sync(body: IngestRequest, config: AppConfig) -> IngestResponse:
    """Execute ingest and optional index build synchronously.

    Args:
        body: Ingest request parameters.
        config: Application configuration.

    Returns:
        Aggregated ingest and index statistics.

    Raises:
        IngestionError: When ingest targets are invalid or ingest fails.
        RuntimeError: When index build fails.
    """
    if body.ingest_only and body.index_only:
        raise IngestionError("Cannot use ingest_only and index_only together")

    ingest_run: IngestRunResult | None = None
    if not body.index_only:
        targets = resolve_ingest_targets(body, config)
        runs = [ingest_path(target, config, force=body.force) for target in targets]
        ingest_run = _merge_ingest_runs(runs)

    index_result = None
    if not body.ingest_only:
        index_result = build_index_from_processed(config, force=body.force)

    ingested_files = (
        [str(result.processed.content_path) for result in ingest_run.ingested]
        if ingest_run
        else []
    )
    removed_files = (
        [str(item.content_path) for item in ingest_run.removed]
        if ingest_run
        else []
    )

    return IngestResponse(
        ingested=len(ingest_run.ingested) if ingest_run else 0,
        skipped=len(ingest_run.skipped) if ingest_run else 0,
        removed=len(ingest_run.removed) if ingest_run else 0,
        failed=len(ingest_run.failed) if ingest_run else 0,
        warnings=len(ingest_run.warnings) if ingest_run else 0,
        ingested_files=ingested_files,
        removed_files=removed_files,
        failed_files=(
            _issue_models(ingest_run.failed, raw_dir=config.raw_dir)
            if ingest_run
            else []
        ),
        warning_files=(
            _issue_models(ingest_run.warnings, raw_dir=config.raw_dir)
            if ingest_run
            else []
        ),
        indexed_documents=index_result.indexed_documents if index_result else None,
        skipped_documents=index_result.skipped_documents if index_result else None,
        removed_documents=index_result.removed_documents if index_result else None,
        chunk_count=index_result.chunk_count if index_result else None,
    )


def _ingestion_http_status(exc: IngestionError) -> int:
    """Map ingestion errors to HTTP status codes."""
    message = str(exc).lower()
    if "does not exist" in message:
        return 404
    return 400


@router.post("/ingest", response_model=IngestResponse)
async def ingest_documents(
    body: IngestRequest,
    config: AppConfig = Depends(get_config),
) -> IngestResponse:
    """Trigger document ingestion and optional index build (admin)."""
    try:
        return await asyncio.to_thread(_run_ingest_sync, body, config)
    except IngestionError as exc:
        logger.error("Ingest failed: %s", exc)
        raise HTTPException(
            status_code=_ingestion_http_status(exc),
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        logger.error("Index build failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
