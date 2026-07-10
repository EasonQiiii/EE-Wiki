"""Merged query rewrite and task classification in one LLM call."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.classify import _parse_task_label
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn, format_history, needs_rewrite
from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_extract import (
    KnowledgeLayer,
    parse_prepare_layer,
    validate_inferred_scope,
)

logger = get_logger(__name__)

PREPARE_MAX_TOKENS = 200

_QUERY_LINE = re.compile(r"^QUERY:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_TASK_LINE = re.compile(r"^TASK:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_PRODUCT_LINE = re.compile(r"^PRODUCT:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_REVISION_LINE = re.compile(r"^REVISION:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_LAYER_LINE = re.compile(r"^LAYER:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class PreparedQuery:
    """Rewrite, scope, and task intent produced before retrieval."""

    retrieval_query: str
    task: str | None
    product: str | None = None
    revision: str | None = None
    layer: KnowledgeLayer | None = None


def _load_prepare_template(repo_root: Path) -> str:
    """Load the merged prepare prompt from ``prompts/prepare/default.md``."""
    path = repo_root / "prompts" / "prepare" / "default.md"
    return path.read_text(encoding="utf-8")


def _render_prepare_prompt(
    template: str,
    *,
    history: str,
    question: str,
    known_products: str,
) -> str:
    """Substitute template placeholders."""
    return (
        template.replace("{{history}}", history)
        .replace("{{question}}", question)
        .replace("{{known_products}}", known_products)
        .strip()
    )


def _normalize_optional_field(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip().strip('"').strip("'")
    if not value or value.lower() in {"none", "null", "n/a"}:
        return None
    return value


def should_prepare_query(
    question: str,
    history: list[ConversationTurn] | None,
    *,
    query_rewrite: bool,
    task_classification: bool,
    caller_task: str | None,
    scope_inference: bool = False,
    scope_inference_mode: str = "merged",
    caller_has_scope: bool = False,
) -> bool:
    """Return whether a merged prepare LLM call is needed.

    Args:
        question: Current user question.
        history: Prior conversation turns.
        query_rewrite: Whether rewrite is enabled in config.
        task_classification: Whether auto task classification is enabled.
        caller_task: Explicit task from the API caller, if any.
        scope_inference: Whether scope inference is enabled.
        scope_inference_mode: ``rules``, ``llm``, or ``merged``.
        caller_has_scope: Whether API caller already passed project/build.

    Returns:
        True when rewrite, classification, or scope LLM inference should run.
    """
    needs_classify = task_classification and caller_task is None
    needs_rw = bool(
        query_rewrite
        and history
        and needs_rewrite(question, history)
    )
    needs_scope_llm = (
        scope_inference
        and not caller_has_scope
        and scope_inference_mode in {"llm", "merged"}
    )
    return needs_classify or needs_rw or needs_scope_llm


def _parse_prepare_output(
    raw: str,
    *,
    question: str,
    default_task: str,
    classify: bool,
    catalog: ScopeCatalog | None,
    scope_inference: bool,
) -> PreparedQuery:
    """Parse prepare prompt output lines."""
    query_match = _QUERY_LINE.search(raw)
    task_match = _TASK_LINE.search(raw)
    product_match = _PRODUCT_LINE.search(raw)
    revision_match = _REVISION_LINE.search(raw)
    layer_match = _LAYER_LINE.search(raw)

    retrieval_query = question
    if query_match:
        candidate = query_match.group(1).strip().strip('"').strip("'")
        if candidate:
            max_query_len = max(len(question) * 5, 256)
            if len(candidate) <= max_query_len:
                retrieval_query = candidate
            else:
                logger.warning(
                    "Prepare QUERY line suspiciously long, using original question",
                )

    task: str | None = None
    if classify and task_match:
        parsed = _parse_task_label(task_match.group(1))
        if parsed is not None:
            task = parsed
        else:
            logger.warning(
                "Prepare TASK line unrecognized (%r), using default: %s",
                task_match.group(1).strip(),
                default_task,
            )
            task = default_task
    elif classify:
        logger.warning("Prepare output missing TASK line, using default: %s", default_task)
        task = default_task

    product: str | None = None
    revision: str | None = None
    layer: KnowledgeLayer | None = None
    if scope_inference and catalog is not None:
        product = _normalize_optional_field(
            product_match.group(1) if product_match else None
        )
        revision = _normalize_optional_field(
            revision_match.group(1) if revision_match else None
        )
        layer = parse_prepare_layer(layer_match.group(1) if layer_match else None)
        validated = validate_inferred_scope(
            product=product,
            revision=revision,
            layer=layer,
            catalog=catalog,
        )
        if validated is not None:
            product = validated.product
            revision = validated.revision
            layer = validated.layer
        else:
            product = None
            revision = None
            layer = None

    return PreparedQuery(
        retrieval_query=retrieval_query,
        task=task,
        product=product,
        revision=revision,
        layer=layer,
    )


def _generate_prepare_text(
    llm: LlmBackend,
    prompt: str,
    *,
    cancel_event: threading.Event | None,
) -> str:
    """Run the prepare prompt through the LLM backend."""
    if callable(getattr(llm, "generate_stream", None)):
        parts: list[str] = []
        for fragment in llm.generate_stream(
            prompt,
            max_new_tokens=PREPARE_MAX_TOKENS,
            cancel_event=cancel_event,
        ):
            if cancel_event and cancel_event.is_set():
                return ""
            parts.append(fragment)
        return "".join(parts).strip()
    return llm.generate(prompt, max_new_tokens=PREPARE_MAX_TOKENS).strip()


def prepare_query(
    question: str,
    history: list[ConversationTurn] | None,
    *,
    llm: LlmBackend,
    repo_root: Path,
    default_task: str = "wiki",
    query_rewrite: bool = True,
    task_classification: bool = True,
    scope_inference: bool = False,
    catalog: ScopeCatalog | None = None,
    caller_task: str | None = None,
    cancel_event: threading.Event | None = None,
    max_history_turns: int = 4,
) -> PreparedQuery:
    """Rewrite, classify, and optionally infer scope in one LLM call.

    Args:
        question: Current user question.
        history: Prior conversation turns.
        llm: LLM backend for generation.
        repo_root: Repository root for loading prompt templates.
        default_task: Fallback task when classification fails.
        query_rewrite: Whether rewrite is enabled (output still parsed when False).
        task_classification: Whether to parse the ``TASK:`` line.
        scope_inference: Whether to parse PRODUCT/REVISION/LAYER lines.
        catalog: Known products and revisions for validating scope output.
        caller_task: Explicit task from caller; prepare is skipped upstream when set.
        cancel_event: Optional cancellation signal.
        max_history_turns: Maximum history turns in the prompt.

    Returns:
        Prepared retrieval query, optional task label, and optional scope fields.
    """
    if cancel_event and cancel_event.is_set():
        return PreparedQuery(retrieval_query=question, task=None)

    classify = task_classification and caller_task is None
    history_turns = history or []
    history_text = (
        format_history(history_turns, max_turns=max_history_turns)
        if history_turns
        else "(none)"
    )

    template = _load_prepare_template(repo_root)
    known_products = catalog.format_known_products() if catalog is not None else "(none)"
    prompt = _render_prepare_prompt(
        template,
        history=history_text,
        question=question,
        known_products=known_products,
    )

    logger.info(
        "Preparing query (rewrite=%s, classify=%s, scope=%s, history_turns=%d): %s",
        query_rewrite,
        classify,
        scope_inference,
        len(history_turns),
        question[:80],
    )

    try:
        raw_output = _generate_prepare_text(llm, prompt, cancel_event=cancel_event)
    except Exception:
        logger.warning("Query prepare failed, using original question", exc_info=True)
        return PreparedQuery(
            retrieval_query=question,
            task=default_task if classify else None,
        )

    if cancel_event and cancel_event.is_set():
        return PreparedQuery(retrieval_query=question, task=None)

    if not raw_output:
        logger.warning("Query prepare returned empty, using original question")
        return PreparedQuery(
            retrieval_query=question,
            task=default_task if classify else None,
        )

    prepared = _parse_prepare_output(
        raw_output,
        question=question,
        default_task=default_task,
        classify=classify,
        catalog=catalog,
        scope_inference=scope_inference,
    )

    if not query_rewrite:
        prepared = replace(prepared, retrieval_query=question)

    if prepared.product or prepared.revision or prepared.layer:
        logger.info(
            "Query prepared: %r -> %r (task=%s, product=%s, revision=%s, layer=%s)",
            question[:60],
            prepared.retrieval_query[:80],
            prepared.task,
            prepared.product,
            prepared.revision,
            prepared.layer,
        )
    elif prepared.task is not None:
        logger.info(
            "Query prepared: %r -> %r (task=%s)",
            question[:60],
            prepared.retrieval_query[:80],
            prepared.task,
        )
    else:
        logger.info(
            "Query prepared: %r -> %r",
            question[:60],
            prepared.retrieval_query[:80],
        )

    return prepared
