"""LLM-based intent classification to select the prompt task automatically.

When the caller does not specify an explicit ``task``, the local LLM
classifies the user question into one of the known task categories
(wiki, debug, fa, design_review) so the correct prompt template is loaded.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.protocols.llm import LlmBackend

logger = get_logger(__name__)

VALID_TASKS: frozenset[str] = frozenset({
    "wiki",
    "debug",
    "fa",
    "design_review",
})

MAX_CLASSIFY_TOKENS = 16


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
        if callable(getattr(llm, "generate_stream", None)):
            parts: list[str] = []
            for fragment in llm.generate_stream(
                prompt,
                max_new_tokens=MAX_CLASSIFY_TOKENS,
                cancel_event=cancel_event,
            ):
                if cancel_event and cancel_event.is_set():
                    return default_task
                parts.append(fragment)
            raw_output = "".join(parts).strip()
        else:
            raw_output = llm.generate(
                prompt, max_new_tokens=MAX_CLASSIFY_TOKENS,
            ).strip()
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
