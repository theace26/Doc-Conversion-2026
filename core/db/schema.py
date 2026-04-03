"""
Schema DDL, versioned migrations, and database initialization.
"""

import uuid

import aiosqlite
import structlog

from core.db.connection import get_db, log

# ── Schema DDL ────────────────────────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversion_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_format TEXT NOT NULL,
    output_filename TEXT NOT NULL,
    output_format TEXT NOT NULL,
    direction TEXT NOT NULL,
    source_path TEXT,
    output_path TEXT,
    file_size_bytes INTEGER,
    ocr_applied BOOLEAN DEFAULT FALSE,
    ocr_flags_total INTEGER DEFAULT 0,
    ocr_flags_resolved INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    duration_ms INTEGER,
    warnings TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_history_created ON conversion_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_batch   ON conversion_history(batch_id);
CREATE INDEX IF NOT EXISTS idx_history_format  ON conversion_history(source_format);
CREATE INDEX IF NOT EXISTS idx_history_status  ON conversion_history(status);

CREATE TABLE IF NOT EXISTS user_preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS batch_state (
    batch_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    total_files INTEGER NOT NULL,
    completed_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    ocr_flags_pending INTEGER DEFAULT 0,
    unattended BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ocr_flags (
    flag_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    page_num INTEGER NOT NULL,
    region_bbox TEXT NOT NULL,          -- JSON: [x1, y1, x2, y2]
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    corrected_text TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    image_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ocr_flags_batch  ON ocr_flags(batch_id);
CREATE INDEX IF NOT EXISTS idx_ocr_flags_status ON ocr_flags(batch_id, status);

CREATE TABLE IF NOT EXISTS bulk_jobs (
    id              TEXT PRIMARY KEY,
    source_path     TEXT NOT NULL,
    output_path     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    worker_count    INTEGER NOT NULL DEFAULT 4,
    include_adobe   INTEGER NOT NULL DEFAULT 1,
    fidelity_tier   INTEGER NOT NULL DEFAULT 2,
    ocr_mode        TEXT NOT NULL DEFAULT 'auto',
    total_files     INTEGER,
    converted       INTEGER NOT NULL DEFAULT 0,
    skipped         INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    adobe_indexed   INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT,
    completed_at    TEXT,
    paused_at       TEXT,
    error_msg       TEXT
);

CREATE TABLE IF NOT EXISTS bulk_files (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES bulk_jobs(id),
    source_path     TEXT NOT NULL,
    output_path     TEXT,
    file_ext        TEXT NOT NULL,
    file_size_bytes INTEGER,
    source_mtime    REAL,
    stored_mtime    REAL,
    content_hash    TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    converted_at    TEXT,
    indexed_at      TEXT,
    UNIQUE(job_id, source_path)
);
CREATE INDEX IF NOT EXISTS idx_bulk_files_job_status ON bulk_files(job_id, status);
CREATE INDEX IF NOT EXISTS idx_bulk_files_source_path ON bulk_files(source_path);

CREATE TABLE IF NOT EXISTS source_files (
    id              TEXT PRIMARY KEY,
    source_path     TEXT NOT NULL UNIQUE,
    file_ext        TEXT NOT NULL,
    file_size_bytes INTEGER,
    source_mtime    REAL,
    stored_mtime    REAL,
    content_hash    TEXT,
    output_path     TEXT,
    mime_type       TEXT,
    file_category   TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    marked_for_deletion_at DATETIME,
    moved_to_trash_at DATETIME,
    purged_at       DATETIME,
    previous_path   TEXT,
    protection_type TEXT DEFAULT 'none',
    password_method TEXT,
    password_attempts INTEGER DEFAULT 0,
    is_archive      INTEGER NOT NULL DEFAULT 0,
    archive_member_count INTEGER,
    archive_total_uncompressed INTEGER,
    is_media        INTEGER NOT NULL DEFAULT 0,
    media_engine    TEXT,
    ocr_confidence_mean REAL,
    ocr_skipped_reason TEXT,
    first_seen_job_id TEXT REFERENCES bulk_jobs(id),
    last_seen_job_id  TEXT REFERENCES bulk_jobs(id),
    created_at      DATETIME DEFAULT (datetime('now')),
    updated_at      DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_source_files_path ON source_files(source_path);
CREATE INDEX IF NOT EXISTS idx_source_files_lifecycle ON source_files(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_source_files_ext ON source_files(file_ext);
CREATE INDEX IF NOT EXISTS idx_source_files_hash ON source_files(content_hash);

CREATE TABLE IF NOT EXISTS adobe_index (
    id              TEXT PRIMARY KEY,
    source_path     TEXT NOT NULL UNIQUE,
    file_ext        TEXT NOT NULL,
    file_size_bytes INTEGER,
    metadata        TEXT,
    text_layers     TEXT,
    indexing_level  INTEGER NOT NULL DEFAULT 2,
    meili_indexed   INTEGER NOT NULL DEFAULT 0,
    indexed_at      TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_adobe_index_ext ON adobe_index(file_ext);

CREATE TABLE IF NOT EXISTS locations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    path        TEXT NOT NULL,
    type        TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS location_exclusions (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    path        TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_providers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    api_key         TEXT,
    api_base_url    TEXT,
    is_active       INTEGER NOT NULL DEFAULT 0,
    is_verified     INTEGER NOT NULL DEFAULT 0,
    last_verified   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bulk_path_issues (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES bulk_jobs(id),
    issue_type      TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    output_path     TEXT,
    collision_group TEXT,
    collision_peer  TEXT,
    resolution      TEXT,
    resolved_path   TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_path_issues_job ON bulk_path_issues(job_id, issue_type);
CREATE INDEX IF NOT EXISTS idx_path_issues_collision_group ON bulk_path_issues(collision_group);

CREATE TABLE IF NOT EXISTS bulk_review_queue (
    id                   TEXT PRIMARY KEY,
    job_id               TEXT NOT NULL REFERENCES bulk_jobs(id),
    bulk_file_id         TEXT NOT NULL REFERENCES bulk_files(id),
    source_path          TEXT NOT NULL,
    file_ext             TEXT NOT NULL,
    estimated_confidence REAL,
    skip_reason          TEXT NOT NULL DEFAULT 'below_threshold',
    status               TEXT NOT NULL DEFAULT 'pending',
    resolution           TEXT,
    resolved_at          TEXT,
    notes                TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_queue_job ON bulk_review_queue(job_id, status);

CREATE TABLE IF NOT EXISTS scene_keyframes (
    id                TEXT PRIMARY KEY,
    history_id        TEXT NOT NULL,
    scene_index       INTEGER NOT NULL,
    start_seconds     REAL NOT NULL,
    end_seconds       REAL NOT NULL,
    midpoint_seconds  REAL NOT NULL,
    keyframe_path     TEXT,
    description       TEXT,
    description_error TEXT,
    provider          TEXT,
    FOREIGN KEY(history_id) REFERENCES conversion_history(id)
);
CREATE INDEX IF NOT EXISTS idx_keyframes_history ON scene_keyframes(history_id, scene_index);

-- Phase 9: File version history
CREATE TABLE IF NOT EXISTS file_versions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bulk_file_id        TEXT NOT NULL,
    version_number      INTEGER NOT NULL,
    recorded_at         DATETIME NOT NULL DEFAULT (datetime('now')),
    change_type         TEXT NOT NULL,
    path_at_version     TEXT NOT NULL,
    mtime_at_version    REAL,
    size_at_version     INTEGER,
    content_hash        TEXT,
    md_content_hash     TEXT,
    diff_summary        TEXT,
    diff_patch          TEXT,
    diff_truncated      INTEGER NOT NULL DEFAULT 0,
    scan_run_id         TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_versions_bulk_file_id ON file_versions(bulk_file_id);
CREATE INDEX IF NOT EXISTS idx_file_versions_recorded_at ON file_versions(recorded_at);

-- Phase 9: Scan run tracking
CREATE TABLE IF NOT EXISTS scan_runs (
    id              TEXT PRIMARY KEY,
    started_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    finished_at     DATETIME,
    status          TEXT NOT NULL DEFAULT 'running',
    files_scanned   INTEGER DEFAULT 0,
    files_new       INTEGER DEFAULT 0,
    files_modified  INTEGER DEFAULT 0,
    files_moved     INTEGER DEFAULT 0,
    files_deleted   INTEGER DEFAULT 0,
    files_restored  INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    error_log       TEXT
);

-- Phase 9: Database maintenance log
CREATE TABLE IF NOT EXISTS db_maintenance_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    operation   TEXT NOT NULL,
    result      TEXT NOT NULL,
    details     TEXT,
    duration_ms INTEGER
);

-- Phase 10: API keys for service accounts
CREATE TABLE IF NOT EXISTS api_keys (
    key_id      TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    last_used_at TEXT
);

-- v0.9.7: Resource monitoring — system metrics (collected every 60s)
CREATE TABLE IF NOT EXISTS system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    cpu_percent_total REAL NOT NULL,
    cpu_percent_system REAL NOT NULL,
    cpu_count INTEGER NOT NULL,
    mem_rss_bytes INTEGER NOT NULL,
    mem_rss_percent REAL NOT NULL,
    mem_system_total_bytes INTEGER NOT NULL,
    mem_system_used_percent REAL NOT NULL,
    io_read_bytes INTEGER,
    io_write_bytes INTEGER,
    thread_count INTEGER NOT NULL,
    active_bulk_jobs INTEGER NOT NULL DEFAULT 0,
    active_lifecycle_scan INTEGER NOT NULL DEFAULT 0,
    active_conversions INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_system_metrics_ts ON system_metrics(timestamp);

-- v0.9.7: Resource monitoring — disk metrics (collected every 6h)
CREATE TABLE IF NOT EXISTS disk_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    output_repo_bytes INTEGER NOT NULL DEFAULT 0,
    output_repo_files INTEGER NOT NULL DEFAULT 0,
    trash_bytes INTEGER NOT NULL DEFAULT 0,
    trash_files INTEGER NOT NULL DEFAULT 0,
    conversion_output_bytes INTEGER NOT NULL DEFAULT 0,
    conversion_output_files INTEGER NOT NULL DEFAULT 0,
    database_bytes INTEGER NOT NULL DEFAULT 0,
    logs_bytes INTEGER NOT NULL DEFAULT 0,
    meilisearch_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    volume_total_bytes INTEGER NOT NULL DEFAULT 0,
    volume_used_bytes INTEGER NOT NULL DEFAULT 0,
    volume_free_bytes INTEGER NOT NULL DEFAULT 0,
    volume_used_percent REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_disk_metrics_ts ON disk_metrics(timestamp);

-- v0.9.7: Activity event log
CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    metadata TEXT,
    duration_seconds REAL
);
CREATE INDEX IF NOT EXISTS idx_activity_events_ts ON activity_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_events_type ON activity_events(event_type);

-- v0.11.0: Auto-conversion historical metrics (hourly aggregates)
CREATE TABLE IF NOT EXISTS auto_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_bucket TEXT NOT NULL,
    day_of_week INTEGER NOT NULL,
    cpu_avg REAL NOT NULL,
    cpu_p95 REAL NOT NULL,
    memory_avg REAL NOT NULL,
    memory_peak REAL NOT NULL,
    active_conversions_avg REAL NOT NULL DEFAULT 0,
    files_converted INTEGER NOT NULL DEFAULT 0,
    conversion_throughput REAL NOT NULL DEFAULT 0,
    io_read_rate_avg REAL NOT NULL DEFAULT 0,
    io_write_rate_avg REAL NOT NULL DEFAULT 0,
    user_request_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_metrics_bucket
    ON auto_metrics(hour_bucket);
CREATE INDEX IF NOT EXISTS idx_auto_metrics_dow_hour
    ON auto_metrics(day_of_week, cast(strftime('%H', hour_bucket) as integer));

-- v0.11.0: Auto-conversion decision/execution audit log
CREATE TABLE IF NOT EXISTS auto_conversion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id TEXT,
    mode TEXT NOT NULL,
    was_override INTEGER NOT NULL DEFAULT 0,
    files_discovered INTEGER NOT NULL DEFAULT 0,
    files_queued INTEGER NOT NULL DEFAULT 0,
    batch_size_chosen INTEGER NOT NULL DEFAULT 0,
    workers_chosen INTEGER NOT NULL DEFAULT 0,
    cpu_at_decision REAL,
    memory_at_decision REAL,
    cpu_hist_avg REAL,
    reason TEXT,
    bulk_job_id TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_auto_runs_status
    ON auto_conversion_runs(status);
CREATE INDEX IF NOT EXISTS idx_auto_runs_started
    ON auto_conversion_runs(started_at);

-- v0.12.3: Archive member tracking (files inside compressed archives)
CREATE TABLE IF NOT EXISTS archive_members (
    id              TEXT PRIMARY KEY,
    bulk_file_id    TEXT NOT NULL REFERENCES bulk_files(id),
    member_path     TEXT NOT NULL,
    member_ext      TEXT NOT NULL,
    member_size     INTEGER,
    member_modified_at TEXT,
    member_hash     TEXT,
    is_directory    INTEGER NOT NULL DEFAULT 0,
    is_archive      INTEGER NOT NULL DEFAULT 0,
    nesting_depth   INTEGER NOT NULL DEFAULT 0,
    parent_member_id TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    output_path     TEXT,
    error_msg       TEXT,
    converted_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_archive_members_bulk_file ON archive_members(bulk_file_id);
CREATE INDEX IF NOT EXISTS idx_archive_members_hash ON archive_members(member_hash);
CREATE INDEX IF NOT EXISTS idx_archive_members_status ON archive_members(bulk_file_id, status);

-- v0.13.0: Transcript segments for media transcription
CREATE TABLE IF NOT EXISTS transcript_segments (
    id              TEXT PRIMARY KEY,
    history_id      TEXT NOT NULL,
    segment_index   INTEGER NOT NULL,
    start_seconds   REAL NOT NULL,
    end_seconds     REAL NOT NULL,
    text            TEXT NOT NULL,
    speaker         TEXT,
    confidence      REAL,
    FOREIGN KEY(history_id) REFERENCES conversion_history(id)
);
CREATE INDEX IF NOT EXISTS idx_segments_history
    ON transcript_segments(history_id, segment_index);

-- v0.16.0: File flagging & content moderation
CREATE TABLE IF NOT EXISTS file_flags (
    id                TEXT PRIMARY KEY,
    source_file_id    TEXT NOT NULL REFERENCES source_files(id),
    flagged_by_sub    TEXT NOT NULL,
    flagged_by_email  TEXT NOT NULL,
    reason            TEXT NOT NULL,
    note              TEXT,
    status            TEXT NOT NULL DEFAULT 'active',
    expires_at        DATETIME NOT NULL,
    created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
    resolved_at       DATETIME,
    resolved_by_email TEXT,
    resolution_note   TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_flags_source_status
    ON file_flags(source_file_id, status);
CREATE INDEX IF NOT EXISTS idx_file_flags_status_expires
    ON file_flags(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_file_flags_user
    ON file_flags(flagged_by_email);

CREATE TABLE IF NOT EXISTS blocklisted_files (
    id              TEXT PRIMARY KEY,
    content_hash    TEXT,
    source_path     TEXT,
    reason          TEXT,
    added_by_email  TEXT NOT NULL,
    flag_id         TEXT REFERENCES file_flags(id),
    created_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_blocklist_hash ON blocklisted_files(content_hash);
CREATE INDEX IF NOT EXISTS idx_blocklist_path ON blocklisted_files(source_path);

-- Schema migration tracking (v0.16.2)
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT,
    applied_at  DATETIME DEFAULT (datetime('now'))
);
"""

# ── Versioned schema migrations ──────────────────────────────────────────────
# Each tuple: (version, description, [SQL statements])
# ALTER TABLE on an existing column is harmless — caught and ignored.
_MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "OCR confidence columns on conversion_history", [
        "ALTER TABLE conversion_history ADD COLUMN ocr_confidence_mean REAL",
        "ALTER TABLE conversion_history ADD COLUMN ocr_confidence_min REAL",
        "ALTER TABLE conversion_history ADD COLUMN ocr_page_count INTEGER",
        "ALTER TABLE conversion_history ADD COLUMN ocr_pages_below_threshold INTEGER",
    ]),
    (2, "OCR columns on bulk_files", [
        "ALTER TABLE bulk_files ADD COLUMN ocr_confidence_mean REAL",
        "ALTER TABLE bulk_files ADD COLUMN ocr_skipped_reason TEXT",
    ]),
    (3, "Review queue count on bulk_jobs", [
        "ALTER TABLE bulk_jobs ADD COLUMN review_queue_count INTEGER DEFAULT 0",
    ]),
    (4, "Path safety columns on bulk_jobs", [
        "ALTER TABLE bulk_jobs ADD COLUMN path_too_long_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bulk_jobs ADD COLUMN collision_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bulk_jobs ADD COLUMN case_collision_count INTEGER NOT NULL DEFAULT 0",
    ]),
    (5, "LLM correction columns on ocr_flags", [
        "ALTER TABLE ocr_flags ADD COLUMN llm_corrected_text TEXT",
        "ALTER TABLE ocr_flags ADD COLUMN llm_correction_model TEXT",
    ]),
    (6, "MIME/category columns on bulk_files", [
        "ALTER TABLE bulk_files ADD COLUMN mime_type TEXT",
        "ALTER TABLE bulk_files ADD COLUMN file_category TEXT DEFAULT 'unknown'",
    ]),
    (7, "Visual enrichment columns on conversion_history", [
        "ALTER TABLE conversion_history ADD COLUMN vision_provider TEXT",
        "ALTER TABLE conversion_history ADD COLUMN vision_model TEXT",
        "ALTER TABLE conversion_history ADD COLUMN scene_count INTEGER",
        "ALTER TABLE conversion_history ADD COLUMN keyframe_count INTEGER",
        "ALTER TABLE conversion_history ADD COLUMN frame_desc_count INTEGER",
        "ALTER TABLE conversion_history ADD COLUMN enrichment_level INTEGER",
    ]),
    (8, "Lifecycle columns on bulk_files", [
        "ALTER TABLE bulk_files ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE bulk_files ADD COLUMN marked_for_deletion_at DATETIME",
        "ALTER TABLE bulk_files ADD COLUMN moved_to_trash_at DATETIME",
        "ALTER TABLE bulk_files ADD COLUMN purged_at DATETIME",
        "ALTER TABLE bulk_files ADD COLUMN previous_path TEXT",
    ]),
    (9, "Password handling columns", [
        "ALTER TABLE conversion_history ADD COLUMN protection_type TEXT DEFAULT 'none'",
        "ALTER TABLE conversion_history ADD COLUMN password_method TEXT",
        "ALTER TABLE conversion_history ADD COLUMN password_attempts INTEGER DEFAULT 0",
        "ALTER TABLE bulk_files ADD COLUMN protection_type TEXT DEFAULT 'none'",
        "ALTER TABLE bulk_files ADD COLUMN password_method TEXT",
        "ALTER TABLE bulk_files ADD COLUMN password_attempts INTEGER DEFAULT 0",
    ]),
    (10, "Auto-triggered flag on bulk_jobs", [
        "ALTER TABLE bulk_jobs ADD COLUMN auto_triggered INTEGER NOT NULL DEFAULT 0",
    ]),
    (11, "Archive tracking columns on bulk_files", [
        "ALTER TABLE bulk_files ADD COLUMN is_archive INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bulk_files ADD COLUMN archive_member_count INTEGER",
        "ALTER TABLE bulk_files ADD COLUMN archive_total_uncompressed INTEGER",
    ]),
    (12, "Progress tracking / ETA columns", [
        "ALTER TABLE scan_runs ADD COLUMN total_files_counted INTEGER",
        "ALTER TABLE scan_runs ADD COLUMN count_status TEXT NOT NULL DEFAULT 'counting'",
        "ALTER TABLE scan_runs ADD COLUMN eta_seconds REAL",
        "ALTER TABLE scan_runs ADD COLUMN files_per_second REAL",
        "ALTER TABLE scan_runs ADD COLUMN eta_updated_at TEXT",
        "ALTER TABLE bulk_jobs ADD COLUMN eta_seconds REAL",
        "ALTER TABLE bulk_jobs ADD COLUMN files_per_second REAL",
        "ALTER TABLE bulk_jobs ADD COLUMN eta_updated_at TEXT",
        "ALTER TABLE conversion_history ADD COLUMN eta_seconds REAL",
    ]),
    (13, "Media transcription columns on conversion_history", [
        "ALTER TABLE conversion_history ADD COLUMN media_duration_seconds REAL",
        "ALTER TABLE conversion_history ADD COLUMN media_engine TEXT",
        "ALTER TABLE conversion_history ADD COLUMN media_whisper_model TEXT",
        "ALTER TABLE conversion_history ADD COLUMN media_language TEXT",
        "ALTER TABLE conversion_history ADD COLUMN media_word_count INTEGER",
        "ALTER TABLE conversion_history ADD COLUMN media_speaker_count INTEGER",
        "ALTER TABLE conversion_history ADD COLUMN media_caption_path TEXT",
        "ALTER TABLE conversion_history ADD COLUMN media_vtt_path TEXT",
    ]),
    (14, "Media columns on bulk_files", [
        "ALTER TABLE bulk_files ADD COLUMN is_media INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bulk_files ADD COLUMN media_engine TEXT",
    ]),
    (15, "Transcription counters on bulk_jobs", [
        "ALTER TABLE bulk_jobs ADD COLUMN transcribed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bulk_jobs ADD COLUMN transcript_failed INTEGER NOT NULL DEFAULT 0",
    ]),
    (16, "Source files FK on bulk_files", [
        "ALTER TABLE bulk_files ADD COLUMN source_file_id TEXT REFERENCES source_files(id)",
    ]),
    (17, "Add cancellation_reason to bulk_jobs", [
        "ALTER TABLE bulk_jobs ADD COLUMN cancellation_reason TEXT",
    ]),
    (18, "Add skip_reason to bulk_files", [
        "ALTER TABLE bulk_files ADD COLUMN skip_reason TEXT",
    ]),
    (19, "Image analysis queue", [
        """CREATE TABLE IF NOT EXISTS analysis_queue (
            id             TEXT PRIMARY KEY,
            source_path    TEXT NOT NULL,
            file_category  TEXT NOT NULL DEFAULT 'image',
            job_id         TEXT,
            scan_run_id    TEXT,
            enqueued_at    TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending',
            batch_id       TEXT,
            batched_at     TEXT,
            analyzed_at    TEXT,
            description    TEXT,
            extracted_text TEXT,
            provider_id    TEXT,
            model          TEXT,
            error          TEXT,
            content_hash   TEXT,
            retry_count    INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_analysis_queue_status ON analysis_queue(status)",
        "CREATE INDEX IF NOT EXISTS idx_analysis_queue_source_path ON analysis_queue(source_path)",
    ]),
    # Migration 20: normalize bulk_files to one row per physical file.
    # Deduplicates existing rows (keep best status), then recreates the table
    # with UNIQUE(source_path) instead of UNIQUE(job_id, source_path).
    # ignore_errors=False: every step must succeed or the migration aborts.
    (20, "Normalize bulk_files to UNIQUE(source_path)", [
        # Part 1: keep the single best row per source_path
        """DELETE FROM bulk_files
           WHERE id NOT IN (
               SELECT id FROM bulk_files bf1
               WHERE id = (
                   SELECT id FROM bulk_files bf2
                   WHERE bf2.source_path = bf1.source_path
                   ORDER BY
                       CASE status
                           WHEN 'converted'    THEN 1
                           WHEN 'skipped'      THEN 2
                           WHEN 'failed'       THEN 3
                           WHEN 'unrecognized' THEN 4
                           ELSE 5
                       END,
                       COALESCE(converted_at, indexed_at, '') DESC
                   LIMIT 1
               )
           )""",
        # Part 2a: rename old table
        "ALTER TABLE bulk_files RENAME TO bulk_files_old",
        # Part 2b: create new table with UNIQUE(source_path)
        """CREATE TABLE bulk_files (
            id                          TEXT PRIMARY KEY,
            job_id                      TEXT NOT NULL REFERENCES bulk_jobs(id),
            source_path                 TEXT NOT NULL,
            output_path                 TEXT,
            file_ext                    TEXT NOT NULL,
            file_size_bytes             INTEGER,
            source_mtime                REAL,
            stored_mtime                REAL,
            content_hash                TEXT,
            status                      TEXT NOT NULL DEFAULT 'pending',
            error_msg                   TEXT,
            converted_at                TEXT,
            indexed_at                  TEXT,
            ocr_confidence_mean         REAL,
            ocr_skipped_reason          TEXT,
            mime_type                   TEXT,
            file_category               TEXT DEFAULT 'unknown',
            lifecycle_status            TEXT NOT NULL DEFAULT 'active',
            marked_for_deletion_at      DATETIME,
            moved_to_trash_at           DATETIME,
            purged_at                   DATETIME,
            previous_path               TEXT,
            protection_type             TEXT DEFAULT 'none',
            password_method             TEXT,
            password_attempts           INTEGER DEFAULT 0,
            is_archive                  INTEGER NOT NULL DEFAULT 0,
            archive_member_count        INTEGER,
            archive_total_uncompressed  INTEGER,
            is_media                    INTEGER NOT NULL DEFAULT 0,
            media_engine                TEXT,
            source_file_id              TEXT REFERENCES source_files(id),
            skip_reason                 TEXT,
            UNIQUE(source_path)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_bulk_files_job_status  ON bulk_files(job_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_bulk_files_source_path ON bulk_files(source_path)",
        "CREATE INDEX IF NOT EXISTS idx_bulk_files_status      ON bulk_files(status)",
        # Part 2c: copy surviving rows using explicit column names (order-independent)
        """INSERT INTO bulk_files (
               id, job_id, source_path, output_path, file_ext, file_size_bytes,
               source_mtime, stored_mtime, content_hash, status, error_msg,
               converted_at, indexed_at, ocr_confidence_mean, ocr_skipped_reason,
               mime_type, file_category, lifecycle_status, marked_for_deletion_at,
               moved_to_trash_at, purged_at, previous_path, protection_type,
               password_method, password_attempts, is_archive, archive_member_count,
               archive_total_uncompressed, is_media, media_engine, source_file_id,
               skip_reason
           )
           SELECT
               id, job_id, source_path, output_path, file_ext, file_size_bytes,
               source_mtime, stored_mtime, content_hash, status, error_msg,
               converted_at, indexed_at, ocr_confidence_mean, ocr_skipped_reason,
               mime_type, file_category, lifecycle_status, marked_for_deletion_at,
               moved_to_trash_at, purged_at, previous_path, protection_type,
               password_method, password_attempts, is_archive, archive_member_count,
               archive_total_uncompressed, is_media, media_engine, source_file_id,
               skip_reason
           FROM bulk_files_old""",
        # Part 2d: drop old table
        "DROP TABLE bulk_files_old",
    ], False),  # ignore_errors=False — every step must succeed
]


# ── Schema init helpers ───────────────────────────────────────────────────────
async def _add_column_if_missing(
    conn: aiosqlite.Connection, table: str, column: str, coltype: str
) -> None:
    """Add a column to a table if it doesn't already exist."""
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    cols = [row[1] for row in rows]
    if column not in cols:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


async def _run_migrations(conn: aiosqlite.Connection) -> int:
    """Apply any pending schema migrations. Returns count of newly applied."""
    async with conn.execute("SELECT version FROM schema_migrations") as cur:
        applied = {row[0] for row in await cur.fetchall()}

    newly_applied = 0
    for entry in _MIGRATIONS:
        version, description, statements = entry[0], entry[1], entry[2]
        ignore_errors = entry[3] if len(entry) > 3 else True
        if version in applied:
            continue
        for sql in statements:
            try:
                await conn.execute(sql)
            except Exception:
                if not ignore_errors:
                    raise
                # Column already exists — safe to ignore for ALTER TABLE migrations
        await conn.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (version, description),
        )
        newly_applied += 1

    if newly_applied:
        await conn.commit()
        log.info("db.migrations_applied", count=newly_applied)
    return newly_applied


async def _migrate_bulk_files_to_source_files(conn: aiosqlite.Connection) -> int:
    """One-time migration: populate source_files from distinct bulk_files rows.

    Idempotent — skips if source_files already has data.
    Returns count of migrated files, or 0 if skipped.
    """
    async with conn.execute("SELECT COUNT(*) AS cnt FROM source_files") as cur:
        row = await cur.fetchone()
        if row and row[0] > 0:
            return 0

    async with conn.execute("SELECT COUNT(*) AS cnt FROM bulk_files") as cur:
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return 0

    async with conn.execute(
        """SELECT bf.*
           FROM bulk_files bf
           INNER JOIN (
               SELECT source_path, MAX(ROWID) AS max_rowid
               FROM bulk_files
               GROUP BY source_path
           ) latest ON bf.source_path = latest.source_path AND bf.ROWID = latest.max_rowid"""
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return 0

    count = 0
    for r in rows:
        source_file_id = uuid.uuid4().hex
        await conn.execute(
            """INSERT INTO source_files
               (id, source_path, file_ext, file_size_bytes, source_mtime, stored_mtime,
                content_hash, output_path, mime_type, file_category, lifecycle_status,
                marked_for_deletion_at, moved_to_trash_at, purged_at, previous_path,
                protection_type, password_method, password_attempts,
                is_archive, archive_member_count, archive_total_uncompressed,
                is_media, media_engine, ocr_confidence_mean, ocr_skipped_reason,
                last_seen_job_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_file_id,
                r["source_path"],
                r["file_ext"],
                r["file_size_bytes"],
                r["source_mtime"],
                r["stored_mtime"],
                r["content_hash"],
                r["output_path"],
                r["mime_type"] if "mime_type" in r.keys() else None,
                r["file_category"] if "file_category" in r.keys() else None,
                r["lifecycle_status"] if "lifecycle_status" in r.keys() else "active",
                r["marked_for_deletion_at"] if "marked_for_deletion_at" in r.keys() else None,
                r["moved_to_trash_at"] if "moved_to_trash_at" in r.keys() else None,
                r["purged_at"] if "purged_at" in r.keys() else None,
                r["previous_path"] if "previous_path" in r.keys() else None,
                r["protection_type"] if "protection_type" in r.keys() else "none",
                r["password_method"] if "password_method" in r.keys() else None,
                r["password_attempts"] if "password_attempts" in r.keys() else 0,
                r["is_archive"] if "is_archive" in r.keys() else 0,
                r["archive_member_count"] if "archive_member_count" in r.keys() else None,
                r["archive_total_uncompressed"] if "archive_total_uncompressed" in r.keys() else None,
                r["is_media"] if "is_media" in r.keys() else 0,
                r["media_engine"] if "media_engine" in r.keys() else None,
                r["ocr_confidence_mean"] if "ocr_confidence_mean" in r.keys() else None,
                r["ocr_skipped_reason"] if "ocr_skipped_reason" in r.keys() else None,
                r["job_id"],
            ),
        )
        await conn.execute(
            "UPDATE bulk_files SET source_file_id=? WHERE source_path=?",
            (source_file_id, r["source_path"]),
        )
        count += 1

    await conn.commit()
    return count


async def init_db() -> None:
    """Create tables and insert default preferences (idempotent)."""
    from core.db.preferences import _init_preferences

    async with get_db() as conn:
        await conn.executescript(_SCHEMA_SQL)
        await conn.commit()
        await _run_migrations(conn)
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA wal_autocheckpoint = 1000")
        await conn.execute("PRAGMA foreign_keys = ON")
        await _init_preferences(conn)
        migrated = await _migrate_bulk_files_to_source_files(conn)
        if migrated:
            log.info("db.source_files_migration", migrated_count=migrated)


async def cleanup_orphaned_jobs() -> None:
    """Clean up jobs stuck in active states from a previous container run."""
    async with get_db() as conn:
        cursor = await conn.execute(
            """UPDATE bulk_jobs SET status='cancelled', completed_at=datetime('now'),
               cancellation_reason='Cancelled: container restarted while job was active'
               WHERE status IN ('scanning', 'running', 'pending')"""
        )
        cancelled_jobs = cursor.rowcount

        cursor = await conn.execute(
            """UPDATE scan_runs SET status='interrupted', finished_at=datetime('now')
               WHERE status='running' AND finished_at IS NULL"""
        )
        interrupted_scans = cursor.rowcount

        await conn.commit()

    if cancelled_jobs or interrupted_scans:
        log.warning("startup.orphan_cleanup",
                     cancelled_jobs=cancelled_jobs,
                     interrupted_scans=interrupted_scans)
    else:
        log.info("startup.orphan_cleanup", msg="No orphaned jobs found")
