"""Offline stub Radar backend for FA session development and tests."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DiagnosisItem,
    RadarComponentRef,
    RadarProblem,
    RadarWriteResult,
)

logger = get_logger(__name__)


class StubRadarBackend:
    """In-memory Radar stand-in that never calls Apple services."""

    def __init__(
        self,
        *,
        default_component_name: str = "demo_product",
        default_component_version: str = "P1",
    ) -> None:
        """Initialize the stub store.

        Args:
            default_component_name: Synthetic component name for new problems.
            default_component_version: Synthetic component version / build.
        """
        self._default_component_name = default_component_name
        self._default_component_version = default_component_version
        self._problems: dict[str, RadarProblem] = {}
        self._diagnosis: dict[str, list[DiagnosisItem]] = {}
        self._attachments: dict[str, list[AttachmentMeta]] = {}

    def get_problem(self, radar_id: str) -> RadarProblem:
        """Return a synthetic or previously mutated problem snapshot."""
        rid = normalize_radar_id(radar_id)
        if rid not in self._problems:
            self._problems[rid] = RadarProblem(
                radar_id=rid,
                title=f"[stub] FA check-in {rid}",
                state="Analyze",
                substate="Investigate",
                component=RadarComponentRef(
                    id=1,
                    name=self._default_component_name,
                    version=self._default_component_version,
                ),
                found_in_builds=(self._default_component_version,),
                configuration_summary=(
                    f"stub unit for radar {rid}; build "
                    f"{self._default_component_version}"
                ),
                assignee="stub.user@example.com",
                priority="3",
                diagnosis=tuple(self._diagnosis.get(rid, [])),
                attachments=tuple(self._attachments.get(rid, [])),
            )
        problem = self._problems[rid]
        return RadarProblem(
            radar_id=problem.radar_id,
            title=problem.title,
            state=problem.state,
            substate=problem.substate,
            component=problem.component,
            found_in_builds=problem.found_in_builds,
            configuration_summary=problem.configuration_summary,
            assignee=problem.assignee,
            priority=problem.priority,
            diagnosis=tuple(self._diagnosis.get(rid, [])),
            attachments=tuple(self._attachments.get(rid, [])),
        )

    def list_diagnosis(self, radar_id: str) -> list[DiagnosisItem]:
        """List in-memory diagnosis entries."""
        rid = normalize_radar_id(radar_id)
        self.get_problem(rid)
        return list(self._diagnosis.get(rid, []))

    def list_attachments(self, radar_id: str) -> list[AttachmentMeta]:
        """List in-memory attachment metadata."""
        rid = normalize_radar_id(radar_id)
        self.get_problem(rid)
        return list(self._attachments.get(rid, []))

    def add_diagnosis(
        self,
        radar_id: str,
        text: str,
        *,
        confirm: bool = False,
    ) -> RadarWriteResult:
        """Append diagnosis when ``confirm``; otherwise return draft preview."""
        rid = normalize_radar_id(radar_id)
        self.get_problem(rid)
        if not confirm:
            return RadarWriteResult(
                radar_id=rid,
                action="add_diagnosis",
                committed=False,
                detail="Draft only; pass confirm=true to commit",
                draft_preview=text,
            )
        items = self._diagnosis.setdefault(rid, [])
        items.append(DiagnosisItem(text=text, added_by="stub", entry_type="user"))
        logger.info("Stub Radar diagnosis committed for %s", rid)
        return RadarWriteResult(
            radar_id=rid,
            action="add_diagnosis",
            committed=True,
            detail="Stub diagnosis committed",
        )

    def upload_attachment(
        self,
        radar_id: str,
        path: Path,
        *,
        confirm: bool = False,
        as_picture: bool = False,
    ) -> RadarWriteResult:
        """Record a fake attachment when ``confirm``; otherwise draft."""
        rid = normalize_radar_id(radar_id)
        self.get_problem(rid)
        kind = "picture" if as_picture else "attachment"
        name = path.name
        if not confirm:
            return RadarWriteResult(
                radar_id=rid,
                action=f"upload_{kind}",
                committed=False,
                detail="Draft only; pass confirm=true to commit",
                draft_preview=str(path),
            )
        size = path.stat().st_size if path.is_file() else None
        meta = AttachmentMeta(
            file_name=name,
            file_size=size,
            kind=kind,
            added_by="stub",
        )
        self._attachments.setdefault(rid, []).append(meta)
        logger.info("Stub Radar %s uploaded for %s: %s", kind, rid, name)
        return RadarWriteResult(
            radar_id=rid,
            action=f"upload_{kind}",
            committed=True,
            detail=f"Stub {kind} recorded: {name}",
        )
