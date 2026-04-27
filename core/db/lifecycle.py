"""
Lifecycle management, file versions, path issues, scan runs, and maintenance.
"""

import json
import uuid
from typing import Any

from core.db.connection import (
    db_execute,
    db_fetch_all,
    db_fetch_one,
    get_db,
    now_iso,
)


# ── Lifecycle query helpers ──────────────────────────────────────────────────

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


# ── Source file query helpers ───────────────────────────────────────────────

async def get_source_file_by_path(source_path: str) -> dict[str, Any] | None:
    """Return a single source_files row by its unique source_path."""
    return await db_fetch_one(
        "SELECT * FROM source_files WHERE source_path=?", (source_path,),
    )


async def get_source_file_count(
    lifecycle_status: str | None = None,
    file_ext: str | None = None,
) -> int:
    """Return count of source_files, optionally filtered."""
    sql = "SELECT COUNT(*) AS cnt FROM source_files WHERE 1=1"
    params: list[Any] = []
    if lifecycle_status is not None:
        sql += " AND lifecycle_status=?"
        params.append(lifecycle_status)
    if file_ext is not None:
        sql += " AND file_ext=?"
        params.append(file_ext)
    row = await db_fetch_one(sql, tuple(params))
    return row["cnt"] if row else 0


async def update_source_file(source_file_id: str, **fields) -> None:
    """Update any combination of source_files fields."""
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [source_file_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE source_files SET {', '.join(sets)} WHERE id=?", values,
        )
        await conn.commit()


async def get_source_files_by_lifecycle_status(
    status: str,
    limit: int | None = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return source_files rows matching a lifecycle_status.

    `limit=None` returns all matching rows. Used by purge_all_trash so
    a single API call can clear an entire trash pile, not just the
    first 500. Default `limit=500` preserves the legacy paginated
    behavior for callers that walk pages by hand.
    """
    if limit is None:
        return await db_fetch_all(
            """SELECT * FROM source_files
               WHERE lifecycle_status=?
               ORDER BY source_path""",
            (status,),
        )
    return await db_fetch_all(
        """SELECT * FROM source_files
           WHERE lifecycle_status=?
           ORDER BY source_path
           LIMIT ? OFFSET ?""",
        (status, limit, offset),
    )


async def count_source_files_by_lifecycle_status(status: str) -> int:
    """True total count of rows for a lifecycle_status. The paginated
    fetch above can't distinguish "page is the last page" from "page
    hit the limit." This is the dedicated counter for /api/trash and
    similar endpoints that need a real total for UI display."""
    row = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM source_files WHERE lifecycle_status=?",
        (status,),
    )
    return row["cnt"] if row else 0


async def get_source_files_pending_trash(
    grace_period_hours: int = 36,
) -> list[dict[str, Any]]:
    """Return source_files marked for deletion whose grace period has expired."""
    return await db_fetch_all(
        """SELECT * FROM source_files
           WHERE lifecycle_status='marked_for_deletion'
             AND marked_for_deletion_at IS NOT NULL
             AND datetime(marked_for_deletion_at, '+' || ? || ' hours') <= datetime('now')
           ORDER BY marked_for_deletion_at""",
        (grace_period_hours,),
    )


async def get_source_files_pending_purge(
    trash_retention_days: int = 60,
) -> list[dict[str, Any]]:
    """Return source_files in trash whose retention period has expired."""
    return await db_fetch_all(
        """SELECT * FROM source_files
           WHERE lifecycle_status='trashed'
             AND moved_to_trash_at IS NOT NULL
             AND datetime(moved_to_trash_at, '+' || ? || ' days') <= datetime('now')
           ORDER BY moved_to_trash_at""",
        (trash_retention_days,),
    )


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
    now = now_iso()
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


# ── Version helpers ──────────────────────────────────────────────────────────

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


# ── Scan run helpers ─────────────────────────────────────────────────────────

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


# ── Maintenance helpers ──────────────────────────────────────────────────────

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
