"""Build a product/revision catalog from indexed chunk metadata."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ee_wiki.common.types import DataLayoutConfig


@dataclass(frozen=True)
class ScopeCatalog:
    """Known products and hardware revisions for scope inference.

    ``global`` is not a product; ``common`` is not a revision — those reserved
    segments come from :class:`DataLayoutConfig` and are excluded from the maps
    below.
    """

    products: dict[str, frozenset[str]]
    enterprise_segment: str
    project_shared_segment: str

    @classmethod
    def from_metadata_pairs(
        cls,
        pairs: Iterable[tuple[str, str]],
        layout: DataLayoutConfig,
    ) -> ScopeCatalog:
        """Build a catalog from ``(project, build)`` metadata pairs.

        Args:
            pairs: Metadata project/build pairs from indexed chunks.
            layout: Data layout configuration for reserved segment names.

        Returns:
            Catalog with products mapped to hardware revision names only.
        """
        enterprise = layout.enterprise_project
        common = layout.project_shared_build
        revisions_by_product: dict[str, set[str]] = {}

        for project, build in pairs:
            if not project or not build:
                continue
            if project == enterprise:
                continue
            # Register the product even when only ``common`` docs exist; ``common``
            # is never a hardware revision.
            revisions_by_product.setdefault(project, set())
            if build == common:
                continue
            revisions_by_product[project].add(build)

        products = {
            product: frozenset(revisions)
            for product, revisions in sorted(revisions_by_product.items())
        }
        return cls(
            products=products,
            enterprise_segment=enterprise,
            project_shared_segment=common,
        )

    @classmethod
    def from_chunk_metadata(
        cls,
        chunks: Iterable[Any],
        layout: DataLayoutConfig,
    ) -> ScopeCatalog:
        """Build a catalog from hybrid chunks or dict metadata records."""
        pairs: list[tuple[str, str]] = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                metadata = chunk
            else:
                metadata = getattr(chunk, "metadata", None) or {}
            project = str(metadata.get("project", "") or "")
            build = str(metadata.get("build", "") or "")
            if project and build:
                pairs.append((project, build))
        return cls.from_metadata_pairs(pairs, layout)

    def format_known_products(self) -> str:
        """Render catalog entries for prepare prompts."""
        if not self.products:
            return "(none)"
        lines: list[str] = []
        for product, revisions in sorted(self.products.items()):
            if revisions:
                rev_list = ", ".join(sorted(revisions))
                lines.append(f"- {product}: {rev_list}")
            else:
                lines.append(
                    f"- {product}: ({self.project_shared_segment} only; no hardware revision)"
                )
        return "\n".join(lines)

    def is_valid_product(self, product: str | None) -> bool:
        """Return whether ``product`` is a known non-enterprise product."""
        if not product:
            return False
        return product in self.products

    def is_valid_revision(self, product: str | None, revision: str | None) -> bool:
        """Return whether ``revision`` is a known hardware build for ``product``."""
        if not product or not revision:
            return False
        revisions = self.products.get(product)
        return revisions is not None and revision in revisions
