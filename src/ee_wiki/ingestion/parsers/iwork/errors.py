"""Errors for Apple iWork ingest via macOS export."""

from ee_wiki.common.errors import EEWikiError


class IworkParserError(EEWikiError):
    """Keynote or Numbers export or parse failed."""
