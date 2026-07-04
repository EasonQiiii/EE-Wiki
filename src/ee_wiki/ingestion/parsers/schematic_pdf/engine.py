"""Qwen3-VL vision extraction for schematic PDF pages (temp3.py stage 2)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.fallback import extract_fields_from_ocr
from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
from ee_wiki.ingestion.parsers.schematic_pdf.prompt import (
    SCHEMATIC_SYSTEM_PROMPT,
    build_schematic_page_prompt,
)
from ee_wiki.ingestion.parsers.schematic_pdf.vision import parse_page_response

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 30.0


def _resolve_torch_device() -> tuple[str, object]:
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.device("cuda")
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps", torch.device("mps")
    return "cpu", torch.device("cpu")


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _heartbeat(label: str, stop_event: threading.Event, *, interval: float) -> None:
    started = time.monotonic()
    while not stop_event.wait(interval):
        elapsed = time.monotonic() - started
        logger.info("%s still running (%.0fs elapsed)", label, elapsed)


def _move_inputs_to_device(inputs: object, device: object) -> dict:
    if isinstance(inputs, dict):
        import torch

        return {
            key: value.to(device) if isinstance(value, torch.Tensor) else value
            for key, value in inputs.items()
        }
    return inputs.to(device)


def _build_vision_messages(
    *,
    system_prompt: str,
    user_prompt: str,
    crop_image: object | None,
) -> list[dict]:
    """Build Qwen3-VL chat messages (user role only; system text is inlined)."""
    user_content: list[dict] = []
    if crop_image is not None:
        user_content.append({"type": "image", "image": crop_image})
    combined_prompt = f"{system_prompt.strip()}\n\n{user_prompt.strip()}"
    user_content.append({"type": "text", "text": combined_prompt})
    return [{"role": "user", "content": user_content}]


def _prepare_vision_inputs(
    processor: object,
    messages: list[dict],
    *,
    crop_image: object | None,
) -> dict:
    """Tokenize Qwen3-VL chat messages for generation."""
    prompt_text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    if crop_image is not None:
        return processor(
            text=[prompt_text],
            images=[crop_image],
            return_tensors="pt",
        )
    return processor(text=[prompt_text], return_tensors="pt")


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
    resized = image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.LANCZOS,
    )
    logger.info(
        "Resized VLM input image from %dx%d to %dx%d (max_side=%d)",
        width,
        height,
        resized.size[0],
        resized.size[1],
        max_side,
    )
    return resized


class SchematicVisionError(EEWikiError):
    """Vision model failed to analyze a schematic page."""


@dataclass
class SchematicVisionEngine:
    """Lazy-loaded Qwen3-VL engine for schematic page reconstruction."""

    model_path: Path
    max_new_tokens: int = 4096
    temperature: float = 0.1
    do_sample: bool = True
    ocr_text_max_chars: int = 1200
    images_rel_prefix: str = "images"
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
            raise SchematicVisionError(
                "torch and transformers are required: pip install ee-wiki[ml]"
            ) from exc

        if not self.model_path.is_dir():
            raise SchematicVisionError(f"Visual model path not found: {self.model_path}")

        device_label, device = _resolve_torch_device()
        dtype = torch.float16 if device_label in {"cuda", "mps"} else torch.float32
        logger.info(
            "Loading schematic vision model from %s (device=%s, dtype=%s)",
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
        logger.info("Schematic vision model ready (device=%s)", device_label)

    def extract_page(
        self,
        layout: PageLayoutResult,
        *,
        project_id: str,
        source_stem: str = "",
    ) -> PageExtraction | None:
        """Run VLM reconstruction for one analyzed page. Returns None on failure."""
        self._source_stem = source_stem
        self._ensure_loaded()
        assert self._model is not None
        assert self._processor is not None

        try:
            import torch
            from PIL import Image
            from transformers import GenerationConfig
        except ImportError as exc:
            raise SchematicVisionError("Pillow and torch are required for vision parsing") from exc

        crop_image = None
        if layout.crop_image_bytes:
            crop_image = _resize_for_vlm(
                Image.open(BytesIO(layout.crop_image_bytes)).convert("RGB"),
                max_side=self.vlm_max_image_side,
            )
            width, height = crop_image.size
            logger.info(
                "Vision inference started: page %d crop (%dx%d, %s)",
                layout.page,
                width,
                height,
                _format_bytes(len(layout.crop_image_bytes)),
            )
        else:
            logger.info(
                "Vision inference started: page %d (OCR text only, no crop)",
                layout.page,
            )

        user_prompt = build_schematic_page_prompt(
            page=layout.page,
            project_id=project_id,
            raw_ocr_text=layout.raw_ocr_text,
            ocr_text_max_chars=self.ocr_text_max_chars,
            slice_filenames=layout.slice_filenames,
            page_image_filename=layout.page_image_filename,
            images_rel_prefix=self.images_rel_prefix,
            source_stem=self._source_stem,
        )
        messages = _build_vision_messages(
            system_prompt=SCHEMATIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            crop_image=crop_image,
        )

        try:
            inputs = _prepare_vision_inputs(
                self._processor,
                messages,
                crop_image=crop_image,
            )
            inputs = _move_inputs_to_device(inputs, self._model.device)

            heartbeat_stop = threading.Event()
            heartbeat_label = f"Vision inference page {layout.page}"
            heartbeat_thread = threading.Thread(
                target=_heartbeat,
                args=(heartbeat_label, heartbeat_stop),
                kwargs={"interval": _HEARTBEAT_INTERVAL_SECONDS},
                daemon=True,
            )
            started = time.monotonic()
            heartbeat_thread.start()
            generated = None
            try:
                generation_config = GenerationConfig(
                    max_new_tokens=self.max_new_tokens,
                    temperature=self.temperature,
                    do_sample=self.do_sample,
                )
                with torch.no_grad():
                    generated = self._model.generate(
                        **inputs,
                        generation_config=generation_config,
                    )
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=1.0)

            elapsed = time.monotonic() - started
            input_ids = inputs["input_ids"]
            trimmed = [
                out_ids[len(in_ids) :]
                for in_ids, out_ids in zip(input_ids, generated, strict=False)
            ]
            output_tokens = int(trimmed[0].shape[-1])
            text = self._processor.batch_decode(
                trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]
            del inputs, generated, trimmed, input_ids
            _release_inference_memory()
        except Exception as exc:
            _release_inference_memory()
            logger.error("VLM inference failed on page %d: %s", layout.page, exc)
            return None

        logger.info(
            "Vision inference finished: page %d in %.1fs (%d output tokens)",
            layout.page,
            elapsed,
            output_tokens,
        )

        if not text or not text.strip():
            return None

        parsed = parse_page_response(text, page=layout.page)
        ocr_components, ocr_nets, ocr_interfaces = extract_fields_from_ocr(layout.raw_ocr_text)
        return PageExtraction(
            page=parsed.page,
            markdown=parsed.markdown,
            major_components=parsed.major_components or ocr_components,
            nets=parsed.nets or ocr_nets,
            interfaces=parsed.interfaces or ocr_interfaces,
        )


def build_vision_engine(config: AppConfig) -> SchematicVisionEngine:
    """Create a vision engine from application config."""
    model_path = config.models.visual_model
    if model_path is None:
        raise SchematicVisionError("models.visual_model is not configured")
    pdf_cfg = config.schematic_pdf
    return SchematicVisionEngine(
        model_path=model_path,
        max_new_tokens=pdf_cfg.max_new_tokens,
        temperature=pdf_cfg.temperature,
        do_sample=pdf_cfg.do_sample,
        ocr_text_max_chars=pdf_cfg.ocr_text_max_chars,
        images_rel_prefix=pdf_cfg.images_rel_prefix,
        vlm_max_image_side=pdf_cfg.vlm_max_image_side,
    )
