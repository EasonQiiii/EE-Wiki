"""Map inferred semantic scope to retrieval engine metadata filters."""

from __future__ import annotations

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope
from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_extract import InferredScope, KnowledgeLayer

ScopeRanks = dict[tuple[str, str, str], int]

ResolvedTargets = tuple[str | None, str | None, str | None, ScopeRanks]


def _ranks_from_expansion(
    product: str,
    project: str,
    build: str,
    layout: DataLayoutConfig,
) -> ScopeRanks:
    scopes = expand_retrieval_scope(product, project, build, layout)
    return {triple: rank for rank, triple in enumerate(scopes)}


def _inherit_project_scope_ranks(
    product: str,
    project: str,
    catalog: ScopeCatalog,
    layout: DataLayoutConfig,
) -> ScopeRanks:
    """Rank all layers for a product+project inherit query."""
    enterprise = layout.enterprise_project
    common = layout.project_shared_build
    ranks: ScopeRanks = {}
    for build in sorted(catalog.builds_for(product, project)):
        ranks[(product, project, build)] = 0
    ranks[(product, project, common)] = 1
    ranks[(product, common, common)] = 2
    ranks[(enterprise, enterprise, enterprise)] = 3
    return ranks


def _inherit_product_scope_ranks(
    product: str,
    catalog: ScopeCatalog,
    layout: DataLayoutConfig,
) -> ScopeRanks:
    """Rank all layers for a product-only inherit query."""
    enterprise = layout.enterprise_project
    common = layout.project_shared_build
    ranks: ScopeRanks = {}
    for project in sorted(catalog.projects_for(product)):
        for build in sorted(catalog.builds_for(product, project)):
            ranks[(product, project, build)] = 0
        ranks[(product, project, common)] = 1
    ranks[(product, common, common)] = 2
    ranks[(enterprise, enterprise, enterprise)] = 3
    return ranks


def _ambiguous_build_scope_ranks(
    product: str,
    build: str,
    catalog: ScopeCatalog,
    layout: DataLayoutConfig,
) -> ScopeRanks:
    """Rank triples when a build slug exists under multiple projects of one product.

    All matching ``(product, project, build)`` triples share the top rank; the
    corresponding project commons, the product common, and ``global`` follow.
    Nothing outside ``product`` (except the enterprise library) is included, so
    a same-named build in another product can never leak in.
    """
    enterprise = layout.enterprise_project
    common = layout.project_shared_build
    ranks: ScopeRanks = {}
    owners = catalog.projects_with_build(product, build) or sorted(
        catalog.projects_for(product)
    )
    for project in owners:
        ranks[(product, project, build)] = 0
    for project in owners:
        ranks[(product, project, common)] = 1
    ranks[(product, common, common)] = 2
    ranks[(enterprise, enterprise, enterprise)] = 3
    return ranks


def resolve_retrieval_targets(
    inferred: InferredScope,
    catalog: ScopeCatalog,
    layout: DataLayoutConfig,
) -> ResolvedTargets:
    """Map semantic scope to engine ``target_product``/``project``/``build`` inputs.

    Args:
        inferred: Rule- or LLM-derived semantic scope.
        catalog: Known products, projects, and builds.
        layout: Data layout configuration.

    Returns:
        Tuple of ``target_product``, ``target_project``, ``target_build``, and
        a scope rank map over ``(product, project, build)`` triples.
    """
    layer: KnowledgeLayer = inferred.layer
    enterprise = layout.enterprise_project
    common = layout.project_shared_build

    if layer == "enterprise":
        return (
            enterprise,
            enterprise,
            enterprise,
            {(enterprise, enterprise, enterprise): 0},
        )

    if layer == "product_common" and inferred.product:
        ranks = _ranks_from_expansion(inferred.product, common, common, layout)
        return inferred.product, common, common, ranks

    if layer == "project_common" and inferred.product and inferred.project:
        ranks = _ranks_from_expansion(
            inferred.product, inferred.project, common, layout
        )
        return inferred.product, inferred.project, common, ranks

    if layer == "build" and inferred.product and inferred.revision:
        if inferred.project:
            ranks = _ranks_from_expansion(
                inferred.product, inferred.project, inferred.revision, layout
            )
            return inferred.product, inferred.project, inferred.revision, ranks
        ranks = _ambiguous_build_scope_ranks(
            inferred.product, inferred.revision, catalog, layout
        )
        return inferred.product, None, inferred.revision, ranks

    if layer == "inherit" and inferred.product and inferred.project:
        ranks = _inherit_project_scope_ranks(
            inferred.product, inferred.project, catalog, layout
        )
        return inferred.product, inferred.project, None, ranks

    if inferred.product and layer == "inherit":
        ranks = _inherit_product_scope_ranks(inferred.product, catalog, layout)
        return inferred.product, None, None, ranks

    return None, None, None, {}


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
