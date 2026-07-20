"""Fuse specialist findings into a supervisor reply (ADR 0008)."""

from __future__ import annotations

from ee_wiki.protocols.agent import Finding, SupervisorResult

INSUFFICIENT_FUSED = (
    "**知识不足 / insufficient knowledge**\n\n"
    "已调度的专家角色在当前 `product` / `project` / `build` 范围内均未收集到可用证据。"
    "不会用推测补全结论。请补充范围、提供 CAD netlist / BoardView，或换一种问法。"
)


def fuse_findings(
    question: str,
    findings: list[Finding],
    *,
    product: str | None,
    project: str | None,
    build: str | None,
) -> SupervisorResult:
    """Merge specialist findings or return insufficient.

    Args:
        question: Original user question.
        findings: Collected findings (may be empty).
        product: Scope product.
        project: Scope project.
        build: Scope build.

    Returns:
        Fused markdown result or explicit insufficient.
    """
    useful = [f for f in findings if not f.insufficient]
    roles = tuple(f.role_id for f in findings)
    if not useful:
        return SupervisorResult(
            kind="insufficient",
            markdown=INSUFFICIENT_FUSED,
            findings=tuple(findings),
            roles_used=roles,
            insufficient=True,
        )

    scope_line = (
        f"scope: product={product or '*'} "
        f"project={project or '*'} build={build or '*'}"
    )
    parts = [
        f"## Agent evidence for: {question}",
        f"_{scope_line}; roles: {', '.join(f.role_id for f in useful)}_",
        "",
        "Use only the evidence below. Prefer build-specific facts over common/global. "
        "Connectivity traces are reliable only when evidence tags are "
        "`cad_netlist` / `boardview`. Do not invent nets, pins, or root causes.",
        "",
    ]
    for finding in useful:
        parts.append(finding.markdown)
        parts.append("")
    return SupervisorResult(
        kind="fused",
        markdown="\n".join(parts).strip(),
        findings=tuple(findings),
        roles_used=tuple(f.role_id for f in useful),
        insufficient=False,
    )
