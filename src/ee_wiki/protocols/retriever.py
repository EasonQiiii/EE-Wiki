"""Abstract interfaces for retrieval backends."""

from __future__ import annotations

from typing import Any, Protocol


class RetrieverBackend(Protocol):
    """Hybrid retrieval and component lookup without generation."""

    def retrieve(
        self,
        query: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
    ) -> Any:
        """Return ranked chunks matching the query and metadata filters.

        Args:
            query: Natural language or keyword search string.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            document_type: Optional document type filter.
            top_k_final: Optional reranked result count override.

        Returns:
            Retrieval result with ``chunks`` and optional ``top_rerank_score``
            (see :class:`ee_wiki.retrieval.hybrid.engine.RetrievalResult`).
        """
        ...

    def search_components(
        self,
        query: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        limit: int = 20,
    ) -> list[Any]:
        """Look up part numbers or schematic designators in the component index.

        Args:
            query: Part number or schematic reference designator.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            limit: Maximum number of hits to return.

        Returns:
            Matching component hits scoped to the requested project/build
            (see :class:`ee_wiki.knowledge.indexer.component_index.ComponentHit`).
        """
        ...
