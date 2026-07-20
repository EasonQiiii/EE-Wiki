"""Build FA integration backends from :class:`AppConfig`."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.config import AppConfig, FaConfig
from ee_wiki.common.errors import ConfigError
from ee_wiki.integrations.flames.manual import ManualFlamesBackend
from ee_wiki.integrations.flames.stub import StubFlamesBackend
from ee_wiki.integrations.radar.stub import StubRadarBackend
from ee_wiki.integrations.report.keynote import StubKeynoteFaReportBackend
from ee_wiki.protocols.fa_report import FaReportBackend
from ee_wiki.protocols.flames import FlamesBackend
from ee_wiki.protocols.radar import RadarBackend


def build_radar_backend(config: AppConfig | FaConfig) -> RadarBackend:
    """Construct the configured Radar backend.

    Args:
        config: Full app config or FA config section.

    Returns:
        Radar backend instance.

    Raises:
        ConfigError: If the backend name is unknown or live backend cannot start.
    """
    fa = config.fa if isinstance(config, AppConfig) else config
    backend = fa.radar.backend.strip().lower()
    if backend == "stub":
        return StubRadarBackend(
            default_component_name=fa.radar.stub_component_name,
            default_component_version=fa.radar.stub_component_version,
        )
    if backend == "radarclient":
        from ee_wiki.integrations.radar.client import RadarclientBackend

        return RadarclientBackend(
            client_system_name=fa.radar.client_system_name,
            client_system_version=fa.radar.client_system_version,
        )
    raise ConfigError(f"Unknown fa.radar.backend: {fa.radar.backend!r}")


def build_flames_backend(config: AppConfig | FaConfig) -> FlamesBackend:
    """Construct the configured Flames backend.

    Args:
        config: Full app config or FA config section.

    Returns:
        Flames backend instance.

    Raises:
        ConfigError: If the backend name is unknown or live backend cannot start.
    """
    fa = config.fa if isinstance(config, AppConfig) else config
    backend = fa.flames.backend.strip().lower()
    if backend == "manual":
        return ManualFlamesBackend()
    if backend == "stub":
        return StubFlamesBackend()
    if backend == "live":
        from ee_wiki.integrations.flames.client import LiveFlamesBackend

        return LiveFlamesBackend(base_url=fa.flames.base_url)
    raise ConfigError(f"Unknown fa.flames.backend: {fa.flames.backend!r}")


def build_fa_report_backend(config: AppConfig) -> FaReportBackend:
    """Construct the Keynote FA report backend.

    Args:
        config: Loaded application configuration.

    Returns:
        Report backend writing under ``config.exports_dir``.
    """
    template = config.fa.report.template_path
    template_path: Path | None = None
    if template:
        candidate = Path(template)
        if not candidate.is_absolute():
            candidate = (config.repo_root / candidate).resolve()
        template_path = candidate
    return StubKeynoteFaReportBackend(
        exports_dir=config.exports_dir,
        template_path=template_path,
    )
