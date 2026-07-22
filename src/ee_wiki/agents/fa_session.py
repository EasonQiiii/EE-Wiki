"""Ephemeral FA session state (bound or unbound) — fa-session.md.

A session is **bound** when it carries a Radar id (``case_id == radar_id``) and
**unbound** (ephemeral) when the user opened an FA investigation by symptom /
part / net without a ticket. An unbound session can later BIND when the user
pastes a Radar id — the same conversation turns into a bound checkout without
losing the opening symptom / scope.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from ee_wiki.api.scope_marker import parse_scope_marker
from ee_wiki.common.config import AppConfig
from ee_wiki.integrations.fa_chat import (
    fa_session_radar_id_from_history,
    parse_fa_checkin_radar_id,
)
from ee_wiki.retrieval.rewrite import ConversationTurn

_BOUND_HEADER = re.compile(
    r"##\s*FA check-in\s*[—-]\s*rdar://(\d{5,})", re.IGNORECASE
)
_UNBOUND_HEADER = re.compile(
    r"(?:FA\s*session\s*[—-]\s*unbound|FA（未绑定\s*Radar）)", re.IGNORECASE
)
_SYMPTOM_LINE = re.compile(
    r"\*\*(?:Symptom|FA（未绑定\s*Radar）)：\*\*\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SCOPE_LINE = re.compile(
    r"\*\*EE-Wiki scope:\*\*\s*product=(?P<product>\S+)\s+"
    r"project=(?P<project>\S+)\s+build=(?P<build>\S+)",
    re.IGNORECASE,
)
_NONE_TOKENS = frozenset({"none", "-", "—", "null", ""})


@dataclass
class FaSession:
    """One FA investigation session (bound ticket or unbound ephemeral)."""

    case_id: str
    radar_id: str | None = None
    product: str | None = None
    project: str | None = None
    build: str | None = None
    symptom: str | None = None
    bound: bool = False

    @property
    def unbound(self) -> bool:
        """True when no Radar id is attached yet."""
        return not self.bound


def _ephemeral_case_id(*parts: str) -> str:
    """Deterministic ephemeral id so an unbound session is stable across turns."""
    joined = "::".join(p for p in parts if p)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]
    return f"fa-unbound-{digest}"


def _last_assistant_content(
    history: Sequence[ConversationTurn] | None,
) -> str | None:
    if not history:
        return None
    for turn in reversed(history):
        if turn.role == "assistant":
            return turn.content
    return None


def _parse_unbound_scope(content: str) -> tuple[str | None, str | None, str | None]:
    match = _SCOPE_LINE.search(content)
    if not match:
        return None, None, None

    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        return None if value.strip().lower() in _NONE_TOKENS else value.strip()

    return _clean(match.group("product")), _clean(match.group("project")), _clean(
        match.group("build")
    )


def _parse_unbound_symptom(content: str) -> str | None:
    match = _SYMPTOM_LINE.search(content)
    return match.group(1).strip() if match else None


def ensure_fa_session(
    question: str,
    history: Sequence[ConversationTurn] | None,
    product: str | None,
    project: str | None,
    build: str | None,
    *,
    config: AppConfig,
    ctx=None,
) -> FaSession:
    """Build (or restore) the :class:`FaSession` for this turn.

    Scope is **TurnScope-locked by the caller** (chat locks once via
    :func:`merge_scope_from_question` before FaAgent / Supervisor). This
    function must **not** re-infer from the question (ADR 0012 §6).

    Restoration order (fa-session.md entry A/B/C):

    1. Bound history header (``rdar://``) → bound session, stays bound.
    2. Unbound history header → ephemeral session. If the new message carries a
       Radar id, it **binds**. Missing axes fall back to the prior header only
       when the caller left them unset (no second NL infer). When there is no
       prior FA header (e.g. a Wiki→FA follow-up), missing axes additionally
       fall back to the history-embedded `<!-- ee-wiki-scope: -->` marker —
       lowest priority, gated by `carry_scope_across_turns` (no NL re-infer).
    3. Radar id in the fresh message → bound check-in session.
    4. Otherwise → ephemeral unbound session using the caller's locked scope.
    """
    _ = ctx  # retained for call-site compatibility / future DialogScope
    rid_from_history = fa_session_radar_id_from_history(history)
    if rid_from_history:
        return FaSession(
            case_id=rid_from_history,
            radar_id=rid_from_history,
            product=product,
            project=project,
            build=build,
            bound=True,
        )

    new_rid = parse_fa_checkin_radar_id(question)
    last_assistant = _last_assistant_content(history)

    # Cross-turn scope carry (ADR 0012 §6): recover the locked (product,
    # project, build) from the hidden `<!-- ee-wiki-scope: -->` marker embedded
    # in a prior assistant reply. Open WebUI's OpenAI-compatible endpoint omits
    # `conversation_id`, so this marker in `history` is the only carry vehicle.
    # It is the *lowest-priority* source: the caller's TurnScope-locked scope
    # wins, and the prior FA header (below) wins over the marker. Gated by
    # `carry_scope_across_turns` so it can never bypass the opt-out.
    carried = None
    if config.api.carry_scope_across_turns and history:
        carried = parse_scope_marker(list(history))

    if last_assistant is not None and _UNBOUND_HEADER.search(last_assistant):
        s_product, s_project, s_build = _parse_unbound_scope(last_assistant)
        symptom = _parse_unbound_symptom(last_assistant)
        # Caller TurnScope wins; gaps fall back to the prior unbound header
        # line, then to the history-embedded marker (the compact header no
        # longer prints a visible scope line — scope travels in the marker).
        product, project, build = (
            product or s_product or (carried.product if carried else None),
            project or s_project or (carried.project if carried else None),
            build or s_build or (carried.build if carried else None),
        )
        if new_rid:
            return FaSession(
                case_id=new_rid,
                radar_id=new_rid,
                product=product,
                project=project,
                build=build,
                symptom=symptom or question,
                bound=True,
            )
        return FaSession(
            case_id=_ephemeral_case_id(
                product or "", project or "", build or "", symptom or ""
            ),
            radar_id=None,
            product=product,
            project=project,
            build=build,
            symptom=symptom or question,
            bound=False,
        )

    if new_rid:
        return FaSession(
            case_id=new_rid,
            radar_id=new_rid,
            product=product,
            project=project,
            build=build,
            symptom=question,
            bound=True,
        )

    eff_product = product or (carried.product if carried else None)
    eff_project = project or (carried.project if carried else None)
    eff_build = build or (carried.build if carried else None)
    return FaSession(
        case_id=_ephemeral_case_id(
            eff_product or "", eff_project or "", eff_build or "", question
        ),
        radar_id=None,
        product=eff_product,
        project=eff_project,
        build=eff_build,
        symptom=question,
        bound=False,
    )


def unbound_header_markdown(session: FaSession) -> str:
    """Compact, readable unbound FA header (parseable by ensure_fa_session).

    Scope is intentionally NOT printed here — it travels in the invisible
    ``<!-- ee-wiki-scope: -->`` marker (api/scope_marker.py), so the visible
    header stays a single short line. Symptom is kept for unbound→unbound
    follow-up continuity.
    """
    symptom = session.symptom or "(未指定现象)"
    return f"**FA（未绑定 Radar）：** {symptom}"
