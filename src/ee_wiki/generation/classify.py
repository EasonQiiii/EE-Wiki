"""LLM-based intent classification to select the prompt task automatically.

When the caller does not specify an explicit ``task``, the local LLM
classifies the user question into one of the known task categories
(wiki, debug, fa, design_review) so the correct prompt template is loaded.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.protocols.radar import RadarProblem
from ee_wiki.retrieval.rewrite import ConversationTurn

logger = get_logger(__name__)

VALID_TASKS: frozenset[str] = frozenset({
    "wiki",
    "debug",
    "fa",
    "design_review",
    "power",
    "rules",
    "translate",
})

MAX_CLASSIFY_TOKENS = 16
MAX_AGENT_ROUTE_TOKENS = 48
MAX_FA_MESSAGE_TOKENS = 16
MAX_FA_SESSION_REPLY_TOKENS = 512
_ROLES_LINE = re.compile(r"^ROLES:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_TASK_LINE = re.compile(r"^TASK:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_FA_KIND_LINE = re.compile(r"^KIND:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_SKILLS_LINE = re.compile(r"^SKILLS:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

# Reasoning wrappers some local LLMs emit before the structured line. We only
# DELETED them (never interpret) — after stripping, if no KIND:/SKILLS: line
# remains, the caller keeps its None -> dialogue/file fallback (Problem 5 D).
_REASONING_WRAPPERS = [
    re.compile(r"<analysis>.*?</analysis>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL),
    re.compile(r"```reasoning.*?```", re.IGNORECASE | re.DOTALL),
    # Unterminated leading wrapper that precedes the structured line.
    re.compile(r"<analysis>.*?(?=\nKIND:|\nSKILLS:)", re.IGNORECASE | re.DOTALL),
    re.compile(r"<think>.*?(?=\nKIND:|\nSKILLS:)", re.IGNORECASE | re.DOTALL),
]


def _strip_reasoning(text: str) -> str:
    """Remove chain-of-thought wrappers so ``KIND:``/``SKILLS:`` parse cleanly.

    Purely structural: we delete wrapper text (including a leading
    unterminated ``<analysis>``/``<think>`` that runs up to the structured
    line) and return the rest. No semantic interpretation is performed.
    """
    if not text:
        return text
    out = text
    for pat in _REASONING_WRAPPERS:
        out = pat.sub("", out)
    return out.strip()
VALID_FA_MESSAGE_KINDS: frozenset[str] = frozenset(
    {"evidence", "question", "stay"}
)
VALID_DIAGNOSIS_INTENT_KINDS: frozenset[str] = frozenset(
    {"list_steps", "summarize_steps", "latest_action", "other"}
)
MAX_DIAGNOSIS_INTENT_TOKENS = 16
MAX_DIAGNOSIS_SUMMARY_TOKENS = 384


@dataclass(frozen=True)
class AgentRoute:
    """One semantic routing decision shared by Supervisor and generation."""

    task: str
    roles: tuple[str, ...]


def _load_classify_template(repo_root: Path) -> str:
    """Load the classification prompt from ``prompts/classify/default.md``.

    Args:
        repo_root: Repository root path.

    Returns:
        Raw template text.
    """
    path = repo_root / "prompts" / "classify" / "default.md"
    return path.read_text(encoding="utf-8")


def _render_classify_prompt(template: str, *, question: str) -> str:
    """Substitute ``{{question}}`` in the classify template."""
    return template.replace("{{question}}", question).strip()


def _generate_short_output(
    llm: LlmBackend,
    prompt: str,
    *,
    max_new_tokens: int,
    cancel_event: threading.Event | None,
) -> str:
    """Generate a short classifier response from either LLM interface."""
    if callable(getattr(llm, "generate_stream", None)):
        parts: list[str] = []
        for fragment in llm.generate_stream(
            prompt,
            max_new_tokens=max_new_tokens,
            cancel_event=cancel_event,
        ):
            if cancel_event and cancel_event.is_set():
                return ""
            parts.append(fragment)
        return "".join(parts).strip()
    return llm.generate(prompt, max_new_tokens=max_new_tokens).strip()


def classify_fa_message(
    question: str,
    *,
    radar_id: str,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Classify an FA-session turn as ``evidence``, ``question``, or ``stay``.

    Used when a chat is already bound to a Radar id so the session stays on
    the FA path (no silent RAG fallthrough). Semantic judgment lives in
    ``prompts/fa/classify_message.md`` — not hardcoded keyword lists.

    Args:
        question: Latest user utterance in the FA chat.
        radar_id: Bound Radar id for prompt context.
        llm: Local LLM backend.
        repo_root: Repository root for loading the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        ``evidence``, ``question``, or ``stay``, or ``None`` when output is
        unusable so the caller can default to a grounded dialogue reply.
    """
    if cancel_event and cancel_event.is_set():
        return None

    path = repo_root / "prompts" / "fa" / "classify_message.md"
    template = path.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{radar_id}}", radar_id)
        .replace("{{question}}", question)
        .strip()
    )

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_FA_MESSAGE_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("FA message classification failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not raw_output:
        return None

    raw_output = _strip_reasoning(raw_output)
    match = _FA_KIND_LINE.search(raw_output)
    raw_kind = match.group(1) if match else raw_output
    cleaned = raw_kind.strip().split("\n")[0].strip()
    cleaned = cleaned.strip('"').strip("'").strip("`").strip().lower()
    cleaned = re.sub(r"[.。,，;；:：!！?？]", "", cleaned)
    if cleaned in VALID_FA_MESSAGE_KINDS:
        logger.info(
            "FA message kind: %r -> %s (rdar://%s)",
            question[:60],
            cleaned,
            radar_id,
        )
        return cleaned
    for kind in ("evidence", "question", "stay"):
        if kind in cleaned:
            logger.info(
                "FA message kind (containment): %r -> %s (rdar://%s)",
                question[:60],
                kind,
                radar_id,
            )
            return kind
    logger.warning("FA message kind unrecognized: %r", raw_output)
    return None


def classify_diagnosis_intent(
    question: str,
    *,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Classify an FA-session "steps / diagnosis" question intent.

    Decides whether the user wants the diagnosis steps listed verbatim,
    summarized, or only the latest action. Semantic judgment lives in
    ``prompts/fa/diagnosis_intent.md`` — not a hardcoded keyword list
    (ADR 0013: regex = structural tokens only).

    Args:
        question: User utterance about FA steps / diagnosis / timeline.
        llm: Local LLM backend.
        repo_root: Repository root for loading the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        One of ``list_steps``, ``summarize_steps``, ``latest_action``,
        ``other``, or ``None`` when output is unusable so the caller can
        default to a verbatim list (precision over latency).
    """
    if cancel_event and cancel_event.is_set():
        return None

    path = repo_root / "prompts" / "fa" / "diagnosis_intent.md"
    template = path.read_text(encoding="utf-8")
    prompt = template.replace("{{question}}", question).strip()

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_DIAGNOSIS_INTENT_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("Diagnosis intent classification failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not raw_output:
        return None

    raw_output = _strip_reasoning(raw_output)
    match = _FA_KIND_LINE.search(raw_output)
    raw_kind = match.group(1) if match else raw_output
    cleaned = raw_kind.strip().split("\n")[0].strip()
    cleaned = cleaned.strip('"').strip("'").strip("`").strip().lower()
    cleaned = re.sub(r"[.。,，;；:：!！?？]", "", cleaned)
    if cleaned in VALID_DIAGNOSIS_INTENT_KINDS:
        logger.info("Diagnosis intent: %r -> %s", question[:60], cleaned)
        return cleaned
    for kind in VALID_DIAGNOSIS_INTENT_KINDS:
        if kind in cleaned:
            return kind
    logger.warning("Diagnosis intent unrecognized: %r", raw_output)
    return None


def summarize_radar_diagnosis(
    problem: RadarProblem,
    question: str,
    *,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Summarize Radar diagnosis steps via LLM (3-5 bullets, 已完成/待做).

    Used when the user asks for a recap / summary of FA steps. Returns
    concise markdown, or ``None`` when generation fails so the caller can
    fall back to the verbatim list. Does not invent true-fail / root cause.

    Args:
        problem: Normalized Radar snapshot (diagnosis is source of truth).
        question: User utterance asking for a summary.
        llm: Local LLM backend.
        repo_root: Repository root for loading the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        Assistant markdown summary, or ``None`` on failure / empty steps.
    """
    if cancel_event and cancel_event.is_set():
        return None

    from ee_wiki.integrations.radar.evidence import diagnosis_steps_text

    steps_text = diagnosis_steps_text(problem)
    if not steps_text.strip():
        return None

    path = repo_root / "prompts" / "fa" / "summarize_diagnosis.md"
    template = path.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{radar_id}}", problem.radar_id)
        .replace("{{question}}", question)
        .replace("{{steps}}", steps_text)
        .strip()
    )

    try:
        text = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_DIAGNOSIS_SUMMARY_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("FA diagnosis summary generation failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not text or not text.strip():
        return None
    return text.strip()


def generate_fa_session_reply(
    question: str,
    *,
    radar_id: str,
    checkin_markdown: str,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Generate a grounded FA dialogue reply from the last check-in context.

    Args:
        question: Engineer's follow-up in the FA session.
        radar_id: Bound Radar id.
        checkin_markdown: Prior FA check-in assistant markdown.
        llm: Local LLM backend.
        repo_root: Repository root for the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        Assistant markdown, or ``None`` when generation fails.
    """
    if cancel_event and cancel_event.is_set():
        return None

    path = repo_root / "prompts" / "fa" / "session_reply.md"
    template = path.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{radar_id}}", radar_id)
        .replace("{{checkin}}", checkin_markdown.strip()[:6000])
        .replace("{{question}}", question)
        .strip()
    )

    try:
        text = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_FA_SESSION_REPLY_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("FA session reply generation failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not text or not text.strip():
        return None
    return text.strip()


def classify_fa_mode(
    question: str,
    *,
    history: Sequence[ConversationTurn] | None = None,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Classify a turn as FA mode or Wiki mode (fa-session.md entry C).

    Args:
        question: Latest user utterance.
        history: Optional prior turns (rendered as a short summary).
        llm: Local LLM backend.
        repo_root: Repository root for loading the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        ``"fa"``, ``"wiki"``, or ``None`` when output is unusable so the caller
        can fall back to the conservative Wiki default.
    """
    if cancel_event and cancel_event.is_set():
        return None

    path = repo_root / "prompts" / "fa" / "classify_mode.md"
    template = path.read_text(encoding="utf-8")
    history_md = ""
    if history:
        bits = [
            f"{turn.role}: {turn.content[:200]}"
            for turn in history[-4:]
            if turn.role in ("user", "assistant") and turn.content.strip()
        ]
        history_md = "\n".join(bits)
    prompt = (
        template.replace("{{history}}", history_md).replace("{{question}}", question).strip()
    )

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_CLASSIFY_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("FA mode classification failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not raw_output:
        return None

    match = re.search(r"MODE:\s*(\w+)", raw_output, re.IGNORECASE)
    raw_mode = match.group(1) if match else raw_output
    cleaned = raw_mode.strip().lower()
    if cleaned.startswith("fa"):
        return "fa"
    if cleaned.startswith("wiki"):
        return "wiki"
    return None


def select_fa_skills(
    question: str,
    *,
    product: str | None,
    project: str | None,
    build: str | None,
    allowlist: set[str] | frozenset[str],
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> list[str] | None:
    """Select 0..N FaAgent tools for one FA turn (allowlist-validated).

    Args:
        question: Latest user utterance.
        product: Current scope product (or ``None``).
        project: Current scope project (or ``None``).
        build: Current scope build (or ``None``).
        allowlist: Tool names the FaAgent is permitted to call.
        llm: Local LLM backend.
        repo_root: Repository root for loading the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        Selected tool names (subset of ``allowlist``), or ``None`` when the LLM
        output is unusable so the caller can use a deterministic default.
    """
    if cancel_event and cancel_event.is_set():
        return None

    path = repo_root / "prompts" / "fa" / "select_skills.md"
    if not path.is_file():
        return None
    template = path.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{allowlist}}", ", ".join(sorted(allowlist)))
        .replace("{{product}}", product or "none")
        .replace("{{project}}", project or "none")
        .replace("{{build}}", build or "none")
        .replace("{{question}}", question)
        .strip()
    )

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=48,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("FA skill selection failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not raw_output:
        return None

    raw_output = _strip_reasoning(raw_output)
    match = _SKILLS_LINE.search(raw_output)
    raw_line = match.group(1) if match else raw_output
    parts = [p.strip() for p in raw_line.split(",") if p.strip()]
    selected = [skill for skill in parts if skill in allowlist]
    if not selected and parts:
        logger.warning("FA skill selection produced no valid tools: %r", raw_output)
        return None
    return selected


def classify_agent_route(
    question: str,
    *,
    llm: LlmBackend,
    repo_root: Path,
    valid_roles: set[str] | frozenset[str],
    max_roles: int = 2,
    cancel_event: threading.Event | None = None,
) -> AgentRoute | None:
    """Classify one turn into a prompt task and zero or more specialist roles.

    A malformed or failed response returns ``None`` so the Supervisor can use
    its deterministic keyword fallback. ``ROLES: none`` is a valid semantic
    passthrough decision and returns an empty role tuple.
    """
    if cancel_event and cancel_event.is_set():
        return None

    template_path = repo_root / "prompts" / "agents" / "supervisor" / "default.md"
    template = template_path.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{question}}", question)
        .replace("{{max_roles}}", str(max_roles))
        .replace("{{role_ids}}", ", ".join(sorted(valid_roles)))
        .strip()
    )

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_AGENT_ROUTE_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("Agent semantic routing failed", exc_info=True)
        return None

    task_match = _TASK_LINE.search(raw_output)
    roles_match = _ROLES_LINE.search(raw_output)
    if task_match is None or roles_match is None:
        logger.warning("Agent routing output malformed: %r", raw_output)
        return None

    task = _parse_task_label(task_match.group(1))
    if task is None:
        logger.warning("Agent routing task unrecognized: %r", task_match.group(1))
        return None

    raw_roles = roles_match.group(1).strip().lower()
    if raw_roles in {"none", "null", "n/a", "-"}:
        roles: tuple[str, ...] = ()
    else:
        parsed = [item.strip() for item in raw_roles.split(",") if item.strip()]
        roles = tuple(dict.fromkeys(role for role in parsed if role in valid_roles))[
            :max_roles
        ]
        if not roles:
            logger.warning("Agent routing roles unrecognized: %r", raw_roles)
            return None

    logger.info(
        "Agent semantic route: %r -> task=%s roles=%s",
        question[:60],
        task,
        roles,
    )
    return AgentRoute(task=task, roles=roles)


def _parse_task_label(raw: str) -> str | None:
    """Extract a valid task label from LLM output.

    Tries exact match first, then containment match for noisy output
    like ``"任务: debug"`` or ``"category: design_review"``.

    Args:
        raw: Raw LLM output text.

    Returns:
        Valid task label, or ``None`` if no match found.
    """
    cleaned = raw.strip().split("\n")[0].strip()
    cleaned = cleaned.strip('"').strip("'").strip("`").strip()
    cleaned = re.sub(r"[.。,，;；:：!！?？]", "", cleaned)
    cleaned = cleaned.strip().lower()

    if cleaned in VALID_TASKS:
        return cleaned

    for task in VALID_TASKS:
        if task in cleaned:
            return task

    return None


def classify_task(
    question: str,
    *,
    llm: LlmBackend,
    repo_root: Path,
    default_task: str = "wiki",
    cancel_event: threading.Event | None = None,
) -> str:
    """Classify a user question into a prompt task category.

    Uses the local LLM with a short classification prompt. Falls back
    to ``default_task`` on any failure (empty output, invalid label,
    exception, or cancellation).

    Args:
        question: User question (ideally already rewritten to be
            self-contained).
        llm: LLM backend for generation.
        repo_root: Repository root for loading prompt templates.
        default_task: Fallback task when classification fails.
        cancel_event: Optional cancellation signal.

    Returns:
        One of ``wiki``, ``debug``, ``fa``, or ``design_review``.
    """
    if cancel_event and cancel_event.is_set():
        return default_task

    template = _load_classify_template(repo_root)
    prompt = _render_classify_prompt(template, question=question)

    logger.info("Classifying task intent for question: %s", question[:80])

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_CLASSIFY_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning(
            "Task classification failed, using default: %s",
            default_task,
            exc_info=True,
        )
        return default_task

    if not raw_output:
        logger.warning("Task classification returned empty, using default: %s", default_task)
        return default_task

    task = _parse_task_label(raw_output)
    if task is None:
        logger.warning(
            "Task classification output unrecognized (%r), using default: %s",
            raw_output,
            default_task,
        )
        return default_task

    logger.info("Task classified: %r -> %s", question[:60], task)
    return task
