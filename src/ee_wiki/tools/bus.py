"""Shared ToolBus runtime for MCP and agents (ADR 0008).

Every read-only capability in :mod:`ee_wiki.tools.handlers` is invoked through
:class:`ToolBus`. The bus enforces timeout, concurrency limits, scope clamping,
structured spans, and a hard ban on write/ingest tool names.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.tools import handlers as handlers_mod
from ee_wiki.tools.context import ToolContext
from ee_wiki.tools.scope import ScopeEnvelope

logger = get_logger(__name__)

# Hard-banned capability names (never register; refuse if requested).
BANNED_TOOLS: frozenset[str] = frozenset(
    {
        "ingest",
        "ingest_file",
        "sync_index",
        "build_index",
        "build_graph",
        "rebuild_graph",
        "write_graph",
        "delete_index",
    }
)


class ToolBusError(EEWikiError):
    """ToolBus refused or failed a tool call."""


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one ToolBus call."""

    name: str
    ok: bool
    text: str
    error: str | None = None
    latency_ms: float = 0.0
    caller_id: str = ""


def _arg_digest(args: dict[str, Any]) -> str:
    payload = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _build_registry() -> dict[str, Callable[[ToolContext, dict[str, Any]], str]]:
    """Map tool names to thin adapters over handler functions."""

    def engineering_search(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.engineering_search(
            ctx,
            str(a["query"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            document_type=a.get("document_type"),
            top_k=a.get("top_k"),
        )

    def query_schematic(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.query_schematic(
            ctx,
            str(a["query"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            top_k=a.get("top_k"),
        )

    def search_datasheet(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.search_datasheet(
            ctx,
            str(a["query"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            top_k=a.get("top_k"),
        )

    def search_component(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.search_component(
            ctx,
            str(a["query"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            limit=int(a.get("limit", 20)),
        )

    def search_debug_case(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.search_debug_case(
            ctx,
            str(a["query"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            limit=int(a.get("limit", 20)),
        )

    def query_power_tree(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.query_power_tree(
            ctx,
            str(a.get("query", "")),
            direction=str(a.get("direction", "tree")),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            max_depth=int(a.get("max_depth", 4)),
        )

    def list_engineering_rules(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.list_engineering_rules(
            ctx,
            include_disabled=bool(a.get("include_disabled", False)),
        )

    def evaluate_engineering_rules(ctx: ToolContext, a: dict[str, Any]) -> str:
        rule_id = a.get("rule_id")
        rule_ids = [rule_id] if rule_id else a.get("rule_ids")
        return handlers_mod.evaluate_engineering_rules(
            ctx,
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            rule_ids=rule_ids,
            include_disabled=bool(a.get("include_disabled", False)),
        )

    def graph_neighbors(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.graph_neighbors(
            ctx,
            str(a["query"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            max_hops=int(a.get("max_hops", 1)),
            edge_types=a.get("edge_types"),
        )

    def graph_path(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.graph_path(
            ctx,
            str(a["source"]),
            str(a["target"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            max_depth=int(a.get("max_depth", 8)),
            edge_types=a.get("edge_types"),
        )

    def graph_filter_by_scope(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.graph_filter_by_scope(
            ctx,
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            node_types=a.get("node_types"),
            limit=int(a.get("limit", 200)),
        )

    def open_graph_node(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.open_graph_node(
            ctx,
            str(a["query"]),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
        )

    def list_projects(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.list_projects(ctx)

    def trace_net(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.trace_net(
            ctx,
            str(a.get("net") or a.get("query") or ""),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            source_file=a.get("source_file"),
        )

    def connector_pins(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.connector_pins(
            ctx,
            str(a.get("refdes") or a.get("query") or ""),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            source_file=a.get("source_file"),
        )

    def module_nets(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.module_nets(
            ctx,
            str(a.get("module") or a.get("query") or ""),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            source_file=a.get("source_file"),
            page=a.get("page"),
        )

    def fa_start_checkin(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.fa_start_checkin(
            ctx,
            str(a.get("query") or ""),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
        )

    def fa_session_turn(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.fa_session_turn(
            ctx,
            str(a.get("query") or ""),
            product=a.get("product"),
            project=a.get("project"),
            build=a.get("build"),
            history_json=a.get("history_json"),
        )

    def radar_get_problem(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.radar_get_problem(ctx, str(a.get("query") or ""))

    def radar_download_attachment(ctx: ToolContext, a: dict[str, Any]) -> str:
        return handlers_mod.radar_download_attachment(
            ctx,
            str(a.get("query") or ""),
            radar_id=a.get("radar_id"),
        )

    return {
        "engineering_search": engineering_search,
        "query_schematic": query_schematic,
        "search_datasheet": search_datasheet,
        "search_component": search_component,
        "search_debug_case": search_debug_case,
        "query_power_tree": query_power_tree,
        "list_engineering_rules": list_engineering_rules,
        "evaluate_engineering_rules": evaluate_engineering_rules,
        "graph_neighbors": graph_neighbors,
        "graph_path": graph_path,
        "graph_filter_by_scope": graph_filter_by_scope,
        "open_graph_node": open_graph_node,
        "list_projects": list_projects,
        "trace_net": trace_net,
        "connector_pins": connector_pins,
        "module_nets": module_nets,
        "fa_start_checkin": fa_start_checkin,
        "fa_session_turn": fa_session_turn,
        "radar_get_problem": radar_get_problem,
        "radar_download_attachment": radar_download_attachment,
    }


REGISTERED_TOOLS: frozenset[str] = frozenset(_build_registry().keys())


class ToolBus:
    """Process-local gateway over read-only tool handlers."""

    def __init__(
        self,
        ctx: ToolContext,
        *,
        timeout_seconds: float = 60.0,
        max_concurrent: int = 2,
        span_log: Path | None = None,
    ) -> None:
        """Initialize the bus.

        Args:
            ctx: Shared tool context (retrieval engine).
            timeout_seconds: Per-call wall-clock timeout.
            max_concurrent: Max in-flight tool calls.
            span_log: Optional JSONL path for structured spans.
        """
        self._ctx = ctx
        self._timeout = max(0.1, float(timeout_seconds))
        self._semaphore = BoundedSemaphore(max(1, int(max_concurrent)))
        self._span_log = span_log
        self._registry = _build_registry()
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_concurrent)))

    @property
    def registered_tools(self) -> frozenset[str]:
        """Return the set of callable tool names."""
        return frozenset(self._registry.keys())

    def call(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        caller_id: str = "anonymous",
        scope: ScopeEnvelope | None = None,
    ) -> ToolResult:
        """Invoke a registered tool under scope + runtime guards.

        Args:
            name: Tool name (must be in the registry, not banned).
            args: Tool arguments.
            caller_id: Supervisor or specialist id for spans.
            scope: Optional scope envelope (clamps product/project/build).

        Returns:
            :class:`ToolResult` with text or error detail.
        """
        started = time.monotonic()
        raw_args = dict(args or {})
        envelope = scope or ScopeEnvelope()
        clamped = envelope.clamp_args(raw_args)
        digest = _arg_digest(clamped)

        if name in BANNED_TOOLS:
            return self._finish(
                name=name,
                ok=False,
                text="",
                error=f"Tool '{name}' is banned (write/ingest not allowed)",
                started=started,
                caller_id=caller_id,
                digest=digest,
            )
        handler = self._registry.get(name)
        if handler is None:
            return self._finish(
                name=name,
                ok=False,
                text="",
                error=f"Unknown tool '{name}'",
                started=started,
                caller_id=caller_id,
                digest=digest,
            )

        acquired = self._semaphore.acquire(blocking=True, timeout=self._timeout)
        if not acquired:
            return self._finish(
                name=name,
                ok=False,
                text="",
                error="ToolBus concurrency limit: could not acquire slot",
                started=started,
                caller_id=caller_id,
                digest=digest,
            )
        try:
            future = self._executor.submit(handler, self._ctx, clamped)
            try:
                text = future.result(timeout=self._timeout)
            except FuturesTimeout:
                future.cancel()
                return self._finish(
                    name=name,
                    ok=False,
                    text="",
                    error=f"Tool '{name}' timed out after {self._timeout:.0f}s",
                    started=started,
                    caller_id=caller_id,
                    digest=digest,
                )
            except Exception as exc:  # noqa: BLE001 — surface as tool error
                logger.exception("ToolBus tool=%s failed: %s", name, exc)
                return self._finish(
                    name=name,
                    ok=False,
                    text="",
                    error=str(exc),
                    started=started,
                    caller_id=caller_id,
                    digest=digest,
                )
            return self._finish(
                name=name,
                ok=True,
                text=text if isinstance(text, str) else str(text),
                error=None,
                started=started,
                caller_id=caller_id,
                digest=digest,
            )
        finally:
            self._semaphore.release()

    def _finish(
        self,
        *,
        name: str,
        ok: bool,
        text: str,
        error: str | None,
        started: float,
        caller_id: str,
        digest: str,
    ) -> ToolResult:
        latency_ms = (time.monotonic() - started) * 1000.0
        self._emit_span(
            caller_id=caller_id,
            tool=name,
            digest=digest,
            latency_ms=latency_ms,
            ok=ok,
            error=error,
        )
        return ToolResult(
            name=name,
            ok=ok,
            text=text,
            error=error,
            latency_ms=latency_ms,
            caller_id=caller_id,
        )

    def _emit_span(
        self,
        *,
        caller_id: str,
        tool: str,
        digest: str,
        latency_ms: float,
        ok: bool,
        error: str | None,
    ) -> None:
        span = {
            "ts": time.time(),
            "caller": caller_id,
            "tool": tool,
            "arg_digest": digest,
            "latency_ms": round(latency_ms, 1),
            "ok": ok,
            "error": error,
        }
        logger.info(
            "toolbus span caller=%s tool=%s ok=%s latency_ms=%.1f digest=%s",
            caller_id,
            tool,
            ok,
            latency_ms,
            digest,
        )
        if self._span_log is None:
            return
        try:
            self._span_log.parent.mkdir(parents=True, exist_ok=True)
            with self._span_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(span, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Failed to write tool span log: %s", exc)


def open_tool_bus(
    ctx: ToolContext,
    *,
    timeout_seconds: float = 60.0,
    max_concurrent: int = 2,
    span_log: Path | None = None,
) -> ToolBus:
    """Construct a :class:`ToolBus` for the given context."""
    return ToolBus(
        ctx,
        timeout_seconds=timeout_seconds,
        max_concurrent=max_concurrent,
        span_log=span_log,
    )
