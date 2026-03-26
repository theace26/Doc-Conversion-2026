"""
Log file download endpoints.

GET /api/logs/download/{filename} — download markflow.log or markflow-debug.log.
Requires MANAGER role. Whitelist-only filenames.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.auth import AuthenticatedUser, UserRole, require_role

router = APIRouter(prefix="/api/logs", tags=["logging"])

_ALLOWED_FILES = {"markflow.log", "markflow-debug.log"}
_logs_dir = Path(os.getenv("LOGS_DIR", "logs"))


@router.get("/download/{filename}")
async def download_log(
    filename: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Download a log file as attachment. Only whitelisted filenames allowed."""
    if filename not in _ALLOWED_FILES:
        raise HTTPException(status_code=400, detail=f"Invalid log file: '{filename}'. Allowed: {sorted(_ALLOWED_FILES)}")

    file_path = _logs_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=filename,
    )
