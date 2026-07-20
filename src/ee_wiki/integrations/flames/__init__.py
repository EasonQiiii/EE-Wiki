"""Flames backends for FA sessions."""

from ee_wiki.integrations.flames.manual import ManualFlamesBackend
from ee_wiki.integrations.flames.stub import StubFlamesBackend

__all__ = ["ManualFlamesBackend", "StubFlamesBackend"]
