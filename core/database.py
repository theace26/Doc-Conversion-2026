"""
SQLite connection management, schema initialization, and query helpers.

Connection settings:
  - WAL journal mode (concurrent reads + writes)
  - busy_timeout = 5000ms
  - row_factory = aiosqlite.Row for dict-like access

DB path: DB_PATH env var (default: data/markflow.db inside the container,
         falls back to markflow.db in the project root for local dev).
"""

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

# ── Path resolution ───────────────────────────────────────────────────────────
_DEFAULT_DB = os.getenv("DB_PATH", "markflow.db")
DB_PATH = Path(_DEFAULT_DB)

# ── Default preferences ───────────────────────────────────────────────────────
DEFAULT_PREFERENCES: dict[str, str] = {
    "last_save_directory": "",
    "last_source_directory": "",
    "ocr_confidence_threshold": "80",
    "default_direction": "to_md",
    "max_upload_size_mb": "100",
    "max_batch_size_mb": "500",
    "retention_days": "30",
    "max_concurrent_conversions": "3",
    "pdf_engine": "pymupdf",
    "pdf_export_engine": "weasyprint",
    "unattended_default": "false",
    "conversion_engine": "native",
    "llm_ocr_correction": "false",
    "llm_summarize": "false",
    "llm_heading_inference": "false",
    "max_output_path_length": "240",
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
    "scanner_business_hours_end": "18:00",
    "lifecycle_grace_period_hours": "36",
    "lifecycle_trash_retention_days": "60",
    "worker_count": "4",
    "cpu_affinity_cores": "[]",
    "process_priority": "normal",
    "log_level": "normal",
}

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
"""


# ── Connection context manager ────────────────────────────────────────────────
@asynccontextmanager
async def get_db():
    """Async context manager yielding a configured aiosqlite connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA foreign_keys=ON")
        yield conn


# ── Schema init ───────────────────────────────────────────────────────────────
async def _add_column_if_missing(
    conn: aiosqlite.Connection, table: str, column: str, coltype: str
) -> None:
    """Add a column to a table if it doesn't already exist."""
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    cols = [row[1] for row in rows]
    if column not in cols:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


async def init_db() -> None:
    """Create tables and insert default preferences (idempotent)."""
    async with get_db() as conn:
        await conn.executescript(_SCHEMA_SQL)
        await conn.commit()
        # Migrate: add OCR confidence columns to conversion_history
        await _add_column_if_missing(conn, "conversion_history", "ocr_confidence_mean", "REAL")
        await _add_column_if_missing(conn, "conversion_history", "ocr_confidence_min", "REAL")
        await _add_column_if_missing(conn, "conversion_history", "ocr_page_count", "INTEGER")
        await _add_column_if_missing(conn, "conversion_history", "ocr_pages_below_threshold", "INTEGER")
        # Migrate: add OCR columns to bulk_files
        await _add_column_if_missing(conn, "bulk_files", "ocr_confidence_mean", "REAL")
        await _add_column_if_missing(conn, "bulk_files", "ocr_skipped_reason", "TEXT")
        # Migrate: add review_queue_count to bulk_jobs
        await _add_column_if_missing(conn, "bulk_jobs", "review_queue_count", "INTEGER DEFAULT 0")
        # Migrate: add path safety columns to bulk_jobs
        await _add_column_if_missing(conn, "bulk_jobs", "path_too_long_count", "INTEGER NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "bulk_jobs", "collision_count", "INTEGER NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "bulk_jobs", "case_collision_count", "INTEGER NOT NULL DEFAULT 0")
        # Migrate: add LLM correction columns to ocr_flags
        await _add_column_if_missing(conn, "ocr_flags", "llm_corrected_text", "TEXT")
        await _add_column_if_missing(conn, "ocr_flags", "llm_correction_model", "TEXT")
        # Migrate: add MIME/category columns to bulk_files
        await _add_column_if_missing(conn, "bulk_files", "mime_type", "TEXT")
        await _add_column_if_missing(conn, "bulk_files", "file_category", "TEXT DEFAULT 'unknown'")
        # Migrate: add visual enrichment columns to conversion_history
        await _add_column_if_missing(conn, "conversion_history", "vision_provider", "TEXT")
        await _add_column_if_missing(conn, "conversion_history", "vision_model", "TEXT")
        await _add_column_if_missing(conn, "conversion_history", "scene_count", "INTEGER")
        await _add_column_if_missing(conn, "conversion_history", "keyframe_count", "INTEGER")
        await _add_column_if_missing(conn, "conversion_history", "frame_desc_count", "INTEGER")
        await _add_column_if_missing(conn, "conversion_history", "enrichment_level", "INTEGER")
        # Phase 9: lifecycle columns on bulk_files
        await _add_column_if_missing(conn, "bulk_files", "lifecycle_status", "TEXT NOT NULL DEFAULT 'active'")
        await _add_column_if_missing(conn, "bulk_files", "marked_for_deletion_at", "DATETIME")
        await _add_column_if_missing(conn, "bulk_files", "moved_to_trash_at", "DATETIME")
        await _add_column_if_missing(conn, "bulk_files", "purged_at", "DATETIME")
        await _add_column_if_missing(conn, "bulk_files", "previous_path", "TEXT")
        await conn.commit()
        # Phase 9: WAL mode and pragmas
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA wal_autocheckpoint = 1000")
        await conn.execute("PRAGMA foreign_keys = ON")
        await _init_preferences(conn)


async def _init_preferences(conn: aiosqlite.Connection) -> None:
    """Insert default preferences that don't already exist."""
    for key, value in DEFAULT_PREFERENCES.items():
        await conn.execute(
            "INSERT OR IGNORE INTO user_preferences (key, value) VALUES (?, ?)",
            (key, value),
        )
    await conn.commit()


# ── Generic query helpers ─────────────────────────────────────────────────────
async def db_fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    """Execute a SELECT and return the first row as a dict (or None)."""
    async with get_db() as conn:
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def db_fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a SELECT and return all rows as a list of dicts."""
    async with get_db() as conn:
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def db_execute(sql: str, params: tuple = ()) -> int:
    """Execute an INSERT/UPDATE/DELETE. Returns lastrowid."""
    async with get_db() as conn:
        async with conn.execute(sql, params) as cursor:
            await conn.commit()
            return cursor.lastrowid


# ── Preference helpers ────────────────────────────────────────────────────────
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


# ── History helpers ───────────────────────────────────────────────────────────
async def record_conversion(record: dict[str, Any]) -> int:
    """Insert a conversion_history record. Returns the new row id."""
    warnings = record.get("warnings")
    if isinstance(warnings, list):
        warnings = json.dumps(warnings)

    return await db_execute(
        """INSERT INTO conversion_history
           (batch_id, source_filename, source_format, output_filename, output_format,
            direction, source_path, output_path, file_size_bytes, ocr_applied,
            ocr_flags_total, ocr_flags_resolved, status, error_message, duration_ms, warnings)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record.get("batch_id", ""),
            record.get("source_filename", ""),
            record.get("source_format", ""),
            record.get("output_filename", ""),
            record.get("output_format", ""),
            record.get("direction", "to_md"),
            record.get("source_path"),
            record.get("output_path"),
            record.get("file_size_bytes"),
            record.get("ocr_applied", False),
            record.get("ocr_flags_total", 0),
            record.get("ocr_flags_resolved", 0),
            record.get("status", "success"),
            record.get("error_message"),
            record.get("duration_ms"),
            warnings,
        ),
    )


# ── Batch state helpers ───────────────────────────────────────────────────────
async def upsert_batch_state(batch_id: str, **kwargs) -> None:
    """Insert or update a batch_state row."""
    async with get_db() as conn:
        async with conn.execute(
            "SELECT batch_id FROM batch_state WHERE batch_id = ?", (batch_id,)
        ) as cur:
            row = await cur.fetchone()

        if row is None:
            fields = ["batch_id"] + list(kwargs.keys())
            placeholders = ", ".join(["?"] * len(fields))
            values = [batch_id] + list(kwargs.values())
            await conn.execute(
                f"INSERT INTO batch_state ({', '.join(fields)}) VALUES ({placeholders})",
                values,
            )
        else:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            values = list(kwargs.values()) + [batch_id]
            await conn.execute(
                f"UPDATE batch_state SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                values,
            )
        await conn.commit()


async def get_batch_state(batch_id: str) -> dict[str, Any] | None:
    return await db_fetch_one(
        "SELECT * FROM batch_state WHERE batch_id = ?", (batch_id,)
    )


# ── OCR flag helpers ──────────────────────────────────────────────────────────

async def insert_ocr_flag(flag: Any) -> None:
    """Persist an OCRFlag dataclass to the ocr_flags table."""
    bbox_json = json.dumps(list(flag.region_bbox))
    async with get_db() as conn:
        await conn.execute(
            """INSERT OR IGNORE INTO ocr_flags
               (flag_id, batch_id, file_name, page_num, region_bbox,
                ocr_text, confidence, corrected_text, status, image_path)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                flag.flag_id,
                flag.batch_id,
                flag.file_name,
                flag.page_num,
                bbox_json,
                flag.ocr_text,
                flag.confidence,
                flag.corrected_text,
                flag.status.value if hasattr(flag.status, "value") else flag.status,
                flag.image_path,
            ),
        )
        await conn.commit()


async def get_flags_for_batch(
    batch_id: str, status: str | None = None
) -> list[dict[str, Any]]:
    """Return OCR flags for a batch, optionally filtered by status."""
    if status:
        rows = await db_fetch_all(
            "SELECT * FROM ocr_flags WHERE batch_id=? AND status=? ORDER BY page_num, flag_id",
            (batch_id, status),
        )
    else:
        rows = await db_fetch_all(
            "SELECT * FROM ocr_flags WHERE batch_id=? ORDER BY page_num, flag_id",
            (batch_id,),
        )
    # Deserialise region_bbox from JSON
    for row in rows:
        if isinstance(row.get("region_bbox"), str):
            row["region_bbox"] = json.loads(row["region_bbox"])
    return rows


async def resolve_flag(
    flag_id: str, status: str, corrected_text: str | None = None
) -> None:
    """Update a single OCR flag's status (and optional corrected text)."""
    async with get_db() as conn:
        await conn.execute(
            """UPDATE ocr_flags
               SET status=?, corrected_text=?, resolved_at=CURRENT_TIMESTAMP
               WHERE flag_id=?""",
            (status, corrected_text, flag_id),
        )
        await conn.commit()


async def resolve_all_pending(batch_id: str) -> int:
    """Accept all pending flags for a batch. Returns the number of rows updated."""
    async with get_db() as conn:
        async with conn.execute(
            """UPDATE ocr_flags
               SET status='accepted', resolved_at=CURRENT_TIMESTAMP
               WHERE batch_id=? AND status='pending'""",
            (batch_id,),
        ) as cur:
            count = cur.rowcount
        await conn.commit()
    return count


async def get_flag_counts(batch_id: str) -> dict[str, int]:
    """Return {pending, accepted, edited, skipped, total} counts for a batch."""
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) AS cnt FROM ocr_flags WHERE batch_id=? GROUP BY status",
        (batch_id,),
    )
    counts = {"pending": 0, "accepted": 0, "edited": 0, "skipped": 0}
    for row in rows:
        counts[row["status"]] = row["cnt"]
    counts["total"] = sum(counts.values())
    return counts


# ── Bulk job helpers ─────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_bulk_job(
    source_path: str,
    output_path: str,
    worker_count: int = 4,
    include_adobe: bool = True,
    fidelity_tier: int = 2,
    ocr_mode: str = "auto",
) -> str:
    """Create a bulk_jobs record. Returns job_id (UUID)."""
    job_id = uuid.uuid4().hex
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO bulk_jobs
               (id, source_path, output_path, status, worker_count, include_adobe,
                fidelity_tier, ocr_mode, started_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                job_id, source_path, output_path, "pending",
                worker_count, int(include_adobe), fidelity_tier, ocr_mode,
                _now_iso(),
            ),
        )
        await conn.commit()
    return job_id


async def get_bulk_job(job_id: str) -> dict[str, Any] | None:
    return await db_fetch_one("SELECT * FROM bulk_jobs WHERE id = ?", (job_id,))


async def list_bulk_jobs(limit: int = 20) -> list[dict[str, Any]]:
    return await db_fetch_all(
        "SELECT * FROM bulk_jobs ORDER BY started_at DESC LIMIT ?", (limit,)
    )


async def update_bulk_job_status(job_id: str, status: str, **fields) -> None:
    """Update job status and any additional fields."""
    sets = ["status=?"]
    values: list[Any] = [status]
    for k, v in fields.items():
        sets.append(f"{k}=?")
        values.append(v)
    values.append(job_id)
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE bulk_jobs SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def increment_bulk_job_counter(job_id: str, counter: str, amount: int = 1) -> None:
    """Atomically increment a bulk_jobs counter (converted, skipped, failed, adobe_indexed)."""
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE bulk_jobs SET {counter} = {counter} + ? WHERE id = ?",
            (amount, job_id),
        )
        await conn.commit()


# ── Bulk file helpers ────────────────────────────────────────────────────────

async def upsert_bulk_file(
    job_id: str,
    source_path: str,
    file_ext: str,
    file_size_bytes: int,
    source_mtime: float,
) -> str:
    """Insert or update a bulk_files record. Returns file_id."""
    async with get_db() as conn:
        # Check if this file already exists for this job
        async with conn.execute(
            "SELECT id, stored_mtime FROM bulk_files WHERE job_id=? AND source_path=?",
            (job_id, source_path),
        ) as cur:
            row = await cur.fetchone()

        if row is not None:
            file_id = row["id"]
            stored_mtime = row["stored_mtime"]
            if stored_mtime is not None and stored_mtime == source_mtime:
                # Unchanged — mark as skipped
                await conn.execute(
                    "UPDATE bulk_files SET status='skipped', source_mtime=?, file_size_bytes=? WHERE id=?",
                    (source_mtime, file_size_bytes, file_id),
                )
            else:
                # Changed or never successfully converted — reset to pending
                await conn.execute(
                    "UPDATE bulk_files SET status='pending', source_mtime=?, file_size_bytes=? WHERE id=?",
                    (source_mtime, file_size_bytes, file_id),
                )
        else:
            file_id = uuid.uuid4().hex
            await conn.execute(
                """INSERT INTO bulk_files
                   (id, job_id, source_path, file_ext, file_size_bytes, source_mtime, status)
                   VALUES (?,?,?,?,?,?,?)""",
                (file_id, job_id, source_path, file_ext, file_size_bytes, source_mtime, "pending"),
            )

        await conn.commit()
    return file_id


async def get_bulk_files(
    job_id: str,
    status: str | None = None,
    file_ext: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return bulk_files for a job, optionally filtered."""
    sql = "SELECT * FROM bulk_files WHERE job_id=?"
    params: list[Any] = [job_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    if file_ext:
        sql += " AND file_ext=?"
        params.append(file_ext)
    sql += " ORDER BY source_path"
    if limit:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return await db_fetch_all(sql, tuple(params))


async def get_bulk_file_count(job_id: str, status: str | None = None) -> int:
    """Return count of bulk_files for a job, optionally filtered by status."""
    sql = "SELECT COUNT(*) as cnt FROM bulk_files WHERE job_id=?"
    params: list[Any] = [job_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    row = await db_fetch_one(sql, tuple(params))
    return row["cnt"] if row else 0


async def update_bulk_file(file_id: str, **fields) -> None:
    """Update any combination of bulk_files fields."""
    if not fields:
        return
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [file_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE bulk_files SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def get_unprocessed_bulk_files(job_id: str) -> list[dict[str, Any]]:
    """Return files that need processing: pending status, excluding permanently skipped."""
    return await db_fetch_all(
        """SELECT * FROM bulk_files WHERE job_id=? AND status='pending'
           AND (ocr_skipped_reason IS NULL OR ocr_skipped_reason != 'permanently_skipped')
           ORDER BY source_path""",
        (job_id,),
    )


# ── Adobe index helpers ──────────────────────────────────────────────────────

async def upsert_adobe_index(
    source_path: str,
    file_ext: str,
    file_size_bytes: int,
    metadata: dict | None,
    text_layers: list[str] | None,
) -> str:
    """Insert or update an adobe_index record. Returns entry id."""
    metadata_json = json.dumps(metadata) if metadata else None
    text_json = json.dumps(text_layers) if text_layers else None
    now = _now_iso()

    async with get_db() as conn:
        async with conn.execute(
            "SELECT id FROM adobe_index WHERE source_path=?", (source_path,)
        ) as cur:
            row = await cur.fetchone()

        if row is not None:
            entry_id = row["id"]
            await conn.execute(
                """UPDATE adobe_index SET file_ext=?, file_size_bytes=?,
                   metadata=?, text_layers=?, updated_at=?, meili_indexed=0
                   WHERE id=?""",
                (file_ext, file_size_bytes, metadata_json, text_json, now, entry_id),
            )
        else:
            entry_id = uuid.uuid4().hex
            await conn.execute(
                """INSERT INTO adobe_index
                   (id, source_path, file_ext, file_size_bytes, metadata, text_layers,
                    indexing_level, meili_indexed, indexed_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (entry_id, source_path, file_ext, file_size_bytes,
                 metadata_json, text_json, 2, 0, now, now),
            )

        await conn.commit()
    return entry_id


async def get_adobe_index_entry(source_path: str) -> dict[str, Any] | None:
    row = await db_fetch_one(
        "SELECT * FROM adobe_index WHERE source_path=?", (source_path,)
    )
    if row:
        if isinstance(row.get("metadata"), str):
            row["metadata"] = json.loads(row["metadata"])
        if isinstance(row.get("text_layers"), str):
            row["text_layers"] = json.loads(row["text_layers"])
    return row


async def get_unindexed_adobe_entries(limit: int = 100) -> list[dict[str, Any]]:
    """Return adobe_index entries not yet indexed in Meilisearch."""
    rows = await db_fetch_all(
        "SELECT * FROM adobe_index WHERE meili_indexed=0 LIMIT ?", (limit,)
    )
    for row in rows:
        if isinstance(row.get("metadata"), str):
            row["metadata"] = json.loads(row["metadata"])
        if isinstance(row.get("text_layers"), str):
            row["text_layers"] = json.loads(row["text_layers"])
    return rows


async def mark_adobe_meili_indexed(entry_id: str) -> None:
    """Mark an adobe_index entry as indexed in Meilisearch."""
    async with get_db() as conn:
        await conn.execute(
            "UPDATE adobe_index SET meili_indexed=1 WHERE id=?", (entry_id,)
        )
        await conn.commit()


# ── Location helpers ────────────────────────────────────────────────────────

async def create_location(
    name: str, path: str, type_: str, notes: str | None = None
) -> str:
    """Insert a new location. Returns id. Raises ValueError if name exists."""
    # Check for duplicate name
    existing = await db_fetch_one(
        "SELECT id FROM locations WHERE name = ?", (name,)
    )
    if existing:
        raise ValueError(f"Location name already exists: {name}")

    location_id = uuid.uuid4().hex
    now = _now_iso()
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO locations (id, name, path, type, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (location_id, name, path, type_, notes, now, now),
        )
        await conn.commit()
    return location_id


async def get_location(location_id: str) -> dict[str, Any] | None:
    """Return a single location by id."""
    return await db_fetch_one("SELECT * FROM locations WHERE id = ?", (location_id,))


async def list_locations(type_filter: str | None = None) -> list[dict[str, Any]]:
    """Return all locations, optionally filtered by type.

    'both' locations appear when filtering by 'source' or 'output'.
    """
    if type_filter and type_filter in ("source", "output"):
        return await db_fetch_all(
            "SELECT * FROM locations WHERE type = ? OR type = 'both' ORDER BY name",
            (type_filter,),
        )
    elif type_filter == "both":
        return await db_fetch_all(
            "SELECT * FROM locations WHERE type = 'both' ORDER BY name"
        )
    return await db_fetch_all("SELECT * FROM locations ORDER BY name")


async def update_location(location_id: str, **fields) -> None:
    """Update name, path, type, or notes. Raises ValueError if new name conflicts."""
    if not fields:
        return

    if "name" in fields:
        existing = await db_fetch_one(
            "SELECT id FROM locations WHERE name = ? AND id != ?",
            (fields["name"], location_id),
        )
        if existing:
            raise ValueError(f"Location name already exists: {fields['name']}")

    fields["updated_at"] = _now_iso()
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [location_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE locations SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def delete_location(location_id: str) -> None:
    """Delete a location by id."""
    async with get_db() as conn:
        await conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))
        await conn.commit()


# ── Bulk review queue helpers ───────────────────────────────────────────────

async def add_to_review_queue(
    job_id: str,
    bulk_file_id: str,
    source_path: str,
    file_ext: str,
    estimated_confidence: float | None,
    skip_reason: str = "below_threshold",
) -> str:
    """Insert into bulk_review_queue. Returns id."""
    entry_id = uuid.uuid4().hex
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO bulk_review_queue
               (id, job_id, bulk_file_id, source_path, file_ext,
                estimated_confidence, skip_reason, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (entry_id, job_id, bulk_file_id, source_path, file_ext,
             estimated_confidence, skip_reason, "pending"),
        )
        await conn.commit()
    return entry_id


async def get_review_queue(
    job_id: str, status: str | None = None, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """Return review queue entries for a job, optionally filtered by status."""
    sql = "SELECT * FROM bulk_review_queue WHERE job_id=?"
    params: list[Any] = [job_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY source_path LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return await db_fetch_all(sql, tuple(params))


async def get_review_queue_entry(entry_id: str) -> dict[str, Any] | None:
    """Return a single review queue entry by id."""
    return await db_fetch_one(
        "SELECT * FROM bulk_review_queue WHERE id = ?", (entry_id,)
    )


async def update_review_queue_entry(
    entry_id: str,
    status: str,
    resolution: str | None = None,
    notes: str | None = None,
    resolved_at: str | None = None,
) -> None:
    """Update a review queue entry's status and resolution."""
    async with get_db() as conn:
        await conn.execute(
            """UPDATE bulk_review_queue
               SET status=?, resolution=?, notes=?, resolved_at=?
               WHERE id=?""",
            (status, resolution, notes, resolved_at, entry_id),
        )
        await conn.commit()


async def get_review_queue_summary(job_id: str) -> dict[str, int]:
    """Returns {pending, converted, skipped_permanently, total} for a job."""
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) AS cnt FROM bulk_review_queue WHERE job_id=? GROUP BY status",
        (job_id,),
    )
    summary = {"pending": 0, "converted": 0, "skipped_permanently": 0, "converting": 0, "review_requested": 0}
    for row in rows:
        summary[row["status"]] = row["cnt"]
    summary["total"] = sum(summary.values())
    return summary


async def get_review_queue_count(job_id: str, status: str | None = None) -> int:
    """Return count of review queue entries for a job."""
    sql = "SELECT COUNT(*) as cnt FROM bulk_review_queue WHERE job_id=?"
    params: list[Any] = [job_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    row = await db_fetch_one(sql, tuple(params))
    return row["cnt"] if row else 0


async def get_ocr_gap_fill_candidates(job_id: str | None = None) -> list[dict[str, Any]]:
    """Return conversion_history records for PDFs converted without OCR stats.

    A PDF is a gap-fill candidate if:
      - source_format = 'pdf'
      - ocr_page_count IS NULL (OCR stats never recorded)
      - status = 'success'
    Optionally restrict to files from a specific bulk job (by batch_id prefix).
    """
    sql = """SELECT * FROM conversion_history
             WHERE source_format='pdf'
             AND ocr_page_count IS NULL
             AND status='success'"""
    params: list[Any] = []
    if job_id:
        sql += " AND batch_id LIKE ?"
        params.append(f"{job_id}%")
    sql += " ORDER BY created_at ASC"
    return await db_fetch_all(sql, tuple(params))


async def get_ocr_gap_fill_count(job_id: str | None = None) -> dict[str, Any]:
    """Return count and oldest conversion date for gap-fill candidates."""
    sql = """SELECT COUNT(*) as cnt, MIN(created_at) as oldest
             FROM conversion_history
             WHERE source_format='pdf'
             AND ocr_page_count IS NULL
             AND status='success'"""
    params: list[Any] = []
    if job_id:
        sql += " AND batch_id LIKE ?"
        params.append(f"{job_id}%")
    row = await db_fetch_one(sql, tuple(params))
    return {
        "count": row["cnt"] if row else 0,
        "oldest_conversion": row["oldest"] if row else None,
    }


async def update_bulk_file_confidence(file_id: str, ocr_confidence_mean: float) -> None:
    """Update OCR confidence for a bulk file."""
    await update_bulk_file(file_id, ocr_confidence_mean=ocr_confidence_mean)


# ── Path issue helpers ──────────────────────────────────────────────────────

async def record_path_issue(
    job_id: str,
    issue_type: str,
    source_path: str,
    output_path: str | None = None,
    collision_group: str | None = None,
    collision_peer: str | None = None,
    resolution: str | None = None,
    resolved_path: str | None = None,
) -> str:
    """Insert into bulk_path_issues. Returns id."""
    issue_id = uuid.uuid4().hex
    now = _now_iso()
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO bulk_path_issues
               (id, job_id, issue_type, source_path, output_path,
                collision_group, collision_peer, resolution, resolved_path, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (issue_id, job_id, issue_type, source_path, output_path,
             collision_group, collision_peer, resolution, resolved_path, now),
        )
        await conn.commit()
    return issue_id


async def get_path_issues(
    job_id: str, issue_type: str | None = None,
    limit: int = 200, offset: int = 0,
) -> list[dict[str, Any]]:
    """Return all path issues for a job, optionally filtered by type."""
    sql = "SELECT * FROM bulk_path_issues WHERE job_id=?"
    params: list[Any] = [job_id]
    if issue_type:
        sql += " AND issue_type=?"
        params.append(issue_type)
    sql += " ORDER BY issue_type, source_path LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return await db_fetch_all(sql, tuple(params))


async def get_path_issue_summary(job_id: str) -> dict[str, int]:
    """Returns {path_too_long, collision, case_collision, total}."""
    rows = await db_fetch_all(
        "SELECT issue_type, COUNT(*) AS cnt FROM bulk_path_issues WHERE job_id=? GROUP BY issue_type",
        (job_id,),
    )
    summary: dict[str, int] = {"path_too_long": 0, "collision": 0, "case_collision": 0}
    for row in rows:
        summary[row["issue_type"]] = row["cnt"]
    summary["total"] = sum(summary.values())
    return summary


async def get_path_issue_count(job_id: str) -> int:
    """Return total path issue count for a job."""
    row = await db_fetch_one(
        "SELECT COUNT(*) as cnt FROM bulk_path_issues WHERE job_id=?", (job_id,)
    )
    return row["cnt"] if row else 0


async def update_path_issue_resolution(
    issue_id: str, resolution: str, resolved_path: str | None = None
) -> None:
    async with get_db() as conn:
        await conn.execute(
            "UPDATE bulk_path_issues SET resolution=?, resolved_path=? WHERE id=?",
            (resolution, resolved_path, issue_id),
        )
        await conn.commit()


async def get_collision_group(job_id: str, output_path: str) -> list[dict[str, Any]]:
    """Return all path issues sharing the same collision_group."""
    return await db_fetch_all(
        "SELECT * FROM bulk_path_issues WHERE job_id=? AND collision_group=? ORDER BY source_path",
        (job_id, output_path),
    )


# ── LLM provider helpers ────────────────────────────────────────────────────

async def create_llm_provider(
    name: str,
    provider: str,
    model: str,
    api_key: str | None = None,
    api_base_url: str | None = None,
) -> str:
    """Create an LLM provider record. Encrypts api_key. Returns id."""
    from core.crypto import encrypt_value

    provider_id = uuid.uuid4().hex
    now = _now_iso()
    encrypted_key = encrypt_value(api_key) if api_key else None

    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO llm_providers
               (id, name, provider, model, api_key, api_base_url,
                is_active, is_verified, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (provider_id, name, provider, model, encrypted_key,
             api_base_url, 0, 0, now, now),
        )
        await conn.commit()
    return provider_id


async def get_llm_provider(provider_id: str) -> dict[str, Any] | None:
    """Return provider with api_key DECRYPTED."""
    row = await db_fetch_one(
        "SELECT * FROM llm_providers WHERE id = ?", (provider_id,)
    )
    if row and row.get("api_key"):
        from core.crypto import decrypt_value
        try:
            row["api_key"] = decrypt_value(row["api_key"])
        except Exception:
            row["api_key"] = None  # key unrecoverable
    return row


async def list_llm_providers() -> list[dict[str, Any]]:
    """Return providers with api_key MASKED."""
    from core.crypto import mask_api_key

    rows = await db_fetch_all(
        "SELECT * FROM llm_providers ORDER BY is_active DESC, name ASC"
    )
    for row in rows:
        row["api_key"] = mask_api_key(row.get("api_key"))
    return rows


async def update_llm_provider(provider_id: str, **fields) -> None:
    """Update provider fields. Encrypts api_key if present."""
    if not fields:
        return
    if "api_key" in fields and fields["api_key"]:
        from core.crypto import encrypt_value
        fields["api_key"] = encrypt_value(fields["api_key"])
    fields["updated_at"] = _now_iso()
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [provider_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE llm_providers SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def delete_llm_provider(provider_id: str) -> None:
    """Delete a provider by id."""
    async with get_db() as conn:
        await conn.execute("DELETE FROM llm_providers WHERE id = ?", (provider_id,))
        await conn.commit()


async def set_active_provider(provider_id: str) -> None:
    """Set one provider as active, deactivate all others."""
    async with get_db() as conn:
        await conn.execute("UPDATE llm_providers SET is_active=0")
        await conn.execute(
            "UPDATE llm_providers SET is_active=1, updated_at=? WHERE id=?",
            (_now_iso(), provider_id),
        )
        await conn.commit()


async def get_active_provider() -> dict[str, Any] | None:
    """Return the currently active provider with api_key DECRYPTED, or None."""
    row = await db_fetch_one(
        "SELECT * FROM llm_providers WHERE is_active=1"
    )
    if row and row.get("api_key"):
        from core.crypto import decrypt_value
        try:
            row["api_key"] = decrypt_value(row["api_key"])
        except Exception:
            row["api_key"] = None
    return row


async def update_history_ocr_stats(
    history_id: int,
    mean: float,
    min_conf: float,
    page_count: int,
    pages_below: int,
) -> None:
    """Update OCR stats on a conversion_history record."""
    async with get_db() as conn:
        await conn.execute(
            """UPDATE conversion_history
               SET ocr_confidence_mean=?, ocr_confidence_min=?,
                   ocr_page_count=?, ocr_pages_below_threshold=?
               WHERE id=?""",
            (mean, min_conf, page_count, pages_below, history_id),
        )
        await conn.commit()


async def update_history_vision_stats(
    history_id: int,
    vision_provider: str | None,
    vision_model: str | None,
    scene_count: int,
    keyframe_count: int,
    frame_desc_count: int,
    enrichment_level: int,
) -> None:
    """Update visual enrichment stats on a conversion_history record."""
    async with get_db() as conn:
        await conn.execute(
            """UPDATE conversion_history
               SET vision_provider=?, vision_model=?, scene_count=?,
                   keyframe_count=?, frame_desc_count=?, enrichment_level=?
               WHERE id=?""",
            (vision_provider, vision_model, scene_count,
             keyframe_count, frame_desc_count, enrichment_level, history_id),
        )
        await conn.commit()


async def record_scene_keyframes(history_id: str, scenes: list[dict]) -> None:
    """Bulk insert scene keyframe records."""
    async with get_db() as conn:
        for scene in scenes:
            scene_id = uuid.uuid4().hex
            await conn.execute(
                """INSERT INTO scene_keyframes
                   (id, history_id, scene_index, start_seconds, end_seconds,
                    midpoint_seconds, keyframe_path, description, description_error, provider)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    scene_id,
                    history_id,
                    scene.get("scene_index", 0),
                    scene.get("start_seconds", 0.0),
                    scene.get("end_seconds", 0.0),
                    scene.get("midpoint_seconds", 0.0),
                    scene.get("keyframe_path"),
                    scene.get("description"),
                    scene.get("description_error"),
                    scene.get("provider"),
                ),
            )
        await conn.commit()


async def get_scene_keyframes(history_id: str) -> list[dict[str, Any]]:
    """Return all scene records for a history entry, ordered by scene_index."""
    return await db_fetch_all(
        "SELECT * FROM scene_keyframes WHERE history_id=? ORDER BY scene_index",
        (history_id,),
    )


# ── Unrecognized file helpers ────────────────────────────────────────────

async def get_unrecognized_files(
    job_id: str | None = None,
    category: str | None = None,
    source_format: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    """Returns paginated unrecognized files with total count."""
    where = ["status='unrecognized'"]
    params: list[Any] = []
    if job_id:
        where.append("job_id=?")
        params.append(job_id)
    if category:
        where.append("file_category=?")
        params.append(category)
    if source_format:
        where.append("file_ext=?")
        params.append(source_format if source_format.startswith(".") else f".{source_format}")

    where_sql = " AND ".join(where)

    count_row = await db_fetch_one(
        f"SELECT COUNT(*) as cnt FROM bulk_files WHERE {where_sql}", tuple(params)
    )
    total = count_row["cnt"] if count_row else 0

    offset = (page - 1) * per_page
    rows = await db_fetch_all(
        f"SELECT * FROM bulk_files WHERE {where_sql} ORDER BY source_path LIMIT ? OFFSET ?",
        tuple(params) + (per_page, offset),
    )

    return {
        "files": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


# ── Phase 9: Lifecycle helpers ──────────────────────────────────────────────

async def get_bulk_file_by_path(source_path: str) -> dict[str, Any] | None:
    """Return a bulk_file by its source_path (across all jobs, latest first)."""
    return await db_fetch_one(
        "SELECT * FROM bulk_files WHERE source_path=? ORDER BY ROWID DESC LIMIT 1",
        (source_path,),
    )


async def get_bulk_file_by_content_hash(content_hash: str) -> dict[str, Any] | None:
    """Return a bulk_file by content_hash (most recent)."""
    return await db_fetch_one(
        "SELECT * FROM bulk_files WHERE content_hash=? ORDER BY ROWID DESC LIMIT 1",
        (content_hash,),
    )


async def get_bulk_files_by_lifecycle_status(
    status: str, job_id: str | None = None
) -> list[dict[str, Any]]:
    """Return bulk_files in the given lifecycle_status."""
    sql = "SELECT * FROM bulk_files WHERE lifecycle_status=?"
    params: list[Any] = [status]
    if job_id:
        sql += " AND job_id=?"
        params.append(job_id)
    sql += " ORDER BY source_path"
    return await db_fetch_all(sql, tuple(params))


async def get_bulk_files_pending_trash(grace_period_hours: int = 36) -> list[dict[str, Any]]:
    """Return files marked_for_deletion whose grace period has expired."""
    return await db_fetch_all(
        """SELECT * FROM bulk_files
           WHERE lifecycle_status='marked_for_deletion'
           AND marked_for_deletion_at IS NOT NULL
           AND datetime(marked_for_deletion_at, '+' || ? || ' hours') < datetime('now')""",
        (grace_period_hours,),
    )


async def get_bulk_files_pending_purge(trash_retention_days: int = 60) -> list[dict[str, Any]]:
    """Return files in_trash whose retention period has expired."""
    return await db_fetch_all(
        """SELECT * FROM bulk_files
           WHERE lifecycle_status='in_trash'
           AND moved_to_trash_at IS NOT NULL
           AND datetime(moved_to_trash_at, '+' || ? || ' days') < datetime('now')""",
        (trash_retention_days,),
    )


async def create_version_snapshot(bulk_file_id: str, version_data: dict) -> int:
    """Insert a file_versions record. Returns the new row id."""
    return await db_execute(
        """INSERT INTO file_versions
           (bulk_file_id, version_number, change_type, path_at_version,
            mtime_at_version, size_at_version, content_hash, md_content_hash,
            diff_summary, diff_patch, diff_truncated, scan_run_id, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            bulk_file_id,
            version_data.get("version_number", 1),
            version_data.get("change_type", "initial"),
            version_data.get("path_at_version", ""),
            version_data.get("mtime_at_version"),
            version_data.get("size_at_version"),
            version_data.get("content_hash"),
            version_data.get("md_content_hash"),
            version_data.get("diff_summary"),
            version_data.get("diff_patch"),
            version_data.get("diff_truncated", 0),
            version_data.get("scan_run_id"),
            version_data.get("notes"),
        ),
    )


async def get_version_history(bulk_file_id: str) -> list[dict[str, Any]]:
    """Return all versions for a file, newest first."""
    return await db_fetch_all(
        "SELECT * FROM file_versions WHERE bulk_file_id=? ORDER BY version_number DESC",
        (bulk_file_id,),
    )


async def get_version(bulk_file_id: str, version_number: int) -> dict[str, Any] | None:
    """Return a single version record."""
    return await db_fetch_one(
        "SELECT * FROM file_versions WHERE bulk_file_id=? AND version_number=?",
        (bulk_file_id, version_number),
    )


async def get_next_version_number(bulk_file_id: str) -> int:
    """Return the next version number for a file (max + 1, or 1 if none)."""
    row = await db_fetch_one(
        "SELECT MAX(version_number) as max_v FROM file_versions WHERE bulk_file_id=?",
        (bulk_file_id,),
    )
    return (row["max_v"] or 0) + 1 if row else 1


async def create_scan_run(run_id: str) -> None:
    """Create a scan_runs record with status='running'."""
    await db_execute(
        "INSERT INTO scan_runs (id, status) VALUES (?, 'running')",
        (run_id,),
    )


async def update_scan_run(run_id: str, updates: dict) -> None:
    """Update a scan_runs record."""
    if not updates:
        return
    sets = [f"{k}=?" for k in updates]
    values = list(updates.values()) + [run_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE scan_runs SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def get_scan_run(run_id: str) -> dict[str, Any] | None:
    return await db_fetch_one("SELECT * FROM scan_runs WHERE id=?", (run_id,))


async def get_latest_scan_run() -> dict[str, Any] | None:
    return await db_fetch_one(
        "SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 1"
    )


async def log_maintenance(
    operation: str, result: str, details: dict | None, duration_ms: int
) -> None:
    """Insert a db_maintenance_log record."""
    details_json = json.dumps(details) if details else None
    await db_execute(
        "INSERT INTO db_maintenance_log (operation, result, details, duration_ms) VALUES (?,?,?,?)",
        (operation, result, details_json, duration_ms),
    )


async def get_maintenance_log(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent maintenance log entries."""
    rows = await db_fetch_all(
        "SELECT * FROM db_maintenance_log ORDER BY run_at DESC LIMIT ?", (limit,)
    )
    for row in rows:
        if isinstance(row.get("details"), str):
            try:
                row["details"] = json.loads(row["details"])
            except (json.JSONDecodeError, TypeError):
                pass
    return rows


# ── API key helpers ──────────────────────────────────────────────────────

async def create_api_key(key_id: str, label: str, key_hash: str) -> str:
    """Insert an API key record. Returns key_id."""
    now = _now_iso()
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO api_keys (key_id, label, key_hash, is_active, created_at)
               VALUES (?,?,?,?,?)""",
            (key_id, label, key_hash, 1, now),
        )
        await conn.commit()
    return key_id


async def get_api_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    """Look up an API key by its hash."""
    return await db_fetch_one(
        "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
    )


async def revoke_api_key(key_id: str) -> bool:
    """Soft-revoke an API key. Returns True if found."""
    async with get_db() as conn:
        async with conn.execute(
            "UPDATE api_keys SET is_active=0 WHERE key_id=?", (key_id,)
        ) as cur:
            updated = cur.rowcount
        await conn.commit()
    return updated > 0


async def list_api_keys() -> list[dict[str, Any]]:
    """Return all API keys (id, label, dates, active status — never the hash)."""
    rows = await db_fetch_all(
        "SELECT key_id, label, is_active, created_at, last_used_at "
        "FROM api_keys ORDER BY created_at DESC"
    )
    return rows


async def touch_api_key(key_id: str) -> None:
    """Update last_used_at to now."""
    async with get_db() as conn:
        await conn.execute(
            "UPDATE api_keys SET last_used_at=? WHERE key_id=?",
            (_now_iso(), key_id),
        )
        await conn.commit()


async def get_unrecognized_stats(job_id: str | None = None) -> dict[str, Any]:
    """Returns summary statistics for unrecognized files."""
    where = "status='unrecognized'"
    params: list[Any] = []
    if job_id:
        where += " AND job_id=?"
        params.append(job_id)

    total_row = await db_fetch_one(
        f"SELECT COUNT(*) as cnt, COALESCE(SUM(file_size_bytes),0) as total_bytes FROM bulk_files WHERE {where}",
        tuple(params),
    )
    total = total_row["cnt"] if total_row else 0
    total_bytes = total_row["total_bytes"] if total_row else 0

    cat_rows = await db_fetch_all(
        f"SELECT file_category, COUNT(*) as cnt FROM bulk_files WHERE {where} GROUP BY file_category ORDER BY cnt DESC",
        tuple(params),
    )
    by_category = {r["file_category"]: r["cnt"] for r in cat_rows}

    fmt_rows = await db_fetch_all(
        f"SELECT file_ext, COUNT(*) as cnt FROM bulk_files WHERE {where} GROUP BY file_ext ORDER BY cnt DESC",
        tuple(params),
    )
    by_format = {r["file_ext"]: r["cnt"] for r in fmt_rows}

    job_rows = await db_fetch_all(
        f"SELECT DISTINCT job_id FROM bulk_files WHERE {where}",
        tuple(params),
    )
    job_ids = [r["job_id"] for r in job_rows]

    return {
        "total": total,
        "by_category": by_category,
        "by_format": by_format,
        "total_bytes": total_bytes,
        "job_ids": job_ids,
    }
