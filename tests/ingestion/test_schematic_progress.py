"""Tests for schematic PDF ingest progress logging."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.ingestion.parsers.schematic_pdf import parse_schematic_pdf
from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction


@pytest.fixture
def schematic_config(app_config, tmp_path: Path) -> AppConfig:
    from dataclasses import replace

    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    layout = replace(
        app_config.data_layout,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )
    models = replace(
        app_config.models,
        base_dir=tmp_path / "models",
        visual_model=tmp_path / "models" / "Qwen3-VL-8B-Instruct",
        layout_model=tmp_path / "models" / "layoutlmv3-base",
    )
    schematic_config = replace(
        app_config,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        data_layout=layout,
        models=models,
        schematic_pdf=replace(
            app_config.schematic_pdf,
            max_pages=2,
            fidelity_mode="vlm_plus_ocr",
        ),
    )
    return schematic_config


def test_parse_schematic_pdf_logs_page_progress(
    schematic_config: AppConfig,
    caplog: pytest.LogCaptureFixture,
    monkeypatch,
) -> None:
    raw_path = schematic_config.raw_dir / "iphone/logan/p1/sch/board.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    mock_layout = MagicMock()
    mock_layout.analyze_page.side_effect = [
        PageLayoutResult(page=1, raw_ocr_text="a", crop_image_bytes=None, slice_filenames=[]),
        PageLayoutResult(page=2, raw_ocr_text="b", crop_image_bytes=None, slice_filenames=[]),
    ]
    mock_vision = MagicMock()
    mock_vision.extract_page.side_effect = [
        PageExtraction(page=1, markdown="p1", major_components=[], nets=[], interfaces=[]),
        PageExtraction(page=2, markdown="p2", major_components=[], nets=[], interfaces=[]),
    ]

    monkeypatch.setattr(
        "ee_wiki.ingestion.parsers.schematic_pdf.build_layout_engine",
        lambda *_args, **_kwargs: mock_layout,
    )
    monkeypatch.setattr(
        "ee_wiki.ingestion.parsers.schematic_pdf.build_vision_engine",
        lambda *_args, **_kwargs: mock_vision,
    )
    mock_fitz = MagicMock()
    mock_fitz.open.return_value = MagicMock(page_count=2, close=MagicMock())
    monkeypatch.setattr("ee_wiki.ingestion.parsers.schematic_pdf.fitz", mock_fitz)

    with caplog.at_level("INFO"):
        parse_schematic_pdf(raw_path, schematic_config.data_layout, schematic_config)

    messages = " ".join(record.message for record in caplog.records)
    assert "page 1/2" in messages.lower() or "page 1/2 —" in messages
    assert mock_layout.analyze_page.call_count == 2
    assert mock_vision.extract_page.call_count == 2
