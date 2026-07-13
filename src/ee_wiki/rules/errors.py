"""Error types for the engineering rules engine."""

from __future__ import annotations

from ee_wiki.common.errors import EEWikiError


class RuleError(EEWikiError):
    """Rules evaluation or configuration failure."""


class RulePackError(RuleError):
    """Failed to load or parse a rule pack from disk."""
