"""Word parser error types."""

from ee_wiki.common.errors import EEWikiError


class WordParserError(EEWikiError):
    """Failed to parse a Word source file."""
