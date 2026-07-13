"""Index inventory: project/build stats and inventory-question detection."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from ee_wiki.common.types import DataLayoutConfig

InventoryKind = Literal["projects", "builds"]

_PROJECT_COUNT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(有多少|多少个|有几个|几个).{0,12}(project|项目)", re.IGNORECASE),
    re.compile(r"(有哪些|哪些).{0,12}(project|项目)", re.IGNORECASE),
    re.compile(r"(list|how many|what|which).{0,24}projects?\b", re.IGNORECASE),
    re.compile(r"知识库.{0,24}(有哪些|有多少|多少个|有几个|几个).{0,12}(project|项目)", re.IGNORECASE),
    re.compile(r"(当前|本).{0,8}知识库.{0,24}(project|项目)", re.IGNORECASE),
    re.compile(r"(indexed|index).{0,24}projects?\b", re.IGNORECASE),
)

_BUILD_COUNT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(有多少|多少个|有几个|几个|有哪些|哪些).{0,12}(build|版本|revision)",
        re.IGNORECASE,
    ),
    re.compile(r"(list|how many|what|which).{0,24}builds?\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class InventoryRequest:
    """Parsed inventory intent for deterministic answering."""

    kind: InventoryKind
    project: str | None = None


@dataclass(frozen=True)
class ProjectInventoryEntry:
    """One indexed project path with build breakdown."""

    project: str
    builds: tuple[str, ...]
    chunk_count: int
    is_enterprise: bool


@dataclass(frozen=True)
class IndexInventory:
    """Aggregated project/build inventory from the loaded index."""

    chunk_count: int
    projects: tuple[ProjectInventoryEntry, ...]
    product_count: int
    enterprise_project: str
    project_shared_build: str


def detect_inventory_kind(question: str) -> InventoryKind | None:
    """Return inventory kind when the question asks for project/build counts."""
    text = question.strip()
    if not text:
        return None
    if any(pattern.search(text) for pattern in _PROJECT_COUNT_PATTERNS):
        return "projects"
    if any(pattern.search(text) for pattern in _BUILD_COUNT_PATTERNS):
        return "builds"
    return None


def resolve_mentioned_project(
    question: str,
    known_projects: Iterable[str],
) -> str | None:
    """Return an indexed project name mentioned in ``question``, if any.

    Matching uses indexed names only (not hardcoded product lists). Longer names
    win when multiple match.
    """
    text = question.strip()
    if not text:
        return None
    ordered = sorted({name for name in known_projects if name}, key=len, reverse=True)
    for project in ordered:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_-]){re.escape(project)}(?![A-Za-z0-9_-])",
            re.IGNORECASE,
        )
        if pattern.search(text):
            return project.casefold()
    return None


def parse_inventory_request(
    question: str,
    *,
    known_projects: Iterable[str] | None = None,
) -> InventoryRequest | None:
    """Parse whether ``question`` asks for indexed project/build inventory.

    Args:
        question: Raw user question.
        known_projects: Optional indexed project names used to scope build questions
            (e.g. ``logan中有几个build`` → project ``logan``).

    Returns:
        Structured inventory intent, or ``None`` when this is not an inventory question.
    """
    kind = detect_inventory_kind(question)
    if kind is None:
        return None
    project = None
    if known_projects is not None:
        project = resolve_mentioned_project(question, known_projects)
    return InventoryRequest(kind=kind, project=project)


def is_inventory_question(question: str) -> bool:
    """Return whether ``question`` asks for indexed project/build inventory."""
    return detect_inventory_kind(question) is not None


def build_index_inventory(
    chunks: Iterable[Any],
    layout: DataLayoutConfig,
) -> IndexInventory:
    """Aggregate ``(project, build)`` counts from indexed chunks.

    Args:
        chunks: Hybrid chunks or metadata dicts.
        layout: Data layout configuration for enterprise/common labels.

    Returns:
        Inventory with per-project builds and chunk counts.
    """
    enterprise = layout.enterprise_project
    common = layout.project_shared_build
    pair_counts: Counter[tuple[str, str]] = Counter()
    project_counts: Counter[str] = Counter()

    for chunk in chunks:
        if isinstance(chunk, dict):
            metadata = chunk
        else:
            metadata = getattr(chunk, "metadata", None) or {}
        project = str(metadata.get("project", "") or "").strip()
        build = str(metadata.get("build", "") or "").strip()
        if not project or not build:
            continue
        pair_counts[(project, build)] += 1
        project_counts[project] += 1

    projects: list[ProjectInventoryEntry] = []
    for project, chunk_count in sorted(project_counts.items()):
        builds = tuple(
            sorted(build for (proj, build) in pair_counts if proj == project)
        )
        projects.append(
            ProjectInventoryEntry(
                project=project,
                builds=builds,
                chunk_count=chunk_count,
                is_enterprise=(project == enterprise),
            )
        )

    product_count = sum(1 for entry in projects if not entry.is_enterprise)
    return IndexInventory(
        chunk_count=sum(project_counts.values()),
        projects=tuple(projects),
        product_count=product_count,
        enterprise_project=enterprise,
        project_shared_build=common,
    )


def _find_project(
    inventory: IndexInventory,
    project: str,
) -> ProjectInventoryEntry | None:
    needle = project.casefold()
    for entry in inventory.projects:
        if entry.project.casefold() == needle:
            return entry
    return None


def format_project_builds_answer(
    inventory: IndexInventory,
    project: str,
) -> str:
    """Render builds for one project from the index.

    Args:
        inventory: Aggregated index inventory.
        project: Requested project name.

    Returns:
        Deterministic Chinese answer focused on that project's builds.
    """
    entry = _find_project(inventory, project)
    if entry is None:
        known = "、".join(f"**{item.project}**" for item in inventory.projects) or "(无)"
        return (
            f"索引中未找到 project **{project}**。\n\n"
            f"当前已索引的 project：{known}。"
        )

    common = inventory.project_shared_build
    hardware = [build for build in entry.builds if build != common]
    has_common = common in entry.builds

    lines: list[str] = [
        f"**{entry.project}** 在当前索引中共有 **{len(entry.builds)}** 个 build 路径"
        f"（{entry.chunk_count} chunks）：",
        "",
    ]
    if hardware:
        lines.append(
            f"- 硬件版本（build）：`{'`, `'.join(hardware)}` — 共 **{len(hardware)}** 个"
        )
    else:
        lines.append("- 硬件版本（build）：无")
    if has_common:
        lines.append(
            f"- 项目共享层：`{common}`（不是硬件版本号）"
        )
    lines.append("")
    lines.append(
        "说明：以上统计来自**已索引**文档；`data/raw/` 中尚未 ingest/index 的目录不会出现。"
    )
    return "\n".join(lines)


def format_builds_overview_answer(inventory: IndexInventory) -> str:
    """Render a builds-focused overview across all indexed projects."""
    if not inventory.projects:
        return "当前索引为空，尚未收录任何 project/build。"

    lines: list[str] = [
        "当前索引中各 project 的 build 路径：",
        "",
    ]
    for entry in inventory.projects:
        builds = ", ".join(f"`{build}`" for build in entry.builds) or "(none)"
        lines.append(
            f"- **{entry.project}**：{builds}（{entry.chunk_count} chunks）"
        )
    lines.append("")
    lines.append(
        f"`{inventory.project_shared_build}` 是项目共享层，不是硬件版本；"
        f"`{inventory.enterprise_project}` 是企业通用层。"
    )
    return "\n".join(lines)


def format_inventory_answer(
    inventory: IndexInventory,
    request: InventoryRequest | None = None,
) -> str:
    """Render a grounded Chinese answer for inventory questions.

    Args:
        inventory: Aggregated index inventory.
        request: Optional parsed intent; defaults to full project listing.

    Returns:
        Deterministic answer text (no LLM).
    """
    intent = request or InventoryRequest(kind="projects")
    if intent.kind == "builds":
        if intent.project:
            return format_project_builds_answer(inventory, intent.project)
        return format_builds_overview_answer(inventory)

    if not inventory.projects:
        return "当前索引为空，尚未收录任何 project。"

    lines: list[str] = [
        f"当前索引共有 **{len(inventory.projects)}** 个 project 路径"
        f"（合计 **{inventory.chunk_count}** 个 chunk）。",
        "",
    ]
    for index, entry in enumerate(inventory.projects, start=1):
        builds = ", ".join(entry.builds) if entry.builds else "(none)"
        if entry.is_enterprise:
            kind = "企业共享层（非产品 project）"
        else:
            kind = "产品 project"
        lines.append(
            f"{index}. **{entry.project}**（{kind}）："
            f"{entry.chunk_count} chunks — builds: `{builds}`"
        )

    product_names = [e.project for e in inventory.projects if not e.is_enterprise]
    lines.append("")
    if product_names:
        lines.append(
            f"产品级 project 共 **{inventory.product_count}** 个："
            + "、".join(f"**{name}**" for name in product_names)
            + f"。`{inventory.enterprise_project}` 是企业通用知识层，"
            f"不是某个硬件产品；`{inventory.project_shared_build}` 是项目共享 build，"
            "不是硬件版本号。"
        )
    else:
        lines.append(
            f"目前只有企业共享层 `{inventory.enterprise_project}`，尚无产品级 project。"
        )
    return "\n".join(lines)


def inventory_to_dict(inventory: IndexInventory) -> dict[str, Any]:
    """Serialize inventory for HTTP/MCP JSON responses."""
    return {
        "chunk_count": inventory.chunk_count,
        "product_count": inventory.product_count,
        "enterprise_project": inventory.enterprise_project,
        "project_shared_build": inventory.project_shared_build,
        "projects": [
            {
                "project": entry.project,
                "builds": list(entry.builds),
                "chunk_count": entry.chunk_count,
                "is_enterprise": entry.is_enterprise,
            }
            for entry in inventory.projects
        ],
    }
