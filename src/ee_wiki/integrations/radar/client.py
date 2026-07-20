"""Live ``radarclient`` backend (implemented when Apple network is available).

This module is intentionally a thin placeholder. Install Apple-internal
``radarclient`` on the host and implement :class:`RadarclientBackend` using
the mapping in ``docs/architecture/integrations-radar.md``.
"""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import ConfigError
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DiagnosisItem,
    RadarProblem,
    RadarWriteResult,
)


class RadarclientBackend:
    """Radar backend backed by Apple ``radarclient``.

    Raises:
        ConfigError: Always, until the live implementation is filled in on
            an intranet host with Kerberos + ``radarclient`` installed.
    """

    def __init__(self) -> None:
        """Attempt to import ``radarclient`` and construct a client."""
        try:
            import radarclient  # noqa: F401
        except ImportError as exc:
            raise ConfigError(
                "fa.radar.backend=radarclient requires the Apple radarclient "
                "package on PYTHONPATH (not vendored in EE-Wiki). "
                "See docs/architecture/integrations-radar.md"
            ) from exc
        raise ConfigError(
            "RadarclientBackend is not implemented yet. "
            "Follow docs/architecture/integrations-radar.md on an "
            "intranet host with Kerberos credentials."
        )

    def get_problem(self, radar_id: str) -> RadarProblem:
        """Fetch a live Radar problem (not implemented)."""
        raise NotImplementedError

    def list_diagnosis(self, radar_id: str) -> list[DiagnosisItem]:
        """List live diagnosis entries (not implemented)."""
        raise NotImplementedError

    def list_attachments(self, radar_id: str) -> list[AttachmentMeta]:
        """List live attachments (not implemented)."""
        raise NotImplementedError

    def add_diagnosis(
        self,
        radar_id: str,
        text: str,
        *,
        confirm: bool = False,
    ) -> RadarWriteResult:
        """Commit diagnosis when confirmed (not implemented)."""
        raise NotImplementedError

    def upload_attachment(
        self,
        radar_id: str,
        path: Path,
        *,
        confirm: bool = False,
        as_picture: bool = False,
    ) -> RadarWriteResult:
        """Upload attachment when confirmed (not implemented)."""
        raise NotImplementedError
