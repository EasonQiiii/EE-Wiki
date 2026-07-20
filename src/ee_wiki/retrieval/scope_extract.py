"""Rule-based product / project / build / layer extraction from natural language."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ee_wiki.retrieval.scope_catalog import ScopeCatalog

KnowledgeLayer = Literal[
    "build",
    "project_common",
    "product_common",
    "enterprise",
    "inherit",
]

_ENTERPRISE_PATTERNS = (
    re.compile(r"\bglobal\b", re.IGNORECASE),
    re.compile(r"全局"),
    re.compile(r"企业通用"),
)


@dataclass(frozen=True)
class InferredScope:
    """Semantic retrieval scope inferred from a user question.

    ``product`` / ``project`` / ``revision`` follow the canonical three-level
    hierarchy (ADR 0011). ``project`` may be ``None`` for a build-layer scope
    when the build slug is ambiguous across the product's projects; resolvers
    must then expand to all matching ``(product, project, build)`` triples.
    """

    product: str | None = None
    project: str | None = None
    revision: str | None = None
    layer: KnowledgeLayer = "inherit"
    stripped_query: str = ""


def _normalize_token(value: str) -> str:
    return value.strip().lower()


def _strip_patterns(text: str, patterns: list[re.Pattern[str]]) -> str:
    cleaned = text
    for pattern in patterns:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text.strip()


def _enterprise_scope(query: str) -> InferredScope | None:
    matched = [pattern for pattern in _ENTERPRISE_PATTERNS if pattern.search(query)]
    if not matched:
        return None
    stripped = _strip_patterns(query, matched)
    return InferredScope(layer="enterprise", stripped_query=stripped)


def _joined_pattern(*tokens: str) -> re.Pattern[str]:
    """Compile a pattern matching tokens joined by whitespace or ``/``."""
    joined = r"(?:\s*/\s*|\s+)".join(re.escape(token) for token in tokens)
    return re.compile(rf"\b{joined}\b", re.IGNORECASE)


def _product_common_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    """Match ``{product} common`` → product-common layer (project=build=common)."""
    common = catalog.project_shared_segment
    for match_token, canonical in catalog.product_match_tokens():
        pattern = _joined_pattern(match_token, common)
        if not pattern.search(query):
            continue
        stripped = _strip_patterns(query, [pattern])
        return InferredScope(
            product=canonical,
            layer="product_common",
            stripped_query=stripped,
        )
    return None


def _project_common_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    """Match ``{product} {project} common`` → project-common layer."""
    common = catalog.project_shared_segment
    for match_token, canonical in catalog.product_match_tokens():
        for project in sorted(catalog.projects_for(canonical), key=len, reverse=True):
            pattern = _joined_pattern(match_token, project, common)
            if not pattern.search(query):
                continue
            stripped = _strip_patterns(query, [pattern])
            return InferredScope(
                product=canonical,
                project=project,
                layer="project_common",
                stripped_query=stripped,
            )
    return None


def _product_project_build_scope(
    query: str,
    catalog: ScopeCatalog,
) -> InferredScope | None:
    """Match ``{product} {project} {build}`` → build layer (full triple)."""
    for match_token, canonical in catalog.product_match_tokens():
        for project in sorted(catalog.projects_for(canonical), key=len, reverse=True):
            builds = catalog.builds_for(canonical, project)
            for build in sorted(builds, key=len, reverse=True):
                pattern = _joined_pattern(match_token, project, build)
                if not pattern.search(query):
                    continue
                stripped = _strip_patterns(query, [pattern])
                return InferredScope(
                    product=canonical,
                    project=project,
                    revision=build,
                    layer="build",
                    stripped_query=stripped,
                )
    return None


def _product_revision_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    """Match ``{product} {build}`` and resolve the owning project when unique."""
    for match_token, canonical in catalog.product_match_tokens():
        revisions = catalog.builds_for(canonical)
        for revision in sorted(revisions, key=len, reverse=True):
            pattern = _joined_pattern(match_token, revision)
            if not pattern.search(query):
                continue
            stripped = _strip_patterns(query, [pattern])
            owners = catalog.projects_with_build(canonical, revision)
            project = owners[0] if len(owners) == 1 else None
            return InferredScope(
                product=canonical,
                project=project,
                revision=revision,
                layer="build",
                stripped_query=stripped,
            )
    return None


def _product_project_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    """Match ``{product} {project}`` → inherit within that project."""
    for match_token, canonical in catalog.product_match_tokens():
        for project in sorted(catalog.projects_for(canonical), key=len, reverse=True):
            pattern = _joined_pattern(match_token, project)
            if not pattern.search(query):
                continue
            stripped = _strip_patterns(query, [pattern])
            return InferredScope(
                product=canonical,
                project=project,
                layer="inherit",
                stripped_query=stripped,
            )
    return None


def _product_only_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    for match_token, canonical in catalog.product_match_tokens():
        pattern = re.compile(rf"\b{re.escape(match_token)}\b", re.IGNORECASE)
        if not pattern.search(query):
            continue
        stripped = _strip_patterns(query, [pattern])
        return InferredScope(
            product=canonical,
            layer="inherit",
            stripped_query=stripped,
        )
    return None


def extract_scope_rules(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    """Infer scope from ``query`` using deterministic rules.

    Match order (most specific first): enterprise keywords, project common,
    product common, full product/project/build triple, product+build,
    product+project, then product only.

    Args:
        query: User question text.
        catalog: Known products, projects, and builds from the index.

    Returns:
        Parsed scope when a rule matches; otherwise ``None``.
    """
    text = query.strip()
    if not text:
        return None

    enterprise = _enterprise_scope(text)
    if enterprise is not None:
        return enterprise

    for catalog_matcher in (
        _project_common_scope,
        _product_common_scope,
        _product_project_build_scope,
        _product_revision_scope,
        _product_project_scope,
        _product_only_scope,
    ):
        result = catalog_matcher(text, catalog)
        if result is not None:
            return result
    return None


def parse_prepare_layer(raw: str | None) -> KnowledgeLayer | None:
    """Normalize a prepare-prompt ``LAYER`` label."""
    if not raw:
        return None
    normalized = _normalize_token(raw)
    if normalized in {"none", "inherit", "all"}:
        return "inherit"
    if normalized in {"build", "revision", "board"}:
        return "build"
    if normalized in {"project_common", "project-common"}:
        return "project_common"
    if normalized in {"product_common", "product-common", "common"}:
        return "product_common"
    if normalized in {"enterprise", "global"}:
        return "enterprise"
    return None


def validate_inferred_scope(
    *,
    product: str | None,
    revision: str | None,
    layer: KnowledgeLayer | None,
    catalog: ScopeCatalog,
    project: str | None = None,
) -> InferredScope | None:
    """Validate prepare/LLM scope fields against the catalog.

    Args:
        product: Product token from the prepare output.
        revision: Build/revision token from the prepare output.
        layer: Normalized knowledge layer, if any.
        catalog: Known products, projects, and builds.
        project: Optional project token (prepare prompts may not emit one; the
            owning project is then resolved from the build when unambiguous).

    Returns:
        Validated scope, or ``None`` when the fields do not match the catalog.
    """
    resolved_layer: KnowledgeLayer = layer or "inherit"

    if resolved_layer == "enterprise":
        return InferredScope(layer="enterprise")

    if product and _normalize_token(product) == catalog.enterprise_segment:
        return InferredScope(layer="enterprise")

    product_name = catalog.resolve_product(product)
    if product and product_name is None:
        return None

    project_name = _normalize_token(project) if project else None
    if project_name and not catalog.is_valid_project(product_name, project_name):
        return None

    if revision and _normalize_token(revision) == catalog.project_shared_segment:
        if not product_name:
            return None
        if project_name:
            return InferredScope(
                product=product_name,
                project=project_name,
                layer="project_common",
            )
        return InferredScope(product=product_name, layer="product_common")

    revision_name = _normalize_token(revision) if revision else None
    if revision_name:
        if not product_name:
            return None
        if project_name:
            if not catalog.is_valid_build(product_name, project_name, revision_name):
                return None
            return InferredScope(
                product=product_name,
                project=project_name,
                revision=revision_name,
                layer="build",
            )
        if not catalog.is_valid_revision(product_name, revision_name):
            return None
        owners = catalog.projects_with_build(product_name, revision_name)
        return InferredScope(
            product=product_name,
            project=owners[0] if len(owners) == 1 else None,
            revision=revision_name,
            layer="build",
        )

    if product_name:
        if resolved_layer == "project_common" and not project_name:
            resolved_layer = "product_common"
        return InferredScope(
            product=product_name,
            project=project_name,
            layer=resolved_layer,
        )

    return None
