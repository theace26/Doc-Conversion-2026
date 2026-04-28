"""Cross-reference table accessors: ``prproj_media_refs``.

Schema is defined in :mod:`core.db.schema` (CREATE TABLE in
``_SCHEMA_SQL`` + idempotent migration v28). Each row pairs a Premiere
project's ``bulk_files`` row with one media path it references. Both
directions are indexed so reverse-lookup ("which projects use this
clip?") and forward-lookup ("what does this project reference?") are
sub-millisecond up to ~100K rows.

Public surface:

    upsert_media_refs(project_path, refs)         -> int   (async)
    upsert_media_refs_sync(project_path, refs)    -> int   (sync, for handlers)
    get_projects_referencing(media_path)          -> list  (async)
    get_media_for_project(project_id)             -> list  (async)
    delete_refs_for_project(project_id)           -> int   (async)
    stats()                                       -> dict  (async)

Author: v0.34.0 Phase 2.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from typing import Any

import structlog

from core.db.connection import (
    db_execute,
    db_fetch_all,
    db_fetch_one,
    get_db_path,
    now_iso,
)

log = structlog.get_logger(__name__)


# ── Async surface (FastAPI route consumers, async tests) ─────────────────────


async def upsert_media_refs(
    *,
    project_path: str,
    refs: list[dict[str, Any]],
) -> int:
    """Replace this project's media-refs atomically.

    ``project_path`` is the absolute path of the .prproj file as stored
    in ``bulk_files.source_path``. We resolve to ``project_id`` ourselves
    so the handler can stay path-keyed (it doesn't know the bulk_files
    row id).

    Returns the number of rows written. If the bulk_files row can't be
    found (e.g. ingest fired before bulk_files was inserted), returns 0
    silently — the next conversion pass will try again.
    """
    row = await db_fetch_one(
        "SELECT id FROM bulk_files WHERE source_path = ?",
        (project_path,),
    )
    if not row:
        log.debug(
            "prproj.refs_upsert_no_bulk_row",
            project_path=project_path,
            n_refs=len(refs),
        )
        return 0
    project_id = row["id"]

    # Replace pattern: delete then insert.
    await db_execute(
        "DELETE FROM prproj_media_refs WHERE project_id = ?",
        (project_id,),
    )

    written = 0
    ts = now_iso()
    for ref in refs:
        await db_execute(
            """INSERT INTO prproj_media_refs
                (id, project_id, project_path,
                 media_path, media_name, media_type, duration_ticks,
                 in_use_in_sequences, recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                uuid.uuid4().hex,
                project_id,
                project_path,
                ref.get("media_path", ""),
                ref.get("media_name"),
                ref.get("media_type"),
                ref.get("duration_ticks"),
                ref.get("in_use_in_sequences"),
                ts,
            ),
        )
        written += 1

    log.info(
        "prproj.media_ref_recorded",
        project_id=project_id,
        project_path=project_path,
        n_refs=written,
    )
    return written


async def get_projects_referencing(media_path: str) -> list[dict[str, Any]]:
    """Reverse lookup: which projects reference this media file?

    Returns a list of {project_id, project_path, media_name, media_type,
    recorded_at} sorted by recorded_at DESC. Empty list if no matches.
    """
    rows = await db_fetch_all(
        """SELECT DISTINCT
                project_id,
                project_path,
                media_name,
                media_type,
                MAX(recorded_at) AS recorded_at
           FROM prproj_media_refs
           WHERE media_path = ?
           GROUP BY project_id, project_path, media_name, media_type
           ORDER BY recorded_at DESC""",
        (media_path,),
    )
    log.info(
        "prproj.cross_ref_lookup",
        media_path=media_path,
        n_results=len(rows),
    )
    return rows


async def get_media_for_project(project_id: str) -> list[dict[str, Any]]:
    """Forward lookup: what media does this project reference?"""
    return await db_fetch_all(
        """SELECT media_path, media_name, media_type, duration_ticks,
                  in_use_in_sequences, recorded_at
           FROM prproj_media_refs
           WHERE project_id = ?
           ORDER BY media_type, media_name""",
        (project_id,),
    )


async def delete_refs_for_project(project_id: str) -> int:
    """Delete every ref for a given project. Returns rows deleted (best
    effort; SQLite does not return a delete count from the connection
    pool wrapper)."""
    before = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM prproj_media_refs WHERE project_id = ?",
        (project_id,),
    )
    n = before["cnt"] if before else 0
    await db_execute(
        "DELETE FROM prproj_media_refs WHERE project_id = ?",
        (project_id,),
    )
    return n


async def stats() -> dict[str, Any]:
    """Aggregate stats: project count, ref count, top-5 most-referenced."""
    n_projects = await db_fetch_one(
        "SELECT COUNT(DISTINCT project_id) AS cnt FROM prproj_media_refs"
    )
    n_refs = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM prproj_media_refs"
    )
    top = await db_fetch_all(
        """SELECT media_path, COUNT(DISTINCT project_id) AS n_projects
           FROM prproj_media_refs
           GROUP BY media_path
           ORDER BY n_projects DESC, media_path
           LIMIT 5"""
    )
    return {
        "n_projects": n_projects["cnt"] if n_projects else 0,
        "n_media_refs": n_refs["cnt"] if n_refs else 0,
        "top_5_most_referenced": top,
    }


# ── Sync surface (for handler.ingest, called from worker threads) ────────────
#
# Handlers are invoked synchronously from sync worker threads
# (core/converter.py and asyncio.to_thread paths in core/bulk_worker.py).
# Inside a sync context we can't await async DB helpers — so we open a
# short-lived sqlite3 connection directly. WAL + busy_timeout make this
# safe to coexist with the connection pool. Failures are logged and
# swallowed; ingest never fails because of cross-ref persistence.


def upsert_media_refs_sync(
    *,
    project_path: str,
    refs: list[dict[str, Any]],
) -> int:
    """Synchronous companion of :func:`upsert_media_refs`.

    Opens a short-lived sqlite3 connection (WAL + busy_timeout). Idempotent:
    deletes existing refs for the project, then re-inserts. Returns the
    number of rows written, or 0 if the bulk_files row can't be found yet.

    This bypasses the connection pool by design — the handler runs from
    sync worker threads where the pool's async API isn't reachable, and
    SQLite WAL serializes the actual writes safely.
    """
    if not refs:
        return 0
    db_path = os.environ.get("DB_PATH", get_db_path())
    written = 0
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA foreign_keys=ON")

            cur = conn.execute(
                "SELECT id FROM bulk_files WHERE source_path = ?",
                (project_path,),
            )
            row = cur.fetchone()
            if not row:
                log.debug(
                    "prproj.refs_sync_upsert_no_bulk_row",
                    project_path=project_path,
                    n_refs=len(refs),
                )
                return 0
            project_id = row["id"]

            conn.execute(
                "DELETE FROM prproj_media_refs WHERE project_id = ?",
                (project_id,),
            )
            from datetime import datetime, timezone

            ts = datetime.now(timezone.utc).isoformat()
            for ref in refs:
                conn.execute(
                    """INSERT INTO prproj_media_refs
                        (id, project_id, project_path,
                         media_path, media_name, media_type, duration_ticks,
                         in_use_in_sequences, recorded_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        uuid.uuid4().hex,
                        project_id,
                        project_path,
                        ref.get("media_path", ""),
                        ref.get("media_name"),
                        ref.get("media_type"),
                        ref.get("duration_ticks"),
                        ref.get("in_use_in_sequences"),
                        ts,
                    ),
                )
                written += 1
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        # "no such table: prproj_media_refs" — fresh DB whose migrations
        # haven't run yet (test paths or pre-init contexts). Log + skip.
        log.warning(
            "prproj.refs_sync_table_missing",
            project_path=project_path,
            error=str(exc),
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "prproj.refs_sync_failed",
            project_path=project_path,
            error_class=exc.__class__.__name__,
            error=str(exc),
        )
        return 0

    return written


__all__ = [
    "upsert_media_refs",
    "upsert_media_refs_sync",
    "get_projects_referencing",
    "get_media_for_project",
    "delete_refs_for_project",
    "stats",
]
