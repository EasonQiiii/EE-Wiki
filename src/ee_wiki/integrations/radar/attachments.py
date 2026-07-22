"""Materialize Radar attachments under ``data/cache/fa/`` for browser download."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from ee_wiki.common.config import AppConfig
from ee_wiki.common.errors import IntegrationError
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.fa_errors import format_fa_error
from ee_wiki.integrations.factory import build_radar_backend
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.session import public_url
from ee_wiki.protocols.radar import AttachmentMeta, RadarProblem

logger = get_logger(__name__)

# Max chars of attachment body shown in chat (keeps replies readable).
_CONTENT_PREVIEW_CHARS = 12_000

_DOWNLOAD_INTENT = re.compile(
    r"(?:下载|download|另存|打开附件|给我链接|下载链接|下来看|"
    r"内容是什么|附件内容|"
    r"fetch\s+attachment|get\s+(?:the\s+)?log)",
    re.IGNORECASE,
)

# Ask to read / analyze the log body (not just paraphrase diagnosis).
_CONTENT_INTENT = re.compile(
    r"(?:分析|解读|解析|摘要|summar(?:y|ize)|analy[sz]e|"
    r"看看.*(?:log|日志|附件)|(?:log|日志|附件).*(?:内容|里面)|"
    r"读一下|打开看看|what(?:'s| is) in)",
    re.IGNORECASE,
)

_PASS_LINE = re.compile(r"\bPASS\b|:\s*PASS\b|PASS:", re.IGNORECASE)
_FAIL_LINE = re.compile(r"\bFAIL\b|:\s*FAIL\b|FAIL:|\bERROR\b", re.IGNORECASE)


def wants_attachment_download(question: str) -> bool:
    """Return whether the user is asking to download / open attachment bytes."""
    return bool(_DOWNLOAD_INTENT.search(question.strip()))


def wants_attachment_content(question: str) -> bool:
    """Return whether the user wants the attachment body analyzed / shown.

    Prefer this over session dialogue when a ``.log`` (or similar) is named —
    dialogue only has diagnosis text, not file bytes.
    """
    q = question.strip()
    if not _CONTENT_INTENT.search(q):
        return False
    # Require a file-ish cue so "分析一下下一步" stays on dialogue.
    # Do not use ``\b`` after ``.log`` — Chinese particles like 吗 keep the
    # word-char class open, so ``.log吗`` would fail a ``\b`` check.
    if re.search(r"\.(?:log|txt|csv|json)(?![A-Za-z0-9_])", q, re.IGNORECASE):
        return True
    if re.search(r"(?:附件|attachment|日志|(?<![A-Za-z0-9_])log(?![A-Za-z0-9_]))", q, re.IGNORECASE):
        return True
    return False


def resolve_requested_attachments(
    query: str,
    available: list[AttachmentMeta] | tuple[AttachmentMeta, ...],
) -> list[str]:
    """Map a user phrase to zero or more attachment file names on the ticket.

    Handles diagnosis shorthand such as ``…MLB_1&2.log`` → both ``_1`` and
    ``_2`` files when present.
    """
    names = [a.file_name for a in available if a.file_name]
    if not names:
        return []
    q = query.strip()
    # Exact / basename mention
    hits = [n for n in names if n in q or n.lower() in q.lower()]
    if hits:
        return list(dict.fromkeys(hits))

    # Combined "1&2" / "1 and 2" shorthand → sibling PASS logs
    if re.search(r"1\s*&\s*2|1\s+and\s+2|mlb_1&2", q, re.IGNORECASE):
        siblings = [
            n
            for n in names
            if re.search(r"mlb_1\.log|mlb_2\.log|MLB_1\.log|MLB_2\.log", n)
            or re.search(r"_1\.log|_2\.log", n)
        ]
        # Prefer sensor_flash_test_PASS* pair when present
        prefer = [n for n in siblings if "PASS" in n or "pass" in n.lower()]
        chosen = prefer or siblings
        if chosen:
            return list(dict.fromkeys(chosen))

    # Fuzzy: any token from query matching a file stem
    tokens = re.findall(r"[A-Za-z0-9_]{4,}", q)
    fuzzy: list[str] = []
    for n in names:
        stem = Path(n).stem.lower()
        if any(t.lower() in stem or stem in t.lower() for t in tokens):
            fuzzy.append(n)
    if fuzzy:
        return list(dict.fromkeys(fuzzy))
    return []


def materialize_attachment(
    config: AppConfig,
    radar_id: str,
    file_name: str,
) -> tuple[Path, str, str]:
    """Ensure ``file_name`` exists under FA cache and return path + public URL.

    Returns:
        ``(absolute_path, relative_cache_path, public_url)``.
    """
    rid = normalize_radar_id(radar_id)
    safe_name = Path(file_name).name
    rel = f"fa/{rid}/attachments/{safe_name}"
    dest = config.cache_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    radar = build_radar_backend(config)
    if dest.is_file() and dest.stat().st_size > 0:
        url = public_url(config, f"/v1/cache/{quote(rel, safe='/')}")
        return dest, rel, url

    radar.download_attachment(rid, safe_name, dest_path=dest)

    url = public_url(config, f"/v1/cache/{quote(rel, safe='/')}")
    logger.info("Radar attachment ready rdar://%s -> %s", rid, dest)
    return dest, rel, url


def _resolve_attachment_targets(
    question: str,
    available: list[AttachmentMeta] | tuple[AttachmentMeta, ...],
) -> tuple[list[str], list[str]]:
    """Return ``(targets, preface_lines)`` for download / content replies."""
    requested = resolve_requested_attachments(question, available)
    preface: list[str] = []
    if not available:
        return [], ["_This Radar has no attachments listed._"]
    if not requested:
        preface.append("未匹配到具体文件名。票上相关附件如下：")
        return [a.file_name for a in available if a.file_name], preface
    if ("1&2" in question or "1 & 2" in question) and len(requested) >= 2:
        preface.append(
            "Diagnosis 里的 `…MLB_1&2.log` 对应票上两个附件"
            "（没有合并成单个 `&` 文件名）："
        )
    return requested, preface


def read_attachment_text(path: Path, *, max_chars: int = _CONTENT_PREVIEW_CHARS) -> str:
    """Decode attachment bytes as text for chat analysis.

    Args:
        path: Local materialized file.
        max_chars: Truncate after this many characters.

    Returns:
        Decoded text (lossy for binary); may be truncated with a marker.
    """
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        return (
            text[:max_chars]
            + f"\n\n… [truncated after {max_chars} chars; "
            f"full file is {len(raw)} bytes on disk] …\n"
        )
    return text


def summarize_log_text(text: str, *, file_name: str) -> list[str]:
    """Heuristic summary lines from log text (no LLM, no invention)."""
    lines = text.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    pass_hits = [ln for ln in non_empty if _PASS_LINE.search(ln)]
    fail_hits = [ln for ln in non_empty if _FAIL_LINE.search(ln)]
    out = [
        f"**File:** `{file_name}`",
        f"**Lines:** {len(lines)} ({len(non_empty)} non-empty)",
        f"**PASS-like lines:** {len(pass_hits)}",
        f"**FAIL/ERROR-like lines:** {len(fail_hits)}",
    ]
    if fail_hits:
        out.append("")
        out.append("FAIL/ERROR samples:")
        for ln in fail_hits[:8]:
            out.append(f"- `{ln.strip()[:200]}`")
    elif pass_hits:
        out.append("")
        out.append("PASS samples:")
        for ln in pass_hits[:8]:
            out.append(f"- `{ln.strip()[:200]}`")
    return out


def format_attachment_download_markdown(
    config: AppConfig,
    radar_id: str,
    question: str,
) -> str:
    """Build FA reply with clickable ``/v1/cache/…`` download links."""
    rid = normalize_radar_id(radar_id)
    problem = build_radar_backend(config).get_problem(rid)
    available = list(problem.attachments)
    targets, preface = _resolve_attachment_targets(question, available)

    lines = [
        f"## FA check-in — rdar://{rid}",
        "",
        "### Radar attachment downloads",
        "",
    ]
    lines.extend(preface)

    if not targets and preface:
        return "\n".join(lines) + "\n"

    lines.append("")
    for name in targets:
        try:
            _path, _rel, url = materialize_attachment(config, rid, name)
            lines.append(f"- [`{name}`]({url})")
        except IntegrationError as exc:
            note = format_fa_error(exc, context="attachment", style="inline")
            lines.append(f"- `{name}` — 下载失败：{note}")

    if config.fa.radar.backend == "stub":
        lines.extend(
            [
                "",
                "_Stub backend：链接可点，内容为占位 PASS 摘要，不是真机 "
                "Radar 二进制。切 `fa.radar.backend: radarclient` 后下载真附件。_",
            ]
        )
    return "\n".join(lines) + "\n"


def format_attachment_content_markdown(
    config: AppConfig,
    radar_id: str,
    question: str,
) -> str:
    """Materialize attachment(s), summarize body text, include download link.

    This is the grounded path for “分析一下 xxx.log” — not diagnosis paraphrase.
    """
    rid = normalize_radar_id(radar_id)
    problem = build_radar_backend(config).get_problem(rid)
    available = list(problem.attachments)
    targets, preface = _resolve_attachment_targets(question, available)

    lines = [
        f"## FA check-in — rdar://{rid}",
        "",
        "### Attachment content (from file bytes)",
        "",
        "以下分析基于**已物化的附件文件**，不是 Radar diagnosis 复述。",
        "",
    ]
    lines.extend(preface)

    if not targets:
        return "\n".join(lines) + "\n"

    for name in targets:
        lines.append("")
        try:
            path, _rel, url = materialize_attachment(config, rid, name)
        except IntegrationError as exc:
            note = format_fa_error(exc, context="attachment", style="inline")
            lines.append(f"#### `{name}`")
            lines.append(f"读取失败：{note}")
            continue

        text = read_attachment_text(path)
        lines.extend(summarize_log_text(text, file_name=name))
        lines.append(f"**Download:** [`{name}`]({url})")
        lines.append("")
        lines.append("<details>")
        lines.append(f"<summary>File preview — {name}</summary>")
        lines.append("")
        lines.append("```text")
        lines.append(text.rstrip() or "(empty file)")
        lines.append("```")
        lines.append("")
        lines.append("</details>")

    if config.fa.radar.backend == "stub":
        lines.extend(
            [
                "",
                "_Stub：正文是占位 PASS 文本，不是真机 unit log。"
                "切 `fa.radar.backend: radarclient` 后这里才是 Radar 真附件。_",
            ]
        )
    return "\n".join(lines) + "\n"


def materialize_all_attachment_links(
    config: AppConfig,
    problem: RadarProblem,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Materialize every attachment.

    Returns:
        A pair ``(links, failed)`` where ``links`` is a list of
        ``(file_name, public_url)`` pairs and ``failed`` is the list of
        attachment file names that could not be materialized (so the caller
        can surface a friendly note instead of silently dropping them).
    """
    out: list[tuple[str, str]] = []
    failed: list[str] = []
    for att in problem.attachments:
        if not att.file_name:
            continue
        try:
            _path, _rel, url = materialize_attachment(
                config, problem.radar_id, att.file_name
            )
            out.append((att.file_name, url))
        except IntegrationError:
            logger.warning(
                "Skip attachment materialize rdar://%s name=%s",
                problem.radar_id,
                att.file_name,
                exc_info=True,
            )
            failed.append(att.file_name)
    return out, failed
