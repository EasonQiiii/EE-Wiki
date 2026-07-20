"""Keynote FA one-pager generation (stub copies/fills template placeholder)."""

from __future__ import annotations

import shutil
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.paths import (
    fa_export_dir,
    fa_summary_download_rel,
    fa_summary_path,
    normalize_radar_id,
)
from ee_wiki.protocols.fa_report import FaReportRequest, FaReportResult

logger = get_logger(__name__)

_PLACEHOLDER_NOTE = (
    "EE-Wiki FA summary placeholder.\n"
    "Replace assets/templates/fa/one_page.key with the company template, "
    "then implement real Keynote fill (macOS / AppleScript).\n"
)


class StubKeynoteFaReportBackend:
    """Write a downloadable FA summary artifact under ``data/exports/fa/``.

    When a company ``.key`` template exists, it is copied to the export path.
    Otherwise a UTF-8 placeholder file with the same name is written so the
    download URL and Open WebUI link can be tested offline.
    """

    def __init__(
        self,
        *,
        exports_dir: Path,
        template_path: Path | None = None,
    ) -> None:
        """Configure export root and optional template.

        Args:
            exports_dir: Absolute ``data/exports`` directory.
            template_path: Optional company ``.key`` template path.
        """
        self.exports_dir = exports_dir
        self.template_path = template_path

    def generate(self, request: FaReportRequest) -> FaReportResult:
        """Create ``FA_summary.key`` for ``request.radar_id``.

        Args:
            request: Structured FA fields for the one-pager.

        Returns:
            Export path and download-relative location.
        """
        rid = normalize_radar_id(request.radar_id)
        out_dir = fa_export_dir(self.exports_dir, rid)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = fa_summary_path(self.exports_dir, rid)
        template_used: Path | None = None
        notes: str

        if self.template_path is not None and self.template_path.is_file():
            shutil.copy2(self.template_path, out_path)
            template_used = self.template_path
            sidecar = out_dir / "FA_summary.fields.txt"
            sidecar.write_text(_format_fields(request), encoding="utf-8")
            notes = (
                "Copied company Keynote template; field merge not yet "
                f"implemented. Structured fields written to {sidecar.name}."
            )
        else:
            out_path.write_text(
                _PLACEHOLDER_NOTE + "\n" + _format_fields(request),
                encoding="utf-8",
            )
            notes = (
                "No company template at assets/templates/fa/one_page.key; "
                "wrote placeholder FA_summary.key for download testing."
            )

        logger.info("FA summary written for radar %s → %s", rid, out_path)
        return FaReportResult(
            radar_id=rid,
            output_path=out_path,
            download_rel_path=fa_summary_download_rel(rid),
            template_used=template_used,
            notes=notes,
        )


def _format_fields(request: FaReportRequest) -> str:
    """Render FA fields as plain text for placeholder / sidecar."""
    lines = [
        f"radar_id: {request.radar_id}",
        f"project: {request.project or ''}",
        f"build: {request.build or ''}",
        f"title: {request.title or ''}",
        f"true_fail_notes: {request.true_fail_notes or ''}",
        f"root_cause: {request.root_cause or ''}",
        "fail_items:",
    ]
    for item in request.fail_items:
        lines.append(f"  - {item}")
    lines.append("steps:")
    for step in request.steps:
        lines.append(f"  - {step}")
    return "\n".join(lines) + "\n"
