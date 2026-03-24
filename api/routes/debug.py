"""
Debug dashboard endpoints.

GET /debug                       — Debug dashboard HTML page.
GET /debug/api/health            — System health snapshot (JSON).
GET /debug/api/activity          — Recent conversion activity (JSON).
GET /debug/api/logs              — Last N log events as JSON array.
GET /debug/api/ocr_distribution  — OCR confidence score distribution (JSON).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse

from core.auth import AuthenticatedUser, UserRole, require_role

from core.database import db_fetch_all, db_fetch_one
from core.health import run_health_check

log = structlog.get_logger(__name__)
router = APIRouter(tags=["debug"])

LOG_FILE = Path("logs/markflow.json")


# ── GET /debug — serve dashboard HTML ────────────────────────────────────────

@router.get("/debug", include_in_schema=False)
async def debug_dashboard():
    """Serve the debug dashboard HTML page."""
    html_path = Path("static/debug.html")
    if html_path.exists():
        return FileResponse(str(html_path), media_type="text/html")
    return JSONResponse({"error": "debug.html not found"}, status_code=404)


# ── GET /debug/api/health ────────────────────────────────────────────────────

@router.get("/debug/api/health")
async def debug_health(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """System health snapshot — reuses core health check logic."""
    return await run_health_check()


# ── GET /debug/api/activity ──────────────────────────────────────────────────

@router.get("/debug/api/activity")
async def debug_activity(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Recent conversion activity, active batches, OCR flag counts, stats."""
    # Active batches (not yet done)
    active_rows = await db_fetch_all(
        "SELECT batch_id, total_files, completed_files, created_at "
        "FROM batch_state WHERE status NOT IN ('done', 'failed') "
        "ORDER BY created_at DESC LIMIT 10"
    )
    active_batches = [
        {
            "batch_id": r["batch_id"],
            "file_count": r["total_files"],
            "completed": r.get("completed_files", 0),
            "started_at": str(r.get("created_at", "")),
        }
        for r in active_rows
    ]

    # Recent history (last 20)
    recent_rows = await db_fetch_all(
        "SELECT batch_id, source_filename, status, source_format, duration_ms, created_at "
        "FROM conversion_history ORDER BY created_at DESC LIMIT 20"
    )
    recent_history = [
        {
            "batch_id": r["batch_id"],
            "filename": r["source_filename"],
            "status": r["status"],
            "format": r["source_format"],
            "duration_ms": r.get("duration_ms", 0),
            "completed_at": str(r.get("created_at", "")),
        }
        for r in recent_rows
    ]

    # OCR flag counts
    ocr_counts = {"pending": 0, "accepted": 0, "corrected": 0}
    try:
        for status_val in ("pending", "accepted", "edited"):
            row = await db_fetch_one(
                "SELECT COUNT(*) as n FROM ocr_flags WHERE status = ?",
                (status_val,),
            )
            key = "corrected" if status_val == "edited" else status_val
            ocr_counts[key] = row["n"] if row else 0
    except Exception:
        pass

    # Stats
    stats_row = await db_fetch_one(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successes, "
        "AVG(duration_ms) as avg_dur "
        "FROM conversion_history"
    )
    total = stats_row["total"] if stats_row else 0
    successes = stats_row["successes"] if stats_row else 0
    avg_dur = stats_row["avg_dur"] if stats_row else 0

    # Vision stats
    vision_stats = {}
    try:
        v_row = await db_fetch_one(
            "SELECT SUM(scene_count) as scenes, SUM(frame_desc_count) as descs, "
            "SUM(keyframe_count) as kf, "
            "SUM(CASE WHEN frame_desc_count IS NOT NULL AND keyframe_count IS NOT NULL "
            "  THEN keyframe_count - frame_desc_count ELSE 0 END) as failed "
            "FROM conversion_history WHERE scene_count IS NOT NULL"
        )
        if v_row and v_row["scenes"]:
            vision_stats = {
                "scenes_detected_total": v_row["scenes"] or 0,
                "frames_described_total": v_row["descs"] or 0,
                "frames_failed_total": v_row["failed"] or 0,
            }
        # Get active vision provider info
        vp_row = await db_fetch_one(
            "SELECT vision_provider, vision_model FROM conversion_history "
            "WHERE vision_provider IS NOT NULL ORDER BY created_at DESC LIMIT 1"
        )
        if vp_row:
            vision_stats["active_provider"] = vp_row["vision_provider"]
            vision_stats["active_model"] = vp_row["vision_model"]
    except Exception:
        pass

    return {
        "active_batches": active_batches,
        "recent_history": recent_history,
        "ocr_flags": ocr_counts,
        "stats": {
            "total_conversions": total,
            "success_rate_pct": round(successes / total * 100, 1) if total else 0.0,
            "avg_duration_ms": round(avg_dur) if avg_dur else 0,
        },
        "vision_stats": vision_stats,
    }


# ── GET /debug/api/logs ──────────────────────────────────────────────────────

@router.get("/debug/api/logs")
async def debug_logs(
    lines: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Return last N lines from logs/markflow.json as parsed JSON objects."""
    if not LOG_FILE.exists():
        return {"events": [], "lines": 0, "log_file": str(LOG_FILE)}

    try:
        raw_lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    except Exception:
        return {"events": [], "lines": 0, "log_file": str(LOG_FILE)}

    # Take last N lines
    tail = raw_lines[-lines:] if len(raw_lines) > lines else raw_lines

    events = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"raw": line})

    return {
        "events": events,
        "lines": len(events),
        "log_file": str(LOG_FILE),
    }


# ── GET /debug/api/ocr_distribution ──────────────────────────────────────────

@router.get("/debug/api/ocr_distribution")
async def debug_ocr_distribution(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Confidence score distribution for OCR'd files."""
    buckets = []
    total_pages = 0
    total_conf = 0.0

    try:
        rows = await db_fetch_all(
            "SELECT confidence FROM ocr_flags"
        )
    except Exception:
        rows = []

    if not rows:
        return {
            "buckets": [{"range": f"{i*10}-{i*10+10}", "count": 0} for i in range(10)],
            "mean_confidence": 0.0,
            "total_pages": 0,
        }

    # Build 10 buckets (0-10, 10-20, ..., 90-100)
    counts = [0] * 10
    for r in rows:
        conf = float(r.get("confidence", 0))
        idx = min(int(conf / 10), 9)
        counts[idx] += 1
        total_conf += conf
        total_pages += 1

    buckets = [
        {"range": f"{i*10}-{i*10+10}", "count": counts[i]}
        for i in range(10)
    ]

    mean_conf = round(total_conf / total_pages, 1) if total_pages else 0.0

    return {
        "buckets": buckets,
        "mean_confidence": mean_conf,
        "total_pages": total_pages,
    }
