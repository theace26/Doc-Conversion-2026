"""
Database health and maintenance API endpoints.

GET  /api/db/health           — health summary
POST /api/db/compact          — trigger compaction
POST /api/db/integrity-check  — run integrity check
POST /api/db/stale-check      — run stale data check
GET  /api/db/maintenance-log  — recent log entries
"""

from fastapi import APIRouter, BackgroundTasks, Depends

from core.auth import AuthenticatedUser, UserRole, require_role

from core.database import get_maintenance_log

router = APIRouter(prefix="/api/db", tags=["db_health"])


@router.get("/health")
async def db_health(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Return comprehensive DB health summary."""
    from core.db_maintenance import get_health_summary
    return await get_health_summary()


@router.post("/compact")
async def trigger_compaction(
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Trigger DB compaction in background."""
    from core.db_maintenance import run_compaction

    # Check for running scans
    from core.database import db_fetch_one
    running = await db_fetch_one(
        "SELECT id FROM scan_runs WHERE status='running' LIMIT 1"
    )
    if running:
        return {"message": "Compaction deferred — scan in progress", "deferred": True}

    background_tasks.add_task(run_compaction)
    return {"message": "Compaction started", "deferred": False}


@router.post("/integrity-check")
async def trigger_integrity_check(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Run integrity check synchronously."""
    from core.db_maintenance import run_integrity_check
    return await run_integrity_check()


@router.post("/stale-check")
async def trigger_stale_check(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Run all stale data checks synchronously."""
    from core.db_maintenance import run_stale_data_check
    result = await run_stale_data_check()
    return {"checks": result}


@router.get("/maintenance-log")
async def maintenance_log(
    limit: int = 50,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Return recent maintenance log entries."""
    entries = await get_maintenance_log(limit=limit)
    return {"entries": entries}


@router.post("/health-check")
async def run_health_check(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Quick DB health check: structure, WAL size, row counts. Under 1 second."""
    from core.db_maintenance import run_quick_health_check
    return await run_quick_health_check()


@router.post("/full-integrity-check")
async def run_full_integrity(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Full integrity check. May take 30+ seconds on large databases."""
    from core.db_maintenance import run_full_integrity_check
    return await run_full_integrity_check()


@router.post("/repair")
async def repair_db(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Dump-and-restore repair. Blocks if jobs are running."""
    from core.db_maintenance import repair_database
    return await repair_database()
