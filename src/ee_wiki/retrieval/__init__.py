"""Hybrid document retrieval."""

from ee_wiki.knowledge.loader import ProcessedRecord, load_processed_records
from ee_wiki.retrieval.tokenizer import tokenize_hw_text

__all__ = [
    "HybridChunk",
    "HybridRagEngine",
    "ProcessedRecord",
    "load_processed_records",
    "tokenize_hw_text",
]


def __getattr__(name: str):
    if name in {"HybridChunk", "HybridRagEngine"}:
        from ee_wiki.retrieval.hybrid import HybridChunk, HybridRagEngine

        return HybridChunk if name == "HybridChunk" else HybridRagEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
