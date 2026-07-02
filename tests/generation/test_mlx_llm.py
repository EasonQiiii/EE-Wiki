"""Tests for MLX LLM backend."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ee_wiki.generation.llm.errors import LlmLoadError
from ee_wiki.generation.llm.mlx import MlxLlmBackend, _format_prompt


def test_format_prompt_uses_chat_template_when_available() -> None:
    tokenizer = MagicMock()
    tokenizer.chat_template = "<template>"
    tokenizer.apply_chat_template.return_value = "<formatted>"

    result = _format_prompt(tokenizer, "Hello")

    assert result == "<formatted>"
    tokenizer.apply_chat_template.assert_called_once()


def test_mlx_generate_applies_chat_template_and_returns_text(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    backend = MlxLlmBackend(model_dir, max_new_tokens=128)

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    mock_tokenizer.chat_template = "<template>"
    mock_tokenizer.apply_chat_template.return_value = "<formatted>"

    mock_mlx = MagicMock()
    mock_mlx.load.return_value = (mock_model, mock_tokenizer)
    mock_mlx.generate.return_value = "Answer text"

    with patch.dict(sys.modules, {"mlx_lm": mock_mlx}):
        result = backend.generate("Question?")

    assert result == "Answer text"
    mock_mlx.load.assert_called_once_with(str(model_dir))
    mock_mlx.generate.assert_called_once_with(
        mock_model,
        mock_tokenizer,
        prompt="<formatted>",
        max_tokens=128,
        verbose=False,
    )


def test_mlx_generate_stream_yields_deltas(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    backend = MlxLlmBackend(model_dir, max_new_tokens=64)

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    mock_tokenizer.chat_template = None

    first = MagicMock(text="Hel")
    second = MagicMock(text="Hello")

    mock_mlx = MagicMock()
    mock_mlx.load.return_value = (mock_model, mock_tokenizer)
    mock_mlx.stream_generate.return_value = [first, second]

    with patch.dict(sys.modules, {"mlx_lm": mock_mlx}):
        chunks = list(backend.generate_stream("Question?"))

    assert chunks == ["Hel", "lo"]
    mock_mlx.stream_generate.assert_called_once()


def test_mlx_missing_dependency_raises_load_error(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    backend = MlxLlmBackend(model_dir)

    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "mlx_lm":
            raise ImportError("no mlx")
        return real_import(name, *args, **kwargs)

    sys.modules.pop("mlx_lm", None)
    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(LlmLoadError, match="mlx-lm is required"):
            backend.generate("Question?")
