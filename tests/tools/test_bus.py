"""Tests for ToolBus runtime (ADR 0008)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.tools.bus import BANNED_TOOLS, ToolBus, open_tool_bus
from ee_wiki.tools.scope import ScopeEnvelope


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.config.agents.tool_timeout_seconds = 60.0
    ctx.config.agents.max_concurrent_tools = 2
    return ctx


def test_scope_envelope_clamps_project_build() -> None:
    env = ScopeEnvelope(product="iphone", project="logan", build="p1")
    clamped = env.clamp_args({"product": "other", "project": "other", "build": "p9", "query": "x"})
    assert clamped["product"] == "iphone"
    assert clamped["project"] == "logan"
    assert clamped["build"] == "p1"
    assert clamped["query"] == "x"


def test_banned_tool_refused(tmp_path: Path) -> None:
    bus = open_tool_bus(_ctx(), span_log=tmp_path / "spans.jsonl")
    result = bus.call("ingest", {"path": "/tmp"}, caller_id="test")
    assert result.ok is False
    assert "banned" in (result.error or "").lower()
    assert "ingest" in BANNED_TOOLS


def test_unknown_tool_refused(tmp_path: Path) -> None:
    bus = open_tool_bus(_ctx(), span_log=tmp_path / "spans.jsonl")
    result = bus.call("not_a_real_tool", {}, caller_id="test")
    assert result.ok is False
    assert "Unknown" in (result.error or "")


def test_registered_tool_invokes_handler(tmp_path: Path, monkeypatch) -> None:
    from ee_wiki.tools import bus as bus_mod

    def fake_engineering_search(ctx, a):
        return json.dumps(
            {"query": a["query"], "product": a.get("product"), "project": a.get("project")}
        )

    monkeypatch.setitem(
        bus_mod._build_registry(),
        "engineering_search",
        fake_engineering_search,
    )
    # Rebuild bus with patched registry
    bus = ToolBus(_ctx(), span_log=tmp_path / "spans.jsonl")
    bus._registry["engineering_search"] = fake_engineering_search

    result = bus.call(
        "engineering_search",
        {"query": "LAN8720A", "product": "evil", "project": "evil"},
        caller_id="hw",
        scope=ScopeEnvelope(product="iphone", project="logan", build="p1"),
    )
    assert result.ok is True
    payload = json.loads(result.text)
    assert payload["query"] == "LAN8720A"
    assert payload["product"] == "iphone"
    assert payload["project"] == "logan"


def test_timeout_returns_error(tmp_path: Path) -> None:
    bus = ToolBus(_ctx(), timeout_seconds=0.05, span_log=tmp_path / "spans.jsonl")

    def slow(_ctx, _args):
        time.sleep(1.0)
        return "late"

    bus._registry["engineering_search"] = slow
    result = bus.call("engineering_search", {"query": "x"}, caller_id="test")
    assert result.ok is False
    assert "timed out" in (result.error or "").lower()


def test_span_log_written(tmp_path: Path) -> None:
    span_path = tmp_path / "spans.jsonl"
    bus = ToolBus(_ctx(), span_log=span_path)

    def ok(_ctx, _args):
        return '{"ok": true}'

    bus._registry["list_projects"] = ok
    result = bus.call("list_projects", {}, caller_id="mcp")
    assert result.ok is True
    lines = span_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    span = json.loads(lines[0])
    assert span["tool"] == "list_projects"
    assert span["caller"] == "mcp"
    assert span["ok"] is True
