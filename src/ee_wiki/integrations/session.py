"""FA check-in orchestration helpers (Radar + Flames + scope)."""

from __future__ import annotations

import re
import threading
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
from ee_wiki.integrations.radar.evidence import (
    compose_radar_evidence_corpus,
    radar_has_evidence_corpus,
    user_diagnosis_entries,
)
from ee_wiki.integrations.scope import ScopeResolution, resolve_scope_from_problem
from ee_wiki.protocols.fa_report import FaReportRequest, FaReportResult
from ee_wiki.protocols.flames import FailItem, FailItemsResult, FlamesUnitRef
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.protocols.radar import RadarProblem, RadarWriteResult

logger = get_logger(__name__)

_NO_EVIDENCE_PROMPT = (
    "No usable fail evidence was found in **Flames** or in Radar "
    "**title / description / diagnosis**.\n\n"
    "Please paste either:\n"
    "1) the test **log** (preferred), or\n"
    "2) a bullet list of **error / fail items**.\n"
    "Optional: station name and serial (SN)."
)

_RADAR_UNPARSED_PROMPT = (
    "Radar has title/description/diagnosis notes, but structured fail items "
    "could not be extracted automatically.\n\n"
    "Please paste the test **log** (preferred), or a bullet list of "
    "error / fail items, or confirm the symptoms from the Radar notes above."
)

# Author field on a Radar diagnosis entry can be wrapped as
# "<CommentAuthor wang.jin92@byd.com Elwen Wang>" or "wang.baofu@byd.com Wang
# Baofu". We surface only the email (structural token, no NLP).
_AUTHOR_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+")


def _author_email(added_by: str | None) -> str:
    """Return the author email only (strip '<CommentAuthor ... Name>' wrappers)."""
    raw = (added_by or "").strip()
    if not raw:
        return "—"
    match = _AUTHOR_EMAIL.search(raw)
    if match:
        return match.group(0)
    return raw


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
    llm: LlmBackend | None = None,
    cancel_event: threading.Event | None = None,
) -> FaCheckinResult:
    """Pull Radar face evidence first; fall back to Flames only if needed.

    Evidence priority (field practice — ADR 0013):

    1. Radar **title** (most prominent symptom)
    2. Radar **description** (station / DUT / configuration)
    3. Radar **diagnosis** (FA notes; ``<Radar History>`` rows skipped)
    4. LLM-selected **strong-related attachments** (downloaded on demand,
       bounded by ``config.fa.checkin``; body text scanned for FAIL lines)
    5. **Flames** — lowest fallback, only when 1–4 are insufficient
    6. Ask the user to paste a log / fail list

    Selecting *which* attachments are strong-related is semantic → LLM
    (``prompts/fa/checkin_background.md``); there is no NG/FAIL filename
    regex gate. When no LLM is available we degrade to caching the corpus +
    listing the inventory (no batch download) and may ask the user to paste.

    Args:
        config: Loaded application configuration.
        radar_id: Radar / rdar identifier.
        serial: Optional unit serial for Flames / manual session.
        user_product: Optional scope override.
        user_project: Optional scope override.
        user_build: Optional scope override.
        llm: Optional local LLM for face read-through + fail extraction.
        cancel_event: Optional cancellation for the LLM calls.

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

    # (1–3) Read the Radar face (LLM) — the primary evidence tier.
    background = None
    if llm is not None and not (cancel_event and cancel_event.is_set()):
        from ee_wiki.api.stream_status import FA_ANALYZE_STATUS
        from ee_wiki.api.stream_status_context import push_stream_status
        from ee_wiki.generation.fa_evidence import extract_checkin_background

        push_stream_status(FA_ANALYZE_STATUS)
        background = extract_checkin_background(
            problem, llm=llm, repo_root=config.repo_root, cancel_event=cancel_event
        )

    # (4) Materialize only the LLM-selected strong-related attachments.
    related = _materialize_related_evidence(
        config,
        problem,
        background.related_files if background else (),
        cancel_event=cancel_event,
    )

    # Cache the face corpus (also written when no LLM, for the paste branch).
    corpus_cache = _cache_radar_corpus(config, problem, cache)
    radar_fails = None
    if corpus_cache is not None:
        if llm is not None and not (cancel_event and cancel_event.is_set()):
            from ee_wiki.api.stream_status import FA_EXTRACT_FAILS_STATUS
            from ee_wiki.api.stream_status_context import push_stream_status

            push_stream_status(FA_EXTRACT_FAILS_STATUS)
        radar_fails = _extract_radar_fail_items(
            config,
            corpus_cache[0],
            corpus_cache[1],
            problem,
            serial=serial,
            llm=llm,
            cancel_event=cancel_event,
        )

    merged_items, cached_logs = _assemble_radar_fail_items(
        radar_fails, background, related
    )
    if merged_items:
        unit = (
            radar_fails.unit
            if radar_fails is not None
            else FlamesUnitRef(
                unit_id=f"radar-text-{rid}", serial=serial, radar_id=rid
            )
        )
        fails = FailItemsResult(
            unit=unit,
            records=(),
            fail_items=merged_items,
            cached_logs=cached_logs,
            source="radar",
            needs_user_input=False,
            user_prompt=None,
        )
        return _make_checkin_result(
            config,
            problem,
            scope,
            fails,
            llm=llm,
            cancel_event=cancel_event,
        )

    # (5) Flames — lowest priority; only reached when the face + attachments
    # yielded nothing. A lab Flames may be empty (manual backend) → skip.
    fails = flames.collect_fail_items(rid, serial=serial, cache_dir=cache)
    if fails.fail_items and not fails.needs_user_input:
        fails = _retag_result(fails, "flames")
        return _make_checkin_result(
            config,
            problem,
            scope,
            fails,
            llm=llm,
            cancel_event=cancel_event,
        )

    # (6) Ask the user to paste evidence.
    prompt = (
        _RADAR_UNPARSED_PROMPT
        if radar_has_evidence_corpus(problem)
        else _NO_EVIDENCE_PROMPT
    )
    extra_cached = tuple(
        dict.fromkeys(
            [*(fails.cached_logs), *cached_logs, *related.cached_rels()]
        )
    )
    fails = FailItemsResult(
        unit=fails.unit,
        records=fails.records,
        fail_items=fails.fail_items,
        cached_logs=extra_cached,
        source=fails.source,
        needs_user_input=True,
        user_prompt=prompt,
    )
    return _make_checkin_result(
        config,
        problem,
        scope,
        fails,
        llm=llm,
        cancel_event=cancel_event,
    )


def _cache_radar_corpus(
    config: AppConfig,
    problem: RadarProblem,
    cache_dir: Path,
) -> tuple[str, str] | None:
    """Write the Radar face corpus to cache; return ``(corpus, rel_path)``.

    Returns ``None`` when the face has no text. Written even when no LLM is
    available so the paste branch can still reference ``radar_corpus.txt``.
    """
    corpus = compose_radar_evidence_corpus(problem)
    if not corpus:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = cache_dir / "radar_corpus.txt"
    corpus_path.write_text(corpus, encoding="utf-8")
    rel = str(corpus_path.relative_to(config.cache_dir)).replace("\\", "/")
    return corpus, rel


def _extract_radar_fail_items(
    config: AppConfig,
    corpus: str,
    corpus_rel: str,
    problem: RadarProblem,
    *,
    serial: str | None,
    llm: LlmBackend | None,
    cancel_event: threading.Event | None,
) -> FailItemsResult | None:
    """Extract fail items from the cached Radar face corpus (LLM)."""
    unit = FlamesUnitRef(
        unit_id=f"radar-text-{problem.radar_id}",
        serial=serial,
        radar_id=problem.radar_id,
    )
    if llm is None:
        logger.info(
            "Radar corpus cached for %s but no LLM — cannot extract fail items",
            problem.radar_id,
        )
        return None

    from ee_wiki.generation.fa_evidence import extract_fail_items_from_radar_corpus

    items = extract_fail_items_from_radar_corpus(
        corpus,
        llm=llm,
        repo_root=config.repo_root,
        cancel_event=cancel_event,
    )
    if items is None:
        return None
    return FailItemsResult(
        unit=unit,
        records=(),
        fail_items=tuple(items),
        cached_logs=(corpus_rel,),
        source="radar",
        needs_user_input=False,
        user_prompt=None,
    )


@dataclass(frozen=True)
class _RelatedFile:
    """One LLM-selected strong-related attachment for a check-in."""

    name: str
    kind: str
    status: str  # cached | image | over_count | over_size | failed
    rel: str | None = None
    url: str | None = None
    text: str | None = None
    note: str = ""


@dataclass(frozen=True)
class _RelatedEvidence:
    """Result of bounded materialization of strong-related attachments."""

    files: tuple[_RelatedFile, ...] = ()

    def cached_rels(self) -> list[str]:
        """Return cache-relative paths of every materialized file."""
        return [f.rel for f in self.files if f.rel]

    def text_files(self) -> list[_RelatedFile]:
        """Return materialized non-picture files that carry decoded text."""
        return [f for f in self.files if f.text]


def _materialize_related_evidence(
    config: AppConfig,
    problem: RadarProblem,
    related_names: tuple[str, ...],
    *,
    cancel_event: threading.Event | None,
) -> _RelatedEvidence:
    """Download the LLM-selected strong-related attachments, bounded by caps.

    Only names that exist in ``problem.attachments`` are fetched (the LLM step
    already demoted unknown names to ``unresolved``). Count / per-file /
    total byte caps from ``config.fa.checkin`` prevent a check-in stall; files
    beyond a cap are recorded with ``status`` set but never downloaded. Picture
    attachments are materialized for a link but not scanned as fail logs.
    """
    if not related_names:
        return _RelatedEvidence()

    from ee_wiki.api.stream_status import FA_DOWNLOAD_STATUS
    from ee_wiki.api.stream_status_context import push_stream_status
    from ee_wiki.integrations.fa_errors import format_fa_error
    from ee_wiki.integrations.radar.attachments import (
        cached_attachment_path,
        materialize_attachment,
        read_attachment_text,
    )

    caps = config.fa.checkin
    meta_by_name = {
        a.file_name: a for a in problem.attachments if a.file_name
    }
    # Pre-plan which names we will attempt so download progress totals are stable.
    planned: list[tuple[str, str, int | None]] = []
    for name in related_names:
        meta = meta_by_name.get(name)
        if meta is None:
            continue
        kind = meta.kind or "attachment"
        size = meta.file_size
        planned.append((name, kind, size))

    # Count how many planned files still need a Radar fetch (not already cached
    # and not over caps) so the UI shows (1/N)…(N/N) during check-in.
    pending_fetch: list[str] = []
    preview_downloaded = 0
    preview_bytes = 0
    for name, kind, size in planned:
        if preview_downloaded >= caps.max_related_files:
            break
        if size is not None and size > caps.max_related_file_bytes:
            continue
        if (
            size is not None
            and preview_bytes + size > caps.max_related_total_bytes
        ):
            continue
        if cached_attachment_path(config, problem.radar_id, name) is None:
            pending_fetch.append(name)
        preview_downloaded += 1
        if size is not None:
            preview_bytes += size
    fetch_total = len(pending_fetch)
    fetch_done = 0

    files: list[_RelatedFile] = []
    downloaded = 0
    total_bytes = 0
    for name, kind, size in planned:
        if cancel_event and cancel_event.is_set():
            break
        if downloaded >= caps.max_related_files:
            files.append(_RelatedFile(name, kind, status="over_count"))
            continue
        if size is not None and size > caps.max_related_file_bytes:
            files.append(_RelatedFile(name, kind, status="over_size"))
            continue
        if (
            size is not None
            and total_bytes + size > caps.max_related_total_bytes
        ):
            files.append(_RelatedFile(name, kind, status="over_size"))
            continue
        needs_fetch = cached_attachment_path(config, problem.radar_id, name) is None
        if needs_fetch and fetch_total:
            fetch_done += 1
            push_stream_status(
                FA_DOWNLOAD_STATUS.format(done=fetch_done, total=fetch_total)
            )
        try:
            path, rel, url = materialize_attachment(
                config, problem.radar_id, name, kind=kind
            )
        except IntegrationError as exc:
            note = format_fa_error(exc, context="attachment", style="inline")
            files.append(_RelatedFile(name, kind, status="failed", note=note))
            logger.warning(
                "Skip related-evidence materialize rdar://%s name=%s",
                problem.radar_id,
                name,
                exc_info=True,
            )
            continue
        downloaded += 1
        actual = path.stat().st_size if path.is_file() else 0
        total_bytes += actual
        if kind == "picture":
            files.append(
                _RelatedFile(name, kind, status="image", rel=rel, url=url)
            )
            continue
        text = read_attachment_text(path)
        files.append(
            _RelatedFile(name, kind, status="cached", rel=rel, url=url, text=text)
        )
    return _RelatedEvidence(files=tuple(files))


def _assemble_radar_fail_items(
    radar_fails: FailItemsResult | None,
    background,
    related: _RelatedEvidence,
) -> tuple[tuple[FailItem, ...], tuple[str, ...]]:
    """Merge face-extracted fails + attachment FAIL lines + true-fail hint.

    Returns ``(fail_items, cached_logs)`` with per-item ``source`` tags and a
    de-duplicated cache path list (corpus + materialized related files).
    """
    from ee_wiki.integrations.radar.attachments import extract_fail_lines

    items: list[FailItem] = []
    cached: list[str] = []

    if radar_fails is not None:
        for it in radar_fails.fail_items:
            items.append(_retag_item(it, "radar_text"))
        cached.extend(radar_fails.cached_logs)

    for rf in related.files:
        if rf.rel:
            cached.append(rf.rel)
        if not rf.text:
            continue
        for line in extract_fail_lines(rf.text):
            items.append(
                FailItem(
                    message=line,
                    station=rf.name,
                    log_rel_path=rf.rel,
                    source="radar_attachment",
                )
            )

    if not items and background is not None and background.true_fail_hint:
        items.append(
            FailItem(
                message=background.true_fail_hint,
                station="radar",
                source="radar_title",
            )
        )

    seen: set[str] = set()
    deduped: list[FailItem] = []
    for it in items:
        key = it.message.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(it)
    cached_unique = tuple(dict.fromkeys(c for c in cached if c))
    return tuple(deduped), cached_unique


def _retag_item(item: FailItem, source: str) -> FailItem:
    """Return ``item`` with ``source`` set when it is currently unset."""
    if item.source:
        return item
    return FailItem(
        message=item.message,
        station=item.station,
        record_id=item.record_id,
        log_rel_path=item.log_rel_path,
        line_no=item.line_no,
        source=source,
    )


def _retag_result(fails: FailItemsResult, source: str) -> FailItemsResult:
    """Return ``fails`` with every fail item's ``source`` tagged."""
    return FailItemsResult(
        unit=fails.unit,
        records=fails.records,
        fail_items=tuple(_retag_item(it, source) for it in fails.fail_items),
        cached_logs=fails.cached_logs,
        source=fails.source,
        needs_user_input=fails.needs_user_input,
        user_prompt=fails.user_prompt,
    )


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
    title: str | None = None,
    state: str | None = None,
    substate: str | None = None,
    fail_items: tuple[str, ...] = (),
    true_fail_notes: str | None = None,
    root_cause: str | None = None,
    steps: tuple[str, ...] = (),
    conclusion: str | None = None,
) -> tuple[FaReportResult, str]:
    """Generate Keynote FA summary and return result + download URL.

    Args:
        config: Loaded application configuration.
        radar_id: Radar id.
        product: Optional product label for the template.
        project: Optional project label for the template.
        build: Optional build label.
        title: Optional title override (Radar title).
        state: Radar state.
        substate: Radar substate.
        fail_items: Fail item strings.
        true_fail_notes: Human true-fail notes.
        root_cause: Root-cause text when known.
        steps: FA step summaries (often from Radar diagnosis).
        conclusion: Latest-status conclusion (Radar-sourced).

    Returns:
        Report result and browser download URL.
    """
    backend = build_fa_report_backend(config)
    result = backend.generate(
        FaReportRequest(
            radar_id=radar_id,
            product=product,
            project=project,
            build=build,
            title=title,
            state=state,
            substate=substate,
            fail_items=fail_items,
            true_fail_notes=true_fail_notes,
            root_cause=root_cause,
            steps=steps,
            conclusion=conclusion,
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
    *,
    ai_summary: str | None = None,
) -> FaCheckinResult:
    """Attach download URLs and markdown to a fail-items payload."""
    log_urls = tuple(
        public_url(config, f"/v1/cache/{quote(rel, safe='/')}")
        for rel in fails.cached_logs
    )
    awaiting = bool(fails.needs_user_input)
    summary = _format_checkin_markdown(
        config,
        problem,
        scope,
        fails,
        ai_summary=ai_summary,
    )
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


def _make_checkin_result(
    config: AppConfig,
    problem: RadarProblem,
    scope: ScopeResolution,
    fails: FailItemsResult,
    *,
    llm: LlmBackend | None = None,
    cancel_event: threading.Event | None = None,
) -> FaCheckinResult:
    """Build a check-in result, generating the LLM AI Summary when possible."""
    ai_summary = None
    if llm is not None and not (cancel_event and cancel_event.is_set()):
        from ee_wiki.api.stream_status import FA_AI_SUMMARY_STATUS
        from ee_wiki.api.stream_status_context import push_stream_status
        from ee_wiki.generation.fa_evidence import generate_checkin_ai_summary

        push_stream_status(FA_AI_SUMMARY_STATUS)
        ai_summary = generate_checkin_ai_summary(
            problem,
            fails,
            llm=llm,
            repo_root=config.repo_root,
            cancel_event=cancel_event,
        )
    return _build_checkin_result(
        config,
        problem,
        scope,
        fails,
        ai_summary=ai_summary,
    )


def _format_checkin_markdown(
    config: AppConfig,
    problem: RadarProblem,
    scope: ScopeResolution,
    fails: FailItemsResult,
    *,
    ai_summary: str | None = None,
) -> str:
    """Build the V2 FA check-in markdown for Open WebUI.

    Order: Title / Component / Fail items (or Need test evidence) /
    Description (quote + collapsible full text) / Diagnosis (email-only
    authors, first 3 shown, rest folded) / Attachments (first 2 shown, rest
    folded; cached → download link) / AI Summary (LLM narrative). Scope
    travels via the invisible ``<!-- ee-wiki-scope -->`` marker, so it is
    intentionally NOT printed here. Fail-item ``source`` stays in structured
    data / logs — never shown in the user-facing face.
    """
    rid = problem.radar_id
    lines: list[str] = [
        f"## FA check-in — rdar://{rid}",
        "",
        f"**Title:** {problem.title or '—'}",
    ]
    if problem.component:
        lines.append(
            f"**Component:** {problem.component.name} | {problem.component.version}"
        )

    if fails.needs_user_input:
        lines.extend(
            [
                "",
                "### Need test evidence",
                fails.user_prompt
                or "Please paste the test log or a list of error items.",
            ]
        )
    else:
        lines.extend(["", "### Fail items"])
        if not fails.fail_items:
            lines.append("_No structured fail items extracted._")
        else:
            for item in fails.fail_items:
                station = item.station or "?"
                lines.append(f"- [{station}] {item.message}")

    # Description: short quoted preview; fold only when there is more to show.
    if problem.description:
        full = "\n\n".join(
            d.text.strip() for d in problem.description if d.text and d.text.strip()
        )
        if full:
            first_line = full.split("\n", 1)[0].strip()
            preview = first_line
            if len(preview) > 160:
                preview = preview[:157] + "..."
            lines.extend(["", "### Description", "", f"> {preview}"])
            if full != preview:
                lines.extend(
                    [
                        "",
                        "<details><summary>展开完整 Description</summary>",
                        "",
                        full,
                        "",
                        "</details>",
                    ]
                )

    # Diagnosis: email-only authors; first 3 shown, rest folded.
    user_diag = user_diagnosis_entries(problem)
    if user_diag:
        lines.extend(["", "### Diagnosis"])
        shown, rest = user_diag[:3], user_diag[3:]
        for item in shown:
            who = _author_email(item.added_by)
            body = item.text.strip()
            if len(body) > 400:
                body = body[:397].rstrip() + "…"
            lines.append(f"- **{who}:** {body}")
        if rest:
            lines.append("")
            lines.append(
                f"<details><summary>展开其余 {len(rest)} 条 diagnosis</summary>"
            )
            lines.append("")
            for item in rest:
                who = _author_email(item.added_by)
                body = item.text.strip()
                if len(body) > 400:
                    body = body[:397].rstrip() + "…"
                lines.append(f"- **{who}:** {body}")
            lines.append("")
            lines.append("</details>")

    # Attachments: first 2 shown, rest folded; cached → download link.
    att_names = [a.file_name for a in problem.attachments if a.file_name]
    if att_names:
        from ee_wiki.integrations.radar.attachments import (
            summarize_attachment_inventory,
        )

        # Problem 1 follow-up: do NOT eagerly download every attachment at
        # check-in. Only list what is available + what is already cached; pull
        # bytes on demand when the user asks to download / analyze a log.
        inventory, att_total, att_cached = summarize_attachment_inventory(
            config, problem
        )
        lines.extend(["", "### Attachments", ""])
        shown, rest = inventory[:2], inventory[2:]
        for entry in shown:
            lines.append(_attachment_line(config, rid, entry))
        if rest:
            lines.append("")
            lines.append(
                f"<details><summary>展开其余 {len(rest)} 个附件</summary>"
            )
            lines.append("")
            for entry in rest:
                lines.append(_attachment_line(config, rid, entry))
            lines.append("")
            lines.append("</details>")
        lines.append(
            f"\n> 已缓存 {att_cached} / {att_total} 个附件"
            "（其余在你说「下载 / 分析 log」或需要查看图片时按需拉取）。"
        )

    if ai_summary:
        lines.extend(["", "### AI Summary", "", ai_summary.strip()])

    if scope.confidence in {"low", "none"}:
        lines.append(
            f"\n> Scope incomplete ({scope.notes}). "
            "Please confirm product/project/build for retrieval."
        )
    return "\n".join(lines)


def _attachment_line(config: AppConfig, rid: str, entry: dict) -> str:
    """Render one attachment inventory row, with a download link when cached."""
    kind_tag = "图片" if entry["kind"] == "picture" else "附件"
    if entry["cached"]:
        rel = f"fa/{rid}/attachments/{entry['name']}"
        url = public_url(config, f"/v1/cache/{quote(rel, safe='/')}")
        cached_tag = f"已缓存 · [下载]({url})"
    else:
        cached_tag = "待下载"
    return f"- `{entry['name']}` — {entry['type']} · {kind_tag} · {cached_tag}"
