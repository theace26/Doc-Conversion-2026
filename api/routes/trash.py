"""
Trash management API endpoints.

GET    /api/trash                      — list trashed files
POST   /api/trash/{id}/restore         — restore a file from trash
DELETE /api/trash/{id}                 — purge immediately
POST   /api/trash/empty                — purge all trashed files
POST   /api/trash/restore-all          — restore all trashed files
"""

from datetime import datetime, timedelta, timezone

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from core.auth import AuthenticatedUser, UserRole, require_role

from api.models import TrashRecord
from core.database import (
    db_fetch_all,
    db_fetch_one,
    get_source_files_by_lifecycle_status,
    get_preference,
)

router = APIRouter(prefix="/api/trash", tags=["trash"])


def _parse_dt(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _to_trash_record(row: dict, retention_days: int = 60) -> TrashRecord:
    moved_at = _parse_dt(row.get("moved_to_trash_at"))
    purge_at = moved_at + timedelta(days=retention_days) if moved_at else None
    now = datetime.now(timezone.utc)
    days_remaining = max(0, (purge_at - now).days) if purge_at else 0

    return TrashRecord(
        id=row["id"],
        source_path=row.get("source_path", ""),
        moved_to_trash_at=row.get("moved_to_trash_at"),
        purge_at=purge_at.isoformat() if purge_at else None,
        days_remaining=days_remaining,
        file_format=row.get("file_ext"),
        size_at_version=row.get("file_size_bytes"),
    )


# POST /api/trash/empty must come BEFORE /{bulk_file_id}/restore
@router.post("/empty")
async def empty_trash(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Purge all trashed files. Batched DB operations, runs in background."""
    from core.lifecycle_manager import purge_all_trash, get_empty_trash_status

    status = get_empty_trash_status()
    if status["running"]:
        return {"status": "already_running", "progress": status}

    source_files = await get_source_files_by_lifecycle_status("in_trash")
    total = len(source_files)

    if total == 0:
        return {"status": "done", "purged_count": 0}

    # Fire and forget — returns immediately, purge runs in background
    asyncio.create_task(purge_all_trash())
    return {"status": "started", "total": total}


@router.get("/empty/status")
async def empty_trash_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Poll progress of a running empty-trash operation."""
    from core.lifecycle_manager import get_empty_trash_status
    return get_empty_trash_status()


@router.post("/restore-all")
async def restore_all_trash(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Restore all trashed files. Runs in background."""
    from core.lifecycle_manager import restore_all_trash, get_restore_all_status

    status = get_restore_all_status()
    if status["running"]:
        return {"status": "already_running", "progress": status}

    source_files = await get_source_files_by_lifecycle_status("in_trash")
    total = len(source_files)
    if total == 0:
        return {"status": "done", "restored_count": 0}

    asyncio.create_task(restore_all_trash())
    return {"status": "started", "total": total}


@router.get("/restore-all/status")
async def restore_all_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Poll progress of restore-all operation."""
    from core.lifecycle_manager import get_restore_all_status
    return get_restore_all_status()


@router.get("")
async def list_trash(
    page: int = 1,
    per_page: int = 25,
    sort: str = "moved_to_trash_at",
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """List all files currently in trash."""
    retention_str = await get_preference("lifecycle_trash_retention_days")
    retention_days = int(retention_str) if retention_str else 60

    files = await get_source_files_by_lifecycle_status("in_trash")

    # Sort
    if sort == "path":
        files.sort(key=lambda f: f.get("source_path", ""))
    else:
        files.sort(key=lambda f: f.get("moved_to_trash_at", ""), reverse=True)

    total = len(files)
    start = (page - 1) * per_page
    end = start + per_page
    page_files = files[start:end]

    records = [_to_trash_record(f, retention_days) for f in page_files]
    return {
        "files": [r.model_dump() for r in records],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/{bulk_file_id}/restore")
async def restore_from_trash(
    bulk_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Restore a file from trash back to active."""
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (bulk_file_id,))
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    if row.get("lifecycle_status") not in ("in_trash", "marked_for_deletion"):
        raise HTTPException(status_code=400, detail="File is not in trash or marked for deletion")

    from core.lifecycle_manager import restore_file
    await restore_file(bulk_file_id, scan_run_id="manual_restore")
    return {"success": True, "message": "File restored"}


@router.delete("/{bulk_file_id}")
async def purge_single(
    bulk_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Immediately purge a file from trash."""
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (bulk_file_id,))
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    if row.get("lifecycle_status") != "in_trash":
        raise HTTPException(status_code=400, detail="File is not in trash")

    from core.lifecycle_manager import purge_file
    await purge_file(bulk_file_id)
    return {"success": True, "message": "File purged"}
