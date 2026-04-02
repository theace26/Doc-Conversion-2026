"""
DB helpers for the analysis_queue table.

Status lifecycle: pending -> batched -> completed | failed
Retry logic: failed rows with retry_count < 3 reset to pending on next claim cycle.
"""

import uuid
from typing import Any

from core.db.connection import db_fetch_one, db_fetch_all, get_db, now_iso

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".eps"}


def is_image_extension(ext: str) -> bool:
    """Return True if ext (with or without leading dot) is a supported image format."""
    return ("." + ext.lstrip(".")).lower() in _IMAGE_EXTENSIONS


async def enqueue_for_analysis(
    source_path: str,
    content_hash: str | None = None,
    job_id: str | None = None,
    scan_run_id: str | None = None,
) -> str | None:
    """
    Enqueue an image file for LLM analysis. Returns entry id or None if skipped.

    Skip conditions:
    - status=completed with same content_hash
    - status=failed with retry_count >= 3 and same content_hash
    If status=pending/batched, returns existing id (no duplicate).
    If content changed (different hash), re-queues unconditionally.
    """
    existing = await db_fetch_one(
        "SELECT id, status, content_hash, retry_count FROM analysis_queue WHERE source_path = ?",
        (source_path,),
    )

    if existing:
        status = existing["status"]
        existing_hash = existing["content_hash"]
        retry_count = existing["retry_count"] or 0

        if status == "completed":
            if not content_hash or existing_hash == content_hash:
                return None
        elif status in ("pending", "batched"):
            return existing["id"]
        elif status == "failed" and retry_count >= 3:
            if not content_hash or existing_hash == content_hash:
                return None

    entry_id = existing["id"] if existing else uuid.uuid4().hex
    now = now_iso()

    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO analysis_queue
               (id, source_path, file_category, job_id, scan_run_id, enqueued_at,
                status, content_hash, retry_count)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status = 'pending',
                 content_hash = excluded.content_hash,
                 job_id = excluded.job_id,
                 scan_run_id = excluded.scan_run_id,
                 enqueued_at = excluded.enqueued_at,
                 batch_id = NULL,
                 batched_at = NULL,
                 analyzed_at = NULL,
                 description = NULL,
                 extracted_text = NULL,
                 error = NULL,
                 retry_count = 0""",
            (entry_id, source_path, "image", job_id, scan_run_id,
             now, "pending", content_hash, 0),
        )
        await conn.commit()
    return entry_id


async def claim_pending_batch(batch_size: int = 10) -> list[dict[str, Any]]:
    """
    Atomically claim up to batch_size pending rows, marking them 'batched'.
    Returns claimed rows, each with batch_id populated.
    """
    batch_id = uuid.uuid4().hex
    now = now_iso()

    async with get_db() as conn:
        async with conn.execute(
            """SELECT id, source_path, content_hash FROM analysis_queue
               WHERE status = 'pending'
               ORDER BY enqueued_at ASC
               LIMIT ?""",
            (batch_size,),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

        if not rows:
            return []

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        await conn.execute(
            f"""UPDATE analysis_queue
                SET status = 'batched', batch_id = ?, batched_at = ?
                WHERE id IN ({placeholders})""",
            [batch_id, now] + ids,
        )
        await conn.commit()

    for row in rows:
        row["batch_id"] = batch_id
    return rows


async def write_batch_results(results: list[dict[str, Any]]) -> None:
    """
    Write analysis results back to analysis_queue.

    Each result dict must have 'id' and either:
    - 'error': str  -> failure: increment retry_count, reset to pending if < 3
    - 'description', 'extracted_text', 'provider_id', 'model'  -> success
    """
    now = now_iso()
    async with get_db() as conn:
        for r in results:
            if r.get("error"):
                await conn.execute(
                    """UPDATE analysis_queue
                       SET status = CASE WHEN retry_count + 1 < 3 THEN 'pending' ELSE 'failed' END,
                           retry_count = retry_count + 1,
                           error = ?,
                           batch_id = NULL,
                           batched_at = NULL
                       WHERE id = ?""",
                    (r["error"], r["id"]),
                )
            else:
                await conn.execute(
                    """UPDATE analysis_queue
                       SET status = 'completed',
                           analyzed_at = ?,
                           description = ?,
                           extracted_text = ?,
                           provider_id = ?,
                           model = ?
                       WHERE id = ?""",
                    (
                        now,
                        r.get("description", ""),
                        r.get("extracted_text", ""),
                        r.get("provider_id"),
                        r.get("model"),
                        r["id"],
                    ),
                )
        await conn.commit()


async def get_analysis_stats() -> dict[str, int]:
    """Return count per status in analysis_queue."""
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) AS cnt FROM analysis_queue GROUP BY status"
    )
    stats: dict[str, int] = {"pending": 0, "batched": 0, "completed": 0, "failed": 0}
    for row in rows:
        s = row["status"]
        if s in stats:
            stats[s] = row["cnt"]
    return stats


async def get_analysis_result(source_path: str) -> dict[str, Any] | None:
    """Return completed analysis row for a given source_path, or None."""
    return await db_fetch_one(
        "SELECT * FROM analysis_queue WHERE source_path = ? AND status = 'completed'",
        (source_path,),
    )
