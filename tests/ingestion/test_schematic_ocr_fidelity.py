"""Tests for OCR fidelity schematic extraction."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import (
    build_fidelity_extraction,
    extract_fidelity_fields,
    extract_module_labels,
)

_MODULE_A = "DISPLAY&SENSOR"
_NET_A0 = "IFACE_D0"
_NET_A1 = "IFACE_D1"
_NET_A_SCL = "IFACE_SCL"


def test_extract_module_labels_finds_ampersand_zone_labels() -> None:
    text = "COMM&USB\nEEPROM\nDISPLAY&SENSOR\nLED\nU10\n"
    labels = extract_module_labels(text)
    assert _MODULE_A in labels
    assert "EEPROM" in labels
    assert "LED" not in labels  # short pin/UI tokens are not zone titles
    assert "U10" not in labels


def test_extract_module_labels_filters_designator_noise_and_pinlike_slash() -> None:
    text = "OLED&CAMERA\nCD/DATA3\nPIC7501 PIC7502\nWIRELESS\nUSB/CAN\nSCL\n"
    labels = extract_module_labels(text)
    assert "OLED&CAMERA" in labels
    assert "WIRELESS" in labels
    assert "USB/CAN" in labels
    assert "CD/DATA3" not in labels
    assert "PIC7501 PIC7502" not in labels
    assert "SCL" not in labels


def test_extract_module_labels_keeps_zone_slash_rejects_pin_mux_slash() -> None:
    text = (
        "USB/CAN\nRS232/RS485\nRS232/BTCOM&GPS\n"
        "TMS/SWDIO\nTCK/SWCLK\nPB2/BOOT1\nLED1/REGOFF\nWR/CLK\nRXD1/MODE1\n"
        "6 AXIS SENSOR\nSD CARD\n"
    )
    labels = extract_module_labels(text)
    assert "USB/CAN" in labels
    assert "RS232/RS485" in labels
    assert "RS232/BTCOM&GPS" in labels
    assert "6 AXIS SENSOR" in labels
    assert "SD CARD" in labels
    assert "TMS/SWDIO" not in labels
    assert "TCK/SWCLK" not in labels
    assert "PB2/BOOT1" not in labels
    assert "LED1/REGOFF" not in labels
    assert "WR/CLK" not in labels
    assert "RXD1/MODE1" not in labels


def test_extract_fidelity_fields_recovers_embedded_nets() -> None:
    text = f"{_MODULE_A}\nNLIFACE0D0\nPIP809NLIFACE0D1\nIFACE__SCL\nGND\n"
    fields = extract_fidelity_fields(text)
    assert _MODULE_A in fields.module_labels
    assert _NET_A0 in fields.nets
    assert _NET_A_SCL in fields.nets


def test_build_fidelity_extraction_includes_page_signal_summary() -> None:
    layout = PageLayoutResult(
        page=3,
        raw_ocr_text=f"{_MODULE_A}\n{_NET_A0}\n{_NET_A1}\n{_NET_A_SCL}\n",
        crop_image_bytes=None,
        slice_filenames=[],
    )
    result = build_fidelity_extraction(layout, project_id="demo")
    assert _MODULE_A in result.markdown
    assert _NET_A0 in result.markdown
    assert "本页模块与接口信号" in result.markdown
    assert "OCR 保真摘录" in result.markdown


def test_enrich_with_fidelity_skips_duplicate_appendix() -> None:
    from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
    from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import enrich_with_fidelity

    layout = PageLayoutResult(
        page=2,
        raw_ocr_text=f"{_MODULE_A}\n{_NET_A0}\n",
        crop_image_bytes=None,
        slice_filenames=[],
    )
    existing = PageExtraction(
        page=2,
        markdown="## fallback\n\n## 5. OCR 保真摘录（检索依据，禁止改写）\n",
        major_components=[],
        nets=[],
        interfaces=[],
    )
    enriched = enrich_with_fidelity(existing, layout)
    assert enriched.markdown.count("## 5. OCR 保真摘录") == 1
    assert _NET_A0 in enriched.nets
