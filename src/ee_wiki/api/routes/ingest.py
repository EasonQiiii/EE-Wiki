"""Admin ingest route — orchestrates raw → processed → index."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ee_wiki.api.auth import require_ingest_api_key
from ee_wiki.api.deps import get_config
from ee_wiki.api.ingest_jobs import get_ingest_job_manager
from ee_wiki.api.models import (
    IngestIssueModel,
    IngestJobAccepted,
    IngestJobStatusResponse,
    IngestRequest,
    IngestResponse,
)
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


def _validate_ingest_request(body: IngestRequest, config: AppConfig) -> None:
    """Raise ``IngestionError`` for conflicting flags or invalid path targets.

    Args:
        body: Ingest request to validate.
        config: Application configuration.

    Raises:
        IngestionError: When flags conflict or path targets cannot be resolved.
    """
    if body.ingest_only and body.index_only:
        raise IngestionError("Cannot use ingest_only and index_only together")
    if not body.index_only:
        resolve_ingest_targets(body, config)


def _job_status_url(job_id: str, config: AppConfig) -> str:
    """Build the poll URL for an ingest job.

    Args:
        job_id: Accepted job identifier.
        config: Application configuration (uses ``public_base_url`` when set).

    Returns:
        Absolute or root-relative status URL.
    """
    path = f"/v1/ingest/jobs/{job_id}"
    base = (config.api.public_base_url or "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def _job_manager(config: AppConfig):
    """Return the shared ingest job manager wired to the sync pipeline."""
    return get_ingest_job_manager(
        max_concurrent=config.api.max_concurrent_ingest_jobs,
        run_fn=_run_ingest_sync,
    )


@router.post(
    "/ingest",
    response_model=None,
    responses={
        200: {"model": IngestResponse},
        202: {"model": IngestJobAccepted},
    },
    dependencies=[Depends(require_ingest_api_key)],
)
async def ingest_documents(
    body: IngestRequest,
    config: AppConfig = Depends(get_config),
) -> IngestResponse | JSONResponse:
    """Trigger document ingestion and optional index build (admin).

    Default is synchronous (200 + counts). Set ``async: true`` to accept a
    background job (202) and poll ``GET /v1/ingest/jobs/{job_id}``.
    """
    try:
        _validate_ingest_request(body, config)
    except IngestionError as exc:
        logger.error("Ingest request invalid: %s", exc)
        raise HTTPException(
            status_code=_ingestion_http_status(exc),
            detail=str(exc),
        ) from exc

    if body.async_mode:
        manager = _job_manager(config)
        record = manager.submit(body, config)
        accepted = IngestJobAccepted(
            job_id=record.job_id,
            status=record.status.value,
            status_url=_job_status_url(record.job_id, config),
        )
        return JSONResponse(
            status_code=202,
            content=accepted.model_dump(),
        )

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


@router.get(
    "/ingest/jobs/{job_id}",
    response_model=IngestJobStatusResponse,
    dependencies=[Depends(require_ingest_api_key)],
)
async def get_ingest_job(
    job_id: str,
    config: AppConfig = Depends(get_config),
) -> IngestJobStatusResponse:
    """Return status (and result when finished) for an async ingest job.

    Jobs are stored in-process only and are lost on server restart.
    """
    manager = _job_manager(config)
    record = manager.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown ingest job: {job_id}")
    return IngestJobStatusResponse(
        job_id=record.job_id,
        status=record.status.value,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error=record.error,
        result=record.result,
    )
