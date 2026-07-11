"""Tests for Open WebUI auxiliary task detection."""

from __future__ import annotations

from ee_wiki.api.open_webui_auxiliary import is_open_webui_auxiliary_task

_TITLE_PROMPT = """### Task:
Generate a concise, 3-5 word title with an emoji summarizing the chat history.
### Chat History:
<chat_history>
USER: 怎么配置邮箱
ASSISTANT: 打开邮件应用...
</chat_history>"""


def test_detects_title_generation_prompt() -> None:
    assert is_open_webui_auxiliary_task(_TITLE_PROMPT) is True


def test_normal_engineering_question_is_not_auxiliary() -> None:
    assert is_open_webui_auxiliary_task("怎么配置邮箱") is False


def test_task_header_without_chat_history_is_not_auxiliary() -> None:
    content = "### Task:\nGenerate a concise, 3-5 word title\n### Output:\nJSON"
    assert is_open_webui_auxiliary_task(content) is False
