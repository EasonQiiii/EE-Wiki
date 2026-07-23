"""FaAgent bound-session suggestion routing (Problem 3, Phase B/F).

A bound FA follow-up that asks for extra suggestions / next actions ("你有没有
额外的建议动作？") must NOT answer "没有" from the read-only path. It must run
the shared ToolBus via `select_fa_skills` -> `INVESTIGATION_TOOLS`, then ground
the reply with `bound_suggestion_summary.md` (Radar-existing vs 非 Radar 原文).

Also covers Problem 4: a bound session asking for the FA one-page Keynote
("keynote / 一页纸 / 导出报告") must run `generate_fa_summary` and return a
download link; an unbound session must ask to bind a rdar:// first.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ee_wiki.agents.fa_agent import FaAgent, FaAgentResult
from ee_wiki.common.config import load_config
from ee_wiki.integrations.scope import ScopeResolution
from ee_wiki.protocols.flames import FailItem, FailItemsResult, FlamesUnitRef
from ee_wiki.protocols.radar import DiagnosisItem, RadarProblem
from ee_wiki.retrieval.rewrite import ConversationTurn


def _config(repo_root: Path):
    return load_config(repo_root=repo_root)


def _bound_history(radar_id: str = "182787079") -> list[ConversationTurn]:
    return [
        ConversationTurn(
            role="assistant",
            content=(
                f"## FA check-in — rdar://{radar_id}\n\n"
                "### Fail items\n- flash erase incomplete\n"
            ),
        )
    ]


def test_fa_agent_bound_suggestion_runs_skills(repo_root: Path) -> None:
    """'你有没有额外的建议动作？' on a bound ticket must select investigation
    tools, execute them through the ToolBus, and ground a reply that marks the
    EE-Wiki extra suggestions as 非 Radar 原文 — NOT a bare '没有额外建议'.
    """
    config = _config(repo_root)
    bus = MagicMock()
    bus.call.return_value = SimpleNamespace(
        ok=True,
        text="[search_debug_case] 找到类似 case: U8600 去耦电容异常 (logan p1)",
        error=None,
    )
    llm = MagicMock()

    with (
        patch(
            "ee_wiki.agents.fa_agent._select_skills",
            return_value=("search_debug_case", "engineering_search"),
        ) as m_select,
        patch(
            "ee_wiki.agents.fa_agent._bound_suggestion_summary",
            return_value=(
                "（非 Radar 原文）建议1：检查 U8600 周边去耦电容布局 (search_debug_case)；"
                "（非 Radar 原文）建议2：查阅 logan p1 电源域工程知识 (engineering_search)"
            ),
        ) as m_summary,
        patch("ee_wiki.agents.fa_agent.try_fa_chat_reply") as m_readonly,
    ):
        agent = FaAgent(config, bus, llm=llm)
        result = agent.handle(
            "你有没有额外的建议动作？",
            history=_bound_history(),
            product="iphone",
            project="logan",
            build="p1",
        )

    # ToolBus path taken; read-only fallback was NOT used.
    assert isinstance(result, FaAgentResult)
    assert result.branch == "fa_agent"
    assert m_readonly.call_count == 0

    # Skill selection was asked and the investigation tools were routed.
    m_select.assert_called_once()
    assert set(result.routed_skills) == {"search_debug_case", "engineering_search"}

    # ToolBus actually executed the selected tools.
    executed = {call.args[0] for call in bus.call.call_args_list}
    assert executed == {"search_debug_case", "engineering_search"}

    # Grounded reply: bound header + EE-Wiki extra suggestions clearly marked.
    assert result.markdown.startswith("## FA check-in — rdar://182787079")
    assert "（非 Radar 原文）" in result.markdown
    assert "没有额外建议" not in result.markdown

    # The summary was composed from the retrieved evidence (not a stub).
    # _bound_suggestion_summary receives (question, radar_id, checkin, evidence,
    # scope_note) positionally, then llm= / repo_root= / cancel_event=.
    m_summary.assert_called_once()
    args = m_summary.call_args.args
    assert "search_debug_case" in args[3]  # evidence is the 4th positional arg


def test_fa_agent_bound_suggestion_fallback_no_bare_no_suggestion(
    repo_root: Path,
) -> None:
    """When the LLM selects NO investigation tools (suggestion asked, nothing
    relevant), the read-only fallback must not answer with only '没有额外建议'
    (Phase C). It should explain the ticket's diagnosis recorded no extra steps
    and that EE-Wiki retrieval wasn't executed for this read-only turn.
    """
    config = _config(repo_root)
    bus = MagicMock()
    llm = MagicMock()

    readonly_markdown = (
        "## FA check-in — rdar://182787079\n\n"
        "票上 diagnosis 未写额外步骤；EE-Wiki 检索未执行或 scope 不足，"
        "无法给检索型建议。可显式要求搜索 debug case / 原理图 / 工程知识。"
    )
    with (
        patch(
            "ee_wiki.agents.fa_agent._select_skills",
            return_value=(),  # no investigation tools selected
        ),
        patch(
            "ee_wiki.agents.fa_agent.try_fa_chat_reply",
            return_value=readonly_markdown,
        ) as m_readonly,
    ):
        agent = FaAgent(config, bus, llm=llm)
        result = agent.handle(
            "你有没有额外的建议动作？",
            history=_bound_history(),
            product="iphone",
            project="logan",
            build="p1",
        )

    # No ToolBus execution when no investigation tools were selected.
    bus.call.assert_not_called()
    # Read-only path was used and its reply explains the gap (no bare 'no').
    m_readonly.assert_called_once()
    assert "没有额外建议" not in result.markdown
    assert "EE-Wiki 检索未执行" in result.markdown


def test_fa_agent_bound_radar_checkin_not_stolen_by_toolbus(
    repo_root: Path,
) -> None:
    """A fresh ``rdar://`` / ``radar://`` message must run start_fa_checkin via
    the read-only path — never be hijacked by investigation ToolBus because
    ``select_fa_skills`` returned empty / failed and fell back to unbound
    defaults (acceptance regression for Problem 3).
    """
    config = _config(repo_root)
    bus = MagicMock()
    llm = MagicMock()
    checkin_md = "## FA check-in — rdar://182787079\n\n**Title:** Drop test\n"

    with (
        patch(
            "ee_wiki.agents.fa_agent._select_skills",
            return_value=("search_debug_case", "engineering_search"),
        ) as m_select,
        patch(
            "ee_wiki.agents.fa_agent.try_fa_chat_reply",
            return_value=checkin_md,
        ) as m_readonly,
    ):
        agent = FaAgent(config, bus, llm=llm)
        result = agent.handle(
            "rdar://182787079",
            history=None,
            product=None,
            project=None,
            build=None,
        )

    m_select.assert_not_called()
    bus.call.assert_not_called()
    m_readonly.assert_called_once()
    assert "FA check-in — rdar://182787079" in result.markdown
    assert result.routed_skills == ()
    assert result.branch == "respond"


def test_fa_agent_bound_empty_skills_stays_readonly_no_unbound_default(
    repo_root: Path,
) -> None:
    """Bound skill selection must pass ``fallback_default=False`` so an empty
    / failed LLM ``SKILLS:`` does not expand to ``_DEFAULT_UNBOUND_SKILLS``.
    """
    config = _config(repo_root)
    bus = MagicMock()
    llm = MagicMock()
    readonly_markdown = (
        "## FA check-in — rdar://182787079\n\n"
        "票上 diagnosis 未写额外步骤；EE-Wiki 检索未执行或 scope 不足，"
        "无法给检索型建议。"
    )

    with (
        patch(
            "ee_wiki.generation.classify.select_fa_skills",
            return_value=[],  # explicit empty SKILLS from LLM
        ) as m_llm_select,
        patch(
            "ee_wiki.agents.fa_agent.try_fa_chat_reply",
            return_value=readonly_markdown,
        ) as m_readonly,
    ):
        agent = FaAgent(config, bus, llm=llm)
        result = agent.handle(
            "你有没有额外的建议动作？",
            history=_bound_history(),
            product="iphone",
            project="logan",
            build="p1",
        )

    m_llm_select.assert_called_once()
    bus.call.assert_not_called()
    m_readonly.assert_called_once()
    assert result.routed_skills == ()
    assert "没有额外建议" not in result.markdown


# ── Problem 4: FA one-page Keynote export (keynote / 一页纸 / 导出报告) ─────


def _fake_checkin():
    """Minimal FaCheckinResult so the export helper can read structured data."""
    problem = RadarProblem(
        radar_id="182787079",
        title="Drop test fail @ station 12",
        state="Analyze",
        substate="Screen",
        diagnosis=(
            DiagnosisItem(
                text="Please perform CT scan after knock test.",
                added_by="naixin",
                entry_type="user",
            ),
        ),
    )
    scope = ScopeResolution(
        product="iphone",
        project="logan",
        build="p1",
        source="component_alias",
        confidence="high",
    )
    fail_items = FailItemsResult(
        unit=FlamesUnitRef(unit_id="radar-text-182787079"),
        records=(),
        fail_items=(
            FailItem(message="flash erase incomplete", station="Station12"),
        ),
        cached_logs=(),
        source="stub",
    )
    return SimpleNamespace(
        radar_id="182787079",
        problem=problem,
        scope=scope,
        fail_items=fail_items,
    )


def test_fa_agent_bound_keynote_export_returns_download_link(
    repo_root: Path,
) -> None:
    """On a bound ticket, '整理成 FA one page keynote' must wire
    start_fa_checkin -> generate_fa_summary and return the fixed
    '## FA One-Page 已生成' reply with a clickable FA_summary.key link
    (Problem 4). No ToolBus / read-only fallback involved.
    """
    config = _config(repo_root)
    bus = MagicMock()
    llm = MagicMock()

    download_url = (
        "http://ee-wiki.test:8080/v1/exports/fa/182787079/FA_summary.key"
    )
    with (
        patch(
            "ee_wiki.integrations.session.start_fa_checkin",
            return_value=_fake_checkin(),
        ) as m_checkin,
        patch(
            "ee_wiki.integrations.session.generate_fa_summary",
            return_value=(
                SimpleNamespace(
                    output_path="x.key",
                    notes="Created Keynote one-pager via AppleScript",
                ),
                download_url,
            ),
        ) as m_summary,
        patch("ee_wiki.agents.fa_agent.try_fa_chat_reply") as m_readonly,
    ):
        agent = FaAgent(config, bus, llm=llm)
        result = agent.handle(
            "帮我整理成 FA one page keynote",
            history=_bound_history(),
            product="iphone",
            project="logan",
            build="p1",
        )

    # Generated the .key and returned the fixed download reply + Radar preview.
    assert isinstance(result, FaAgentResult)
    assert result.markdown.startswith("## FA One-Page 已生成")
    assert "[下载 FA_summary.key]" in result.markdown
    assert download_url in result.markdown
    assert "## Summary" in result.markdown
    assert "## Conclusion" in result.markdown
    assert result.routed_skills == ("fa_export_keynote",)
    assert result.branch == "fa_report"

    # The two orchestration helpers were driven with the bound radar id.
    m_checkin.assert_called_once()
    assert m_checkin.call_args.args[1] == "182787079"
    m_summary.assert_called_once()
    summary_kwargs = m_summary.call_args.kwargs
    assert summary_kwargs.get("conclusion")
    assert "Ticket state" in summary_kwargs["conclusion"]
    m_readonly.assert_not_called()
    bus.call.assert_not_called()


def test_fa_agent_unbound_keynote_asks_to_bind(repo_root: Path) -> None:
    """An unbound keynote ask must NOT generate anything — it must ask the
    user to bind a rdar:// first (Problem 4 trigger scope decision).
    """
    config = _config(repo_root)
    bus = MagicMock()
    llm = MagicMock()

    with (
        patch(
            "ee_wiki.integrations.session.start_fa_checkin"
        ) as m_checkin,
        patch(
            "ee_wiki.integrations.session.generate_fa_summary"
        ) as m_summary,
    ):
        agent = FaAgent(config, bus, llm=llm)
        result = agent.handle(
            "帮我整理成 FA one page keynote",
            history=None,
            product=None,
            project=None,
            build=None,
        )

    assert isinstance(result, FaAgentResult)
    assert "rdar://" in result.markdown
    assert "FA one-page keynote" in result.markdown
    assert result.routed_skills == ("fa_export_keynote",)
    assert result.branch == "fa_report"
    # No export machinery runs for an unbound session.
    m_checkin.assert_not_called()
    m_summary.assert_not_called()


# ── Problem 5: deterministic "有哪些附件" inventory (no LLM) ────────────────


def test_fa_agent_bound_attachment_inventory_routes_deterministically(
    repo_root: Path, tmp_path: Path
) -> None:
    """On a bound ticket, 'radar 里有哪些附件' must take the structural
    fast-path: enumerate every attachment (incl .log/.zip/pictures) via
    format_attachment_inventory_markdown and return with
    routed_skills=('radar_list_attachments',), branch='respond' — never handed
    to the LLM dialogue (Problem 5 root B)."""
    config = replace(
        load_config(repo_root=repo_root),
        cache_dir=tmp_path / "cache",
        api=replace(
            load_config(repo_root=repo_root).api,
            public_base_url="http://ee-wiki.test:8080",
        ),
    )
    bus = MagicMock()
    agent = FaAgent(config, bus, llm=None)
    first = agent.handle("rdar://problem/101493937")
    assert "FA check-in" in first.markdown
    history = [ConversationTurn(role="assistant", content=first.markdown)]
    second = agent.handle("radar 里有哪些附件", history=history)

    # Deterministic inventory header, no LLM tool-evidence block.
    assert "### Radar attachments（共" in second.markdown
    assert "### Tool evidence" not in second.markdown
    # Every attachment (logs + picture) enumerated by name.
    from ee_wiki.integrations.session import start_fa_checkin

    problem = start_fa_checkin(config, "101493937").problem
    for att in problem.attachments:
        assert att.file_name in second.markdown
    # Never claims there is no log when logs are listed.
    assert "没有 log" not in second.markdown
    assert "no log" not in second.markdown.lower()
    # Routed as trace-only inventory.
    assert second.routed_skills == ("radar_list_attachments",)
    assert second.branch == "respond"


def test_fa_agent_bound_explicit_radar_tool_routes(
    repo_root: Path, tmp_path: Path
) -> None:
    """'调用 radar 工具' (Decision 2 explicit tool intent) routes deterministically:
    no filename -> inventory list; with a specific file name -> on-demand
    download. Neither path reaches the LLM dialogue.
    """
    config = replace(
        load_config(repo_root=repo_root),
        cache_dir=tmp_path / "cache",
        api=replace(
            load_config(repo_root=repo_root).api,
            public_base_url="http://ee-wiki.test:8080",
        ),
    )
    bus = MagicMock()
    agent = FaAgent(config, bus, llm=None)
    first = agent.handle("rdar://problem/101493937")
    history = [ConversationTurn(role="assistant", content=first.markdown)]

    # No filename -> inventory list (routed as trace-only).
    inv = agent.handle("调用 radar 工具", history=history)
    assert "### Radar attachments（共" in inv.markdown
    assert inv.routed_skills == ("radar_list_attachments",)
    assert inv.branch == "respond"
    assert "### Tool evidence" not in inv.markdown

    # With a specific file name -> on-demand download links.
    dl = agent.handle(
        "调用 radar 工具 下载 sensor_flash_test_PASS_with_MLB_1.log",
        history=history,
    )
    assert "### Radar attachment downloads" in dl.markdown
    assert "MLB_1.log" in dl.markdown
    assert "/v1/cache/" in dl.markdown
    assert "### Tool evidence" not in dl.markdown
