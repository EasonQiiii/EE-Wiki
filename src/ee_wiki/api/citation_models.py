"""Map domain citations to API response models."""

from __future__ import annotations

from ee_wiki.api.models import CitationModel
from ee_wiki.common.types import Citation


def citation_to_model(citation: Citation) -> CitationModel:
    """Convert a domain :class:`Citation` to its HTTP representation."""
    return CitationModel(
        source_file=citation.source_file,
        chunk_id=citation.chunk_id,
        page=citation.page,
        excerpt=citation.excerpt,
        url=citation.url,
        images=list(citation.images),
    )
