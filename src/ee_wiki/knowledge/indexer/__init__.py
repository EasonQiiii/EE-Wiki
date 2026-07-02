"""Hybrid index builders and on-disk persistence."""

from ee_wiki.knowledge.indexer.store import (
    IndexManifest,
    IndexStoreError,
    PersistedIndex,
    index_exists,
    load_index,
    save_index,
)

__all__ = [
    "IndexBuildResult",
    "IndexManifest",
    "IndexStoreError",
    "PersistedIndex",
    "build_index_from_processed",
    "index_exists",
    "load_index",
    "save_index",
]


def __getattr__(name: str):
    if name == "IndexBuildResult":
        from ee_wiki.knowledge.indexer.build import IndexBuildResult

        return IndexBuildResult
    if name == "build_index_from_processed":
        from ee_wiki.knowledge.indexer.build import build_index_from_processed

        return build_index_from_processed
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
