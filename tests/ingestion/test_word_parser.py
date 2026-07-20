"""Tests for Word document ingest."""

from __future__ import annotations

import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.parsers.word import WordParserError, parse_word
from ee_wiki.ingestion.parsers.word.docx import parse_docx
from ee_wiki.ingestion.parsers.word.libreoffice import LibreOfficeError, resolve_soffice_path
from ee_wiki.ingestion.pipeline import ingest_file

_OVERRIDE = (
    'PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"'
)
_CONTENT_TYPES = f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override {_OVERRIDE}/>
</Types>"""

_REL_TARGET = "word/document.xml"
_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
_RELS = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="{_REL_TYPE}" Target="{_REL_TARGET}"/>
</Relationships>"""

_WORD_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""


def _write_minimal_docx(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", _WORD_RELS)


@pytest.fixture
def word_config(app_config, tmp_path: Path) -> AppConfig:
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
        repo_root=app_config.repo_root,
    )


def test_parse_docx_extracts_text(word_config: AppConfig) -> None:
    raw_path = word_config.raw_dir / "global/datasheet/wm8978.docx"
    _write_minimal_docx(raw_path, "WM8978 中文 datasheet excerpt")

    document = parse_docx(raw_path, word_config.data_layout, repo_root=word_config.repo_root)

    assert document.metadata.project == "global"
    assert document.metadata.build == "global"
    assert document.metadata.document_type == "datasheet"
    assert "WM8978" in document.content
    assert "中文" in document.content


def test_ingest_file_writes_docx_mirror(word_config: AppConfig) -> None:
    raw_path = word_config.raw_dir / "global/datasheet/wm8978.docx"
    _write_minimal_docx(raw_path, "PMIC register map")

    result = ingest_file(raw_path, word_config)
    assert result.processed.content_path.suffix == ".md"
    assert "PMIC register map" in result.processed.content_path.read_text(encoding="utf-8")


def test_parse_legacy_doc_uses_libreoffice_and_prose_pdf(
    word_config: AppConfig, tmp_path: Path
) -> None:
    raw_path = word_config.raw_dir / "global/datasheet/wm8978.doc"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"legacy-doc-bytes")

    pdf_path = tmp_path / "wm8978.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% fake pdf for test\n")

    with (
        patch(
            "ee_wiki.ingestion.parsers.word.legacy_doc.resolve_soffice_path",
            return_value=Path("/usr/bin/soffice"),
        ),
        patch(
            "ee_wiki.ingestion.parsers.word.legacy_doc.convert_to_pdf",
            return_value=pdf_path,
        ),
        patch(
            "ee_wiki.ingestion.parsers.word.legacy_doc.parse_prose_pdf",
        ) as mock_parse_pdf,
    ):
        mock_parse_pdf.return_value = StandardDocument(
            content="# wm8978\n\n## Page 1\n\nConverted body text.\n",
            metadata=Metadata(
                product="global",
                project="global",
                build="global",
                document_type="datasheet",
                title="wm8978",
                source_file="data/raw/global/datasheet/wm8978.pdf",
            ),
            source_ref=str(pdf_path),
        )
        document = parse_word(raw_path, word_config.data_layout, word_config)

    assert document.metadata.source_file.endswith("wm8978.doc")
    assert "Converted body text." in document.content
    mock_parse_pdf.assert_called_once()
    call_kwargs = mock_parse_pdf.call_args.kwargs
    assert call_kwargs.get("metadata") is not None
    assert call_kwargs["metadata"].source_file.endswith("wm8978.doc")


def test_resolve_soffice_path_honors_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "soffice"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("EE_WIKI_LIBREOFFICE_PATH", str(fake))
    assert resolve_soffice_path() == fake.resolve()


def test_parse_legacy_doc_requires_libreoffice(word_config: AppConfig) -> None:
    raw_path = word_config.raw_dir / "global/datasheet/missing.doc"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"legacy")

    with (
        patch(
            "ee_wiki.ingestion.parsers.word.legacy_doc.resolve_soffice_path",
            side_effect=LibreOfficeError("LibreOffice not found"),
        ),
        pytest.raises(WordParserError, match="LibreOffice not found"),
    ):
        parse_word(raw_path, word_config.data_layout, word_config)
