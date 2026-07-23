"""Keynote FA one-pager generation from Radar fields (ADR 0010).

Lab contract (all content from Radar, no invention):

1. **Summary table** — radar id, title, state, product/project/build, fail items
2. **FA steps** — brief diagnosis lines (human notes only)
3. **Conclusion** — latest diagnosis / ticket state

On macOS with Keynote installed, AppleScript builds (or fills) a real
``.key``. Offline / CI / missing Keynote: write the same one-pager as UTF-8
Markdown at ``FA_summary.md`` only — never masquerade text as ``FA_summary.key``
(which Keynote cannot open).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.paths import (
    fa_export_dir,
    fa_summary_download_rel,
    fa_summary_md_download_rel,
    fa_summary_md_path,
    fa_summary_path,
    normalize_radar_id,
)
from ee_wiki.protocols.fa_report import FaReportRequest, FaReportResult

logger = get_logger(__name__)

# Reuse the same process-wide Keynote lock as iWork ingest export.
_KEYNOTE_CREATE_SCRIPT = """on run argv
    set destPath to item 1 of argv
    set titlePath to item 2 of argv
    set bodyPath to item 3 of argv
    set titleText to do shell script "cat " & quoted form of titlePath
    set bodyText to do shell script "cat " & quoted form of bodyPath
    tell application "Keynote"
        launch
        delay 1.5
        activate
        set theDoc to make new document
        delay 0.5
        set theSlide to slide 1 of theDoc
        tell theSlide
            try
                set object text of default title item to titleText
            end try
            try
                set object text of default body item to bodyText
            end try
        end tell
        save theDoc in POSIX file destPath
        close theDoc saving no
    end tell
end run
"""

_KEYNOTE_FILL_TEMPLATE_SCRIPT = """on run argv
    set srcPath to item 1 of argv
    set destPath to item 2 of argv
    set mapPath to item 3 of argv
    do shell script "cp " & quoted form of srcPath & " " & quoted form of destPath
    set mapText to do shell script "cat " & quoted form of mapPath
    tell application "Keynote"
        activate
        open POSIX file destPath
        delay 1.0
        set theDoc to front document
        repeat with s in slides of theDoc
            tell s
                try
                    set tTitle to object text of default title item
                    set object text of default title item to my replaceAll(tTitle, mapText)
                end try
                try
                    set tBody to object text of default body item
                    set object text of default body item to my replaceAll(tBody, mapText)
                end try
                try
                    repeat with t in text items
                        try
                            set object text of t to my replaceAll(object text of t, mapText)
                        end try
                    end repeat
                end try
            end tell
        end repeat
        save theDoc
        close theDoc saving yes
    end tell
end run

on replaceAll(theText, mapText)
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set rows to every text item of mapText
    set AppleScript's text item delimiters to oldDelims
    set outText to theText
    repeat with row in rows
        set rowText to row as text
        if rowText is not "" then
            set AppleScript's text item delimiters to tab
            set parts to every text item of rowText
            set AppleScript's text item delimiters to oldDelims
            if (count of parts) ≥ 2 then
                set needle to item 1 of parts
                set replacement to item 2 of parts
                -- TSV encodes newlines as the single char U+2424 (␤)
                set replacement to my replaceText(replacement, "␤", linefeed)
                set outText to my replaceText(outText, needle, replacement)
            end if
        end if
    end repeat
    return outText
end replaceAll

on replaceText(theText, needle, replacement)
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to needle
    set chunks to every text item of theText
    set AppleScript's text item delimiters to replacement
    set outText to chunks as text
    set AppleScript's text item delimiters to oldDelims
    return outText
end replaceText
"""


class StubKeynoteFaReportBackend:
    """Generate a Radar-grounded FA one-pager under ``data/exports/fa/``.

    Prefer a real Keynote via AppleScript when available; always also write
    ``FA_summary.md`` with the same content for chat preview / offline lab.
    When Keynote is unavailable, ``FA_summary.md`` is the sole download artifact.
    """

    def __init__(
        self,
        *,
        exports_dir: Path,
        template_path: Path | None = None,
        keynote_timeout_seconds: int = 180,
        force_text_fallback: bool = False,
    ) -> None:
        """Configure export root and optional company template.

        Args:
            exports_dir: Absolute ``data/exports`` directory.
            template_path: Optional company ``.key`` with ``{{…}}`` placeholders.
            keynote_timeout_seconds: ``osascript`` wall-clock limit.
            force_text_fallback: Skip AppleScript (tests / non-GUI hosts).
        """
        self.exports_dir = exports_dir
        self.template_path = template_path
        self.keynote_timeout_seconds = keynote_timeout_seconds
        self.force_text_fallback = force_text_fallback

    def generate(self, request: FaReportRequest) -> FaReportResult:
        """Create ``FA_summary.key`` and/or ``FA_summary.md`` for ``request.radar_id``.

        A real Keynote bundle is written only when AppleScript succeeds. Text
        fallback writes ``FA_summary.md`` only and removes any stale ``.key``.

        Args:
            request: Structured FA fields (Radar-sourced).

        Returns:
            Export path and download-relative location for the primary artifact.
        """
        rid = normalize_radar_id(request.radar_id)
        out_dir = fa_export_dir(self.exports_dir, rid)
        out_dir.mkdir(parents=True, exist_ok=True)
        key_path = fa_summary_path(self.exports_dir, rid)
        md_path = fa_summary_md_path(self.exports_dir, rid)
        one_pager = format_one_pager_markdown(request)
        md_path.write_text(one_pager, encoding="utf-8")

        template_used: Path | None = None
        notes: str
        keynote_available = False

        if self.force_text_fallback or not _keynote_usable():
            _remove_path_if_exists(key_path)
            notes = (
                "Keynote unavailable (no Keynote.app or force_text_fallback); "
                "wrote Markdown one-pager to FA_summary.md only."
            )
            logger.info("FA summary (markdown) for radar %s → %s", rid, md_path)
        else:
            try:
                if (
                    self.template_path is not None
                    and self.template_path.is_file()
                ):
                    _fill_keynote_template(
                        self.template_path,
                        key_path,
                        request,
                        timeout=self.keynote_timeout_seconds,
                    )
                    template_used = self.template_path
                    notes = (
                        f"Filled company template {self.template_path.name}; "
                        "markdown mirror in FA_summary.md."
                    )
                else:
                    _create_keynote_from_scratch(
                        key_path,
                        request,
                        timeout=self.keynote_timeout_seconds,
                    )
                    notes = (
                        "Created Keynote one-pager via AppleScript from Radar "
                        "fields; markdown mirror in FA_summary.md."
                    )
                keynote_available = True
                logger.info("FA summary (Keynote) for radar %s → %s", rid, key_path)
            except Exception as exc:  # noqa: BLE001 — fall back for lab UX
                logger.warning(
                    "Keynote FA summary failed; writing Markdown one-pager only: %s",
                    exc,
                    exc_info=True,
                )
                _remove_path_if_exists(key_path)
                notes = (
                    f"Keynote generation failed ({exc}); wrote Markdown one-pager "
                    "to FA_summary.md only."
                )

        if keynote_available:
            return FaReportResult(
                radar_id=rid,
                output_path=key_path,
                download_rel_path=fa_summary_download_rel(rid),
                template_used=template_used,
                notes=notes,
                keynote_available=True,
                markdown_path=md_path,
                markdown_download_rel_path=fa_summary_md_download_rel(rid),
            )
        return FaReportResult(
            radar_id=rid,
            output_path=md_path,
            download_rel_path=fa_summary_md_download_rel(rid),
            template_used=template_used,
            notes=notes,
            keynote_available=False,
            markdown_path=md_path,
            markdown_download_rel_path=fa_summary_md_download_rel(rid),
        )


def format_one_pager_markdown(request: FaReportRequest) -> str:
    """Render the FA one-pager as Markdown (Radar fields only)."""
    rid = normalize_radar_id(request.radar_id)
    product = (request.product or "—").strip() or "—"
    project = (request.project or "—").strip() or "—"
    build = (request.build or "—").strip() or "—"
    state = (request.state or "—").strip() or "—"
    substate = (request.substate or "").strip()
    state_cell = f"{state} / {substate}" if substate else state
    title = (request.title or "—").strip() or "—"
    conclusion = (request.conclusion or "—").strip() or "—"

    lines = [
        f"# FA One-Page — rdar://{rid}",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Radar | `rdar://{rid}` |",
        f"| Title | {title} |",
        f"| State | {state_cell} |",
        f"| Product | {product} |",
        f"| Project | {project} |",
        f"| Build | {build} |",
    ]
    if request.fail_items:
        fails = "; ".join(item.strip() for item in request.fail_items if item.strip())
        if fails:
            lines.append(f"| Fail items | {fails} |")
    lines.extend(["", "## FA Steps（来自 Radar diagnosis）", ""])
    if request.steps:
        for i, step in enumerate(request.steps, start=1):
            body = " ".join(step.strip().split())
            if len(body) > 280:
                body = body[:277].rstrip() + "…"
            lines.append(f"{i}. {body}")
    else:
        lines.append("_No user diagnosis notes on this Radar yet._")
    lines.extend(
        [
            "",
            "## Conclusion（当前最新状态）",
            "",
            conclusion,
            "",
        ]
    )
    return "\n".join(lines)


def format_slide_title(request: FaReportRequest) -> str:
    """Title line for the Keynote default title item."""
    rid = normalize_radar_id(request.radar_id)
    title = (request.title or "").strip()
    if title:
        short = title if len(title) <= 80 else title[:77].rstrip() + "…"
        return f"FA One-Page — rdar://{rid}\n{short}"
    return f"FA One-Page — rdar://{rid}"


def format_slide_body(request: FaReportRequest) -> str:
    """Body text for the Keynote default body item (plain, no markdown table)."""
    rid = normalize_radar_id(request.radar_id)
    product = (request.product or "—").strip() or "—"
    project = (request.project or "—").strip() or "—"
    build = (request.build or "—").strip() or "—"
    state = (request.state or "—").strip() or "—"
    substate = (request.substate or "").strip()
    state_cell = f"{state} / {substate}" if substate else state
    title = (request.title or "—").strip() or "—"
    conclusion = (request.conclusion or "—").strip() or "—"

    lines = [
        "Summary",
        f"  Radar: rdar://{rid}",
        f"  Title: {title}",
        f"  State: {state_cell}",
        f"  Product: {product}",
        f"  Project: {project}",
        f"  Build: {build}",
    ]
    if request.fail_items:
        fails = "; ".join(item.strip() for item in request.fail_items if item.strip())
        if fails:
            lines.append(f"  Fail items: {fails}")
    lines.append("")
    lines.append("FA Steps (Radar diagnosis)")
    if request.steps:
        for i, step in enumerate(request.steps, start=1):
            body = " ".join(step.strip().split())
            if len(body) > 220:
                body = body[:217].rstrip() + "…"
            lines.append(f"  {i}. {body}")
    else:
        lines.append("  (no user diagnosis notes yet)")
    lines.append("")
    lines.append("Conclusion (latest status)")
    lines.append(f"  {conclusion}")
    return "\n".join(lines)


def _keynote_usable() -> bool:
    """Return whether we are on macOS and Keynote looks runnable."""
    if sys.platform != "darwin":
        return False
    app = Path("/Applications/Keynote.app")
    return app.is_dir()


def _remove_path_if_exists(path: Path) -> None:
    """Remove a file or Keynote bundle directory if it exists."""
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _run_osascript(script: str, *argv: str, timeout: int) -> None:
    """Run AppleScript with argv; raise RuntimeError on failure."""
    from ee_wiki.ingestion.parsers.iwork.export import _export_lock

    command = ["osascript", "-", *argv]
    with _export_lock:
        logger.info("FA Keynote osascript (%s)", argv[0] if argv else "")
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
            raise RuntimeError(f"Failed to run osascript: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Keynote FA export timed out after {timeout}s"
            ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"osascript exit {completed.returncode}")


def _ensure_keynote_running(*, timeout: int = 30) -> None:
    """Best-effort launch of Keynote.app before scripting it."""
    try:
        subprocess.run(
            ["open", "-a", "Keynote"],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("Could not open Keynote.app via LaunchServices")
        return
    deadline = time.monotonic() + min(timeout, 20)
    while time.monotonic() < deadline:
        try:
            probe = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to '
                    '(name of processes) contains "Keynote"',
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.returncode == 0 and "true" in (probe.stdout or "").lower():
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(0.5)


def _placeholder_map(request: FaReportRequest) -> str:
    """Tab-separated needle→replacement rows for template fill AppleScript."""
    rid = normalize_radar_id(request.radar_id)
    product = (request.product or "").strip()
    project = (request.project or "").strip()
    build = (request.build or "").strip()
    state = (request.state or "").strip()
    substate = (request.substate or "").strip()
    state_cell = f"{state} / {substate}" if substate else state
    title = (request.title or "").strip()
    conclusion = (request.conclusion or "").strip()
    body = format_slide_body(request)

    def _flat(value: str) -> str:
        return value.replace("\t", " ").replace("\n", "␤")

    steps_text = (
        "\n".join(
            f"{i}. {' '.join(s.split())[:220]}"
            for i, s in enumerate(request.steps, 1)
        )
        if request.steps
        else "(none)"
    )
    summary_part = body.split("FA Steps")[0].rstrip()
    pairs = [
        ("{{RADAR_ID}}", rid),
        ("{{TITLE}}", title),
        ("{{PRODUCT}}", product),
        ("{{PROJECT}}", project),
        ("{{BUILD}}", build),
        ("{{STATE}}", state_cell),
        ("{{CONCLUSION}}", conclusion),
        ("{{BODY}}", body),
        ("{{SUMMARY_TABLE}}", summary_part),
        ("{{STEPS}}", steps_text),
    ]
    return "\n".join(f"{needle}\t{_flat(val)}" for needle, val in pairs) + "\n"


def _create_keynote_from_scratch(
    dest: Path,
    request: FaReportRequest,
    *,
    timeout: int,
) -> None:
    """Create a new one-slide Keynote from Radar fields."""
    dest = dest.resolve()
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    _ensure_keynote_running(timeout=min(timeout, 25))
    with tempfile.TemporaryDirectory(prefix="ee-wiki-fa-key-") as tmp:
        tmp_path = Path(tmp)
        title_file = tmp_path / "title.txt"
        body_file = tmp_path / "body.txt"
        title_file.write_text(format_slide_title(request), encoding="utf-8")
        body_file.write_text(format_slide_body(request), encoding="utf-8")
        _run_osascript(
            _KEYNOTE_CREATE_SCRIPT,
            str(dest),
            str(title_file),
            str(body_file),
            timeout=timeout,
        )
    if not dest.exists():
        raise RuntimeError(f"Keynote did not write {dest}")


def _fill_keynote_template(
    template: Path,
    dest: Path,
    request: FaReportRequest,
    *,
    timeout: int,
) -> None:
    """Copy company template and replace ``{{…}}`` placeholders via AppleScript."""
    dest = dest.resolve()
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    _ensure_keynote_running(timeout=min(timeout, 25))
    with tempfile.TemporaryDirectory(prefix="ee-wiki-fa-fill-") as tmp:
        map_file = Path(tmp) / "map.tsv"
        map_file.write_text(_placeholder_map(request), encoding="utf-8")
        _run_osascript(
            _KEYNOTE_FILL_TEMPLATE_SCRIPT,
            str(template.resolve()),
            str(dest),
            str(map_file),
            timeout=timeout,
        )
    if not dest.exists():
        raise RuntimeError(f"Keynote did not write {dest}")


def build_conclusion_from_radar(
    *,
    state: str | None,
    substate: str | None,
    latest_diagnosis: str | None,
    fail_items: tuple[str, ...] = (),
) -> str:
    """Build a short conclusion string from Radar state + latest diagnosis.

    Does not invent root cause / true-fail — only restates ticket status.
    """
    state_s = (state or "").strip() or "—"
    sub_s = (substate or "").strip()
    status = f"{state_s} / {sub_s}" if sub_s else state_s
    parts = [f"Ticket state: {status}."]
    if latest_diagnosis:
        snippet = " ".join(latest_diagnosis.strip().split())
        if len(snippet) > 400:
            snippet = snippet[:397].rstrip() + "…"
        parts.append(f"Latest diagnosis: {snippet}")
    elif fail_items:
        joined = "; ".join(f.strip() for f in fail_items if f.strip())
        if joined:
            parts.append(f"Open fail items: {joined}")
    else:
        parts.append("No further diagnosis notes on the ticket yet.")
    return " ".join(parts)
