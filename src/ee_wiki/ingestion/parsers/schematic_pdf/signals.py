"""Generic schematic net grouping for OCR fidelity ingest.

Groups nets by interface prefix discovered from the page OCR text itself.
No project-specific signal tables in code or configuration.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_POWER_NETS = frozenset({"GND", "AGND", "VCC", "VDD", "VCC3.3", "VCC3V3", "VCC5"})
_DOUBLE_UNDERSCORE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{1,15})__")
_EMBEDDED_DATA_NET_PATTERN = re.compile(
    r"(?:^|[^A-Z0-9])([A-Z]{2,15})[_0]*D(\d+)(?:[^A-Z0-9]|$)",
    re.IGNORECASE,
)
_CLEAN_PREFIX_PATTERN = re.compile(r"\b([A-Z]{2,15})_", re.IGNORECASE)


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
    """Recover ``PREFIX_Dn`` nets embedded in OCR noise (e.g. ``NLDCMI0D0``)."""
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


def build_page_signal_summary(
    module_labels: Sequence[str],
    nets: Sequence[str],
) -> str:
    """Build one page-level summary listing module zones and grouped interface nets."""
    nets_by_prefix = group_nets_by_prefix(nets)
    if not module_labels and not nets_by_prefix:
        return ""

    lines = [
        "## 本页模块与接口信号",
        "",
        "> 由同页 OCR 网络名按接口前缀自动分组；引脚序号请对照原理图 connector。",
        "",
    ]
    if module_labels:
        lines.append("### 模块分区")
        lines.extend(f"- `{label}`" for label in module_labels)
        lines.append("")

    for prefix in sorted(nets_by_prefix):
        prefix_nets = nets_by_prefix[prefix]
        data_bus, control = _partition_prefix_nets(prefix, prefix_nets)
        if data_bus:
            lines.append(f"### 数据总线（{prefix}）")
            lines.extend(f"- `{net}`" for net in data_bus)
            lines.append("")
        if control:
            lines.append(f"### 控制与时钟（{prefix}）")
            lines.extend(f"- `{net}`" for net in control)
            lines.append("")

    power = _power_nets_on_page(nets)
    if power:
        lines.append("### 电源")
        lines.extend(f"- `{net}`" for net in power)
        lines.append("")

    return "\n".join(lines).strip()
