"""
Admin endpoints — API key management and system info.

POST   /api/admin/api-keys     — Generate a new API key (raw key returned once)
GET    /api/admin/api-keys     — List all keys (id, label, dates, active status)
DELETE /api/admin/api-keys/{id} — Revoke a key (soft delete)
GET    /api/admin/system       — System info: version, env, auth mode, Meilisearch
"""

import os
import secrets
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthenticatedUser, UserRole, require_role, hash_api_key
from core.database import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


class ApiKeyCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)


# ── POST /api/admin/api-keys ────────────────────────────────────────────────

@router.post("/api-keys")
async def generate_api_key(
    body: ApiKeyCreateRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Generate a new API key. The raw key is returned ONCE — store it immediately."""
    salt = os.getenv("API_KEY_SALT", "")
    if not salt:
        raise HTTPException(
            status_code=500,
            detail="API_KEY_SALT is not configured. Cannot generate keys.",
        )

    raw_token = secrets.token_urlsafe(32)
    raw_key = f"mf_{raw_token}"
    key_hash = hash_api_key(raw_key, salt)
    key_id = uuid.uuid4().hex

    await create_api_key(key_id, body.label, key_hash)

    log.info("admin.api_key_created", key_id=key_id, label=body.label, by=user.sub)

    return {
        "key_id": key_id,
        "label": body.label,
        "raw_key": raw_key,
        "warning": "Store this key now. It cannot be retrieved again.",
    }


# ── GET /api/admin/api-keys ─────────────────────────────────────────────────

@router.get("/api-keys")
async def get_api_keys(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """List all API keys (never returns raw key values)."""
    keys = await list_api_keys()
    return keys


# ── DELETE /api/admin/api-keys/{key_id} ─────────────────────────────────────

@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Revoke an API key (soft delete — sets is_active=false)."""
    revoked = await revoke_api_key(key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found.")

    log.info("admin.api_key_revoked", key_id=key_id, by=user.sub)
    return {"key_id": key_id, "status": "revoked"}


# ── GET /api/admin/system ───────────────────────────────────────────────────

@router.get("/system")
async def system_info(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """System overview: version, auth mode, Meilisearch status, DB size."""
    from core.database import DB_PATH

    dev_bypass = os.getenv("DEV_BYPASS_AUTH", "false").lower() == "true"

    # DB size
    db_size = None
    try:
        if DB_PATH.exists():
            db_size = DB_PATH.stat().st_size
    except Exception:
        pass

    # Meilisearch status
    meili_status = "unknown"
    try:
        from core.search_client import get_meili_client
        client = get_meili_client()
        if await client.health_check():
            meili_status = "ok"
        else:
            meili_status = "unavailable"
    except Exception:
        meili_status = "unavailable"

    return {
        "version": "0.9.0",
        "auth_mode": "DEV_BYPASS" if dev_bypass else "JWT",
        "dev_bypass_active": dev_bypass,
        "meilisearch_status": meili_status,
        "db_size_bytes": db_size,
        "unioncore_origin": os.getenv("UNIONCORE_ORIGIN", ""),
    }
