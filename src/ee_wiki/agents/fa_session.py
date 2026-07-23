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

from ee_wiki.api.scope_marker import CarriedScope, parse_scope_marker
from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.fa_chat import (
    fa_session_radar_id_from_history,
    parse_fa_checkin_radar_id,
)
from ee_wiki.integrations.scope import resolve_scope_from_problem
from ee_wiki.retrieval.rewrite import ConversationTurn

logger = get_logger(__name__)

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


def _norm_scope_value(value: str | None) -> str | None:
    """Normalize a parsed scope token: strip backticks, `?`/`-`/none -> None."""
    if value is None:
        return None
    cleaned = value.strip().strip("`").strip()
    if not cleaned or cleaned.lower() in _NONE_TOKENS or cleaned == "?":
        return None
    return cleaned


def _parse_scope_line(
    content: str,
) -> tuple[str | None, str | None, str | None]:
    """Parse the structural ``**EE-Wiki scope:** ...`` line from check-in markdown.

    Unlike :func:`_parse_unbound_scope` (which feeds the unbound header), this
    also strips the backtick-wrapped display values the check-in emits
    (``product=`logan` ``) and treats ``?`` as a missing axis.
    """
    match = _SCOPE_LINE.search(content)
    if not match:
        return None, None, None
    return (
        _norm_scope_value(match.group("product")),
        _norm_scope_value(match.group("project")),
        _norm_scope_value(match.group("build")),
    )


def _fill_scope_from_radar(
    product: str | None,
    project: str | None,
    build: str | None,
    *,
    config: AppConfig,
    radar_id: str,
) -> tuple[str | None, str | None, str | None]:
    """Fill still-missing scope axes from the Radar component.

    Uses the same deterministic alias mapping as ``start_fa_checkin``
    (``resolve_scope_from_problem``). Placeholder tokens (``?`` / ``-`` / none)
    are normalized to ``None`` so they don't block the component fill. Only
    missing axes are adopted; existing axes are preserved. No NL re-inference.
    """
    u_product = _norm_scope_value(product)
    u_project = _norm_scope_value(project)
    u_build = _norm_scope_value(build)
    try:
        from ee_wiki.integrations.factory import build_radar_backend

        problem = build_radar_backend(config).get_problem(radar_id)
    except Exception:
        logger.warning(
            "Radar get_problem failed (bound scope restore) radar=%s",
            radar_id,
            exc_info=True,
        )
        return product, project, build
    resolved = resolve_scope_from_problem(
        problem,
        project_aliases=config.data_layout.project_aliases,
        user_product=u_product,
        user_project=u_project,
        user_build=u_build,
    )
    return (
        product if _norm_scope_value(product) else (resolved.product or product),
        project if _norm_scope_value(project) else (resolved.project or project),
        build if _norm_scope_value(build) else (resolved.build or build),
    )


def _restore_bound_scope(
    product: str | None,
    project: str | None,
    build: str | None,
    *,
    last_assistant: str | None,
    carried: CarriedScope | None,
    config: AppConfig,
    radar_id: str,
) -> tuple[str | None, str | None, str | None]:
    """Restore bound-session scope for a follow-up turn (ADR 0012 §6).

    Priority (each source only fills axes still missing):
      1. caller TurnScope (passed in; already locked at chat entry)
      2. history FA check-in ``**EE-Wiki scope:**`` line (structural)
      3. ``<!-- ee-wiki-scope: -->`` marker
      4. Radar component via ``resolve_scope_from_problem``
    """
    # 1) caller scope is already in product/project/build.
    # 2) history check-in scope line.
    if last_assistant is not None:
        h_product, h_project, h_build = _parse_scope_line(last_assistant)
        product = product or h_product
        project = project or h_project
        build = build or h_build
    # 3) marker.
    if carried is not None:
        product = product or carried.product
        project = project or carried.project
        build = build or carried.build
    # 4) Radar component (only when an axis is still missing).
    if (product is None or project is None or build is None) and radar_id:
        product, project, build = _fill_scope_from_radar(
            product, project, build, config=config, radar_id=radar_id
        )
    return product, project, build


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
    last_assistant = _last_assistant_content(history)
    # Cross-turn scope carry (ADR 0012 §6): recover the locked (product,
    # project, build) from the hidden `<!-- ee-wiki-scope: -->` marker embedded
    # in a prior assistant reply. Open WebUI's OpenAI-compatible endpoint omits
    # `conversation_id`, so this marker in `history` is the only carry vehicle.
    # Gated by `carry_scope_across_turns` so it can never bypass the opt-out.
    carried = (
        parse_scope_marker(list(history))
        if (config.api.carry_scope_across_turns and history)
        else None
    )

    if rid_from_history:
        # Bound session: restore scope for follow-up turns. Caller TurnScope
        # wins; gaps are filled from the history FA check-in scope line, then
        # the ee-wiki-scope marker, then the Radar component (same deterministic
        # alias mapping start_fa_checkin uses — NOT a second NL inference,
        # ADR 0012 §6). This is what lets bound "建议/追模块" turns actually run
        # scope-required tools (query_schematic / trace_net) instead of being
        # skipped for missing scope.
        product, project, build = _restore_bound_scope(
            product, project, build,
            last_assistant=last_assistant,
            carried=carried,
            config=config,
            radar_id=rid_from_history,
        )
        return FaSession(
            case_id=rid_from_history,
            radar_id=rid_from_history,
            product=product,
            project=project,
            build=build,
            bound=True,
        )

    new_rid = parse_fa_checkin_radar_id(question)

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
