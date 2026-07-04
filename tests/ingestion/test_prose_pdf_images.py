"""Tests for prose PDF image extraction, filtering, and description."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.ingestion.parsers.prose_pdf import parse_prose_pdf
from ee_wiki.ingestion.parsers.prose_pdf.images import (
    ExtractedImage,
    _content_hash,
    _image_slug,
    extract_and_filter_images,
    extract_page_images,
    save_images,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_png_bytes(width: int = 100, height: int = 100, color: str = "red") -> bytes:
    """Create a tiny valid PNG for testing."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow required")
    buf = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _mock_page(native_text: str) -> MagicMock:
    page = MagicMock()
    page.get_text.side_effect = lambda mode="text", textpage=None: native_text
    page.get_textpage_ocr.side_effect = AssertionError("OCR should not run")
    page.get_images.return_value = []
    return page


# ---------------------------------------------------------------------------
# Unit tests — images.py helpers
# ---------------------------------------------------------------------------

def test_image_slug_normalizes() -> None:
    assert _image_slug("Board Rev A V1.0") == "board_rev_a_v1_0"
    assert _image_slug("simple") == "simple"
    assert _image_slug("") == "prose"


def test_content_hash_stable() -> None:
    data = b"hello world"
    assert _content_hash(data) == _content_hash(data)
    assert len(_content_hash(data)) == 16


def test_content_hash_differs_for_different_data() -> None:
    assert _content_hash(b"aaa") != _content_hash(b"bbb")


# ---------------------------------------------------------------------------
# Unit tests — extract_page_images
# ---------------------------------------------------------------------------

def test_extract_page_images_filters_by_area() -> None:
    png = _make_png_bytes(200, 200)
    small_png = _make_png_bytes(5, 5)

    doc = MagicMock()
    page = MagicMock()
    doc.__getitem__ = MagicMock(return_value=page)
    page.get_images.return_value = [
        (1, 0, 200, 200, 8, "DeviceRGB", "", "", "", 0),
        (2, 0, 5, 5, 8, "DeviceRGB", "", "", "", 0),
    ]
    doc.extract_image.side_effect = lambda xref: {
        1: {"width": 200, "height": 200, "image": png, "ext": "png"},
        2: {"width": 5, "height": 5, "image": small_png, "ext": "png"},
    }.get(xref)

    with patch("ee_wiki.ingestion.parsers.prose_pdf.images.fitz", create=True):
        result = extract_page_images(doc, 0, min_area=100, max_images=10)

    assert len(result) == 1
    assert result[0][1] == 200


def test_extract_page_images_respects_max() -> None:
    png = _make_png_bytes(200, 200)
    doc = MagicMock()
    page = MagicMock()
    doc.__getitem__ = MagicMock(return_value=page)
    page.get_images.return_value = [
        (i, 0, 200, 200, 8, "DeviceRGB", "", "", "", 0) for i in range(5)
    ]
    doc.extract_image.return_value = {
        "width": 200, "height": 200, "image": png, "ext": "png",
    }

    with patch("ee_wiki.ingestion.parsers.prose_pdf.images.fitz", create=True):
        result = extract_page_images(doc, 0, min_area=100, max_images=2)

    assert len(result) == 2


def test_extract_page_images_empty_when_no_images() -> None:
    doc = MagicMock()
    page = MagicMock()
    doc.__getitem__ = MagicMock(return_value=page)
    page.get_images.return_value = []

    result = extract_page_images(doc, 0, min_area=100, max_images=5)
    assert result == []


# ---------------------------------------------------------------------------
# Unit tests — extract_and_filter_images (dedup)
# ---------------------------------------------------------------------------

def test_dedup_removes_template_images() -> None:
    """Images appearing on >dedup_max_pages pages are dropped."""
    png_logo = _make_png_bytes(100, 100, "blue")
    png_content = _make_png_bytes(100, 100, "green")

    doc = MagicMock()
    doc.page_count = 4

    def mock_getitem(idx: int) -> MagicMock:
        page = MagicMock()
        if idx < 3:
            page.get_images.return_value = [
                (1, 0, 100, 100, 8, "DeviceRGB", "", "", "", 0),
            ]
        else:
            page.get_images.return_value = [
                (2, 0, 100, 100, 8, "DeviceRGB", "", "", "", 0),
            ]
        return page

    doc.__getitem__ = MagicMock(side_effect=mock_getitem)
    doc.extract_image.side_effect = lambda xref: {
        1: {"width": 100, "height": 100, "image": png_logo, "ext": "png"},
        2: {"width": 100, "height": 100, "image": png_content, "ext": "png"},
    }.get(xref)

    with patch("ee_wiki.ingestion.parsers.prose_pdf.images.fitz", create=True):
        result = extract_and_filter_images(
            doc,
            page_limit=4,
            source_stem="test",
            min_area=100,
            max_images_per_page=5,
            dedup_max_pages=2,
        )

    assert len(result) == 1
    assert result[0].png_bytes == png_content


def test_dedup_keeps_unique_images() -> None:
    """Each unique image appears once regardless of page."""
    png_a = _make_png_bytes(100, 100, "red")
    png_b = _make_png_bytes(100, 100, "blue")

    doc = MagicMock()
    doc.page_count = 2

    def mock_getitem(idx: int) -> MagicMock:
        page = MagicMock()
        xref = idx + 1
        page.get_images.return_value = [
            (xref, 0, 100, 100, 8, "DeviceRGB", "", "", "", 0),
        ]
        return page

    doc.__getitem__ = MagicMock(side_effect=mock_getitem)
    doc.extract_image.side_effect = lambda xref: {
        1: {"width": 100, "height": 100, "image": png_a, "ext": "png"},
        2: {"width": 100, "height": 100, "image": png_b, "ext": "png"},
    }.get(xref)

    with patch("ee_wiki.ingestion.parsers.prose_pdf.images.fitz", create=True):
        result = extract_and_filter_images(
            doc,
            page_limit=2,
            source_stem="test",
            min_area=100,
            max_images_per_page=5,
            dedup_max_pages=3,
        )

    assert len(result) == 2


# ---------------------------------------------------------------------------
# Unit tests — save_images
# ---------------------------------------------------------------------------

def test_save_images_writes_files(tmp_path: Path) -> None:
    png = _make_png_bytes(50, 50)
    images = [
        ExtractedImage(
            page=1, index=0, png_bytes=png,
            width=50, height=50,
            content_hash="abc123", filename="test_p1_img0.png",
        ),
    ]
    out_dir = tmp_path / "images" / "test"
    save_images(images, out_dir)

    assert (out_dir / "test_p1_img0.png").exists()
    assert (out_dir / "test_p1_img0.png").read_bytes() == png


def test_save_images_noop_when_empty(tmp_path: Path) -> None:
    out_dir = tmp_path / "images" / "empty"
    save_images([], out_dir)
    assert not out_dir.exists()


# ---------------------------------------------------------------------------
# Integration — _build_markdown with images
# ---------------------------------------------------------------------------

def test_build_markdown_includes_image_refs() -> None:
    from ee_wiki.ingestion.parsers.prose_pdf import _build_markdown
    from ee_wiki.ingestion.parsers.prose_pdf.extract import PageText

    pages = [PageText(page=1, text="Body text here.", method="text")]
    images = [
        ExtractedImage(
            page=1, index=0, png_bytes=b"png",
            width=100, height=100,
            content_hash="aaa", filename="doc_p1_img0.png",
        ),
    ]
    descriptions = {"doc_p1_img0.png": "DC-DC buck converter block diagram"}

    md = _build_markdown(
        "Test Doc",
        pages,
        images=images,
        descriptions=descriptions,
        images_rel_prefix="images",
        source_slug="doc",
    )

    assert "![doc_p1_img0.png](images/doc/doc_p1_img0.png)" in md
    assert "> DC-DC buck converter block diagram" in md
    assert "Body text here." in md


def test_build_markdown_no_images_unchanged() -> None:
    from ee_wiki.ingestion.parsers.prose_pdf import _build_markdown
    from ee_wiki.ingestion.parsers.prose_pdf.extract import PageText

    pages = [PageText(page=1, text="Just text.", method="text")]
    md = _build_markdown("Title", pages)
    assert "![" not in md
    assert "Just text." in md


# ---------------------------------------------------------------------------
# Integration — parse_prose_pdf with images
# ---------------------------------------------------------------------------

@pytest.fixture
def ingest_config(app_config: AppConfig, tmp_path: Path) -> AppConfig:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    layout = replace(
        app_config.data_layout,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )
    return replace(app_config, raw_dir=raw_dir, processed_dir=processed_dir, data_layout=layout)


def test_parse_prose_pdf_extracts_images(ingest_config: AppConfig) -> None:
    """End-to-end: images are extracted, described, and referenced in markdown."""
    raw_path = ingest_config.raw_dir / "logan/p1/note/report.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    png_data = _make_png_bytes(200, 200, "green")

    mock_doc = MagicMock()
    mock_doc.page_count = 1

    page_mock = MagicMock()
    page_mock.get_text.side_effect = lambda mode="text", textpage=None: (
        "Engineering report body with sufficient embedded text for extraction."
    )
    page_mock.get_textpage_ocr.side_effect = AssertionError("OCR should not run")
    page_mock.get_images.return_value = [
        (1, 0, 200, 200, 8, "DeviceRGB", "", "", "", 0),
    ]
    mock_doc.__getitem__.return_value = page_mock
    mock_doc.extract_image.return_value = {
        "width": 200, "height": 200, "image": png_data, "ext": "png",
    }

    cfg_with_images = replace(
        ingest_config,
        prose_pdf=replace(
            ingest_config.prose_pdf,
            extract_images=True,
            describe_images="off",
            min_image_area=100,
        ),
    )

    with patch("ee_wiki.ingestion.parsers.prose_pdf.fitz") as mock_fitz:
        mock_fitz.open.return_value = mock_doc
        document = parse_prose_pdf(
            raw_path, cfg_with_images.data_layout, cfg_with_images,
        )

    assert "![" in document.content
    assert "report_p1_img0.png" in document.content


def test_parse_prose_pdf_skips_images_when_disabled(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/note/noimages.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    mock_doc = MagicMock()
    mock_doc.page_count = 1
    mock_doc.__getitem__.return_value = _mock_page(
        "Plain text document with enough embedded text."
    )

    cfg_no_images = replace(
        ingest_config,
        prose_pdf=replace(ingest_config.prose_pdf, extract_images=False),
    )

    with patch("ee_wiki.ingestion.parsers.prose_pdf.fitz") as mock_fitz:
        mock_fitz.open.return_value = mock_doc
        document = parse_prose_pdf(
            raw_path, cfg_no_images.data_layout, cfg_no_images,
        )

    assert "![" not in document.content


def test_re_ingest_clears_stale_images(ingest_config: AppConfig) -> None:
    """Re-ingesting a PDF removes old images before saving new ones."""
    raw_path = ingest_config.raw_dir / "logan/p1/note/refresh.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    images_dir = (
        ingest_config.processed_dir / "logan/p1/note/images/refresh"
    )
    images_dir.mkdir(parents=True)
    stale = images_dir / "refresh_p3_img2.png"
    stale.write_bytes(b"OLD-PNG-FROM-PREVIOUS-INGEST")

    new_png = _make_png_bytes(200, 200, "yellow")

    mock_doc = MagicMock()
    mock_doc.page_count = 1
    page_mock = MagicMock()
    page_mock.get_text.side_effect = (
        lambda mode="text", textpage=None: "Body with enough text for prose."
    )
    page_mock.get_textpage_ocr.side_effect = AssertionError("no OCR")
    page_mock.get_images.return_value = [
        (1, 0, 200, 200, 8, "DeviceRGB", "", "", "", 0),
    ]
    mock_doc.__getitem__.return_value = page_mock
    mock_doc.extract_image.return_value = {
        "width": 200, "height": 200, "image": new_png, "ext": "png",
    }

    cfg = replace(
        ingest_config,
        prose_pdf=replace(
            ingest_config.prose_pdf,
            extract_images=True,
            describe_images="off",
            min_image_area=100,
        ),
    )

    with patch("ee_wiki.ingestion.parsers.prose_pdf.fitz") as mock_fitz:
        mock_fitz.open.return_value = mock_doc
        parse_prose_pdf(raw_path, cfg.data_layout, cfg)

    assert not stale.exists(), "stale image from previous ingest should be gone"
    new_files = list(images_dir.iterdir())
    assert len(new_files) == 1
    assert new_files[0].name == "refresh_p1_img0.png"
    assert new_files[0].read_bytes() == new_png
