"""Tests for generic schematic signal grouping."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.signals import (
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


def test_build_page_signal_summary_embedded_heading_level() -> None:
    summary = build_page_signal_summary(
        [_MODULE_A],
        [_NET_A0],
        ocr_text=f"{_MODULE_A} {_NET_A0}",
        heading_level=3,
    )
    assert summary.startswith("### 本页模块与接口信号")
    assert f"#### 模块：{_MODULE_A}" in summary
