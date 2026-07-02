"""Backward-compatible re-export; prefer :mod:`ee_wiki.knowledge.loader`."""

from ee_wiki.knowledge.loader import ProcessedRecord, load_processed_records

__all__ = ["ProcessedRecord", "load_processed_records"]
