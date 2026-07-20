"""Build a product/project/build catalog from indexed chunk metadata."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ee_wiki.common.project_aliases import canonicalize_project, normalize_project_aliases
from ee_wiki.common.types import DataLayoutConfig


@dataclass(frozen=True)
class ScopeCatalog:
    """Known products, projects, and hardware builds for scope inference.

    ``global`` is not a product; ``common`` is not a project or build — those
    reserved segments come from :class:`DataLayoutConfig` and are excluded
    from the maps below.

    ``products`` maps ``product → project → builds``. Membership is always a
    full ``(product, project, build)`` triple so identical project/build slugs
    under two different products stay isolated.

    ``project_aliases`` maps alternate names (e.g. 甲方 ``H340``) to the
    EE-Wiki product path slug (e.g. 乙方 ``logan``).
    """

    products: dict[str, dict[str, frozenset[str]]]
    enterprise_segment: str
    project_shared_segment: str
    project_aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_metadata_triples(
        cls,
        triples: Iterable[tuple[str, str, str]],
        layout: DataLayoutConfig,
    ) -> ScopeCatalog:
        """Build a catalog from ``(product, project, build)`` metadata triples.

        Args:
            triples: Metadata scope triples from indexed chunks.
            layout: Data layout configuration for reserved segment names.

        Returns:
            Catalog with products mapped to projects and hardware builds only.
        """
        enterprise = layout.enterprise_project
        common = layout.project_shared_build
        by_product: dict[str, dict[str, set[str]]] = {}

        for product, project, build in triples:
            if not product:
                continue
            if product == enterprise:
                continue
            # Register the product even when only ``common`` docs exist;
            # ``common`` is never a project or hardware build.
            projects = by_product.setdefault(product, {})
            if not project or project == common:
                continue
            builds = projects.setdefault(project, set())
            if not build or build == common:
                continue
            builds.add(build)

        products = {
            product: {
                project: frozenset(builds)
                for project, builds in sorted(projects.items())
            }
            for product, projects in sorted(by_product.items())
        }
        return cls(
            products=products,
            enterprise_segment=enterprise,
            project_shared_segment=common,
            project_aliases=normalize_project_aliases(dict(layout.project_aliases)),
        )

    @classmethod
    def from_chunk_metadata(
        cls,
        chunks: Iterable[Any],
        layout: DataLayoutConfig,
    ) -> ScopeCatalog:
        """Build a catalog from hybrid chunks or dict metadata records."""
        triples: list[tuple[str, str, str]] = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                metadata = chunk
            else:
                metadata = getattr(chunk, "metadata", None) or {}
            product = str(metadata.get("product", "") or "")
            project = str(metadata.get("project", "") or "")
            build = str(metadata.get("build", "") or "")
            if product:
                triples.append((product, project, build))
        return cls.from_metadata_triples(triples, layout)

    def format_known_products(self) -> str:
        """Render catalog entries for prepare prompts."""
        if not self.products:
            return "(none)"
        lines: list[str] = []
        for product, projects in sorted(self.products.items()):
            if not projects:
                lines.append(
                    f"- {product}: ({self.project_shared_segment} only; no project)"
                )
                continue
            bits: list[str] = []
            for project, builds in sorted(projects.items()):
                if builds:
                    bits.append(f"{project} ({', '.join(sorted(builds))})")
                else:
                    bits.append(f"{project} ({self.project_shared_segment} only)")
            lines.append(f"- {product}: {'; '.join(bits)}")
        if self.project_aliases:
            alias_bits = [
                f"{alias}→{canonical}"
                for alias, canonical in sorted(self.project_aliases.items())
            ]
            lines.append(f"- aliases: {', '.join(alias_bits)}")
        return "\n".join(lines)

    def resolve_product(self, product: str | None) -> str | None:
        """Resolve an alias or product token to a catalog product slug."""
        canonical = canonicalize_project(product, self.project_aliases)
        if canonical and canonical in self.products:
            return canonical
        return None

    def is_valid_product(self, product: str | None) -> bool:
        """Return whether ``product`` is a known non-enterprise product."""
        return self.resolve_product(product) is not None

    def projects_for(self, product: str | None) -> frozenset[str]:
        """Return known project slugs for ``product`` (aliases resolved)."""
        resolved = self.resolve_product(product)
        if not resolved:
            return frozenset()
        return frozenset(self.products.get(resolved, {}))

    def is_valid_project(self, product: str | None, project: str | None) -> bool:
        """Return whether ``project`` is a known project under ``product``."""
        if not project:
            return False
        return project in self.projects_for(product)

    def builds_for(self, product: str | None, project: str | None = None) -> frozenset[str]:
        """Return hardware builds for ``product`` (optionally one project).

        Args:
            product: Product slug or alias.
            project: Optional project restriction; ``None`` unions all projects.

        Returns:
            Known hardware build slugs (never includes reserved segments).
        """
        resolved = self.resolve_product(product)
        if not resolved:
            return frozenset()
        projects = self.products.get(resolved, {})
        if project is not None:
            return projects.get(project, frozenset())
        merged: set[str] = set()
        for builds in projects.values():
            merged |= builds
        return frozenset(merged)

    def is_valid_build(
        self,
        product: str | None,
        project: str | None,
        build: str | None,
    ) -> bool:
        """Return whether ``build`` is a known hardware build in that scope."""
        if not build:
            return False
        return build in self.builds_for(product, project)

    def is_valid_revision(self, product: str | None, revision: str | None) -> bool:
        """Return whether ``revision`` is a known hardware build for ``product``."""
        if not revision:
            return False
        return revision in self.builds_for(product)

    def projects_with_build(self, product: str | None, build: str | None) -> list[str]:
        """Return projects of ``product`` that contain hardware build ``build``.

        Used to resolve a product+build query (e.g. ``logan p1``) to concrete
        ``(product, project, build)`` triples without guessing across products.
        """
        resolved = self.resolve_product(product)
        if not resolved or not build:
            return []
        return sorted(
            project
            for project, builds in self.products.get(resolved, {}).items()
            if build in builds
        )

    def product_match_tokens(self) -> list[tuple[str, str]]:
        """Return ``(match_token, canonical_product)`` pairs, longest first.

        Includes indexed products and configured aliases that resolve to them.
        """
        pairs: dict[str, str] = {}
        for product in self.products:
            pairs[product.casefold()] = product
        for alias, canonical in self.project_aliases.items():
            if canonical in self.products:
                pairs[alias.casefold()] = canonical
        return sorted(pairs.items(), key=lambda item: len(item[0]), reverse=True)
