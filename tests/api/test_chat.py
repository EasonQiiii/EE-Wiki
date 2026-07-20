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
    assert payload["choices"][0]["message"]["content"] == "RMII uses ETH_MDIO."
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
    service.llm.generate.return_value = "TASK: translate\nROLES: none"
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
    service.llm.generate.assert_called_once()
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
