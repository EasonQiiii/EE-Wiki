"""Locate LibreOffice and convert legacy Word documents to PDF."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

_MAC_SOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


class LibreOfficeError(EEWikiError):
    """LibreOffice is missing or conversion failed."""


def resolve_soffice_path(configured: Path | None = None) -> Path:
    """Return the LibreOffice ``soffice`` binary path.

    Resolution order: explicit config path, ``EE_WIKI_LIBREOFFICE_PATH``,
    ``PATH``, then the default macOS app bundle location.

    Args:
        configured: Optional path from ``ingestion.word.libreoffice_path``.

    Returns:
        Resolved ``soffice`` executable.

    Raises:
        LibreOfficeError: When no usable binary is found.
    """
    candidates: list[Path] = []
    env_override = os.environ.get("EE_WIKI_LIBREOFFICE_PATH")
    if env_override:
        candidates.append(Path(env_override).expanduser())
    if configured is not None:
        candidates.append(configured.expanduser())
    found = shutil.which("soffice")
    if found:
        candidates.append(Path(found))
    candidates.append(_MAC_SOFFICE)

    for candidate in candidates:
        path = candidate.resolve()
        if path.is_file() and os.access(path, os.X_OK):
            logger.debug("Using LibreOffice binary: %s", path)
            return path

    raise LibreOfficeError(
        "LibreOffice (soffice) not found. Install LibreOffice and ensure `soffice` "
        "is on PATH, or set ingestion.word.libreoffice_path / EE_WIKI_LIBREOFFICE_PATH."
    )


def convert_to_pdf(
    source: Path,
    *,
    soffice: Path,
    out_dir: Path,
) -> Path:
    """Convert a legacy ``.doc`` file to PDF via headless LibreOffice.

    Args:
        source: Input ``.doc`` path.
        soffice: Resolved LibreOffice binary.
        out_dir: Directory for the converted PDF.

    Returns:
        Path to the generated PDF.

    Raises:
        LibreOfficeError: If conversion fails or output is missing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(soffice),
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(source.resolve()),
    ]
    logger.info("Converting %s to PDF via LibreOffice", source.name)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except OSError as exc:
        raise LibreOfficeError(f"Failed to run LibreOffice: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LibreOfficeError(f"LibreOffice conversion timed out for {source.name}") from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise LibreOfficeError(
            f"LibreOffice failed to convert {source.name} (exit {completed.returncode}): {stderr}"
        )

    pdf_path = out_dir / f"{source.stem}.pdf"
    if not pdf_path.is_file():
        raise LibreOfficeError(f"LibreOffice did not produce expected PDF: {pdf_path}")
    return pdf_path
