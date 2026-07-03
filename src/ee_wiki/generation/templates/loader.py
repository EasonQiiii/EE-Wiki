"""Load prompt templates from the prompts/ directory."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TEMPLATE_NAME = "default"


SCOPE_RULES_TASK = "_shared"
SCOPE_RULES_NAME = "scope_rules"


class TemplateLoadError(EEWikiError):
    """Failed to load or render a prompt template."""


def resolve_prompts_dir(repo_root: Path) -> Path:
    """Return the repository ``prompts/`` directory.

    Args:
        repo_root: Repository root path.

    Returns:
        Absolute path to ``prompts/``.
    """
    return (repo_root / "prompts").resolve()


def load_template(repo_root: Path, task: str, name: str = DEFAULT_TEMPLATE_NAME) -> str:
    """Load a Markdown prompt template from ``prompts/{task}/{name}.md``.

    Args:
        repo_root: Repository root path.
        task: Task subdirectory (e.g. ``wiki``).
        name: Template file stem without extension.

    Returns:
        Raw template text.

    Raises:
        TemplateLoadError: If the template file is missing.
    """
    path = resolve_prompts_dir(repo_root) / task / f"{name}.md"
    if not path.is_file():
        raise TemplateLoadError(f"Prompt template not found: {path}")
    logger.debug("Loaded prompt template from %s", path)
    return path.read_text(encoding="utf-8")


def load_scope_rules(repo_root: Path) -> str:
    """Load shared knowledge-scope instructions from ``prompts/_shared/scope_rules.md``.

    Args:
        repo_root: Repository root path.

    Returns:
        Raw scope-rules markdown for ``{{scope_rules}}`` substitution.

    Raises:
        TemplateLoadError: If the scope rules file is missing.
    """
    return load_template(repo_root, SCOPE_RULES_TASK, SCOPE_RULES_NAME)


def render_template(
    template: str,
    *,
    context: str,
    question: str,
    scope_rules: str = "",
) -> str:
    """Substitute ``{{context}}``, ``{{question}}``, and ``{{scope_rules}}`` placeholders.

    Args:
        template: Raw template text.
        context: Retrieved context blocks.
        question: User question.
        scope_rules: Shared knowledge-scope instructions (optional).

    Returns:
        Rendered prompt ready for the LLM.
    """
    return (
        template.replace("{{scope_rules}}", scope_rules)
        .replace("{{context}}", context)
        .replace("{{question}}", question)
        .strip()
    )


def render_assistant_template(template: str, *, role: str, question: str) -> str:
    """Substitute ``{{role}}`` and ``{{question}}`` for assistant-meta prompts.

    Args:
        template: Raw assistant prompt template.
        role: Static role description text.
        question: User question.

    Returns:
        Rendered prompt ready for the LLM.
    """
    return template.replace("{{role}}", role).replace("{{question}}", question).strip()
