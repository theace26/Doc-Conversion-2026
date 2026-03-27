"""Auto-conversion engine API endpoints.

GET    /api/auto-convert/status     — Engine status + last decision
POST   /api/auto-convert/override   — Set temporary mode override
DELETE /api/auto-convert/override   — Clear mode override
GET    /api/auto-convert/history    — Recent auto-conversion run history
GET    /api/auto-convert/metrics    — Aggregated hourly metrics
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth import AuthenticatedUser, UserRole, require_role
from core.auto_converter import get_auto_conversion_engine
from core.database import db_fetch_all, db_fetch_one

router = APIRouter(prefix="/api/auto-convert", tags=["auto-convert"])


class ModeOverrideRequest(BaseModel):
    mode: str = Field(..., description="One of: off, immediate, queued, scheduled")
    duration_minutes: int = Field(60, ge=5, le=1440, description="Override duration in minutes")


# ── GET /api/auto-convert/status ─────────────────────────────────────────────

@router.get("/status")
async def get_auto_convert_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return current auto-conversion engine status."""
    engine = get_auto_conversion_engine()
    status = engine.get_status()

    # Add the configured mode from preferences
    from core.database import get_preference
    status["configured_mode"] = await get_preference("auto_convert_mode") or "off"

    return status


# ── POST /api/auto-convert/override ──────────────────────────────────────────

@router.post("/override")
async def set_auto_convert_override(
    body: ModeOverrideRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Set a temporary mode override. Expires after duration_minutes."""
    engine = get_auto_conversion_engine()
    try:
        engine.set_mode_override(body.mode, body.duration_minutes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return engine.get_status()


# ── DELETE /api/auto-convert/override ────────────────────────────────────────

@router.delete("/override")
async def clear_auto_convert_override(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Clear any active mode override."""
    engine = get_auto_conversion_engine()
    engine.clear_mode_override()
    return engine.get_status()


# ── GET /api/auto-convert/history ────────────────────────────────────────────

@router.get("/history")
async def get_auto_convert_history(
    limit: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> list:
    """Return recent auto-conversion decision history."""
    rows = await db_fetch_all(
        """SELECT * FROM auto_conversion_runs
           ORDER BY started_at DESC LIMIT ?""",
        (limit,),
    )
    return rows


# ── GET /api/auto-convert/metrics ────────────────────────────────────────────

@router.get("/metrics")
async def get_auto_convert_metrics(
    days: int = Query(7, ge=1, le=30),
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> list:
    """Return aggregated hourly metrics for the last N days."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    rows = await db_fetch_all(
        """SELECT * FROM auto_metrics
           WHERE hour_bucket >= ?
           ORDER BY hour_bucket ASC""",
        (cutoff,),
    )
    return rows
