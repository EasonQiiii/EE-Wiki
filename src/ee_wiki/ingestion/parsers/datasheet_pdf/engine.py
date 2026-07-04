"""Qwen3-VL engine for datasheet page extraction.

Reuses the same model-loading and inference pattern as the schematic parser
but applies datasheet-specific prompts (table extraction, graph description).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.datasheet_pdf.classify import PageType
from ee_wiki.ingestion.parsers.datasheet_pdf.prompts import (
    SYSTEM_PROMPT,
    build_graph_prompt,
    build_mixed_prompt,
    build_table_prompt,
)

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 30.0


class DatasheetVisionError(EEWikiError):
    """Vision model failed to process a datasheet page."""


def _resolve_torch_device() -> tuple[str, object]:
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.device("cuda")
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps", torch.device("mps")
    return "cpu", torch.device("cpu")


def _heartbeat(label: str, stop_event: threading.Event, *, interval: float) -> None:
    started = time.monotonic()
    while not stop_event.wait(interval):
        elapsed = time.monotonic() - started
        logger.info("%s still running (%.0fs elapsed)", label, elapsed)


def _release_inference_memory() -> None:
    """Return cached GPU/MPS memory between page inferences."""
    import gc

    gc.collect()
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        torch.mps.empty_cache()


def _resize_for_vlm(image: object, *, max_side: int) -> object:
    """Downscale large page renders to reduce VLM vision-token memory."""
    from PIL import Image

    if not isinstance(image, Image.Image):
        return image
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.LANCZOS,
    )


@dataclass
class DatasheetVisionEngine:
    """Lazy-loaded Qwen3-VL engine for datasheet page extraction."""

    model_path: Path
    max_new_tokens: int = 2048
    temperature: float = 0.1
    do_sample: bool = False
    vlm_max_image_side: int = 1280
    _model: object | None = None
    _processor: object | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        try:
            import torch
            from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        except ImportError as exc:
            raise DatasheetVisionError(
                "torch and transformers are required: pip install ee-wiki[ml]"
            ) from exc

        if not self.model_path.is_dir():
            raise DatasheetVisionError(f"Visual model path not found: {self.model_path}")

        device_label, device = _resolve_torch_device()
        dtype = torch.float16 if device_label in {"cuda", "mps"} else torch.float32
        logger.info(
            "Loading datasheet vision model from %s (device=%s, dtype=%s)",
            self.model_path,
            device_label,
            dtype,
        )
        processor = AutoProcessor.from_pretrained(str(self.model_path), trust_remote_code=True)
        if device_label == "cuda":
            model = Qwen3VLForConditionalGeneration.from_pretrained(
                str(self.model_path),
                torch_dtype=dtype,
                device_map="auto",
                trust_remote_code=True,
            )
        else:
            model = Qwen3VLForConditionalGeneration.from_pretrained(
                str(self.model_path),
                torch_dtype=dtype,
                trust_remote_code=True,
            )
            model = model.to(device)
        model.eval()
        self._model = model
        self._processor = processor
        logger.info("Datasheet vision model ready (device=%s)", device_label)

    def extract_page(
        self,
        page_image_bytes: bytes,
        page_num: int,
        page_type: PageType,
        *,
        ocr_text: str | None = None,
    ) -> str:
        """Run VLM extraction for one page and return Markdown text.

        Args:
            page_image_bytes: PNG-rendered page image.
            page_num: 0-based page number.
            page_type: Classification determining which prompt to use.
            ocr_text: Optional embedded/OCR text for reference context.

        Returns:
            Extracted Markdown content from the VLM.

        Raises:
            DatasheetVisionError: On model load or inference failure.
        """
        self._ensure_loaded()
        assert self._model is not None
        assert self._processor is not None

        try:
            import torch
            from PIL import Image
            from transformers import GenerationConfig
        except ImportError as exc:
            raise DatasheetVisionError("Pillow and torch are required") from exc

        pil_image = _resize_for_vlm(
            Image.open(BytesIO(page_image_bytes)).convert("RGB"),
            max_side=self.vlm_max_image_side,
        )

        if page_type == PageType.TABLE:
            user_prompt = build_table_prompt(ocr_text)
        elif page_type == PageType.GRAPH:
            user_prompt = build_graph_prompt(ocr_text)
        else:
            user_prompt = build_mixed_prompt(ocr_text)

        combined_prompt = f"{SYSTEM_PROMPT.strip()}\n\n{user_prompt.strip()}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_image},
                    {"type": "text", "text": combined_prompt},
                ],
            }
        ]

        try:
            prompt_text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
            inputs = self._processor(
                text=[prompt_text], images=[pil_image], return_tensors="pt",
            )
            inputs = {
                key: value.to(self._model.device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }

            heartbeat_stop = threading.Event()
            heartbeat_thread = threading.Thread(
                target=_heartbeat,
                args=(f"Datasheet VLM page {page_num + 1}", heartbeat_stop),
                kwargs={"interval": _HEARTBEAT_INTERVAL_SECONDS},
                daemon=True,
            )
            started = time.monotonic()
            heartbeat_thread.start()
            try:
                gen_config = GenerationConfig(
                    max_new_tokens=self.max_new_tokens,
                    temperature=self.temperature,
                    do_sample=self.do_sample,
                )
                with torch.no_grad():
                    generated = self._model.generate(**inputs, generation_config=gen_config)
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=1.0)

            elapsed = time.monotonic() - started
            input_ids = inputs["input_ids"]
            trimmed = [
                out_ids[len(in_ids):]
                for in_ids, out_ids in zip(input_ids, generated, strict=False)
            ]
            output_tokens = int(trimmed[0].shape[-1])
            text = self._processor.batch_decode(
                trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False,
            )[0]
            del inputs, generated, trimmed, input_ids
            _release_inference_memory()
        except Exception as exc:
            _release_inference_memory()
            logger.error("Datasheet VLM inference failed on page %d: %s", page_num + 1, exc)
            return ""

        logger.info(
            "Datasheet VLM finished: page %d in %.1fs (%d tokens)",
            page_num + 1,
            elapsed,
            output_tokens,
        )
        return text.strip() if text else ""


def build_datasheet_engine(config: AppConfig) -> DatasheetVisionEngine:
    """Create a datasheet vision engine from application config.

    Args:
        config: Loaded application configuration.

    Returns:
        Configured :class:`DatasheetVisionEngine`.

    Raises:
        DatasheetVisionError: If ``models.visual_model`` is not configured.
    """
    model_path = config.models.visual_model
    if model_path is None:
        raise DatasheetVisionError("models.visual_model is not configured")
    ds_cfg = config.datasheet_pdf
    return DatasheetVisionEngine(
        model_path=model_path,
        max_new_tokens=ds_cfg.max_new_tokens,
        temperature=ds_cfg.temperature,
        do_sample=ds_cfg.do_sample,
        vlm_max_image_side=ds_cfg.vlm_max_image_side,
    )
