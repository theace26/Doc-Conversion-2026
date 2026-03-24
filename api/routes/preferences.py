"""
User preferences endpoints.

GET /api/preferences         — All user preferences.
PUT /api/preferences/{key}   — Update a single preference (write-through to SQLite).
"""

from fastapi import APIRouter, HTTPException

from api.models import PreferenceUpdate
from core.database import DEFAULT_PREFERENCES, get_all_preferences, set_preference

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

# Keys that are read-only (should not be set via API)
_READONLY_KEYS: set[str] = set()

# Valid preference keys (whitelist from defaults)
_VALID_KEYS = set(DEFAULT_PREFERENCES.keys())


# ── GET /api/preferences ──────────────────────────────────────────────────────

@router.get("")
async def get_preferences() -> dict[str, str]:
    """Return all user preferences as {key: value}."""
    return await get_all_preferences()


# ── PUT /api/preferences/{key} ────────────────────────────────────────────────

@router.put("/{key}")
async def update_preference(key: str, body: PreferenceUpdate) -> dict[str, str]:
    """Update a single preference value."""
    if key not in _VALID_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown preference key: '{key}'. Valid keys: {sorted(_VALID_KEYS)}",
        )
    if key in _READONLY_KEYS:
        raise HTTPException(status_code=403, detail=f"Preference '{key}' is read-only.")

    await set_preference(key, body.value)
    return {"key": key, "value": body.value}
