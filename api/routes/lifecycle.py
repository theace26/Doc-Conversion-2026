"""
Version history and diff API endpoints.

GET /api/lifecycle/files/{id}/versions      — version list (newest first)
GET /api/lifecycle/files/{id}/versions/{n}  — single version with full diff
GET /api/lifecycle/files/{id}/diff/{v1}/{v2} — diff between two versions
"""

import json

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthenticatedUser, UserRole, require_role

from api.models import DiffResponse, VersionListResponse, VersionRecord
from core.database import get_version, get_version_history

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


def _row_to_version(row: dict, include_patch: bool = False) -> VersionRecord:
    """Convert a DB row to a VersionRecord."""
    summary = None
    if row.get("diff_summary"):
        try:
            summary = json.loads(row["diff_summary"])
        except (json.JSONDecodeError, TypeError):
            summary = [row["diff_summary"]]

    return VersionRecord(
        id=row["id"],
        bulk_file_id=row["bulk_file_id"],
        version_number=row["version_number"],
        recorded_at=row.get("recorded_at", ""),
        change_type=row["change_type"],
        path_at_version=row["path_at_version"],
        size_at_version=row.get("size_at_version"),
        content_hash=row.get("content_hash"),
        diff_summary=summary,
        diff_truncated=bool(row.get("diff_truncated", 0)),
        scan_run_id=row.get("scan_run_id"),
        notes=row.get("notes"),
    )


@router.get("/files/{bulk_file_id}/versions")
async def list_versions(
    bulk_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> VersionListResponse:
    """List all versions for a file, newest first."""
    versions = await get_version_history(bulk_file_id)
    records = [_row_to_version(v) for v in versions]
    return VersionListResponse(
        file_id=bulk_file_id,
        versions=records,
        total=len(records),
    )


@router.get("/files/{bulk_file_id}/versions/{version_number}")
async def get_single_version(
    bulk_file_id: str,
    version_number: int,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Get a single version with full diff_patch included."""
    row = await get_version(bulk_file_id, version_number)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")

    record = _row_to_version(row, include_patch=True)
    result = record.model_dump()
    result["diff_patch"] = row.get("diff_patch")
    return result


@router.get("/files/{bulk_file_id}/diff/{v1}/{v2}")
async def diff_versions(
    bulk_file_id: str,
    v1: int,
    v2: int,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> DiffResponse:
    """Compute diff between two versions."""
    ver1 = await get_version(bulk_file_id, v1)
    ver2 = await get_version(bulk_file_id, v2)

    if not ver1:
        raise HTTPException(status_code=404, detail=f"Version {v1} not found")
    if not ver2:
        raise HTTPException(status_code=404, detail=f"Version {v2} not found")

    rec1 = _row_to_version(ver1)
    rec2 = _row_to_version(ver2)

    # Use stored diff if available on the later version
    later = ver2 if v2 > v1 else ver1
    summary: list[str] = []
    patch: str | None = None
    patch_truncated = False
    lines_added = 0
    lines_removed = 0

    if later.get("diff_summary"):
        try:
            summary = json.loads(later["diff_summary"])
        except (json.JSONDecodeError, TypeError):
            summary = []
        patch = later.get("diff_patch")
        patch_truncated = bool(later.get("diff_truncated", 0))
    else:
        summary = [f"Version {v1} -> {v2}: {later.get('change_type', 'unknown')} change"]

    return DiffResponse(
        summary=summary,
        patch=patch,
        patch_truncated=patch_truncated,
        lines_added=lines_added,
        lines_removed=lines_removed,
        v1=rec1,
        v2=rec2,
    )
