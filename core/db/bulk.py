"""
Bulk job, bulk file, and source file helpers.
"""

import uuid
from typing import Any

from core.db.connection import (
    db_fetch_all,
    db_fetch_one,
    get_db,
    now_iso,
)


# ── Bulk job helpers ─────────────────────────────────────────────────────────

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
                now_iso(),
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


# ── Source file helpers ──────────────────────────────────────────────────────

async def upsert_source_file(
    source_path: str,
    file_ext: str,
    file_size_bytes: int | None = None,
    source_mtime: float | None = None,
    job_id: str | None = None,
    **extra_fields,
) -> str:
    """Insert or update a source_files record by source_path (UNIQUE key).

    Uses INSERT ... ON CONFLICT DO UPDATE for single-statement upsert.
    Returns the source_file_id.
    """
    new_id = uuid.uuid4().hex

    # -- Build INSERT columns (used for new rows) --
    insert_cols: dict[str, Any] = {
        "id": new_id,
        "source_path": source_path,
        "file_ext": file_ext,
        "file_size_bytes": file_size_bytes,
        "source_mtime": source_mtime,
        "first_seen_job_id": job_id,
        "last_seen_job_id": job_id,
    }
    insert_cols.update(extra_fields)
    col_names = ", ".join(insert_cols.keys())
    placeholders = ", ".join(["?"] * len(insert_cols))

    # -- Build ON CONFLICT update (used for existing rows) --
    update_parts: dict[str, Any] = {"updated_at": now_iso()}
    if file_size_bytes is not None:
        update_parts["file_size_bytes"] = file_size_bytes
    if source_mtime is not None:
        update_parts["source_mtime"] = source_mtime
    if job_id is not None:
        update_parts["last_seen_job_id"] = job_id
    update_parts.update(extra_fields)
    update_sets = ", ".join(f"{k}=?" for k in update_parts)

    values = list(insert_cols.values()) + list(update_parts.values())

    async with get_db() as conn:
        await conn.execute(
            f"INSERT INTO source_files ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(source_path) DO UPDATE SET {update_sets}",
            values,
        )
        await conn.commit()
        # Retrieve actual id (new_id for inserts, existing id for conflicts)
        async with conn.execute(
            "SELECT id FROM source_files WHERE source_path=?", (source_path,),
        ) as cur:
            row = await cur.fetchone()
            return row["id"]


# ── Bulk file helpers ────────────────────────────────────────────────────────

async def upsert_bulk_file(
    job_id: str,
    source_path: str,
    file_ext: str,
    file_size_bytes: int,
    source_mtime: float,
) -> str:
    """Insert or update a bulk_files record. Returns file_id.

    Also upserts the corresponding source_files row and links via source_file_id.
    """
    source_file_id = await upsert_source_file(
        source_path=source_path,
        file_ext=file_ext,
        file_size_bytes=file_size_bytes,
        source_mtime=source_mtime,
        job_id=job_id,
    )

    file_id = uuid.uuid4().hex

    async with get_db() as conn:
        # Atomic upsert: INSERT or update on conflict to avoid race conditions
        # between SELECT and INSERT that caused UNIQUE constraint errors.
        await conn.execute(
            """INSERT INTO bulk_files
               (id, job_id, source_path, file_ext, file_size_bytes,
                source_mtime, status, source_file_id)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id, source_path) DO UPDATE SET
                file_ext = excluded.file_ext,
                file_size_bytes = excluded.file_size_bytes,
                source_file_id = excluded.source_file_id,
                status = CASE
                    WHEN bulk_files.stored_mtime IS NOT NULL
                         AND bulk_files.stored_mtime = excluded.source_mtime
                    THEN 'skipped'
                    ELSE 'pending'
                END,
                skip_reason = CASE
                    WHEN bulk_files.stored_mtime IS NOT NULL
                         AND bulk_files.stored_mtime = excluded.source_mtime
                    THEN 'Unchanged since last scan'
                    ELSE NULL
                END,
                source_mtime = excluded.source_mtime""",
            (file_id, job_id, source_path, file_ext, file_size_bytes,
             source_mtime, "pending", source_file_id),
        )

        # Retrieve actual id (generated for inserts, existing for conflicts)
        async with conn.execute(
            "SELECT id FROM bulk_files WHERE job_id=? AND source_path=?",
            (job_id, source_path),
        ) as cur:
            row = await cur.fetchone()
            file_id = row["id"]

        await conn.commit()
    return file_id


async def upsert_bulk_files_batch(
    job_id: str,
    files: list[tuple[str, str, int, float]],
) -> int:
    """Batch-upsert source_files + bulk_files in a single transaction.

    Each tuple in *files* is (source_path, file_ext, file_size_bytes, source_mtime).
    Returns the number of files written.  On error, falls back to per-file
    upserts so a single bad row doesn't lose the whole batch.
    """
    if not files:
        return 0

    ts = now_iso()

    try:
        async with get_db() as conn:
            for source_path, file_ext, file_size_bytes, source_mtime in files:
                sf_id = uuid.uuid4().hex

                # -- source_files upsert --
                insert_cols = {
                    "id": sf_id,
                    "source_path": source_path,
                    "file_ext": file_ext,
                    "file_size_bytes": file_size_bytes,
                    "source_mtime": source_mtime,
                    "first_seen_job_id": job_id,
                    "last_seen_job_id": job_id,
                }
                col_names = ", ".join(insert_cols.keys())
                placeholders = ", ".join(["?"] * len(insert_cols))
                update_parts = {
                    "updated_at": ts,
                    "file_size_bytes": file_size_bytes,
                    "source_mtime": source_mtime,
                    "last_seen_job_id": job_id,
                }
                update_sets = ", ".join(f"{k}=?" for k in update_parts)
                values = list(insert_cols.values()) + list(update_parts.values())

                await conn.execute(
                    f"INSERT INTO source_files ({col_names}) VALUES ({placeholders}) "
                    f"ON CONFLICT(source_path) DO UPDATE SET {update_sets}",
                    values,
                )

                # Retrieve actual source_file id
                async with conn.execute(
                    "SELECT id FROM source_files WHERE source_path=?",
                    (source_path,),
                ) as cur:
                    row = await cur.fetchone()
                    source_file_id = row["id"]

                # -- bulk_files upsert --
                bf_id = uuid.uuid4().hex
                await conn.execute(
                    """INSERT INTO bulk_files
                       (id, job_id, source_path, file_ext, file_size_bytes,
                        source_mtime, status, source_file_id)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(job_id, source_path) DO UPDATE SET
                        file_ext = excluded.file_ext,
                        file_size_bytes = excluded.file_size_bytes,
                        source_file_id = excluded.source_file_id,
                        status = CASE
                            WHEN bulk_files.stored_mtime IS NOT NULL
                                 AND bulk_files.stored_mtime = excluded.source_mtime
                            THEN 'skipped'
                            ELSE 'pending'
                        END,
                        skip_reason = CASE
                            WHEN bulk_files.stored_mtime IS NOT NULL
                                 AND bulk_files.stored_mtime = excluded.source_mtime
                            THEN 'Unchanged since last scan'
                            ELSE NULL
                        END,
                        source_mtime = excluded.source_mtime""",
                    (bf_id, job_id, source_path, file_ext, file_size_bytes,
                     source_mtime, "pending", source_file_id),
                )

            await conn.commit()
        return len(files)

    except Exception:
        # Fallback: per-file upserts so one bad row doesn't lose the batch
        import structlog
        log = structlog.get_logger(__name__)
        log.warning("batch_upsert_fallback", job_id=job_id, batch_size=len(files))
        count = 0
        for source_path, file_ext, file_size_bytes, source_mtime in files:
            try:
                await upsert_bulk_file(
                    job_id=job_id,
                    source_path=source_path,
                    file_ext=file_ext,
                    file_size_bytes=file_size_bytes,
                    source_mtime=source_mtime,
                )
                count += 1
            except Exception:
                log.warning("batch_upsert_file_error", source_path=source_path)
        return count


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


async def get_pending_files_global(
    status: str = "pending",
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return pending/failed bulk_files across all jobs with total count."""
    base_where = "WHERE bf.status = ?"
    params: list[Any] = [status]
    if search:
        base_where += " AND bf.source_path LIKE ?"
        params.append(f"%{search}%")

    count_sql = f"SELECT COUNT(*) as cnt FROM bulk_files bf {base_where}"
    count_row = await db_fetch_one(count_sql, tuple(params))
    total = count_row["cnt"] if count_row else 0

    data_sql = f"""SELECT bf.*, bj.started_at as job_started_at, bj.status as job_status
                   FROM bulk_files bf
                   LEFT JOIN bulk_jobs bj ON bf.job_id = bj.id
                   {base_where}
                   ORDER BY bf.source_path
                   LIMIT ? OFFSET ?"""
    data_params = params + [limit, offset]
    rows = await db_fetch_all(data_sql, tuple(data_params))
    return rows, total


async def get_pipeline_files(
    statuses: list[str],
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "source_path",
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Return files matching one or more pipeline status categories.

    Valid statuses: scanned, pending, failed, unrecognized,
                    pending_analysis, batched, analysis_failed.
    ('indexed' is handled separately via Meilisearch in the route.)

    Returns (rows, total_count).
    """
    ALLOWED_SORTS = {"source_path", "file_ext", "file_size_bytes", "status"}
    if sort not in ALLOWED_SORTS:
        sort = "source_path"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    sub_queries: list[str] = []
    sub_params: list[Any] = []

    for s in statuses:
        if s == "scanned":
            q = ("SELECT sf.id, sf.source_path, sf.file_ext, sf.file_size_bytes, "
                 "sf.source_mtime, 'scanned' AS status, NULL AS error_msg, "
                 "NULL AS skip_reason, NULL AS converted_at, "
                 "sf.last_seen_job_id AS job_id, sf.content_hash "
                 "FROM source_files sf WHERE sf.lifecycle_status = 'active'")
            if search:
                q += " AND sf.source_path LIKE ?"
                sub_params.append(f"%{search}%")
            sub_queries.append(q)

        elif s in ("pending", "failed", "unrecognized"):
            q = ("SELECT bf.id, bf.source_path, bf.file_ext, bf.file_size_bytes, "
                 "bf.source_mtime, bf.status, bf.error_msg, bf.skip_reason, "
                 "bf.converted_at, bf.job_id, sf.content_hash "
                 "FROM bulk_files bf "
                 "LEFT JOIN source_files sf ON bf.source_file_id = sf.id "
                 "WHERE bf.status = ?")
            sub_params.append(s)
            if search:
                q += " AND bf.source_path LIKE ?"
                sub_params.append(f"%{search}%")
            sub_queries.append(q)

        elif s in ("pending_analysis", "batched", "analysis_failed"):
            aq_status = {
                "pending_analysis": "pending",
                "batched": "batched",
                "analysis_failed": "failed",
            }[s]
            q = ("SELECT aq.id, aq.source_path, "
                 "NULL AS file_ext, NULL AS file_size_bytes, "
                 "NULL AS source_mtime, "
                 f"'{s}' AS status, aq.error AS error_msg, "
                 "NULL AS skip_reason, aq.analyzed_at AS converted_at, "
                 "aq.job_id, aq.content_hash "
                 "FROM analysis_queue aq WHERE aq.status = ?")
            sub_params.append(aq_status)
            if search:
                q += " AND aq.source_path LIKE ?"
                sub_params.append(f"%{search}%")
            sub_queries.append(q)

    if not sub_queries:
        return [], 0

    union_sql = " UNION ALL ".join(sub_queries)

    # Count
    count_sql = f"SELECT COUNT(*) AS cnt FROM ({union_sql})"
    count_row = await db_fetch_one(count_sql, tuple(sub_params))
    total = count_row["cnt"] if count_row else 0

    # Data — wrap in subquery so ORDER BY isn't ambiguous across UNION
    data_sql = f"SELECT * FROM ({union_sql}) ORDER BY {sort} {sort_dir} LIMIT ? OFFSET ?"
    data_params = list(sub_params) + [limit, offset]
    rows = await db_fetch_all(data_sql, tuple(data_params))

    return rows, total


async def load_dir_mtimes() -> dict[str, float]:
    """Load all cached directory mtimes into a dict for fast lookup."""
    rows = await db_fetch_all("SELECT dir_path, dir_mtime FROM scan_dir_mtimes")
    return {row["dir_path"]: row["dir_mtime"] for row in rows}


async def save_dir_mtimes_batch(
    dir_mtimes: dict[str, float],
    scan_run_id: str,
) -> None:
    """Persist directory mtimes in a single transaction."""
    if not dir_mtimes:
        return
    ts = now_iso()
    async with get_db() as conn:
        await conn.execute("DELETE FROM scan_dir_mtimes")
        for dir_path, mtime in dir_mtimes.items():
            await conn.execute(
                "INSERT INTO scan_dir_mtimes (dir_path, dir_mtime, scan_run_id, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (dir_path, mtime, scan_run_id, ts),
            )
        await conn.commit()


async def get_incremental_scan_count() -> int:
    """Return the number of incremental scans since the last full walk."""
    row = await db_fetch_one(
        "SELECT value FROM preferences WHERE key = 'scan_incremental_count'"
    )
    if row:
        try:
            return int(row["value"])
        except (ValueError, TypeError):
            pass
    return 0


async def increment_scan_count() -> int:
    """Increment and return the incremental scan counter."""
    current = await get_incremental_scan_count()
    new_count = current + 1
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            ("scan_incremental_count", str(new_count), str(new_count)),
        )
        await conn.commit()
    return new_count


async def reset_scan_count() -> None:
    """Reset the incremental scan counter to 0 (after a full walk)."""
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            ("scan_incremental_count", "0", "0"),
        )
        await conn.commit()


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
