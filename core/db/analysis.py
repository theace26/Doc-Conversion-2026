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
                # v0.29.8: clear `error` and reset `retry_count` on success.
                # Previously a row that failed, retried, and eventually
                # succeeded would keep the old error text indefinitely,
                # which the batch-management UI faithfully displayed
                # alongside the (actually-successful) description +
                # extracted_text. This confused operators into thinking
                # successful analyses were failing.
                await conn.execute(
                    """UPDATE analysis_queue
                       SET status = 'completed',
                           analyzed_at = ?,
                           description = ?,
                           extracted_text = ?,
                           provider_id = ?,
                           model = ?,
                           tokens_used = ?,
                           error = NULL,
                           retry_count = 0
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


_VALID_STATUS_FILTERS = {"pending", "batched", "completed", "failed", "excluded"}


async def get_batches(status_filter: str | None = None) -> list[dict[str, Any]]:
    """
    List all analysis batches grouped by batch_id.

    Batches where ALL rows are 'excluded' are hidden.
    Status derivation (first match wins, computed from non-excluded rows):
      any 'failed'    -> 'failed'
      any 'batched'   -> 'batched'
      all 'completed' -> 'completed'
      otherwise       -> 'mixed'

    v0.29.4: optional `status_filter` restricts the set of rows that
    contribute to file_count / total_size_bytes / earliest_batched_at
    to rows matching that status. Batches with zero matching rows are
    omitted. The derived 'status' field is computed from all rows in
    the batch, not the filtered subset, so users still see the real
    shape of each batch.
    """
    if status_filter and status_filter not in _VALID_STATUS_FILTERS:
        raise ValueError(f"invalid status_filter: {status_filter}")

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
        # When filtering, only count rows matching the filter toward
        # file_count / total_size_bytes / batched_ats. The full status
        # list is still tracked for the derivation below.
        if status_filter is None or r["status"] == status_filter:
            g["file_count"] += 1
            g["total_size_bytes"] += r["file_size_bytes"] or 0
            if r["batched_at"]:
                g["batched_ats"].append(r["batched_at"])

    result = []
    for bid, g in groups.items():
        statuses = g["statuses"]
        # Hide batches where ALL rows are excluded (unless explicitly
        # filtering for 'excluded' — then the user wants to see them).
        if status_filter != "excluded" and all(s == "excluded" for s in statuses):
            continue
        # Skip batches with zero rows matching the filter.
        if status_filter is not None and g["file_count"] == 0:
            continue

        # Derive status from all non-excluded rows (independent of filter).
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


async def get_batch_files(
    batch_id: str,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return files in a batch joined with source_files metadata.

    v0.29.4: optional `status_filter` restricts results to rows with
    that status. None = all statuses (previous behaviour).
    """
    if status_filter and status_filter not in _VALID_STATUS_FILTERS:
        raise ValueError(f"invalid status_filter: {status_filter}")

    params: list[Any] = [batch_id]
    sql = (
        """SELECT aq.id, aq.source_path, aq.status, aq.enqueued_at, aq.batched_at,
                  sf.id AS source_file_id,
                  sf.file_size_bytes, sf.source_mtime
           FROM analysis_queue aq
           LEFT JOIN source_files sf ON sf.source_path = aq.source_path
           WHERE aq.batch_id = ?"""
    )
    if status_filter:
        sql += " AND aq.status = ?"
        params.append(status_filter)
    sql += " ORDER BY aq.enqueued_at ASC"

    rows = await db_fetch_all(sql, tuple(params))
    return [dict(r) for r in rows]


async def get_pending_files(
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return files with status='pending' and no batch_id, paginated.

    Pending rows haven't been assigned to a batch yet, so they are
    invisible to get_batches(). This helper surfaces them for the
    batch-management UI's status-filter drill-down (v0.29.4).

    Returns: {files: [...], total: int, limit: int, offset: int}
    """
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    total_row = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM analysis_queue "
        "WHERE status = 'pending' AND batch_id IS NULL"
    )
    total = total_row["cnt"] if total_row else 0

    rows = await db_fetch_all(
        """SELECT aq.id, aq.source_path, aq.status, aq.enqueued_at,
                  sf.id AS source_file_id,
                  sf.file_size_bytes, sf.source_mtime
           FROM analysis_queue aq
           LEFT JOIN source_files sf ON sf.source_path = aq.source_path
           WHERE aq.status = 'pending' AND aq.batch_id IS NULL
           ORDER BY aq.enqueued_at ASC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    return {
        "files": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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


# v0.31.0: bulk re-analyze.
# Cap above which the API endpoint refuses to act, to prevent an
# operator from torching their LLM quota on a single click.
BULK_REANALYZE_CAP = 10_000

_BULK_FILTER_FIELDS = {"analyzed_before_iso", "analyzed_after_iso",
                       "provider_id", "model", "status"}


async def find_rows_for_bulk_reanalyze(
    *,
    analyzed_before_iso: str | None = None,
    analyzed_after_iso: str | None = None,
    provider_id: str | None = None,
    model: str | None = None,
    status: str | None = "completed",
    limit: int = BULK_REANALYZE_CAP,
) -> list[dict[str, Any]]:
    """Return rows in `analysis_queue` matching the given filters,
    capturing the columns needed to delete and re-insert them
    (id, source_path, content_hash, job_id, scan_run_id, file_category).

    Defaults to status='completed' since that is the canonical
    re-analyze target. Pass status=None to ignore the status filter
    (e.g. to retry both failed and completed rows).
    """
    where: list[str] = []
    params: list[Any] = []
    if status is not None and status != "":
        if status not in _VALID_STATUS_FILTERS:
            raise ValueError(f"invalid status: {status}")
        where.append("status = ?")
        params.append(status)
    if analyzed_before_iso:
        where.append("analyzed_at IS NOT NULL AND analyzed_at < ?")
        params.append(analyzed_before_iso)
    if analyzed_after_iso:
        where.append("analyzed_at IS NOT NULL AND analyzed_at > ?")
        params.append(analyzed_after_iso)
    if provider_id:
        where.append("provider_id = ?")
        params.append(provider_id)
    if model:
        where.append("model = ?")
        params.append(model)
    if not where:
        # Refuse "match every row" — operator must specify at least one filter.
        raise ValueError("at least one filter is required for bulk re-analyze")

    where_sql = " AND ".join(where)
    sql = (
        "SELECT id, source_path, content_hash, job_id, scan_run_id, file_category "
        "FROM analysis_queue "
        f"WHERE {where_sql} "
        "ORDER BY enqueued_at ASC LIMIT ?"
    )
    params.append(limit + 1)  # fetch one extra so caller can detect "exceeds cap"
    rows = await db_fetch_all(sql, tuple(params))
    return [dict(r) for r in rows]


async def delete_rows_by_ids(row_ids: list[str]) -> int:
    """Delete the given analysis_queue rows by id. Returns rowcount."""
    if not row_ids:
        return 0
    placeholders = ",".join("?" * len(row_ids))
    async with get_db() as conn:
        cur = await conn.execute(
            f"DELETE FROM analysis_queue WHERE id IN ({placeholders})",
            list(row_ids),
        )
        await conn.commit()
        return cur.rowcount or 0


async def list_distinct_provider_models() -> dict[str, list[str]]:
    """Return distinct provider_id + model values seen across the queue.
    Used to populate the dropdowns on the bulk re-analyze modal."""
    rows = await db_fetch_all(
        "SELECT DISTINCT provider_id, model FROM analysis_queue "
        "WHERE provider_id IS NOT NULL OR model IS NOT NULL"
    )
    providers: set[str] = set()
    models: set[str] = set()
    for r in rows:
        if r["provider_id"]:
            providers.add(r["provider_id"])
        if r["model"]:
            models.add(r["model"])
    return {
        "providers": sorted(providers),
        "models": sorted(models),
    }
