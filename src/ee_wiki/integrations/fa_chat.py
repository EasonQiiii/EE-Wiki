"""Open WebUI FA entry: Radar check-in and session-locked turns (ADR 0010).

Lightweight intent routing — not the V4 agent supervisor. Full ``agents/``
FA orchestration still waits on ADR 0008 §8.

Semantic judgments (evidence vs FA dialogue) use the local LLM and
``prompts/fa/classify_message.md`` / ``session_reply.md``. Regex here is only
for structural tokens (Radar ids in headers / URLs), not for "does this look
like a log?".
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.session import ingest_fa_user_evidence, start_fa_checkin
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn

logger = get_logger(__name__)

# Structural entry: Radar URL / id tokens (not semantic "is this FA?" NLP).
# The scheme may be followed by an optional URL path segment such as
# `problem/` (real Radar URLs look like `rdar://problem/{id}`).
_CHECKIN_VERB = re.compile(
    r"(?:new\s+check\s*in|check\s*in|开案|"
    r"(?:帮(?:我|忙)\s*)?(?:做(?:个|一下)?\s*)?(?:FA|分析)(?:\s*一下)?|"
    r"FA(?:\s*一下)?)\s*"
    r"(?:rdar://|radar://|radar\s+)(?:[A-Za-z0-9_-]+/)?(?P<id>\d{5,})",
    re.IGNORECASE,
)
_CHECKIN_RADAR_ANYWHERE = re.compile(
    r"(?:rdar://|radar://|radar\s+)(?:[A-Za-z0-9_-]+/)?(?P<id>\d{5,})",
    re.IGNORECASE,
)
_FA_SESSION_RADAR = re.compile(
    r"FA check-in\s*[—-]\s*rdar://(?P<id>\d{5,})",
    re.IGNORECASE,
)
_STATION_LINE = re.compile(
    r"^\s*station\s*[:=]\s*(?P<station>\S.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_EVIDENCE_MARKERS = re.compile(
    r"(?:ERROR|FAIL|NG\b|FAIL:|ERROR:)",
    re.IGNORECASE,
)
# The check-in markdown renders attachments under "### Attachments" (V2) or
# the legacy "### Radar attachments（按需下载）", with each file as a
# backtick-quoted name (including names folded inside a <details> block).
# Structural parse only.
_ATTACHMENT_SECTION = re.compile(
    r"###\s*(?:Radar\s+)?attachments[^\n]*\n(.*?)(?=\n###|\Z)",
    re.IGNORECASE | re.DOTALL,
)
# Structural pre-filter only (NOT a verbatim-router): does the question touch
# diagnosis steps at all? The actual list/summarize/latest decision is made by
# the LLM classifier `classify_diagnosis_intent` (ADR 0013: regex = structural
# tokens only). Keeping this narrow keyword set is acceptable because it only
# gates *whether* to call the classifier, not *how* to answer.
_ABOUT_DIAGNOSIS_STEPS = re.compile(
    r"(?:diagnosis|诊断|步骤|timeline|进度|已完成|"
    r"做了什么|列一下|列出|FA\s*步骤|排查步骤)",
    re.IGNORECASE,
)

# Structural export-intent token (NOT semantic classification): does the
# question ask to produce an FA one-page Keynote / report? Kept to a tight
# token set (keynote | one page | 一页纸 | 导出报告) so it is a structural
# fast-path only, not a "does this look like an export?" NLP gate (ADR 0013).
_ABOUT_FA_KEYNOTE = re.compile(
    r"(?:keynote|one[.\s-]?page|一页纸|导出报告|整理成.*(?:keynote|一页纸))",
    re.IGNORECASE,
)


def parse_fa_checkin_radar_id(text: str) -> str | None:
    """Extract a Radar id from a user message for FA check-in.

    Structural tokens (any of these, anywhere in the utterance):

    - ``rdar://101493937`` / ``radar://101493937``
    - ``rdar://problem/101493937`` (real Radar web / paste format)
    - ``radar 101493937``

    No Chinese verb like 「分析」 is required.

    Args:
        text: Latest user utterance.

    Returns:
        Digits-only Radar id, or ``None`` when no Radar token is present.
    """
    stripped = text.strip()
    if not stripped:
        return None
    # Prefer explicit URL / radar+digits anywhere (structural, not NLP).
    match = _CHECKIN_RADAR_ANYWHERE.search(stripped)
    if match:
        return normalize_radar_id(match.group("id"))
    # Verb + bare digits (e.g. 「分析 12345678」 without scheme).
    match = _CHECKIN_VERB.search(stripped)
    if match:
        return normalize_radar_id(match.group("id"))
    return None


def fa_session_radar_id_from_history(
    history: Sequence[ConversationTurn] | None,
) -> str | None:
    """Return Radar id when this chat is already an FA session.

    Looks for an assistant ``FA check-in — rdar://…`` header. Once present,
    the chat stays on the FA path (no silent RAG fallthrough).

    Args:
        history: Prior turns (excluding the current user message).

    Returns:
        Bound Radar id, or ``None`` when this is not an FA chat.
    """
    if not history:
        return None
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        match = _FA_SESSION_RADAR.search(turn.content)
        if match:
            return normalize_radar_id(match.group("id"))
        # Stop at the first assistant turn without an FA header so an older
        # FA reply in a long mixed history does not re-bind the session.
        return None
    return None


def awaiting_radar_id_from_history(
    history: Sequence[ConversationTurn] | None,
) -> str | None:
    """Return Radar id when the last FA assistant turn asked for test evidence.

    Args:
        history: Prior turns (excluding the current user message).

    Returns:
        Radar id awaiting paste, or ``None``.
    """
    session_id = fa_session_radar_id_from_history(history)
    if not session_id or not history:
        return None
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        awaiting = (
            "Need test evidence" in turn.content
            or "Flames API is not available" in turn.content
            or "please paste" in turn.content.lower()
        )
        return session_id if awaiting else None
    return None


def last_fa_checkin_markdown(
    history: Sequence[ConversationTurn] | None,
) -> str | None:
    """Return the most recent assistant FA check-in markdown from history."""
    if not history:
        return None
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        if _FA_SESSION_RADAR.search(turn.content):
            return turn.content
        return None
    return None


def try_fa_chat_reply(
    config: AppConfig,
    question: str,
    history: Sequence[ConversationTurn] | None = None,
    *,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
    llm: LlmBackend | None = None,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Handle FA check-in / session turns; otherwise return ``None`` for RAG.

    When history already contains an FA check-in, the reply stays on the FA
    path. Turns are ``evidence`` (ingest paste), ``question`` (dialogue from
    check-in context), or ``stay`` (short redirect). Without an LLM, short
    messages default to grounded dialogue — never silent RAG.

    Args:
        config: Application configuration (``fa.enabled`` gates this path).
        question: Current user message.
        history: Prior conversation turns.
        user_product: Optional explicit API product filter.
        user_project: Optional explicit API project filter.
        user_build: Optional explicit API build filter.
        llm: Optional local LLM for classify + dialogue.
        cancel_event: Optional cancellation for LLM calls.

    Returns:
        Markdown reply for Open WebUI, or ``None`` only when this chat is not
        on the FA path yet (caller may continue normal RAG).
    """
    if not config.fa.enabled:
        return None

    checkin_id = parse_fa_checkin_radar_id(question)
    if checkin_id:
        result = start_fa_checkin(
            config,
            checkin_id,
            user_product=user_product,
            user_project=user_project,
            user_build=user_build,
            llm=llm,
            cancel_event=cancel_event,
        )
        logger.info(
            "FA chat check-in radar=%s awaiting=%s",
            checkin_id,
            result.awaiting_user_evidence,
        )
        return result.summary_markdown

    session_id = fa_session_radar_id_from_history(history)
    if not session_id:
        return None

    kind = _classify_session_message(
        config,
        question,
        radar_id=session_id,
        llm=llm,
        cancel_event=cancel_event,
    )
    if kind == "evidence":
        station = _parse_station(question)
        body = _strip_station_line(question)
        result = ingest_fa_user_evidence(
            config,
            session_id,
            body,
            station=station,
            user_product=user_product,
            user_project=user_project,
            user_build=user_build,
        )
        logger.info(
            "FA chat evidence radar=%s fails=%d awaiting=%s",
            session_id,
            len(result.fail_items.fail_items),
            result.awaiting_user_evidence,
        )
        return result.summary_markdown

    checkin = last_fa_checkin_markdown(history) or ""
    if kind == "stay" and _looks_offtopic_wiki(question):
        logger.info("FA chat session stay (off-topic) radar=%s", session_id)
        return _session_offtopic_reply(session_id)

    logger.info("FA chat session dialogue radar=%s kind=%s", session_id, kind)
    return _session_dialogue_reply(
        config,
        question,
        radar_id=session_id,
        checkin_markdown=checkin,
        llm=llm,
        cancel_event=cancel_event,
    )


def _classify_session_message(
    config: AppConfig,
    question: str,
    *,
    radar_id: str,
    llm: LlmBackend | None,
    cancel_event: threading.Event | None,
) -> str:
    """Return ``evidence``, ``question``, or ``stay`` for a bound FA turn."""
    if llm is None:
        if _looks_like_evidence_paste(question):
            logger.info(
                "FA session classify (no LLM) → evidence rdar://%s",
                radar_id,
            )
            return "evidence"
        logger.info(
            "FA session classify (no LLM) → question rdar://%s",
            radar_id,
        )
        return "question"

    from ee_wiki.generation.classify import classify_fa_message

    kind = classify_fa_message(
        question,
        radar_id=radar_id,
        llm=llm,
        repo_root=config.repo_root,
        cancel_event=cancel_event,
    )
    if kind in {"evidence", "question", "stay"}:
        return kind
    # Unusable classify → dialogue, not the old rigid paste nag.
    return "question"


def _session_dialogue_reply(
    config: AppConfig,
    question: str,
    *,
    radar_id: str,
    checkin_markdown: str,
    llm: LlmBackend | None,
    cancel_event: threading.Event | None,
) -> str:
    """Answer an FA follow-up from check-in / Radar (diagnosis is authoritative)."""
    rid = normalize_radar_id(radar_id)

    # Structural pre-filter: does the question touch diagnosis steps at all?
    asks_steps = bool(_ABOUT_DIAGNOSIS_STEPS.search(question))

    problem = None
    if asks_steps:
        from ee_wiki.integrations.factory import build_radar_backend
        from ee_wiki.integrations.radar.evidence import (
            format_latest_diagnosis_action,
            format_radar_diagnosis_steps,
            user_diagnosis_entries,
        )

        try:
            problem = build_radar_backend(config).get_problem(radar_id)
        except Exception:
            logger.warning("Radar get_problem failed (steps intent)", exc_info=True)
            problem = None

        if problem is not None:
            # No LLM available: the deterministic verbatim list is the safe,
            # exact answer (covers "列出/总结" without a classifier).
            if llm is None:
                return format_radar_diagnosis_steps(problem, include_history=True)

            from ee_wiki.generation.classify import (
                classify_diagnosis_intent,
                summarize_radar_diagnosis,
            )

            intent = classify_diagnosis_intent(
                question,
                llm=llm,
                repo_root=config.repo_root,
                cancel_event=cancel_event,
            )
            if intent == "list_steps":
                # Deterministic verbatim list — no LLM, fast and exact.
                return format_radar_diagnosis_steps(problem, include_history=True)
            if intent == "latest_action":
                return format_latest_diagnosis_action(problem)
            # summarize_steps / other / unrecognized (None) → try LLM brief
            # summary first. Unrecognized must NOT dump the full verbatim list
            # (that was Problem 2: "简要总结" after a bad KIND parse). Fall back
            # to the verbatim list only when summarization is unavailable.
            summary = None
            if intent in ("summarize_steps", "other", None) and user_diagnosis_entries(
                problem
            ):
                summary = summarize_radar_diagnosis(
                    problem,
                    question,
                    llm=llm,
                    repo_root=config.repo_root,
                    cancel_event=cancel_event,
                )
            if summary:
                return f"## FA check-in — rdar://{rid}\n\n{summary}"
            return format_radar_diagnosis_steps(problem, include_history=True)

    # Build enriched context (verbatim steps) for the generic LLM reply.
    enriched = checkin_markdown
    if not re.search(r"###\s*Diagnosis", checkin_markdown, re.IGNORECASE):
        if problem is None:
            from ee_wiki.integrations.factory import build_radar_backend
            from ee_wiki.integrations.radar.evidence import format_radar_diagnosis_steps

            try:
                problem = build_radar_backend(config).get_problem(radar_id)
            except Exception:
                logger.warning("Radar get_problem failed (enrich)", exc_info=True)
                problem = None
        if problem is not None:
            steps = format_radar_diagnosis_steps(problem)
            if steps.strip():
                enriched = f"{checkin_markdown.rstrip()}\n\n{steps}"

    if llm is not None and enriched.strip():
        from ee_wiki.generation.classify import generate_fa_session_reply

        generated = generate_fa_session_reply(
            question,
            radar_id=radar_id,
            checkin_markdown=enriched,
            llm=llm,
            repo_root=config.repo_root,
            cancel_event=cancel_event,
        )
        if generated:
            if "FA check-in" not in generated:
                return (
                    f"## FA check-in — rdar://{rid}\n\n"
                    f"{generated}"
                )
            return generated

    return _deterministic_session_reply(radar_id, question, enriched, config=config)


def _mention_flames(question: str, config: AppConfig | None) -> bool:
    """Gate Flames mentions: only when the user asks, or flames backend != manual.

    When the backend is ``manual`` (default) and the user didn't mention Flames,
    replies must keep Flames entirely out (Problem 5, root C) — the old reply
    wrongly nudged for Flames paste on every log question.
    """
    q = (question or "").lower()
    if "flames" in q or "火焰" in q:
        return True
    if config is None:
        return False
    flames = getattr(getattr(config, "fa", None), "flames", None)
    backend = getattr(flames, "backend", "manual")
    return backend != "manual"


def _deterministic_session_reply(
    radar_id: str,
    question: str,
    checkin_markdown: str,
    *,
    config: AppConfig | None = None,
) -> str:
    """Grounded FA dialogue without LLM (attachments / next steps / logs)."""
    rid = normalize_radar_id(radar_id)
    lines = [f"## FA check-in — rdar://{rid}", ""]
    q = question.strip()
    attachments = _parse_attachment_names(checkin_markdown)
    has_fail_items = bool(
        re.search(r"### Fail items\n(?:- .+\n)+", checkin_markdown)
    )
    needs_paste = "Need test evidence" in checkin_markdown
    about_log = bool(
        re.search(r"log|日志|附件|attachment|evidence|证据", q, re.IGNORECASE)
    )
    about_next = bool(
        re.search(r"下一步|接下来|next|怎么继续|然后呢|继续", q, re.IGNORECASE)
    )

    if about_log:
        if attachments:
            names = ", ".join(f"`{n}`" for n in attachments)
            lines.append(f"Radar 上已经挂了附件：{names}。")
            lines.append("")
            lines.append(
                "已缓存的可直接打开；未缓存的说「下载 <文件名>」即按需取回正文，"
                "取回后我可帮你读 PASS/FAIL、做摘要或对照 fail items。"
            )
            if has_fail_items:
                lines.append("")
                lines.append(
                    "本 Radar 已从 Radar 文本抽出了 fail items；"
                    "若你要对照原始 log 正文，下载对应附件即可，或把关键片段贴到这里。"
                )
            if _mention_flames(question, config):
                lines.append("")
                lines.append(
                    "Flames 产线 log 走 flames 后端（非 manual 时自动）；需要的话告诉我。"
                )
        elif needs_paste:
            lines.append(
                "这个 check-in 里还没有列出可用的 Radar 附件名。"
            )
            if _mention_flames(question, config):
                lines.append("Flames 也还没拿到 fail items。")
            lines.append(
                "可以贴一段带 ERROR/FAIL 的 log，或 bullet 失败项，我再继续整理。"
            )
        else:
            lines.append(
                "当前 check-in 没有列出 Radar 附件名。"
            )
            if _mention_flames(question, config):
                lines.append(
                    "若该 Radar 上确实有 log，可在 Radar 客户端打开下载，或把关键片段贴到这里。"
                )
        return "\n".join(lines)

    if about_next or not q:
        if has_fail_items:
            lines.append("目前 check-in 里 **已经有 fail items**（来自 Radar 文本/诊断）。")
            lines.append("")
            lines.append("建议下一步：")
            lines.append("1. 标出哪些是 **true fail**（相对 fixture / SW / setup）")
            lines.append("2. 选定要追的模块 / 网络 / 位号，我再帮你对 EE-Wiki 知识库或追网")
            if attachments:
                lines.append(
                    "3. 若要核对原始数据：Radar 附件 "
                    + ", ".join(f"`{n}`" for n in attachments)
                    + "（下载正文后我可帮你读；本聊天按需拉取，不整批下载）"
                )
        elif needs_paste:
            lines.append(
                "下一步：补测试证据。优先贴 **ERROR/FAIL 行** 或失败 bullet 列表；"
                "可选 `station: <工站>`。"
            )
        else:
            lines.append(
                "下一步：确认 scope / 现象，或贴 fail 列表后继续模块排查。"
            )
        return "\n".join(lines)

    # Generic grounded summary of what we already know
    lines.append("还在这张 FA 会话里。根据上一轮 check-in：")
    lines.append("")
    if attachments:
        lines.append(
            "- Radar 附件名："
            + ", ".join(f"`{n}`" for n in attachments)
            + "（元数据；已缓存的可直接打开，其余按需下载）"
        )
    if has_fail_items:
        lines.append("- 已抽出 fail items — 请指出 true fail 以继续")
    elif needs_paste:
        lines.append("- 仍缺结构化 fail 证据 — 可贴 ERROR/FAIL log 或 bullet 列表")
    lines.append("")
    lines.append("你可以直接问「有没有 log」「下一步做什么」，或点名某个 fail item。")
    return "\n".join(lines)


def _session_offtopic_reply(radar_id: str) -> str:
    """Short redirect when the user asks a general wiki question in FA chat."""
    rid = normalize_radar_id(radar_id)
    return (
        f"## FA check-in — rdar://{rid}\n\n"
        "这句更像通用 wiki / 器件查询，和本 Radar 的 FA triage 无关。\n\n"
        "- 继续本 Radar：问 fail items、Radar 附件、下一步排查，或贴 ERROR/FAIL log\n"
        "- 查通用知识：请 **新开** 一个 Open WebUI 对话（本线程不会静默切到 RAG）"
    )


def _parse_attachment_names(checkin_markdown: str) -> list[str]:
    match = _ATTACHMENT_SECTION.search(checkin_markdown)
    if not match:
        return []
    return [n.strip("` ") for n in re.findall(r"`([^`]+)`", match.group(1))]


def _looks_like_evidence_paste(text: str) -> bool:
    """Structural hint when no LLM: multi-line paste with fail markers."""
    stripped = text.strip()
    if len(stripped) < 40:
        return False
    if _EVIDENCE_MARKERS.search(stripped):
        return True
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    return len(lines) >= 8 and len(stripped) >= 200


def _looks_offtopic_wiki(text: str) -> bool:
    """Conservative off-topic hint (wiki params) when classify returns stay."""
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    return bool(
        re.search(
            r"(?:核心参数|datasheet|数据手册|怎么翻译|what is|pinout 是什么)",
            stripped,
            re.IGNORECASE,
        )
    )


def _parse_station(text: str) -> str | None:
    match = _STATION_LINE.search(text)
    if not match:
        return None
    return match.group("station").strip()


def _strip_station_line(text: str) -> str:
    return _STATION_LINE.sub("", text).strip()
