"""Structured logging helpers for EE-Wiki."""

from __future__ import annotations

import logging


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
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root = logging.getLogger("ee_wiki")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return logger
