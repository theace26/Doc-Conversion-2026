"""
Frontend client event logging endpoint.

POST /api/log/client-event — logs user actions from the browser in developer mode.
Only writes to the debug trace log when log_level == "developer".
Rate-limited to 50 events/second per IP.
"""

import time
from collections import defaultdict, deque

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from core.logging_config import get_current_level

router = APIRouter(prefix="/api/log", tags=["logging"])

log = structlog.get_logger(__name__)

# Simple token-bucket rate limiter: max 50 events/second per IP
_MAX_EVENTS_PER_SECOND = 50
_rate_buckets: dict[str, deque] = defaultdict(deque)


class ClientEvent(BaseModel):
    page: str = ""
    event: str = ""
    target: str = ""
    detail: str = ""


def _is_rate_limited(ip: str) -> bool:
    """Return True if this IP has exceeded 50 events in the last second."""
    now = time.monotonic()
    bucket = _rate_buckets[ip]
    # Trim entries older than 1 second
    while bucket and bucket[0] < now - 1.0:
        bucket.popleft()
    if len(bucket) >= _MAX_EVENTS_PER_SECOND:
        return True
    bucket.append(now)
    return False


@router.post("/client-event", status_code=204)
async def client_event(request: Request):
    """Log a frontend user action. No-op unless log_level is 'developer'."""
    try:
        if get_current_level() != "developer":
            return Response(status_code=204)

        ip = request.client.host if request.client else "unknown"
        if _is_rate_limited(ip):
            return Response(status_code=204)

        body = await request.json()
        log.debug(
            "client_action",
            page=body.get("page", ""),
            event_type=body.get("event", ""),
            target=body.get("target", ""),
            detail=body.get("detail", ""),
            client_ip=ip,
        )
    except Exception:
        pass  # Never return an error to the client

    return Response(status_code=204)
