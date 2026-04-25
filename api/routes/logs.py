"""
Log file download and archive endpoints.

GET /api/logs/download/{filename}        — download active log file
GET /api/logs/archives                   — list compressed log archives
GET /api/logs/archives/download/{name}   — download a single .gz archive
GET /api/logs/archives/stats             — archive summary stats

Requires MANAGER role. Whitelist-only filenames for active logs;
archive downloads restricted to .gz files inside the archive directory.

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
_archive_dir = _logs_dir / "archive"
_DOWNLOAD_MAX_BYTES = int(os.getenv("LOG_DOWNLOAD_MAX_MB", "500")) * 1024 * 1024


# ── Active log download ─────────────────────────────────────────────────────

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


# ── Log archives ────────────────────────────────────────────────────────────

@router.get("/archives")
async def list_archives(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """List all compressed log archive files, newest first."""
    if not _archive_dir.exists():
        return {"archives": []}

    archives = []
    for gz_file in sorted(_archive_dir.glob("*.gz"), key=lambda f: f.stat().st_mtime, reverse=True):
        stat = gz_file.stat()
        archives.append({
            "name": gz_file.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": stat.st_mtime,
        })

    return {"archives": archives, "total": len(archives)}


@router.get("/archives/download/{name}")
async def download_archive(
    name: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Download a single compressed log archive."""
    if not name.endswith(".gz") or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid archive filename")

    file_path = _archive_dir / name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Archive not found")

    file_size = file_path.stat().st_size

    return FileResponse(
        path=str(file_path),
        media_type="application/gzip",
        filename=name,
        headers={"Content-Length": str(file_size)},
    )


@router.get("/archives/stats")
async def archive_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Return summary statistics about the log archive.

    v0.31.0: now sources from `core.log_manager` (the legacy
    `core.log_archiver` module was deleted). Retention days are
    read from DB prefs instead of env var, so the value here
    matches what the Settings page shows.
    """
    from core.log_manager import get_archive_stats
    return await get_archive_stats()
