"""
User preference storage and retrieval.
"""

import aiosqlite

from core.db.connection import db_fetch_all, db_fetch_one, get_db

# ── Default preferences ───────────────────────────────────────────────────────
DEFAULT_PREFERENCES: dict[str, str] = {
    "last_save_directory": "",
    "last_source_directory": "",
    "ocr_confidence_threshold": "70",
    "default_direction": "to_md",
    "max_upload_size_mb": "100",
    "max_batch_size_mb": "500",
    "retention_days": "30",
    "max_concurrent_conversions": "10",
    "pdf_engine": "pymupdf",
    "pdf_export_engine": "weasyprint",
    "unattended_default": "false",
    "conversion_engine": "native",
    "llm_ocr_correction": "false",
    "llm_summarize": "false",
    "llm_heading_inference": "false",
    "max_output_path_length": "250",
    "collision_strategy": "rename",
    "bulk_active_files_visible": "true",
    "vision_enrichment_level": "2",
    "vision_frame_limit": "50",
    "vision_save_keyframes": "false",
    "vision_frame_prompt": (
        "Describe this frame from a video. Note any visible text, slides, "
        "diagrams, charts, people, or on-screen graphics. Be concise and "
        "factual. Do not describe what you cannot see clearly."
    ),
    "scanner_enabled": "true",
    "scanner_interval_minutes": "15",
    "scanner_business_hours_start": "06:00",
    "scanner_business_hours_end": "22:00",
    "lifecycle_grace_period_hours": "36",
    "lifecycle_trash_retention_days": "60",
    "worker_count": "8",
    "cpu_affinity_cores": "[]",
    "process_priority": "normal",
    "log_level": "normal",
    # Password recovery
    "password_dictionary_enabled": "true",
    "password_brute_force_enabled": "true",
    "password_brute_force_max_length": "8",
    "password_brute_force_charset": "all_ascii",
    "password_timeout_seconds": "300",
    "password_reuse_found": "true",
    "password_hashcat_enabled": "true",
    "password_hashcat_workload": "3",
    # Auto-conversion
    "auto_convert_mode": "immediate",
    "auto_convert_workers": "8",
    "auto_convert_batch_size": "auto",
    "auto_convert_schedule_windows": "",
    "auto_convert_decision_log_level": "elevated",
    "auto_metrics_retention_days": "30",
    "auto_convert_business_hours_start": "09:00",
    "auto_convert_business_hours_end": "18:00",
    "auto_convert_conservative_factor": "0.7",
    # Pipeline (v0.14.0)
    "pipeline_enabled": "true",
    "pipeline_max_files_per_run": "0",
    "pipeline_startup_delay_minutes": "5",
    "pipeline_auto_reset_days": "3",
    # Cloud file prefetch (v0.15.1)
    "cloud_prefetch_enabled": "false",
    "cloud_prefetch_concurrency": "5",
    "cloud_prefetch_rate_limit": "30",
    "cloud_prefetch_timeout_seconds": "120",
    "cloud_prefetch_min_size_bytes": "0",
    "cloud_prefetch_probe_all": "false",
    # File flagging (v0.16.0)
    "flag_webhook_url": "",
    "flag_default_expiry_days": "14",
    # Scan parallelism (v0.13.1)
    "scan_max_threads": "auto",
    # Search preview (v0.16.3)
    "preview_enabled": "true",
    "preview_size": "medium",
    "preview_delay_ms": "400",
    # Transcription (v0.13.0)
    "whisper_model": "base",
    "whisper_language": "auto",
    "whisper_device": "auto",
    "transcription_cloud_fallback": "true",
    "caption_file_extensions": ".srt,.vtt,.sbv",
    "transcription_timeout_seconds": "3600",
}


async def _init_preferences(conn: aiosqlite.Connection) -> None:
    """Insert default preferences that don't already exist."""
    for key, value in DEFAULT_PREFERENCES.items():
        await conn.execute(
            "INSERT OR IGNORE INTO user_preferences (key, value) VALUES (?, ?)",
            (key, value),
        )
    await conn.commit()


async def get_preference(key: str) -> str | None:
    """Return a single preference value by key."""
    row = await db_fetch_one(
        "SELECT value FROM user_preferences WHERE key = ?", (key,)
    )
    return row["value"] if row else None


async def set_preference(key: str, value: str) -> None:
    """Upsert a preference value."""
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO user_preferences (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
               updated_at=CURRENT_TIMESTAMP""",
            (key, value),
        )
        await conn.commit()


async def get_all_preferences() -> dict[str, str]:
    """Return all preferences as {key: value}."""
    rows = await db_fetch_all("SELECT key, value FROM user_preferences")
    return {r["key"]: r["value"] for r in rows}
