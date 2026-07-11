"""Abstract interfaces for on-disk index persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ee_wiki.common.types import Chunk


class IndexStoreBackend(Protocol):
    """Persist and load hybrid retrieval index bundles."""

    def save_index(
        self,
        indexes_dir: Path,
        *,
        chunks: list[Chunk],
        embeddings: Any,
        bm25_corpus: list[list[str]],
        source_fingerprints: dict[str, dict[str, float | int]],
    ) -> Any:
        """Write chunks, embeddings, and BM25 corpus to ``indexes_dir``.

        Args:
            indexes_dir: Target directory (created when missing).
            chunks: Indexed chunks in embedding row order.
            embeddings: ``(n_chunks, dim)`` embedding matrix aligned with ``chunks``.
            bm25_corpus: Tokenized corpus aligned with ``chunks``.
            source_fingerprints: Processed document fingerprints keyed by ``target_file``.

        Returns:
            Written manifest metadata (implementation-specific dataclass).
        """
        ...

    def load_index(self, indexes_dir: Path) -> Any:
        """Load a persisted hybrid index bundle.

        Args:
            indexes_dir: Directory containing manifest, chunks, embeddings, and BM25 files.

        Returns:
            Loaded index bundle ready for retrieval (implementation-specific dataclass).
        """
        ...
