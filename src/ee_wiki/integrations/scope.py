"""Map Radar component fields to EE-Wiki product/project/build scope."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ee_wiki.common.project_aliases import (
    match_scope_in_text,
    resolve_alias_target,
)
from ee_wiki.protocols.radar import RadarComponentRef, RadarProblem, RadarScopeHint

_BUILD_TOKEN = re.compile(
    r"\b(?P<build>p\d+|evt\d*|dvt\d*|pvt\d*|mp)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ScopeResolution:
    """Result of mapping Radar metadata to EE-Wiki scope."""

    product: str | None
    project: str | None
    build: str | None
    source: str
    confidence: str  # high | medium | low | none
    notes: str = ""


def normalize_build(version: str) -> str:
    """Normalize a Radar component version / build token to lowercase.

    Args:
        version: Raw version string (e.g. ``P1``, ``p1 ``).

    Returns:
        Stripped lowercase build id.
    """
    return version.strip().lower()


def resolve_scope_from_component(
    component: RadarComponentRef | None,
    *,
    project_aliases: dict[str, str] | None = None,
    hint: RadarScopeHint | None = None,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
) -> ScopeResolution:
    """Resolve EE-Wiki ``product`` / ``project`` / ``build`` from Radar metadata.

    Priority: user override → project alias / name match in component →
    foundInBuild / configurationSummary heuristics → unknown.

    Args:
        component: Radar component (``name | version``).
        project_aliases: 甲方/乙方等别名 → EE-Wiki path slug or
            ``product/project`` qualified target
            (``data_layout.project_aliases``).
        hint: Optional found-in-build / configuration summary.
        user_product: Explicit session override.
        user_project: Explicit session override.
        user_build: Explicit session override.

    Returns:
        Scope resolution with provenance ``source`` and ``confidence``.
    """
    aliases = project_aliases or {}
    if user_product or user_project or user_build:
        product_hint, project_slug = resolve_alias_target(user_project, aliases)
        if user_product:
            user_prod_hint, user_prod_slug = resolve_alias_target(user_product, aliases)
            product = user_prod_hint if user_prod_hint is not None else user_prod_slug
        else:
            product = product_hint
        return ScopeResolution(
            product=product,
            project=project_slug if user_project else None,
            build=normalize_build(user_build) if user_build else None,
            source="user_override",
            confidence="high",
            notes="Explicit session/API override",
        )

    if component is not None:
        build = normalize_build(component.version) if component.version else None
        product, project = match_scope_in_text(component.name, aliases)
        if project is None:
            # Whole component.name might itself be a slug/alias (no spaces).
            compact = component.name.strip()
            if compact and " " not in compact:
                product, project = resolve_alias_target(compact, aliases)

        if project and build:
            return ScopeResolution(
                product=product,
                project=project,
                build=build,
                source="component_alias",
                confidence="high",
                notes=f"component {component.name!r} | {component.version!r}",
            )
        if project:
            return ScopeResolution(
                product=product,
                project=project,
                build=build,
                source="component_alias",
                confidence="medium",
                notes="Resolved project; build missing or empty",
            )
        if build:
            return ScopeResolution(
                product=None,
                project=None,
                build=build,
                source="component_version",
                confidence="low",
                notes=(
                    f"No project alias matched in {component.name!r}; "
                    "configure data_layout.project_aliases or state product/project"
                ),
            )

    if hint:
        if hint.configuration_summary:
            product, project = match_scope_in_text(
                hint.configuration_summary, aliases
            )
            build_match = _BUILD_TOKEN.search(hint.configuration_summary)
            build = (
                normalize_build(build_match.group("build")) if build_match else None
            )
            if project or build:
                return ScopeResolution(
                    product=product,
                    project=project,
                    build=build,
                    source="configuration_summary",
                    confidence="medium" if project and build else "low",
                    notes="Heuristics from configurationSummary",
                )
        for token in hint.found_in_builds:
            norm = normalize_build(token)
            if norm:
                return ScopeResolution(
                    product=None,
                    project=None,
                    build=norm,
                    source="found_in_build",
                    confidence="low",
                    notes="Build only from foundInBuild; product/project still needed",
                )

    return ScopeResolution(
        product=None,
        project=None,
        build=None,
        source="unknown",
        confidence="none",
        notes="Ask user for product/project/build",
    )


def resolve_scope_from_problem(
    problem: RadarProblem,
    *,
    project_aliases: dict[str, str] | None = None,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
) -> ScopeResolution:
    """Resolve scope from a full :class:`RadarProblem` snapshot.

    Priority: user override → component alias → **title / configuration
    summary** alias match → foundInBuild heuristics → unknown.

    Args:
        problem: Normalized Radar problem.
        project_aliases: Alias → canonical project (or product/project) map.
        user_product: Explicit override.
        user_project: Explicit override.
        user_build: Explicit override.

    Returns:
        Scope resolution.
    """
    hint = RadarScopeHint(
        found_in_builds=problem.found_in_builds,
        configuration_summary=problem.configuration_summary,
    )
    resolved = resolve_scope_from_component(
        problem.component,
        project_aliases=project_aliases,
        hint=hint,
        user_product=user_product,
        user_project=user_project,
        user_build=user_build,
    )
    if resolved.project is not None:
        return resolved

    # Component name often has no EE-Wiki slug (e.g. "B5xx HW Build FATP").
    # Titles like "Ruby,P0,Scarif …" still carry program tokens — scan them.
    aliases = project_aliases or {}
    title = (problem.title or "").strip()
    if title:
        product, project = match_scope_in_text(title, aliases)
        build = resolved.build
        if build is None:
            build_match = _BUILD_TOKEN.search(title)
            if build_match:
                build = normalize_build(build_match.group("build"))
        if project is not None:
            return ScopeResolution(
                product=product,
                project=project,
                build=build,
                source="title_alias",
                confidence="high" if product and project and build else "medium",
                notes=f"Matched project alias in title {title!r}",
            )
    return resolved


# Re-export helpers used by tests and callers.
__all__ = [
    "ScopeResolution",
    "normalize_build",
    "resolve_scope_from_component",
    "resolve_scope_from_problem",
]
