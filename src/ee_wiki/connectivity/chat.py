"""Chat intercept for schematic trace questions (authoritative-only gate).

The chat/RAG pipeline answers from probabilistic VLM/OCR schematic text, which
is unsafe for connectivity questions. :func:`answer_trace_question` detects a
trace intent and diverts it to the gated connectivity path so the reply is
either grounded on board-verified evidence (CAD netlist / BoardView) or an
explicit refusal — never a guess from VLM text.
"""

from __future__ import annotations

from ee_wiki.connectivity.authority import ADVISORY_REFUSAL
from ee_wiki.connectivity.intent import TraceIntent, detect_trace_intent
from ee_wiki.connectivity.query import ConnectivityQuery

_NO_SIDECAR = (
    "**无法追踪连接（缺少权威连接数据）**\n\n"
    "当前范围没有可用的 `*.connectivity.json` 侧车（CAD netlist）。"
    "BoardView（`.brd`）仅作参考，不作为权威追网依据。"
    "原理图 PDF 的 VLM/OCR 文本不足以可靠追踪连接关系，为避免给失效分析提供"
    "错误依据，这里不返回任何 trace。\n\n"
    "请为该原理图补充 CAD netlist（`.net` / KiCad / Altium）"
    "companion 后重新 ingest，或直接在板上确认。"
)


def _refusal(reason: str) -> str:
    return (
        "**无法提供可靠的连接追踪（authoritative-only 闸门）**\n\n"
        f"{reason}\n\n"
        f"> {ADVISORY_REFUSAL}"
    )


def _format_pins_table(pins: list[dict]) -> str:
    lines = ["| refdes | pin | net | evidence |", "| --- | --- | --- | --- |"]
    for pin in pins:
        lines.append(
            f"| {pin.get('refdes', '')} | {pin.get('pin', '')} "
            f"| {pin.get('net', '')} | {pin.get('evidence', '')} |"
        )
    return "\n".join(lines)


def _format_documents(documents: list[dict]) -> str:
    if not documents:
        return ""
    srcs = sorted({str(d.get("source_file", "")) for d in documents if d.get("source_file")})
    if not srcs:
        return ""
    body = "\n".join(f"- `{src}`" for src in srcs)
    return f"\n\n**来源（board-verified）**：\n{body}"


def _format_found(intent: TraceIntent, result: dict) -> str:
    pins = list(result.get("pins") or [])
    evidence_tags = sorted(
        {
            str(p.get("evidence") or "")
            for p in pins
            if p.get("evidence")
        }
    )
    if intent.kind == "net":
        resolved = result.get("resolved_net") or intent.query
        header = f"**Net `{resolved}` — pin list (board-verified)**"
    else:
        resolved = result.get("resolved_refdes") or intent.query
        header = f"**`{resolved}` — pin list (board-verified)**"
        if intent.pin:
            pins = [
                p
                for p in pins
                if str(p.get("pin", "")).upper() == intent.pin.upper()
            ] or pins
    table = _format_pins_table(pins) if pins else "_(no pin bindings)_"
    limitations = result.get("limitations", "")
    docs = _format_documents(result.get("documents") or [])
    evidence_line = (
        f"\n\n**Evidence tags:** {', '.join(f'`{t}`' for t in evidence_tags)}"
        if evidence_tags
        else ""
    )
    disclaimer = (
        "\n\n_同一 net 上的 pin 列表，不是有向信号路径。"
        "禁止把上表拼成「A 经 B 到 C」的故事；"
        "模块页码 / 接口叙事若不在上表 evidence 中，一律不算。_"
    )
    tail = f"\n\n> {limitations}" if limitations else ""
    return f"{header}\n\n{table}{evidence_line}{docs}{disclaimer}{tail}"


def answer_trace_question(
    question: str,
    *,
    cq: ConnectivityQuery | None,
    connectivity_enabled: bool,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
) -> str | None:
    """Return a gated trace reply, or ``None`` to let normal retrieval handle it.

    Args:
        question: The user's chat message.
        cq: Connectivity query handle, or ``None`` when no sidecars loaded.
        connectivity_enabled: Whether ``schematic_pdf.connectivity.enabled``.
        product: Resolved product scope.
        project: Resolved project scope.
        build: Resolved build scope.

    Returns:
        Markdown reply when the question is a trace/connectivity question
        (authoritative answer or explicit refusal), else ``None``.
    """
    if not connectivity_enabled:
        return None
    intent = detect_trace_intent(question)
    if intent is None:
        return None
    if cq is None:
        return _NO_SIDECAR

    result = cq.resolve_trace(
        intent.kind,
        intent.query,
        product=product,
        project=project,
        build=build,
    )
    if result.get("authority") == "insufficient":
        reason = (
            f"仅在几何/OCR 层（pdf_geometry / ocr_spatial）或 BoardView 参考层找到 "
            f"`{intent.query}` 的线索，没有 CAD netlist 级别的验证数据"
            "（BoardView 仅作参考，不用于追网）。"
        )
        return _refusal(reason)
    if result.get("error") and not result.get("found"):
        candidates = result.get("candidates") or []
        extra = ""
        if candidates:
            listed = ", ".join(f"`{c}`" for c in candidates[:12])
            extra = f"\n\n可选网络：{listed}"
        return _refusal(f"{result['error']}{extra}")
    if not result.get("found"):
        return _refusal(
            f"在权威连接侧车中未找到 `{intent.query}`（net/designator 不存在或范围不匹配）。"
        )
    return _format_found(intent, result)
