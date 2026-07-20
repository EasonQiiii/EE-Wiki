"""LLM-based intent classification to select the prompt task automatically.

When the caller does not specify an explicit ``task``, the local LLM
classifies the user question into one of the known task categories
(wiki, debug, fa, design_review) so the correct prompt template is loaded.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.protocols.llm import LlmBackend

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
_ROLES_LINE = re.compile(r"^ROLES:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_TASK_LINE = re.compile(r"^TASK:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_FA_KIND_LINE = re.compile(r"^KIND:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
VALID_FA_MESSAGE_KINDS: frozenset[str] = frozenset({"evidence", "stay"})


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
    """Classify an FA-session turn as ``evidence`` or ``stay`` (prompt-driven).

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
        ``evidence`` or ``stay``, or ``None`` when output is unusable so the
        caller can default to ``stay`` (session lock, ask again).
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
    for kind in VALID_FA_MESSAGE_KINDS:
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
