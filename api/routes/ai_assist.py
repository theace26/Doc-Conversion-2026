"""
AI-assisted search endpoints.
POST /api/ai-assist/search       — stream synthesis over search result snippets
POST /api/ai-assist/expand       — stream deep analysis of a single document
GET  /api/ai-assist/status       — whether AI Assist is configured + enabled
PUT  /api/ai-assist/admin/toggle — admin: enable/disable org-wide
GET  /api/ai-assist/admin/usage  — admin: usage log + per-user totals
"""
import os

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any

from core.ai_assist import stream_search_synthesis, stream_document_expand
from core.auth import AuthenticatedUser, UserRole, get_current_user, require_role
from core.db.connection import db_fetch_one
from core.db.ai_usage import (
    get_ai_assist_enabled,
    set_ai_assist_enabled,
    log_ai_usage,
    get_usage_summary,
    get_usage_by_user,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/ai-assist", tags=["ai-assist"])


class SearchSynthesisRequest(BaseModel):
    query: str
    results: list[dict[str, Any]]


class ExpandRequest(BaseModel):
    query: str
    doc_id: str


class AIAssistToggleRequest(BaseModel):
    enabled: bool


def _api_key_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


# ── Search synthesis ─────────────────────────────────────────────────────────

@router.post("/search")
async def ai_search_synthesis(
    req: SearchSynthesisRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Stream a Claude-synthesized answer grounded in the provided search snippets.
    Returns text/event-stream with JSON events:
      {"type": "chunk",   "text": "..."}
      {"type": "sources", "sources": [...]}
      {"type": "done"}
      {"type": "error",   "message": "..."}
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    if not req.results:
        raise HTTPException(status_code=400, detail="results list is empty")

    if not await get_ai_assist_enabled():
        raise HTTPException(
            status_code=503,
            detail="AI Assist is disabled. An administrator can enable it in Settings.",
        )

    async def _on_complete(input_tokens_est: int, output_tokens_est: int):
        await log_ai_usage(
            user_id=user.sub,
            username=user.email,
            query=req.query,
            mode="search",
            result_count=len(req.results),
            input_tokens_est=input_tokens_est,
            output_tokens_est=output_tokens_est,
        )

    return StreamingResponse(
        stream_search_synthesis(req.query, req.results, on_complete=_on_complete),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Document expand ──────────────────────────────────────────────────────────

@router.post("/expand")
async def ai_expand_document(
    req: ExpandRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Stream a deep analysis of a single document.
    Reads the converted markdown from the source_files table output_path.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    if not req.doc_id.strip():
        raise HTTPException(status_code=400, detail="doc_id is required")

    if not await get_ai_assist_enabled():
        raise HTTPException(
            status_code=503,
            detail="AI Assist is disabled. An administrator can enable it in Settings.",
        )

    row = await db_fetch_one(
        "SELECT output_path FROM source_files WHERE id = ?",
        (req.doc_id,),
    )

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    if not row.get("output_path"):
        raise HTTPException(
            status_code=404, detail="No converted markdown available for this document"
        )

    output_path = row["output_path"]

    try:
        with open(output_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Markdown file not found at {output_path}"
        )

    async def _on_complete(input_tokens_est: int, output_tokens_est: int):
        await log_ai_usage(
            user_id=user.sub,
            username=user.email,
            query=req.query,
            mode="expand",
            result_count=1,
            input_tokens_est=input_tokens_est,
            output_tokens_est=output_tokens_est,
        )

    return StreamingResponse(
        stream_document_expand(req.query, req.doc_id, content, on_complete=_on_complete),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Status ───────────────────────────────────────────────────────────────────

@router.get("/status")
async def ai_assist_status():
    """
    Returns whether AI Assist is both configured (API key present)
    and enabled org-wide by an admin.
    """
    key_present = _api_key_configured()
    org_enabled = await get_ai_assist_enabled() if key_present else False
    return {
        "key_configured": key_present,
        "org_enabled": org_enabled,
        "enabled": key_present and org_enabled,
    }


# ── Admin endpoints ──────────────────────────────────────────────────────────

@router.put("/admin/toggle")
async def admin_toggle_ai_assist(
    req: AIAssistToggleRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Admin only — enable or disable AI Assist org-wide."""
    await set_ai_assist_enabled(req.enabled)
    return {"enabled": req.enabled}


@router.get("/admin/usage")
async def admin_get_usage(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Admin only — usage log + per-user totals."""
    return {
        "by_user": await get_usage_by_user(),
        "recent": await get_usage_summary(limit=limit),
    }
