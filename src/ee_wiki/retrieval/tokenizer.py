"""Hardware-aware tokenization for BM25 sparse retrieval."""

from __future__ import annotations

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


def tokenize_hw_text(text: str) -> list[str]:
    """Tokenize text while preserving hardware identifiers.

    Ported from legacy BYDEE101 RAG pipeline. Uses jieba when available and keeps
    designators such as ``U101``, ``NET_PCIE_CLK``, and ``DDR4_A0`` intact.

    Args:
        text: Input document or query text.

    Returns:
        Token list suitable for BM25 indexing.
    """
    try:
        import jieba
    except ImportError as exc:
        raise ImportError(
            "jieba is required for BM25 tokenization: pip install ee-wiki[ml]"
        ) from exc

    words = [word.strip() for word in jieba.cut(text) if word.strip()]
    return words
