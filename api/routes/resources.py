"""
Resources API — historical metrics, disk history, activity events, executive summary, CSV export.

GET  /api/resources/metrics   — time-range-filtered, downsampled system metrics
GET  /api/resources/disk      — historical disk usage
GET  /api/resources/events    — activity event log
GET  /api/resources/summary   — executive summary (the IT admin pitch card)
GET  /api/resources/export    — CSV download of any metrics table
"""

import csv
import io
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.auth import AuthenticatedUser, UserRole, require_role
from core.metrics_collector import (
    query_system_metrics,
    query_disk_metrics,
    query_activity_events,
    compute_summary,
    _auto_resolution,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/resources", tags=["resources"])

_VALID_RANGES = {"1h", "6h", "24h", "7d", "30d", "90d"}
_VALID_RESOLUTIONS = {"raw", "1m", "5m", "15m", "1h", "6h"}


def _validate_range(range_str: str) -> str:
    if range_str not in _VALID_RANGES:
        raise HTTPException(status_code=400, detail=f"Invalid range '{range_str}'. Valid: {', '.join(sorted(_VALID_RANGES))}")
    return range_str


# ── GET /api/resources/metrics ────────────────────────────────────────────────

@router.get("/metrics")
async def get_metrics(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
    range: str = Query("24h", alias="range"),
    resolution: str | None = Query(None),
):
    """Historical system metrics with time range and downsampling."""
    range_str = _validate_range(range)
    if resolution and resolution not in _VALID_RESOLUTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid resolution '{resolution}'")

    effective_resolution = resolution or _auto_resolution(range_str)
    try:
        points = await query_system_metrics(range_str, effective_resolution)
        return {
            "range": range_str,
            "resolution": effective_resolution,
            "points": points,
        }
    except Exception as exc:
        log.error("resources.metrics_failed", error=str(exc))
        return {"range": range_str, "resolution": effective_resolution, "points": [], "error": str(exc)}


# ── GET /api/resources/disk ───────────────────────────────────────────────────

@router.get("/disk")
async def get_disk_history(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
    range: str = Query("30d", alias="range"),
):
    """Historical disk metrics."""
    range_str = _validate_range(range)
    try:
        points = await query_disk_metrics(range_str)
        return {"range": range_str, "points": points}
    except Exception as exc:
        log.error("resources.disk_failed", error=str(exc))
        return {"range": range_str, "points": [], "error": str(exc)}


# ── GET /api/resources/events ─────────────────────────────────────────────────

@router.get("/events")
async def get_events(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
    range: str = Query("7d", alias="range"),
    type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Activity event log with filtering."""
    range_str = _validate_range(range)
    event_types = [t.strip() for t in type.split(",")] if type else None
    try:
        events, total = await query_activity_events(range_str, event_types, limit)
        return {"events": events, "total": total}
    except Exception as exc:
        log.error("resources.events_failed", error=str(exc))
        return {"events": [], "total": 0, "error": str(exc)}


# ── GET /api/resources/summary ────────────────────────────────────────────────

@router.get("/summary")
async def get_summary(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
    days: int = Query(30, ge=1, le=90),
):
    """Executive summary — the IT admin pitch card."""
    try:
        return await compute_summary(days)
    except Exception as exc:
        log.error("resources.summary_failed", error=str(exc))
        return {
            "period_days": days,
            "error": str(exc),
            "cpu": None, "memory": None, "disk": None,
            "io": None, "activity": None, "self_governance": None,
        }


# ── GET /api/resources/export ─────────────────────────────────────────────────

@router.get("/export")
async def export_csv(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
    table: str = Query(..., description="system, disk, or events"),
    range: str = Query("30d", alias="range"),
):
    """Export raw metrics as CSV."""
    range_str = _validate_range(range)

    if table == "system":
        rows = await query_system_metrics(range_str, "raw")
        filename = f"markflow-system-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    elif table == "disk":
        rows = await query_disk_metrics(range_str)
        filename = f"markflow-disk-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    elif table == "events":
        events, _ = await query_activity_events(range_str, limit=500)
        rows = events
        filename = f"markflow-events-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    else:
        raise HTTPException(status_code=400, detail="table must be 'system', 'disk', or 'events'")

    if not rows:
        return StreamingResponse(
            io.BytesIO(b"No data\n"),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    for row in rows:
        # Serialize any dict values (metadata) to string
        clean = {}
        for k, v in row.items():
            if isinstance(v, dict):
                import json
                clean[k] = json.dumps(v)
            else:
                clean[k] = v
        writer.writerow(clean)

    content = output.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
