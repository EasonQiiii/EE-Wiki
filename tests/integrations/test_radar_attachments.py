"""Tests for Radar attachment materialize + download markdown."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.agents.fa_agent import FaAgent
from ee_wiki.common.config import load_config
from ee_wiki.integrations.radar.attachments import (
    format_attachment_content_markdown,
    format_attachment_download_markdown,
    format_attachment_inventory_markdown,
    resolve_requested_attachments,
    wants_attachment_content,
    wants_attachment_download,
    wants_attachment_inventory,
)
from ee_wiki.integrations.radar.client import RadarclientBackend
from ee_wiki.integrations.session import start_fa_checkin
from ee_wiki.protocols.radar import AttachmentMeta, RadarProblem
from ee_wiki.tools.bus import ToolBus


def test_wants_download_phrases() -> None:
    assert wants_attachment_download("我想下载下来看一下")
    assert wants_attachment_download("给我下载链接")
    assert wants_attachment_download("download the log")
    assert not wants_attachment_download("下一步是什么")


def test_wants_content_analysis_phrases() -> None:
    assert wants_attachment_content(
        "你可以分析一下这个sensor_flash_test_PASS_with_MLB_1.log吗"
    )
    assert wants_attachment_content("分析一下这个附件")
    assert not wants_attachment_content("分析一下下一步怎么办")


def test_resolve_mlb_1_and_2_shorthand() -> None:
    available = (
        AttachmentMeta(file_name="sensor_flash_test_PASS_with_MLB_1.log"),
        AttachmentMeta(file_name="sensor_flash_test_PASS_with_MLB_2.log"),
        AttachmentMeta(file_name="H9H242500041JJY1A_save_100_NG.log"),
    )
    hits = resolve_requested_attachments(
        "sensor_flash_test_PASS_with_MLB_1&2.log 我想下载",
        available,
    )
    assert "sensor_flash_test_PASS_with_MLB_1.log" in hits
    assert "sensor_flash_test_PASS_with_MLB_2.log" in hits


def test_checkin_lists_attachments_without_eager_download(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    result = start_fa_checkin(config, "rdar://problem/101493937")
    # Inventory section present, old eager-download block gone.
    assert "### Attachments" in result.summary_markdown
    assert "已缓存" in result.summary_markdown
    assert "待下载" in result.summary_markdown
    assert "sensor_flash_test_PASS_with_MLB_1.log" in result.summary_markdown
    # Problem 1: check-in must NOT pull every file up front (no 56s stall).
    assert "### Radar attachment downloads" not in result.summary_markdown
    assert "_(src:" not in result.summary_markdown
    att_dir = tmp_path / "cache/fa/101493937/attachments"
    assert not (att_dir / "sensor_flash_test_PASS_with_MLB_1.log").is_file()
    # On-demand download still produces a link + materializes the file.
    md = format_attachment_download_markdown(
        config,
        "101493937",
        "我想下载 sensor_flash_test_PASS_with_MLB_1.log",
    )
    assert "/v1/cache/fa/101493937/attachments/" in md
    assert (att_dir / "sensor_flash_test_PASS_with_MLB_1.log").is_file()


def test_picture_download_routes_through_pictures_collection(
    repo_root: Path, tmp_path: Path
) -> None:
    """PNG attachments (kind=picture) must download via the pictures API."""
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    from ee_wiki.integrations.radar.attachments import (
        materialize_attachment,
        summarize_attachment_inventory,
    )

    result = start_fa_checkin(config, "101493937")
    problem = result.problem
    png = next(a for a in problem.attachments if a.kind == "picture")

    # Inventory reports the picture kind + pending (not cached) up front.
    inv, total, cached = summarize_attachment_inventory(config, problem)
    pic_entry = next(e for e in inv if e["name"] == png.file_name)
    assert pic_entry["kind"] == "picture"
    assert pic_entry["cached"] is False

    # materialize with kind="picture" routes to download_picture and writes.
    _path, _rel, url = materialize_attachment(
        config, "101493937", png.file_name, kind="picture"
    )
    assert Path(_path).is_file()
    assert "101493937/attachments/" in url
    # After materialization the inventory flips to cached.
    _, _, cached_after = summarize_attachment_inventory(config, problem)
    assert cached_after == cached + 1


def test_download_reply_for_1_and_2(repo_root: Path, tmp_path: Path) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    md = format_attachment_download_markdown(
        config,
        "101493937",
        "我想下载 sensor_flash_test_PASS_with_MLB_1&2.log",
    )
    assert "### Radar attachment downloads" in md
    assert "MLB_1.log" in md and "MLB_2.log" in md
    assert "http://ee-wiki.test:8080/v1/cache/fa/101493937/attachments/" in md
    assert "没有合并成单个" in md or "两个附件" in md


def test_fa_agent_download_intent_returns_links(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    bus = MagicMock(spec=ToolBus)
    agent = FaAgent(config, bus, llm=None)
    # First bind via check-in style question
    first = agent.handle("rdar://problem/101493937")
    assert "FA check-in" in first.markdown
    from ee_wiki.retrieval.rewrite import ConversationTurn

    history = [ConversationTurn(role="assistant", content=first.markdown)]
    second = agent.handle(
        "我想下载下来看一下 sensor_flash_test_PASS_with_MLB_1&2.log",
        history=history,
    )
    assert "### Radar attachment downloads" in second.markdown
    assert "/v1/cache/" in second.markdown
    assert "### Tool evidence" not in second.markdown


def test_fa_agent_analyze_log_returns_file_bytes(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    bus = MagicMock(spec=ToolBus)
    agent = FaAgent(config, bus, llm=None)
    first = agent.handle("rdar://problem/101493937")
    from ee_wiki.retrieval.rewrite import ConversationTurn

    history = [ConversationTurn(role="assistant", content=first.markdown)]
    second = agent.handle(
        "你可以分析一下这个sensor_flash_test_PASS_with_MLB_1.log吗",
        history=history,
    )
    assert "### Attachment content (from file bytes)" in second.markdown
    assert "PASS-like lines:" in second.markdown
    assert "连续成功运行 40 次" not in second.markdown
    assert "PASS:" in second.markdown


def test_content_markdown_includes_preview(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    md = format_attachment_content_markdown(
        config,
        "101493937",
        "分析 sensor_flash_test_PASS_with_MLB_1.log",
    )
    assert "Attachment content" in md
    assert "sensor_flash_test_PASS_with_MLB_1.log" in md
    assert "```text" in md


def test_analyze_log_numeric_no_passfail_has_interpretation(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Cal_LPNM-style log (numeric / out of limit, NO literal PASS/FAIL) must
    still get an LLM interpretation, and the preview must sit OUTSIDE <details>
    so Open WebUI renders it. The reply must not falsely claim pass/fail."""
    cal_log = (
        "Cal_LPNM unit test start\n"
        "gyro_x_average: 0.012\n"
        "gyro_y_average: -0.042\n"
        "accel_z_average: 1.021\n"
        "out of limit: gyro_y_average below spec\n"
        "test end\n"
    )

    fake_problem = RadarProblem(
        radar_id="182787079",
        title="IMU Cal_LPNM gyro_y out of limit",
        description=(),
        diagnosis=(),
        attachments=(AttachmentMeta(file_name="Cal_LPNM_1.log", kind="attachment"),),
    )
    fake_backend = MagicMock()
    fake_backend.get_problem.return_value = fake_problem
    monkeypatch.setattr(
        "ee_wiki.integrations.radar.attachments.build_radar_backend",
        lambda config: fake_backend,
    )

    def _fake_materialize(config, rid, targets, kind_by_name=None):
        written = []
        for name in targets:
            p = tmp_path / name
            p.write_text(cal_log, encoding="utf-8")
            rel = f"fa/{rid}/attachments/{name}"
            url = f"http://ee-wiki.test:8080/v1/cache/{rel}"
            written.append((name, p, rel, url))
        return written, {}

    monkeypatch.setattr(
        "ee_wiki.integrations.radar.attachments.materialize_named_attachments",
        _fake_materialize,
    )

    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = (
        "1. 文件类型 / 用途：IMU 校准(Cal_LPNM)输出，测陀螺仪三轴平均值。\n"
        "2. 关键指标：`gyro_y_average: -0.042`、`out of limit: gyro_y_average below spec`。\n"
        "3. 未见字面 PASS/FAIL，以下为结构解读：数值均有限，gyro_y 超下界。"
    )

    md = format_attachment_content_markdown(
        load_config(repo_root=repo_root),
        "182787079",
        "分析一下 Cal_LPNM_1.log",
        llm=llm,
        repo_root=repo_root,
    )
    # LLM interpretation layer actually ran and its output is present.
    assert "AI 解读" in md
    assert "未见字面 PASS/FAIL" in md
    # Preview is Open WebUI-safe: no raw <details> dump of the full file.
    assert "**预览（前 40 行）：**" in md
    assert "<details>" not in md
    assert "</details>" not in md
    # The heuristic still reports 0/0 structural counts, but the answer must
    # NOT assert the test "passed" (no fabricated pass/fail verdict).
    assert "测试通过" not in md
    assert "全部通过" not in md


# ---------------------------------------------------------------------------
# Problem 5: inventory intent + cross-collection download fallback
# ---------------------------------------------------------------------------


def test_wants_attachment_inventory_phrases() -> None:
    assert wants_attachment_inventory("有哪些附件")
    assert wants_attachment_inventory("列出附件清单")
    assert wants_attachment_inventory("调用 radar 工具")
    assert not wants_attachment_inventory("下一步是什么")
    # "下载 X.log" must stay on the download path, not inventory.
    assert not wants_attachment_inventory("下载 sensor_flash_test_PASS_with_MLB_1.log")


class _FakeEntry:
    """Minimal stand-in for a radarclient attachment/picture entry."""

    def __init__(self, file_name: str, data: bytes = b"fake") -> None:
        self.fileName = file_name
        self._data = data

    def write_to_file(self, handle, continue_at: int = 0, client=None) -> None:
        handle.write(self._data)


class _FakeCollection:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self._entries = list(entries)

    def items(self):
        return list(self._entries)


class _FakeRadar:
    def __init__(self, attachments=(), pictures=()) -> None:
        self.attachments = _FakeCollection(list(attachments))
        self.pictures = _FakeCollection(list(pictures))


def test_download_attachment_falls_back_to_pictures(tmp_path: Path) -> None:
    """A .png stored only under radar.pictures must still download via
    download_attachment (Problem 5 root A cross-collection fallback)."""
    radar = _FakeRadar(
        attachments=[_FakeEntry("a.log")],
        pictures=[_FakeEntry("Cal_LPNM_2.png")],
    )
    backend = RadarclientBackend(client=MagicMock())
    backend._radar_for_id = lambda rid: radar  # type: ignore[method-assign]
    dest = tmp_path / "out.png"
    got = backend.download_attachment("182787079", "Cal_LPNM_2.png", dest_path=dest)
    assert got.is_file()
    assert dest.read_bytes() == b"fake"


def test_download_picture_falls_back_to_attachments(tmp_path: Path) -> None:
    """Reverse direction: a file tagged picture but living under attachments."""
    radar = _FakeRadar(
        attachments=[_FakeEntry("Cal_LPNM_2.png")],
        pictures=[],
    )
    backend = RadarclientBackend(client=MagicMock())
    backend._radar_for_id = lambda rid: radar  # type: ignore[method-assign]
    dest = tmp_path / "out.png"
    got = backend.download_picture("182787079", "Cal_LPNM_2.png", dest_path=dest)
    assert got.is_file()


def _configured(repo_root: Path, tmp_path: Path):
    config = load_config(repo_root=repo_root)
    return replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )


def test_attachment_inventory_lists_all_kinds(repo_root: Path, tmp_path: Path) -> None:
    config = _configured(repo_root, tmp_path)
    result = start_fa_checkin(config, "101493937")
    md = format_attachment_inventory_markdown(config, "101493937")
    assert "### Radar attachments（共" in md
    # Every listed attachment (logs + picture) appears by name.
    for att in result.problem.attachments:
        assert att.file_name in md
    # cached / pending markers present.
    assert "已缓存" in md or "待下载" in md
    # Must never claim there is no log when logs are listed.
    assert "没有 log" not in md
    assert "no log" not in md.lower()


def test_inventory_with_log_zip_must_not_say_no_log(
    repo_root: Path, tmp_path: Path
) -> None:
    config = _configured(repo_root, tmp_path)
    result = start_fa_checkin(config, "101493937")
    names = [a.file_name for a in result.problem.attachments]
    assert any(n.endswith(".log") or n.endswith(".zip") for n in names)
    md = format_attachment_inventory_markdown(config, "101493937")
    assert "没有 log" not in md
    assert "no log" not in md.lower()
