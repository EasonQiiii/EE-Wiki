"""Tests for Apple iWork ingest parsers."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ee_wiki.common.config import AppConfig, IworkConfig
from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.parsers.iwork import (
    IworkParserError,
    iwork_ingest_active,
    parse_keynote,
    parse_numbers,
)
from ee_wiki.ingestion.parsers.iwork.export import (
    _OPEN_WAIT_LOOPS,
    _export_opened_iwork_document,
    _maybe_clear_quarantine,
    _open_in_app,
    require_darwin,
)
from ee_wiki.ingestion.pipeline import IngestionError, ingest_file


@pytest.fixture
def iwork_config(app_config, tmp_path: Path) -> AppConfig:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    layout = replace(
        app_config.data_layout,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )
    return replace(
        app_config,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        data_layout=layout,
        iwork=IworkConfig(enabled=True),
    )


def test_iwork_ingest_active_requires_darwin_and_enabled() -> None:
    assert iwork_ingest_active(IworkConfig(enabled=True)) is (sys.platform == "darwin")
    assert iwork_ingest_active(IworkConfig(enabled=False)) is False


def test_parse_keynote_uses_original_metadata(iwork_config: AppConfig, tmp_path: Path) -> None:
    raw_path = iwork_config.raw_dir / "logan/p1/note/slides.key"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"fake-key")

    pdf_path = tmp_path / "slides.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    with (
        patch(
            "ee_wiki.ingestion.parsers.iwork.keynote.export_keynote_to_pdf",
            return_value=pdf_path,
        ),
        patch(
            "ee_wiki.ingestion.parsers.iwork.keynote.parse_prose_pdf",
        ) as mock_parse_pdf,
    ):
        mock_parse_pdf.return_value = StandardDocument(
            content="# slides\n\n## Page 1\n\nSlide body.\n",
            metadata=Metadata(
                project="logan",
                build="p1",
                document_type="engineering_note",
                title="slides",
                source_file="data/raw/logan/p1/note/slides.pdf",
            ),
            source_ref=str(pdf_path),
        )
        document = parse_keynote(raw_path, iwork_config.data_layout, iwork_config)

    assert document.metadata.source_file.endswith("slides.key")
    assert "Slide body." in document.content
    mock_parse_pdf.assert_called_once()
    call_kwargs = mock_parse_pdf.call_args.kwargs
    assert call_kwargs.get("metadata") is not None
    assert call_kwargs["metadata"].source_file.endswith("slides.key")


def test_parse_numbers_uses_original_metadata(iwork_config: AppConfig, tmp_path: Path) -> None:
    raw_path = iwork_config.raw_dir / "logan/p1/note/bom.numbers"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"fake-numbers")

    xlsx_path = tmp_path / "bom.xlsx"
    xlsx_path.write_bytes(b"fake-xlsx")

    with (
        patch(
            "ee_wiki.ingestion.parsers.iwork.numbers.export_numbers_to_xlsx",
            return_value=xlsx_path,
        ),
        patch(
            "ee_wiki.ingestion.parsers.iwork.numbers.parse_excel",
        ) as mock_parse_excel,
    ):
        mock_parse_excel.return_value = StandardDocument(
            content="# bom\n\n## Sheet: Parts\n\n| Part | Value |\n",
            metadata=Metadata(
                project="logan",
                build="p1",
                document_type="engineering_note",
                title="bom",
                source_file="data/raw/logan/p1/note/bom.xlsx",
            ),
            source_ref=str(xlsx_path),
        )
        document = parse_numbers(raw_path, iwork_config.data_layout, iwork_config)

    assert document.metadata.source_file.endswith("bom.numbers")
    assert "Sheet: Parts" in document.content
    mock_parse_excel.assert_called_once()
    call_kwargs = mock_parse_excel.call_args.kwargs
    assert call_kwargs.get("metadata") is not None
    assert call_kwargs["metadata"].source_file.endswith("bom.numbers")


def test_parse_keynote_disabled_raises(iwork_config: AppConfig) -> None:
    raw_path = iwork_config.raw_dir / "logan/p1/note/slides.key"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"fake-key")
    config = replace(iwork_config, iwork=IworkConfig(enabled=False))

    with pytest.raises(IworkParserError, match="disabled"):
        parse_keynote(raw_path, config.data_layout, config)


def test_require_darwin_raises_off_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ee_wiki.ingestion.parsers.iwork.export.sys.platform", "linux")
    with pytest.raises(IworkParserError, match="macOS"):
        require_darwin()


def test_open_wait_loops_is_one_minute() -> None:
    assert _OPEN_WAIT_LOOPS == 120


def test_maybe_clear_quarantine_ignores_missing_attribute(tmp_path: Path) -> None:
    source = tmp_path / "slides.key"
    source.write_bytes(b"fake-key")
    _maybe_clear_quarantine(source)


def test_open_in_app_uses_launchservices(tmp_path: Path) -> None:
    source = tmp_path / "slides.key"
    source.write_bytes(b"fake-key")
    with patch("ee_wiki.ingestion.parsers.iwork.export.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        _open_in_app("Keynote", source)
    command = mock_run.call_args.args[0]
    assert command[:3] == ["open", "-a", "Keynote"]
    assert command[3] == str(source.resolve())


def test_export_opened_iwork_document_orchestrates_open_then_osascript(
    tmp_path: Path,
) -> None:
    source = tmp_path / "slides.key"
    source.write_bytes(b"fake-key")
    dest = tmp_path / "slides.pdf"
    with (
        patch("ee_wiki.ingestion.parsers.iwork.export._maybe_clear_quarantine") as mock_clear,
        patch(
            "ee_wiki.ingestion.parsers.iwork.export._iwork_document_count",
            return_value=0,
        ) as mock_count,
        patch("ee_wiki.ingestion.parsers.iwork.export._open_in_app") as mock_open,
        patch("ee_wiki.ingestion.parsers.iwork.export._run_osascript") as mock_osascript,
    ):
        _export_opened_iwork_document(
            app_name="Keynote",
            script="script",
            source=source,
            dest=dest,
            quit_after=False,
            timeout=600,
        )
    mock_clear.assert_called_once_with(source.resolve())
    mock_count.assert_called_once_with("Keynote")
    mock_open.assert_called_once_with("Keynote", source.resolve())
    mock_osascript.assert_called_once()
    assert mock_osascript.call_args.args[1] == str(source.resolve())
    assert mock_osascript.call_args.args[5] == str(_OPEN_WAIT_LOOPS)


def test_ingest_file_key_mocked(iwork_config: AppConfig, tmp_path: Path) -> None:
    raw_path = iwork_config.raw_dir / "logan/p1/note/slides.key"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"fake-key")

    with patch(
        "ee_wiki.ingestion.pipeline.parse_keynote",
    ) as mock_parse:
        mock_parse.return_value = StandardDocument(
            content="# slides\n\nDeck text.\n",
            metadata=Metadata(
                project="logan",
                build="p1",
                document_type="engineering_note",
                title="slides",
                source_file="data/raw/logan/p1/note/slides.key",
            ),
            source_ref=str(raw_path),
        )
        result = ingest_file(raw_path, iwork_config)

    assert result.processed.content_path.name == "slides.md"
    assert "Deck text." in result.processed.content_path.read_text(encoding="utf-8")


def test_ingest_file_key_maps_parser_error(iwork_config: AppConfig) -> None:
    raw_path = iwork_config.raw_dir / "logan/p1/note/slides.key"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"fake-key")

    with (
        patch(
            "ee_wiki.ingestion.pipeline.parse_keynote",
            side_effect=IworkParserError("Keynote missing"),
        ),
        pytest.raises(IngestionError, match="Keynote missing"),
    ):
        ingest_file(raw_path, iwork_config)
