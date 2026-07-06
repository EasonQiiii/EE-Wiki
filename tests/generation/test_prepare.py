"""Tests for merged query prepare (rewrite + task classification)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ee_wiki.generation.prepare import (
    PREPARE_MAX_TOKENS,
    PreparedQuery,
    _parse_prepare_output,
    prepare_query,
    should_prepare_query,
)
from ee_wiki.retrieval.rewrite import ConversationTurn


class TestParsePrepareOutput:
    """Parsing for merged QUERY/TASK output."""

    def test_parses_query_and_task(self) -> None:
        raw = "QUERY: RMII interface pinout\nTASK: wiki"
        result = _parse_prepare_output(
            raw,
            question="它呢？",
            default_task="wiki",
            classify=True,
        )
        assert result == PreparedQuery(
            retrieval_query="RMII interface pinout",
            task="wiki",
        )

    def test_missing_task_uses_default(self) -> None:
        result = _parse_prepare_output(
            "QUERY: UART wiring",
            question="UART不通",
            default_task="wiki",
            classify=True,
        )
        assert result.retrieval_query == "UART wiring"
        assert result.task == "wiki"

    def test_classify_disabled_returns_none_task(self) -> None:
        result = _parse_prepare_output(
            "QUERY: UART wiring\nTASK: debug",
            question="UART不通",
            default_task="wiki",
            classify=False,
        )
        assert result.task is None


class TestShouldPrepareQuery:
    """Heuristics for when merged prepare should run."""

    def test_first_turn_with_classification(self) -> None:
        assert should_prepare_query(
            "UART不通",
            [],
            query_rewrite=True,
            task_classification=True,
            caller_task=None,
        )

    def test_explicit_task_skips_prepare(self) -> None:
        assert not should_prepare_query(
            "UART不通",
            [],
            query_rewrite=True,
            task_classification=True,
            caller_task="fa",
        )

    def test_follow_up_with_pronoun(self) -> None:
        history = [
            ConversationTurn(role="user", content="U0902 的 VBAT 在哪？"),
            ConversationTurn(role="assistant", content="VBAT 在 pin 3。"),
        ]
        assert should_prepare_query(
            "它的使能引脚呢？",
            history,
            query_rewrite=True,
            task_classification=True,
            caller_task=None,
        )

    def test_both_disabled(self) -> None:
        assert not should_prepare_query(
            "test",
            [],
            query_rewrite=False,
            task_classification=False,
            caller_task=None,
        )


class TestPrepareQuery:
    """End-to-end merged prepare with mocked LLM."""

    @pytest.fixture()
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def test_merged_output_parsed(self, repo_root: Path) -> None:
        llm = MagicMock()
        llm.generate_stream = None
        llm.generate.return_value = "QUERY: UART debug steps\nTASK: debug"

        result = prepare_query(
            "UART不通",
            [],
            llm=llm,
            repo_root=repo_root,
        )
        assert result.retrieval_query == "UART debug steps"
        assert result.task == "debug"
        llm.generate.assert_called_once()
        assert llm.generate.call_args.kwargs["max_new_tokens"] == PREPARE_MAX_TOKENS

    def test_streaming_llm(self, repo_root: Path) -> None:
        llm = MagicMock()

        def _fake_stream(prompt, max_new_tokens=PREPARE_MAX_TOKENS, cancel_event=None):
            yield "QUERY: schematic review\nTASK: design"
            yield "_review"

        llm.generate_stream = _fake_stream

        result = prepare_query(
            "帮我审查原理图",
            [],
            llm=llm,
            repo_root=repo_root,
        )
        assert result.retrieval_query == "schematic review"
        assert result.task == "design_review"
