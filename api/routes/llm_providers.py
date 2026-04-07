"""
LLM provider management API.

GET    /api/llm-providers               — List all providers (API keys masked)
GET    /api/llm-providers/registry       — Provider registry for frontend dropdowns
GET    /api/llm-providers/ollama-models  — Fetch models from Ollama server
POST   /api/llm-providers               — Create provider
PUT    /api/llm-providers/{id}           — Update provider
DELETE /api/llm-providers/{id}           — Delete provider
POST   /api/llm-providers/{id}/verify    — Verify saved provider
POST   /api/llm-providers/verify-draft   — Verify unsaved provider config
POST   /api/llm-providers/{id}/activate  — Set as active provider
POST   /api/llm-providers/{id}/use-for-ai-assist — Opt this provider in for AI Assist
"""

from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthenticatedUser, UserRole, require_role
from pydantic import BaseModel, Field

from core.database import (
    create_llm_provider,
    delete_llm_provider,
    get_active_provider,
    get_ai_assist_provider,
    get_llm_provider,
    list_llm_providers,
    set_active_provider,
    set_ai_assist_provider,
    update_llm_provider,
)
from core.llm_client import LLMClient
from core.llm_providers import PROVIDER_REGISTRY

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/llm-providers", tags=["llm-providers"])


# ── Request models ────────────────────────────────────────────────────────────

class CreateProviderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(..., pattern="^(anthropic|openai|gemini|ollama|custom)$")
    model: str = Field(..., min_length=1)
    api_key: str | None = None
    api_base_url: str | None = None
    use_for_ai_assist: bool | None = None  # v0.22.11


class UpdateProviderRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    use_for_ai_assist: bool | None = None  # v0.22.11


class VerifyDraftRequest(BaseModel):
    provider: str = Field(..., pattern="^(anthropic|openai|gemini|ollama|custom)$")
    model: str = Field(..., min_length=1)
    api_key: str | None = None
    api_base_url: str | None = None


# ── GET /api/llm-providers ──────────────────────────────────────────────────

@router.get("")
async def get_providers(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """List all providers (API keys masked)."""
    providers = await list_llm_providers()
    return {"providers": providers}


# ── GET /api/llm-providers/registry ─────────────────────────────────────────

@router.get("/registry")
async def get_registry(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Return the provider registry for frontend dropdowns."""
    return {"registry": PROVIDER_REGISTRY}


# ── GET /api/llm-providers/ollama-models ────────────────────────────────────

@router.get("/ollama-models")
async def get_ollama_models(
    base_url: str = "http://localhost:11434",
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Fetch available models from an Ollama server."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code != 200:
                return {"models": [], "error": f"Ollama returned {resp.status_code}"}
            data = resp.json()
            models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
            # Deduplicate
            models = sorted(set(models))
            return {"models": models}
    except httpx.ConnectError:
        return {"models": [], "error": f"Cannot reach Ollama at {base_url}"}
    except Exception as exc:
        return {"models": [], "error": str(exc)}


# ── POST /api/llm-providers ──────────────────────────────────────────────────

@router.post("")
async def create_provider(
    req: CreateProviderRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Create a new LLM provider."""
    try:
        provider_id = await create_llm_provider(
            name=req.name,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
            api_base_url=req.api_base_url,
        )
        # If the create request asked to use this provider for AI Assist,
        # opt it in (mutually exclusive — clears the flag on others).
        if req.use_for_ai_assist:
            await set_ai_assist_provider(provider_id)
        return {"id": provider_id, "name": req.name}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail=f"Provider name already exists: {req.name}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── PUT /api/llm-providers/{id} ────────────────────────────────────────────

@router.put("/{provider_id}")
async def update_provider(
    provider_id: str,
    req: UpdateProviderRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Update a provider."""
    existing = await get_llm_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider not found.")

    fields = {}
    if req.name is not None:
        fields["name"] = req.name
    if req.model is not None:
        fields["model"] = req.model
    if req.api_key is not None:
        fields["api_key"] = req.api_key
    if req.api_base_url is not None:
        fields["api_base_url"] = req.api_base_url

    if fields:
        await update_llm_provider(provider_id, **fields)

    # The AI Assist opt-in flag is mutually exclusive across providers, so
    # it's handled separately via set_ai_assist_provider() (which clears
    # the flag on every other row in the same transaction). Setting it
    # via update_llm_provider() with use_for_ai_assist would not clear the
    # flag elsewhere and could leave two rows opted in at once.
    updated_keys = list(fields.keys())
    if req.use_for_ai_assist is not None:
        if req.use_for_ai_assist:
            await set_ai_assist_provider(provider_id)
        else:
            # Only clear if THIS provider is currently the opted-in one.
            current = await get_ai_assist_provider()
            if current and current.get("id") == provider_id:
                await set_ai_assist_provider(None)
        updated_keys.append("use_for_ai_assist")

    return {"id": provider_id, "updated": updated_keys}


# ── DELETE /api/llm-providers/{id} ──────────────────────────────────────────

@router.delete("/{provider_id}")
async def remove_provider(
    provider_id: str,
    force: bool = False,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Delete a provider. Returns 409 if active and force=false."""
    existing = await get_llm_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider not found.")

    if existing.get("is_active") and not force:
        raise HTTPException(
            status_code=409,
            detail="This is the active provider. Add ?force=true to delete anyway.",
        )

    await delete_llm_provider(provider_id)
    return {"deleted": provider_id}


# ── POST /api/llm-providers/{id}/verify ─────────────────────────────────────

@router.post("/{provider_id}/verify")
async def verify_provider(
    provider_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Verify a saved provider's connectivity."""
    config = await get_llm_provider(provider_id)
    if not config:
        raise HTTPException(status_code=404, detail="Provider not found.")

    client = LLMClient(config)
    success, message = await client.ping()

    now = datetime.now(timezone.utc).isoformat()
    await update_llm_provider(
        provider_id,
        is_verified=1 if success else 0,
        last_verified=now,
    )

    # On successful verification, re-queue failed analysis items
    # These likely failed due to the provider being unconfigured/unverified
    requeued = 0
    if success:
        try:
            from core.database import get_db
            async with get_db() as conn:
                cursor = await conn.execute(
                    "UPDATE analysis_queue SET status = 'pending', retry_count = 0 "
                    "WHERE status = 'failed'"
                )
                requeued = cursor.rowcount
                await conn.commit()
            if requeued:
                log.info("provider_verify.requeued_failed_analysis",
                         provider_id=provider_id, requeued=requeued)
        except Exception as exc:
            log.warning("provider_verify.requeue_failed", error=str(exc))

    return {
        "success": success,
        "provider": config["provider"],
        "model": config["model"],
        "message": message,
        "verified_at": now,
        "requeued_analysis": requeued,
    }


# ── POST /api/llm-providers/verify-draft ───────────────────────────────────

@router.post("/verify-draft")
async def verify_draft(
    req: VerifyDraftRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Verify an unsaved provider config."""
    config = {
        "provider": req.provider,
        "model": req.model,
        "api_key": req.api_key or "",
        "api_base_url": req.api_base_url or "",
    }
    client = LLMClient(config)
    success, message = await client.ping()

    return {
        "success": success,
        "provider": req.provider,
        "model": req.model,
        "message": message,
    }


# ── POST /api/llm-providers/{id}/activate ──────────────────────────────────

@router.post("/{provider_id}/activate")
async def activate_provider(
    provider_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Set a provider as the active one (deactivates all others)."""
    existing = await get_llm_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider not found.")

    await set_active_provider(provider_id)
    return {"active": provider_id, "name": existing["name"]}


# ── POST /api/llm-providers/{id}/use-for-ai-assist ─────────────────────────

@router.post("/{provider_id}/use-for-ai-assist")
async def use_for_ai_assist(
    provider_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """
    Mark this provider as the one AI Assist will use (mutually exclusive
    across providers — clears the flag on all others). Independent of the
    `is_active` flag used by the image scanner.

    Pass `provider_id="none"` to clear the AI Assist opt-in entirely
    (disables AI Assist provider routing; falls back to active provider
    if any).
    """
    if provider_id == "none":
        await set_ai_assist_provider(None)
        return {"ai_assist_provider": None}

    existing = await get_llm_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider not found.")

    await set_ai_assist_provider(provider_id)
    return {"ai_assist_provider": provider_id, "name": existing["name"]}
