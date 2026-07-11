"""Detect Open WebUI background task prompts that must bypass RAG.

Open WebUI sends title, tag, and follow-up generation through the same
``/v1/chat/completions`` connection as user questions. Those prompts embed
``<chat_history>`` and must not run hybrid retrieval — doing so can build
100k+ token prompts and block the LLM server for minutes.
"""

from __future__ import annotations

# Markers from Open WebUI ``DEFAULT_*_GENERATION_PROMPT_TEMPLATE`` strings
# (backend/open_webui/config.py). Keep case-insensitive substring checks.
_OPEN_WEBUI_TASK_MARKERS: tuple[str, ...] = (
    "generate a concise, 3-5 word title",
    "generate 1-3 broad tags",
    "suggest 3-5 relevant follow-up",
    "generate a detailed prompt for am image generation",
    "generate a detailed prompt for an image generation",
    "generate 3-5 relevant search queries",
    "generate search queries",
    "autocomplete the user's message",
    "mixture-of-agents",
    "voice mode",
)

# Short cap for JSON title/tag/follow-up outputs (Open WebUI expects small JSON).
AUXILIARY_MAX_NEW_TOKENS = 256


def is_open_webui_auxiliary_task(content: str) -> bool:
    """Return whether ``content`` is an Open WebUI background LLM task.

    Args:
        content: Last user message body from a chat completion request.

    Returns:
        True when the prompt matches Open WebUI title/tag/follow-up templates.
    """
    stripped = content.strip()
    if not stripped.startswith("### Task:"):
        return False
    lowered = stripped.lower()
    if "<chat_history>" not in lowered and "### chat history:" not in lowered:
        return False
    return any(marker in lowered for marker in _OPEN_WEBUI_TASK_MARKERS)
