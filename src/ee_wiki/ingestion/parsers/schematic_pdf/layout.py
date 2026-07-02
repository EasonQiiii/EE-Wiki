"""LayoutLMv3 figure detection and crop extraction for schematic PDF pages."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.prompt import schematic_image_slug

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)


class SchematicLayoutError(EEWikiError):
    """Layout analysis failed for a schematic page."""


@dataclass(frozen=True)
class PageLayoutResult:
    """Layout analysis output for one PDF page."""

    page: int
    raw_ocr_text: str
    crop_image_bytes: bytes | None
    slice_filenames: list[str]


def _extract_text_and_boxes(page, zoom_factor: float, img_w: int, img_h: int) -> tuple[list[str], list[list[int]]]:
    words = page.get_text("words")
    text_list: list[str] = []
    boxes_list: list[list[int]] = []
    for word in words:
        text_list.append(word[4])
        x0 = max(0, min(int((word[0] * zoom_factor) / img_w * 1000), 1000))
        y0 = max(0, min(int((word[1] * zoom_factor) / img_h * 1000), 1000))
        x1 = max(0, min(int((word[2] * zoom_factor) / img_w * 1000), 1000))
        y1 = max(0, min(int((word[3] * zoom_factor) / img_h * 1000), 1000))
        boxes_list.append([x0, y0, x1, y1])
    if not text_list:
        return [" "], [[0, 0, 0, 0]]
    return text_list, boxes_list


@dataclass
class SchematicLayoutEngine:
    """Lazy-loaded LayoutLMv3 engine for schematic figure cropping."""

    model_path: Path
    layout_zoom: float = 2.0
    min_figure_area: int = 10_000
    _processor: object | None = None
    _model: object | None = None
    _id2label: dict[int, str] | None = None
    _device: object | None = None
    _available: bool | None = None

    def _ensure_loaded(self) -> bool:
        if self._available is False:
            return False
        if self._model is not None and self._processor is not None:
            return True
        if not self.model_path.is_dir():
            logger.warning("Layout model path not found, skipping figure crop: %s", self.model_path)
            self._available = False
            return False
        try:
            import torch
            from transformers import LayoutLMv3ForTokenClassification, LayoutLMv3Processor
        except ImportError as exc:
            logger.warning("LayoutLMv3 dependencies unavailable: %s", exc)
            self._available = False
            return False

        try:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            processor = LayoutLMv3Processor.from_pretrained(str(self.model_path))
            if hasattr(processor, "image_processor"):
                processor.image_processor.apply_ocr = False
            elif hasattr(processor, "feature_extractor"):
                processor.feature_extractor.apply_ocr = False

            model = LayoutLMv3ForTokenClassification.from_pretrained(str(self.model_path)).to(device)
            model.eval()
            self._processor = processor
            self._model = model
            self._id2label = model.config.id2label
            self._device = device
            self._available = True
            logger.info("Schematic layout model ready: %s (device=%s)", self.model_path.name, device)
            return True
        except Exception as exc:
            logger.warning("Failed to load layout model, using OCR-only mode: %s", exc)
            self._available = False
            return False

    def analyze_page(
        self,
        pdf_path: Path,
        page_index: int,
        *,
        images_dir: Path | None,
        source_stem: str,
    ) -> PageLayoutResult:
        """Run layout analysis and optional figure cropping for one PDF page."""
        try:
            import fitz
            from PIL import Image
        except ImportError as exc:
            raise SchematicLayoutError("pymupdf and Pillow are required for layout analysis") from exc

        page_id = page_index + 1
        try:
            document = fitz.open(pdf_path)
            page = document.load_page(page_index)
            zoom = self.layout_zoom
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            img_w, img_h = image.size
            raw_ocr_text = page.get_text("text").strip()
            text_list, boxes_list = _extract_text_and_boxes(page, zoom, img_w, img_h)
            document.close()
        except Exception as exc:
            raise SchematicLayoutError(f"Cannot render PDF page {page_id}: {pdf_path}") from exc

        slice_filenames: list[str] = []
        best_crop_bytes: bytes | None = None

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        best_crop_bytes = buffer.getvalue()

        if self._ensure_loaded():
            assert self._processor is not None
            assert self._model is not None
            assert self._id2label is not None
            assert self._device is not None

            import torch

            encoding = self._processor(
                image,
                text_list,
                boxes=boxes_list,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )
            encoding = {
                key: value.to(self._device) if isinstance(value, torch.Tensor) else value
                for key, value in encoding.items()
            }
            keep_keys = {"input_ids", "attention_mask", "bbox", "pixel_values"}
            encoding = {key: value for key, value in encoding.items() if key in keep_keys}

            with torch.no_grad():
                outputs = self._model(**encoding)

            predictions = outputs.logits.argmax(-1).squeeze().tolist()
            token_boxes = encoding["bbox"].squeeze().tolist()
            if isinstance(predictions, int):
                predictions = [predictions]
                token_boxes = [token_boxes]

            figure_boxes: list[list[int]] = []
            for pred, box in zip(predictions, token_boxes, strict=False):
                if box == [0, 0, 0, 0]:
                    continue
                if self._id2label[pred].lower() != "figure":
                    continue
                figure_boxes.append(
                    [
                        max(0, int(box[0] * img_w / 1000)),
                        max(0, int(box[1] * img_h / 1000)),
                        min(img_w, int(box[2] * img_w / 1000)),
                        min(img_h, int(box[3] * img_h / 1000)),
                    ]
                )

            if figure_boxes:
                figure_boxes.sort(key=lambda box: (box[2] - box[0]) * (box[3] - box[1]), reverse=True)
                slug = schematic_image_slug(source_stem)
                if images_dir is not None:
                    images_dir.mkdir(parents=True, exist_ok=True)
                for idx, box in enumerate(figure_boxes):
                    area = (box[2] - box[0]) * (box[3] - box[1])
                    if area < self.min_figure_area:
                        continue
                    cropped = image.crop(box)
                    buffer = BytesIO()
                    cropped.save(buffer, format="PNG")
                    png_bytes = buffer.getvalue()
                    slice_name = f"{slug}_p{page_id}_crop_{idx}.png"
                    slice_filenames.append(slice_name)
                    if images_dir is not None:
                        (images_dir / slice_name).write_bytes(png_bytes)
                    if len(slice_filenames) == 1:
                        best_crop_bytes = png_bytes

        if not slice_filenames:
            logger.info(
                "Layout analysis page %d: no figure crop, using full-page render for VLM",
                page_id,
            )

        logger.info(
            "Layout analysis page %d: ocr_chars=%d, crops=%d",
            page_id,
            len(raw_ocr_text),
            len(slice_filenames),
        )
        return PageLayoutResult(
            page=page_id,
            raw_ocr_text=raw_ocr_text,
            crop_image_bytes=best_crop_bytes,
            slice_filenames=slice_filenames,
        )


def build_layout_engine(config: AppConfig) -> SchematicLayoutEngine:
    """Create a layout engine from application config."""
    pdf_cfg = config.schematic_pdf
    model_path = config.models.layout_model
    if model_path is None:
        model_path = config.models.base_dir / "layoutlmv3-base"
    return SchematicLayoutEngine(
        model_path=model_path,
        layout_zoom=pdf_cfg.layout_zoom,
        min_figure_area=pdf_cfg.min_figure_area,
    )
