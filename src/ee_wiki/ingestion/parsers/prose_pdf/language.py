"""OCR language selection for prose PDF pages."""

from __future__ import annotations

import re
import subprocess
import tempfile
from typing import TYPE_CHECKING

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.prose_pdf.tesseract_paths import (
    resolve_tesseract_binary,
    tesseract_env,
)

if TYPE_CHECKING:
    import fitz

logger = get_logger(__name__)

_CJK_RANGES = (
    (0x3400, 0x4DBF),  # Extension A
    (0x4E00, 0x9FFF),  # Unified
    (0xF900, 0xFAFF),  # Compatibility
)
_OSD_SCRIPT_PATTERN = re.compile(r"^Script:\s+(\S+)", re.MULTILINE)
_BILINGUAL_TESSERACT_LANG = "eng+chi_sim"
_LATIN_TESSERACT_LANG = "eng"
_HAN_SCRIPTS = frozenset({"Han", "Hani", "Chinese"})
_LATIN_SCRIPTS = frozenset({"Latin"})


def is_cjk_character(char: str) -> bool:
    """Return whether ``char`` is a CJK ideograph."""
    if not char:
        return False
    code = ord(char)
    return any(start <= code <= end for start, end in _CJK_RANGES)


def cjk_character_ratio(text: str) -> float:
    """Return the share of script-bearing characters that are CJK.

    Args:
        text: Sample text from embedded PDF content or OCR output.

    Returns:
        Ratio in ``[0.0, 1.0]``. Zero when no script characters are present.
    """
    script_chars = [char for char in text if char.isalpha() or is_cjk_character(char)]
    if not script_chars:
        return 0.0
    cjk_count = sum(1 for char in script_chars if is_cjk_character(char))
    return cjk_count / len(script_chars)


def language_from_text_sample(text: str, *, cjk_threshold: float = 0.05) -> str:
    """Pick a Tesseract language pack from embedded text.

    Args:
        text: Combined embedded text sample.
        cjk_threshold: Minimum CJK ratio to enable bilingual OCR.

    Returns:
        ``eng+chi_sim`` when CJK is present, otherwise ``eng``.
    """
    if cjk_character_ratio(text) >= cjk_threshold:
        return _BILINGUAL_TESSERACT_LANG
    return _LATIN_TESSERACT_LANG


def _map_osd_script(script: str) -> str:
    normalized = script.strip()
    if normalized in _HAN_SCRIPTS:
        return _BILINGUAL_TESSERACT_LANG
    if normalized in _LATIN_SCRIPTS:
        return _LATIN_TESSERACT_LANG
    logger.debug("Unknown OSD script %r; using bilingual OCR fallback", normalized)
    return _BILINGUAL_TESSERACT_LANG


def detect_language_from_osd(
    page: fitz.Page,
    *,
    ocr_dpi: int,
    tessdata_dir: str | None = None,
) -> str | None:
    """Detect page script with Tesseract OSD.

    Args:
        page: Open PyMuPDF page handle.
        ocr_dpi: Render resolution for the OSD probe image.

    Returns:
        Tesseract language code, or ``None`` when OSD is unavailable.
    """
    binary = resolve_tesseract_binary()
    if binary is None:
        return None

    try:
        import fitz
    except ImportError:
        return None

    try:
        matrix = fitz.Matrix(ocr_dpi / 72.0, ocr_dpi / 72.0)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        with tempfile.NamedTemporaryFile(suffix=".png") as handle:
            pixmap.save(handle.name)
            completed = subprocess.run(
                [binary, handle.name, "stdout", "--psm", "0", "-l", "osd"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=tesseract_env(tessdata_dir),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Tesseract OSD probe failed: %s", exc)
        return None

    if completed.returncode != 0:
        logger.debug(
            "Tesseract OSD exited %d: %s",
            completed.returncode,
            completed.stderr.strip() or completed.stdout.strip(),
        )
        return None

    match = _OSD_SCRIPT_PATTERN.search(completed.stdout)
    if match is None:
        return None
    script = _map_osd_script(match.group(1))
    logger.info("Tesseract OSD selected OCR language %s (script=%s)", script, match.group(1))
    return script


def resolve_document_ocr_language(
    document: fitz.Document,
    *,
    page_limit: int,
    configured_language: str,
    fallback_language: str,
    ocr_dpi: int,
    cjk_threshold: float = 0.05,
    tessdata_dir: str | None = None,
) -> str:
    """Resolve OCR language for a PDF before per-page extraction.

    When ``configured_language`` is ``auto``:

    1. Sample embedded text across pages and enable bilingual OCR when CJK appears.
    2. For image-only PDFs, run Tesseract OSD on the first page.
    3. Fall back to ``fallback_language`` when script cannot be inferred.

    Args:
        document: Open PyMuPDF document.
        page_limit: Number of pages to inspect.
        configured_language: User setting, or ``auto``.
        fallback_language: Language used when auto-detection cannot decide.
        ocr_dpi: Render resolution for OSD probing.
        cjk_threshold: Minimum CJK ratio in embedded text for bilingual OCR.

    Returns:
        Tesseract language code for OCR fallback pages.
    """
    if configured_language.casefold() != "auto":
        return configured_language

    samples: list[str] = []
    for page_index in range(page_limit):
        sample = document[page_index].get_text("text").strip()
        if sample:
            samples.append(sample)

    if samples:
        combined = "\n".join(samples)
        resolved = language_from_text_sample(combined, cjk_threshold=cjk_threshold)
        logger.info(
            "Prose PDF OCR language auto-detected as %s from embedded text",
            resolved,
        )
        return resolved

    osd_language = detect_language_from_osd(
        document[0],
        ocr_dpi=ocr_dpi,
        tessdata_dir=tessdata_dir,
    )
    if osd_language is not None:
        return osd_language

    logger.info(
        "Prose PDF OCR language falling back to %s (no embedded text, OSD unavailable)",
        fallback_language,
    )
    return fallback_language


def resolve_page_ocr_language(
    page: fitz.Page,
    *,
    configured_language: str,
    document_language: str,
    cjk_threshold: float = 0.05,
) -> str:
    """Resolve OCR language for one page that needs OCR.

    In ``auto`` mode, sparse embedded text on the page can override the
    document default so mixed-language PDFs OCR each page appropriately.

    Args:
        page: Open PyMuPDF page handle.
        configured_language: User setting, or ``auto``.
        document_language: Language inferred for the whole document.
        cjk_threshold: Minimum CJK ratio for bilingual OCR.

    Returns:
        Tesseract language code for this page.
    """
    if configured_language.casefold() != "auto":
        return configured_language

    native = page.get_text("text").strip()
    if native:
        return language_from_text_sample(native, cjk_threshold=cjk_threshold)
    return document_language
