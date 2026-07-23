"""Materialize Radar attachments under ``data/cache/fa/`` for browser download."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from urllib.parse import quote

from ee_wiki.api.stream_status import (
    FA_ATTACHMENT_ANALYZE_STATUS,
    FA_DOWNLOAD_STATUS,
)
from ee_wiki.api.stream_status_context import push_stream_status
from ee_wiki.common.config import AppConfig, find_repo_root
from ee_wiki.common.errors import IntegrationError
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.fa_evidence import generate_log_analysis
from ee_wiki.generation.llm.factory import build_llm_backend
from ee_wiki.integrations.fa_errors import format_fa_error
from ee_wiki.integrations.factory import build_radar_backend
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.session import public_url
from ee_wiki.protocols.llm import LlmBackend
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
# Structural alert tokens (no semantic classification). Surfaces something
# meaningful even when a log has NO literal PASS/FAIL (e.g. Cal_LPNM numeric
# / "out of limit" / "阈值超限" output). Still structural — not a verdict.
_STRUCTURAL_ALERT = re.compile(
    r"out\s*of\s*limit|out-of-limit|阈值(?:超限)?|over\s*limit|exceed|超出",
    re.IGNORECASE,
)

# Inventory intent: "有哪些附件 / 附件列表 / 有哪些文件 / 几个附件" and the
# explicit "调用 radar 工具". Structural-only (ADR 0013: regex = structural
# tokens, no semantic classification). Must stay narrow so it never swallows a
# diagnosis / log-content / download question — those keep their own paths.
_ABOUT_ATTACHMENT_INVENTORY = re.compile(
    r"(?:有哪些附件|附件有哪些|附件列表|列出附件|附件清单|"
    r"有哪些文件|文件清单|几个附件|几个文件|"
    r"attachment list|list (?:the )?attachments|"
    r"what (?:attachments|files) (?:are )?(?:there|listed)|"
    r"调用\s*(?:radar|雷达)\s*工具)",
    re.IGNORECASE,
)


def wants_attachment_download(question: str) -> bool:
    """Return whether the user is asking to download / open attachment bytes."""
    return bool(_DOWNLOAD_INTENT.search(question.strip()))


def wants_attachment_inventory(question: str) -> bool:
    """Return whether the user wants the full attachment inventory (no bytes).

    "有哪些附件" / "调用 radar 工具" hit here — routed to the deterministic
    ``format_attachment_inventory_markdown`` (never the LLM) so the count is
    exact and we never claim "no log" when logs are listed.
    """
    return bool(_ABOUT_ATTACHMENT_INVENTORY.search(question.strip()))


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
    log_word = r"(?:附件|attachment|日志|(?<![A-Za-z0-9_])log(?![A-Za-z0-9_]))"
    if re.search(log_word, q, re.IGNORECASE):
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


_TYPE_BY_EXT = {
    "log": "Log",
    "txt": "Text",
    "csv": "CSV",
    "json": "JSON",
    "rtf": "RTF log",
    "zip": "Archive",
    "tar": "Archive",
    "gz": "Archive",
    "axl": "AXI scan",
    "axi": "AXI scan",
    "png": "Image",
    "jpg": "Image",
    "jpeg": "Image",
    "gif": "Image",
    "bmp": "Image",
    "tiff": "Image",
    "pdf": "PDF",
    "xlsx": "Spreadsheet",
    "xls": "Spreadsheet",
    "key": "Keynote",
    "pptx": "Slide deck",
    "docx": "Document",
}


def attachment_type_label(file_name: str) -> str:
    """Human-readable type for an attachment derived from its extension."""
    ext = Path(file_name).suffix.lower().lstrip(".")
    return _TYPE_BY_EXT.get(ext, "File")


def cached_attachment_path(
    config: AppConfig,
    radar_id: str,
    file_name: str,
) -> Path | None:
    """Return the cached path if ``file_name`` is already materialized.

    This is a *read-only* check — it never downloads. Used by the check-in
    inventory to report cached vs pending without triggering a fetch (the
    whole point of fixing the eager-download stall in Problem 1).
    """
    rid = normalize_radar_id(radar_id)
    rel = f"fa/{rid}/attachments/{Path(file_name).name}"
    dest = config.cache_dir / rel
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    return None


def summarize_attachment_inventory(
    config: AppConfig,
    problem: RadarProblem,
) -> tuple[list[dict], int, int]:
    """List attachments with type / kind / cached status *without* downloading.

    Returns:
        ``(entries, total, cached_count)`` where each entry is a dict with
        keys ``name``, ``type``, ``kind``, ``cached``. Intended for the FA
        check-in reply so the user sees what is available and what is already
        on disk, without the backend pulling every file up front.
    """
    entries: list[dict] = []
    cached = 0
    for att in problem.attachments:
        if not att.file_name:
            continue
        is_cached = cached_attachment_path(config, problem.radar_id, att.file_name) is not None
        if is_cached:
            cached += 1
        entries.append(
            {
                "name": att.file_name,
                "type": attachment_type_label(att.file_name),
                "kind": att.kind or "attachment",
                "cached": is_cached,
            }
        )
    return entries, len(entries), cached


def materialize_attachment(
    config: AppConfig,
    radar_id: str,
    file_name: str,
    *,
    kind: str | None = None,
) -> tuple[Path, str, str]:
    """Ensure ``file_name`` exists under FA cache and return path + public URL.

    ``kind`` should be ``"picture"`` for image attachments (``.png`` etc.) so
    the download routes through the Radar *pictures* collection instead of
    ``attachments`` — ``download_attachment`` cannot see pictures and would
    raise "not found".

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

    if (kind or "attachment") == "picture":
        radar.download_picture(rid, safe_name, dest_path=dest)
    else:
        radar.download_attachment(rid, safe_name, dest_path=dest)

    url = public_url(config, f"/v1/cache/{quote(rel, safe='/')}")
    logger.info("Radar attachment ready rdar://%s -> %s", rid, dest)
    return dest, rel, url


def materialize_named_attachments(
    config: AppConfig,
    radar_id: str,
    names: list[str],
    *,
    kind_by_name: dict[str, str] | None = None,
) -> tuple[list[tuple[str, Path, str, str]], list[tuple[str, str]]]:
    """Materialize ``names`` on demand, emitting download progress when bound.

    Skips files that are already cached. When a streaming status hub is active
    (see ``stream_status_context``), emits ``FA_DOWNLOAD_STATUS`` before each
    fetch that would hit Radar.

    Returns:
        ``(successes, failures)`` where successes are
        ``(file_name, path, rel_cache_path, public_url)`` and failures are
        ``(file_name, user_facing_note)``.
    """
    rid = normalize_radar_id(radar_id)
    kinds = kind_by_name or {}
    successes: list[tuple[str, Path, str, str]] = []
    failures: list[tuple[str, str]] = []
    pending = [
        n
        for n in names
        if n and cached_attachment_path(config, rid, n) is None
    ]
    total = len(pending)
    done = 0
    for name in names:
        if not name:
            continue
        if cached_attachment_path(config, rid, name) is None:
            done += 1
            if total:
                push_stream_status(
                    FA_DOWNLOAD_STATUS.format(done=done, total=total)
                )
        try:
            path, rel, url = materialize_attachment(
                config,
                rid,
                name,
                kind=kinds.get(name, "attachment"),
            )
            successes.append((name, path, rel, url))
        except IntegrationError as exc:
            note = format_fa_error(exc, context="attachment", style="inline")
            failures.append((name, note))
            logger.warning(
                "Skip attachment materialize rdar://%s name=%s",
                rid,
                name,
                exc_info=True,
            )
    return successes, failures


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
        preface.append("未匹配到具体文件名。该 Radar 相关附件如下：")
        return [a.file_name for a in available if a.file_name], preface
    if ("1&2" in question or "1 & 2" in question) and len(requested) >= 2:
        preface.append(
            "Diagnosis 里的 `…MLB_1&2.log` 对应 Radar 上两个附件"
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


def extract_fail_lines(text: str, *, limit: int = 8) -> list[str]:
    """Return up to ``limit`` FAIL/ERROR-like lines from log text.

    Structural line scan (same ``_FAIL_LINE`` token as ``summarize_log_text``)
    used only to surface concrete evidence lines from an attachment body the
    LLM already selected as strong-related — it does NOT decide *which* file is
    relevant (that is the LLM's job, ADR 0013).
    """
    hits: list[str] = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if stripped and _FAIL_LINE.search(stripped):
            hits.append(stripped[:200])
            if len(hits) >= limit:
                break
    return hits


def summarize_log_text(text: str, *, file_name: str) -> list[str]:
    """Heuristic summary lines from log text (no LLM, no invention).

    Counts literal PASS/FAIL/ERROR plus structural alert tokens (out of limit
    / 阈值超限 / exceed …) so the summary is not empty when a log carries no
    literal pass/fail words. This is a structural supplement only — the LLM
    interpretation layer (``generate_log_analysis``) is what actually explains
    the file. The heuristic never claims a pass/fail verdict on its own.
    """
    lines = text.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    pass_hits = [ln for ln in non_empty if _PASS_LINE.search(ln)]
    fail_hits = [ln for ln in non_empty if _FAIL_LINE.search(ln)]
    alert_hits = [ln for ln in non_empty if _STRUCTURAL_ALERT.search(ln)]
    out = [
        f"**File:** `{file_name}`",
        f"**Lines:** {len(lines)} ({len(non_empty)} non-empty)",
        f"**PASS-like lines:** {len(pass_hits)}",
        f"**FAIL/ERROR-like lines:** {len(fail_hits)}",
        f"**结构告警 token（out of limit / 阈值超限 等）：{len(alert_hits)}**",
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
    if alert_hits:
        out.append("")
        out.append("结构告警 samples:")
        for ln in alert_hits[:8]:
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
    kind_by_name = {a.file_name: (a.kind or "attachment") for a in available}
    materialized, failed = materialize_named_attachments(
        config, rid, targets, kind_by_name=kind_by_name
    )
    for name, _path, _rel, url in materialized:
        lines.append(f"- [`{name}`]({url})")
    for name, note in failed:
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


def format_attachment_inventory_markdown(
    config: AppConfig,
    radar_id: str,
) -> str:
    """Deterministic list of every Radar attachment (incl. pictures).

    Enumerates ``problem.attachments`` — pictures are merged in with
    ``kind="picture"`` — and never downloads bytes (Problem 1: on-demand only).
    Cached files get a clickable ``/v1/cache/…`` link; pending ones are marked
    so the user knows to say "下载 <名>". This is the authoritative answer for
    "有哪些附件" / "调用 radar 工具" and must never claim "no log" when logs
    are listed.
    """
    rid = normalize_radar_id(radar_id)
    problem = build_radar_backend(config).get_problem(rid)
    available = list(problem.attachments)
    entries, total, cached = summarize_attachment_inventory(config, problem)

    lines = [
        f"## FA check-in — rdar://{rid}",
        "",
        f"### Radar attachments（共 {total} 个）",
        "",
    ]
    if not available:
        lines.append("_这张 Radar 没有列出任何附件。_")
        return "\n".join(lines) + "\n"

    for entry in entries:
        name = entry["name"]
        kind_tag = "图片" if entry["kind"] == "picture" else "附件"
        if entry["cached"]:
            rel = f"fa/{rid}/attachments/{Path(name).name}"
            url = public_url(config, f"/v1/cache/{quote(rel, safe='/')}")
            lines.append(
                f"- [`{name}`]({url}) — {entry['type']} · {kind_tag} · 已缓存"
            )
        else:
            lines.append(
                f"- `{name}` — {entry['type']} · {kind_tag} · 待下载"
            )
    lines.append("")
    lines.append(
        f"> 已缓存 {cached} / {total} 个；未缓存的说「下载 <文件名>」即可按需取回。"
    )
    return "\n".join(lines) + "\n"


def _preview_text(
    text: str, *, max_lines: int = 40, max_chars: int = 2000
) -> str:
    """First ~40 lines / ~2000 chars of a file for an in-chat preview.

    Structural only — no semantic choice. Open WebUI cannot fold HTML
    ``<details>``, so the preview stays short and the download link carries
    the full file.
    """
    lines = text.splitlines()
    if len(lines) <= max_lines:
        head = text.rstrip()
    else:
        head = "\n".join(lines[:max_lines]).rstrip()
    if len(head) > max_chars:
        head = head[:max_chars].rstrip() + "\n…（预览截断，全文见下载链接）"
    return head or "(empty file)"


def format_attachment_content_markdown(
    config: AppConfig,
    radar_id: str,
    question: str,
    *,
    llm: LlmBackend | None = None,
    repo_root: Path | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """Materialize attachment(s), summarize body text, include download link.

    This is the grounded path for “分析一下 xxx.log” — not diagnosis paraphrase.

    After the structural heuristic (``summarize_log_text``) an optional local-LLM
    interpretation layer (``generate_log_analysis``) explains the file even when
    it carries no literal PASS/FAIL lines (e.g. Cal_LPNM numeric / "out of limit"
    output). A short preview is shown in a fenced block; Open WebUI does not
    render HTML ``<details>``, so the full body is never inlined — use Download.
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

    push_stream_status(FA_ATTACHMENT_ANALYZE_STATUS)
    kind_by_name = {
        a.file_name: (a.kind or "attachment") for a in available if a.file_name
    }
    materialized, failed = materialize_named_attachments(
        config, rid, targets, kind_by_name=kind_by_name
    )
    by_name = {name: (path, rel, url) for name, path, rel, url in materialized}
    fail_by_name = dict(failed)

    # Lazily build a LOCAL LLM backend for the interpretation layer, but only
    # for offline backends that fail fast at load time (mlx/transformers). We
    # do NOT auto-build the openai backend here: it would construct a client
    # with no server and then hang on a (default 180s) network timeout in
    # environments without a running server. The FA agent passes its own real
    # backend via `llm=`. If `llm` stays None we keep the heuristic summary
    # only (graceful degradation).
    if llm is None and config.generation.llm_backend in {"mlx", "transformers"}:
        try:
            llm = build_llm_backend(config)
        except Exception:
            logger.warning("LLM backend unavailable for log analysis", exc_info=True)
            llm = None
    if llm is not None and repo_root is None:
        repo_root = find_repo_root()

    for name in targets:
        lines.append("")
        if name in fail_by_name:
            lines.append(f"#### `{name}`")
            lines.append(f"读取失败：{fail_by_name[name]}")
            continue
        if name not in by_name:
            lines.append(f"#### `{name}`")
            lines.append("读取失败：附件未物化")
            continue
        path, _rel, url = by_name[name]

        text = read_attachment_text(path)
        lines.extend(summarize_log_text(text, file_name=name))

        # LLM interpretation layer — grounded in file bytes + Radar fail context.
        if llm is not None and repo_root is not None:
            try:
                interp = generate_log_analysis(
                    problem, name, text,
                    llm=llm, repo_root=repo_root, cancel_event=cancel_event,
                )
            except Exception:
                logger.warning("Log interpretation failed", exc_info=True)
                interp = None
            if interp:
                lines.append("")
                lines.append("**AI 解读（基于文件字节 + Radar fail 上下文）：**")
                lines.append("")
                lines.append(interp)

        lines.append(f"**Download:** [`{name}`]({url})")
        # Open WebUI does not render <details>; keep a short preview only and
        # point to the download link for the full file.
        lines.append("")
        lines.append("**预览（前 40 行）：**")
        lines.append("")
        lines.append("```text")
        lines.append(_preview_text(text))
        lines.append("```")
        if text.count("\n") >= 40 or len(text) > 4000:
            lines.append("")
            lines.append(f"_全文见 [下载 `{name}`]({url})。_")

    if config.fa.radar.backend == "stub":
        lines.extend(
            [
                "",
                "_Stub：正文是占位 PASS 文本，不是真机 unit log。"
                "切 `fa.radar.backend: radarclient` 后这里才是 Radar 真附件。_",
            ]
        )
    return "\n".join(lines) + "\n"
