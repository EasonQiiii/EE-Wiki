"""Tests for LLM-based intent classification."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ee_wiki.generation.classify import (
    VALID_TASKS,
    _parse_task_label,
    classify_agent_route,
    classify_task,
)

# ---------------------------------------------------------------------------
# _parse_task_label unit tests
# ---------------------------------------------------------------------------


class TestParseTaskLabel:
    """Parsing logic for extracting valid labels from noisy LLM output."""

    @pytest.mark.parametrize(
        "raw",
        ["wiki", "debug", "fa", "design_review", "power", "rules", "translate"],
    )
    def test_exact_match(self, raw: str) -> None:
        assert _parse_task_label(raw) == raw

    @pytest.mark.parametrize("raw", ["  wiki  ", "Wiki", "DEBUG", "FA", "Design_Review"])
    def test_case_and_whitespace(self, raw: str) -> None:
        result = _parse_task_label(raw)
        assert result is not None
        assert result in VALID_TASKS

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('"debug"', "debug"),
            ("'fa'", "fa"),
            ("`wiki`", "wiki"),
            ("wiki.", "wiki"),
            ("debug。", "debug"),
        ],
    )
    def test_quotes_and_punctuation_stripped(self, raw: str, expected: str) -> None:
        assert _parse_task_label(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("任务: debug", "debug"),
            ("category: design_review", "design_review"),
            ("The answer is fa", "fa"),
        ],
    )
    def test_containment_match(self, raw: str, expected: str) -> None:
        assert _parse_task_label(raw) == expected

    @pytest.mark.parametrize("raw", ["unknown", "hello world", "", "  "])
    def test_no_match_returns_none(self, raw: str) -> None:
        assert _parse_task_label(raw) is None

    def test_multiline_uses_first_line(self) -> None:
        assert _parse_task_label("debug\nsome explanation here") == "debug"


# ---------------------------------------------------------------------------
# classify_task integration tests (mock LLM)
# ---------------------------------------------------------------------------


class TestClassifyTask:
    """End-to-end classification with mocked LLM backend."""

    @pytest.fixture()
    def mock_llm(self) -> MagicMock:
        llm = MagicMock()
        llm.generate_stream = None
        return llm

    @pytest.fixture()
    def repo_root(self) -> str:
        from pathlib import Path

        return Path(__file__).resolve().parents[2]

    def test_valid_label_returned(self, mock_llm, repo_root) -> None:
        mock_llm.generate.return_value = "debug"
        result = classify_task("UART不通", llm=mock_llm, repo_root=repo_root)
        assert result == "debug"
        mock_llm.generate.assert_called_once()

    def test_noisy_output_falls_back_correctly(self, mock_llm, repo_root) -> None:
        mock_llm.generate.return_value = "任务: fa"
        result = classify_task("芯片烧了", llm=mock_llm, repo_root=repo_root)
        assert result == "fa"

    def test_invalid_output_returns_default(self, mock_llm, repo_root) -> None:
        mock_llm.generate.return_value = "banana"
        result = classify_task("test", llm=mock_llm, repo_root=repo_root)
        assert result == "wiki"

    def test_empty_output_returns_default(self, mock_llm, repo_root) -> None:
        mock_llm.generate.return_value = ""
        result = classify_task("test", llm=mock_llm, repo_root=repo_root)
        assert result == "wiki"

    def test_exception_returns_default(self, mock_llm, repo_root) -> None:
        mock_llm.generate.side_effect = RuntimeError("model crashed")
        result = classify_task("test", llm=mock_llm, repo_root=repo_root)
        assert result == "wiki"

    def test_cancel_returns_default(self, mock_llm, repo_root) -> None:
        import threading

        cancel = threading.Event()
        cancel.set()
        result = classify_task(
            "test", llm=mock_llm, repo_root=repo_root, cancel_event=cancel,
        )
        assert result == "wiki"
        mock_llm.generate.assert_not_called()

    def test_custom_default_task(self, mock_llm, repo_root) -> None:
        mock_llm.generate.return_value = "gibberish"
        result = classify_task(
            "test", llm=mock_llm, repo_root=repo_root, default_task="debug",
        )
        assert result == "debug"

    def test_streaming_llm(self, repo_root) -> None:
        llm = MagicMock()

        def _fake_stream(prompt, max_new_tokens=16, cancel_event=None):
            yield "design"
            yield "_review"

        llm.generate_stream = _fake_stream
        result = classify_task("原理图审查", llm=llm, repo_root=repo_root)
        assert result == "design_review"


class TestClassifyAgentRoute:
    """Shared Supervisor task-and-role semantic routing."""

    @pytest.fixture()
    def repo_root(self):
        from pathlib import Path

        return Path(__file__).resolve().parents[2]

    def test_returns_task_and_multiple_roles(self, repo_root) -> None:
        llm = MagicMock()
        llm.generate_stream = None
        llm.generate.return_value = "TASK: design_review\nROLES: pcb, si"

        route = classify_agent_route(
            "检查 DDR layout 和眼图风险",
            llm=llm,
            repo_root=repo_root,
            valid_roles=frozenset({"hw", "fa", "pcb", "si", "mfg", "power"}),
        )

        assert route is not None
        assert route.task == "design_review"
        assert route.roles == ("pcb", "si")

    def test_none_roles_is_valid_passthrough(self, repo_root) -> None:
        llm = MagicMock()
        llm.generate_stream = None
        llm.generate.return_value = "TASK: translate\nROLES: none"

        route = classify_agent_route(
            "translate the previous answer",
            llm=llm,
            repo_root=repo_root,
            valid_roles=frozenset({"hw", "fa"}),
        )

        assert route is not None
        assert route.task == "translate"
        assert route.roles == ()

    def test_malformed_output_requests_fallback(self, repo_root) -> None:
        llm = MagicMock()
        llm.generate_stream = None
        llm.generate.return_value = "pcb"

        route = classify_agent_route(
            "review layout",
            llm=llm,
            repo_root=repo_root,
            valid_roles=frozenset({"pcb"}),
        )

        assert route is None

    def test_truncates_to_max_roles(self, repo_root) -> None:
        llm = MagicMock()
        llm.generate_stream = None
        llm.generate.return_value = "TASK: design_review\nROLES: pcb, si, power, mfg"

        route = classify_agent_route(
            "审查 layout、SI 和电源风险",
            llm=llm,
            repo_root=repo_root,
            valid_roles=frozenset({"hw", "fa", "pcb", "si", "mfg", "power"}),
            max_roles=3,
        )

        assert route is not None
        assert route.roles == ("pcb", "si", "power")
