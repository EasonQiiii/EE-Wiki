"""Tests for elapsed time footer formatting."""

from __future__ import annotations

from ee_wiki.generation.elapsed import RagPhaseTiming, format_phase_timing_footer


def test_format_phase_timing_footer() -> None:
    footer = format_phase_timing_footer(
        RagPhaseTiming(
            retrieval_seconds=3.21,
            generation_seconds=38.47,
            first_char_seconds=41.68,
        )
    )
    assert footer == (
        "\n\n---\n⏱ 检索 3.2 秒 · 生成 38.5 秒 · 首字 41.7 秒"
    )


def test_format_phase_timing_footer_minutes() -> None:
    footer = format_phase_timing_footer(
        RagPhaseTiming(
            retrieval_seconds=65.0,
            generation_seconds=120.5,
            first_char_seconds=185.5,
        )
    )
    assert "检索 1 分 5.0 秒" in footer
    assert "生成 2 分 0.5 秒" in footer
    assert "首字 3 分 5.5 秒" in footer
