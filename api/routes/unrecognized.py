"""
Unrecognized file endpoints.

GET /api/unrecognized         — Paginated list of unrecognized files with filters.
GET /api/unrecognized/stats   — Summary statistics by category and format.
GET /api/unrecognized/export  — CSV download of matching files.
"""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from core.auth import AuthenticatedUser, UserRole, require_role

from core.database import get_unrecognized_files, get_unrecognized_stats

router = APIRouter(prefix="/api/unrecognized", tags=["unrecognized"])


@router.get("")
async def list_unrecognized(
    job_id: str | None = None,
    category: str | None = None,
    source_format: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Return paginated unrecognized files with filter support."""
    return await get_unrecognized_files(
        job_id=job_id,
        category=category,
        source_format=source_format,
        page=page,
        per_page=per_page,
    )


@router.get("/stats")
async def unrecognized_stats(
    job_id: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Return summary statistics for unrecognized files."""
    return await get_unrecognized_stats(job_id=job_id)


@router.get("/export")
async def export_csv(
    job_id: str | None = None,
    category: str | None = None,
    source_format: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Export unrecognized files as CSV download."""
    data = await get_unrecognized_files(
        job_id=job_id,
        category=category,
        source_format=source_format,
        page=1,
        per_page=100000,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "source_path", "source_format", "mime_type", "file_category",
        "file_size_bytes", "job_id",
    ])
    for f in data["files"]:
        writer.writerow([
            f.get("source_path", ""),
            f.get("file_ext", ""),
            f.get("mime_type", ""),
            f.get("file_category", ""),
            f.get("file_size_bytes", ""),
            f.get("job_id", ""),
        ])

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="markflow-unrecognized-{today}.csv"'
        },
    )
