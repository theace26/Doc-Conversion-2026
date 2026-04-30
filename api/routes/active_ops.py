"""Active Operations Registry — HTTP API (v0.35.0).

Spec: docs/superpowers/specs/2026-04-28-active-operations-registry-design.md

Endpoints:
    GET  /api/active-ops                  — running + finished-within-30s
    POST /api/active-ops/{op_id}/cancel   — operator-triggered cancel
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Response

from core import active_ops
from core.auth import AuthenticatedUser, UserRole, require_role

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/active-ops", tags=["active-ops"])


@router.get("")
async def list_active_ops(
    response: Response,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return all currently-running ops + ops finished within last 30s.

    The 30s window lets the UI keep showing a "Done" state briefly
    after completion, so the operator gets visual confirmation."""
    ops = await active_ops.list_ops()
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return {"ops": [op.to_api_dict() for op in ops]}
