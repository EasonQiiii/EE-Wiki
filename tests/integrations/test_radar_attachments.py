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
    resolve_requested_attachments,
    wants_attachment_content,
    wants_attachment_download,
)
from ee_wiki.integrations.session import start_fa_checkin
from ee_wiki.protocols.radar import AttachmentMeta
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


def test_checkin_includes_download_links(repo_root: Path, tmp_path: Path) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    result = start_fa_checkin(config, "rdar://problem/101493937")
    assert "### Radar attachment downloads" in result.summary_markdown
    assert "/v1/cache/fa/101493937/attachments/" in result.summary_markdown
    assert "sensor_flash_test_PASS_with_MLB_1.log" in result.summary_markdown
    # Files materialized on disk
    att_dir = tmp_path / "cache/fa/101493937/attachments"
    assert (att_dir / "sensor_flash_test_PASS_with_MLB_1.log").is_file()


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
