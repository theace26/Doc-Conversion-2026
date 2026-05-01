"""
MarkFlow — FastAPI application entry point.

Lifespan:
  - Initializes database schema and default preferences on startup.
  - Verifies system dependencies (Tesseract, LibreOffice, Poppler, WeasyPrint).
  - Shuts down ProcessPoolExecutor cleanly.

Routes mounted:
  /api/auth         — Auth info (GET /api/auth/me)
  /api/admin        — API key management (admin only)
  /api/convert      — Upload and conversion endpoints
  /api/batch        — Batch status and download endpoints
  /api/history      — Conversion history endpoints
  /api/preferences  — User preferences endpoints
  /api/debug        — Debug dashboard
  /static           — Static HTML/CSS/JS files
  /                 — Serves home page (new UX when ENABLE_NEW_UX=true)
"""

import os
from contextlib import asynccontextmanager

from core.version import __version__

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from core.feature_flags import is_new_ux_enabled
from fastapi.staticfiles import StaticFiles

from core.database import init_db
from core.health import HealthChecker, run_health_check
from core.logging_config import configure_logging
from api.routes import convert, batch, history, preferences, review, debug as debug_routes
from api.routes import bulk, search as search_routes, cowork, locations, browse
from api.routes import llm_providers as llm_providers_routes
from api.routes import mcp_info as mcp_info_routes
from api.routes import mounts as mounts_routes
from api.routes import storage as storage_routes
from api.routes import auth as auth_routes
from api.routes import admin as admin_routes
from api.routes import llm_costs as llm_costs_routes
from api.middleware import add_middleware

# ── Logging (initial config — level updated from DB in lifespan) ─────────────
configure_logging()

import structlog
log = structlog.get_logger(__name__)

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
DEV_BYPASS_AUTH = os.getenv("DEV_BYPASS_AUTH", "false").lower() == "true"
UNIONCORE_ORIGIN = os.getenv("UNIONCORE_ORIGIN", "")


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    log.info("markflow.startup", debug=DEBUG, dev_bypass_auth=DEV_BYPASS_AUTH)

    # Validate required env vars in production mode
    # v0.29.0 SEC-H13: also reject the weak hardcoded SECRET_KEY default and
    # enforce a minimum length so a production deploy can't silently ship with
    # a predictable JWT/credentials-store key.
    _WEAK_DEFAULTS = {"", "dev-secret-change-in-prod", "dev-secret", "change-me", "changeme"}
    if not DEV_BYPASS_AUTH:
        if not os.getenv("UNIONCORE_JWT_SECRET"):
            raise ValueError("UNIONCORE_JWT_SECRET must be set when DEV_BYPASS_AUTH=false")
        if not os.getenv("API_KEY_SALT"):
            raise ValueError("API_KEY_SALT must be set when DEV_BYPASS_AUTH=false")
        _sk = os.getenv("SECRET_KEY", "")
        if _sk in _WEAK_DEFAULTS or len(_sk) < 32:
            raise ValueError(
                "SECRET_KEY must be set to a strong value (>=32 chars, not the "
                "committed dev default) when DEV_BYPASS_AUTH=false"
            )
    else:
        # Dev mode: still warn loudly if the key is weak so operators notice.
        _sk = os.getenv("SECRET_KEY", "")
        if _sk in _WEAK_DEFAULTS or len(_sk) < 32:
            log.warning(
                "markflow.weak_secret_key",
                hint="SECRET_KEY is short or a known default — safe in dev, MUST be replaced before prod",
            )

    # Initialize SQLite schema + default preferences
    await init_db()
    log.info("markflow.db_ready")

    # v0.33.1: load LLM cost rate table from disk so cost-estimate
    # endpoints have data ready before any request lands. Soft-fails
    # if the file is missing/malformed (operator can edit + reload via
    # POST /api/admin/llm-costs/reload without container restart).
    try:
        from core.llm_costs import load_costs
        load_costs()
    except Exception as exc:  # noqa: BLE001 — never block startup
        log.warning("markflow.llm_costs_load_failed", error=str(exc))

    # Clean up any jobs stuck from a previous container run
    from core.database import cleanup_orphaned_jobs
    await cleanup_orphaned_jobs()

    # v0.22.19 one-time junk-row cleanup. Pre-v0.22.19 the scan-time filter
    # didn't catch ~$* Office lock files / Thumbs.db / desktop.ini, so they
    # accumulated in bulk_files (1,327 Thumbs.db rows in one observed scan)
    # and source_files (453 in the same scan), polluting counts and
    # producing misleading "LibreOffice not found" errors when LibreOffice
    # was correctly invoked on a 162-byte ~$* lock file. The scanner is now
    # fixed (see core/bulk_scanner.is_junk_filename) — this migration
    # purges the historical leak. Idempotent: gated by the
    # 'junk_cleanup_v0_22_19_done' preference.
    try:
        from core.database import get_preference, set_preference, get_db
        if (await get_preference("junk_cleanup_v0_22_19_done")) != "true":
            # Mirror the same patterns the scanner now filters. Use SQL LIKE
            # because we're matching path suffixes here, not basenames in
            # Python — '%/X' matches any path ending in /X across both
            # POSIX and Windows-mounted UNC paths.
            patterns = [
                "%/~$%", "%\\~$%",            # Office lock files
                "%/~WRL%.tmp", "%\\~WRL%.tmp",  # Word recovery temp
                "%/Thumbs.db", "%\\Thumbs.db",
                "%/thumbs.db", "%\\thumbs.db",
                "%/desktop.ini", "%\\desktop.ini",
                "%/.DS_Store", "%\\.DS_Store",
                "%/ehthumbs.db", "%\\ehthumbs.db",
            ]
            where_clause = " OR ".join(["source_path LIKE ?"] * len(patterns))
            async with get_db() as conn:
                # bulk_files first (FK to source_files in some schemas)
                cur = await conn.execute(
                    f"DELETE FROM bulk_files WHERE {where_clause}", patterns,
                )
                bulk_deleted = cur.rowcount
                cur = await conn.execute(
                    f"DELETE FROM source_files WHERE {where_clause}", patterns,
                )
                source_deleted = cur.rowcount
                await conn.commit()
            log.info(
                "markflow.junk_cleanup_v0_22_19",
                bulk_files_deleted=bulk_deleted,
                source_files_deleted=source_deleted,
            )
            await set_preference("junk_cleanup_v0_22_19_done", "true")
    except Exception as exc:
        log.warning("markflow.junk_cleanup_v0_22_19_failed", error=str(exc))

    # --- v0.23.0 startup migrations ---
    # Initialize connection pool (must be after init_db, before pool-dependent code)
    from core.db.connection import get_db_path
    from core.db.pool import init_pool, shutdown_pool
    await init_pool(get_db_path())
    log.info("markflow.pool_ready")

    # Stale job cleanup (idempotent, no gate needed)
    from core.db.migrations import add_heartbeat_column, cleanup_stale_jobs
    await add_heartbeat_column()
    await cleanup_stale_jobs()

    # bulk_files dedup (one-time, gated by preference flag)
    from core.db.migrations import run_bulk_files_dedup
    await run_bulk_files_dedup()

    # Clear stale `error` from completed analysis_queue rows (one-time, v0.29.8)
    from core.db.migrations import clear_stale_analysis_errors
    await clear_stale_analysis_errors()

    # Vision re-queue MIME failures (one-time, best-effort)
    try:
        from core.database import db_execute
        await db_execute("""
            UPDATE analysis_queue
            SET status = 'pending', retry_count = 0
            WHERE status = 'failed'
              AND error LIKE '%media type%'
        """)
    except Exception:
        pass

    # Lifecycle timer warnings
    from core.preferences_cache import get_cached_preference
    grace = await get_cached_preference("lifecycle_grace_period_hours", 36)
    retention = await get_cached_preference("lifecycle_trash_retention_days", 60)
    try:
        grace_val = int(grace) if grace else 36
        retention_val = int(retention) if retention else 60
    except (ValueError, TypeError):
        grace_val, retention_val = 36, 60
    if grace_val < 24:
        log.warning("lifecycle_timer_below_production",
                    setting="grace_period", current=grace_val, recommended=36)
    if retention_val < 30:
        log.warning("lifecycle_timer_below_production",
                    setting="trash_retention", current=retention_val, recommended=60)

    # Recover files stuck in 'moving' status (crash recovery)
    from core.lifecycle_manager import recover_moving_files
    await recover_moving_files()

    # Reset in-memory coordinator flags so ghost scan state doesn't persist
    from core.scan_coordinator import reset_coordinator
    reset_coordinator()

    # Clear in-memory stop flag so the banner doesn't stick after restart
    from core.stop_controller import reset_stop
    reset_stop()

    # Apply log level: DB preference wins, then DEFAULT_LOG_LEVEL env var, then "normal"
    from core.database import get_preference
    from core.logging_config import update_log_level
    pref_level = await get_preference("log_level")
    env_level = os.getenv("DEFAULT_LOG_LEVEL", "").strip().lower()
    effective_level = pref_level if pref_level and pref_level != "normal" else env_level
    if effective_level in ("elevated", "developer"):
        update_log_level(effective_level)

    # Verify system dependencies
    checker = HealthChecker()
    health = await checker.check_all()
    for dep, status in health.items():
        level = "info" if status.get("ok") else "warning"
        getattr(log, level)("markflow.dependency", dependency=dep, **status)

    # Seed default locations from env vars on first run
    try:
        from core.database import list_locations, create_location
        existing = await list_locations()
        if not existing:
            bulk_source = os.getenv("BULK_SOURCE_PATH")
            bulk_output = os.getenv("BULK_OUTPUT_PATH")
            if bulk_source:
                await create_location("Default Source", bulk_source, "source")
                log.info("markflow.seed_location", name="Default Source", path=bulk_source)
            if bulk_output:
                await create_location("Default Output", bulk_output, "output")
                log.info("markflow.seed_location", name="Default Output", path=bulk_output)
    except Exception as exc:
        log.warning("markflow.seed_locations_error", error=str(exc))

    # Initialize Meilisearch indexes (best-effort — app starts without it)
    try:
        from core.search_indexer import get_search_indexer
        indexer = get_search_indexer()
        if indexer:
            await indexer.ensure_indexes()
    except Exception as exc:
        log.warning("markflow.meilisearch_init_skip", error=str(exc))

    # Initialize vector search (best-effort — app starts without it)
    try:
        from core.vector.index_manager import get_vector_indexer
        vec_indexer = await get_vector_indexer()
        if vec_indexer:
            status = await vec_indexer.get_status()
            log.info("markflow.vector_search_ready", **status)
        else:
            log.info("markflow.vector_search_disabled", reason="Qdrant not configured or unreachable")
    except Exception as exc:
        log.warning("markflow.vector_search_init_skip", error=str(exc))

    # Prime psutil CPU cache (first call with interval=0.1, then interval=None is instant)
    import psutil
    psutil.cpu_percent(interval=0.1, percpu=True)

    # Detect GPU for hashcat password cracking
    try:
        from core.gpu_detector import detect_gpu
        gpu_info = detect_gpu()
        log.info("markflow.gpu_detected",
                 execution_path=gpu_info.execution_path,
                 effective_gpu=gpu_info.effective_gpu_name)
    except Exception as exc:
        log.warning("markflow.gpu_detection_failed", error=str(exc))

    # v0.25.0: Universal Storage Manager — load output-path cache from DB,
    # then re-mount any saved network shares. Both steps are best-effort:
    # a flaky NAS must not block startup, and the rest of the app is happy
    # to come up with the write guard denying everything (the Storage page
    # then guides the operator to fix the configuration).
    try:
        from core import storage_manager as _sm
        await _sm.load_config_from_db()
    except Exception as exc:  # noqa: BLE001
        log.warning("markflow.storage_config_load_failed", error=str(exc))

    try:
        from core.credential_store import CredentialStore
        from core.mount_manager import get_mount_manager, remount_all_saved
        secret = os.environ.get("SECRET_KEY", "")
        creds = CredentialStore(secret_key=secret) if secret else None
        remount_result = await remount_all_saved(get_mount_manager(), creds)
        log.info("markflow.storage_remount_complete", result=remount_result)
    except Exception as exc:  # noqa: BLE001 — never block startup
        log.warning("markflow.storage_remount_failed", error=str(exc))

    # Phase 9: Start scheduler + health-gated initial pipeline cycle
    from core.scheduler import start_scheduler, stop_scheduler
    from core.metrics_collector import record_activity_event

    # v0.32.10: hydrate the lifecycle scanner's in-memory state from
    # the DB so the Status page's "Last scan" reflects history, not
    # just whatever ran since this container started. Without this,
    # the Lifecycle Scanner card shows "Last scan: never" after every
    # restart even when scan_runs has dozens of completed rows.
    try:
        from core.lifecycle_scanner import hydrate_scan_state_from_db
        await hydrate_scan_state_from_db()
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("markflow.scan_state_hydration_failed", error=str(exc))

    try:
        start_scheduler()

        # Health-gated pipeline startup: waits for services, then runs
        # initial scan+convert+index. Runs as background task so the app
        # starts serving immediately (health endpoint, UI, API all available).
        import asyncio
        from core.pipeline_startup import wait_for_health_and_start_pipeline
        asyncio.create_task(wait_for_health_and_start_pipeline())

        # Initialize cloud file prefetch if enabled
        prefetch_enabled = (await get_preference("cloud_prefetch_enabled") or "false").lower() == "true"
        if prefetch_enabled:
            from core.cloud_prefetch import init_prefetch_manager
            pfx_concurrency = int(await get_preference("cloud_prefetch_concurrency") or "5")
            pfx_rate = int(await get_preference("cloud_prefetch_rate_limit") or "30")
            pfx_timeout = int(await get_preference("cloud_prefetch_timeout_seconds") or "120")
            pfx_min_size = int(await get_preference("cloud_prefetch_min_size_bytes") or "0")
            pfx_probe_all = (await get_preference("cloud_prefetch_probe_all") or "false").lower() == "true"
            await init_prefetch_manager(pfx_concurrency, pfx_rate, pfx_timeout, pfx_min_size, pfx_probe_all)
            log.info("markflow.cloud_prefetch_enabled", concurrency=pfx_concurrency, rate_limit=pfx_rate)

        # Record startup event
        await record_activity_event("startup", "MarkFlow started", {
            "version": __version__,
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total": psutil.virtual_memory().total,
        })
    except Exception as exc:
        log.warning("markflow.scheduler_start_error", error=str(exc))

    yield

    try:
        await record_activity_event("shutdown", "MarkFlow shutting down")
    except Exception:
        pass
    try:
        stop_scheduler()
    except Exception as exc:
        log.warning("markflow.scheduler_stop_error", error=str(exc))
    try:
        from core.cloud_prefetch import shutdown_prefetch_manager
        await shutdown_prefetch_manager()
    except Exception as exc:
        log.warning("markflow.prefetch_shutdown_error", error=str(exc))
    try:
        from core.db.pool import shutdown_pool
        await shutdown_pool()
    except Exception as exc:
        log.warning("markflow.pool_shutdown_error", error=str(exc))
    log.info("markflow.shutdown")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MarkFlow — Document Conversion",
    description=(
        "Convert documents bidirectionally between their original format "
        "and Markdown. OCR, batch processing, and style preservation."
    ),
    version=__version__,
    lifespan=lifespan,
)

# ── CORS middleware ──────────────────────────────────────────────────────────
_allowed_origins = ["*"] if DEV_BYPASS_AUTH else (
    [UNIONCORE_ORIGIN] if UNIONCORE_ORIGIN else []
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def add_static_cache_headers(request, call_next):
    """Bust browser cache for static assets after deploys."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

add_middleware(app)

# ── API Routes ────────────────────────────────────────────────────────────────
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(convert.router)
app.include_router(batch.router)
app.include_router(history.router)
app.include_router(preferences.router)
app.include_router(review.router)

# Debug dashboard — always available (developer/operator tool)
app.include_router(debug_routes.router)

# Phase 7 — Bulk, Search, Cowork
app.include_router(bulk.router)
app.include_router(search_routes.router)
app.include_router(cowork.router)

# v0.7.1 — Named Locations
app.include_router(locations.router)

# v0.7.2 — Directory Browser
app.include_router(browse.router)

# v0.7.4 — LLM Providers + MCP info
app.include_router(llm_providers_routes.router)
app.include_router(mcp_info_routes.router)

# v0.8.2 — Unrecognized file catalog
from api.routes import unrecognized as unrecognized_routes
app.include_router(unrecognized_routes.router)

# v0.8.5 — Phase 9: Lifecycle, Trash, Scanner, DB Health
from api.routes import lifecycle as lifecycle_routes
from api.routes import trash as trash_routes
from api.routes import scanner as scanner_routes
from api.routes import db_health as db_health_routes
app.include_router(lifecycle_routes.router)
app.include_router(trash_routes.router)
app.include_router(scanner_routes.router)
app.include_router(db_health_routes.router)

# v0.9.5 — Logging endpoints
from api.routes import client_log as client_log_routes
from api.routes import logs as logs_routes
app.include_router(client_log_routes.router)
app.include_router(logs_routes.router)

# v0.9.7 — Resources page (metrics, activity, summary)
from api.routes import resources as resources_routes
app.include_router(resources_routes.router)

# v0.10.0 — Help wiki (public, no auth)
from api.routes import help as help_routes
app.include_router(help_routes.router)

# v0.11.0 — Auto-conversion engine
from api.routes import auto_convert as auto_convert_routes
app.include_router(auto_convert_routes.router)

# v0.14.0 — Pipeline control
from api.routes import pipeline as pipeline_routes
app.include_router(pipeline_routes.router)

# v0.13.0 — Media transcript API
from api.routes import media as media_routes
app.include_router(media_routes.router)

# v0.16.0 — File flagging & content moderation
from api.routes import flags as flags_routes
app.include_router(flags_routes.router)

# NFS/SMB mount configuration
app.include_router(mounts_routes.router)
app.include_router(storage_routes.router)

# v0.21.0 — AI-Assisted Search
from api.routes import ai_assist as ai_assist_routes
app.include_router(ai_assist_routes.router)

# Spec B — Analysis queue management
from api.routes import analysis as analysis_routes
app.include_router(analysis_routes.router)

# v0.30.1: Log Management subsystem
from api.routes import log_management as log_management_routes
app.include_router(log_management_routes.router)

# v0.33.1: LLM token-cost estimation subsystem
app.include_router(llm_costs_routes.router)

# v0.32.0: file detail / preview page (path-keyed, OPERATOR+)
from api.routes import preview as preview_routes
app.include_router(preview_routes.router)

# v0.34.0: Premiere project (.prproj) cross-reference API
from api.routes import prproj as prproj_routes
app.include_router(prproj_routes.router)

# UX overhaul §10: per-user preferences (distinct from system-level /api/preferences)
from api.routes import user_prefs as user_prefs_routes
app.include_router(user_prefs_routes.router)

# UX overhaul §13: UI telemetry sink (unauthenticated, ui.* events only)
from api.routes import telemetry as telemetry_routes
app.include_router(telemetry_routes.router)

# UX overhaul Plan 4: /api/me — authenticated user identity + role + build info
from api.routes import me as me_routes
app.include_router(me_routes.router)

# UX overhaul Plan 4: /api/activity/summary — operator-gated activity aggregator
from api.routes import activity as activity_routes
app.include_router(activity_routes.router)

# /pipeline -> /activity 301 alias (one-release deprecation window).
# Spec §1: route renamed during UX overhaul. Remove after Plan 4 ships
# and confirm no internal links / bookmarks still hit /pipeline.
@app.get("/pipeline", include_in_schema=False)
@app.get("/pipeline/{rest:path}", include_in_schema=False)
async def _pipeline_alias(rest: str = ""):
    target = "/activity" + (("/" + rest) if rest else "")
    return RedirectResponse(target, status_code=301)


@app.get("/activity", include_in_schema=False)
async def activity_page():
    """Activity dashboard (admin/operator-only at the API layer; the
    boot script redirects members to / on /api/me response).
    """
    return FileResponse("static/activity.html")


# UX overhaul Plan 5: Settings overview + Storage detail
@app.get("/settings", include_in_schema=False)
async def settings_page():
    """Settings overview card grid. New UX when ENABLE_NEW_UX=true."""
    if is_new_ux_enabled():
        return FileResponse("static/settings-new.html")
    return FileResponse("static/settings.html")


@app.get("/settings/storage", include_in_schema=False)
async def settings_storage_page():
    """Storage detail page — sidebar + mounts/output view."""
    return FileResponse("static/settings-storage.html")


@app.get("/settings/pipeline", include_in_schema=False)
async def settings_pipeline_page():
    return FileResponse("static/settings-pipeline.html")


@app.get("/settings/ai-providers", include_in_schema=False)
async def settings_ai_providers_page():
    return FileResponse("static/settings-ai-providers.html")


@app.get("/settings/auth", include_in_schema=False)
async def settings_auth_page():
    return FileResponse("static/settings-auth.html")


@app.get("/settings/notifications", include_in_schema=False)
async def settings_notifications_page():
    return FileResponse("static/settings-notifications.html")


@app.get("/settings/{section}", include_in_schema=False)
async def settings_section_page(section: str):
    """Future plans implement each section. Redirect to overview for now."""
    return RedirectResponse("/settings", status_code=302)


log.info("markflow.all_routes_registered")

# ── Static files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

# OCR debug / flag crop images — served from the output directory.
#
# v0.34.1 BUG-009: route through the shared Storage Paths resolver so
# this mount points at the same place the converter writes. Note: this
# StaticFiles mount captures the path at app-startup time (before
# lifespan startup → before load_config_from_db → before Storage
# Manager populates). So it'll resolve to the env value here and
# changing the Storage Manager output path at runtime requires a
# container restart for /ocr-images to follow. Documented in gotchas.
import os as _os
from core.storage_paths import get_output_root_str as _get_output_root_str
_output_dir = _get_output_root_str()
_os.makedirs(_output_dir, exist_ok=True)
app.mount("/ocr-images", StaticFiles(directory=_output_dir), name="ocr-images")


# ── Health endpoint ───────────────────────────────────────────────────────────
@app.get("/api/version", tags=["system"])
async def get_version():
    """Return the current MarkFlow version."""
    return {"version": __version__}


@app.get("/api/health", tags=["system"])
async def health_check():
    """System health check — Tesseract, LibreOffice, disk space, DB size."""
    return await run_health_check()


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root_index():
    """Serve the home page. New UX rendered when ENABLE_NEW_UX=true."""
    if is_new_ux_enabled():
        return FileResponse("static/index-new.html")
    return FileResponse("static/index.html")


# ── Catch-all for SPA-style page navigation ───────────────────────────────────
@app.get("/{page_name}.html", include_in_schema=False)
async def serve_page(page_name: str):
    path = f"static/{page_name}.html"
    if os.path.exists(path):
        return FileResponse(path)
    return FileResponse("static/index.html")
