"""Tests for colored logging helpers."""

from __future__ import annotations

import logging

from ee_wiki.common.logging import ColoredFormatter


def test_colored_formatter_adds_warning_and_error_colors() -> None:
    formatter = ColoredFormatter("%(levelname)s %(message)s", use_color=True)

    warning_record = logging.LogRecord(
        name="ee_wiki.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Skipping unsupported raw file: demo.zip",
        args=(),
        exc_info=None,
    )
    error_record = logging.LogRecord(
        name="ee_wiki.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Ingest failed",
        args=(),
        exc_info=None,
    )
    info_record = logging.LogRecord(
        name="ee_wiki.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Ingested 3 file(s)",
        args=(),
        exc_info=None,
    )

    warning_line = formatter.format(warning_record)
    error_line = formatter.format(error_record)
    info_line = formatter.format(info_record)

    assert "\033[33m" in warning_line
    assert "\033[0m" in warning_line
    assert "\033[31m" in error_line
    assert "\033[0m" in error_line
    assert "\033[" not in info_line


def test_colored_formatter_respects_disabled_color() -> None:
    formatter = ColoredFormatter("%(levelname)s %(message)s", use_color=False)
    record = logging.LogRecord(
        name="ee_wiki.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Ingest failed",
        args=(),
        exc_info=None,
    )

    assert "\033[" not in formatter.format(record)
