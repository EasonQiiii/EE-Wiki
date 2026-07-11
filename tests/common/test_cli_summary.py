"""Tests for colored CLI ingest summaries."""

from __future__ import annotations

import io
from pathlib import Path

from ee_wiki.common.cli_summary import print_ingest_run_summary
from ee_wiki.ingestion.pipeline import IngestFailure, IngestRunResult
from ee_wiki.ingestion.sync import RawFileWarning


def test_print_ingest_run_summary_reports_failures_and_warnings(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    failed_path = raw_dir / "global/note/missing.key"
    warning_path = raw_dir / "global/note/archive.zip"
    run = IngestRunResult(
        failed=[IngestFailure(raw_path=failed_path, message="Not a file")],
        warnings=[
            RawFileWarning(
                raw_path=warning_path,
                message="unsupported raw file format",
            )
        ],
    )

    stream = io.StringIO()
    has_issues = print_ingest_run_summary(run, raw_dir=raw_dir, stream=stream)
    output = stream.getvalue()

    assert has_issues is True
    assert "ERRORS (1):" in output
    assert "global/note/missing.key: Not a file" in output
    assert "WARNINGS (1):" in output
    assert "global/note/archive.zip: unsupported raw file format" in output
    assert "finished with issues" in output


def test_print_ingest_run_summary_clean_run(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    stream = io.StringIO()
    has_issues = print_ingest_run_summary(IngestRunResult(), raw_dir=raw_dir, stream=stream)
    output = stream.getvalue()

    assert has_issues is False
    assert "failed: 0" in output
    assert "ERRORS" not in output
