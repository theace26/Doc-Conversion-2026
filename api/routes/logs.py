"""
Log file download endpoints.

GET /api/logs/download/{filename} — download markflow.log or markflow-debug.log.
Requires MANAGER role. Whitelist-only filenames.

Size guard: refuses to serve files larger than 500 MB (configurable via
LOG_DOWNLOAD_MAX_MB env var). With size-based rotation enabled in logging_config,
individual log files should stay well under this limit.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.auth import AuthenticatedUser, UserRole, require_role

router = APIRouter(prefix="/api/logs", tags=["logging"])

_ALLOWED_FILES = {"markflow.log", "markflow-debug.log"}
_logs_dir = Path(os.getenv("LOGS_DIR", "logs"))
_DOWNLOAD_MAX_BYTES = int(os.getenv("LOG_DOWNLOAD_MAX_MB", "500")) * 1024 * 1024


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

    file_size = file_path.stat().st_size

    if file_size > _DOWNLOAD_MAX_BYTES:
        size_mb = file_size // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=(
                f"Log file is {size_mb} MB — too large to download. "
                f"Log rotation has been enabled; rotated files will be smaller. "
                f"Access the log directly in the container at /app/{file_path}"
            ),
        )

    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Length": str(file_size)},
    )
