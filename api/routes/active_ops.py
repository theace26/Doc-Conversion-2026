"""Active Operations Registry — HTTP API (v0.35.0).

Spec: docs/superpowers/specs/2026-04-28-active-operations-registry-design.md

Endpoints:
    GET  /api/active-ops                  — running + finished-within-30s
    POST /api/active-ops/{op_id}/cancel   — operator-triggered cancel
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response

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
    response.headers["Cache-Control"] = "no-cache"
    return {"ops": [op.to_api_dict() for op in ops]}


@router.post("/{op_id}/cancel")
async def cancel_active_op(
    op_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Cancel a running op. 404 if op_id unknown, 400 if op already
    finished or op_type uncancellable."""
    op = await active_ops.get_op(op_id)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Unknown op_id: {op_id}")
    if op.finished_at_epoch is not None:
        raise HTTPException(
            status_code=400,
            detail="Operation already finished — cancel ignored.",
        )
    if not op.cancellable:
        raise HTTPException(
            status_code=400,
            detail=f"Operation type {op.op_type!r} is uncancellable.",
        )

    cancelled = await active_ops.cancel_op(op_id)
    log.info(
        "active_ops.cancel_requested",
        op_id=op_id, op_type=op.op_type, by=user.email, success=cancelled,
    )
    return {
        "cancelled": cancelled,
        "message": (
            "Cancel signal sent. Operation will stop within "
            "the next progress tick."
            if cancelled else
            "Cancel hook failed — see error_msg on the op."
        ),
    }
