"""Load prompt templates from the prompts/ directory."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TEMPLATE_NAME = "default"


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


def render_template(template: str, *, context: str, question: str) -> str:
    """Substitute ``{{context}}`` and ``{{question}}`` placeholders.

    Args:
        template: Raw template text.
        context: Retrieved context blocks.
        question: User question.

    Returns:
        Rendered prompt ready for the LLM.
    """
    return (
        template.replace("{{context}}", context).replace("{{question}}", question).strip()
    )
