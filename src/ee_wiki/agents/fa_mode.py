"""Chat-mode gating: decide FA vs Wiki before routing (fa-session.md A/B/C).

This is the single entry gate for the Chat Runtime. ``resolve_chat_mode`` runs
*before* the Wiki Supervisor so an FA-intent turn (with or without a Radar id)
never silently falls through to hybrid RAG. When the gate returns ``"fa"`` the
pipeline routes to :class:`ee_wiki.agents.fa_agent.FaAgent`; otherwise the
existing Supervisor / RAG path runs unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from ee_wiki.common.config import AppConfig
from ee_wiki.integrations.fa_chat import parse_fa_checkin_radar_id
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn

# Structural FA session headers (bound ticket, or unbound ephemeral session).
_FA_BOUND_HEADER = re.compile(
    r"##\s*FA check-in\s*[—-]\s*rdar://(\d{5,})", re.IGNORECASE
)
_FA_UNBOUND_HEADER = re.compile(
    r"(?:FA\s*session\s*[—-]\s*unbound|FA（未绑定\s*Radar）)", re.IGNORECASE
)

# Pure schematic / connectivity asks — must not enter unbound FA as a "symptom".
# Includes net/trace *property* follow-ups (impedance / equal-length / SI) that
# carry no failure-investigation language — these are parameter lookups, not FA.
_WIKI_CONNECTIVITY = re.compile(
    r"(?:完整\s*trace|追网|trace\s*(?:the\s+)?net|"
    r"阻抗|等长布线|信号完整性|stack[-\s]?up|叠层|"
    r"原理图.{0,60}(?:trace|追网|连通)|"
    r"(?:trace|追网|连通).{0,60}原理图|"
    r"\bconnectivity\b|\bnet\s*trace\b)",
    re.IGNORECASE | re.DOTALL,
)
_FA_FAILURE_CUES = re.compile(
    r"(?:fail(?:ure)?|失效|异常|没输出|无输出|客退|\bRMA\b|"
    r"帮我\s*FA|根因|true[\s-]?fail|报错|排查为什么|"
    r"rdar://|radar://)",
    re.IGNORECASE,
)

# Methodology / advice asks about HOW to do FA (not an active investigation).
# These should stay in readable Wiki mode, not open the heavy unbound FA
# artifact. Pairs with `_FA_REAL_INVESTIGATION` below.
_FA_ADVICE = re.compile(
    r"(?:怎么\s*FA|如何\s*FA|应该怎么\s*FA|怎么\s*分析|如何\s*分析|"
    r"分析思路|排查思路|应该.{0,12}怎么\s*(?:查|分析|FA)|"
    r"FA\s*的?\s*(?:思路|方法|步骤|怎么|如何)|"
    r"如何\s*(?:做|进行)\s*FA|怎么\s*(?:做|进行)\s*FA|"
    r"FA\s*(?:该|要)\s*怎么)",
    re.IGNORECASE,
)
# Strong signals that the user is launching a REAL investigation now (not advice).
_FA_REAL_INVESTIGATION = re.compile(
    r"(帮我\s*FA|根因|rdar://|radar://|量到|测到|确认是|开路|短路|"
    r"observe|measure|detect)",
    re.IGNORECASE,
)

ChatMode = Literal["fa", "wiki"]


def is_fa_advice_without_investigation(question: str) -> bool:
    """True when the question asks ABOUT the FA process (methodology/advice)
    rather than launching a real failure investigation.

    Such questions belong in readable Wiki mode, not the heavy unbound FA
    artifact. A real investigation (帮我FA / radar:// / 量到开路 …) still routes
    to FA because ``_FA_REAL_INVESTIGATION`` short-circuits this.
    """
    q = question.strip()
    if not q:
        return False
    if not _FA_ADVICE.search(q):
        return False
    if _FA_REAL_INVESTIGATION.search(q):
        return False
    return True


def is_wiki_connectivity_query(question: str) -> bool:
    """Return True for schematic-trace asks without failure-investigation language.

    Used as a structural override so ``logan p1 原理图 … 完整trace`` stays in
    Wiki mode even when an unbound FA header is sticky in history, or when the
    mode LLM over-classifies net names as FA symptoms.
    """
    q = question.strip()
    if not q:
        return False
    if _FA_FAILURE_CUES.search(q):
        return False
    return bool(_WIKI_CONNECTIVITY.search(q))


def _history_is_fa_session(history: Sequence[ConversationTurn] | None) -> bool:
    """Return True when the most recent assistant turn is an FA session.

    Mirrors :func:`fa_session_radar_id_from_history`: we stop at the first
    assistant turn that is not an FA header, so an older FA reply buried in a
    long mixed history cannot re-bind the turn to FA mode.
    """
    if not history:
        return False
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        if _FA_BOUND_HEADER.search(turn.content) or _FA_UNBOUND_HEADER.search(
            turn.content
        ):
            return True
        return False
    return False


def resolve_chat_mode(
    question: str,
    history: Sequence[ConversationTurn] | None,
    *,
    llm: LlmBackend | None,
    config: AppConfig,
    cancel_event=None,
) -> ChatMode:
    """Decide whether this turn is FA or Wiki mode (fa-session.md A/B/C).

    Decision order (cheapest first):

    1. Structural Radar id in the question → ``"fa"``.
    2. FA *advice / methodology* (怎么FA / 应该怎么FA / 如何分析 …) without a
       real-investigation signal → ``"wiki"`` (readable answer, no heavy unbound
       FA artifact). A real investigation (帮我FA / radar:// / 量到开路 …) is NOT
       advice and still routes to FA.
    3. Structural wiki connectivity (完整trace / 追网 / …, no failure cues)
       → ``"wiki"`` (escapes sticky unbound FA and LLM over-classify).
    4. History already an FA session (bound or unbound header) → ``"fa"``.
    5. LLM classify via ``prompts/fa/classify_mode.md`` → ``"fa"`` | ``"wiki"``.
    6. Otherwise (no LLM / classify failed / FA disabled) → ``"wiki"``
       (conservative default).

    Args:
        question: Latest user utterance.
        history: Prior conversation turns (excluding the current message).
        llm: Optional local LLM used for semantic mode classification.
        config: Application configuration (``fa.enabled`` gates the FA path).
        cancel_event: Optional cancellation signal for the LLM call.

    Returns:
        ``"fa"`` or ``"wiki"``.
    """
    if parse_fa_checkin_radar_id(question):
        return "fa"
    if is_fa_advice_without_investigation(question):
        return "wiki"
    if is_wiki_connectivity_query(question):
        return "wiki"
    if _history_is_fa_session(history):
        return "fa"
    if config.fa.enabled and llm is not None:
        from ee_wiki.generation.classify import classify_fa_mode

        mode = classify_fa_mode(
            question,
            history=history,
            llm=llm,
            repo_root=config.repo_root,
            cancel_event=cancel_event,
        )
        if mode in ("fa", "wiki"):
            return mode
    return "wiki"
