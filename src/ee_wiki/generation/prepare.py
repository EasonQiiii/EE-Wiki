"""Merged query rewrite and task classification in one LLM call."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.classify import _parse_task_label
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn, format_history, needs_rewrite

logger = get_logger(__name__)

PREPARE_MAX_TOKENS = 160

_QUERY_LINE = re.compile(r"^QUERY:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_TASK_LINE = re.compile(r"^TASK:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class PreparedQuery:
    """Rewrite and task intent produced before retrieval."""

    retrieval_query: str
    task: str | None


def _load_prepare_template(repo_root: Path) -> str:
    """Load the merged prepare prompt from ``prompts/prepare/default.md``."""
    path = repo_root / "prompts" / "prepare" / "default.md"
    return path.read_text(encoding="utf-8")


def _render_prepare_prompt(
    template: str,
    *,
    history: str,
    question: str,
) -> str:
    """Substitute template placeholders."""
    return (
        template.replace("{{history}}", history)
        .replace("{{question}}", question)
        .strip()
    )


def should_prepare_query(
    question: str,
    history: list[ConversationTurn] | None,
    *,
    query_rewrite: bool,
    task_classification: bool,
    caller_task: str | None,
) -> bool:
    """Return whether a merged prepare LLM call is needed.

    Args:
        question: Current user question.
        history: Prior conversation turns.
        query_rewrite: Whether rewrite is enabled in config.
        task_classification: Whether auto task classification is enabled.
        caller_task: Explicit task from the API caller, if any.

    Returns:
        True when rewrite and/or classification should run via :func:`prepare_query`.
    """
    needs_classify = task_classification and caller_task is None
    needs_rw = bool(
        query_rewrite
        and history
        and needs_rewrite(question, history)
    )
    return needs_classify or needs_rw


def _parse_prepare_output(
    raw: str,
    *,
    question: str,
    default_task: str,
    classify: bool,
) -> PreparedQuery:
    """Parse ``QUERY:`` / ``TASK:`` lines from model output."""
    query_match = _QUERY_LINE.search(raw)
    task_match = _TASK_LINE.search(raw)

    retrieval_query = question
    if query_match:
        candidate = query_match.group(1).strip().strip('"').strip("'")
        if candidate:
            max_query_len = max(len(question) * 5, 256)
            if len(candidate) <= max_query_len:
                retrieval_query = candidate
            else:
                logger.warning(
                    "Prepare QUERY line suspiciously long, using original question",
                )

    task: str | None = None
    if classify and task_match:
        parsed = _parse_task_label(task_match.group(1))
        if parsed is not None:
            task = parsed
        else:
            logger.warning(
                "Prepare TASK line unrecognized (%r), using default: %s",
                task_match.group(1).strip(),
                default_task,
            )
            task = default_task
    elif classify:
        logger.warning("Prepare output missing TASK line, using default: %s", default_task)
        task = default_task

    return PreparedQuery(retrieval_query=retrieval_query, task=task)


def _generate_prepare_text(
    llm: LlmBackend,
    prompt: str,
    *,
    cancel_event: threading.Event | None,
) -> str:
    """Run the prepare prompt through the LLM backend."""
    if callable(getattr(llm, "generate_stream", None)):
        parts: list[str] = []
        for fragment in llm.generate_stream(
            prompt,
            max_new_tokens=PREPARE_MAX_TOKENS,
            cancel_event=cancel_event,
        ):
            if cancel_event and cancel_event.is_set():
                return ""
            parts.append(fragment)
        return "".join(parts).strip()
    return llm.generate(prompt, max_new_tokens=PREPARE_MAX_TOKENS).strip()


def prepare_query(
    question: str,
    history: list[ConversationTurn] | None,
    *,
    llm: LlmBackend,
    repo_root: Path,
    default_task: str = "wiki",
    query_rewrite: bool = True,
    task_classification: bool = True,
    caller_task: str | None = None,
    cancel_event: threading.Event | None = None,
    max_history_turns: int = 4,
) -> PreparedQuery:
    """Rewrite and classify a question in one LLM call.

    When rewrite is not needed, the model should return the latest question
    unchanged on the ``QUERY:`` line. When classification is disabled, the
    ``TASK:`` line is ignored and ``task`` is ``None``.

    Args:
        question: Current user question.
        history: Prior conversation turns.
        llm: LLM backend for generation.
        repo_root: Repository root for loading prompt templates.
        default_task: Fallback task when classification fails.
        query_rewrite: Whether rewrite is enabled (output still parsed when False).
        task_classification: Whether to parse the ``TASK:`` line.
        caller_task: Explicit task from caller; prepare is skipped upstream when set.
        cancel_event: Optional cancellation signal.
        max_history_turns: Maximum history turns in the prompt.

    Returns:
        Prepared retrieval query and optional task label.
    """
    if cancel_event and cancel_event.is_set():
        return PreparedQuery(retrieval_query=question, task=None)

    classify = task_classification and caller_task is None
    history_turns = history or []
    history_text = (
        format_history(history_turns, max_turns=max_history_turns)
        if history_turns
        else "(none)"
    )

    template = _load_prepare_template(repo_root)
    prompt = _render_prepare_prompt(
        template,
        history=history_text,
        question=question,
    )

    logger.info(
        "Preparing query (rewrite=%s, classify=%s, history_turns=%d): %s",
        query_rewrite,
        classify,
        len(history_turns),
        question[:80],
    )

    try:
        raw_output = _generate_prepare_text(llm, prompt, cancel_event=cancel_event)
    except Exception:
        logger.warning("Query prepare failed, using original question", exc_info=True)
        return PreparedQuery(
            retrieval_query=question,
            task=default_task if classify else None,
        )

    if cancel_event and cancel_event.is_set():
        return PreparedQuery(retrieval_query=question, task=None)

    if not raw_output:
        logger.warning("Query prepare returned empty, using original question")
        return PreparedQuery(
            retrieval_query=question,
            task=default_task if classify else None,
        )

    prepared = _parse_prepare_output(
        raw_output,
        question=question,
        default_task=default_task,
        classify=classify,
    )

    if not query_rewrite:
        prepared = PreparedQuery(
            retrieval_query=question,
            task=prepared.task,
        )

    if prepared.task is not None:
        logger.info(
            "Query prepared: %r -> %r (task=%s)",
            question[:60],
            prepared.retrieval_query[:80],
            prepared.task,
        )
    else:
        logger.info(
            "Query prepared: %r -> %r",
            question[:60],
            prepared.retrieval_query[:80],
        )

    return prepared
