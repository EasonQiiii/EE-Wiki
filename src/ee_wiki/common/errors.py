"""Shared exception types for EE-Wiki."""


class EEWikiError(Exception):
    """Base exception for EE-Wiki."""


class ConfigError(EEWikiError):
    """Configuration file is missing or invalid."""


class PathMetadataError(EEWikiError):
    """A raw file path does not match the expected data/raw layout."""
