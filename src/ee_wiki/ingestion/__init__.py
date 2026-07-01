"""Document ingestion: parsers and path-derived metadata."""

from ee_wiki.ingestion.path_metadata import expand_retrieval_scope, parse_path_metadata
from ee_wiki.ingestion.pipeline import IngestResult, ingest_file, ingest_path

__all__ = [
    "IngestResult",
    "expand_retrieval_scope",
    "ingest_file",
    "ingest_path",
    "parse_path_metadata",
]
