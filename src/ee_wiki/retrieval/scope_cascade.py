"""Hardcoded scope-tier cascade retrieval helpers.

Tier priority (lower number = higher priority):
  build (0) > project_common (1) > global (2)

No project or build names appear here — tiers are derived from metadata pairs
and :class:`DataLayoutConfig` reserved segments only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ee_wiki.retrieval.hybrid.engine import HybridChunk

from ee_wiki.common.types import DataLayoutConfig

SCOPE_TIER_BUILD = 0
SCOPE_TIER_PROJECT_COMMON = 1
SCOPE_TIER_GLOBAL = 2

DEFAULT_QUOTA_BUILD = 6
DEFAULT_QUOTA_COMMON = 2
DEFAULT_QUOTA_GLOBAL = 2


@dataclass(frozen=True)
class CascadePhase:
    """One cascade search phase covering scope pairs at the same tier."""

    tier: int
    scope_pairs: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class ScopeQuotas:
    """Per-tier slot caps for mixed context assembly."""

    build: int = DEFAULT_QUOTA_BUILD
    common: int = DEFAULT_QUOTA_COMMON
    global_: int = DEFAULT_QUOTA_GLOBAL

    def for_tier(self, tier: int) -> int:
        """Return the configured slot cap for ``tier``."""
        if tier == SCOPE_TIER_BUILD:
            return self.build
        if tier == SCOPE_TIER_PROJECT_COMMON:
            return self.common
        return self.global_


def scope_tier(project: str, build: str, layout: DataLayoutConfig) -> int:
    """Classify a ``(project, build)`` metadata pair into a cascade tier.

    Args:
        project: Metadata project segment.
        build: Metadata build segment.
        layout: Path naming configuration.

    Returns:
        ``SCOPE_TIER_BUILD``, ``SCOPE_TIER_PROJECT_COMMON``, or ``SCOPE_TIER_GLOBAL``.
    """
    enterprise = layout.enterprise_project
    common = layout.project_shared_build
    if project == enterprise and build == enterprise:
        return SCOPE_TIER_GLOBAL
    if build == common:
        return SCOPE_TIER_PROJECT_COMMON
    return SCOPE_TIER_BUILD


def build_cascade_phases_from_ranks(
    scope_ranks: dict[tuple[str, str], int],
    layout: DataLayoutConfig,
) -> list[CascadePhase]:
    """Group scope rank pairs into ordered cascade phases by tier.

    Args:
        scope_ranks: ``(project, build)`` pairs allowed for this query.
        layout: Path naming configuration.

    Returns:
        Phases sorted by tier (build first, then common, then global).
    """
    by_tier: dict[int, set[tuple[str, str]]] = {}
    for pair in scope_ranks:
        tier = scope_tier(pair[0], pair[1], layout)
        by_tier.setdefault(tier, set()).add(pair)
    return [
        CascadePhase(tier=tier, scope_pairs=frozenset(by_tier[tier]))
        for tier in sorted(by_tier)
    ]


def should_run_scope_cascade(
    *,
    scope_inheritance: bool,
    scope_cascade: bool,
    target_project: str | None,
    scope_ranks: dict[tuple[str, str], int] | None,
) -> bool:
    """Return whether tier cascade retrieval should run for this query."""
    if not scope_inheritance or not scope_cascade:
        return False
    if scope_ranks:
        return True
    return target_project is not None


def effective_primary_quota(
    tier: int,
    *,
    primary_tier: int,
    final_k: int,
    quotas: ScopeQuotas,
) -> int:
    """Max slots the primary tier may occupy when assembling mixed context.

    Lower-priority tiers keep reserved supplement caps; the primary tier fills
    the remainder up to its configured quota.
    """
    base = quotas.for_tier(tier)
    if tier != primary_tier:
        return base
    lower_reserve = sum(
        quotas.for_tier(other)
        for other in (SCOPE_TIER_BUILD, SCOPE_TIER_PROJECT_COMMON, SCOPE_TIER_GLOBAL)
        if other > tier
    )
    return min(final_k, max(base, final_k - lower_reserve))


def assemble_mixed_quota(
    reranked_by_tier: dict[int, list[tuple[float, Any]]],
    *,
    primary_tier: int,
    final_k: int,
    quotas: ScopeQuotas,
) -> list[Any]:
    """Assemble final chunks: primary tier first, then lower tiers as supplement.

    Args:
        reranked_by_tier: Per-tier candidate lists sorted by rerank score descending.
        primary_tier: Highest tier that met the sufficiency threshold (or deepest fallback).
        final_k: Maximum chunks to return.
        quotas: Per-tier slot caps.

    Returns:
        Ordered chunk list respecting tier quotas.
    """
    selected: list[Any] = []
    seen: set[str] = set()
    tier_used: dict[int, int] = {
        SCOPE_TIER_BUILD: 0,
        SCOPE_TIER_PROJECT_COMMON: 0,
        SCOPE_TIER_GLOBAL: 0,
    }

    def _add_from_tier(tier: int, max_for_tier: int) -> None:
        for score, chunk in reranked_by_tier.get(tier, []):
            if len(selected) >= final_k:
                return
            if tier_used[tier] >= max_for_tier:
                return
            chunk_id = getattr(chunk, "chunk_id", None)
            if chunk_id is None:
                continue
            if chunk_id in seen:
                continue
            selected.append(chunk)
            seen.add(chunk_id)
            tier_used[tier] += 1

    primary_cap = effective_primary_quota(
        primary_tier,
        primary_tier=primary_tier,
        final_k=final_k,
        quotas=quotas,
    )
    _add_from_tier(primary_tier, primary_cap)

    for tier in sorted(reranked_by_tier):
        if tier <= primary_tier:
            continue
        remaining = final_k - len(selected)
        if remaining <= 0:
            break
        supplement_cap = min(quotas.for_tier(tier), remaining)
        _add_from_tier(tier, supplement_cap)

    return selected


def merge_tier_results(
    existing: dict[int, list[tuple[float, HybridChunk]]],
    tier: int,
    new_results: list[tuple[float, HybridChunk]],
) -> dict[int, list[tuple[float, HybridChunk]]]:
    """Merge phase results into ``existing``, deduplicating by chunk id."""
    merged = dict(existing)
    seen = {chunk.chunk_id for pairs in merged.values() for _, chunk in pairs}
    combined = list(merged.get(tier, []))
    for score, chunk in new_results:
        if chunk.chunk_id in seen:
            continue
        combined.append((score, chunk))
        seen.add(chunk.chunk_id)
    combined.sort(key=lambda item: item[0], reverse=True)
    merged[tier] = combined
    return merged
