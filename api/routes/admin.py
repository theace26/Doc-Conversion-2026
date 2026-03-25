"""
Admin endpoints — API key management, system info, resource controls, stats.

POST   /api/admin/api-keys          — Generate a new API key (raw key returned once)
GET    /api/admin/api-keys          — List all keys (id, label, dates, active status)
DELETE /api/admin/api-keys/{id}     — Revoke a key (soft delete)
GET    /api/admin/system            — System info: version, env, auth mode, Meilisearch
PUT    /api/admin/resources         — Apply CPU affinity, worker count, process priority
GET    /api/admin/system/metrics    — Live CPU/memory/thread metrics
GET    /api/admin/stats             — Aggregated repository statistics dashboard
"""

import asyncio
import json
import os
import secrets
import uuid
from datetime import datetime, timezone

import psutil
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthenticatedUser, UserRole, require_role, hash_api_key
from core.database import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    db_fetch_all,
    db_fetch_one,
    set_preference,
)
from core.resource_manager import (
    apply_affinity,
    apply_priority,
    get_cpu_info_cached,
    get_live_metrics,
)
from core.stop_controller import (
    get_stop_state,
    request_stop,
    reset_stop,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


class ApiKeyCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)


class ResourceSettingsUpdate(BaseModel):
    cpu_affinity_cores: list[int] | None = None
    process_priority: str | None = None
    worker_count: int | None = None


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
        "version": "0.9.2",
        "auth_mode": "DEV_BYPASS" if dev_bypass else "JWT",
        "dev_bypass_active": dev_bypass,
        "meilisearch_status": meili_status,
        "db_size_bytes": db_size,
        "unioncore_origin": os.getenv("UNIONCORE_ORIGIN", ""),
    }


# ── PUT /api/admin/resources ────────────────────────────────────────────────

@router.put("/resources")
async def update_resources(
    payload: ResourceSettingsUpdate,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """
    Apply CPU affinity, worker count, and process priority.
    Changes take effect immediately. Persisted via preferences.
    Worker count change takes effect on the next bulk job start.
    CPU affinity and priority apply to the live process immediately.
    """
    applied = {}
    warnings = []

    # CPU affinity
    if payload.cpu_affinity_cores is not None:
        cpu_count = psutil.cpu_count(logical=True)
        for idx in payload.cpu_affinity_cores:
            if idx < 0 or idx >= cpu_count:
                raise HTTPException(
                    status_code=422,
                    detail=f"Core index {idx} out of range. Available: 0-{cpu_count - 1}",
                )
        ok = apply_affinity(payload.cpu_affinity_cores)
        applied["cpu_affinity"] = ok
        if not ok:
            warnings.append("CPU affinity not supported on this platform — not applied")
        await set_preference("cpu_affinity_cores", json.dumps(payload.cpu_affinity_cores))

    # Process priority
    if payload.process_priority is not None:
        if payload.process_priority not in ("low", "normal", "high"):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid priority '{payload.process_priority}'. Must be low/normal/high.",
            )
        ok = apply_priority(payload.process_priority)
        applied["process_priority"] = ok
        if not ok:
            warnings.append("Process priority change requires root — not applied")
        await set_preference("process_priority", payload.process_priority)

    # Worker count
    if payload.worker_count is not None:
        if payload.worker_count < 1 or payload.worker_count > 32:
            raise HTTPException(
                status_code=422,
                detail=f"Worker count must be 1-32, got {payload.worker_count}.",
            )
        await set_preference("worker_count", str(payload.worker_count))
        applied["worker_count"] = True

    log.info("admin.resources_updated", applied=applied, by=user.sub)
    return {"applied": applied, "warnings": warnings}


# ── GET /api/admin/system/metrics ───────────────────────────────────────────

@router.get("/system/metrics")
async def system_metrics(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Live CPU/memory/thread metrics for the task manager."""
    metrics = get_live_metrics()
    metrics["cpu_info"] = get_cpu_info_cached()
    return metrics


# ── GET /api/admin/stats ────────────────────────────────────────────────────

async def _safe(coro):
    """Wrap an awaitable so exceptions return None instead of propagating."""
    try:
        return await coro
    except Exception as exc:
        log.warning("admin.stats_query_failed", error=str(exc))
        return None


async def _query_bulk_files() -> dict | None:
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) as count FROM bulk_files GROUP BY status"
    )
    by_status = {r["status"]: r["count"] for r in rows}
    total = sum(by_status.values())

    lifecycle_rows = await db_fetch_all(
        "SELECT lifecycle_status, COUNT(*) as count FROM bulk_files GROUP BY lifecycle_status"
    )
    by_lifecycle = {r["lifecycle_status"]: r["count"] for r in lifecycle_rows}

    unrecognized_rows = await db_fetch_all(
        "SELECT file_category, COUNT(*) as count FROM bulk_files "
        "WHERE status='unrecognized' GROUP BY file_category"
    )
    unrecognized_by_cat = {r["file_category"]: r["count"] for r in unrecognized_rows}

    ocr_pending = await db_fetch_one(
        "SELECT COUNT(*) as c FROM bulk_files WHERE ocr_skipped_reason='pending_review'"
    )
    ocr_skipped = await db_fetch_one(
        "SELECT COUNT(*) as c FROM bulk_files WHERE ocr_skipped_reason='permanently_skipped'"
    )
    converted_bytes = await db_fetch_one(
        "SELECT SUM(file_size) as total FROM bulk_files WHERE status='converted'"
    )

    return {
        "total": total,
        "by_status": by_status,
        "by_lifecycle": by_lifecycle,
        "unrecognized_by_category": unrecognized_by_cat,
        "ocr_review_pending": (ocr_pending or {}).get("c", 0),
        "ocr_permanently_skipped": (ocr_skipped or {}).get("c", 0),
        "total_converted_bytes": (converted_bytes or {}).get("total", 0),
    }


async def _query_conversion_history() -> dict | None:
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) as count FROM conversion_history GROUP BY status"
    )
    by_status = {r["status"]: r["count"] for r in rows}
    total = sum(by_status.values())

    format_rows = await db_fetch_all(
        "SELECT source_format, COUNT(*) as count FROM conversion_history "
        "WHERE status='success' GROUP BY source_format ORDER BY count DESC LIMIT 10"
    )
    by_format = [{"format": r["source_format"], "count": r["count"]} for r in format_rows]

    success_rate = await db_fetch_one(
        "SELECT AVG(CASE WHEN status='success' THEN 1.0 ELSE 0.0 END) * 100 "
        "as rate FROM conversion_history"
    )
    rate = (success_rate or {}).get("rate")
    if rate is not None:
        rate = round(rate, 1)

    last_24h = await db_fetch_one(
        "SELECT COUNT(*) as c FROM conversion_history "
        "WHERE created_at > datetime('now', '-24 hours')"
    )
    last_7d = await db_fetch_one(
        "SELECT COUNT(*) as c FROM conversion_history "
        "WHERE created_at > datetime('now', '-7 days')"
    )

    return {
        "total": total,
        "by_status": by_status,
        "success_rate_pct": rate,
        "by_format": by_format,
        "last_24h": (last_24h or {}).get("c", 0),
        "last_7d": (last_7d or {}).get("c", 0),
    }


async def _query_ocr_queue() -> dict | None:
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) as count FROM ocr_flags GROUP BY status"
    )
    return {r["status"]: r["count"] for r in rows}


async def _query_recent_errors() -> list | None:
    rows = await db_fetch_all(
        "SELECT source_filename as filename, source_format as format, "
        "error_message as error, created_at as at "
        "FROM conversion_history WHERE status='failed' "
        "ORDER BY created_at DESC LIMIT 10"
    )
    return [dict(r) for r in rows]


async def _query_meilisearch() -> dict:
    try:
        from core.search_client import get_meili_client
        client = get_meili_client()
        healthy = await client.health_check()
        if not healthy:
            return {"available": False, "documents_index": None, "adobe_files_index": None}

        docs_stats = await client.get_index_stats("documents")
        adobe_stats = await client.get_index_stats("adobe-files")
        return {
            "available": True,
            "documents_index": {
                "count": docs_stats.get("numberOfDocuments", 0),
                "is_indexing": docs_stats.get("isIndexing", False),
            } if docs_stats else None,
            "adobe_files_index": {
                "count": adobe_stats.get("numberOfDocuments", 0),
                "is_indexing": adobe_stats.get("isIndexing", False),
            } if adobe_stats else None,
        }
    except Exception:
        return {"available": False, "documents_index": None, "adobe_files_index": None}


async def _query_llm_providers() -> list | None:
    rows = await db_fetch_all(
        "SELECT name, provider_type as type, is_active, created_at "
        "FROM llm_providers ORDER BY is_active DESC"
    )
    return [
        {
            "name": r["name"],
            "type": r["type"],
            "active": bool(r["is_active"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ── POST /api/admin/stop-all ───────────────────────────────────────────────

@router.post("/stop-all")
async def stop_all_jobs(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Hard stop all running jobs. Workers will finish current file then exit."""
    result = request_stop(reason=f"admin_stop by {user.sub}")
    log.warning("admin_stop_all", by=user.sub, jobs=result["stopped_jobs"])
    return result


# ── POST /api/admin/reset-stop ────────────────────────────────────────────

@router.post("/reset-stop")
async def reset_stop_flag(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Clear the stop flag so new jobs can be started."""
    reset_stop()
    return {"ok": True}


# ── GET /api/admin/stop-state ─────────────────────────────────────────────

@router.get("/stop-state")
async def stop_state(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    return get_stop_state()


# ── GET /api/admin/active-jobs ────────────────────────────────────────────

@router.get("/active-jobs")
async def active_jobs(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """All currently running or recently completed jobs. Polled by global status bar."""
    from core.bulk_worker import get_all_active_jobs
    from core.lifecycle_scanner import get_scan_state

    bulk_jobs = await get_all_active_jobs()
    lifecycle = get_scan_state()
    stop = get_stop_state()

    running_count = (
        sum(1 for j in bulk_jobs if j["status"] in ("scanning", "running", "paused"))
        + (1 if lifecycle["running"] else 0)
    )

    return {
        "running_count": running_count,
        "stop_requested": stop["stop_requested"],
        "bulk_jobs": bulk_jobs,
        "lifecycle_scan": lifecycle,
    }


# ── GET /api/admin/stats ─────────────────────────────────────────────────

@router.get("/stats")
async def admin_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """
    Aggregated repository statistics for the admin dashboard.
    All queries run concurrently. If any sub-query fails, that section
    returns null — the endpoint never returns 500 due to a stats failure.
    """
    results = await asyncio.gather(
        _safe(_query_bulk_files()),
        _safe(_query_conversion_history()),
        _safe(_query_ocr_queue()),
        _safe(_query_recent_errors()),
        _safe(_query_meilisearch()),
        _safe(_query_llm_providers()),
        return_exceptions=True,
    )

    # Safely extract results — any exception becomes None
    def _get(idx):
        v = results[idx]
        if isinstance(v, BaseException):
            log.warning("admin.stats_gather_exception", idx=idx, error=str(v))
            return None
        return v

    # Scheduler status (sync, no DB)
    scheduler_status = {}
    try:
        from core.scheduler import get_scheduler_status
        scheduler_status = get_scheduler_status()
    except Exception:
        pass

    return {
        "bulk_files": _get(0),
        "conversion_history": _get(1),
        "ocr_queue": _get(2),
        "recent_errors": _get(3),
        "meilisearch": _get(4) or {"available": False},
        "llm_providers": _get(5),
        "scheduler": scheduler_status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
