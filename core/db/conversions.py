"""
Conversion history, batch state, OCR flags, review queue, and scene keyframes.
"""

import json
import uuid
from typing import Any

from core.db.connection import (
    _count_by_status,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    get_db,
)


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
            ocr_flags_total, ocr_flags_resolved, status, error_message, duration_ms, warnings,
            protection_type, password_method, password_attempts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            record.get("protection_type", "none"),
            record.get("password_method"),
            record.get("password_attempts", 0),
        ),
    )


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
    sql = "SELECT * FROM ocr_flags WHERE batch_id=?"
    params: list[Any] = [batch_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY page_num, flag_id"
    rows = await db_fetch_all(sql, tuple(params))
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
    return _count_by_status(rows, {"pending": 0, "accepted": 0, "edited": 0, "skipped": 0})


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
    return _count_by_status(rows, {"pending": 0, "converted": 0, "skipped_permanently": 0, "converting": 0, "review_requested": 0})


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
    """Return conversion_history records for PDFs converted without OCR stats."""
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
    from core.db.bulk import update_bulk_file
    await update_bulk_file(file_id, ocr_confidence_mean=ocr_confidence_mean)
