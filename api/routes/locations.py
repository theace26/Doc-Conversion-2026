"""
Named Locations API — CRUD for friendly path aliases used in bulk jobs.

GET    /api/locations               — List all (optionally filter by type)
POST   /api/locations               — Create a location
GET    /api/locations/validate      — Check if a container path is accessible
GET    /api/locations/{id}          — Get single location
PUT    /api/locations/{id}          — Update a location
DELETE /api/locations/{id}          — Delete a location
"""

import asyncio
import os
import re
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.models import LocationCreate, LocationResponse, LocationUpdate
from core.database import (
    create_location,
    delete_location,
    get_location,
    list_locations,
    update_location,
    db_fetch_all,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/locations", tags=["locations"])

_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:\\")


def _is_windows_path(p: str) -> bool:
    return bool(_WINDOWS_PATH_RE.match(p))


def _validate_path(path: str) -> None:
    """Raise HTTPException if path is not a valid container path."""
    if _is_windows_path(path):
        raise HTTPException(
            status_code=422,
            detail="Path must be a container path starting with /. "
                   "Windows paths like C:\\ are not valid here.",
        )
    if not path.startswith("/"):
        raise HTTPException(
            status_code=422,
            detail="Path must be an absolute container path starting with /.",
        )


# ── GET /api/locations ───────────────────────────────────────────────────────

@router.get("")
async def list_all(type: str | None = Query(default=None)):
    """List locations, optionally filtered by type (source, output, both)."""
    locations = await list_locations(type_filter=type)
    return locations


# ── POST /api/locations ──────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create(body: LocationCreate):
    """Create a new named location."""
    _validate_path(body.path)

    try:
        loc_id = await create_location(
            name=body.name,
            path=body.path,
            type_=body.type,
            notes=body.notes,
        )
    except ValueError:
        raise HTTPException(status_code=409, detail=f"Location name already exists: {body.name}")

    loc = await get_location(loc_id)
    return loc


# ── GET /api/locations/validate — must be before /{id} ───────────────────────

@router.get("/validate")
async def validate_path(path: str = Query(...)):
    """Check if a container path is accessible."""
    if _is_windows_path(path) or not path.startswith("/"):
        return {"path": path, "accessible": False, "error": "not_a_container_path"}

    p = Path(path)
    exists = p.exists()
    if not exists:
        return {
            "path": path,
            "accessible": False,
            "exists": False,
            "readable": False,
            "writable": False,
            "file_count_estimate": None,
        }

    readable = False
    try:
        os.listdir(path)
        readable = True
    except (PermissionError, OSError):
        pass

    writable = False
    try:
        test_file = p / ".markflow_write_test"
        test_file.touch()
        test_file.unlink()
        writable = True
    except (PermissionError, OSError):
        pass

    file_count = None
    if readable:
        try:
            def _count():
                return sum(1 for f in p.rglob("*") if f.is_file())

            file_count = await asyncio.wait_for(
                asyncio.to_thread(_count), timeout=10.0
            )
        except (asyncio.TimeoutError, OSError):
            file_count = None

    return {
        "path": path,
        "accessible": readable,
        "exists": True,
        "readable": readable,
        "writable": writable,
        "file_count_estimate": file_count,
    }


# ── GET /api/locations/{id} ─────────────────────────────────────────────────

@router.get("/{location_id}")
async def get_single(location_id: str):
    """Get a single location by ID."""
    loc = await get_location(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found.")
    return loc


# ── PUT /api/locations/{id} ─────────────────────────────────────────────────

@router.put("/{location_id}")
async def update(location_id: str, body: LocationUpdate):
    """Update a location."""
    loc = await get_location(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found.")

    fields = body.model_dump(exclude_none=True)
    if not fields:
        return loc

    if "path" in fields:
        _validate_path(fields["path"])

    # Remap 'type' field name to avoid SQL keyword issues
    if "type" in fields:
        fields["type"] = fields["type"]  # keep as-is, column is named 'type'

    try:
        await update_location(location_id, **fields)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail=f"Location name already exists: {fields.get('name')}",
        )

    return await get_location(location_id)


# ── DELETE /api/locations/{id} ──────────────────────────────────────────────

@router.delete("/{location_id}", status_code=204)
async def delete(location_id: str, force: bool = Query(default=False)):
    """Delete a location. Returns 409 if in use by bulk jobs (unless force=true)."""
    loc = await get_location(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found.")

    if not force:
        # Check if any bulk jobs reference this location's path
        jobs = await db_fetch_all(
            "SELECT id FROM bulk_jobs WHERE source_path = ? OR output_path = ?",
            (loc["path"], loc["path"]),
        )
        if jobs:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "location_in_use",
                    "message": f"This location is used by {len(jobs)} bulk job(s). "
                               "Delete those jobs first or remove this location anyway.",
                    "job_count": len(jobs),
                    "force_url": f"/api/locations/{location_id}?force=true",
                },
            )

    await delete_location(location_id)
