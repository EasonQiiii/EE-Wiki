"""Merge per-page schematic extraction results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageExtraction:
    """Structured output from one schematic PDF page."""

    page: int
    markdown: str
    major_components: list[str] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def merge_page_extractions(
    pages: list[PageExtraction],
    *,
    title: str,
) -> tuple[str, list[str], list[str], list[str]]:
    """Combine page-level extractions into one Markdown document and metadata lists.

    Args:
        pages: Ordered page extraction results.
        title: Document title for the top-level heading.

    Returns:
        Tuple of ``(markdown, major_components, nets, interfaces)``.
    """
    if not pages:
        return f"# 电子图纸分析报告：{title}\n\n", [], [], []

    sections: list[str] = [f"# 电子图纸分析报告：{title}\n"]
    all_components: list[str] = []
    all_nets: list[str] = []
    all_interfaces: list[str] = []

    for index, page in enumerate(sorted(pages, key=lambda item: item.page)):
        if index > 0:
            sections.append("\n---\n")
        sections.append(page.markdown.strip())
        sections.append("")
        all_components.extend(page.major_components)
        all_nets.extend(page.nets)
        all_interfaces.extend(page.interfaces)

    markdown = "\n".join(sections).rstrip() + "\n"
    return (
        markdown,
        _dedupe_preserve_order(all_components),
        _dedupe_preserve_order(all_nets),
        _dedupe_preserve_order(all_interfaces),
    )
