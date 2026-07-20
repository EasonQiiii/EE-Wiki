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
from ee_wiki.retrieval.scope_catalog import ScopeCatalog


class TestParsePrepareOutput:
    """Parsing for merged QUERY/TASK output."""

    def test_parses_query_and_task(self) -> None:
        raw = "QUERY: RMII interface pinout\nTASK: wiki"
        result = _parse_prepare_output(
            raw,
            question="它呢？",
            default_task="wiki",
            classify=True,
            catalog=None,
            scope_inference=False,
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
            catalog=None,
            scope_inference=False,
        )
        assert result.retrieval_query == "UART wiring"
        assert result.task == "wiki"

    def test_classify_disabled_returns_none_task(self) -> None:
        result = _parse_prepare_output(
            "QUERY: UART wiring\nTASK: debug",
            question="UART不通",
            default_task="wiki",
            classify=False,
            catalog=None,
            scope_inference=False,
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

    def test_scope_inference_runs_on_first_message(self) -> None:
        assert should_prepare_query(
            "Logan p1 LCD pins",
            [],
            query_rewrite=False,
            task_classification=False,
            caller_task=None,
            scope_inference=True,
            scope_inference_mode="merged",
        )

    def test_scope_inference_skipped_when_api_scope_set(self) -> None:
        assert not should_prepare_query(
            "LCD pins",
            [],
            query_rewrite=False,
            task_classification=False,
            caller_task=None,
            scope_inference=True,
            caller_has_scope=True,
        )


class TestParsePrepareScope:
    """Parsing PRODUCT/REVISION/LAYER lines."""

    @pytest.fixture()
    def catalog(self, data_layout) -> ScopeCatalog:
        return ScopeCatalog(
            products={"iphone": {"logan": frozenset({"p1", "p2"})}},
            enterprise_segment=data_layout.enterprise_project,
            project_shared_segment=data_layout.project_shared_build,
        )

    def test_parses_product_revision_layer(self, catalog: ScopeCatalog) -> None:
        raw = (
            "PRODUCT: iphone\n"
            "REVISION: p1\n"
            "LAYER: build\n"
            "QUERY: LCD touch pins\n"
            "TASK: wiki"
        )
        result = _parse_prepare_output(
            raw,
            question="iPhone p1 lcd的pin有哪些",
            default_task="wiki",
            classify=True,
            catalog=catalog,
            scope_inference=True,
        )
        assert result.product == "iphone"
        assert result.revision == "p1"
        assert result.layer == "build"
        assert result.retrieval_query == "LCD touch pins"

    def test_rejects_global_as_product(self, catalog: ScopeCatalog) -> None:
        raw = (
            "PRODUCT: global\n"
            "REVISION: none\n"
            "LAYER: enterprise\n"
            "QUERY: CH340 pins\n"
            "TASK: wiki"
        )
        result = _parse_prepare_output(
            raw,
            question="global CH340 pins",
            default_task="wiki",
            classify=True,
            catalog=catalog,
            scope_inference=True,
        )
        assert result.product is None
        assert result.revision is None
        assert result.layer == "enterprise"


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

    def test_prepare_includes_history_for_semantic_classification(self, repo_root: Path) -> None:
        llm = MagicMock()
        captured: dict[str, str] = {}

        def _fake_generate(prompt, max_new_tokens=PREPARE_MAX_TOKENS, cancel_event=None):
            captured["prompt"] = prompt
            return "QUERY: TPS2514A max input voltage\nTASK: wiki"

        llm.generate_stream = None
        llm.generate.side_effect = _fake_generate

        history = [
            ConversationTurn(role="user", content="ipad快速放电指令"),
            ConversationTurn(role="assistant", content="方案 A"),
        ]
        prepare_query(
            "What is the maximum input voltage for TPS2514A on Logan P1?",
            history,
            llm=llm,
            repo_root=repo_root,
        )
        assert "方案 A" in captured["prompt"]
        assert "TPS2514A" in captured["prompt"]

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
