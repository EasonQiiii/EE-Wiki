"""Shared exception types for EE-Wiki."""


class EEWikiError(Exception):
    """Base exception for EE-Wiki."""


class ConfigError(EEWikiError):
    """Configuration file is missing or invalid."""


class PathMetadataError(EEWikiError):
    """A raw file path does not match the expected data/raw layout."""


class MigrationError(EEWikiError):
    """Legacy raw-layout migration cannot proceed safely."""


class IntegrationError(EEWikiError):
    """External FA integration (Radar / Flames / report) failure."""


class ScopeValidationError(EEWikiError):
    """Ambiguous or incomplete product/project/build scope filters."""
