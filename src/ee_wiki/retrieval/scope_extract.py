"""Rule-based product / revision / layer extraction from natural language."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ee_wiki.retrieval.scope_catalog import ScopeCatalog

KnowledgeLayer = Literal["build", "project_common", "enterprise", "inherit"]

_ENTERPRISE_PATTERNS = (
    re.compile(r"\bglobal\b", re.IGNORECASE),
    re.compile(r"全局"),
    re.compile(r"企业通用"),
)


@dataclass(frozen=True)
class InferredScope:
    """Semantic retrieval scope inferred from a user question."""

    product: str | None = None
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


def _product_common_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    common = catalog.project_shared_segment
    for product in catalog.products:
        pattern = re.compile(
            rf"\b{re.escape(product)}\s+{re.escape(common)}\b",
            re.IGNORECASE,
        )
        if not pattern.search(query):
            continue
        stripped = _strip_patterns(query, [pattern])
        return InferredScope(
            product=product,
            layer="project_common",
            stripped_query=stripped,
        )
    return None


def _product_revision_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    for product, revisions in catalog.products.items():
        for revision in sorted(revisions, key=len, reverse=True):
            slash_pattern = re.compile(
                rf"\b{re.escape(product)}\s*/\s*{re.escape(revision)}\b",
                re.IGNORECASE,
            )
            if slash_pattern.search(query):
                stripped = _strip_patterns(query, [slash_pattern])
                return InferredScope(
                    product=product,
                    revision=revision,
                    layer="build",
                    stripped_query=stripped,
                )
            spaced_pattern = re.compile(
                rf"\b{re.escape(product)}\s+{re.escape(revision)}\b",
                re.IGNORECASE,
            )
            if spaced_pattern.search(query):
                stripped = _strip_patterns(query, [spaced_pattern])
                return InferredScope(
                    product=product,
                    revision=revision,
                    layer="build",
                    stripped_query=stripped,
                )
    return None


def _product_only_scope(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    for product in sorted(catalog.products, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(product)}\b", re.IGNORECASE)
        if not pattern.search(query):
            continue
        stripped = _strip_patterns(query, [pattern])
        return InferredScope(
            product=product,
            layer="inherit",
            stripped_query=stripped,
        )
    return None


def extract_scope_rules(query: str, catalog: ScopeCatalog) -> InferredScope | None:
    """Infer scope from ``query`` using deterministic rules.

    Args:
        query: User question text.
        catalog: Known products and revisions from the index.

    Returns:
        Parsed scope when a rule matches; otherwise ``None``.
    """
    text = query.strip()
    if not text:
        return None

    enterprise = _enterprise_scope(text)
    if enterprise is not None:
        return enterprise

    product_common = _product_common_scope(text, catalog)
    if product_common is not None:
        return product_common

    product_revision = _product_revision_scope(text, catalog)
    if product_revision is not None:
        return product_revision

    return _product_only_scope(text, catalog)


def parse_prepare_layer(raw: str | None) -> KnowledgeLayer | None:
    """Normalize a prepare-prompt ``LAYER`` label."""
    if not raw:
        return None
    normalized = _normalize_token(raw)
    if normalized in {"none", "inherit", "all"}:
        return "inherit"
    if normalized in {"build", "revision", "board"}:
        return "build"
    if normalized in {"project_common", "common", "project-common"}:
        return "project_common"
    if normalized in {"enterprise", "global"}:
        return "enterprise"
    return None


def validate_inferred_scope(
    *,
    product: str | None,
    revision: str | None,
    layer: KnowledgeLayer | None,
    catalog: ScopeCatalog,
) -> InferredScope | None:
    """Validate prepare/LLM scope fields against the catalog."""
    resolved_layer: KnowledgeLayer = layer or "inherit"

    if resolved_layer == "enterprise":
        return InferredScope(layer="enterprise")

    if product and _normalize_token(product) == catalog.enterprise_segment:
        return InferredScope(layer="enterprise")

    if revision and _normalize_token(revision) == catalog.project_shared_segment:
        product_name = _normalize_token(product) if product else None
        if product_name and catalog.is_valid_product(product_name):
            return InferredScope(product=product_name, layer="project_common")
        return None

    product_name = _normalize_token(product) if product else None
    revision_name = _normalize_token(revision) if revision else None

    if product_name and not catalog.is_valid_product(product_name):
        return None

    if revision_name:
        if not product_name or not catalog.is_valid_revision(product_name, revision_name):
            return None
        return InferredScope(
            product=product_name,
            revision=revision_name,
            layer="build",
        )

    if product_name:
        return InferredScope(product=product_name, layer=resolved_layer)

    return None
