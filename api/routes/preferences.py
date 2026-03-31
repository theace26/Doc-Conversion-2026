"""
User preferences endpoints.

GET /api/preferences         — All user preferences with schema metadata.
PUT /api/preferences/{key}   — Update a single preference (write-through to SQLite, validated).
"""

from fastapi import APIRouter, Depends, HTTPException

from api.models import PreferenceUpdate
from core.auth import AuthenticatedUser, UserRole, require_role, role_satisfies
from core.database import DEFAULT_PREFERENCES, get_all_preferences, set_preference
from core.logging_config import update_log_level

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
    "worker_count", "cpu_affinity_cores", "process_priority",
    "log_level",
    "password_dictionary_enabled", "password_brute_force_enabled",
    "password_brute_force_max_length", "password_brute_force_charset",
    "password_timeout_seconds", "password_reuse_found",
    "password_hashcat_enabled", "password_hashcat_workload",
    "auto_convert_mode", "auto_convert_workers", "auto_convert_batch_size",
    "auto_convert_schedule_windows", "auto_convert_decision_log_level",
    "auto_metrics_retention_days", "auto_convert_business_hours_start",
    "auto_convert_business_hours_end", "auto_convert_conservative_factor",
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
    "worker_count": {
        "type": "number",
        "min": 1,
        "max": 32,
        "label": "Worker count",
        "description": "Parallel conversion jobs. Takes effect on next bulk run.",
    },
    "cpu_affinity_cores": {
        "type": "text",
        "label": "CPU core affinity (JSON array)",
        "description": "Specific CPU core indices to pin the process to. [] = all cores.",
    },
    "process_priority": {
        "type": "select",
        "options": ["low", "normal", "high"],
        "label": "Process scheduling priority",
        "description": "'high' requires root in Docker.",
    },
    "log_level": {
        "type": "select",
        "options": ["normal", "elevated", "developer"],
        "label": "Logging verbosity",
        "description": "Normal (WARNING+), Elevated (INFO+), Developer (DEBUG + frontend trace)",
    },
    "password_dictionary_enabled": {
        "type": "toggle",
        "label": "Dictionary attack on unknown passwords",
        "description": "Try common passwords from the bundled dictionary when a file is encrypted",
    },
    "password_brute_force_enabled": {
        "type": "toggle",
        "label": "Brute-force password recovery",
        "description": "Try all character combinations up to a configured length (can be slow)",
    },
    "password_brute_force_max_length": {
        "type": "number",
        "min": 1,
        "max": 8,
        "label": "Max brute-force password length",
    },
    "password_brute_force_charset": {
        "type": "select",
        "options": ["numeric", "alpha", "alphanumeric", "all_printable"],
        "label": "Brute-force character set",
    },
    "password_timeout_seconds": {
        "type": "number",
        "min": 10,
        "max": 3600,
        "label": "Password recovery timeout (seconds)",
        "description": "Max time to spend cracking a single file",
    },
    "password_reuse_found": {
        "type": "toggle",
        "label": "Reuse found passwords across batch",
        "description": "Try passwords that worked on other files in the same bulk job",
    },
    "password_hashcat_enabled": {
        "type": "toggle",
        "label": "Use hashcat when available",
        "description": "Enable GPU-accelerated cracking via hashcat (container or host worker)",
    },
    "password_hashcat_workload": {
        "type": "select",
        "options": ["1", "2", "3", "4"],
        "label": "Hashcat workload profile",
        "description": "1=Low (keep responsive), 2=Default, 3=High (dedicated), 4=Maximum (100% GPU)",
    },
    # ── Auto-Conversion ──
    "auto_convert_mode": {
        "type": "select",
        "options": ["off", "immediate", "queued", "scheduled"],
        "label": "Auto-Conversion Mode",
        "description": "How to handle new/modified files found by the lifecycle scanner. Off = detect only.",
        "section": "auto_conversion",
    },
    "auto_convert_workers": {
        "type": "select",
        "options": ["auto", "1", "2", "3", "4", "6", "8", "10"],
        "label": "Auto-Conversion Workers",
        "description": "Parallel workers for auto-conversion jobs. Auto adjusts based on system load.",
        "section": "auto_conversion",
    },
    "auto_convert_batch_size": {
        "type": "select",
        "options": ["auto", "25", "50", "100", "250", "500", "unlimited"],
        "label": "Max Batch Size",
        "description": "Maximum files per auto-conversion run. Auto adjusts based on load and time.",
        "section": "auto_conversion",
    },
    "auto_convert_schedule_windows": {
        "type": "text",
        "label": "Scheduled Conversion Windows",
        "description": "JSON time windows for scheduled mode. Example: [{\"start\":\"00:00\",\"end\":\"05:00\",\"days\":[0,1,2,3,4]}]. Empty = auto-detect.",
        "section": "auto_conversion",
    },
    "auto_convert_decision_log_level": {
        "type": "select",
        "options": ["normal", "elevated", "developer"],
        "label": "Decision Logging Level",
        "description": "Detail level for auto-conversion decision logs. Developer adds raw metric snapshots.",
        "section": "auto_conversion",
    },
    "auto_metrics_retention_days": {
        "type": "number",
        "min": 7,
        "max": 365,
        "label": "Metrics Retention (Days)",
        "description": "Historical metrics retention for auto-conversion learning. Longer = better patterns.",
        "section": "auto_conversion",
    },
    "auto_convert_business_hours_start": {
        "type": "select",
        "options": ["00:00", "01:00", "02:00", "03:00", "04:00", "05:00", "06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00"],
        "label": "Business Hours Start",
        "description": "Auto-conversion throttles during business hours.",
        "section": "auto_conversion",
    },
    "auto_convert_business_hours_end": {
        "type": "select",
        "options": ["12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"],
        "label": "Business Hours End",
        "description": "After this time, auto-conversion can be more aggressive.",
        "section": "auto_conversion",
    },
    "auto_convert_conservative_factor": {
        "type": "range",
        "min": 0.3,
        "max": 1.0,
        "step": 0.05,
        "label": "Conservatism Factor",
        "description": "Resource usage caution level. 0.3 = very conservative, 1.0 = full utilization.",
        "section": "auto_conversion",
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
        # Support float ranges (e.g. conservatism factor 0.3-1.0)
        if schema.get("step") and isinstance(schema["step"], float):
            try:
                n = float(value)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"'{key}' must be a number, got '{value}'.",
                )
            if n < schema.get("min", 0) or n > schema.get("max", 999999):
                raise HTTPException(
                    status_code=422,
                    detail=f"'{key}' must be between {schema['min']} and {schema['max']}, got {n}.",
                )
        else:
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

    if key == "log_level":
        update_log_level(body.value)

    return {"key": key, "value": body.value}
