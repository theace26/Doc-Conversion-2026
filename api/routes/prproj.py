"""Premiere Pro project (.prproj) cross-reference API.

Public surface (auth: OPERATOR+ for reads):

    GET  /api/prproj/references?path=<media_path>   -> list of projects
    GET  /api/prproj/{project_id}/media             -> list of media refs
    GET  /api/prproj/stats                          -> aggregate counts

External integrators (e.g. asset-management dashboards) can hit these
endpoints with the same JWT or X-API-Key used elsewhere in MarkFlow.

Author: v0.34.0 Phase 2.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthenticatedUser, UserRole, require_role
from core.db.prproj_refs import (
    get_media_for_project,
    get_projects_referencing,
    stats,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/prproj", tags=["prproj"])


@router.get("/references")
async def references(
    path: str = Query(..., description="Absolute path of a media file"),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Reverse lookup: which Premiere projects reference the given media path?

    Returns ``{"media_path": <path>, "projects": [...]}`` where each
    project entry includes ``project_id``, ``project_path``,
    ``media_name``, ``media_type``, and ``recorded_at``.

    Empty ``projects`` list (HTTP 200) when no project references the
    media path — distinguishable from an HTTP 404 which is reserved for
    routing errors.
    """
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="path query param required")
    rows = await get_projects_referencing(path.strip())
    return {"media_path": path, "projects": rows, "count": len(rows)}


@router.get("/{project_id}/media")
async def project_media(
    project_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Forward lookup: what media does this project reference?

    ``project_id`` is the ``bulk_files.id`` of an indexed ``.prproj``.
    Returns ``{"project_id": <id>, "media": [...], "count": N}``.

    Note: an empty ``media`` list (HTTP 200) means either (a) the project
    has been parsed but has no media, or (b) the project hasn't been
    parsed yet. The /references endpoint and Markdown output let the
    caller distinguish.
    """
    rows = await get_media_for_project(project_id)
    return {"project_id": project_id, "media": rows, "count": len(rows)}


@router.get("/stats")
async def cross_ref_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Aggregate stats across the cross-reference table.

    Returns ``{"n_projects": N, "n_media_refs": M, "top_5_most_referenced": [...]}``.
    Useful for dashboards / monitoring drift.
    """
    s = await stats()
    return s
