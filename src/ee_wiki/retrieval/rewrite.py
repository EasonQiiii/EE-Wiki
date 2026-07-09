"""Query rewriting for multi-turn conversation continuity.

Rewrites ambiguous follow-up questions into self-contained retrieval queries
using conversation history context and the local LLM.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.protocols.llm import LlmBackend

logger = get_logger(__name__)

MAX_HISTORY_TURNS = 4
MAX_REWRITE_TOKENS = 128


@dataclass(frozen=True)
class ConversationTurn:
    """A single turn in conversation history."""

    role: str
    content: str


def _load_rewrite_template(repo_root: Path) -> str:
    """Load the rewrite prompt template from prompts/rewrite/default.md.

    Args:
        repo_root: Repository root path.

    Returns:
        Raw template text.
    """
    path = repo_root / "prompts" / "rewrite" / "default.md"
    return path.read_text(encoding="utf-8")


def _render_rewrite_prompt(template: str, *, history: str, question: str) -> str:
    """Substitute {{history}} and {{question}} in the rewrite template."""
    return template.replace("{{history}}", history).replace("{{question}}", question).strip()


def needs_rewrite(question: str, history: list[ConversationTurn]) -> bool:
    """Determine if a question likely needs rewriting based on heuristics.

    Args:
        question: The current user question.
        history: Prior conversation turns.

    Returns:
        True if the question appears to depend on prior context.
    """
    if not history:
        return False

    has_prior_user = any(t.role == "user" for t in history)
    if not has_prior_user:
        return False

    short_threshold = 60
    pronoun_indicators = (
        "它", "这个", "那个", "该", "上面", "前面", "刚才",
        "this", "that", "it", "its", "the same", "above",
        "继续", "展开", "详细", "更多",
    )
    question_lower = question.lower()

    if len(question) < short_threshold:
        for indicator in pronoun_indicators:
            if indicator in question_lower:
                return True

    if len(question) < 20 and has_prior_user:
        return True

    return False


def needs_answer_history(
    question: str,
    history: list[ConversationTurn],
    *,
    task: str | None = None,
    prepared_task: str | None = None,
    retrieval_query: str | None = None,
) -> bool:
    """Return whether prior turns should appear in the answer-generation prompt.

    Unrelated new questions in the same Open WebUI chat should not inherit
    conversation context. History is included when prepare/classify signals
    a follow-up (``translate`` task or rewritten retrieval query) or when
    cheap rewrite heuristics indicate the question depends on prior turns.

    Args:
        question: Current user question.
        history: Prior conversation turns.
        task: Resolved prompt task from caller or post-retrieval classification.
        prepared_task: Task label from merged prepare, if any.
        retrieval_query: Retrieval query after prepare/rewrite, if any.

    Returns:
        True when conversation history should be injected into answer prompts.
    """
    if not history:
        return False

    effective_task = task if task is not None else prepared_task
    if effective_task == "translate":
        return True

    if retrieval_query is not None and retrieval_query.strip() != question.strip():
        return True

    return needs_rewrite(question, history)


def format_history(history: list[ConversationTurn], max_turns: int = MAX_HISTORY_TURNS) -> str:
    """Format conversation history for the rewrite prompt.

    Args:
        history: Full conversation history (excluding current question).
        max_turns: Maximum number of recent turns to include.

    Returns:
        Formatted history string for template substitution.
    """
    recent = history[-max_turns:] if len(history) > max_turns else history
    lines: list[str] = []
    for turn in recent:
        role_label = "User" if turn.role == "user" else "Assistant"
        content = turn.content
        if turn.role == "assistant" and len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"[{role_label}]: {content}")
    return "\n".join(lines)


def rewrite_query(
    question: str,
    history: list[ConversationTurn],
    *,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
    max_history_turns: int = MAX_HISTORY_TURNS,
) -> str:
    """Rewrite a follow-up question into a self-contained retrieval query.

    Uses the local LLM with the rewrite prompt template to produce a
    standalone query that resolves pronouns and references from history.

    Args:
        question: The current user question (potentially ambiguous).
        history: Prior conversation turns for context.
        llm: LLM backend for generation.
        repo_root: Repository root for loading prompt templates.
        cancel_event: Optional cancellation signal.
        max_history_turns: Maximum history turns to include in prompt.

    Returns:
        Rewritten self-contained query, or the original question if
        rewriting fails or is unnecessary.
    """
    if cancel_event and cancel_event.is_set():
        return question

    if not needs_rewrite(question, history):
        logger.debug("Query rewrite skipped (self-contained): %s", question[:80])
        return question

    history_text = format_history(history, max_turns=max_history_turns)
    template = _load_rewrite_template(repo_root)
    prompt = _render_rewrite_prompt(template, history=history_text, question=question)

    logger.info("Rewriting query with conversation context (%d history turns)", len(history))

    try:
        if callable(getattr(llm, "generate_stream", None)):
            parts: list[str] = []
            for fragment in llm.generate_stream(
                prompt,
                max_new_tokens=MAX_REWRITE_TOKENS,
                cancel_event=cancel_event,
            ):
                if cancel_event and cancel_event.is_set():
                    return question
                parts.append(fragment)
            rewritten = "".join(parts).strip()
        else:
            rewritten = llm.generate(prompt, max_new_tokens=MAX_REWRITE_TOKENS).strip()
    except Exception:
        logger.warning("Query rewrite failed, using original question", exc_info=True)
        return question

    if not rewritten:
        logger.warning("Query rewrite returned empty result, using original")
        return question

    rewritten = rewritten.strip().strip('"').strip("'").strip()
    if len(rewritten) > len(question) * 5:
        logger.warning("Rewritten query suspiciously long, using original")
        return question

    logger.info("Query rewritten: %r -> %r", question[:60], rewritten[:80])
    return rewritten
