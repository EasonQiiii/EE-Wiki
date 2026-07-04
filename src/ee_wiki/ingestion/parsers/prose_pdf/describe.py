"""Generate searchable text descriptions for extracted PDF images."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.prose_pdf.images import ExtractedImage

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)


def describe_image_ocr(
    image: ExtractedImage,
    *,
    ocr_language: str = "eng",
    tessdata_dir: str | None = None,
) -> str:
    """Extract text from an image via Tesseract OCR.

    Args:
        image: Extracted image with PNG bytes.
        ocr_language: Tesseract language code.
        tessdata_dir: Optional tessdata directory path.

    Returns:
        OCR text found in the image, or empty string.
    """
    try:
        import fitz
    except ImportError:
        logger.warning("pymupdf not available; cannot OCR image %s", image.filename)
        return ""

    try:
        pixmap = fitz.Pixmap(image.png_bytes)
        page_rect = fitz.Rect(0, 0, pixmap.width, pixmap.height)
        pdf = fitz.open()
        page = pdf.new_page(width=page_rect.width, height=page_rect.height)
        page.insert_image(page_rect, pixmap=pixmap)

        ocr_kwargs: dict[str, object] = {
            "dpi": 150,
            "full": True,
            "language": ocr_language,
        }
        if tessdata_dir:
            ocr_kwargs["tessdata"] = tessdata_dir
        textpage = page.get_textpage_ocr(**ocr_kwargs)
        text = page.get_text("text", textpage=textpage).strip()
        pdf.close()
    except Exception as exc:
        logger.warning("OCR failed for image %s: %s", image.filename, exc)
        return ""

    if text:
        logger.debug(
            "OCR for %s: %d chars extracted",
            image.filename,
            len(text),
        )
    return text


def describe_image_vlm(
    image: ExtractedImage,
    *,
    model_path: Path,
    max_new_tokens: int = 512,
    max_image_side: int = 1280,
) -> str:
    """Generate a structured description of an image using a vision-language model.

    Args:
        image: Extracted image with PNG bytes.
        model_path: Path to the VLM model directory.
        max_new_tokens: Token budget for generation.
        max_image_side: Downscale images larger than this.

    Returns:
        VLM description text, or empty string on failure.
    """
    try:
        import torch
        from PIL import Image
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
    except ImportError as exc:
        logger.warning("VLM dependencies unavailable: %s", exc)
        return ""

    if not model_path.is_dir():
        logger.warning("VLM model path not found: %s", model_path)
        return ""

    try:
        pil_image = Image.open(BytesIO(image.png_bytes)).convert("RGB")
        width, height = pil_image.size
        longest = max(width, height)
        if longest > max_image_side:
            scale = max_image_side / longest
            pil_image = pil_image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )

        device_label = "cpu"
        if torch.cuda.is_available():
            device_label = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device_label = "mps"
        device = torch.device(device_label)
        dtype = torch.float16 if device_label in {"cuda", "mps"} else torch.float32

        processor = AutoProcessor.from_pretrained(str(model_path), trust_remote_code=True)
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(model_path),
            torch_dtype=dtype,
            trust_remote_code=True,
        )
        if device_label != "cuda":
            model = model.to(device)
        model.eval()

        system_prompt = (
            "你是一个电子工程领域专家。请用中文简洁描述这张图片的内容，"
            "包括图片类型（如框图、波形图、PCB layout、电路图等）、"
            "涉及的关键器件/信号/数值。只输出描述，不要加任何前缀。"
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_image},
                    {"type": "text", "text": system_prompt},
                ],
            }
        ]
        prompt_text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
        )
        inputs = processor(text=[prompt_text], images=[pil_image], return_tensors="pt")
        inputs = {
            k: v.to(device) if isinstance(v, torch.Tensor) else v
            for k, v in inputs.items()
        }

        with torch.no_grad():
            generated = model.generate(**inputs, max_new_tokens=max_new_tokens)
        trimmed = generated[0][inputs["input_ids"].shape[-1]:]
        text = processor.decode(trimmed, skip_special_tokens=True).strip()

        del model, processor, inputs, generated
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif device_label == "mps":
            torch.mps.empty_cache()

        logger.info("VLM description for %s: %d chars", image.filename, len(text))
        return text

    except Exception as exc:
        logger.error("VLM description failed for %s: %s", image.filename, exc)
        return ""


def describe_images(
    images: list[ExtractedImage],
    *,
    mode: str,
    ocr_language: str = "eng",
    tessdata_dir: str | None = None,
    model_path: Path | None = None,
    max_new_tokens: int = 512,
    max_image_side: int = 1280,
) -> dict[str, str]:
    """Generate text descriptions for a batch of extracted images.

    Args:
        images: Images to describe.
        mode: Description mode — ``off``, ``ocr``, or ``vlm``.
        ocr_language: Tesseract language code (for ``ocr`` mode).
        tessdata_dir: Optional tessdata directory (for ``ocr`` mode).
        model_path: VLM model path (required for ``vlm`` mode).
        max_new_tokens: VLM token budget.
        max_image_side: VLM image downscale limit.

    Returns:
        Mapping from image filename to description text.
    """
    if mode == "off" or not images:
        return {}

    descriptions: dict[str, str] = {}

    for img in images:
        if mode == "ocr":
            text = describe_image_ocr(
                img,
                ocr_language=ocr_language,
                tessdata_dir=tessdata_dir,
            )
        elif mode == "vlm":
            if model_path is None:
                logger.warning("VLM model path not configured; skipping image description")
                break
            text = describe_image_vlm(
                img,
                model_path=model_path,
                max_new_tokens=max_new_tokens,
                max_image_side=max_image_side,
            )
        else:
            logger.warning("Unknown describe_images mode: %s", mode)
            break

        if text:
            descriptions[img.filename] = text

    logger.info(
        "Described %d / %d images (mode=%s)",
        len(descriptions),
        len(images),
        mode,
    )
    return descriptions
