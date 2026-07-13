"""In-process async ingest job store and runner.

Jobs live in memory for the lifetime of a single FastAPI process. They are
not durable across server restarts. Concurrent running jobs are bounded to
avoid GPU thrash during VLM ingest.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from ee_wiki.common.logging import get_logger

if TYPE_CHECKING:
    from ee_wiki.api.models import IngestRequest, IngestResponse
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)


class IngestJobStatus(StrEnum):
    """Lifecycle states for an async ingest job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).isoformat()


@dataclass
class IngestJobRecord:
    """Mutable record for one ingest job."""

    job_id: str
    status: IngestJobStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: IngestResponse | None = None


@dataclass
class IngestJobManager:
    """Thread-safe in-memory job store with bounded concurrent runners.

    Args:
        max_concurrent: Maximum jobs allowed to run at once (default 1).
        run_fn: Callable that executes the sync ingest pipeline.
    """

    max_concurrent: int = 1
    run_fn: Callable[[IngestRequest, AppConfig], IngestResponse] | None = None
    _jobs: dict[str, IngestJobRecord] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _semaphore: threading.Semaphore = field(init=False)
    _active_threads: list[threading.Thread] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._semaphore = threading.Semaphore(self.max_concurrent)

    def submit(
        self,
        body: IngestRequest,
        config: AppConfig,
    ) -> IngestJobRecord:
        """Enqueue an ingest job and start a background worker thread.

        Args:
            body: Ingest request parameters.
            config: Application configuration snapshot for the job.

        Returns:
            The newly created job record (status ``queued``).

        Raises:
            RuntimeError: If ``run_fn`` was not configured.
        """
        if self.run_fn is None:
            raise RuntimeError("IngestJobManager.run_fn is not configured")

        job_id = str(uuid4())
        created_at = _utc_now_iso()
        record = IngestJobRecord(
            job_id=job_id,
            status=IngestJobStatus.QUEUED,
            created_at=created_at,
        )
        with self._lock:
            self._jobs[job_id] = record

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, body, config),
            name=f"ingest-job-{job_id[:8]}",
            daemon=True,
        )
        with self._lock:
            self._active_threads.append(thread)
        thread.start()
        logger.info(
            "Accepted ingest job %s (max_concurrent=%s)",
            job_id,
            self.max_concurrent,
        )
        # Snapshot at accept time so the 202 body stays ``queued`` even if the
        # worker advances status before the response is serialized.
        return IngestJobRecord(
            job_id=job_id,
            status=IngestJobStatus.QUEUED,
            created_at=created_at,
        )

    def get(self, job_id: str) -> IngestJobRecord | None:
        """Return a job record by id, or ``None`` if unknown.

        Args:
            job_id: Job identifier from submit.

        Returns:
            Snapshot-safe copy of the job record, or ``None``.
        """
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            return IngestJobRecord(
                job_id=record.job_id,
                status=record.status,
                created_at=record.created_at,
                started_at=record.started_at,
                finished_at=record.finished_at,
                error=record.error,
                result=record.result,
            )

    def reset(self) -> None:
        """Clear all jobs (intended for tests)."""
        with self._lock:
            self._jobs.clear()
            self._active_threads.clear()

    def _run_job(
        self,
        job_id: str,
        body: IngestRequest,
        config: AppConfig,
    ) -> None:
        """Acquire a concurrency slot, run the pipeline, update job state."""
        assert self.run_fn is not None
        self._semaphore.acquire()
        try:
            self._set_running(job_id)
            try:
                result = self.run_fn(body, config)
            except Exception as exc:
                logger.error("Ingest job %s failed: %s", job_id, exc)
                self._set_failed(job_id, str(exc))
            else:
                self._set_succeeded(job_id, result)
                logger.info("Ingest job %s succeeded", job_id)
        finally:
            self._semaphore.release()
            with self._lock:
                current = threading.current_thread()
                self._active_threads = [
                    t for t in self._active_threads if t is not current
                ]

    def _set_running(self, job_id: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = IngestJobStatus.RUNNING
            record.started_at = _utc_now_iso()

    def _set_succeeded(self, job_id: str, result: IngestResponse) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = IngestJobStatus.SUCCEEDED
            record.finished_at = _utc_now_iso()
            record.result = result
            record.error = None

    def _set_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = IngestJobStatus.FAILED
            record.finished_at = _utc_now_iso()
            record.error = error
            record.result = None


_manager: IngestJobManager | None = None
_manager_lock = threading.Lock()


def get_ingest_job_manager(
    *,
    max_concurrent: int,
    run_fn: Callable[[IngestRequest, AppConfig], IngestResponse],
) -> IngestJobManager:
    """Return the process-wide ingest job manager, creating it if needed.

    Args:
        max_concurrent: Concurrent job limit from config (used on first create).
        run_fn: Sync pipeline callable wired by the ingest route.

    Returns:
        Shared ``IngestJobManager`` singleton.
    """
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = IngestJobManager(
                max_concurrent=max_concurrent,
                run_fn=run_fn,
            )
        elif _manager.run_fn is None:
            _manager.run_fn = run_fn
        return _manager


def reset_ingest_job_manager() -> None:
    """Drop the process-wide manager (for tests)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.reset()
        _manager = None
