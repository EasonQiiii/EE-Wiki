"""Supervisor clarify heuristics (Supervisor-first routing; ADR 0012 amend)."""

from __future__ import annotations

import re

from ee_wiki.connectivity.intent import detect_trace_intent

_VAGUE = re.compile(
    r"^(?:帮我)?(?:看看|看一下|分析)?(?:这个|一下)?$|"
    r"^(?:help|hi|hello|你好)[!.?]*$",
    re.IGNORECASE,
)


def needs_scope_clarify(
    question: str,
    *,
    product: str | None,
    project: str | None,
    build: str | None,
) -> str | None:
    """Return clarify markdown when trace intent lacks product/project scope.

    Args:
        question: Latest user utterance.
        product: Turn scope product.
        project: Turn scope project.
        build: Turn scope build.

    Returns:
        Clarify prompt, or ``None`` when scope is sufficient or not required.
    """
    intent = detect_trace_intent(question)
    if intent is None:
        return None
    if product and project:
        return None
    return (
        "要追踪 **net / 引脚连接**，需要明确的 **product** 和 **project** "
        "（可选 **build**）范围，才能从 netlist / BoardView 侧车查询。\n\n"
        "请在问题中写明，或在 API / Open WebUI 里设置 scope 后重试。"
    )


def needs_vague_clarify(question: str) -> str | None:
    """Return clarify markdown for underspecified user messages.

    Args:
        question: Latest user utterance.

    Returns:
        Clarify prompt, or ``None``.
    """
    stripped = question.strip()
    if not stripped:
        return "请描述你的工程问题（例如：电源轨、位号、Radar 号、失效现象）。"
    if len(stripped) <= 6 and _VAGUE.match(stripped):
        return (
            "请具体说明需要什么帮助，例如：\n"
            "- Radar 开案：`radar://12345678`\n"
            "- 追网：`J1 第3脚连到哪`（需 scope）\n"
            "- 知识检索：`STM32 供电要求`"
        )
    if _VAGUE.match(stripped):
        return (
            "问题还比较笼统。请补充 **产品/项目/build**、**位号或网络名**，"
            "或 **Radar 号**，方便路由到对应 specialist。"
        )
    return None
