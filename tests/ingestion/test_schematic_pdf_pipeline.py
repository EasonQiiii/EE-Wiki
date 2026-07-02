"""Tests for schematic PDF ingest routing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
from ee_wiki.ingestion.pipeline import IngestionError, ingest_file


@pytest.fixture
def ingest_config(app_config, tmp_path: Path) -> AppConfig:
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
    return replace(
        app_config,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        data_layout=layout,
        models=models,
        schematic_pdf=replace(app_config.schematic_pdf, fidelity_mode="vlm_plus_ocr"),
    )


def test_pdf_in_note_folder_rejected(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/note/doc.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")
    with pytest.raises(IngestionError, match="sch/ only"):
        ingest_file(raw_path, ingest_config)


def test_schematic_pdf_ingest_with_mock_engine(ingest_config: AppConfig, monkeypatch) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/sch/board.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    mock_layout = MagicMock()
    mock_layout.analyze_page.return_value = PageLayoutResult(
        page=1,
        raw_ocr_text="U0902 VBAT",
        crop_image_bytes=b"png",
        slice_filenames=["board_p1_crop_0.png"],
    )

    mock_vision = MagicMock()
    mock_vision.extract_page.return_value = PageExtraction(
        page=1,
        markdown="## 1. 模块图纸基本信息\nPMIC section",
        major_components=["U0902"],
        nets=["VBAT"],
        interfaces=["I2C1"],
    )

    monkeypatch.setattr(
        "ee_wiki.ingestion.parsers.schematic_pdf.build_layout_engine",
        lambda *_args, **_kwargs: mock_layout,
    )
    monkeypatch.setattr(
        "ee_wiki.ingestion.parsers.schematic_pdf.build_vision_engine",
        lambda *_args, **_kwargs: mock_vision,
    )
    mock_fitz = MagicMock()
    mock_fitz.open.return_value = MagicMock(page_count=1, close=MagicMock())
    monkeypatch.setattr("ee_wiki.ingestion.parsers.schematic_pdf.fitz", mock_fitz)

    result = ingest_file(raw_path, ingest_config)
    assert result.processed.content_path.suffix == ".md"
    assert result.processed.content_path.name == "board.md"
    meta_path = result.processed.metadata_path
    import json

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["document_type"] == "schematic"
    assert meta["target_file"].endswith("logan/p1/sch/board.md")
    assert meta["major_components"] == ["U0902"]
    assert meta["nets"] == ["VBAT"]
