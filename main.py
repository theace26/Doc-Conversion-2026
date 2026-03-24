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
from core.health import HealthChecker
from core.logging_config import configure_logging
from api.routes import convert, batch, history, preferences, review
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

    yield

    log.info("markflow.shutdown")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MarkFlow — Document Conversion",
    description=(
        "Convert documents bidirectionally between their original format "
        "and Markdown. OCR, batch processing, and style preservation."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

add_middleware(app)

# ── API Routes ────────────────────────────────────────────────────────────────
app.include_router(convert.router)
app.include_router(batch.router)
app.include_router(history.router)
app.include_router(preferences.router)
app.include_router(review.router)

# Debug routes — only in DEBUG mode
if DEBUG:
    from api.routes import debug as debug_routes
    app.include_router(debug_routes.router)
    log.info("markflow.debug_routes_registered")

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
    checker = HealthChecker()
    return await checker.check_all()


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
