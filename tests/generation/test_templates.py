"""Tests for prompt template loading."""

from __future__ import annotations

import pytest

from ee_wiki.generation.templates.loader import (
    TemplateLoadError,
    load_graph_rules,
    load_scope_rules,
    load_template,
    render_template,
)


def test_load_template_reads_default_wiki_prompt(repo_root) -> None:
    template = load_template(repo_root, "wiki", "default")
    assert "{{context}}" in template
    assert "{{question}}" in template
    assert "{{scope_rules}}" in template
    assert "{{history}}" in template


def test_load_scope_rules_reads_shared_prompt(repo_root) -> None:
    rules = load_scope_rules(repo_root)
    assert "project_common" in rules
    assert "global" in rules


def test_load_graph_rules_reads_shared_prompt(repo_root) -> None:
    rules = load_graph_rules(repo_root)
    assert "heuristic" in rules.lower() or "graph" in rules.lower()
    assert "netlist" in rules.lower()


@pytest.mark.parametrize(
    "task,marker",
    [
        ("debug", "hardware debug assistant"),
        ("fa", "failure analysis"),
        ("design_review", "design review assistant"),
        ("power", "power-tree assistant"),
        ("rules", "engineering-rules assistant"),
    ],
)
def test_load_template_reads_task_prompts(repo_root, task: str, marker: str) -> None:
    template = load_template(repo_root, task, "default")
    assert marker in template.lower()
    assert "{{context}}" in template
    if task in {"debug", "fa", "design_review", "power", "rules"}:
        assert "{{graph_rules}}" in template


def test_render_template_substitutes_placeholders() -> None:
    rendered = render_template(
        "Rules:\n{{scope_rules}}\n\nGraph:\n{{graph_rules}}\n\n"
        "Context:\n{{context}}\n\nQ: {{question}}",
        context="[1] example",
        question="What is VBAT?",
        scope_rules="Scope tier rules.",
        graph_rules="Graph evidence rules.",
    )
    assert "Scope tier rules." in rendered
    assert "Graph evidence rules." in rendered
    assert "[1] example" in rendered
    assert "What is VBAT?" in rendered
    assert "{{" not in rendered


def test_render_template_substitutes_history() -> None:
    rendered = render_template(
        "History:\n{{history}}\n\nContext:\n{{context}}\n\nQ: {{question}}",
        context="[1] example",
        question="用英文",
        history="[User]:\nipad快速放电指令\n\n[Assistant]:\n方案 A",
    )
    assert "[User]:\nipad快速放电指令" in rendered
    assert "方案 A" in rendered
    assert "{{" not in rendered


def test_load_template_raises_for_missing_file(repo_root) -> None:
    with pytest.raises(TemplateLoadError, match="not found"):
        load_template(repo_root, "wiki", "missing-template")
