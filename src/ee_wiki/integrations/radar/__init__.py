"""Radar backends for FA sessions."""

from ee_wiki.integrations.radar.stub import StubRadarBackend

__all__ = ["StubRadarBackend", "RadarclientBackend"]


def __getattr__(name: str):
    """Lazy-load live backend so importing stub does not require radarclient."""
    if name == "RadarclientBackend":
        from ee_wiki.integrations.radar.client import RadarclientBackend

        return RadarclientBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
