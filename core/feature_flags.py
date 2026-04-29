"""Feature flag accessors. Centralized so tests can monkeypatch one place."""
from __future__ import annotations
import os


_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(val: str | None) -> bool:
    return val is not None and val.strip().lower() in _TRUTHY


def is_new_ux_enabled() -> bool:
    """Whether the v0.35+ UX (Search-as-home, new chrome, role-gated nav) is active.

    Default: False. Production must explicitly set ENABLE_NEW_UX=true.

    Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §13
    """
    return _is_truthy(os.environ.get("ENABLE_NEW_UX"))
