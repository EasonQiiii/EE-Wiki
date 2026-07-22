"""Tests for OpenAI-compatible chat endpoint."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_config, get_rag_service
from ee_wiki.api.routes.chat import _fetch_stream_result
from ee_wiki.api.stream_status import GENERATION_STATUS, RETRIEVAL_STATUS
from ee_wiki.common.types import Citation
from ee_wiki.generation.service import AnswerStreamResult

_TITLE_PROMPT = """### Task:
Generate a concise, 3-5 word title with an emoji summarizing the chat history.
### Chat History:
<chat_history>
USER: 怎么配置邮箱
ASSISTANT: 打开邮件应用...
</chat_history>"""


def _stream_result(
    text: str,
    *,
    citations: list[Citation] | None = None,
) -> AnswerStreamResult:
    def _chunks():
        yield text

    return AnswerStreamResult(citations=citations or [], text_chunks=_chunks())


def _config_without_elapsed(app_config):
    return replace(
        app_config,
        generation=replace(app_config.generation, show_elapsed_time=False),
    )


def test_chat_completions_uses_last_user_message(app_config) -> None:
    service = MagicMock()
    service.stream_answer.return_value = _stream_result("RMII uses ETH_MDIO.")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: _config_without_elapsed(app_config)
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "What is RMII?"},
            ],
            "product": "iphone",
            "project": "logan",
            "build": "p1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # carry_scope_across_turns embeds a hidden scope marker (no conversation_id
    # needed) when scope is known; assert the answer body and the marker.
    content = payload["choices"][0]["message"]["content"]
    assert content.startswith("RMII uses ETH_MDIO.")
    assert "<!-- ee-wiki-scope: iphone/logan/p1 -->" in content
    assert payload["model"] == "ee-wiki"
    assert payload["sources"] == []
    assert "created" in payload
    service.stream_answer.assert_called_once()
    call_kwargs = service.stream_answer.call_args.kwargs
    assert call_kwargs["target_product"] == "iphone"
    assert call_kwargs["target_project"] == "logan"
    assert call_kwargs["target_build"] == "p1"
    assert "cancel_event" in call_kwargs


def test_chat_completions_returns_open_webui_sources(app_config) -> None:
    citations = [
        Citation(
            source_file="data/raw/iphone/logan/p1/note/manual.md",
            chunk_id="manual__power",
            page=0,
            excerpt="VBAT connects to PMIC.",
            url="http://localhost:8080/v1/sources/iphone/logan/p1/note/manual.md#power",
        ),
    ]
    service = MagicMock()
    service.stream_answer.return_value = _stream_result(
        "VBAT is connected to the PMIC [1].",
        citations=citations,
    )

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: _config_without_elapsed(app_config)
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [{"role": "user", "content": "What is VBAT?"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "VBAT is connected to the PMIC [1]."
    assert payload["citations"][0]["url"].endswith(
        "/v1/sources/iphone/logan/p1/note/manual.md#power"
    )
    assert payload["sources"][0]["source"]["url"] == citations[0].url
    assert payload["sources"][0]["source"]["name"] == "[1] manual.md"


def test_chat_completions_stream_emits_sources_chunk() -> None:
    citations = [
        Citation(
            source_file="data/raw/iphone/logan/p1/note/manual.md",
            chunk_id="manual__power",
            page=0,
            excerpt="VBAT connects to PMIC.",
            url="http://localhost:8080/v1/sources/iphone/logan/p1/note/manual.md#power",
        ),
    ]

    def _text_chunks():
        yield "VBAT answer [1]."

    service = MagicMock()
    service.stream_answer.return_value = AnswerStreamResult(
        citations=citations,
        text_chunks=_text_chunks(),
    )

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "stream": True,
            "messages": [{"role": "user", "content": "What is VBAT?"}],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert '"sources"' in body
    assert '"event"' in body
    assert RETRIEVAL_STATUS in body
    assert GENERATION_STATUS in body
    assert '"type": "status"' in body
    assert "VBAT answer [1]." in body
    assert "<a href=" not in body


def test_chat_completions_stream_emits_retrieval_status() -> None:
    service = MagicMock()
    service.stream_answer.return_value = _stream_result("Quick answer.")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "stream": True,
            "messages": [{"role": "user", "content": "Test question"}],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert RETRIEVAL_STATUS in body
    assert GENERATION_STATUS in body
    assert '"done": false' in body.lower()
    assert '"done": true' in body.lower()
    assert '"hidden": true' in body.lower()


def test_chat_completions_meta_question_uses_service_fast_path() -> None:
    service = MagicMock()
    service.stream_answer.return_value = _stream_result(
        "我是 EE-Wiki 的电子工程知识助手。",
    )

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [{"role": "user", "content": "你的角色是什么？"}],
        },
    )

    assert response.status_code == 200
    assert "EE-Wiki" in response.json()["choices"][0]["message"]["content"]
    service.stream_answer.assert_called_once()


def test_supervisor_route_forwards_task_without_second_classification(
    app_config,
) -> None:
    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.llm.generate_stream = None
    # FA mode classify runs first ("MODE: wiki" → stays wiki), then the
    # supervisor routing call gets the TASK/ROLES line.
    service.llm.generate.side_effect = [
        "MODE: wiki",
        "TASK: translate\nROLES: none",
    ]
    service.stream_answer.return_value = _stream_result("Translated.")

    result = _fetch_stream_result(
        service,
        "translate the previous answer",
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
    )

    assert "".join(result.text_chunks) == "Translated."
    # FA classify (1) + supervisor route (1) = 2 LLM calls — but the supervisor
    # itself does NOT re-classify (no third call).
    assert service.llm.generate.call_count == 2
    service.stream_answer.assert_called_once()
    assert service.stream_answer.call_args.kwargs["task"] == "translate"
    assert service.stream_answer.call_args.kwargs["task_owner"] == "supervisor"
    service.stream_direct.assert_not_called()


def test_supervisor_hybrid_uses_stream_answer_with_evidence(app_config) -> None:
    """Specialist findings go to RagService hybrid path, not stream_direct."""
    from unittest.mock import patch

    from ee_wiki.protocols.agent import SupervisorResult

    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.stream_answer.return_value = _stream_result(
        "Grounded.",
        citations=[
            Citation(
                source_file="note.md",
                page=1,
                chunk_id="c1",
                excerpt="rail",
            )
        ],
    )

    hybrid = SupervisorResult(
        kind="hybrid",
        markdown="## Agent evidence\npower hit",
        task="power",
        roles_used=("power",),
    )
    with patch(
        "ee_wiki.agents.supervisor.Supervisor.handle",
        return_value=hybrid,
    ):
        result = _fetch_stream_result(
            service,
            "VDD power tree",
            bypass_rag=False,
            target_product=None,
            target_project=None,
            target_build=None,
            document_type=None,
            top_k=None,
            cancel_event=None,
            task=None,
            history=None,
        )

    assert "".join(result.text_chunks) == "Grounded."
    service.stream_answer.assert_called_once()
    kwargs = service.stream_answer.call_args.kwargs
    assert kwargs["agent_evidence"] == "## Agent evidence\npower hit"
    assert kwargs["task"] == "power"
    assert kwargs["task_owner"] == "supervisor"
    service.stream_direct.assert_not_called()


def test_chat_completions_bypasses_rag_for_open_webui_title_task() -> None:
    service = MagicMock()
    service.stream_direct.return_value = _stream_result(
        '{"title": "📧 邮箱配置"}',
    )

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [{"role": "user", "content": _TITLE_PROMPT}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == '{"title": "📧 邮箱配置"}'
    service.stream_direct.assert_called_once()
    service.stream_answer.assert_not_called()


def test_chat_completions_appends_elapsed_footer_when_enabled(app_config) -> None:
    service = MagicMock()
    service.stream_answer.return_value = _stream_result("Answer text.")
    config = replace(
        app_config,
        generation=replace(app_config.generation, show_elapsed_time=True),
    )

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [{"role": "user", "content": "Test question"}],
        },
    )

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content.startswith("Answer text.")
    assert "检索" in content
    assert "生成" in content
    assert "首字" in content


def test_chat_completions_stream_appends_elapsed_footer_when_enabled(app_config) -> None:
    service = MagicMock()
    service.stream_answer.return_value = _stream_result("Stream answer.")
    config = replace(
        app_config,
        generation=replace(app_config.generation, show_elapsed_time=True),
    )

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "stream": True,
            "messages": [{"role": "user", "content": "Test question"}],
        },
    )

    assert response.status_code == 200
    assert "Stream answer." in response.text
    assert "检索" in response.text
    assert "首字" in response.text


# ── FA mode gating (fa-session.md A/B/C) ──────────────────────────────────


def test_fa_mode_unbound_golden_sentence_routes_to_fa_agent(app_config) -> None:
    """Golden sentence: '帮我FA一下…U8600…IIC…' → FaMode unbound, not wiki RAG.

    Only the ToolBus is mocked — FaAgent.handle runs for real through
    ensure_session → select_skills → exec → ground_and_say.
    """
    from unittest.mock import patch

    from ee_wiki.tools.bus import ToolResult

    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.llm = MagicMock()
    service.llm.generate_stream = None
    # 1) classify_fa_mode → fa, 2) select_fa_skills, 3) unbound LLM summary
    service.llm.generate.side_effect = [
        "MODE: fa",
        "SKILLS: search_component, engineering_search",
        "U8600 is an I2C buffer (VDDIO 1.8V). No true-fail conclusion yet.",
    ]

    mock_bus = MagicMock()
    mock_bus.call.return_value = ToolResult(
        name="search_component",
        ok=True,
        text="U8600: I2C buffer, VDDIO 1.8V, SCL/SDA on pins 5/6",
    )

    with patch("ee_wiki.agents.fa_agent.open_tool_bus", return_value=mock_bus):
        result = _fetch_stream_result(
            service,
            "帮我FA一下为什么U8600（logan p1）的IIC接口没有输出",
            bypass_rag=False,
            target_product="iphone",
            target_project="logan",
            target_build="p1",
            document_type=None,
            top_k=None,
            cancel_event=None,
            task=None,
            history=None,
        )

    content = "".join(result.text_chunks)
    assert "FA（未绑定 Radar）" in content
    assert "### Tool evidence" not in content  # P0: no raw JSON dump
    assert "仅检索上下文没有" not in content
    # ToolBus was called (real FaAgent ran, not a mock)
    assert mock_bus.call.call_count >= 1
    service.stream_answer.assert_not_called()


def test_wiki_mode_parameter_query_uses_rag(app_config) -> None:
    """'STM32F407 核心参数' → WikiMode, stream_answer called (not FaAgent)."""
    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.llm = MagicMock()
    service.llm.generate_stream = None
    # FA mode classify returns "MODE: wiki"; supervisor route then gets
    # "TASK: wiki\nROLES: none" → passthrough → stream_answer.
    service.llm.generate.side_effect = [
        "MODE: wiki",
        "TASK: wiki\nROLES: none",
    ]
    service.stream_answer.return_value = _stream_result(
        "STM32F407 main parameters: Cortex-M4, 168MHz."
    )

    result = _fetch_stream_result(
        service,
        "STM32F407 核心参数",
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
    )

    content = "".join(result.text_chunks)
    assert "STM32F407" in content
    service.stream_answer.assert_called_once()


def test_fa_methodology_advice_routes_to_readable_wiki(app_config) -> None:
    """Repro of the user's complaint turn: '这个trace没有输出应该怎么FA' asks
    ABOUT the FA process (methodology), not launching a real investigation. It
    must route to readable Wiki mode — NO unbound FAQ header and NO raw
    `### Tool evidence` JSON dump. Mirrors the Open WebUI round-trip: the prior
    reply carries the scope marker in history (no conversation_id)."""
    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.llm = MagicMock()
    service.llm.generate_stream = None
    # Advice gate short-circuits before classify_fa_mode; the supervisor route
    # LLM call is the only one.
    service.llm.generate.side_effect = ["TASK: wiki\nROLES: none"]
    service.stream_answer.return_value = _stream_result(
        "针对 DP_TBTSNK1_ML_C_N<1>（ipad/logan/p1，DP Sink 差分对负端），"
        "无输出建议依次排查供电/使能/HPD、连接性与 NO STUFF 标注。"
    )

    from ee_wiki.retrieval.rewrite import ConversationTurn

    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "DP_TBTSNK1_ML_C_N<1> 的 trace 需要 CAD netlist 才能给出权威走线。"
                "<!-- ee-wiki-scope: ipad/logan/p1 -->"
            ),
        ),
    ]

    result = _fetch_stream_result(
        service,
        "这个trace没有输出应该怎么FA",
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=history,
    )

    content = "".join(result.text_chunks)
    # Readable Wiki answer, not the heavy FAQ artifact.
    assert "FA（未绑定 Radar）" not in content
    assert "### Tool evidence" not in content
    # Scope carried from history marker (no conversation_id in Open WebUI).
    assert "ipad/logan/p1" in content
    service.stream_answer.assert_called_once()


def test_fa_mode_bound_radar_checkin_routes_to_fa_agent(app_config) -> None:
    """radar://101493937 → FaMode bound check-in (structural, no LLM needed)."""
    from unittest.mock import patch

    from ee_wiki.agents.fa_agent import FaAgentResult

    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.llm = MagicMock()

    checkin_markdown = (
        "## FA check-in — rdar://101493937\n\n"
        "### Fail items\n"
        "- Scarif flash cannot erase fully after imu save\n"
        "- System entering standby during test\n\n"
        "### Need test evidence\n"
    )
    fa_result = FaAgentResult(
        markdown=checkin_markdown,
        routed_skills=(),
        branch="respond",
    )
    mock_agent = MagicMock()
    mock_agent.handle.return_value = fa_result

    with (
        patch("ee_wiki.agents.fa_agent.open_fa_agent", return_value=mock_agent),
    ):
        result = _fetch_stream_result(
            service,
            "radar://101493937",
            bypass_rag=False,
            target_product=None,
            target_project=None,
            target_build=None,
            document_type=None,
            top_k=None,
            cancel_event=None,
            task=None,
            history=None,
        )

    content = "".join(result.text_chunks)
    assert "FA check-in" in content
    assert "rdar://101493937" in content
    service.stream_answer.assert_not_called()


def test_fa_mode_unbound_then_bind_on_radar(app_config) -> None:
    """Unbound session followed by radar:// → bind; still FaMode (not wiki)."""
    from unittest.mock import patch

    from ee_wiki.agents.fa_agent import FaAgentResult
    from ee_wiki.retrieval.rewrite import ConversationTurn

    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.llm = MagicMock()

    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "**FA（未绑定 Radar）：** U8600 IIC no output\n"
                "<!-- ee-wiki-scope: iphone/logan/p1 -->"
            ),
        ),
    ]

    bound_markdown = (
        "## FA check-in — rdar://101493937\n\n"
        "Bound from unbound session. Fail items listed below.\n"
    )
    fa_result = FaAgentResult(
        markdown=bound_markdown,
        routed_skills=(),
        branch="respond",
    )
    mock_agent = MagicMock()
    mock_agent.handle.return_value = fa_result

    with patch("ee_wiki.agents.fa_agent.open_fa_agent", return_value=mock_agent):
        result = _fetch_stream_result(
            service,
            "radar://101493937",
            bypass_rag=False,
            target_product="iphone",
            target_project="logan",
            target_build="p1",
            document_type=None,
            top_k=None,
            cancel_event=None,
            task=None,
            history=history,
        )

    content = "".join(result.text_chunks)
    assert "FA check-in" in content
    assert "rdar://101493937" in content
    service.stream_answer.assert_not_called()


def test_fa_mode_integration_error_returns_friendly_message(app_config) -> None:
    """Radar IntegrationError in FaAgent must not 500 — pipeline returns friendly text."""
    from unittest.mock import MagicMock, patch

    from ee_wiki.common.errors import IntegrationError

    service = MagicMock()
    service.config = app_config
    service.engine = MagicMock()
    service.llm = MagicMock()
    service.llm.generate_stream = None
    service.llm.generate.return_value = "MODE: fa"

    bad_agent = MagicMock()
    bad_agent.handle.side_effect = IntegrationError(
        "radar_for_id(101) failed: 403 Forbidden"
    )

    with patch("ee_wiki.agents.fa_agent.open_fa_agent", return_value=bad_agent):
        result = _fetch_stream_result(
            service,
            "rdar://problem/101493937 最新进展",
            bypass_rag=False,
            target_product=None,
            target_project=None,
            target_build=None,
            document_type=None,
            top_k=None,
            cancel_event=None,
            task=None,
            history=None,
        )

    content = "".join(result.text_chunks)
    assert "FA 集成提示" in content
    assert "ACL" in content
    service.stream_answer.assert_not_called()


def test_chat_scope_carries_across_turns(app_config) -> None:
    """History-embedded marker (ADR 0012 §6): a follow-up with no scope words
    inherits the prior turn's locked TurnScope when api.carry_scope_across_turns
    is enabled. The marker rides inside the prior assistant reply (echoed back
    by Open WebUI as history), so it is multi-worker safe."""
    conv_id = "conv-scope-carry-1"

    cfg = replace(
        app_config,
        generation=replace(app_config.generation, show_elapsed_time=False),
        api=replace(app_config.api, carry_scope_across_turns=True),
    )
    service = MagicMock()
    service.config = cfg
    service.stream_answer.return_value = _stream_result("Answer.")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: cfg
    client = TestClient(app)

    # Turn 1: scope inferred from the question text ("logan p1" -> ipad/logan/p1).
    r1 = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "user", "content": "logan p1 原理图有哪些电源轨？"}
            ],
            "conversation_id": conv_id,
        },
    )
    assert r1.status_code == 200
    turn1 = service.stream_answer.call_args_list[0].kwargs
    assert turn1["target_product"] == "ipad"
    assert turn1["target_project"] == "logan"
    assert turn1["target_build"] == "p1"

    # The assistant reply embeds a hidden scope marker; Open WebUI echoes it back
    # as history on the next turn. Recover it to inherit scope.
    assistant_content = r1.json()["choices"][0]["message"]["content"]
    assert "<!-- ee-wiki-scope:" in assistant_content

    # Turn 2: follow-up with no scope words, same conversation_id -> inherits.
    r2 = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "user", "content": "logan p1 原理图有哪些电源轨？"},
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": "那它的电源是怎么供电的？"},
            ],
            "conversation_id": conv_id,
        },
    )
    assert r2.status_code == 200
    turn2 = service.stream_answer.call_args_list[1].kwargs
    assert turn2["target_product"] == "ipad"
    assert turn2["target_project"] == "logan"
    assert turn2["target_build"] == "p1"


def test_chat_scope_not_carried_when_disabled(app_config) -> None:
    """With carry explicitly disabled, a follow-up with no scope words gets no
    inherited scope — confirming the opt-out path still works."""
    conv_id = "conv-scope-carry-2"

    cfg = replace(
        app_config,
        generation=replace(app_config.generation, show_elapsed_time=False),
        api=replace(app_config.api, carry_scope_across_turns=False),
    )
    service = MagicMock()
    service.config = cfg
    service.stream_answer.return_value = _stream_result("Answer.")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: cfg
    client = TestClient(app)

    r1 = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "user", "content": "logan p1 原理图有哪些电源轨？"}
            ],
            "conversation_id": conv_id,
        },
    )
    assert r1.status_code == 200
    # With carry disabled, turn 1 does NOT embed a marker in the reply.
    assistant_content = r1.json()["choices"][0]["message"]["content"]
    assert "<!-- ee-wiki-scope:" not in assistant_content

    r2 = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "user", "content": "logan p1 原理图有哪些电源轨？"},
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": "那它的电源是怎么供电的？"},
            ],
            "conversation_id": conv_id,
        },
    )
    assert r2.status_code == 200
    turn2 = service.stream_answer.call_args_list[1].kwargs
    assert turn2["target_product"] is None
    assert turn2["target_project"] is None
    assert turn2["target_build"] is None


def test_chat_scope_carries_without_conversation_id(app_config) -> None:
    """Real Open WebUI round-trip: Open WebUI's OpenAI-compatible
    /v1/chat/completions request does NOT send `conversation_id`, and echoes
    prior turns in `messages` history. Carry must therefore work off `history`
    alone (not `conversation_id`). A follow-up with no scope words inherits the
    prior turn's locked TurnScope when carry is enabled."""
    cfg = replace(
        app_config,
        generation=replace(app_config.generation, show_elapsed_time=False),
        api=replace(app_config.api, carry_scope_across_turns=True),
    )
    service = MagicMock()
    service.config = cfg
    service.stream_answer.return_value = _stream_result("Answer.")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: cfg
    client = TestClient(app)

    # Turn 1: scope inferred from the question text. No conversation_id sent
    # (mirrors Open WebUI). The marker must still be embedded.
    r1 = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "user", "content": "logan p1 原理图有哪些电源轨？"}
            ],
        },
    )
    assert r1.status_code == 200
    turn1 = service.stream_answer.call_args_list[0].kwargs
    assert turn1["target_product"] == "ipad"
    assert turn1["target_project"] == "logan"
    assert turn1["target_build"] == "p1"

    assistant_content = r1.json()["choices"][0]["message"]["content"]
    assert "<!-- ee-wiki-scope:" in assistant_content

    # Turn 2: follow-up with NO scope words and NO conversation_id. History
    # carries the prior reply (with marker). Scope must be inherited.
    r2 = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "user", "content": "logan p1 原理图有哪些电源轨？"},
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": "这个 board 的电源是怎么供电的？"},
            ],
        },
    )
    assert r2.status_code == 200
    turn2 = service.stream_answer.call_args_list[1].kwargs
    assert turn2["target_product"] == "ipad"
    assert turn2["target_project"] == "logan"
    assert turn2["target_build"] == "p1"


def test_chat_fa_followup_inherits_scope_without_conversation_id(app_config) -> None:
    """Exact regression for the reported bug: a Wiki->FA follow-up whose
    question carries no scope words must NOT open an unbound FA session with
    none/none/none. The prior Wiki reply embeds the `<!-- ee-wiki-scope: -->`
    marker; chat.py carries it (no conversation_id) and the FA path inherits
    ipad/logan/p1. Resembles the pasted Open WebUI session (turn 1 trace refusal
    -> turn 6 EMI/EMC follow-up)."""
    from unittest.mock import patch

    from ee_wiki.agents.fa_agent import FaAgentResult

    cfg = replace(
        app_config,
        generation=replace(app_config.generation, show_elapsed_time=False),
        api=replace(app_config.api, carry_scope_across_turns=True),
        fa=replace(app_config.fa, enabled=True),
    )
    service = MagicMock()
    service.config = cfg
    service.stream_answer.return_value = _stream_result("Answer.")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: cfg
    client = TestClient(app)

    # Turn 1: Wiki trace question -> ipad/logan/p1, marker embedded (no conv id).
    r1 = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {
                    "role": "user",
                    "content": "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace",
                },
            ],
        },
    )
    assert r1.status_code == 200
    assistant_content = r1.json()["choices"][0]["message"]["content"]
    assert "<!-- ee-wiki-scope: ipad/logan/p1 -->" in assistant_content

    # Turn 2: FA-mode follow-up with no scope words, no conversation_id.
    with (
        patch("ee_wiki.agents.fa_mode.resolve_chat_mode", return_value="fa"),
        patch("ee_wiki.agents.fa_agent.FaAgent.handle") as mock_handle,
    ):
        mock_handle.return_value = FaAgentResult(
            markdown="EMI evidence...",
            citations=[],
            routed_skills=(),
            branch="fa_agent",
        )
        r2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "ee-wiki",
                "messages": [
                    {
                        "role": "user",
                        "content": "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace",
                    },
                    {"role": "assistant", "content": assistant_content},
                    {
                        "role": "user",
                        "content": "是否有针对该走线的EMI/EMC测试数据或建议？",
                    },
                ],
            },
        )
        assert r2.status_code == 200
        kwargs = mock_handle.call_args.kwargs
        assert kwargs["product"] == "ipad"
        assert kwargs["project"] == "logan"
        assert kwargs["build"] == "p1"
