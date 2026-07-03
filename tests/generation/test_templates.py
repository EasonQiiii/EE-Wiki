"""Tests for prompt template loading."""

from __future__ import annotations

import pytest

from ee_wiki.generation.templates.loader import (
    TemplateLoadError,
    load_scope_rules,
    load_template,
    render_template,
)


def test_load_template_reads_default_wiki_prompt(repo_root) -> None:
    template = load_template(repo_root, "wiki", "default")
    assert "{{context}}" in template
    assert "{{question}}" in template
    assert "{{scope_rules}}" in template


def test_load_scope_rules_reads_shared_prompt(repo_root) -> None:
    rules = load_scope_rules(repo_root)
    assert "project_common" in rules
    assert "global" in rules


@pytest.mark.parametrize(
    "task,marker",
    [
        ("debug", "hardware debug assistant"),
        ("fa", "failure analysis"),
        ("design_review", "design review assistant"),
    ],
)
def test_load_template_reads_task_prompts(repo_root, task: str, marker: str) -> None:
    template = load_template(repo_root, task, "default")
    assert marker in template.lower()
    assert "{{context}}" in template


def test_render_template_substitutes_placeholders() -> None:
    rendered = render_template(
        "Rules:\n{{scope_rules}}\n\nContext:\n{{context}}\n\nQ: {{question}}",
        context="[1] example",
        question="What is VBAT?",
        scope_rules="Scope tier rules.",
    )
    assert "Scope tier rules." in rendered
    assert "[1] example" in rendered
    assert "What is VBAT?" in rendered
    assert "{{" not in rendered


def test_load_template_raises_for_missing_file(repo_root) -> None:
    with pytest.raises(TemplateLoadError, match="not found"):
        load_template(repo_root, "wiki", "missing-template")
