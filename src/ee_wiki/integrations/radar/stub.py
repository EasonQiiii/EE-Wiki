"""Offline stub Radar backend for FA session development and tests."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DescriptionItem,
    DiagnosisItem,
    RadarComponentRef,
    RadarProblem,
    RadarWriteResult,
)

logger = get_logger(__name__)


def _sample_problem(
    rid: str,
    *,
    component_name: str,
    component_version: str,
) -> RadarProblem:
    """Build a redacted stub shaped like a real radarclient snapshot.

    Based on lab sample rdar://101493937 (flash erase / standby) so offline
    FA check-in can exercise Radar title → description → diagnosis evidence
    without Apple network access.
    """
    return RadarProblem(
        radar_id=rid,
        title=f"[stub] Scarif flash erase issue ({rid})",
        state="Analyze",
        substate="Investigate",
        component=RadarComponentRef(
            id=1,
            name=component_name,
            version=component_version,
        ),
        found_in_builds=(component_version,),
        configuration_summary=(
            f"stub unit for radar {rid}; build {component_version}"
        ),
        assignee="stub.user@example.com",
        priority="3",
        description=(
            DescriptionItem(
                text=(
                    "Summary:\n"
                    "This rdar is for the Scarif flash cannot erase fully"
                ),
                added_by="stub",
            ),
        ),
        diagnosis=(
            DiagnosisItem(
                text=(
                    "The external flash cannot been erased fully"
                    "(turn to all `0xff`) after issue command "
                    "`imu -d gyro save xxx`.\n\n"
                    "Raw fail log please check "
                    "`UNIT_save_100_NG.log` and `UNIT_save_500_NG.log`."
                ),
                added_by="stub",
                entry_type="user",
            ),
            DiagnosisItem(
                text=(
                    "<Radar History>\n"
                    "Assignee was changed.\n"
                    "</Radar History>"
                ),
                added_by="stub",
                entry_type="history",
            ),
            DiagnosisItem(
                text=(
                    "It looks like system is entering standby during test\n\n"
                    "> Enter Standby\n"
                    "MSG:  IMUProcessor State: Extended Idle\n\n"
                    "Before running any test can you please try "
                    "`pwr_state set factory` then continue with full test."
                ),
                added_by="stub",
                entry_type="user",
            ),
        ),
        attachments=(
            AttachmentMeta(file_name="UNIT_save_100_NG.log", kind="attachment"),
            AttachmentMeta(file_name="UNIT_save_500_NG.log", kind="attachment"),
            AttachmentMeta(
                file_name="sensor_flash_test_PASS.log", kind="attachment"
            ),
        ),
    )


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
            sample = _sample_problem(
                rid,
                component_name=self._default_component_name,
                component_version=self._default_component_version,
            )
            self._problems[rid] = sample
            self._diagnosis[rid] = list(sample.diagnosis)
            self._attachments[rid] = list(sample.attachments)
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
            description=problem.description,
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
