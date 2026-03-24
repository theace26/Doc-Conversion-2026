"""
MarkFlow — FastAPI application entry point.

Lifespan:
  - Initializes database schema and default preferences on startup.
  - Verifies system dependencies (Tesseract, LibreOffice, Poppler, WeasyPrint).
  - Shuts down ProcessPoolExecutor cleanly.

Routes mounted:
  /api/convert      — Upload and conversion endpoints
  /api/batch        — Batch status and download endpoints
  /api/history      — Conversion history endpoints
  /api/preferences  — User preferences endpoints
  /api/debug        — Debug dashboard (only when DEBUG=true)
  /static           — Static HTML/CSS/JS files
  /                 — Serves static/index.html
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.database import init_db
from core.health import HealthChecker, run_health_check
from core.logging_config import configure_logging
from api.routes import convert, batch, history, preferences, review, debug as debug_routes
from api.routes import bulk, search as search_routes, cowork, locations, browse
from api.routes import llm_providers as llm_providers_routes
from api.routes import mcp_info as mcp_info_routes
from api.middleware import add_middleware

# ── Logging ──────────────────────────────────────────────────────────────────
configure_logging()

import structlog
log = structlog.get_logger(__name__)

DEBUG = os.getenv("DEBUG", "false").lower() == "true"


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    log.info("markflow.startup", debug=DEBUG)

    # Initialize SQLite schema + default preferences
    await init_db()
    log.info("markflow.db_ready")

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

    yield

    log.info("markflow.shutdown")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MarkFlow — Document Conversion",
    description=(
        "Convert documents bidirectionally between their original format "
        "and Markdown. OCR, batch processing, and style preservation."
    ),
    version="0.8.2",
    lifespan=lifespan,
)

add_middleware(app)

# ── API Routes ────────────────────────────────────────────────────────────────
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

log.info("markflow.all_routes_registered")

# ── Static files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

# OCR debug / flag crop images — served from the output directory
import os as _os
_output_dir = _os.getenv("OUTPUT_DIR", "output")
_os.makedirs(_output_dir, exist_ok=True)
app.mount("/ocr-images", StaticFiles(directory=_output_dir), name="ocr-images")


# ── Health endpoint ───────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health_check():
    """System health check — Tesseract, LibreOffice, disk space, DB size."""
    return await run_health_check()


# ── Root — serve index.html ───────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


# ── Catch-all for SPA-style page navigation ───────────────────────────────────
@app.get("/{page_name}.html", include_in_schema=False)
async def serve_page(page_name: str):
    path = f"static/{page_name}.html"
    if os.path.exists(path):
        return FileResponse(path)
    return FileResponse("static/index.html")
