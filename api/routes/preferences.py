"""
User preferences endpoints.

GET /api/preferences         — All user preferences with schema metadata.
PUT /api/preferences/{key}   — Update a single preference (write-through to SQLite, validated).
"""

from fastapi import APIRouter, Depends, HTTPException

from api.models import PreferenceUpdate
from core.auth import AuthenticatedUser, UserRole, require_role, role_satisfies
from core.database import DEFAULT_PREFERENCES, get_all_preferences, set_preference

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

# Keys that are read-only (should not be set via API)
_READONLY_KEYS: set[str] = {"last_source_directory", "last_save_directory"}

# Keys that require manager role or higher to update
_SYSTEM_PREF_KEYS: set[str] = {
    "max_concurrent_conversions", "max_upload_size_mb", "max_batch_size_mb",
    "retention_days", "pdf_engine", "pdf_export_engine", "conversion_engine",
    "max_output_path_length", "collision_strategy",
    "scanner_enabled", "scanner_interval_minutes",
    "scanner_business_hours_start", "scanner_business_hours_end",
    "lifecycle_grace_period_hours", "lifecycle_trash_retention_days",
}

# Valid preference keys (whitelist from defaults)
_VALID_KEYS = set(DEFAULT_PREFERENCES.keys())

# Schema describes each preference for the UI
_PREFERENCE_SCHEMA: dict[str, dict] = {
    "default_direction": {
        "type": "select",
        "options": ["to_md", "from_md"],
        "label": "Default conversion direction",
    },
    "ocr_confidence_threshold": {
        "type": "range",
        "min": 0,
        "max": 100,
        "label": "OCR confidence threshold",
    },
    "unattended_default": {
        "type": "toggle",
        "label": "OCR unattended mode",
    },
    "max_upload_size_mb": {
        "type": "number",
        "min": 1,
        "max": 500,
        "label": "Max upload file size (MB)",
    },
    "max_batch_size_mb": {
        "type": "number",
        "min": 1,
        "max": 2000,
        "label": "Max batch size (MB)",
    },
    "retention_days": {
        "type": "number",
        "min": 0,
        "max": 365,
        "label": "Output retention (days, 0 = forever)",
    },
    "max_concurrent_conversions": {
        "type": "number",
        "min": 1,
        "max": 10,
        "label": "Max concurrent conversions",
    },
    "pdf_engine": {
        "type": "select",
        "options": ["pymupdf", "pdfplumber"],
        "label": "PDF extraction engine",
    },
    "pdf_export_engine": {
        "type": "select",
        "options": ["weasyprint"],
        "label": "PDF export engine",
    },
    "conversion_engine": {
        "type": "select",
        "options": ["native"],
        "label": "Conversion engine",
    },
    "last_save_directory": {
        "type": "text",
        "label": "Last save directory",
        "readonly": True,
    },
    "last_source_directory": {
        "type": "text",
        "label": "Last source directory",
        "readonly": True,
    },
    "llm_ocr_correction": {
        "type": "toggle",
        "label": "Use LLM to correct low-confidence OCR text",
    },
    "llm_summarize": {
        "type": "toggle",
        "label": "Generate document summaries",
    },
    "llm_heading_inference": {
        "type": "toggle",
        "label": "Use LLM to infer headings in PDFs",
    },
    "max_output_path_length": {
        "type": "number",
        "min": 100,
        "max": 400,
        "label": "Max output path length (chars)",
    },
    "collision_strategy": {
        "type": "select",
        "options": ["rename", "skip", "error"],
        "label": "Duplicate filename strategy",
    },
    "bulk_active_files_visible": {
        "type": "toggle",
        "label": "Show active files during bulk conversion",
    },
    "vision_enrichment_level": {
        "type": "select",
        "options": ["1", "2", "3"],
        "label": "Visual enrichment level",
    },
    "vision_frame_limit": {
        "type": "number",
        "min": 1,
        "max": 200,
        "label": "Max keyframes per video",
    },
    "vision_save_keyframes": {
        "type": "toggle",
        "label": "Save keyframe images to _markflow/frames/",
    },
    "vision_frame_prompt": {
        "type": "text",
        "label": "Frame description prompt",
    },
    "scanner_enabled": {
        "type": "toggle",
        "label": "Periodic file scanner",
        "description": "Scan source repository every 15 minutes during business hours",
    },
    "scanner_interval_minutes": {
        "type": "number",
        "min": 5,
        "max": 120,
        "label": "Scan interval (minutes)",
        "description": "How often to scan during business hours",
    },
    "scanner_business_hours_start": {
        "type": "str",
        "label": "Business hours start (HH:MM)",
        "description": "Scanner only runs between start and end times on weekdays",
    },
    "scanner_business_hours_end": {
        "type": "str",
        "label": "Business hours end (HH:MM)",
    },
    "lifecycle_grace_period_hours": {
        "type": "number",
        "min": 1,
        "max": 168,
        "label": "Deletion grace period (hours)",
        "description": "How long before a missing file moves to trash. Default: 36 hours.",
    },
    "lifecycle_trash_retention_days": {
        "type": "number",
        "min": 1,
        "max": 365,
        "label": "Trash retention (days)",
        "description": "How long files stay in trash before permanent deletion. Default: 60 days.",
    },
}

# Validation rules per key
_VALIDATORS: dict[str, callable] = {}


def _validate_int_range(value: str, min_val: int, max_val: int, key: str) -> None:
    try:
        n = int(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"'{key}' must be an integer, got '{value}'.",
        )
    if n < min_val or n > max_val:
        raise HTTPException(
            status_code=422,
            detail=f"'{key}' must be between {min_val} and {max_val}, got {n}.",
        )


def _validate_preference(key: str, value: str) -> None:
    """Validate a preference value against its schema. Raises HTTPException on failure."""
    schema = _PREFERENCE_SCHEMA.get(key)
    if not schema:
        return  # no schema = no validation

    ptype = schema.get("type")

    if ptype == "select":
        options = schema.get("options", [])
        if value not in options:
            raise HTTPException(
                status_code=422,
                detail=f"'{key}' must be one of {options}, got '{value}'.",
            )

    elif ptype in ("number", "range"):
        _validate_int_range(value, schema.get("min", 0), schema.get("max", 999999), key)

    elif ptype == "toggle":
        if value not in ("true", "false"):
            raise HTTPException(
                status_code=422,
                detail=f"'{key}' must be 'true' or 'false', got '{value}'.",
            )


# ── GET /api/preferences ──────────────────────────────────────────────────────

@router.get("")
async def get_preferences(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return all user preferences with schema metadata for UI rendering."""
    prefs = await get_all_preferences()
    return {
        "preferences": prefs,
        "schema": _PREFERENCE_SCHEMA,
    }


# ── PUT /api/preferences/{key} ────────────────────────────────────────────────

@router.put("/{key}")
async def update_preference(
    key: str,
    body: PreferenceUpdate,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict[str, str]:
    """Update a single preference value (validated)."""
    if key in _SYSTEM_PREF_KEYS and not role_satisfies(user.role, UserRole.MANAGER):
        raise HTTPException(
            status_code=403,
            detail=f"System preference '{key}' requires 'manager' role or higher.",
        )
    if key not in _VALID_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown preference key: '{key}'. Valid keys: {sorted(_VALID_KEYS)}",
        )
    if key in _READONLY_KEYS:
        raise HTTPException(status_code=403, detail=f"Preference '{key}' is read-only.")

    _validate_preference(key, body.value)

    await set_preference(key, body.value)
    return {"key": key, "value": body.value}
