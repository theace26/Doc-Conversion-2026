"""GET /api/activity/summary — single aggregated payload for the
Activity dashboard. Operator/admin only.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §5
"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, Depends

from core.auth import AuthenticatedUser, UserRole, require_role
from core.db.connection import db_fetch_all, db_fetch_one

router = APIRouter(prefix="/api/activity", tags=["activity"])

_require_operator = require_role(UserRole.OPERATOR)


@router.get("/summary")
async def activity_summary(user: AuthenticatedUser = Depends(_require_operator)):
    """Aggregate everything the Activity dashboard needs into one payload."""
    pulse, tiles, throughput, running, queues, recent = await asyncio.gather(
        _pulse(),
        _tiles(),
        _throughput_24h(),
        _running_jobs(),
        _queues(),
        _recent_jobs(),
    )
    return {
        "pulse": pulse,
        "tiles": tiles,
        "throughput": throughput,
        "running_jobs": running,
        "queues": queues,
        "recent_jobs": recent,
    }


async def _pulse() -> dict:
    """Health pulse: running job count + indexed file count."""
    active = await _safe_count(
        "SELECT COUNT(*) AS cnt FROM bulk_jobs WHERE status='running'"
    )
    indexed = await _safe_count(
        "SELECT COUNT(*) AS cnt FROM source_files WHERE lifecycle_status='active'"
    )
    return {
        "status": "ok",
        "label": f"All systems running · {indexed:,} indexed",
        "active_jobs": active,
    }


async def _tiles() -> dict:
    """Top tiles: files processed today, in queue, active jobs, last error."""
    today_processed = await _safe_count(
        """SELECT COUNT(*) AS cnt FROM bulk_files
           WHERE status='converted' AND DATE(updated_at) = DATE('now')"""
    )
    in_queue = await _safe_count(
        "SELECT COUNT(*) AS cnt FROM bulk_files WHERE status='pending'"
    )
    active_jobs = await _safe_count(
        "SELECT COUNT(*) AS cnt FROM bulk_jobs WHERE status='running'"
    )
    last_error = await _safe_fetch_one(
        "SELECT MAX(timestamp) AS ts FROM activity_events WHERE event_type='error'"
    )
    return {
        "files_processed_today": today_processed,
        "in_queue": in_queue,
        "active_jobs": active_jobs,
        "last_error_at": (last_error.get("ts") if last_error else None),
    }


async def _throughput_24h() -> list[dict]:
    """24 hourly buckets of files-converted counts for sparkline rendering."""
    rows = await _safe_fetch_all(
        """SELECT CAST(strftime('%H', updated_at) AS INTEGER) AS hour,
                  COUNT(*) AS cnt
           FROM bulk_files
           WHERE status='converted'
             AND updated_at >= datetime('now', '-24 hours')
           GROUP BY hour ORDER BY hour"""
    )
    by_hour = {r["hour"]: r["cnt"] for r in rows}
    return [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)]


async def _running_jobs() -> list[dict]:
    rows = await _safe_fetch_all(
        """SELECT id, source_path, started_at, total_files,
                  converted, failed, eta_seconds
           FROM bulk_jobs
           WHERE status='running'
           ORDER BY started_at DESC LIMIT 10"""
    )
    return [
        {
            "id": r["id"],
            "source_path": r["source_path"],
            "started_at": r["started_at"],
            "total": r["total_files"] or 0,
            "converted": r["converted"] or 0,
            "failed": r["failed"] or 0,
            "eta_seconds": r["eta_seconds"],
        }
        for r in rows
    ]


async def _queues() -> dict:
    """Queue depth snapshot: recently converted, pending, awaiting AI, recently failed."""
    return {
        "recently_converted": await _safe_count(
            """SELECT COUNT(*) AS cnt FROM bulk_files
               WHERE status='converted' AND updated_at >= datetime('now', '-24 hours')"""
        ),
        "needs_ocr": await _safe_count(
            "SELECT COUNT(*) AS cnt FROM bulk_files WHERE status='pending_ocr'"
        ),
        "awaiting_ai_summary": await _safe_count(
            "SELECT COUNT(*) AS cnt FROM analysis_queue WHERE status='pending'"
        ),
        "recently_failed": await _safe_count(
            """SELECT COUNT(DISTINCT bf.source_path) AS cnt FROM bulk_files bf
               WHERE bf.status='failed' AND bf.updated_at >= datetime('now', '-24 hours')"""
        ),
    }


async def _recent_jobs() -> list[dict]:
    rows = await _safe_fetch_all(
        """SELECT id, source_path, status, started_at, completed_at,
                  total_files, converted, failed, auto_triggered
           FROM bulk_jobs
           ORDER BY started_at DESC LIMIT 10"""
    )
    return [
        {
            "id": r["id"],
            "source_path": r["source_path"],
            "status": r["status"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "total": r["total_files"] or 0,
            "converted": r["converted"] or 0,
            "failed": r["failed"] or 0,
            "auto_triggered": bool(r["auto_triggered"]),
        }
        for r in rows
    ]


async def _safe_count(sql: str) -> int:
    try:
        row = await db_fetch_one(sql)
        return row["cnt"] if row else 0
    except Exception:
        return 0


async def _safe_fetch_one(sql: str) -> dict | None:
    try:
        return await db_fetch_one(sql)
    except Exception:
        return None


async def _safe_fetch_all(sql: str) -> list[dict]:
    try:
        return await db_fetch_all(sql)
    except Exception:
        return []
