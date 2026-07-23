"""FA check-in evidence priority: Radar face first, Flames last (ADR 0013).

These tests pin the reorder in ``start_fa_checkin``:

1. The LLM reads the Radar face and selects strong-related attachments; only
   those are downloaded on demand — unrelated pictures are never fetched.
2. A file the FA notes name but that is not attached becomes ``unresolved``
   and triggers no download.
3. When the face yields fail items, Flames is never consulted (lowest tier).
4. With no LLM we degrade to caching the corpus + listing the inventory and
   asking the user to paste — no batch download.
5. Flames is still the fallback when the face has nothing usable.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ee_wiki.common.config import load_config
from ee_wiki.integrations import session as session_mod
from ee_wiki.integrations.radar import attachments as attachments_mod
from ee_wiki.protocols.flames import FailItem, FailItemsResult, FlamesUnitRef
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DescriptionItem,
    DiagnosisItem,
    RadarComponentRef,
    RadarProblem,
)


class _FakeRadar:
    """Radar backend with a controllable problem + download tracking."""

    def __init__(self, problem: RadarProblem) -> None:
        self.problem = problem
        self.downloads: list[tuple[str, str]] = []

    def get_problem(self, radar_id: str) -> RadarProblem:
        return self.problem

    def download_attachment(
        self, radar_id: str, file_name: str, *, dest_path: Path
    ) -> Path:
        self.downloads.append(("attachment", file_name))
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(
            "boot ok\nFAIL: flash erase incomplete at block 0x1003f0\nPASS: idle\n",
            encoding="utf-8",
        )
        return dest_path

    def download_picture(
        self, radar_id: str, file_name: str, *, dest_path: Path
    ) -> Path:
        self.downloads.append(("picture", file_name))
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"\x89PNG\r\n stub")
        return dest_path


class _FakeFlames:
    """Flames backend that records whether it was consulted."""

    def __init__(self, result: FailItemsResult) -> None:
        self.result = result
        self.called = False

    def collect_fail_items(
        self, radar_id: str, *, serial: str | None = None, cache_dir: Path
    ) -> FailItemsResult:
        self.called = True
        return self.result


class _RouteLLM:
    """Mock LLM returning face-briefing vs corpus-fails by prompt content."""

    generate_stream = None

    def __init__(self, *, background: str, fails: str) -> None:
        self._background = background
        self._fails = fails
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, max_new_tokens: int) -> str:
        self.prompts.append(prompt)
        if "## Briefing" in prompt:
            return self._background
        return self._fails


def _make_problem(attachments: tuple[AttachmentMeta, ...], *, diagnosis: str) -> RadarProblem:
    return RadarProblem(
        radar_id="700001",
        title="Ruby,P0,Scarif flash erase issue",
        state="Analyze",
        substate="",
        component=RadarComponentRef(id=1, name="ipad/logan", version="P1"),
        description=(
            DescriptionItem(
                text="FQT station; Scarif DUT; flash erase after imu save.",
                added_by="eng",
            ),
        ),
        diagnosis=(
            DiagnosisItem(text=diagnosis, added_by="eng", entry_type="user"),
        ),
        attachments=attachments,
    )


def _base_config(repo_root: Path, tmp_path: Path, *, flames_backend: str = "stub"):
    config = load_config(repo_root=repo_root)
    return replace(
        config,
        cache_dir=tmp_path / "cache",
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend=flames_backend),
        ),
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )


def _patch_backends(monkeypatch, radar: _FakeRadar, flames: _FakeFlames) -> None:
    monkeypatch.setattr(session_mod, "build_radar_backend", lambda cfg: radar)
    monkeypatch.setattr(session_mod, "build_flames_backend", lambda cfg: flames)
    # materialize_attachment builds its own radar via the attachments module.
    monkeypatch.setattr(attachments_mod, "build_radar_backend", lambda cfg: radar)


def _stub_flames_result() -> FailItemsResult:
    return FailItemsResult(
        unit=FlamesUnitRef(unit_id="u", serial=None, radar_id="700001"),
        records=(),
        fail_items=(
            FailItem(message="flames-only error one", station="FCT"),
            FailItem(message="flames-only error two", station="FCT"),
        ),
        cached_logs=(),
        source="stub",
        needs_user_input=False,
    )


def test_related_log_downloaded_picture_untouched(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    problem = _make_problem(
        (
            AttachmentMeta(file_name="foo.log", kind="attachment"),
            AttachmentMeta(file_name="photo.png", kind="picture"),
        ),
        diagnosis="Raw fail log please check `foo.log` for the erase failure.",
    )
    radar = _FakeRadar(problem)
    flames = _FakeFlames(_stub_flames_result())
    _patch_backends(monkeypatch, radar, flames)
    config = _base_config(repo_root, tmp_path)

    statuses: list[str] = []
    monkeypatch.setattr(
        "ee_wiki.api.stream_status_context.push_stream_status",
        lambda description: statuses.append(description),
    )

    llm = _RouteLLM(
        background=(
            "BACKGROUND: FQT station, Scarif DUT flash erase test.\n"
            "TRUE_FAIL_HINT: flash not erased fully after imu save\n"
            "FA_NOTES:\n- please check foo.log for the erase failure\n"
            "RELATED_FILES:\n- foo.log\n"
            "UNRESOLVED: none\n"
        ),
        fails="FAIL_ITEMS:\n- flash not erased fully after imu save\n",
    )

    result = session_mod.start_fa_checkin(config, "700001", llm=llm)

    # Only the LLM-selected log is fetched; the unrelated picture is untouched.
    assert ("attachment", "foo.log") in radar.downloads
    assert ("picture", "photo.png") not in radar.downloads
    # Face evidence wins → Flames never consulted.
    assert flames.called is False
    assert result.fail_items.source == "radar"
    sources = {it.source for it in result.fail_items.fail_items}
    assert "radar_attachment" in sources  # FAIL line read from foo.log body
    assert "foo.log" in result.summary_markdown
    # Check-in face read + related download + fail extract + AI summary statuses.
    from ee_wiki.api.stream_status import (
        FA_AI_SUMMARY_STATUS,
        FA_ANALYZE_STATUS,
        FA_DOWNLOAD_STATUS,
        FA_EXTRACT_FAILS_STATUS,
    )

    assert FA_ANALYZE_STATUS in statuses
    assert FA_DOWNLOAD_STATUS.format(done=1, total=1) in statuses
    assert FA_EXTRACT_FAILS_STATUS in statuses
    assert FA_AI_SUMMARY_STATUS in statuses
    # Empty Evidence files wording must not nudge Flames (residual #4).
    assert "Flames/Radar corpus" not in result.summary_markdown


def test_evidence_files_empty_copy_avoids_flames_nudge(
    repo_root: Path, tmp_path: Path
) -> None:
    """Empty Evidence files copy must not mention Flames (residual #4)."""
    from ee_wiki.integrations.scope import ScopeResolution

    config = _base_config(repo_root, tmp_path, flames_backend="manual")
    problem = _make_problem(
        (AttachmentMeta(file_name="a.log", kind="attachment"),),
        diagnosis="Monitoring only.",
    )
    fails = FailItemsResult(
        unit=FlamesUnitRef(unit_id="u", serial=None, radar_id="700001"),
        records=(),
        fail_items=(
            FailItem(
                message="face fail",
                station="radar",
                source="radar_title",
            ),
        ),
        cached_logs=(),
        source="radar",
        needs_user_input=False,
    )
    scope = ScopeResolution(
        product="ipad",
        project="logan",
        build="p1",
        source="component_alias",
        confidence="high",
    )
    result = session_mod._build_checkin_result(config, problem, scope, fails)
    # V2 template: Attachments + Fail items, no separate "Evidence files" block.
    assert "### Attachments" in result.summary_markdown
    assert "### Fail items" in result.summary_markdown
    assert "face fail" in result.summary_markdown
    assert "Flames" not in result.summary_markdown
    assert "Flames/Radar corpus" not in result.summary_markdown
    assert "_(src:" not in result.summary_markdown
    assert "### Radar attachments" not in result.summary_markdown
    assert "Evidence files" not in result.summary_markdown
    assert "强关联证据" not in result.summary_markdown
    assert "Background" not in result.summary_markdown


def test_named_but_missing_file_becomes_unresolved(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    problem = _make_problem(
        (AttachmentMeta(file_name="present.log", kind="attachment"),),
        diagnosis="Raw fail log please check `bar.log` (not uploaded).",
    )
    radar = _FakeRadar(problem)
    flames = _FakeFlames(_stub_flames_result())
    _patch_backends(monkeypatch, radar, flames)
    config = _base_config(repo_root, tmp_path)

    llm = _RouteLLM(
        background=(
            "BACKGROUND: erase failure investigation.\n"
            "TRUE_FAIL_HINT: erase incomplete\n"
            "FA_NOTES:\n- see bar.log\n"
            "RELATED_FILES:\n- bar.log\n"
            "UNRESOLVED: none\n"
        ),
        fails="FAIL_ITEMS: none\n",
    )

    result = session_mod.start_fa_checkin(config, "700001", llm=llm)

    # bar.log is not attached → never downloaded. The unresolved-evidence
    # section was removed in the V2 template, but the name still surfaces in
    # the Diagnosis body, and the file is never fetched.
    assert radar.downloads == []
    assert "bar.log" in result.summary_markdown
    # No corpus fails + no attachment fails → true-fail hint carries the item.
    assert any(
        it.source == "radar_title" for it in result.fail_items.fail_items
    )


def test_flames_not_called_when_face_has_fails(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    problem = _make_problem(
        (AttachmentMeta(file_name="nope.log", kind="attachment"),),
        diagnosis="Standby entered during test; see notes.",
    )
    radar = _FakeRadar(problem)
    flames = _FakeFlames(_stub_flames_result())
    _patch_backends(monkeypatch, radar, flames)
    config = _base_config(repo_root, tmp_path)

    llm = _RouteLLM(
        background=(
            "BACKGROUND: standby regression.\n"
            "TRUE_FAIL_HINT: system enters standby during test\n"
            "FA_NOTES:\n- pwr_state set factory before test\n"
            "RELATED_FILES: none\n"
            "UNRESOLVED: none\n"
        ),
        fails="FAIL_ITEMS:\n- system enters standby during test\n",
    )

    result = session_mod.start_fa_checkin(config, "700001", llm=llm)

    assert flames.called is False
    assert result.fail_items.source == "radar"
    messages = " ".join(it.message for it in result.fail_items.fail_items)
    assert "standby" in messages.lower()
    assert "flames-only" not in messages  # Flames items must not appear


def test_no_llm_degrades_to_paste_without_batch_download(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    problem = _make_problem(
        (
            AttachmentMeta(file_name="a.log", kind="attachment"),
            AttachmentMeta(file_name="b.png", kind="picture"),
        ),
        diagnosis="Raw fail log please check `a.log`.",
    )
    radar = _FakeRadar(problem)
    manual = _FakeFlames(
        FailItemsResult(
            unit=FlamesUnitRef(unit_id="u", serial=None, radar_id="700001"),
            records=(),
            fail_items=(),
            cached_logs=(),
            source="manual",
            needs_user_input=True,
            user_prompt="paste log",
        )
    )
    _patch_backends(monkeypatch, radar, manual)
    config = _base_config(repo_root, tmp_path, flames_backend="manual")

    result = session_mod.start_fa_checkin(config, "700001", llm=None)

    # No LLM → no strong-related selection → nothing downloaded up front.
    assert radar.downloads == []
    assert result.awaiting_user_evidence is True
    assert "Need test evidence" in result.summary_markdown
    # Inventory still lists every attachment (Problem 1/5 behavior retained).
    assert "a.log" in result.summary_markdown
    assert "b.png" in result.summary_markdown
    # Corpus is cached for the paste branch.
    assert (tmp_path / "cache/fa/700001/radar_corpus.txt").is_file()


def test_flames_is_fallback_when_face_empty(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    problem = _make_problem(
        (AttachmentMeta(file_name="x.log", kind="attachment"),),
        diagnosis="Monitoring only; no remaining failure.",
    )
    radar = _FakeRadar(problem)
    flames = _FakeFlames(_stub_flames_result())
    _patch_backends(monkeypatch, radar, flames)
    config = _base_config(repo_root, tmp_path)

    llm = _RouteLLM(
        background=(
            "BACKGROUND: monitoring after fix.\n"
            "TRUE_FAIL_HINT: none\n"
            "FA_NOTES: none\n"
            "RELATED_FILES: none\n"
            "UNRESOLVED: none\n"
        ),
        fails="FAIL_ITEMS: none\n",
    )

    result = session_mod.start_fa_checkin(config, "700001", llm=llm)

    # Face carried no fail → Flames consulted as the lowest fallback.
    assert flames.called is True
    assert result.awaiting_user_evidence is False
    assert len(result.fail_items.fail_items) == 2
    assert all(
        it.source == "flames" for it in result.fail_items.fail_items
    )


def test_golden_stub_canonical_selects_ng_logs(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Golden: canonical stub diagnosis names NG logs → LLM selects them."""
    from ee_wiki.integrations.radar.stub import StubRadarBackend

    class _TrackingStub(StubRadarBackend):
        def __init__(self) -> None:
            super().__init__()
            self.downloads: list[tuple[str, str]] = []

        def download_attachment(self, radar_id, file_name, *, dest_path):
            self.downloads.append(("attachment", file_name))
            return super().download_attachment(
                radar_id, file_name, dest_path=dest_path
            )

        def download_picture(self, radar_id, file_name, *, dest_path):
            self.downloads.append(("picture", file_name))
            return super().download_picture(
                radar_id, file_name, dest_path=dest_path
            )

    radar = _TrackingStub()
    flames = _FakeFlames(_stub_flames_result())
    _patch_backends(monkeypatch, radar, flames)
    config = _base_config(repo_root, tmp_path)

    llm = _RouteLLM(
        background=(
            "BACKGROUND: Scarif flash erase FATP failure.\n"
            "TRUE_FAIL_HINT: external flash cannot be erased fully\n"
            "FA_NOTES:\n- check the two save NG logs\n"
            "RELATED_FILES:\n"
            "- H9H242500041JJY1A_save_100_NG.log\n"
            "- H9H242500041JJY1A_save_500_NG.log\n"
            "UNRESOLVED: none\n"
        ),
        fails=(
            "FAIL_ITEMS:\n- external flash cannot be erased fully after imu save\n"
        ),
    )

    result = session_mod.start_fa_checkin(config, "101493937", llm=llm)

    fetched = {name for _kind, name in radar.downloads}
    assert "H9H242500041JJY1A_save_100_NG.log" in fetched
    assert "H9H242500041JJY1A_save_500_NG.log" in fetched
    # The picture the diagnosis mentions is not in RELATED_FILES → not fetched.
    assert not any(name.endswith(".png") for name in fetched)
    assert flames.called is False
    assert result.fail_items.source == "radar"


def test_v2_checkin_face_email_fold_and_no_legacy_sections(
    repo_root: Path, tmp_path: Path
) -> None:
    """V2 face: email-only authors, folds, AI Summary, no legacy blocks."""
    from ee_wiki.integrations.scope import ScopeResolution

    config = _base_config(repo_root, tmp_path, flames_backend="manual")
    problem = RadarProblem(
        radar_id="182787079",
        title="IMU Gyro Average Y out of limit",
        state="Analyze",
        substate="Screen",
        component=RadarComponentRef(id=1, name="B632 Rel FA Tracker", version="FVB"),
        description=(
            DescriptionItem(
                text="Unit SN: G32NC7GJ9N\nConfig: FBHAY-R1B-LD\nFail Rate: Pending",
                added_by="eng",
            ),
        ),
        diagnosis=(
            DiagnosisItem(
                text="Unit send to EE FA 7/21.",
                added_by="<CommentAuthor wang.jin92@byd.com Elwen Wang>",
                entry_type="user",
            ),
            DiagnosisItem(
                text="Bench Cal_LPNM 3x reproduce.",
                added_by="wang.baofu@byd.com Wang Baofu",
                entry_type="user",
            ),
            DiagnosisItem(
                text="Gentle knock still OOL.",
                added_by="naixin_song@apple.com",
                entry_type="user",
            ),
            DiagnosisItem(
                text="Next step: CT scan.",
                added_by="wang.baofu@byd.com",
                entry_type="user",
            ),
        ),
        attachments=tuple(
            AttachmentMeta(file_name=name, kind="attachment")
            for name in (
                "Cal_LPNM_1.log",
                "Cal_LPNM_2.log",
                "Cal_LPNM_3.log",
                "gentle_knock.zip",
                "mst_fail.zip",
            )
        ),
    )
    fails = FailItemsResult(
        unit=FlamesUnitRef(unit_id="u", serial=None, radar_id="182787079"),
        records=(),
        fail_items=(
            FailItem(
                message="Gyro Y average out of limit",
                station="radar",
                source="radar_text",
            ),
        ),
        cached_logs=(),
        source="radar",
        needs_user_input=False,
    )
    scope = ScopeResolution(
        product="pencil",
        project="mocalamari",
        build="fvb",
        source="component_alias",
        confidence="high",
    )
    md = session_mod._format_checkin_markdown(
        config,
        problem,
        scope,
        fails,
        ai_summary="跌落后 IMU 校准 Y 轴超限；bench 已复现；下一步 CT scan。",
    )

    assert md.startswith("## FA check-in — rdar://182787079")
    assert "**Title:**" in md
    assert "**Component:** B632 Rel FA Tracker | FVB" in md
    assert "### Fail items" in md
    assert "- [radar] Gyro Y average out of limit" in md
    assert "_(src:" not in md
    assert "### Description" in md
    assert "> Unit SN: G32NC7GJ9N" in md
    assert "展开完整 Description" in md
    assert "### Diagnosis" in md
    assert "**wang.jin92@byd.com:**" in md
    assert "Elwen Wang" not in md
    assert "CommentAuthor" not in md
    assert "展开其余 1 条 diagnosis" in md
    assert "### Attachments" in md
    assert "展开其余 3 个附件" in md
    assert "### AI Summary" in md
    assert "下一步 CT scan" in md

    for banned in (
        "强关联证据",
        "Evidence files",
        "Background",
        "最突出",
        "FA notes",
        "True-fail",
        "票面",
        "Radar 票",
        "EE-Wiki scope",
        "Evidence source",
        "### Radar attachments",
    ):
        assert banned not in md, banned


def test_author_email_strips_comment_author_wrapper() -> None:
    assert (
        session_mod._author_email(
            "<CommentAuthor wang.jin92@byd.com Elwen Wang>"
        )
        == "wang.jin92@byd.com"
    )
    assert (
        session_mod._author_email("wang.baofu@byd.com Wang Baofu")
        == "wang.baofu@byd.com"
    )
    assert session_mod._author_email("") == "—"
    assert session_mod._author_email("lab-user") == "lab-user"
