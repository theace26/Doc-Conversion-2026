"""
FastAPI middleware for MarkFlow.

- Request ID generation (UUID4) injected into structlog context.
- Request timing middleware.
- Debug headers (X-MarkFlow-*) when DEBUG=true.
- Security response headers (v0.29.0 — SEC-H12 remediation).
"""

import os
import time
import uuid

import structlog
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from core.active_connections import record_request_activity
from core.logging_config import bind_request_context, clear_context
from core.request_pressure import get_request_pressure

log = structlog.get_logger(__name__)
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Security response headers (v0.29.0, addresses SEC-H12).
# All headers are conservative defaults that won't break existing pages.
# CSP uses 'unsafe-inline' for style because several pages have inline styles;
# a tighter policy requires a frontend refactor and is left for a later pass.
_SECURITY_HEADERS: dict[str, str] = {
    # Prevent MIME sniffing
    "X-Content-Type-Options": "nosniff",
    # Block rendering inside a frame (clickjacking protection)
    "X-Frame-Options": "DENY",
    # Only send the origin on cross-origin requests (not the full URL)
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Lock down browser feature access
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    ),
    # Reasonable CSP — same-origin scripts + inline styles (for legacy pages);
    # unsafe-inline on scripts would be needed to fully lock down XSS, but many
    # pages have onclick= handlers; tightening further is a v0.30.x task.
    "Content-Security-Policy": (
        "default-src 'self'; "
        # cdn.jsdelivr.net is allowed for marked.js + DOMPurify which the
        # new-UX /viewer + /preview pages load for client-side Markdown
        # render (always sanitized via DOMPurify before DOM insertion).
        # fonts.googleapis.com + fonts.gstatic.com cover the Google Fonts
        # block that every new-UX page links to.
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}

# Routes that count as user-facing traffic for backpressure purposes
_PRESSURE_PREFIXES = ("/api/search", "/api/files", "/api/history", "/api/drive")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds request_id to structlog context and measures request duration."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Track user-facing requests for background-task backpressure
        pressure = get_request_pressure()
        track = any(request.url.path.startswith(p) for p in _PRESSURE_PREFIXES)
        if track:
            pressure.enter()

        # Bind request context for all downstream log calls
        clear_context()
        bind_request_context(request_id, request.url.path, request.method)

        try:
            response = await call_next(request)

            duration_ms = int((time.perf_counter() - start) * 1000)

            # Security response headers (v0.29.0, SEC-H12). Applied to every
            # response, including errors, so attackers can't force an unprotected
            # 404/500 page.
            for _k, _v in _SECURITY_HEADERS.items():
                response.headers.setdefault(_k, _v)

            if DEBUG:
                response.headers["X-MarkFlow-Request-Id"] = request_id
                response.headers["X-MarkFlow-Duration-Ms"] = str(duration_ms)

            # Record per-user "last seen" activity for the active-connections
            # widget on the Resources page (v0.22.13). The auth dependency
            # stashes the resolved user on request.state.user; if no auth ran
            # for this route (e.g. /api/health, static asset) state.user will
            # be unset and we skip silently.
            user = getattr(request.state, "user", None)
            if user is not None and getattr(user, "sub", None):
                record_request_activity(user.sub, getattr(user, "email", ""))

            log.info(
                "request_complete",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            log.error(
                "request_error",
                duration_ms=duration_ms,
                exc_info=True,
            )
            raise
        finally:
            if track:
                pressure.exit()
            clear_context()


def add_middleware(app: FastAPI) -> None:
    """Register all MarkFlow middleware on the FastAPI app."""
    app.add_middleware(RequestContextMiddleware)
