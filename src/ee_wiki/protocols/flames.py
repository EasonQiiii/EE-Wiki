"""Abstract interface for Flames assembly/test lookup (FA sessions; ADR 0010)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class FlamesUnitRef:
    """Resolved manufacturing / test unit identity in Flames."""

    unit_id: str
    serial: str | None = None
    radar_id: str | None = None


@dataclass(frozen=True)
class TestRecord:
    """One station test attempt with optional remote log locator."""

    record_id: str
    station: str
    stage: str | None = None
    result: str | None = None
    started_at: str | None = None
    log_uri: str | None = None


@dataclass(frozen=True)
class FailItem:
    """One error item extracted from a test log.

    ``source`` records where the item came from so the check-in reply can show
    provenance and enforce evidence priority (Radar face first, Flames last):
    ``radar_title`` | ``radar_text`` | ``radar_attachment`` | ``flames`` |
    ``user_paste``. ``None`` means unspecified (legacy / stub).
    """

    message: str
    station: str | None = None
    record_id: str | None = None
    log_rel_path: str | None = None
    line_no: int | None = None
    source: str | None = None


@dataclass(frozen=True)
class FailItemsResult:
    """Aggregated fail items plus cached log paths for download links."""

    unit: FlamesUnitRef
    records: tuple[TestRecord, ...]
    fail_items: tuple[FailItem, ...]
    cached_logs: tuple[str, ...]  # paths relative to cache root (e.g. fa/{id}/x.log)
    source: str = "flames"  # flames | stub | manual
    needs_user_input: bool = False
    user_prompt: str | None = None


class FlamesBackend(Protocol):
    """Read Flames test history and logs for FA triage."""

    def resolve_unit(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
    ) -> FlamesUnitRef:
        """Resolve a Flames unit from Radar id and/or serial.

        Args:
            radar_id: FA session Radar id.
            serial: Optional unit serial when known.

        Returns:
            Flames unit reference.
        """
        ...

    def list_test_records(self, unit: FlamesUnitRef) -> list[TestRecord]:
        """List station test attempts for ``unit``."""
        ...

    def fetch_log(self, record: TestRecord, dest_dir: Path) -> Path:
        """Download a raw log for ``record`` into ``dest_dir``.

        Args:
            record: Test attempt with log locator.
            dest_dir: Directory to write the log file into.

        Returns:
            Absolute path to the cached log file.
        """
        ...

    def extract_errors(self, log_path: Path) -> list[FailItem]:
        """Extract all reported error items from ``log_path``.

        Args:
            log_path: Local cached log file.

        Returns:
            Fail items (phase 1: all errors; no true-fail judgment).
        """
        ...

    def collect_fail_items(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
        cache_dir: Path,
    ) -> FailItemsResult:
        """Resolve unit, fetch logs into ``cache_dir``, and extract errors.

        Args:
            radar_id: FA session Radar id.
            serial: Optional serial override.
            cache_dir: Directory for cached logs (typically ``data/cache/fa/{id}/``).

        Returns:
            Aggregated fail items and relative cache paths for download URLs.
        """
        ...
