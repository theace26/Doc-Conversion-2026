"""
Flag API endpoints — file flagging & content moderation.

POST   /api/flags                         -- Flag a file
GET    /api/flags/mine                    -- List caller's active flags
GET    /api/flags/lookup-source           -- Look up source_file_id from path
GET    /api/flags/stats                   -- Flag counts by status (admin)
GET    /api/flags/blocklist               -- Paginated blocklist (admin)
GET    /api/flags                         -- List all flags with filters (admin)
DELETE /api/flags/blocklist/{blocklist_id} -- Remove from blocklist (admin)
DELETE /api/flags/{flag_id}               -- Retract own flag
GET    /api/flags/{flag_id}               -- Single flag detail (admin)
PUT    /api/flags/{flag_id}/dismiss       -- Dismiss flag (admin)
PUT    /api/flags/{flag_id}/extend        -- Extend flag expiry (admin)
PUT    /api/flags/{flag_id}/remove        -- Remove file + blocklist (admin)
"""

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import db_fetch_one
from core import flag_manager

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/flags", tags=["flags"])


# ── 1. POST /api/flags — Flag a file ────────────────────────────────────────

@router.post("")
async def create_flag(
    body: dict = Body(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
) -> dict:
    """Flag a source file for review."""
    source_file_id = body.get("source_file_id")
    reason = body.get("reason")
    note = body.get("note", "")

    if not source_file_id or not reason:
        raise HTTPException(400, "source_file_id and reason are required")

    try:
        flag = await flag_manager.create_flag(
            source_file_id=source_file_id,
            reason=reason,
            flagged_by_sub=user.sub,
            flagged_by_email=user.email,
            note=note,
            role=user.role.value,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return {"ok": True, "flag": flag}


# ── 2. GET /api/flags/mine — Caller's active flags ──────────────────────────

@router.get("/mine")
async def my_flags(
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
) -> dict:
    """List the caller's active flags."""
    flags = await flag_manager.get_my_flags(user.sub)
    return {"ok": True, "flags": flags}


# ── 3. GET /api/flags/lookup-source — Path → source_file_id ─────────────────

@router.get("/lookup-source")
async def lookup_source(
    source_path: str = Query(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
) -> dict:
    """Look up a source_file_id from a source_path."""
    row = await db_fetch_one(
        "SELECT id FROM source_files WHERE source_path = ?", (source_path,)
    )
    if not row:
        raise HTTPException(404, f"No source file found for path: {source_path}")
    return {"source_file_id": row["id"]}


# ── 4. GET /api/flags/stats — Flag counts by status (admin) ─────────────────

@router.get("/stats")
async def flag_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Return flag counts grouped by status."""
    stats = await flag_manager.get_flag_stats()
    return {"ok": True, "stats": stats}


# ── 5. GET /api/flags/blocklist — Paginated blocklist (admin) ────────────────

@router.get("/blocklist")
async def get_blocklist(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=5, le=100),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Return the paginated blocklist."""
    result = await flag_manager.get_blocklist(page=page, per_page=per_page)
    return {"ok": True, **result}


# ── 6. GET /api/flags — List all flags with filters (admin) ─────────────────

@router.get("")
async def list_flags(
    status: str | None = Query(None),
    flagged_by: str | None = Query(None),
    reason: str | None = Query(None),
    path_prefix: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    sort_by: str = Query("expires_at"),
    sort_dir: str = Query("asc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=5, le=100),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """List all flags with optional filters, sorting, and pagination."""
    result = await flag_manager.list_flags(
        status=status,
        flagged_by=flagged_by,
        reason=reason,
        path_prefix=path_prefix,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        per_page=per_page,
    )
    return {"ok": True, **result}


# ── 7. DELETE /api/flags/blocklist/{blocklist_id} — Remove from blocklist ────

@router.delete("/blocklist/{blocklist_id}")
async def remove_from_blocklist(
    blocklist_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Remove an entry from the blocklist."""
    removed = await flag_manager.remove_from_blocklist(blocklist_id)
    if not removed:
        raise HTTPException(404, f"Blocklist entry {blocklist_id} not found")
    log.info("blocklist_entry_removed", blocklist_id=blocklist_id, admin=user.email)
    return {"ok": True}


# ── 8. DELETE /api/flags/{flag_id} — Retract own flag ───────────────────────

@router.delete("/{flag_id}")
async def retract_flag(
    flag_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
) -> dict:
    """Retract a flag (only the original flagger can retract)."""
    try:
        flag = await flag_manager.retract_flag(flag_id, user.sub)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return {"ok": True, "flag": flag}


# ── 9. GET /api/flags/{flag_id} — Single flag detail (admin) ────────────────

@router.get("/{flag_id}")
async def get_flag(
    flag_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Return a single flag by ID."""
    flag = await flag_manager.get_flag(flag_id)
    if not flag:
        raise HTTPException(404, f"Flag {flag_id} not found")
    return {"ok": True, "flag": flag}


# ── 10. PUT /api/flags/{flag_id}/dismiss — Dismiss flag (admin) ─────────────

@router.put("/{flag_id}/dismiss")
async def dismiss_flag(
    flag_id: str,
    body: dict = Body(default={}),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Dismiss a flag (admin resolution)."""
    try:
        flag = await flag_manager.dismiss_flag(
            flag_id=flag_id,
            admin_email=user.email,
            resolution_note=body.get("resolution_note", ""),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, "flag": flag}


# ── 11. PUT /api/flags/{flag_id}/extend — Extend flag expiry (admin) ────────

@router.put("/{flag_id}/extend")
async def extend_flag(
    flag_id: str,
    body: dict = Body(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Extend a flag's expiry period (admin action)."""
    days = body.get("days")
    if days is None:
        raise HTTPException(400, "'days' is required")

    try:
        flag = await flag_manager.extend_flag(
            flag_id=flag_id,
            days=int(days),
            admin_email=user.email,
            resolution_note=body.get("resolution_note", ""),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, "flag": flag}


# ── 12. PUT /api/flags/{flag_id}/remove — Remove + blocklist (admin) ────────

@router.put("/{flag_id}/remove")
async def remove_and_blocklist(
    flag_id: str,
    body: dict = Body(default={}),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Remove the flagged file and add it to the blocklist (admin action)."""
    try:
        result = await flag_manager.remove_and_blocklist(
            flag_id=flag_id,
            admin_email=user.email,
            resolution_note=body.get("resolution_note", ""),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, **result}
