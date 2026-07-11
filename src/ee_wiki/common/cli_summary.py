"""Colored CLI summaries for batch ingest and sync runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ee_wiki.ingestion.pipeline import IngestRunResult

_RESET = "\033[0m"
_ERROR = "\033[31m"
_WARNING = "\033[33m"
_BOLD = "\033[1m"


def _use_color(stream: object | None = None) -> bool:
    """Return whether CLI summary lines should include ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("EE_WIKI_LOG_COLOR") == "0":
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("EE_WIKI_LOG_COLOR") == "1":
        return True
    target = stream if stream is not None else sys.stderr
    return hasattr(target, "isatty") and target.isatty()


def _style(text: str, color: str, *, stream: object | None = None) -> str:
    if not _use_color(stream):
        return text
    return f"{color}{text}{_RESET}"


def _relative_label(raw_path: Path, raw_dir: Path) -> str:
    try:
        return str(raw_path.resolve().relative_to(raw_dir.resolve()))
    except ValueError:
        return raw_path.name


def print_ingest_run_summary(
    run: IngestRunResult,
    *,
    raw_dir: Path,
    stream: object | None = None,
) -> bool:
    """Print ingest outcome summary with colored errors and warnings.

    Args:
        run: Batch ingest result.
        raw_dir: Configured raw directory for relative path labels.
        stream: Output stream (defaults to stderr).

    Returns:
        ``True`` when the run had failures or deferred-file warnings.
    """
    out = stream or sys.stderr
    has_issues = bool(run.failed or run.warnings)

    print("", file=out)
    print(
        _style("=== Ingest summary ===", _BOLD, stream=out),
        file=out,
    )
    print(
        (
            f"Ingested: {len(run.ingested)}, "
            f"skipped (unchanged): {len(run.skipped)}, "
            f"removed (raw deleted): {len(run.removed)}, "
            f"failed: {len(run.failed)}, "
            f"warnings: {len(run.warnings)}"
        ),
        file=out,
    )

    if run.failed:
        print(
            _style(f"ERRORS ({len(run.failed)}):", _ERROR, stream=out),
            file=out,
        )
        for failure in run.failed:
            label = _relative_label(failure.raw_path, raw_dir)
            print(
                _style(f"  {label}: {failure.message}", _ERROR, stream=out),
                file=out,
            )

    if run.warnings:
        print(
            _style(f"WARNINGS ({len(run.warnings)}):", _WARNING, stream=out),
            file=out,
        )
        for warning in run.warnings:
            label = _relative_label(warning.raw_path, raw_dir)
            print(
                _style(f"  {label}: {warning.message}", _WARNING, stream=out),
                file=out,
            )

    if has_issues:
        print(
            _style(
                "Ingest finished with issues; successful files were still processed.",
                _WARNING,
                stream=out,
            ),
            file=out,
        )

    return has_issues
