"""Tests for agent role loading and supervisor routing (ADR 0008)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from ee_wiki.agents.fuse import fuse_findings
from ee_wiki.agents.roles import load_all_roles, load_role_pack
from ee_wiki.agents.supervisor import Supervisor
from ee_wiki.common.config import load_config
from ee_wiki.common.errors import ConfigError
from ee_wiki.integrations.fa_chat import parse_fa_checkin_radar_id
from ee_wiki.protocols.agent import Finding
from ee_wiki.tools.bus import ToolBus


def test_load_shipped_roles(repo_root: Path) -> None:
    roles = load_all_roles(repo_root / "config" / "agents" / "roles")
    assert set(roles) >= {"radar", "fa", "hw", "power", "pcb", "si", "mfg"}
    assert "engineering_search" in roles["hw"].tools
    assert "fa_session_turn" in roles["radar"].tools


def test_role_rejects_banned_tool(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.dump(
            {
                "id": "bad",
                "display_name": "Bad",
                "routing": {"keywords": ["x"]},
                "tools": ["ingest"],
                "recipe": [{"tool": "ingest"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="banned|unknown"):
        load_role_pack(path)


def test_fa_intent_radar_slash() -> None:
    assert parse_fa_checkin_radar_id("帮我FA一下radar://123456") == "123456"
    assert parse_fa_checkin_radar_id("FA一下 rdar://99999888") == "99999888"


def test_fuse_all_insufficient() -> None:
    result = fuse_findings(
        "q",
        [Finding(role_id="si", markdown="x", insufficient=True)],
        product="iphone",
        project="logan",
        build="p1",
    )
    assert result.insufficient is True
    assert result.kind == "insufficient"


def test_supervisor_selects_power_role(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    bus.call.return_value = MagicMock(
        ok=True,
        text='{"hits":[{"id":1}],"found":true}',
        error=None,
    )
    sup = Supervisor(config, bus, roles, connectivity_query=None)
    selected = sup._select_roles("VDD_1V8 电源轨从哪里来？power tree")
    assert "power" in selected


def test_supervisor_semantic_when_keywords_below_threshold(repo_root: Path) -> None:
    """Single keyword hits stay below threshold; semantic LLM fills TASK/ROLES."""
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "TASK: design_review\nROLES: pcb, si"
    sup = Supervisor(config, bus, roles, llm=llm)

    # "布线" alone scores pcb=1 < route_score_threshold (2)
    route = sup._route_question("帮我检查高速布线有没有风险")

    assert route.task == "design_review"
    assert route.roles == ("pcb", "si")
    assert sup.last_route_mode == "semantic"
    llm.generate.assert_called_once()


def test_supervisor_rules_first_skips_semantic_llm(repo_root: Path) -> None:
    """Keyword scores at/above threshold skip the routing LLM (ADR 0012)."""
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "TASK: wiki\nROLES: none"
    sup = Supervisor(config, bus, roles, llm=llm)

    route = sup._route_question("VDD_1V8 电源轨从哪里来？power tree")

    assert "power" in route.roles
    assert route.task == "power"
    assert sup.last_route_mode == "rules"
    llm.generate.assert_not_called()


def test_supervisor_semantic_allows_three_roles(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    assert config.agents.max_roles_per_turn == 3
    from dataclasses import replace

    # Force semantic path: raise threshold so layout/眼图/电源树 each miss alone.
    config = replace(
        config,
        agents=replace(config.agents, route_score_threshold=99),
    )
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "TASK: design_review\nROLES: pcb, si, power"
    sup = Supervisor(config, bus, roles, llm=llm)

    route = sup._route_question("检查 layout、眼图和电源树风险")

    assert route.task == "design_review"
    assert route.roles == ("pcb", "si", "power")
    assert sup.last_route_mode == "semantic"


def test_supervisor_semantic_passthrough_preserves_task(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "TASK: translate\nROLES: none"
    sup = Supervisor(config, bus, roles, llm=llm)

    result = sup.handle("把上一条翻译成英文")

    assert result.kind == "passthrough"
    assert result.task == "translate"
    llm.generate.assert_called_once()


def test_supervisor_hybrid_on_insufficient_findings(repo_root: Path) -> None:
    """Empty specialist evidence still returns hybrid so chat can RAG-fallback."""
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    bus.call.return_value = MagicMock(
        ok=True,
        text='{"hits":[],"found":false}',
        error=None,
    )
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "TASK: power\nROLES: power"
    from dataclasses import replace

    config = replace(
        config,
        agents=replace(config.agents, route_score_threshold=99),
    )
    sup = Supervisor(config, bus, roles, llm=llm)
    result = sup.handle("电源树从哪来")
    assert result.kind == "hybrid"
    assert result.markdown == ""
    assert result.task == "power"


def test_supervisor_passthrough_when_no_keywords(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    # Raise threshold so casual questions don't match
    from dataclasses import replace

    config = replace(
        config,
        agents=replace(config.agents, route_score_threshold=99),
    )
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    sup = Supervisor(config, bus, roles)
    result = sup.handle("hello what time is it")
    assert result.kind == "passthrough"
    assert result.task == "wiki"


def test_supervisor_forces_radar_on_checkin(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    bus.call.return_value = MagicMock(
        ok=True,
        text="## FA check-in\n\nRadar **123456** stub summary.",
        error=None,
    )
    sup = Supervisor(config, bus, roles)
    result = sup.handle("帮我FA一下radar://123456")
    assert result.kind == "respond"
    assert "FA check-in" in result.markdown
    assert "Agent evidence" not in result.markdown
    assert result.markdown.count("FA check-in") == 1
    assert sup.last_route_mode == "rules"
    bus.call.assert_called_once()


def test_supervisor_clarify_vague(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    sup = Supervisor(config, bus, roles)
    result = sup.handle("帮我看看")
    assert result.kind == "clarify"
    assert result.markdown
    bus.call.assert_not_called()


def test_supervisor_clarify_trace_without_scope(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    sup = Supervisor(config, bus, roles)
    result = sup.handle("J1 第3脚连到哪")
    assert result.kind == "clarify"
    assert "product" in result.markdown.lower() or "project" in result.markdown
    bus.call.assert_not_called()
