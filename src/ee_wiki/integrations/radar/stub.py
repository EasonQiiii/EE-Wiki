"""Offline stub Radar backend for FA session development and tests.

Canonical fixture is a faithful offline copy of lab sample
``rdar://problem/101493937`` (Scarif flash erase / standby), captured from
``radarclient`` in ``radar.log``. Stub never calls Apple services.
"""

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

# Lab sample id from radar.log — preferred smoke / Open WebUI check-in target.
CANONICAL_STUB_RADAR_ID = "101493937"

_REAL_COMPONENT_NAME = "B5xx HW Build FATP"
_REAL_COMPONENT_VERSION = "P0"
_REAL_COMPONENT_ID = 1457538


def _history(text: str, *, added_by: str) -> DiagnosisItem:
    return DiagnosisItem(
        text=f"<Radar History>\n{text}\n</Radar History>",
        added_by=added_by,
        entry_type="history",
    )


def _scarif_flash_erase_problem(
    rid: str,
    *,
    component_name: str,
    component_version: str,
    component_id: int | None = None,
) -> RadarProblem:
    """Build the Scarif flash-erase ticket snapshot from radar.log.

    Narrative, diagnosis thread, and attachment names match
    ``rdar://101493937``. ``component_*`` may be overridden for EE-Wiki scope
    tests; the canonical id uses the real B5xx / P0 component by default.
    """
    eason = "Eason Qi (eason.qi@byd.com)"
    fei = "Fei Gao (f_gao@apple.com)"
    kevin = "Kevin Abas (kabas@apple.com)"

    return RadarProblem(
        radar_id=rid,
        title="Ruby,P0,Scarif flash erase issue",
        state="Verify",
        substate="",
        component=RadarComponentRef(
            id=component_id if component_id is not None else _REAL_COMPONENT_ID,
            name=component_name,
            version=component_version,
        ),
        found_in_builds=(component_version,),
        configuration_summary=(
            f"Ruby / Scarif FATP; component {component_name} {component_version}"
        ),
        assignee="Fei Gao (f_gao@apple.com)",
        priority="3",
        description=(
            DescriptionItem(
                text=(
                    "Summary:\n"
                    "This rdar is for the Scarif flash cannot erase fully"
                ),
                added_by=eason,
            ),
        ),
        diagnosis=(
            _history("New information added to Problem diagnosis.", added_by=eason),
            _history(
                "1 file(s) added to Attachments.\n"
                "1 file(s) added to Attachments.",
                added_by=eason,
            ),
            DiagnosisItem(
                text=(
                    "The external flash cannot been erased fully"
                    "(turn to all `0xff`) after issue command "
                    "`imu -d gyro save xxx`.\n\n"
                    "Check attachment  "
                    "`Flash not erased fully after imu -d gyro save xxx.png` "
                    "for quick compare review.\n\n"
                    "Raw fail log please check "
                    "`H9H242500041JJY1A_save_100_NG.log` and "
                    "`H9H242500041JJY1A_save_500_NG.log`."
                ),
                added_by=eason,
                entry_type="user",
            ),
            _history(
                "Picture 'Flash not erased fully after`imu -d gyro save xxx`.png' "
                "added.",
                added_by=eason,
            ),
            _history(
                'Assignee was changed from "Fei Gao" to "Kevin Abas".',
                added_by=fei,
            ),
            _history(
                "Added Relation: this problem is related to "
                "rdar://problem/99757923.",
                added_by=fei,
            ),
            _history("New information added to Problem diagnosis.", added_by=kevin),
            _history(
                'Assignee was changed from "Kevin Abas" to "Fei Gao".',
                added_by=kevin,
            ),
            DiagnosisItem(
                text=(
                    "Hi Eason,\n\n"
                    "It looks like system is entering standby during test\n\n"
                    "\n"
                    "  1003f0 :ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff "
                    "| ................\n"
                    "--------------------------------------------------------"
                    "------------------------\n"
                    "> Enter Standby                                          "
                    "<——————————————————————————HERE\n"
                    "MSG:  IMUProcessor State: Extended Idle\n\n"
                    "> imu -d gyro start\n"
                    "- Start Streaming ---------------------------------------"
                    "-----------------------\n"
                    "Success!\n"
                    "--------------------------------------------------------"
                    "------------------------\n"
                    "> imu -d gyro print 1\n"
                    "- Print Enable ------------------------------------------"
                    "-----------------------\n"
                    "Print set to 1\n"
                    "----------------------------------------------------"
                    "MSG: PrintData, 94: Gyro  66 temperature (raw) 442\n"
                    "MSG: PrintData, 43: Gyro  66 accel (raw) "
                    "[    6, -2003,   17]\n\n"
                    "\n\n"
                    "Before running any test can you please try "
                    "‘pwr_state set factory’ \n"
                    "Then continue with full test."
                ),
                added_by=kevin,
                entry_type="user",
            ),
            _history("New information added to Problem diagnosis.", added_by=eason),
            _history(
                "1 file(s) added to Attachments.\n"
                "1 file(s) added to Attachments.",
                added_by=eason,
            ),
            DiagnosisItem(
                text=(
                    "Ran total 40x times same sequence with 2x MLBs with "
                    "setting `pwr_state set factory` .\n\n"
                    "No previous failure found, will keep monitoring this "
                    "issue.\n\n"
                    "Detail pass log please see "
                    "`sensor_flash_test_PASS_with_MLB_1&2.log`"
                ),
                added_by=eason,
                entry_type="user",
            ),
            _history(
                'Substate was changed from "Screen" to "".\n'
                'Resolution was changed from "Unresolved" to '
                '"Process Changed".\n'
                'Resolver was changed from null to "Fei Gao".\n'
                'State was changed from "Analyze" to "Verify".\n'
                "Read by assignee check box was checked.",
                added_by=fei,
            ),
        ),
        attachments=(
            AttachmentMeta(
                file_name="H9H242500041JJY1A_save_100_NG.log",
                kind="attachment",
                added_by=eason,
            ),
            AttachmentMeta(
                file_name="H9H242500041JJY1A_save_500_NG.log",
                kind="attachment",
                added_by=eason,
            ),
            AttachmentMeta(
                file_name="sensor_flash_test_PASS_with_MLB_1.log",
                kind="attachment",
                added_by=eason,
            ),
            AttachmentMeta(
                file_name="sensor_flash_test_PASS_with_MLB_2.log",
                kind="attachment",
                added_by=eason,
            ),
            AttachmentMeta(
                file_name=(
                    "Flash not erased fully after imu -d gyro save xxx.png"
                ),
                kind="picture",
                added_by=eason,
            ),
        ),
    )


def _sample_problem(
    rid: str,
    *,
    component_name: str,
    component_version: str,
) -> RadarProblem:
    """Return the Scarif fixture; canonical id keeps real B5xx/P0 component."""
    if rid == CANONICAL_STUB_RADAR_ID:
        return _scarif_flash_erase_problem(
            rid,
            component_name=_REAL_COMPONENT_NAME,
            component_version=_REAL_COMPONENT_VERSION,
            component_id=_REAL_COMPONENT_ID,
        )
    # Other ids reuse the same narrative so unit tests / casual ids still work;
    # component comes from config for EE-Wiki scope aliasing.
    return _scarif_flash_erase_problem(
        rid,
        component_name=component_name,
        component_version=component_version,
        component_id=1,
    )


class StubRadarBackend:
    """In-memory Radar stand-in that never calls Apple services."""

    def __init__(
        self,
        *,
        default_component_name: str = _REAL_COMPONENT_NAME,
        default_component_version: str = _REAL_COMPONENT_VERSION,
    ) -> None:
        """Initialize the stub store.

        Args:
            default_component_name: Component name for non-canonical radar ids.
            default_component_version: Component version / build for those ids.
        """
        self._default_component_name = default_component_name
        self._default_component_version = default_component_version
        self._problems: dict[str, RadarProblem] = {}
        self._diagnosis: dict[str, list[DiagnosisItem]] = {}
        self._attachments: dict[str, list[AttachmentMeta]] = {}

    def get_problem(self, radar_id: str) -> RadarProblem:
        """Return the Scarif fixture (or a previously mutated copy)."""
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
            logger.info(
                "Stub Radar seeded rdar://%s title=%r component=%s|%s",
                rid,
                sample.title,
                sample.component.name if sample.component else "?",
                sample.component.version if sample.component else "?",
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

    def download_attachment(
        self,
        radar_id: str,
        file_name: str,
        *,
        dest_path: Path,
    ) -> Path:
        """Write a synthetic stub file for download-link UX (not live bytes)."""
        rid = normalize_radar_id(radar_id)
        self.get_problem(rid)
        names = {a.file_name for a in self._attachments.get(rid, [])}
        if file_name not in names:
            from ee_wiki.common.errors import IntegrationError

            raise IntegrationError(
                f"Attachment {file_name!r} not found on stub rdar://{rid}"
            )
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        body = (
            f"# EE-Wiki stub Radar attachment\n"
            f"# rdar://{rid}\n"
            f"# file: {file_name}\n"
            f"# NOTE: placeholder for /v1/cache download UX; not live Radar bytes.\n"
            f"PASS: flash erase sequence completed\n"
            f"PASS: no standby under pwr_state set factory\n"
        ).encode()
        dest_path.write_bytes(body)
        logger.info("Stub Radar attachment written %s -> %s", file_name, dest_path)
        return dest_path

    def download_picture(
        self,
        radar_id: str,
        file_name: str,
        *,
        dest_path: Path,
    ) -> Path:
        """Write a synthetic stub picture for download-link UX (not live bytes)."""
        rid = normalize_radar_id(radar_id)
        self.get_problem(rid)
        names = {a.file_name for a in self._attachments.get(rid, [])}
        if file_name not in names:
            from ee_wiki.common.errors import IntegrationError

            raise IntegrationError(
                f"Picture {file_name!r} not found on stub rdar://{rid}"
            )
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        body = (
            f"# EE-Wiki stub Radar picture\n"
            f"# rdar://{rid}\n"
            f"# file: {file_name}\n"
            f"# NOTE: placeholder for /v1/cache download UX; not live Radar bytes.\n"
        ).encode()
        dest_path.write_bytes(body)
        logger.info("Stub Radar picture written %s -> %s", file_name, dest_path)
        return dest_path

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
