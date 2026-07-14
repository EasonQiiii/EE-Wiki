"""Tests for generic schematic signal grouping."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.signals import (
    OcrToken,
    associate_nets_to_modules_spatial,
    build_module_signal_blocks,
    build_page_signal_summary,
    recover_noisy_prefix_nets,
)

_MODULE_A = "DISPLAY&SENSOR"
_MODULE_B = "COMM&USB"
_NET_A0 = "IFACE_D0"
_NET_A1 = "IFACE_D1"
_NET_A_SCL = "IFACE_SCL"
_NET_B_TX = "COMM_TX"
_NET_B_H = "COMM_H"
_NET_B_L = "COMM_L"


def test_recover_noisy_prefix_nets_without_prefix_list() -> None:
    text = "NLIFACE0D0 PIP809NLIFACE0D1 IFACE__SCL MEM__D2"
    recovered = recover_noisy_prefix_nets(text)
    assert _NET_A0 in recovered
    assert "MEM_D2" in recovered


def test_build_page_signal_summary_groups_all_prefixes_on_page() -> None:
    summary = build_page_signal_summary(
        [_MODULE_A, _MODULE_B],
        [_NET_A0, _NET_A1, _NET_A_SCL, _NET_B_H, _NET_B_L, "GND"],
    )
    assert "本页模块与接口信号" in summary
    assert _MODULE_A in summary
    assert _MODULE_B in summary
    assert _NET_A0 in summary
    assert _NET_B_H in summary


def test_build_module_signal_blocks_use_ocr_proximity() -> None:
    ocr_text = (
        f"{_MODULE_A}\nJ1\nSENSOR_IC\nIFACE__SCL\nIFACE__SDA\n"
        f"{_NET_A0}\n{_NET_A1}\n{_MODULE_B}\n{_NET_B_TX}\nCOMM_RX\n"
    )
    blocks = build_module_signal_blocks(
        [_MODULE_A, _MODULE_B],
        [_NET_A0, _NET_A1, _NET_A_SCL, "IFACE_SDA", _NET_B_TX],
        ocr_text,
    )
    assert len(blocks) == 2
    assert f"模块：{_MODULE_A}" in blocks[0]
    assert _NET_A0 in blocks[0]
    assert _NET_B_TX not in blocks[0]


def test_build_module_signal_blocks_emit_empty_stub_when_no_nets() -> None:
    blocks = build_module_signal_blocks(
        ["OLED&CAMERA", "ADC&DAC"],
        ["SPI1_SCK"],
        "OLED&CAMERA\nADC&DAC\nSPI1_SCK\n",
    )
    assert any("OLED&CAMERA" in block and "不得臆造" in block for block in blocks)


def test_build_page_signal_summary_embedded_heading_level() -> None:
    summary = build_page_signal_summary(
        [_MODULE_A],
        [_NET_A0],
        ocr_text=f"{_MODULE_A} {_NET_A0}",
        heading_level=3,
    )
    assert summary.startswith("### 本页模块与接口信号")
    assert f"### 模块：{_MODULE_A}" in summary


def test_associate_nets_to_modules_spatial_prefers_nearby_zone_title() -> None:
    tokens = (
        OcrToken("OLED&CAMERA", 660, 40, 760, 55),
        OcrToken("ADC&DAC", 600, 400, 680, 420),
        OcrToken("DCMI_D0", 670, 110, 720, 125),
        OcrToken("DCMI__SCL", 670, 90, 740, 105),
        OcrToken("STM_ADC", 620, 450, 680, 465),
        OcrToken("SPI1_SCK", 560, 120, 620, 135),
        OcrToken("WIRELESS", 520, 40, 600, 55),
    )
    assigned = associate_nets_to_modules_spatial(
        ["OLED&CAMERA", "ADC&DAC", "WIRELESS"],
        ["DCMI_D0", "DCMI_SCL", "STM_ADC", "SPI1_SCK"],
        tokens,
    )
    assert "DCMI_D0" in assigned["OLED&CAMERA"]
    assert "DCMI_SCL" in assigned["OLED&CAMERA"]
    assert "STM_ADC" in assigned["ADC&DAC"]
    assert "SPI1_SCK" in assigned["WIRELESS"]
    assert "DCMI_D0" not in assigned["ADC&DAC"]


def test_associate_nets_to_modules_spatial_prefers_prefix_when_close() -> None:
    tokens = (
        OcrToken("USB/CAN", 40, 280, 100, 300),
        OcrToken("CAN&USB", 50, 290, 120, 310),
        OcrToken("FLASH", 600, 300, 680, 320),
        OcrToken("CAN_TX", 55, 320, 110, 335),
        OcrToken("USB_DP", 45, 360, 100, 375),
        OcrToken("F_CS", 620, 350, 680, 365),
    )
    assigned = associate_nets_to_modules_spatial(
        ["USB/CAN", "CAN&USB", "FLASH"],
        ["CAN_TX", "USB_DP", "F_CS"],
        tokens,
    )
    assert "CAN_TX" in assigned["CAN&USB"]
    # USB_DP may land on USB/CAN or CAN&USB (both contain USB); must not go to FLASH.
    usb_owners = [lab for lab, nets in assigned.items() if "USB_DP" in nets]
    assert usb_owners and set(usb_owners) <= {"USB/CAN", "CAN&USB"}
    assert "F_CS" in assigned["FLASH"]
    assert "CAN_TX" not in assigned["FLASH"]


def test_build_module_signal_blocks_use_spatial_tokens() -> None:
    tokens = (
        OcrToken("OLED&CAMERA", 660, 40, 760, 55),
        OcrToken("DCMI_D0", 670, 110, 720, 125),
        OcrToken("ADC&DAC", 600, 400, 680, 420),
    )
    # Reading-order text would wrongly cut OLED before DCMI nets.
    ocr_text = "OLED&CAMERA\nTEMP&HUMI SENSOR\nADC&DAC\nDCMI_D0\n"
    blocks = build_module_signal_blocks(
        ["OLED&CAMERA", "ADC&DAC"],
        ["DCMI_D0"],
        ocr_text,
        ocr_tokens=tokens,
    )
    oled_block = next(block for block in blocks if "OLED&CAMERA" in block)
    assert "DCMI_D0" in oled_block
    adc_block = next(block for block in blocks if "ADC&DAC" in block)
    assert "DCMI_D0" not in adc_block
