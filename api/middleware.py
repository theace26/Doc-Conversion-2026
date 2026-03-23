"""
FastAPI middleware for MarkFlow.

- Request ID generation (UUID4) injected into structlog context.
- Request timing middleware.
- Debug headers (X-MarkFlow-*) when DEBUG=true.
"""

import os
import time
import uuid

import structlog
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger(__name__)
DEBUG = os.getenv("DEBUG", "false").lower() == "true"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds request_id to structlog context and measures request duration."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Bind request_id to all log calls within this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)

        duration_ms = int((time.perf_counter() - start) * 1000)

        if DEBUG:
            response.headers["X-MarkFlow-Request-Id"] = request_id
            response.headers["X-MarkFlow-Duration-Ms"] = str(duration_ms)

        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


def add_middleware(app: FastAPI) -> None:
    """Register all MarkFlow middleware on the FastAPI app."""
    app.add_middleware(RequestContextMiddleware)
