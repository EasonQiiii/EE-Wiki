"""Tests for query rewriting module."""

from __future__ import annotations

from unittest.mock import MagicMock

from ee_wiki.retrieval.rewrite import (
    ConversationTurn,
    format_history,
    needs_answer_history,
    needs_rewrite,
    rewrite_query,
)


class TestNeedsRewrite:
    """Tests for the needs_rewrite heuristic."""

    def test_empty_history_returns_false(self) -> None:
        assert needs_rewrite("What is VBAT?", []) is False

    def test_no_prior_user_returns_false(self) -> None:
        history = [ConversationTurn(role="system", content="You are a helper.")]
        assert needs_rewrite("What is VBAT?", history) is False

    def test_short_with_pronoun_returns_true(self) -> None:
        history = [
            ConversationTurn(role="user", content="Tell me about TPS2514A."),
            ConversationTurn(role="assistant", content="TPS2514A is a USB switch."),
        ]
        assert needs_rewrite("它的使能引脚在哪？", history) is True

    def test_short_with_english_pronoun_returns_true(self) -> None:
        history = [
            ConversationTurn(role="user", content="What is U5?"),
            ConversationTurn(role="assistant", content="U5 is a regulator."),
        ]
        assert needs_rewrite("What about that chip?", history) is True

    def test_self_contained_long_question_returns_false(self) -> None:
        history = [
            ConversationTurn(role="user", content="What is VBAT?"),
            ConversationTurn(role="assistant", content="VBAT is the battery voltage rail."),
        ]
        question = "What is the maximum voltage rating for the TPS2514A USB switch on Logan P1?"
        assert needs_rewrite(question, history) is False

    def test_very_short_question_with_history_returns_true(self) -> None:
        history = [
            ConversationTurn(role="user", content="Explain the power tree."),
            ConversationTurn(role="assistant", content="The power tree has three stages."),
        ]
        assert needs_rewrite("第二级呢？", history) is True

    def test_continuation_keyword_triggers_rewrite(self) -> None:
        history = [
            ConversationTurn(role="user", content="Describe the USB section."),
            ConversationTurn(role="assistant", content="USB uses a switch IC."),
        ]
        assert needs_rewrite("继续展开说说", history) is True


class TestNeedsAnswerHistory:
    """Tests for when conversation history should reach answer prompts."""

    def test_unrelated_long_question_returns_false(self) -> None:
        history = [
            ConversationTurn(role="user", content="ipad快速放电指令"),
            ConversationTurn(role="assistant", content="方案 A：OSDBatteryTester [1]"),
        ]
        question = "What is the maximum input voltage for TPS2514A on Logan P1?"
        assert needs_answer_history(question, history) is False

    def test_prepared_translate_task_returns_true(self) -> None:
        history = [
            ConversationTurn(role="user", content="ipad快速放电指令"),
            ConversationTurn(role="assistant", content="方案 A"),
        ]
        question = "Please render the previous answer in English for the team."
        assert needs_answer_history(
            question,
            history,
            prepared_task="translate",
        ) is True

    def test_rewritten_retrieval_query_returns_true(self) -> None:
        history = [
            ConversationTurn(role="user", content="Tell me about TPS2514A."),
            ConversationTurn(role="assistant", content="TPS2514A is a USB switch."),
        ]
        question = "它的EN接在哪？"
        assert needs_answer_history(
            question,
            history,
            retrieval_query="Logan P1 TPS2514A EN pin connection",
        ) is True

    def test_short_follow_up_uses_rewrite_heuristic(self) -> None:
        history = [
            ConversationTurn(role="user", content="ipad快速放电指令"),
            ConversationTurn(role="assistant", content="方案 A"),
        ]
        assert needs_answer_history("用英文", history) is True


class TestFormatHistory:
    """Tests for formatting conversation history."""

    def test_formats_user_and_assistant(self) -> None:
        history = [
            ConversationTurn(role="user", content="Hello"),
            ConversationTurn(role="assistant", content="Hi there"),
        ]
        result = format_history(history)
        assert "[User]: Hello" in result
        assert "[Assistant]: Hi there" in result

    def test_truncates_long_assistant_responses(self) -> None:
        long_text = "A" * 500
        history = [
            ConversationTurn(role="assistant", content=long_text),
        ]
        result = format_history(history)
        assert "..." in result
        assert len(result) < 500

    def test_limits_to_max_turns(self) -> None:
        history = [
            ConversationTurn(role="user", content=f"Message {i}")
            for i in range(10)
        ]
        result = format_history(history, max_turns=3)
        assert "Message 7" in result
        assert "Message 9" in result
        assert "Message 0" not in result


class TestRewriteQuery:
    """Tests for the full rewrite_query function."""

    def test_skips_when_no_history(self, repo_root) -> None:
        llm = MagicMock()
        result = rewrite_query(
            "What is VBAT?",
            [],
            llm=llm,
            repo_root=repo_root,
        )
        assert result == "What is VBAT?"
        llm.generate.assert_not_called()
        llm.generate_stream.assert_not_called()

    def test_skips_self_contained_question(self, repo_root) -> None:
        llm = MagicMock()
        history = [
            ConversationTurn(role="user", content="What is VBAT?"),
            ConversationTurn(role="assistant", content="VBAT is battery voltage."),
        ]
        result = rewrite_query(
            "What is the maximum input voltage for TPS2514A on Logan P1 board?",
            history,
            llm=llm,
            repo_root=repo_root,
        )
        assert "TPS2514A" in result
        llm.generate.assert_not_called()

    def test_calls_llm_for_ambiguous_question(self, repo_root) -> None:
        llm = MagicMock()
        llm.generate_stream = MagicMock(
            return_value=iter(["Logan P1 TPS2514A", " EN pin connection"])
        )
        history = [
            ConversationTurn(role="user", content="Tell me about TPS2514A on Logan P1."),
            ConversationTurn(role="assistant", content="TPS2514A is a USB switch IC."),
        ]
        result = rewrite_query(
            "它的EN接在哪？",
            history,
            llm=llm,
            repo_root=repo_root,
        )
        assert result == "Logan P1 TPS2514A EN pin connection"
        llm.generate_stream.assert_called_once()

    def test_returns_original_on_llm_failure(self, repo_root) -> None:
        llm = MagicMock()
        llm.generate_stream = MagicMock(side_effect=RuntimeError("model crash"))
        history = [
            ConversationTurn(role="user", content="What is U5?"),
            ConversationTurn(role="assistant", content="U5 is a regulator."),
        ]
        result = rewrite_query(
            "那个芯片的datasheet?",
            history,
            llm=llm,
            repo_root=repo_root,
        )
        assert result == "那个芯片的datasheet?"

    def test_returns_original_on_empty_llm_response(self, repo_root) -> None:
        llm = MagicMock()
        llm.generate_stream = MagicMock(return_value=iter([""]))
        history = [
            ConversationTurn(role="user", content="What is U5?"),
            ConversationTurn(role="assistant", content="U5 is a regulator."),
        ]
        result = rewrite_query(
            "这个呢？",
            history,
            llm=llm,
            repo_root=repo_root,
        )
        assert result == "这个呢？"

    def test_respects_cancel_event(self, repo_root) -> None:
        import threading

        llm = MagicMock()
        cancel = threading.Event()
        cancel.set()
        history = [
            ConversationTurn(role="user", content="What is U5?"),
            ConversationTurn(role="assistant", content="U5 is a regulator."),
        ]
        result = rewrite_query(
            "它在哪？",
            history,
            llm=llm,
            repo_root=repo_root,
            cancel_event=cancel,
        )
        assert result == "它在哪？"
        llm.generate.assert_not_called()


class TestRenderRewriteTemplate:
    """Test the rewrite template loading and rendering."""

    def test_load_rewrite_template(self, repo_root) -> None:
        from ee_wiki.retrieval.rewrite import _load_rewrite_template

        template = _load_rewrite_template(repo_root)
        assert "{{history}}" in template
        assert "{{question}}" in template

    def test_render_rewrite_template(self) -> None:
        from ee_wiki.retrieval.rewrite import _render_rewrite_prompt

        template = "History:\n{{history}}\n\nQuestion: {{question}}\n\nRewritten:"
        result = _render_rewrite_prompt(
            template,
            history="[User]: What is U5?\n[Assistant]: It's a regulator.",
            question="它的输出电压是多少？",
        )
        assert "[User]: What is U5?" in result
        assert "它的输出电压是多少？" in result
        assert "{{" not in result
