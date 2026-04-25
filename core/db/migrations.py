"""One-time database migrations gated by preference flags."""

import structlog
from core.db.connection import db_execute, db_fetch_one, db_fetch_all
from core.db.preferences import get_preference, set_preference

log = structlog.get_logger(__name__)


async def clear_stale_analysis_errors():
    """One-time cleanup of analysis_queue rows where status='completed'
    still carries an old `error` blob from a prior failed attempt
    (v0.29.8). The bug was in write_batch_results: the success branch
    never cleared `error`, so a row that failed, retried, and
    eventually succeeded kept the stale error string indefinitely.

    Gated by preference 'analysis_stale_errors_cleared_v0_29_8'.
    """
    done = await get_preference("analysis_stale_errors_cleared_v0_29_8")
    if done == "true":
        return

    row = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM analysis_queue "
        "WHERE status = 'completed' AND error IS NOT NULL"
    )
    before = row["cnt"] if row else 0

    if before > 0:
        log.info("migration.clear_stale_analysis_errors_starting", rows=before)
        await db_execute(
            "UPDATE analysis_queue "
            "SET error = NULL, retry_count = 0 "
            "WHERE status = 'completed' AND error IS NOT NULL"
        )
        log.info("migration.clear_stale_analysis_errors_complete", cleared=before)
    else:
        log.info("migration.clear_stale_analysis_errors_noop")

    await set_preference("analysis_stale_errors_cleared_v0_29_8", "true")


async def run_bulk_files_dedup():
    """One-time dedup of bulk_files: keep latest row per source_path.

    Gated by preference 'bulk_dedup_v0_23_done'. Expected to delete
    ~187,784 duplicate rows on first run.
    """
    done = await get_preference("bulk_dedup_v0_23_done")
    if done == "true":
        return

    log.info("migration.bulk_dedup_starting")

    row = await db_fetch_one("SELECT COUNT(*) as cnt FROM bulk_files")
    before = row["cnt"] if row else 0

    # Disable FK enforcement during dedup — deleted rows may be referenced
    # by other tables (e.g. bulk_job_files). The duplicates are stale data
    # that should never have existed; the FK references are also stale.
    await db_execute("PRAGMA foreign_keys = OFF")
    try:
        await db_execute("""
            DELETE FROM bulk_files
            WHERE rowid NOT IN (
                SELECT MAX(rowid) FROM bulk_files GROUP BY source_path
            )
        """)
    finally:
        await db_execute("PRAGMA foreign_keys = ON")

    row = await db_fetch_one("SELECT COUNT(*) as cnt FROM bulk_files")
    after = row["cnt"] if row else 0

    log.info("migration.bulk_dedup_complete",
             before=before, after=after, deleted=before - after)

    await set_preference("bulk_dedup_v0_23_done", "true")


async def add_heartbeat_column():
    """Add last_heartbeat column to bulk_jobs if missing."""
    try:
        await db_execute(
            "ALTER TABLE bulk_jobs ADD COLUMN last_heartbeat TEXT"
        )
        log.info("migration.heartbeat_column_added")
    except Exception:
        pass  # Column already exists


async def cleanup_stale_jobs():
    """Mark jobs stuck in 'running' OR 'scanning' with stale heartbeat
    as 'interrupted'. v0.30.3: 'scanning' added — without it, a
    container restart mid-scan would leave a zombie job displayed in
    the Active Jobs UI forever (no scanner running to update it,
    status never moves off 'scanning'). Also stamps `completed_at` so
    the Bulk Jobs page knows when it stopped."""
    stale = await db_fetch_all("""
        SELECT id, status FROM bulk_jobs
        WHERE status IN ('running', 'scanning')
          AND (last_heartbeat IS NULL OR last_heartbeat < datetime('now', '-30 minutes'))
    """)
    for row in stale:
        await db_execute(
            "UPDATE bulk_jobs "
            "SET status = 'interrupted', "
            "    completed_at = datetime('now'), "
            "    error_msg = COALESCE(error_msg, 'Container restart during ' || ? || '; auto-cleared on next startup') "
            "WHERE id = ?",
            (row["status"], row["id"]),
        )
        log.warning("migration.stale_job_interrupted",
                    job_id=row["id"], prior_status=row["status"])
    if stale:
        log.info("migration.stale_jobs_cleaned", count=len(stale))
