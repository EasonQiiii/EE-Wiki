"""Export Keynote and Numbers documents via macOS AppleScript."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.iwork.errors import IworkParserError

logger = get_logger(__name__)

_export_lock = threading.Lock()

_KEYNOTE_EXPORT_SCRIPT = """on run argv
    set srcPath to item 1 of argv
    set destPath to item 2 of argv
    set quitAfter to item 3 of argv
    tell application "Keynote"
        set docRef to open (POSIX file srcPath)
        export docRef to (POSIX file destPath) as PDF
        close docRef saving no
        if quitAfter is "true" then quit
    end tell
end run"""

_NUMBERS_EXPORT_SCRIPT = """on run argv
    set srcPath to item 1 of argv
    set destPath to item 2 of argv
    set quitAfter to item 3 of argv
    tell application "Numbers"
        set docRef to open (POSIX file srcPath)
        repeat until exists document 1
            delay 0.5
        end repeat
        with timeout of 1200 seconds
            export docRef to (POSIX file destPath) as Microsoft Excel
        end timeout
        close docRef saving no
        if quitAfter is "true" then quit
    end tell
end run"""


def require_darwin() -> None:
    """Raise when iWork export is invoked off macOS.

    Raises:
        IworkParserError: When ``sys.platform`` is not ``darwin``.
    """
    if sys.platform != "darwin":
        raise IworkParserError(
            ".key and .numbers ingest requires macOS with Keynote and Numbers installed"
        )


def _run_osascript(script: str, *argv: str, timeout: int) -> None:
    """Run an AppleScript with arguments under a process-wide export lock.

    Args:
        script: AppleScript source executed via ``osascript -``.
        *argv: Arguments passed to the script's ``run`` handler.
        timeout: Subprocess timeout in seconds.

    Raises:
        IworkParserError: If ``osascript`` fails or times out.
    """
    require_darwin()
    command = ["osascript", "-", *argv]
    with _export_lock:
        logger.info("Running iWork export via osascript (%s)", argv[0] if argv else "")
        try:
            completed = subprocess.run(
                command,
                input=script,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except OSError as exc:
            raise IworkParserError(f"Failed to run osascript: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise IworkParserError(
                f"iWork export timed out after {timeout}s for {argv[0] if argv else 'input'}"
            ) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit {completed.returncode}"
        raise IworkParserError(f"osascript export failed: {detail}")


def export_keynote_to_pdf(
    source: Path,
    *,
    out_dir: Path,
    timeout: int,
    quit_after: bool,
) -> Path:
    """Export a ``.key`` presentation to PDF via Keynote.

    Args:
        source: Input Keynote file.
        out_dir: Directory for the generated PDF.
        timeout: ``osascript`` timeout in seconds.
        quit_after: When ``True``, quit Keynote after export.

    Returns:
        Path to the generated PDF.

    Raises:
        IworkParserError: If export fails or the PDF is missing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{source.stem}.pdf"
    _run_osascript(
        _KEYNOTE_EXPORT_SCRIPT,
        str(source.resolve()),
        str(dest.resolve()),
        "true" if quit_after else "false",
        timeout=timeout,
    )
    if not dest.is_file():
        raise IworkParserError(f"Keynote did not produce expected PDF: {dest}")
    return dest


def export_numbers_to_xlsx(
    source: Path,
    *,
    out_dir: Path,
    timeout: int,
    quit_after: bool,
) -> Path:
    """Export a ``.numbers`` spreadsheet to Excel via Numbers.

    Args:
        source: Input Numbers file.
        out_dir: Directory for the generated ``.xlsx`` file.
        timeout: ``osascript`` timeout in seconds.
        quit_after: When ``True``, quit Numbers after export.

    Returns:
        Path to the generated ``.xlsx`` file.

    Raises:
        IworkParserError: If export fails or the workbook is missing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{source.stem}.xlsx"
    _run_osascript(
        _NUMBERS_EXPORT_SCRIPT,
        str(source.resolve()),
        str(dest.resolve()),
        "true" if quit_after else "false",
        timeout=timeout,
    )
    if not dest.is_file():
        raise IworkParserError(f"Numbers did not produce expected Excel file: {dest}")
    return dest
