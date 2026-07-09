"""Translation task handling (intent from semantic classification)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.context import resolve_history_for_prompt
from ee_wiki.generation.templates.loader import load_template, render_template
from ee_wiki.retrieval.rewrite import ConversationTurn

logger = get_logger(__name__)

TRANSLATE_TASK = "translate"


def is_translation_task(task: str | None) -> bool:
    """Return whether the resolved or prepared task is translation.

    Args:
        task: Task label from prepare/classify or the API caller.

    Returns:
        True when ``task`` is ``translate``.
    """
    return task == TRANSLATE_TASK


def build_translation_prompt(
    repo_root: Path,
    *,
    question: str,
    history: list[ConversationTurn] | None = None,
    template_name: str = "default",
) -> str:
    """Render the translation prompt without retrieval context.

    Args:
        repo_root: Repository root for loading ``prompts/translate/``.
        question: Current user question.
        history: Prior conversation turns, if any.
        template_name: Template stem under ``prompts/translate/``.

    Returns:
        Rendered prompt for the LLM.
    """
    template = load_template(repo_root, TRANSLATE_TASK, template_name)
    return render_template(
        template,
        context="",
        question=question,
        scope_rules="",
        history=resolve_history_for_prompt(question, history, task=TRANSLATE_TASK),
    )


def log_translation_task(question: str) -> None:
    """Log that translation mode was selected by task classification."""
    logger.info("Translation task selected for question: %s", question[:80])
