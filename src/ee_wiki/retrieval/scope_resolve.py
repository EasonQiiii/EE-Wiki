"""Map inferred semantic scope to retrieval engine metadata filters."""

from __future__ import annotations

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope
from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_extract import InferredScope, KnowledgeLayer


def _inherit_product_scope_ranks(
    product: str,
    catalog: ScopeCatalog,
    layout: DataLayoutConfig,
) -> dict[tuple[str, str], int]:
    """Rank all layers for a product-only inherit query."""
    enterprise = layout.enterprise_project
    common = layout.project_shared_build
    ranks: dict[tuple[str, str], int] = {}
    revision_rank = 0
    for revision in sorted(catalog.products.get(product, ())):
        ranks[(product, revision)] = revision_rank
    ranks[(product, common)] = revision_rank + 1
    ranks[(enterprise, enterprise)] = revision_rank + 2
    return ranks


def resolve_retrieval_targets(
    inferred: InferredScope,
    catalog: ScopeCatalog,
    layout: DataLayoutConfig,
) -> tuple[str | None, str | None, dict[tuple[str, str], int]]:
    """Map semantic scope to engine ``target_project`` / ``target_build`` inputs.

    Args:
        inferred: Rule- or LLM-derived semantic scope.
        catalog: Known products and revisions.
        layout: Data layout configuration.

    Returns:
        Tuple of ``target_project``, ``target_build``, and optional scope rank map.
    """
    layer: KnowledgeLayer = inferred.layer
    enterprise = layout.enterprise_project
    common = layout.project_shared_build

    if layer == "enterprise":
        return enterprise, enterprise, {(enterprise, enterprise): 0}

    if layer == "project_common" and inferred.product:
        scopes = expand_retrieval_scope(inferred.product, common, layout)
        scope_ranks = {pair: rank for rank, pair in enumerate(scopes)}
        return inferred.product, common, scope_ranks

    if layer == "build" and inferred.product and inferred.revision:
        scopes = expand_retrieval_scope(inferred.product, inferred.revision, layout)
        scope_ranks = {pair: rank for rank, pair in enumerate(scopes)}
        return inferred.product, inferred.revision, scope_ranks

    if inferred.product and layer == "inherit":
        scope_ranks = _inherit_product_scope_ranks(inferred.product, catalog, layout)
        return inferred.product, None, scope_ranks

    return None, None, {}


def merge_inferred_scope(
    *,
    rules: InferredScope | None,
    prepared_product: str | None,
    prepared_revision: str | None,
    prepared_layer: KnowledgeLayer | None,
    catalog: ScopeCatalog,
    stripped_from_rules: str = "",
) -> tuple[InferredScope | None, str]:
    """Prefer prepare output, then fall back to rule extraction."""
    from ee_wiki.retrieval.scope_extract import validate_inferred_scope

    if prepared_product or prepared_revision or prepared_layer == "enterprise":
        validated = validate_inferred_scope(
            product=prepared_product,
            revision=prepared_revision,
            layer=prepared_layer,
            catalog=catalog,
        )
        if validated is not None:
            return validated, stripped_from_rules

    if rules is not None:
        return rules, rules.stripped_query

    return None, stripped_from_rules
