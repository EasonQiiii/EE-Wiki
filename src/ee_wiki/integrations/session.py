"""FA check-in orchestration helpers (Radar + Flames + scope)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from ee_wiki.common.config import AppConfig
from ee_wiki.common.errors import IntegrationError
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.factory import (
    build_fa_report_backend,
    build_flames_backend,
    build_radar_backend,
)
from ee_wiki.integrations.flames.manual import ManualFlamesBackend
from ee_wiki.integrations.paths import fa_cache_dir, normalize_radar_id
from ee_wiki.integrations.scope import ScopeResolution, resolve_scope_from_problem
from ee_wiki.protocols.fa_report import FaReportRequest, FaReportResult
from ee_wiki.protocols.flames import FailItemsResult
from ee_wiki.protocols.radar import RadarProblem, RadarWriteResult

logger = get_logger(__name__)


@dataclass(frozen=True)
class FaCheckinResult:
    """Outcome of starting or refreshing an FA session for a Radar id."""

    radar_id: str
    problem: RadarProblem
    scope: ScopeResolution
    fail_items: FailItemsResult
    log_download_urls: tuple[str, ...]
    summary_markdown: str
    awaiting_user_evidence: bool = False


def public_url(config: AppConfig, path: str) -> str:
    """Build an absolute or root-relative URL for Open WebUI links.

    Args:
        config: App config (uses ``api.public_base_url`` when set).
        path: URL path beginning with ``/``.

    Returns:
        Absolute URL when ``public_base_url`` is set; otherwise ``path``.
    """
    base = (config.api.public_base_url or "").rstrip("/")
    if not base:
        return path
    return f"{base}{path}"


def start_fa_checkin(
    config: AppConfig,
    radar_id: str,
    *,
    serial: str | None = None,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
) -> FaCheckinResult:
    """Pull Radar + Flames (or ask for manual evidence) for FA check-in.

    When ``fa.flames.backend`` is ``manual`` and the user has not pasted a log
    yet, ``awaiting_user_evidence`` is true and the summary asks for paste.

    Args:
        config: Loaded application configuration.
        radar_id: Radar / rdar identifier.
        serial: Optional unit serial for Flames / manual session.
        user_product: Optional scope override.
        user_project: Optional scope override.
        user_build: Optional scope override.

    Returns:
        Check-in result with fail items and downloadable log URLs.
    """
    rid = normalize_radar_id(radar_id)
    radar = build_radar_backend(config)
    flames = build_flames_backend(config)
    problem = radar.get_problem(rid)
    scope = resolve_scope_from_problem(
        problem,
        project_aliases=config.data_layout.project_aliases,
        user_product=user_product,
        user_project=user_project,
        user_build=user_build,
    )
    cache = fa_cache_dir(config.cache_dir, rid)
    fails = flames.collect_fail_items(rid, serial=serial, cache_dir=cache)
    return _build_checkin_result(config, problem, scope, fails)


def ingest_fa_user_evidence(
    config: AppConfig,
    radar_id: str,
    text: str,
    *,
    station: str | None = None,
    serial: str | None = None,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
) -> FaCheckinResult:
    """Accept Open WebUI-pasted log/errors as Flames backup evidence.

    Args:
        config: Loaded application configuration.
        radar_id: FA session Radar id.
        text: Pasted test log or fail list.
        station: Optional station name.
        serial: Optional unit serial.
        user_product: Optional scope override.
        user_project: Optional scope override.
        user_build: Optional scope override.

    Returns:
        Updated check-in result after parsing the paste.

    Raises:
        IntegrationError: If Flames backend is not ``manual``, or text is empty.
    """
    flames = build_flames_backend(config)
    if not isinstance(flames, ManualFlamesBackend):
        raise IntegrationError(
            "ingest_fa_user_evidence requires fa.flames.backend=manual "
            f"(current={config.fa.flames.backend!r})"
        )

    rid = normalize_radar_id(radar_id)
    radar = build_radar_backend(config)
    problem = radar.get_problem(rid)
    scope = resolve_scope_from_problem(
        problem,
        project_aliases=config.data_layout.project_aliases,
        user_product=user_product,
        user_project=user_project,
        user_build=user_build,
    )
    cache = fa_cache_dir(config.cache_dir, rid)
    fails = flames.ingest_user_evidence(
        rid,
        text,
        cache_dir=cache,
        station=station,
        serial=serial,
    )
    return _build_checkin_result(config, problem, scope, fails)


def generate_fa_summary(
    config: AppConfig,
    radar_id: str,
    *,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    fail_items: tuple[str, ...] = (),
    true_fail_notes: str | None = None,
    root_cause: str | None = None,
    steps: tuple[str, ...] = (),
    title: str | None = None,
) -> tuple[FaReportResult, str]:
    """Generate Keynote FA summary and return result + download URL.

    Args:
        config: Loaded application configuration.
        radar_id: Radar id.
        product: Optional product label for the template.
        project: Optional project label for the template.
        build: Optional build label.
        fail_items: Fail item strings.
        true_fail_notes: Human true-fail notes.
        root_cause: Root-cause text when known.
        steps: FA step summaries (often from Radar diagnosis).
        title: Optional title override.

    Returns:
        Report result and browser download URL.
    """
    backend = build_fa_report_backend(config)
    # Keynote template labels use project/build; qualify project when product known.
    project_label = (
        f"{product}/{project}" if product and project else project
    )
    result = backend.generate(
        FaReportRequest(
            radar_id=radar_id,
            project=project_label,
            build=build,
            title=title,
            fail_items=fail_items,
            true_fail_notes=true_fail_notes,
            root_cause=root_cause,
            steps=steps,
        )
    )
    url = public_url(
        config, f"/v1/exports/{quote(result.download_rel_path, safe='/')}"
    )
    return result, url


def commit_diagnosis(
    config: AppConfig,
    radar_id: str,
    text: str,
    *,
    confirm: bool,
) -> RadarWriteResult:
    """Draft or commit a Radar diagnosis entry.

    Args:
        config: Loaded application configuration.
        radar_id: Target Radar id.
        text: Diagnosis body.
        confirm: Must be true to write to Radar.

    Returns:
        Write result (draft or committed).
    """
    radar = build_radar_backend(config)
    return radar.add_diagnosis(radar_id, text, confirm=confirm)


def commit_attachment(
    config: AppConfig,
    radar_id: str,
    path: Path,
    *,
    confirm: bool,
    as_picture: bool = False,
) -> RadarWriteResult:
    """Draft or upload a Radar attachment/picture.

    Args:
        config: Loaded application configuration.
        radar_id: Target Radar id.
        path: Local file path.
        confirm: Must be true to upload.
        as_picture: Upload as picture when true.

    Returns:
        Write result (draft or committed).
    """
    radar = build_radar_backend(config)
    return radar.upload_attachment(
        radar_id, path, confirm=confirm, as_picture=as_picture
    )


def _build_checkin_result(
    config: AppConfig,
    problem: RadarProblem,
    scope: ScopeResolution,
    fails: FailItemsResult,
) -> FaCheckinResult:
    """Attach download URLs and markdown to a fail-items payload."""
    log_urls = tuple(
        public_url(config, f"/v1/cache/{quote(rel, safe='/')}")
        for rel in fails.cached_logs
    )
    awaiting = bool(fails.needs_user_input)
    summary = _format_checkin_markdown(problem, scope, fails, log_urls)
    logger.info(
        "FA check-in radar=%s product=%s project=%s build=%s fails=%d awaiting=%s source=%s",
        problem.radar_id,
        scope.product,
        scope.project,
        scope.build,
        len(fails.fail_items),
        awaiting,
        fails.source,
    )
    return FaCheckinResult(
        radar_id=problem.radar_id,
        problem=problem,
        scope=scope,
        fail_items=fails,
        log_download_urls=log_urls,
        summary_markdown=summary,
        awaiting_user_evidence=awaiting,
    )


def _format_checkin_markdown(
    problem: RadarProblem,
    scope: ScopeResolution,
    fails: FailItemsResult,
    log_urls: tuple[str, ...],
) -> str:
    """Build the assistant markdown for Open WebUI."""
    lines = [
        f"## FA check-in — rdar://{problem.radar_id}",
        "",
        f"**Title:** {problem.title}",
        f"**State:** {problem.state or '—'} / {problem.substate or '—'}",
    ]
    if problem.component:
        lines.append(
            f"**Component:** {problem.component.name} | {problem.component.version}"
        )
    lines.append(
        f"**EE-Wiki scope:** product=`{scope.product or '?'}` "
        f"project=`{scope.project or '?'}` "
        f"build=`{scope.build or '?'}` "
        f"(source={scope.source}, confidence={scope.confidence})"
    )
    lines.append(f"**Evidence source:** `{fails.source}`")

    if fails.needs_user_input:
        lines.extend(
            [
                "",
                "### Need test evidence",
                fails.user_prompt
                or "Please paste the test log or a list of error items.",
                "",
                "After you paste, I will list fail items and continue triage.",
            ]
        )
    else:
        lines.extend(["", "### Fail items"])
        if not fails.fail_items:
            lines.append("_No ERROR/FAIL lines extracted from cached logs._")
        else:
            for item in fails.fail_items:
                station = item.station or "?"
                lines.append(f"- [{station}] {item.message}")

        lines.extend(["", "### Raw logs"])
        if not log_urls:
            lines.append("_No logs cached._")
        else:
            for rel, url in zip(fails.cached_logs, log_urls, strict=True):
                lines.append(f"- [{Path(rel).name}]({url})")

        lines.extend(
            [
                "",
                "_True-fail vs fixture/SW is a human judgment. "
                "Say which items are true fail to continue module triage._",
            ]
        )

    if scope.confidence in {"low", "none"}:
        lines.append(
            f"\n> Scope incomplete ({scope.notes}). "
            "Please confirm product/project/build for retrieval."
        )
    return "\n".join(lines)
