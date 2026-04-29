"""Per-user preferences — portable across machines, keyed by UnionCore sub claim.

Stored as a JSON blob in `mf_user_prefs` (one row per user). Validation
happens at write time; reads always return a dict with all keys present
(defaults filled in for any missing).

Distinct from `core/db/preferences.py`, which manages **system-level**
singleton preferences (one row per key name, table `user_preferences`).
The two stores serve different concerns:

- `core.db.preferences`  -> system config (e.g., `pdf_engine`, `pipeline_enabled`)
- `core.user_prefs`      -> per-user UI state (layout, density, pinned, ...)

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §10
"""
from __future__ import annotations
import json
from pathlib import Path
import aiosqlite
import structlog

log = structlog.get_logger(__name__)


SCHEMA_VER = 1


# Default values for every supported per-user preference. Reads return these
# for missing keys; writes are rejected for keys not in this dict.
DEFAULT_USER_PREFS: dict = {
    # Layout (Spec §3)
    "layout":                    "minimal",   # 'maximal' | 'recent' | 'minimal'
    "density":                   "cards",     # 'cards' | 'compact' | 'list'
    "snippet_length":            "medium",    # 'short' | 'medium' | 'long'
    "show_file_thumbnails":      False,

    # Power-user gate (Spec §9)
    "advanced_actions_inline":   False,       # default off for member; UI initializes True for operator/admin

    # Search history (Spec §3 Recent layout, §10)
    "track_recent_searches":     True,
    "recent_searches":           [],          # list[str], capped to 50

    # Items-per-page per density mode (Spec §13 settings table)
    "items_per_page_cards":      24,
    "items_per_page_compact":    48,
    "items_per_page_list":       250,

    # Pinned (Spec §3 Maximal mode)
    "pinned_folders":            [],
    "pinned_topics":             [],

    # Onboarding (Plan 8 -- empty string = not yet completed)
    "onboarding_completed_at":   "",
}


USER_PREF_KEYS = set(DEFAULT_USER_PREFS.keys())


_ENUMS = {
    "layout":         {"maximal", "recent", "minimal"},
    "density":        {"cards", "compact", "list"},
    "snippet_length": {"short", "medium", "long"},
}
_BOOLS = {"show_file_thumbnails", "advanced_actions_inline", "track_recent_searches"}
_INTS  = {"items_per_page_cards", "items_per_page_compact", "items_per_page_list"}
_LISTS = {"pinned_folders", "pinned_topics"}
_STRS  = {"onboarding_completed_at"}


def _validate(key: str, value):
    """Return (possibly normalized) value if valid; raise ValueError otherwise."""
    if key in _ENUMS:
        if value not in _ENUMS[key]:
            raise ValueError(f"invalid value for {key}: {value!r}")
        return value
    if key in _BOOLS:
        if not isinstance(value, bool):
            raise ValueError(f"invalid value for {key}: must be bool")
        return value
    if key in _INTS:
        if not isinstance(value, int) or value <= 0 or value > 10000:
            raise ValueError(f"invalid value for {key}: must be 1..10000")
        return value
    if key in _LISTS:
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"invalid value for {key}: must be list[str]")
        return value
    if key == "recent_searches":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"invalid value for recent_searches: must be list[str]")
        return value[-50:]
    if key in _STRS:
        if not isinstance(value, str):
            raise ValueError(f"invalid value for {key}: must be str")
        return value
    raise ValueError(f"unknown preference: {key}")


async def get_user_prefs(db_path: Path | str, user_id: str) -> dict:
    """Return user's prefs, with defaults filled in for any missing keys."""
    async with aiosqlite.connect(str(db_path)) as conn:
        async with conn.execute(
            "SELECT value FROM mf_user_prefs WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    stored = json.loads(row[0]) if row else {}
    merged = dict(DEFAULT_USER_PREFS)
    merged.update({k: v for k, v in stored.items() if k in USER_PREF_KEYS})
    return merged


async def set_user_pref(db_path: Path | str, user_id: str, key: str, value) -> None:
    """Validate + persist a single per-user preference."""
    if key not in USER_PREF_KEYS:
        raise ValueError(f"unknown preference: {key}")
    validated = _validate(key, value)
    current = await get_user_prefs(db_path, user_id)
    current[key] = validated
    await _write_all(db_path, user_id, current)


async def set_user_prefs(db_path: Path | str, user_id: str, updates: dict) -> None:
    """Validate + persist multiple per-user preferences atomically."""
    validated = {}
    for k, v in updates.items():
        if k not in USER_PREF_KEYS:
            raise ValueError(f"unknown preference: {k}")
        validated[k] = _validate(k, v)
    current = await get_user_prefs(db_path, user_id)
    current.update(validated)
    await _write_all(db_path, user_id, current)


async def _write_all(db_path: Path | str, user_id: str, prefs: dict) -> None:
    blob = json.dumps(prefs, separators=(",", ":"), sort_keys=True)
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(
            """
            INSERT INTO mf_user_prefs (user_id, value, schema_ver, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT (user_id) DO UPDATE SET
              value      = excluded.value,
              schema_ver = excluded.schema_ver,
              updated_at = datetime('now')
            """,
            (user_id, blob, SCHEMA_VER),
        )
        await conn.commit()
    log.info("user_prefs_saved", user_id=user_id, keys=sorted(prefs.keys()))
