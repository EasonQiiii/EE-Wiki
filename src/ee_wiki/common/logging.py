"""Structured logging helpers for EE-Wiki."""

from __future__ import annotations

import logging
import os
import sys

_RESET = "\033[0m"
_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "\033[2m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}


def _use_color() -> bool:
    """Return whether stderr log lines should include ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("EE_WIKI_LOG_COLOR") == "0":
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("EE_WIKI_LOG_COLOR") == "1":
        return True
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


class ColoredFormatter(logging.Formatter):
    """Format log records with ANSI colors for WARNING and above."""

    def __init__(self, fmt: str, *, use_color: bool | None = None) -> None:
        super().__init__(fmt)
        self.use_color = _use_color() if use_color is None else use_color

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if not self.use_color:
            return formatted
        color = _LEVEL_COLORS.get(record.levelno)
        if color is None:
            return formatted
        return f"{color}{formatted}{_RESET}"


def get_logger(name: str) -> logging.Logger:
    """Return a module logger with a consistent format if unconfigured.

    Args:
        name: Logger name, typically ``__name__``.

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)
    if not logging.getLogger("ee_wiki").handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            ColoredFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root = logging.getLogger("ee_wiki")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return logger
