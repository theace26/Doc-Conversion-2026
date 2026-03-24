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
from contextlib import asynccontextmanager
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
async def init_db() -> None:
    """Create tables and insert default preferences (idempotent)."""
    async with get_db() as conn:
        await conn.executescript(_SCHEMA_SQL)
        await conn.commit()
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
