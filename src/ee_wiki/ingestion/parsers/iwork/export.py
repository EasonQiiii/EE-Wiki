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

_OPEN_WAIT_LOOPS = 120  # 60 seconds at 0.5s per loop

_KEYNOTE_EXPORT_SCRIPT = """on run argv
    set srcPath to item 1 of argv
    set destPath to item 2 of argv
    set quitAfter to item 3 of argv
    set priorCount to (item 4 of argv) as integer
    set maxWaitLoops to (item 5 of argv) as integer
    set srcAlias to POSIX file srcPath as alias
    tell application "Keynote"
        activate
        set docRef to missing value
        repeat with i from 1 to maxWaitLoops
            if (count of documents) > priorCount then
                set docRef to front document
            end if
            if docRef is missing value then
                repeat with d in documents
                    try
                        if (file of d) is srcAlias then
                            set docRef to d
                            exit repeat
                        end if
                    end try
                end repeat
            end if
            if docRef is not missing value then exit repeat
            delay 0.5
        end repeat
        if docRef is missing value then ¬
            error "Keynote document did not open in time"
        with timeout of 1200 seconds
            export docRef to (POSIX file destPath) as PDF
        end timeout
        close docRef saving no
        if quitAfter is "true" then quit
    end tell
end run"""

_NUMBERS_EXPORT_SCRIPT = """on run argv
    set srcPath to item 1 of argv
    set destPath to item 2 of argv
    set quitAfter to item 3 of argv
    set priorCount to (item 4 of argv) as integer
    set maxWaitLoops to (item 5 of argv) as integer
    set srcAlias to POSIX file srcPath as alias
    tell application "Numbers"
        activate
        set docRef to missing value
        repeat with i from 1 to maxWaitLoops
            if (count of documents) > priorCount then
                set docRef to front document
            end if
            if docRef is missing value then
                repeat with d in documents
                    try
                        if (file of d) is srcAlias then
                            set docRef to d
                            exit repeat
                        end if
                    end try
                end repeat
            end if
            if docRef is not missing value then exit repeat
            delay 0.5
        end repeat
        if docRef is missing value then ¬
            error "Numbers document did not open in time"
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


def _maybe_clear_quarantine(source: Path) -> None:
    """Remove the quarantine xattr when present so LaunchServices can open the file."""
    try:
        subprocess.run(
            ["xattr", "-d", "com.apple.quarantine", str(source)],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass


def _osascript_int(script: str, *, timeout: int = 30) -> int:
    """Evaluate a short AppleScript expression that returns an integer."""
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if completed.returncode != 0:
        return 0
    raw = (completed.stdout or "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def _iwork_document_count(app_name: str) -> int:
    """Return how many documents an iWork app currently has open."""
    script = (
        f'try\n'
        f'  tell application "{app_name}"\n'
        f'    if not running then return 0\n'
        f'    return count of documents\n'
        f'  end tell\n'
        f'on error\n'
        f'  return 0\n'
        f'end try'
    )
    return _osascript_int(script)


def _open_in_app(app_name: str, source: Path, *, timeout: int = 60) -> None:
    """Open a document with the native iWork app via LaunchServices.

    Args:
        app_name: Application name understood by ``open -a`` (e.g. ``Keynote``).
        source: File to open.
        timeout: Seconds to wait for ``open`` to return.

    Raises:
        IworkParserError: If ``open`` fails or times out.
    """
    resolved = source.resolve()
    logger.info("Opening %s with %s via LaunchServices", resolved.name, app_name)
    try:
        completed = subprocess.run(
            ["open", "-a", app_name, str(resolved)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except OSError as exc:
        raise IworkParserError(f"Failed to run open for {resolved.name}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise IworkParserError(
            f"Timed out opening {resolved.name} with {app_name}"
        ) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise IworkParserError(
            f"Failed to open {resolved.name} with {app_name}: {detail or 'unknown error'}"
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


def _export_opened_iwork_document(
    *,
    app_name: str,
    script: str,
    source: Path,
    dest: Path,
    quit_after: bool,
    timeout: int,
) -> None:
    """Open an iWork file with LaunchServices, then export it via AppleScript."""
    resolved = source.resolve()
    _maybe_clear_quarantine(resolved)
    prior_count = _iwork_document_count(app_name)
    _open_in_app(app_name, resolved)
    _run_osascript(
        script,
        str(resolved),
        str(dest.resolve()),
        "true" if quit_after else "false",
        str(prior_count),
        str(_OPEN_WAIT_LOOPS),
        timeout=timeout,
    )


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
    _export_opened_iwork_document(
        app_name="Keynote",
        script=_KEYNOTE_EXPORT_SCRIPT,
        source=source,
        dest=dest,
        quit_after=quit_after,
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
    _export_opened_iwork_document(
        app_name="Numbers",
        script=_NUMBERS_EXPORT_SCRIPT,
        source=source,
        dest=dest,
        quit_after=quit_after,
        timeout=timeout,
    )
    if not dest.is_file():
        raise IworkParserError(f"Numbers did not produce expected Excel file: {dest}")
    return dest
