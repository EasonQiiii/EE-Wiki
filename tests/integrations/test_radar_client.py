"""Tests for radarclient → RadarProblem mapping (no Apple network)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ee_wiki.integrations.radar.client import RadarclientBackend
from ee_wiki.integrations.radar.map_problem import map_radar_problem
from ee_wiki.protocols.radar import RadarWriteResult


def test_map_problem_from_lab_shaped_objects() -> None:
    raw = SimpleNamespace(
        id=101493937,
        title="Ruby,P0,Scarif flash erase issue",
        state="Analyze",
        substate="Investigate",
        component={"id": 1457538, "name": "B5xx HW Build FATP", "version": "P0"},
        configurationSummary="stub config",
        assignee="stub.user@example.com",
        priority="3",
        foundInBuild="P0",
        description=SimpleNamespace(
            items=lambda: [
                SimpleNamespace(
                    text="Summary:\nThis rdar is for the Scarif flash cannot erase fully",
                    addedBy="eason",
                )
            ]
        ),
        diagnosis=SimpleNamespace(
            items=lambda: [
                SimpleNamespace(
                    text=(
                        "<Radar History>\nNew information added.\n</Radar History>"
                    ),
                    addedBy="system",
                ),
                SimpleNamespace(
                    text=(
                        "The external flash cannot been erased fully after "
                        "`imu -d gyro save xxx`."
                    ),
                    addedBy="eason",
                ),
            ]
        ),
        attachments=SimpleNamespace(
            items=lambda: [
                SimpleNamespace(fileName="UNIT_save_100_NG.log", fileSize=12),
            ]
        ),
        pictures=SimpleNamespace(items=lambda: []),
    )

    problem = map_radar_problem(raw, radar_id="101493937")
    assert problem.radar_id == "101493937"
    assert "Scarif" in problem.title
    assert problem.component is not None
    assert problem.component.name == "B5xx HW Build FATP"
    assert problem.component.version == "P0"
    assert len(problem.description) == 1
    assert "cannot erase fully" in problem.description[0].text
    assert len(problem.diagnosis) == 2
    assert problem.diagnosis[0].entry_type == "history"
    assert problem.diagnosis[1].entry_type == "user"
    assert problem.attachments[0].file_name == "UNIT_save_100_NG.log"


def test_radarclient_backend_get_problem_uses_injected_client() -> None:
    raw = SimpleNamespace(
        id=42424242,
        title="demo",
        state="Analyze",
        substate=None,
        component=None,
        description=SimpleNamespace(items=lambda: []),
        diagnosis=SimpleNamespace(items=lambda: []),
        attachments=SimpleNamespace(items=lambda: []),
        pictures=SimpleNamespace(items=lambda: []),
        foundInBuild=None,
        configurationSummary=None,
        assignee=None,
        priority=None,
    )
    client = MagicMock()
    client.radar_for_id.return_value = raw
    backend = RadarclientBackend(client=client)
    problem = backend.get_problem("rdar://42424242")
    assert problem.radar_id == "42424242"
    assert problem.title == "demo"
    client.radar_for_id.assert_called()


def test_add_diagnosis_draft_without_confirm() -> None:
    backend = RadarclientBackend(client=MagicMock())
    result = backend.add_diagnosis("999001", "note", confirm=False)
    assert isinstance(result, RadarWriteResult)
    assert result.committed is False
    assert result.draft_preview == "note"


def test_radar_for_id_retries_timeout_then_succeeds(monkeypatch) -> None:
    """First IdMS timeout is retried; second attempt returns the problem."""
    from urllib.error import URLError

    raw = SimpleNamespace(
        id=182787079,
        title="demo timeout recover",
        state="Analyze",
        substate=None,
        component=None,
        description=SimpleNamespace(items=lambda: []),
        diagnosis=SimpleNamespace(items=lambda: []),
        attachments=SimpleNamespace(items=lambda: []),
        pictures=SimpleNamespace(items=lambda: []),
        foundInBuild=None,
        configurationSummary=None,
        assignee=None,
        priority=None,
    )
    client = MagicMock()
    client.radar_for_id.side_effect = [
        URLError(TimeoutError("timed out")),
        raw,
    ]
    sleeps: list[float] = []
    monkeypatch.setattr(
        "ee_wiki.integrations.radar.client.time.sleep",
        lambda s: sleeps.append(s),
    )
    backend = RadarclientBackend(client=client)
    problem = backend.get_problem("rdar://182787079")
    assert problem.radar_id == "182787079"
    assert client.radar_for_id.call_count == 2
    assert sleeps == [1.0]


def test_radar_for_id_exhausts_timeout_retries(monkeypatch) -> None:
    """All attempts timeout -> IntegrationError whose message maps to 超时."""
    from urllib.error import URLError

    from ee_wiki.common.errors import IntegrationError
    from ee_wiki.integrations.fa_errors import format_fa_error

    client = MagicMock()
    client.radar_for_id.side_effect = URLError(
        OSError(60, "Operation timed out")
    )
    monkeypatch.setattr(
        "ee_wiki.integrations.radar.client.time.sleep",
        lambda _s: None,
    )
    backend = RadarclientBackend(client=client)
    with pytest.raises(IntegrationError) as exc_info:
        backend.get_problem("182787079")
    assert client.radar_for_id.call_count == 3
    msg = format_fa_error(exc_info.value, radar_id="182787079")
    assert "超时" in msg
    assert "Radar 操作失败" not in msg


def test_radar_for_id_does_not_retry_acl() -> None:
    """Permission / ACL failures must fail immediately (no sleep/retry)."""
    from ee_wiki.common.errors import IntegrationError

    client = MagicMock()
    client.radar_for_id.side_effect = RuntimeError(
        "You can contact the Component Owner to get access to this problem."
    )
    backend = RadarclientBackend(client=client)
    with pytest.raises(IntegrationError) as exc_info:
        backend.get_problem("182787079")
    assert client.radar_for_id.call_count == 1
    assert "access to this problem" in str(exc_info.value)
