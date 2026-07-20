"""Live Flames backend placeholder (fill when intranet API is available).

See ``docs/architecture/integrations-flames.md``.
"""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import ConfigError
from ee_wiki.protocols.flames import (
    FailItem,
    FailItemsResult,
    FlamesUnitRef,
    TestRecord,
)


class LiveFlamesBackend:
    """Flames backend for the corporate API.

    Raises:
        ConfigError: Always, until API details are documented and implemented.
    """

    def __init__(self, *, base_url: str | None = None) -> None:
        """Record config and refuse until implemented.

        Args:
            base_url: Flames API base URL (TBD).
        """
        self.base_url = base_url
        raise ConfigError(
            "LiveFlamesBackend is not implemented yet. "
            "Document the API in docs/architecture/integrations-flames.md "
            "on an intranet host, then implement this class."
        )

    def resolve_unit(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
    ) -> FlamesUnitRef:
        """Resolve a live Flames unit (not implemented)."""
        raise NotImplementedError

    def list_test_records(self, unit: FlamesUnitRef) -> list[TestRecord]:
        """List live test records (not implemented)."""
        raise NotImplementedError

    def fetch_log(self, record: TestRecord, dest_dir: Path) -> Path:
        """Download a live log (not implemented)."""
        raise NotImplementedError

    def extract_errors(self, log_path: Path) -> list[FailItem]:
        """Extract errors from a log (not implemented)."""
        raise NotImplementedError

    def collect_fail_items(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
        cache_dir: Path,
    ) -> FailItemsResult:
        """Collect fail items from live Flames (not implemented)."""
        raise NotImplementedError
