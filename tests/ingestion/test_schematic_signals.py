"""Tests for generic schematic signal grouping."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.signals import (
    build_page_signal_summary,
    recover_noisy_prefix_nets,
)


def test_recover_noisy_prefix_nets_without_prefix_list() -> None:
    text = "NLDCMI0D0 PIP809NLDCMI0D1 DCMI__SCL FSMC__D2"
    recovered = recover_noisy_prefix_nets(text)
    assert "DCMI_D0" in recovered
    assert "FSMC_D2" in recovered


def test_build_page_signal_summary_groups_all_prefixes_on_page() -> None:
    summary = build_page_signal_summary(
        ["OLED&CAMERA", "CAN&USB"],
        ["DCMI_D0", "DCMI_D1", "DCMI_SCL", "CAN_H", "CAN_L", "GND"],
    )
    assert "本页模块与接口信号" in summary
    assert "OLED&CAMERA" in summary
    assert "CAN&USB" in summary
    assert "DCMI_D0" in summary
    assert "CAN_H" in summary
