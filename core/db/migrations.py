"""One-time database migrations gated by preference flags."""

import structlog
from core.db.connection import db_execute, db_fetch_one, db_fetch_all
from core.db.preferences import get_preference, set_preference

log = structlog.get_logger(__name__)


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
    """Mark jobs stuck in 'running' with stale heartbeat as 'interrupted'."""
    stale = await db_fetch_all("""
        SELECT id FROM bulk_jobs
        WHERE status = 'running'
          AND (last_heartbeat IS NULL OR last_heartbeat < datetime('now', '-30 minutes'))
    """)
    for row in stale:
        await db_execute(
            "UPDATE bulk_jobs SET status = 'interrupted' WHERE id = ?",
            (row["id"],),
        )
        log.warning("migration.stale_job_interrupted", job_id=row["id"])
    if stale:
        log.info("migration.stale_jobs_cleaned", count=len(stale))
