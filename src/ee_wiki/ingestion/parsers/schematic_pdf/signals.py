"""Generic schematic net grouping for OCR fidelity ingest.

Groups nets by interface prefix discovered from the page OCR text itself.
When word bounding boxes are available, bind nets to module zone labels by
spatial proximity (preferred). Otherwise fall back to reading-order proximity.
No project-specific signal tables in code or configuration.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

_POWER_NETS = frozenset({"GND", "AGND", "VCC", "VDD", "VCC3.3", "VCC3V3", "VCC5"})
_DOUBLE_UNDERSCORE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{1,15})__")
_EMBEDDED_DATA_NET_PATTERN = re.compile(
    r"(?:^|[^A-Z0-9])([A-Z]{2,15})[_0]*D(\d+)(?:[^A-Z0-9]|$)",
    re.IGNORECASE,
)
_CLEAN_PREFIX_PATTERN = re.compile(r"\b([A-Z]{2,15})_", re.IGNORECASE)
_LABEL_SPLIT_PATTERN = re.compile(r"[&/\s]+")
_MODULE_NEAR_WINDOW_CHARS = 3000
_SPATIAL_MAX_DISTANCE = 150.0
_BELOW_LABEL_PENALTY = 1.5
_PREFIX_MATCH_BONUS = 40.0

_EMPTY_MODULE_NOTE = (
    "> 同页 OCR 未关联到网络名；该模块引脚请对照原理图 connector，"
    "检索结果不足以列出其引脚时不得臆造。"
)
_SPATIAL_MODULE_NOTE = (
    "> 以下网络名由同页 OCR 词框空间邻近关联得到（非电气连接确认），"
    "仅表示该网络名出现在该模块标签附近；不属于该模块的引脚请勿归因；"
    "引脚序号请对照原理图 connector。"
)
_TEXT_MODULE_NOTE = (
    "> 以下网络名由同页 OCR 文本邻近关联得到（非电气连接确认），"
    "仅表示该网络名出现在该模块标签附近；不属于该模块的引脚请勿归因；"
    "引脚序号请对照原理图 connector。"
)
_GEOMETRY_MODULE_NOTE = (
    "> 以下网络名由 PDF 连接器位号（P/J/…）几何捕获关联得到（evidence=pdf_geometry，"
    "非网表电气确认）；不属于该模块的引脚请勿归因；引脚序号请对照原理图 connector。"
)
_CAD_MODULE_NOTE = (
    "> 以下网络名来自伴随 CAD/网表解析（evidence=cad_netlist）；"
    "引脚序号请对照原理图 connector。"
)
_BOARDVIEW_MODULE_NOTE = (
    "> 以下网络名来自伴随 BoardView（.brd）引脚表（evidence=boardview）；"
    "为板级逻辑连通而非铜皮走线；引脚序号请对照原理图 / boardview。"
    "BoardView 仅作参考，不用于追网（权威追网以 CAD netlist 为准）。"
)


@dataclass(frozen=True)
class OcrToken:
    """One OCR word with page-space bounding box."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        """Horizontal center of the token box."""
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        """Vertical center of the token box."""
        return (self.y0 + self.y1) / 2.0


def _known_prefixes_in_text(text: str) -> set[str]:
    prefixes = {match.group(1).upper() for match in _CLEAN_PREFIX_PATTERN.finditer(text)}
    prefixes.update(
        net.split("_", 1)[0].upper()
        for net in re.findall(r"\b([A-Z][A-Z0-9]{0,15}_[A-Z0-9][A-Z0-9_]{0,31})\b", text, re.I)
    )
    return prefixes


def _pick_prefix_suffix(raw_prefix: str, known_prefixes: set[str]) -> str:
    upper = raw_prefix.upper()
    candidates = [upper[start:] for start in range(len(upper)) if len(upper[start:]) >= 2]
    matching = [candidate for candidate in candidates if candidate in known_prefixes]
    if matching:
        return min(matching, key=len)
    return upper


def normalize_ocr_text(text: str) -> str:
    """Fix double-underscore artifacts in uppercase schematic net names."""
    return _DOUBLE_UNDERSCORE_PATTERN.sub(r"\1_", text)


def recover_noisy_prefix_nets(text: str, *, max_data_index: int = 15) -> set[str]:
    """Recover ``PREFIX_Dn`` nets embedded in OCR noise (e.g. ``NLIFACE0D0``)."""
    normalized = normalize_ocr_text(text)
    known_prefixes = _known_prefixes_in_text(normalized)
    recovered: set[str] = set()
    for match in _EMBEDDED_DATA_NET_PATTERN.finditer(normalized):
        raw_prefix = match.group(1).upper()
        index = int(match.group(2))
        if index > max_data_index:
            continue
        prefix = _pick_prefix_suffix(raw_prefix, known_prefixes)
        recovered.add(f"{prefix}_D{index}")
    return recovered


def group_nets_by_prefix(nets: Sequence[str]) -> dict[str, list[str]]:
    """Group schematic nets by the token before the first underscore."""
    groups: dict[str, list[str]] = {}
    for net in nets:
        if "_" not in net:
            continue
        prefix = net.split("_", 1)[0].upper()
        groups.setdefault(prefix, []).append(net)
    return groups


def _sort_data_bus(nets: Sequence[str], prefix: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(prefix)}_D(\d+)$", re.IGNORECASE)

    def sort_key(net: str) -> tuple[int, str]:
        match = pattern.match(net)
        if match:
            return (0, f"{int(match.group(1)):04d}")
        return (1, net.upper())

    return sorted(nets, key=sort_key)


def _partition_prefix_nets(prefix: str, nets: Sequence[str]) -> tuple[list[str], list[str]]:
    data_pattern = re.compile(rf"^{re.escape(prefix)}_D\d+$", re.IGNORECASE)
    data_bus = [net for net in nets if data_pattern.match(net)]
    control = [net for net in nets if net not in data_bus]
    return _sort_data_bus(data_bus, prefix), sorted(control, key=str.upper)


def _power_nets_on_page(nets: Sequence[str]) -> list[str]:
    power: list[str] = []
    for net in nets:
        upper = net.upper()
        if upper in _POWER_NETS or upper.startswith("VCC") or upper.startswith("VDD"):
            power.append(net)
    return sorted(set(power), key=str.upper)


def _heading(level: int, title: str) -> str:
    return f"{'#' * level} {title}"


def _module_label_tokens(label: str) -> list[str]:
    return [
        token.upper()
        for token in _LABEL_SPLIT_PATTERN.split(label.strip())
        if len(token.strip()) >= 2
    ]


def _normalize_token_text(text: str) -> str:
    return normalize_ocr_text(text).upper().replace("__", "_")


def _ocr_region_for_module(
    label: str,
    ocr_text: str,
    module_labels: Sequence[str],
    *,
    window_chars: int = _MODULE_NEAR_WINDOW_CHARS,
) -> str:
    """Return OCR text after ``label`` until the next module label or window end."""
    upper_ocr = ocr_text.upper()
    upper_label = label.upper()
    position = upper_ocr.find(upper_label)
    if position < 0:
        return ""

    end = min(len(ocr_text), position + window_chars)
    for other in module_labels:
        if other.upper() == upper_label:
            continue
        other_pos = upper_ocr.find(other.upper(), position + len(upper_label))
        if position < other_pos < end:
            end = other_pos
    return ocr_text[position:end]


def nets_for_module_label(
    label: str,
    nets: Sequence[str],
    ocr_text: str,
    *,
    module_labels: Sequence[str] | None = None,
    window_chars: int = _MODULE_NEAR_WINDOW_CHARS,
) -> list[str]:
    """Return nets associated with a module zone label on the same page.

    Uses OCR reading-order proximity around the label and prefix/token overlap.
    Prefer :func:`associate_nets_to_modules` with ``ocr_tokens`` when boxes exist.
    """
    found: set[str] = set()
    labels = list(module_labels) if module_labels is not None else [label]
    region = _ocr_region_for_module(label, ocr_text, labels, window_chars=window_chars).upper()
    if region:
        region_norm = _normalize_token_text(region)
        for net in nets:
            net_upper = net.upper()
            if net_upper in region or net_upper in region_norm:
                found.add(net)

    tokens = _module_label_tokens(label)
    for net in nets:
        prefix = net.split("_", 1)[0].upper()
        if prefix in tokens:
            found.add(net)

    return sorted(found, key=str.upper)


def _label_centers(label: str, tokens: Sequence[OcrToken]) -> list[tuple[float, float]]:
    """Locate module-label centroids from OCR word boxes."""
    upper_label = label.upper()
    exact = [(token.cx, token.cy) for token in tokens if token.text.upper() == upper_label]
    if exact:
        return exact

    parts = [part for part in _LABEL_SPLIT_PATTERN.split(label.strip()) if part]
    if not parts:
        return []

    joined = "&".join(parts).upper()
    joined_hits = [(token.cx, token.cy) for token in tokens if token.text.upper() == joined]
    if joined_hits:
        return joined_hits

    upper_tokens = [(token.text.upper(), token.cx, token.cy) for token in tokens]
    centers: list[tuple[float, float]] = []
    for index, (text, cx, cy) in enumerate(upper_tokens):
        if text != parts[0].upper():
            continue
        points = [(cx, cy)]
        cursor = index + 1
        matched = True
        for part in parts[1:]:
            found = False
            for look in range(cursor, min(cursor + 6, len(upper_tokens))):
                if upper_tokens[look][0] == part.upper():
                    points.append((upper_tokens[look][1], upper_tokens[look][2]))
                    cursor = look + 1
                    found = True
                    break
            if not found:
                matched = False
                break
        if matched:
            centers.append(
                (
                    sum(point[0] for point in points) / len(points),
                    sum(point[1] for point in points) / len(points),
                )
            )
    return centers


def _net_token_matches(net: str, token_text: str) -> bool:
    """Return True when an OCR token represents ``net`` (including noisy forms)."""
    net_upper = net.upper()
    normalized = _normalize_token_text(token_text)
    if normalized == net_upper:
        return True
    if token_text.upper().replace("__", "_") == net_upper:
        return True
    if "_" not in net_upper:
        return False
    prefix, _, suffix = net_upper.partition("_")
    noisy = f"NL{prefix}0{suffix}"
    return normalized == noisy or noisy in normalized


def _net_centers(net: str, tokens: Sequence[OcrToken]) -> list[tuple[float, float]]:
    """Locate net-name centroids from OCR word boxes."""
    centers: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for token in tokens:
        if not _net_token_matches(net, token.text):
            continue
        key = (round(token.cx, 1), round(token.cy, 1))
        if key in seen:
            continue
        seen.add(key)
        centers.append((token.cx, token.cy))
    return centers


def associate_nets_to_modules_spatial(
    module_labels: Sequence[str],
    nets: Sequence[str],
    ocr_tokens: Sequence[OcrToken],
    *,
    max_distance: float = _SPATIAL_MAX_DISTANCE,
) -> dict[str, list[str]]:
    """Assign each net to the nearest module label using word bounding boxes.

    Labels below a net are penalized so zone titles above content win when
    distances are similar. Nets farther than ``max_distance`` stay unassigned.
    """
    label_positions = {
        label: _label_centers(label, ocr_tokens) for label in module_labels
    }
    assigned: dict[str, set[str]] = {label: set() for label in module_labels}

    for net in nets:
        net_points = _net_centers(net, ocr_tokens)
        if not net_points:
            continue
        net_prefix = net.split("_", 1)[0].upper() if "_" in net else ""
        best: tuple[float, float, str] | None = None
        for label, centers in label_positions.items():
            if not centers:
                continue
            label_tokens = set(_module_label_tokens(label))
            prefix_bonus = (
                _PREFIX_MATCH_BONUS if net_prefix and net_prefix in label_tokens else 0.0
            )
            for label_x, label_y in centers:
                for net_x, net_y in net_points:
                    distance = math.hypot(net_x - label_x, net_y - label_y)
                    score = (
                        distance
                        + max(0.0, label_y - net_y) * _BELOW_LABEL_PENALTY
                        - prefix_bonus
                    )
                    if best is None or score < best[0]:
                        best = (score, distance, label)
        if best is not None and best[1] <= max_distance:
            assigned[best[2]].add(net)

    return {
        label: sorted(values, key=str.upper)
        for label, values in assigned.items()
        if label in module_labels
    }


def associate_nets_to_modules(
    module_labels: Sequence[str],
    nets: Sequence[str],
    *,
    ocr_text: str = "",
    ocr_tokens: Sequence[OcrToken] | None = None,
) -> dict[str, list[str]]:
    """Associate nets to module labels via spatial boxes or text proximity."""
    if ocr_tokens:
        return associate_nets_to_modules_spatial(module_labels, nets, ocr_tokens)
    return {
        label: nets_for_module_label(
            label,
            nets,
            ocr_text,
            module_labels=module_labels,
        )
        for label in module_labels
    }


def _format_prefix_groups(
    nets_by_prefix: dict[str, list[str]],
    *,
    heading_level: int,
) -> list[str]:
    lines: list[str] = []
    sub_level = heading_level + 1
    for prefix in sorted(nets_by_prefix):
        prefix_nets = nets_by_prefix[prefix]
        data_bus, control = _partition_prefix_nets(prefix, prefix_nets)
        if data_bus:
            lines.append(_heading(sub_level, f"数据总线（{prefix}）"))
            lines.extend(f"- `{net}`" for net in data_bus)
            lines.append("")
        if control:
            lines.append(_heading(sub_level, f"控制与时钟（{prefix}）"))
            lines.extend(f"- `{net}`" for net in control)
            lines.append("")
    return lines


def _note_for_evidence(evidence: str | None, *, has_tokens: bool) -> str:
    if evidence == "cad_netlist":
        return _CAD_MODULE_NOTE
    if evidence == "boardview":
        return _BOARDVIEW_MODULE_NOTE
    if evidence == "pdf_geometry":
        return _GEOMETRY_MODULE_NOTE
    if has_tokens:
        return _SPATIAL_MODULE_NOTE
    return _TEXT_MODULE_NOTE


def build_module_signal_blocks(
    module_labels: Sequence[str],
    nets: Sequence[str],
    ocr_text: str,
    *,
    heading_level: int = 3,
    ocr_tokens: Sequence[OcrToken] | None = None,
    module_nets_map: dict[str, list[str]] | None = None,
    evidence: str | None = None,
) -> list[str]:
    """Build per-module retrieval blocks with grouped interface nets."""
    associations = module_nets_map or associate_nets_to_modules(
        module_labels,
        nets,
        ocr_text=ocr_text,
        ocr_tokens=ocr_tokens,
    )
    note = _note_for_evidence(evidence, has_tokens=bool(ocr_tokens))
    blocks: list[str] = []
    for label in module_labels:
        label_nets = associations.get(label, [])
        lines = [
            _heading(heading_level, f"模块：{label}"),
            "",
        ]
        if not label_nets:
            lines.append(_EMPTY_MODULE_NOTE)
            blocks.append("\n".join(lines).strip())
            continue
        lines.append(note)
        lines.append("")
        lines.extend(
            _format_prefix_groups(
                group_nets_by_prefix(label_nets),
                heading_level=heading_level,
            )
        )
        power = _power_nets_on_page(label_nets)
        if power:
            lines.append(_heading(heading_level + 1, "电源"))
            lines.extend(f"- `{net}`" for net in power)
            lines.append("")
        blocks.append("\n".join(lines).strip())
    return blocks


def build_page_signal_summary(
    module_labels: Sequence[str],
    nets: Sequence[str],
    *,
    ocr_text: str = "",
    ocr_tokens: Sequence[OcrToken] | None = None,
    heading_level: int = 2,
    module_nets_map: dict[str, list[str]] | None = None,
    evidence: str | None = None,
) -> str:
    """Build one page-level summary listing module zones and grouped interface nets."""
    nets_by_prefix = group_nets_by_prefix(nets)
    if not module_labels and not nets_by_prefix:
        return ""

    sub_level = heading_level + 1
    if evidence == "cad_netlist":
        association_hint = (
            "下方“模块：”分组来自伴随 CAD/网表（evidence=cad_netlist）。"
            "引脚序号请对照原理图 connector。"
        )
    elif evidence == "boardview":
        association_hint = (
            "下方“模块：”分组可对照文档级 BoardView 引脚表（evidence=boardview）；"
            "页内模块区仍以 PDF/OCR 为准。BoardView 为逻辑连通而非铜皮确认。"
        )
    elif evidence == "pdf_geometry":
        association_hint = (
            "下方“模块：”分组优先使用 PDF 连接器几何捕获（evidence=pdf_geometry）；"
            "其余模块回退 OCR 空间邻近。关联为检索辅助而非网表电气确认；"
            "引脚序号请对照原理图 connector。"
        )
    else:
        association_hint = (
            "下方“模块：”分组优先使用 OCR 词框空间邻近；无词框时回退文本邻近。"
            "关联为检索辅助而非电气连接确认；引脚序号请对照原理图 connector。"
        )
    lines = [
        _heading(heading_level, "本页模块与接口信号"),
        "",
        f"> 由同页 OCR 网络名按接口前缀自动分组；{association_hint}",
        "",
    ]
    if module_labels:
        lines.append(_heading(sub_level, "模块分区"))
        lines.extend(f"- `{label}`" for label in module_labels)
        lines.append("")

    if module_labels and (ocr_text or ocr_tokens or module_nets_map):
        # Use the same heading level as the page summary so each ``### 模块：``
        # becomes its own schematic chunk (chunker splits on ``###``, not ``####``).
        for block in build_module_signal_blocks(
            module_labels,
            nets,
            ocr_text,
            heading_level=heading_level,
            ocr_tokens=ocr_tokens,
            module_nets_map=module_nets_map,
            evidence=evidence,
        ):
            lines.append(block)
            lines.append("")

    lines.extend(_format_prefix_groups(nets_by_prefix, heading_level=heading_level))

    power = _power_nets_on_page(nets)
    if power:
        lines.append(_heading(sub_level, "电源"))
        lines.extend(f"- `{net}`" for net in power)
        lines.append("")

    return "\n".join(lines).strip()
