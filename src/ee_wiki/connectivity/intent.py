"""Detect schematic trace/connectivity intent in a chat question.

The chat/RAG pipeline answers from probabilistic VLM/OCR schematic text. That
is unsafe for connectivity/trace questions, whose answers must come from
board-verified sidecars (CAD netlist / BoardView) or be refused. This module
recognises when a question is really asking "what is X electrically connected
to" so the chat route can divert it to the gated connectivity path
(:meth:`ee_wiki.connectivity.query.ConnectivityQuery.resolve_trace`).

Detection is deliberately conservative: it requires an explicit connectivity
verb *and* a concrete net / designator token, so that generic schematic recall
questions (for example "what is the ethernet PHY part number") still flow to
normal retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Phrases that signal the user wants pin-level electrical connectivity, not a
# generic fact. Mix of EN + zh-CN because FA users write in both.
_CONNECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\btrace\b", re.IGNORECASE),
    re.compile(r"\bnet\s*list\b", re.IGNORECASE),
    re.compile(r"\bconnect(?:ed|s|ion|ivity)?\s+to\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:is\s+)?(?:it\s+)?connect", re.IGNORECASE),
    re.compile(r"\bpin\s*(?:out|map|list)\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+pins?\b", re.IGNORECASE),
    re.compile(r"连(?:接|到|去|向)"),
    re.compile(r"接(?:到|去|入|了)"),
    re.compile(r"接在(?:哪|什么)"),
    re.compile(r"(?:走线|布线|连线|连通|通路|网表|连接关系|连接情况)"),
    re.compile(r"引脚.*(?:连|接)|(?:连|接).*引脚"),
    re.compile(r"哪(?:些|几)?(?:个|根)?(?:引脚|管脚|pin)"),
)

# A net name: uppercase/underscore token with at least one letter, length >= 3
# (for example EDP_AUXP, ETH_MDIO, VBAT). Avoid matching plain words.
_NET_TOKEN = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{2,}\d+[A-Z0-9_]*)\b")
# A designator, optionally with a pin: U502, J1, U0500.7, R12.A12
_REFDES_TOKEN = re.compile(
    r"\b((?:U|J|P|R|C|L|D|Q|Y|X|SW|CN|FB|TP|RN)\d+[A-Z]?)(?:[.\-]([A-Z0-9]+))?\b"
)
# Explicit `net X` / `网络 X` naming that promotes an otherwise ambiguous token.
_NET_KEYWORD = re.compile(r"(?:net|网络|信号)\s*[:：]?\s*", re.IGNORECASE)


@dataclass(frozen=True)
class TraceIntent:
    """A detected connectivity/trace request.

    Attributes:
        kind: ``"net"`` (trace a net) or ``"pins"`` (a connector/part).
        query: The net name or designator to look up.
        pin: Optional pin extracted from a ``REFDES.pin`` token.
    """

    kind: str
    query: str
    pin: str | None = None


def _has_connect_intent(question: str) -> bool:
    return any(pat.search(question) for pat in _CONNECT_PATTERNS)


def detect_trace_intent(question: str) -> TraceIntent | None:
    """Return a :class:`TraceIntent` when the question asks for a trace.

    Args:
        question: The user's chat message.

    Returns:
        A :class:`TraceIntent` when both a connectivity verb and a concrete
        net/designator token are present, else ``None`` (let normal retrieval
        handle it).
    """
    if not question or not question.strip():
        return None
    if not _has_connect_intent(question):
        return None

    refdes_match = _REFDES_TOKEN.search(question)
    net_match = _NET_TOKEN.search(question)

    # A designator (optionally with a pin) is the strongest signal for a
    # part/connector trace.
    if refdes_match:
        refdes = refdes_match.group(1)
        pin = refdes_match.group(2)
        # If a net keyword precedes a net token, prefer a net trace instead.
        if net_match and _net_is_explicit(question, net_match):
            return TraceIntent(kind="net", query=net_match.group(1))
        return TraceIntent(kind="pins", query=refdes, pin=pin)

    if net_match:
        return TraceIntent(kind="net", query=net_match.group(1))
    return None


def _net_is_explicit(question: str, net_match: re.Match[str]) -> bool:
    """Return whether a ``net``/``网络`` keyword directly precedes the token."""
    start = net_match.start()
    prefix = question[max(0, start - 12) : start]
    return bool(_NET_KEYWORD.search(prefix))
