"""FaAgent must return a friendly Chinese reply on Radar integration errors.

ConfigError (no Kerberos / radarclient) and IntegrationError (ACL / not found /
opaque) raised inside the bound path must be caught by FaAgent.handle and turned
into a readable reply — never propagated as an exception (which would surface as
an HTTP 500 in the chat route).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from ee_wiki.agents.fa_agent import FaAgent, FaAgentResult
from ee_wiki.common.config import load_config
from ee_wiki.common.errors import IntegrationError


def _config_with_live_radar(repo_root: Path):
    """Load config but force the live backend so Radar construction fails here."""
    config = load_config(repo_root=repo_root)
    fa = replace(
        config.fa,
        radar=replace(config.fa.radar, backend="radarclient"),
    )
    return replace(config, fa=fa)


def test_fa_agent_handles_config_error_on_attachment_path(repo_root: Path) -> None:
    """'下载' triggers the attachment path; radarclient absent -> ConfigError."""
    config = _config_with_live_radar(repo_root)
    agent = FaAgent(config, MagicMock(), llm=None)
    result = agent.handle("rdar://problem/101493937 下载附件", history=None)
    assert isinstance(result, FaAgentResult)
    assert "## FA 集成提示" in result.markdown
    assert "Kerberos" in result.markdown or "radarclient" in result.markdown


def test_fa_agent_handles_config_error_on_session_turn(repo_root: Path) -> None:
    """A follow-up question (no '下载') hits try_fa_chat_reply -> ConfigError."""
    config = _config_with_live_radar(repo_root)
    agent = FaAgent(config, MagicMock(), llm=None)
    result = agent.handle("rdar://problem/101493937 最新进展", history=None)
    assert isinstance(result, FaAgentResult)
    assert "## FA 集成提示" in result.markdown


def test_fa_agent_maps_integration_error_to_acl_message(repo_root: Path) -> None:
    """try_fa_chat_reply raising IntegrationError(403) -> friendly ACL reply."""
    config = load_config(repo_root=repo_root)
    agent = FaAgent(config, MagicMock(), llm=None)
    with patch(
        "ee_wiki.agents.fa_agent.try_fa_chat_reply",
        side_effect=IntegrationError("radar_for_id(101) failed: 403 Forbidden"),
    ):
        result = agent.handle("rdar://problem/101493937 最新进展", history=None)
    assert isinstance(result, FaAgentResult)
    assert "ACL" in result.markdown
    assert "rdar://101" in result.markdown
