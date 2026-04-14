"""
Database health and maintenance API endpoints.

GET  /api/db/health           — health summary
POST /api/db/compact          — trigger compaction
POST /api/db/integrity-check  — run integrity check
POST /api/db/stale-check      — run stale data check
GET  /api/db/maintenance-log  — recent log entries
"""

from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.auth import AuthenticatedUser, UserRole, require_role

from core.database import get_maintenance_log

log = structlog.get_logger(__name__)

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


def _error_to_http_status(error: str) -> int:
    """Map a db_backup error string to an HTTP status code."""
    if "Bulk jobs active" in error:
        return 409
    return 400


@router.post("/backup")
async def db_backup(
    download: bool = False,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Create a DB backup. With download=True, streams the file to the caller.

    Otherwise saves into BACKUPS_DIR and returns a metadata dict.
    """
    from core.db_backup import backup_database

    result = await backup_database(download=download)

    # download=True returns a FileResponse on success
    if isinstance(result, FileResponse):
        return result

    # Otherwise result is a dict
    if not result.get("ok", False):
        err = result.get("error", "Backup failed")
        raise HTTPException(status_code=_error_to_http_status(err), detail=err)
    return result


@router.post("/restore")
async def db_restore(
    file: UploadFile | None = File(default=None),
    backup_path: str | None = Form(default=None),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Restore the live DB from either an uploaded file or a server-side backup path.

    Exactly one of ``file`` (multipart upload) or ``backup_path`` (form field
    naming a file under BACKUPS_DIR) must be supplied.
    """
    if (file is None) == (backup_path is None):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of 'file' (upload) or 'backup_path' (server-side path)",
        )

    from core.db_backup import restore_database

    try:
        if file is not None:
            uploaded = await file.read()
            result = await restore_database(uploaded_bytes=uploaded)
        else:
            result = await restore_database(source_path=Path(backup_path))  # type: ignore[arg-type]
    except ValueError as exc:
        # Path-traversal / "exactly one" guard from restore_database
        raise HTTPException(status_code=400, detail=str(exc))

    if not result.get("ok", False):
        err = result.get("error", "Restore failed")
        raise HTTPException(status_code=_error_to_http_status(err), detail=err)
    return result


@router.get("/backups")
async def db_list_backups(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """List available backup files in BACKUPS_DIR, newest-first."""
    from core.db_backup import list_backups
    entries = await list_backups()
    return {"backups": entries}
