"""
Scanner status and control API endpoints.

GET  /api/scanner/status     — last run, is_running, next estimate, business hours
GET  /api/scanner/progress   — live scan progress (polling)
POST /api/scanner/run-now    — trigger immediate scan
GET  /api/scanner/runs       — recent scan run history
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends

from core.auth import AuthenticatedUser, UserRole, require_role

from api.models import ScanRunRecord
from core.database import db_fetch_all, get_latest_scan_run, get_preference

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


def _row_to_record(row: dict) -> ScanRunRecord:
    return ScanRunRecord(
        id=row["id"],
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        status=row.get("status", "unknown"),
        files_scanned=row.get("files_scanned", 0),
        files_new=row.get("files_new", 0),
        files_modified=row.get("files_modified", 0),
        files_moved=row.get("files_moved", 0),
        files_deleted=row.get("files_deleted", 0),
        files_restored=row.get("files_restored", 0),
        errors=row.get("errors", 0),
    )


@router.get("/status")
async def scanner_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Current scanner status."""
    last_run = await get_latest_scan_run()

    # Check if any scan is currently running
    running_row = await db_fetch_all(
        "SELECT id FROM scan_runs WHERE status='running' LIMIT 1"
    )
    is_running = bool(running_row)

    # Business hours config
    start = await get_preference("scanner_business_hours_start") or "06:00"
    end = await get_preference("scanner_business_hours_end") or "18:00"
    interval = await get_preference("scanner_interval_minutes") or "15"

    return {
        "last_run": _row_to_record(last_run).model_dump() if last_run else None,
        "is_running": is_running,
        "next_run_estimate": None,
        "business_hours": {
            "start": start,
            "end": end,
            "days": [1, 2, 3, 4, 5],
            "interval_minutes": int(interval),
        },
    }


@router.get("/progress")
async def scanner_progress(
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
) -> dict:
    """Live scan progress — poll this endpoint every 3 seconds."""
    from core.lifecycle_scanner import get_scan_state
    return get_scan_state()


@router.post("/run-now")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Trigger immediate scan (runs in background)."""
    from core.lifecycle_scanner import run_lifecycle_scan
    import uuid

    scan_run_id = uuid.uuid4().hex

    async def _run():
        await run_lifecycle_scan()

    background_tasks.add_task(_run)
    return {"scan_run_id": scan_run_id, "message": "Scan triggered"}


@router.get("/runs")
async def list_runs(
    limit: int = 10,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """List recent scan runs."""
    rows = await db_fetch_all(
        "SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT ?", (limit,)
    )
    return {"runs": [_row_to_record(r).model_dump() for r in rows]}
