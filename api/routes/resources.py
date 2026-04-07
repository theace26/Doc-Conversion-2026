"""
Resources API — historical metrics, disk history, activity events, executive summary, CSV export,
OCR quality metrics, scan throttle history.

GET  /api/resources/metrics          — time-range-filtered, downsampled system metrics
GET  /api/resources/disk             — historical disk usage
GET  /api/resources/events           — activity event log
GET  /api/resources/summary          — executive summary (the IT admin pitch card)
GET  /api/resources/export           — CSV download of any metrics table
GET  /api/resources/ocr-quality      — OCR confidence avg / min / max / distribution
GET  /api/resources/scan-throttle    — scan throttle adjustment history
GET  /api/resources/active           — currently active users + live stream connections (v0.22.13)
"""

import csv
import io
import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.active_connections import (
    get_active_streams,
    get_active_users,
    get_total_active_streams,
)
from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import db_fetch_all, get_preference
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


# ── GET /api/resources/ocr-quality ────────────────────────────────────────────

@router.get("/ocr-quality")
async def get_ocr_quality(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
    range: str = Query("30d", alias="range"),
):
    """OCR confidence metrics — avg, min, max, distribution, files below threshold."""
    range_str = _validate_range(range)

    from core.metrics_collector import _range_to_cutoff
    cutoff = _range_to_cutoff(range_str)

    try:
        rows = await db_fetch_all(
            """SELECT ocr_confidence_mean, ocr_confidence_min, ocr_page_count,
                      ocr_pages_below_threshold, created_at
               FROM conversion_history
               WHERE ocr_confidence_mean IS NOT NULL
                 AND created_at >= ?
               ORDER BY created_at ASC""",
            (cutoff,),
        )

        if not rows:
            return {
                "range": range_str,
                "files_with_ocr": 0,
                "avg_confidence": None,
                "min_confidence": None,
                "max_confidence": None,
                "threshold": None,
                "files_below_threshold": 0,
                "distribution": [],
                "timeline": [],
            }

        confs = [r["ocr_confidence_mean"] for r in rows]
        mins = [r["ocr_confidence_min"] for r in rows if r["ocr_confidence_min"] is not None]

        avg_conf = round(sum(confs) / len(confs), 1)
        min_conf = round(min(mins), 1) if mins else round(min(confs), 1)
        max_conf = round(max(confs), 1)

        threshold_str = await get_preference("ocr_confidence_threshold") or "70"
        threshold = float(threshold_str)
        below = sum(1 for c in confs if c < threshold)

        # Distribution buckets (0-10, 10-20, ..., 90-100)
        buckets = [0] * 10
        for c in confs:
            idx = min(int(c // 10), 9)
            buckets[idx] += 1
        distribution = [
            {"range": f"{i*10}-{i*10+10}", "count": buckets[i]}
            for i in range(10)
        ]

        # Timeline (for chart) — group by day
        from collections import defaultdict
        daily: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            day = r["created_at"][:10] if r["created_at"] else "unknown"
            daily[day].append(r["ocr_confidence_mean"])

        timeline = [
            {
                "date": day,
                "avg": round(sum(vals) / len(vals), 1),
                "min": round(min(vals), 1),
                "max": round(max(vals), 1),
                "count": len(vals),
            }
            for day, vals in sorted(daily.items())
        ]

        return {
            "range": range_str,
            "files_with_ocr": len(confs),
            "avg_confidence": avg_conf,
            "min_confidence": min_conf,
            "max_confidence": max_conf,
            "threshold": threshold,
            "files_below_threshold": below,
            "distribution": distribution,
            "timeline": timeline,
        }
    except Exception as exc:
        log.error("resources.ocr_quality_failed", error=str(exc))
        return {"range": range_str, "error": str(exc)}


# ── GET /api/resources/scan-throttle ─────────────────────────────────────────

@router.get("/scan-throttle")
async def get_scan_throttle_history(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
    range: str = Query("7d", alias="range"),
    limit: int = Query(100, ge=1, le=500),
):
    """Scan throttle adjustment history from activity events."""
    range_str = _validate_range(range)

    try:
        # Query both individual throttle events and summaries
        events, total = await query_activity_events(
            range_str,
            event_types=["scan_throttle", "scan_throttle_summary"],
            limit=limit,
        )

        adjustments = []
        summaries = []
        for ev in events:
            meta = ev.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            if ev.get("event_type") == "scan_throttle":
                adjustments.append({
                    "timestamp": ev.get("timestamp"),
                    "direction": meta.get("direction", "unknown"),
                    "from_threads": meta.get("from_threads"),
                    "to_threads": meta.get("to_threads"),
                    "latency_ratio": meta.get("latency_ratio"),
                    "median_ms": meta.get("median_ms"),
                    "baseline_ms": meta.get("baseline_ms"),
                    "scan_type": meta.get("scan_type"),
                    "job_id": meta.get("job_id"),
                })
            else:
                summaries.append({
                    "timestamp": ev.get("timestamp"),
                    "scan_type": meta.get("scan_type"),
                    "adjustments": meta.get("adjustments", 0),
                    "max_threads": meta.get("max_threads"),
                    "final_threads": meta.get("final_threads"),
                    "total_errors": meta.get("total_errors", 0),
                    "error_rate": meta.get("error_rate", 0),
                    "aborted": meta.get("aborted", False),
                    "job_id": meta.get("job_id"),
                })

        return {
            "range": range_str,
            "adjustments": adjustments,
            "summaries": summaries,
            "total_events": total,
        }
    except Exception as exc:
        log.error("resources.scan_throttle_failed", error=str(exc))
        return {"range": range_str, "adjustments": [], "summaries": [], "error": str(exc)}


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


# ── GET /api/resources/active ────────────────────────────────────────────────

@router.get("/active")
async def get_active_connections(
    window_seconds: int = Query(default=300, ge=10, le=3600,
                                description="Sliding window for 'recently active' users"),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """
    Return who/what is currently using MarkFlow (v0.22.13).

    Two independent in-memory counters (no DB schema, resets on restart):

    - **Recently active users** — last-seen timestamp per `user.sub`,
      updated by the request middleware. Returns users seen in the last
      `window_seconds` (default 5 min).
    - **Live SSE / streaming connections** — incremented when a long-lived
      StreamingResponse generator starts and decremented in `finally`.
      Bucketed by endpoint label so admins can see *which* live streams
      are open.

    The widget on the Resources page polls this endpoint every ~5 seconds.
    """
    users = get_active_users(window_seconds=window_seconds)
    streams_by_endpoint = get_active_streams()
    total_streams = get_total_active_streams()
    return {
        "window_seconds": window_seconds,
        "users": users,
        "total_users": len(users),
        "total_streams": total_streams,
        "streams_by_endpoint": streams_by_endpoint,
    }
