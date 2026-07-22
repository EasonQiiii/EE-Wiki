"""History-embedded TurnScope marker (ADR 0012 §6 cross-turn carry).

Cross-turn scope carry must survive a multi-worker deployment
(``uvicorn --workers N``), where each worker is a separate OS process with its
own memory. An in-memory per-process store therefore drops carried scope
whenever consecutive turns land on different workers.

We instead embed the locked ``(product, project, build)`` as a hidden HTML
comment inside the assistant's own reply. Open WebUI echoes that reply back in
the next turn's ``history``; we recover the marker to backfill axes the new
question left blank. The mechanism is stateless, restart-safe, and
multi-worker-safe. It reuses the same hidden-marker idea as the FA session
scope line (``fa_session._SCOPE_LINE``).

Marker format (invisible in Open WebUI rendering)::

    <!-- ee-wiki-scope: product/project/build -->

Missing axes are encoded as ``-`` so the triple is always three segments.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from ee_wiki.retrieval.rewrite import ConversationTurn

_MARKER_PREFIX = "<!-- ee-wiki-scope: "
_MARKER_SUFFIX = " -->"

_SCOPE_MARKER_RE = re.compile(
    r"<!--\s*ee-wiki-scope:\s*([^/\s]+)/([^/\s]+)/([^/\s]+)\s*-->"
)


@dataclass(frozen=True)
class CarriedScope:
    """A canonical product/project/build triple carried across turns."""

    product: str | None
    project: str | None
    build: str | None

    @property
    def complete(self) -> bool:
        """True when all three axes are set."""
        return bool(self.product and self.project and self.build)

    @property
    def empty(self) -> bool:
        """True when no axis is set (nothing worth carrying)."""
        return not (self.product or self.project or self.build)


def format_scope_marker(
    product: str | None, project: str | None, build: str | None
) -> str:
    """Render the hidden scope marker for embedding in an assistant reply."""

    def _seg(value: str | None) -> str:
        stripped = (value or "").strip()
        return stripped or "-"

    return (
        f"{_MARKER_PREFIX}{_seg(product)}/{_seg(project)}/"
        f"{_seg(build)}{_MARKER_SUFFIX}"
    )


def parse_scope_marker(history: list[ConversationTurn]) -> CarriedScope | None:
    """Recover the most recent carried scope from assistant turns.

    Scans history newest-first and returns the first marker found, or ``None``
    when no assistant turn carries one.
    """
    if not history:
        return None
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        match = _SCOPE_MARKER_RE.search(turn.content or "")
        if not match:
            continue

        def _norm(segment: str) -> str | None:
            segment = segment.strip()
            return None if segment == "-" else segment

        return CarriedScope(
            _norm(match.group(1)), _norm(match.group(2)), _norm(match.group(3))
        )
    return None


def append_scope_marker(chunks: Iterator[str], marker: str) -> Iterator[str]:
    """Yield ``chunks`` then a final hidden ``marker`` chunk."""
    yield from chunks
    yield marker
