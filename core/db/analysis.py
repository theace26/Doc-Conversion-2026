"""
DB helpers for the analysis_queue table.

Status lifecycle: pending -> batched -> completed | failed
Retry logic: failed rows with retry_count < 3 reset to pending on next claim cycle.
"""

import uuid
from typing import Any

from core.db.connection import db_fetch_one, db_fetch_all, get_db, now_iso

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif"}
_VECTOR_IMAGE_EXTENSIONS = {".eps"}


def is_image_extension(ext: str) -> bool:
    """Return True if ext (with or without leading dot) is a raster image format."""
    return ("." + ext.lstrip(".")).lower() in _IMAGE_EXTENSIONS


def is_vector_image_extension(ext: str) -> bool:
    """Return True if ext is a vector/layered format needing rasterization for vision."""
    return ("." + ext.lstrip(".")).lower() in _VECTOR_IMAGE_EXTENSIONS


async def enqueue_for_analysis(
    source_path: str,
    content_hash: str | None = None,
    job_id: str | None = None,
    scan_run_id: str | None = None,
    file_category: str = "image",
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
            (entry_id, source_path, file_category, job_id, scan_run_id,
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
            """SELECT id, source_path, content_hash, file_category FROM analysis_queue
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
                           model = ?,
                           tokens_used = ?
                       WHERE id = ?""",
                    (
                        now,
                        r.get("description", ""),
                        r.get("extracted_text", ""),
                        r.get("provider_id"),
                        r.get("model"),
                        r.get("tokens_used"),
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


async def get_analysis_token_summary() -> dict[str, Any]:
    """Return aggregate token usage across all completed analysis rows."""
    row = await db_fetch_one(
        """SELECT
               COUNT(*) AS total_analyzed,
               COALESCE(SUM(tokens_used), 0) AS total_tokens,
               COALESCE(AVG(tokens_used), 0) AS avg_tokens_per_file
           FROM analysis_queue
           WHERE status = 'completed' AND tokens_used IS NOT NULL"""
    )
    by_model = await db_fetch_all(
        """SELECT model, provider_id,
               COUNT(*) AS file_count,
               COALESCE(SUM(tokens_used), 0) AS total_tokens
           FROM analysis_queue
           WHERE status = 'completed' AND tokens_used IS NOT NULL
           GROUP BY model, provider_id"""
    )
    return {
        "total_analyzed": row["total_analyzed"] if row else 0,
        "total_tokens": row["total_tokens"] if row else 0,
        "avg_tokens_per_file": round(row["avg_tokens_per_file"], 1) if row else 0,
        "by_model": [dict(r) for r in by_model],
    }


async def get_analysis_result(source_path: str) -> dict[str, Any] | None:
    """Return completed analysis row for a given source_path, or None."""
    return await db_fetch_one(
        "SELECT * FROM analysis_queue WHERE source_path = ? AND status = 'completed'",
        (source_path,),
    )


async def get_batches() -> list[dict[str, Any]]:
    """
    List all analysis batches grouped by batch_id.

    Batches where ALL rows are 'excluded' are hidden.
    Status derivation (first match wins):
      any 'failed'    -> 'failed'
      any 'batched'   -> 'batched'
      all 'completed' -> 'completed'
      otherwise       -> 'mixed'
    """
    rows = await db_fetch_all(
        """SELECT aq.batch_id, aq.status,
                  aq.batched_at,
                  COALESCE(sf.file_size_bytes, 0) AS file_size_bytes
           FROM analysis_queue aq
           LEFT JOIN source_files sf ON sf.source_path = aq.source_path
           WHERE aq.batch_id IS NOT NULL"""
    )

    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        bid = r["batch_id"]
        g = groups.setdefault(bid, {
            "batch_id": bid,
            "statuses": [],
            "file_count": 0,
            "total_size_bytes": 0,
            "batched_ats": [],
        })
        g["statuses"].append(r["status"])
        g["file_count"] += 1
        g["total_size_bytes"] += r["file_size_bytes"] or 0
        if r["batched_at"]:
            g["batched_ats"].append(r["batched_at"])

    result = []
    for bid, g in groups.items():
        statuses = g["statuses"]
        # Hide batches where ALL rows are excluded
        if all(s == "excluded" for s in statuses):
            continue
        # Derive status (ignore excluded rows for derivation decisions
        # except as part of the "not-all-completed" fallback)
        non_excluded = [s for s in statuses if s != "excluded"]
        if any(s == "failed" for s in non_excluded):
            derived = "failed"
        elif any(s == "batched" for s in non_excluded):
            derived = "batched"
        elif non_excluded and all(s == "completed" for s in non_excluded):
            derived = "completed"
        else:
            derived = "mixed"

        batched_ats = g["batched_ats"]
        result.append({
            "batch_id": bid,
            "file_count": g["file_count"],
            "total_size_bytes": g["total_size_bytes"],
            "status": derived,
            "earliest_batched_at": min(batched_ats) if batched_ats else None,
            "latest_batched_at": max(batched_ats) if batched_ats else None,
        })
    return result


async def get_batch_files(batch_id: str) -> list[dict[str, Any]]:
    """Return files in a batch joined with source_files metadata."""
    rows = await db_fetch_all(
        """SELECT aq.id, aq.source_path, aq.status, aq.enqueued_at, aq.batched_at,
                  sf.id AS source_file_id,
                  sf.file_size_bytes, sf.source_mtime
           FROM analysis_queue aq
           LEFT JOIN source_files sf ON sf.source_path = aq.source_path
           WHERE aq.batch_id = ?
           ORDER BY aq.enqueued_at ASC""",
        (batch_id,),
    )
    return [dict(r) for r in rows]


async def exclude_files(file_ids: list[str]) -> int:
    """Mark the given analysis_queue ids as status='excluded'. Return rows updated."""
    if not file_ids:
        return 0
    placeholders = ",".join("?" * len(file_ids))
    async with get_db() as conn:
        cur = await conn.execute(
            f"UPDATE analysis_queue SET status = 'excluded' WHERE id IN ({placeholders})",
            list(file_ids),
        )
        await conn.commit()
        return cur.rowcount or 0


async def cancel_all_batched() -> int:
    """
    Reset all rows with status='batched' back to status='pending',
    clearing batch_id and batched_at. Returns count reset.
    """
    async with get_db() as conn:
        cur = await conn.execute(
            """UPDATE analysis_queue
               SET status = 'pending', batch_id = NULL, batched_at = NULL
               WHERE status = 'batched'"""
        )
        await conn.commit()
        return cur.rowcount or 0
