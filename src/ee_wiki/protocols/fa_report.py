"""Abstract interface for FA one-page Keynote report generation (ADR 0010)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class FaReportRequest:
    """Inputs for generating an FA one-page summary."""

    radar_id: str
    project: str | None = None
    build: str | None = None
    title: str | None = None
    fail_items: tuple[str, ...] = ()
    true_fail_notes: str | None = None
    root_cause: str | None = None
    steps: tuple[str, ...] = ()
    extra: dict[str, Any] | None = None


@dataclass(frozen=True)
class FaReportResult:
    """Generated FA report artifact."""

    radar_id: str
    output_path: Path
    download_rel_path: str  # under data/exports/, e.g. fa/123/FA_summary.key
    template_used: Path | None = None
    notes: str = ""


class FaReportBackend(Protocol):
    """Generate company-template Keynote FA summaries under ``data/exports/fa/``."""

    def generate(self, request: FaReportRequest) -> FaReportResult:
        """Fill the company template and write ``FA_summary.key``.

        Args:
            request: Structured FA fields for the one-pager.

        Returns:
            Paths and download-relative location for ``GET /v1/exports/...``.
        """
        ...
