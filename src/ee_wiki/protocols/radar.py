"""Abstract interface for Apple Radar access (FA sessions; ADR 0010)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RadarComponentRef:
    """Radar component used for EE-Wiki project/build mapping."""

    id: int | None
    name: str
    version: str


@dataclass(frozen=True)
class DiagnosisItem:
    """One diagnosis entry on a Radar problem."""

    text: str
    added_by: str | None = None
    added_at: datetime | None = None
    entry_type: str = "user"  # user | history | unknown


@dataclass(frozen=True)
class AttachmentMeta:
    """Metadata for a Radar attachment or picture."""

    file_name: str
    file_size: int | None = None
    kind: str = "attachment"  # attachment | picture
    added_by: str | None = None
    added_at: datetime | None = None


@dataclass(frozen=True)
class RadarProblem:
    """Normalized Radar problem snapshot for FA sessions."""

    radar_id: str
    title: str
    state: str | None = None
    substate: str | None = None
    component: RadarComponentRef | None = None
    found_in_builds: tuple[str, ...] = ()
    configuration_summary: str | None = None
    assignee: str | None = None
    priority: str | None = None
    diagnosis: tuple[DiagnosisItem, ...] = ()
    attachments: tuple[AttachmentMeta, ...] = ()


@dataclass(frozen=True)
class RadarWriteResult:
    """Outcome of a confirm-gated Radar mutation."""

    radar_id: str
    action: str
    committed: bool
    detail: str = ""
    draft_preview: str | None = None


class RadarBackend(Protocol):
    """Read/write Radar for FA sessions.

    Mutating methods must no-op or return a draft when ``confirm`` is false;
    they must call the live API only when ``confirm`` is true.
    """

    def get_problem(self, radar_id: str) -> RadarProblem:
        """Fetch a Radar problem snapshot.

        Args:
            radar_id: Numeric Radar / rdar id (digits only or ``rdar://`` form).

        Returns:
            Normalized problem including component and recent diagnosis when available.
        """
        ...

    def list_diagnosis(self, radar_id: str) -> list[DiagnosisItem]:
        """List diagnosis entries for ``radar_id``."""
        ...

    def list_attachments(self, radar_id: str) -> list[AttachmentMeta]:
        """List attachment and picture metadata for ``radar_id``."""
        ...

    def add_diagnosis(
        self,
        radar_id: str,
        text: str,
        *,
        confirm: bool = False,
    ) -> RadarWriteResult:
        """Append a diagnosis entry.

        Args:
            radar_id: Target problem id.
            text: Diagnosis body to append.
            confirm: When false, return draft only; when true, commit to Radar.

        Returns:
            Write result indicating whether the change was committed.
        """
        ...

    def upload_attachment(
        self,
        radar_id: str,
        path: Path,
        *,
        confirm: bool = False,
        as_picture: bool = False,
    ) -> RadarWriteResult:
        """Upload a local file as a Radar attachment or picture.

        Args:
            radar_id: Target problem id.
            path: Local file to upload.
            confirm: When false, return draft only; when true, commit upload.
            as_picture: When true, upload via pictures collection.

        Returns:
            Write result indicating whether the upload was committed.
        """
        ...


@dataclass
class RadarScopeHint:
    """Optional extras when mapping Radar → EE-Wiki scope."""

    found_in_builds: tuple[str, ...] = field(default_factory=tuple)
    configuration_summary: str | None = None
