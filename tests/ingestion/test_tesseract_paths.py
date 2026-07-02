"""Tests for Tesseract path auto-detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ee_wiki.ingestion.parsers.prose_pdf.tesseract_paths import (
    resolve_tessdata_dir,
    resolve_tesseract_binary,
)


def test_resolve_tesseract_binary_finds_homebrew_path() -> None:
    with patch(
        "ee_wiki.ingestion.parsers.prose_pdf.tesseract_paths.shutil.which",
        return_value=None,
    ):
        binary = resolve_tesseract_binary()
    if Path("/opt/homebrew/bin/tesseract").is_file():
        assert binary is not None
        assert binary.endswith("/bin/tesseract")
    else:
        assert binary is None or binary.endswith("tesseract")


def test_resolve_tessdata_dir_uses_homebrew_default() -> None:
    with patch.dict("os.environ", {}, clear=True):
        resolved = resolve_tessdata_dir(None)
    if Path("/opt/homebrew/share/tessdata/eng.traineddata").is_file():
        assert resolved == "/opt/homebrew/share/tessdata"
    else:
        assert resolved is None or resolved.endswith("tessdata")


def test_resolve_tessdata_dir_honors_explicit_config(tmp_path: Path) -> None:
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").write_text("stub", encoding="utf-8")
    assert resolve_tessdata_dir(tessdata) == str(tessdata.resolve())
