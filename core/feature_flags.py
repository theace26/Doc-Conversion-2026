"""Feature flag accessors. Centralized so tests can monkeypatch one place."""
from __future__ import annotations
import os

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(val: str | None) -> bool:
    return val is not None and val.strip().lower() in _TRUTHY


def is_new_ux_enabled() -> bool:
    """Env-only check — for non-auth contexts (e.g. middleware, health).

    Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §13
    """
    return _is_truthy(os.environ.get("ENABLE_NEW_UX"))


async def is_new_ux_enabled_for(user_sub: str) -> bool:
    """Three-tier lookup: user pref > env bypass > system pref > False.

    User pref always wins (users can always opt in/out).
    Env var bypasses the system DB pref but not the user pref.

    Spec: docs/superpowers/specs/2026-04-30-theme-ux-toggle-display-prefs-design.md §3
    """
    from core.db.connection import get_db_path
    from core.user_prefs import get_user_prefs
    from core.db.preferences import get_preference

    user_pref = await get_user_prefs(get_db_path(), user_sub)
    if "use_new_ux" in user_pref:
        return bool(user_pref["use_new_ux"])

    env_val = os.environ.get("ENABLE_NEW_UX", "").strip().lower()
    if env_val in ("true", "false"):
        return env_val == "true"

    sys_pref = await get_preference("enable_new_ux")
    if sys_pref is not None:
        return sys_pref.strip().lower() == "true"

    return False
