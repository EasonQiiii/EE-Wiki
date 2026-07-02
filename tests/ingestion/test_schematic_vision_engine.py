"""Tests for schematic vision engine helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from ee_wiki.ingestion.parsers.schematic_pdf.engine import (
    _build_vision_messages,
    _prepare_vision_inputs,
    _resize_for_vlm,
)


def test_build_vision_messages_inlines_system_prompt() -> None:
    messages = _build_vision_messages(
        system_prompt="System rules",
        user_prompt="User task",
        crop_image=None,
    )
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    text_block = messages[0]["content"][-1]
    assert text_block["type"] == "text"
    assert "System rules" in text_block["text"]
    assert "User task" in text_block["text"]


def test_prepare_vision_inputs_uses_processor_not_tokenized_template() -> None:
    processor = MagicMock()
    processor.apply_chat_template.return_value = "<prompt>"
    processor.return_value = {"input_ids": "tensor"}

    messages = _build_vision_messages(
        system_prompt="System",
        user_prompt="Task",
        crop_image="image-object",
    )
    inputs = _prepare_vision_inputs(processor, messages, crop_image="image-object")

    processor.apply_chat_template.assert_called_once_with(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    processor.assert_called_once_with(
        text=["<prompt>"],
        images=["image-object"],
        return_tensors="pt",
    )
    assert inputs == {"input_ids": "tensor"}


def test_resize_for_vlm_downscales_large_images() -> None:
    from PIL import Image

    image = Image.new("RGB", (1684, 1190), color="white")
    resized = _resize_for_vlm(image, max_side=1280)
    assert max(resized.size) == 1280
