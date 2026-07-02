"""Locate local Tesseract binaries and tessdata for offline prose PDF OCR."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

_TESSERACT_CANDIDATES = (
    Path("/opt/homebrew/bin/tesseract"),
    Path("/usr/local/bin/tesseract"),
    Path("/usr/bin/tesseract"),
)

_TESSDATA_CANDIDATES = (
    Path("/opt/homebrew/share/tessdata"),
    Path("/usr/local/share/tessdata"),
    Path("/usr/share/tesseract-ocr/4.00/tessdata"),
    Path("/usr/share/tesseract-ocr/5/tessdata"),
    Path("/usr/share/tessdata"),
)


def _is_tessdata_dir(path: Path) -> bool:
    return path.is_dir() and (path / "eng.traineddata").is_file()


def resolve_tesseract_binary() -> str | None:
    """Return a Tesseract executable path when available on the host.

    Returns:
        Absolute path to ``tesseract``, or ``None`` when not found.
    """
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in _TESSERACT_CANDIDATES:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def resolve_tessdata_dir(configured: str | Path | None = None) -> str | None:
    """Return a tessdata directory usable by PyMuPDF OCR.

    Resolution order:

    1. Explicit config path
    2. ``TESSDATA_PREFIX`` environment variable
    3. Common Homebrew / Linux install locations

    Args:
        configured: Optional path from ``ingestion.prose_pdf.tessdata_dir``.

    Returns:
        Absolute tessdata directory, or ``None`` when not found.
    """
    if configured:
        path = Path(configured).expanduser()
        if _is_tessdata_dir(path):
            return str(path.resolve())
        logger.warning("Configured tessdata_dir is missing eng.traineddata: %s", path)

    env_prefix = os.environ.get("TESSDATA_PREFIX", "").strip()
    if env_prefix:
        path = Path(env_prefix).expanduser()
        if _is_tessdata_dir(path):
            return str(path.resolve())
        logger.warning("TESSDATA_PREFIX does not contain eng.traineddata: %s", path)

    for candidate in _TESSDATA_CANDIDATES:
        if _is_tessdata_dir(candidate):
            resolved = str(candidate.resolve())
            logger.debug("Using tessdata directory: %s", resolved)
            return resolved

    return None


def tesseract_env(tessdata_dir: str | None) -> dict[str, str]:
    """Build subprocess environment with tessdata and tesseract hints.

    Args:
        tessdata_dir: Resolved tessdata directory.

    Returns:
        Environment mapping for ``subprocess.run``.
    """
    env = os.environ.copy()
    if tessdata_dir:
        env["TESSDATA_PREFIX"] = tessdata_dir
    binary = resolve_tesseract_binary()
    if binary:
        binary_dir = str(Path(binary).parent)
        env["PATH"] = f"{binary_dir}{os.pathsep}{env.get('PATH', '')}"
    return env
