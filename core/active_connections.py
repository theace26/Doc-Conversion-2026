"""
In-memory tracking of who/what is currently using MarkFlow.

Two independent counters, both kept in process memory (no DB schema):

1. **Recently-active users** — last-seen timestamp per `user.sub`. Updated by
   the `record_request_activity()` middleware on every authenticated HTTP
   request. A user is "active" if their last-seen timestamp is within the
   sliding window (default 5 minutes).

2. **Live SSE / streaming connections** — incremented when a long-lived
   StreamingResponse generator starts and decremented in `finally`. Bucketed
   by a short endpoint label so admins can see *which* live streams are open
   ("3 watching bulk progress, 1 in AI Assist drawer").

Both counters reset on container restart. That's intentional — these are
"right now" diagnostics, not historical metrics. The Resources page card
will simply show 0 immediately after a rebuild and refill within seconds as
clients reconnect.

Why no DB schema:
- Resets on restart are acceptable for "right now" widgets.
- Avoids write contention with the bulk worker / scanner during heavy load.
- Two `dict` reads are far cheaper than even an indexed SQLite query.
- The data is throwaway by design.

Usage:
    # In a middleware:
    from core.active_connections import record_request_activity
    record_request_activity(user.sub, user.email)

    # Wrapping an SSE generator:
    from core.active_connections import track_stream
    async def event_generator():
        async with track_stream("bulk_events"):
            ...
    return StreamingResponse(event_generator(), ...)

    # On the Resources endpoint:
    from core.active_connections import get_active_users, get_active_streams
    users = get_active_users(window_seconds=300)
    streams = get_active_streams()
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

import structlog

log = structlog.get_logger(__name__)


# ── Module state ────────────────────────────────────────────────────────────
#
# `_user_last_seen` maps a user's `sub` to (last_seen_iso, email). Email is
# carried so the UI can show a friendlier label without a separate user
# table lookup. dict iteration is reentrant-safe in CPython for the simple
# read-only use we need.
#
# `_active_streams` maps an endpoint label (e.g. "bulk_events", "ai_assist")
# to the current count of open generators on that endpoint.

_user_last_seen: dict[str, tuple[str, str]] = {}
_active_streams: dict[str, int] = {}


# ── Sliding-window user activity ────────────────────────────────────────────


def record_request_activity(user_sub: str | None, user_email: str | None = None) -> None:
    """
    Record that `user_sub` made a request right now. Called from the auth
    middleware. Service-account requests (where `user_sub` is the API key
    hash) are also tracked — useful for spotting "is the integration alive".

    Pass `user_sub=None` to skip silently (lets callers fire-and-forget for
    unauthenticated routes).
    """
    if not user_sub:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    _user_last_seen[user_sub] = (now_iso, user_email or "")


def get_active_users(window_seconds: int = 300) -> list[dict]:
    """
    Return a list of users seen in the last `window_seconds`, sorted by
    most-recent activity first. Each entry: ``{sub, email, last_seen}``.

    Stale entries older than the window are dropped from the in-memory map
    on every call so it can't grow unbounded over a long-running process.
    """
    if window_seconds <= 0:
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - window_seconds

    active: list[dict] = []
    stale: list[str] = []
    for sub, (iso, email) in list(_user_last_seen.items()):
        try:
            ts = datetime.fromisoformat(iso).timestamp()
        except ValueError:
            stale.append(sub)
            continue
        if ts >= cutoff:
            active.append({"sub": sub, "email": email, "last_seen": iso})
        else:
            stale.append(sub)

    for sub in stale:
        _user_last_seen.pop(sub, None)

    active.sort(key=lambda r: r["last_seen"], reverse=True)
    return active


# ── Live stream tracking ────────────────────────────────────────────────────


@asynccontextmanager
async def track_stream(endpoint: str) -> AsyncIterator[None]:
    """
    Async context manager that increments the live-stream counter for
    `endpoint` while the body runs and decrements it in `finally`.

    Wrap the body of any SSE / StreamingResponse generator function:

        async def event_generator():
            async with track_stream("bulk_events"):
                while True:
                    ...
                    yield event

    Decrement is exception-safe — if the client disconnects mid-stream and
    the generator raises `CancelledError` / `BrokenPipeError`, the counter
    still drops back. The endpoint label is intentionally short and stable
    so the UI can render a clean per-endpoint breakdown.
    """
    _active_streams[endpoint] = _active_streams.get(endpoint, 0) + 1
    try:
        yield
    finally:
        n = _active_streams.get(endpoint, 0) - 1
        if n <= 0:
            _active_streams.pop(endpoint, None)
        else:
            _active_streams[endpoint] = n


def get_active_streams() -> dict[str, int]:
    """Return a copy of the live-stream counts, keyed by endpoint label."""
    return dict(_active_streams)


def get_total_active_streams() -> int:
    """Sum of all live-stream counts across endpoints."""
    return sum(_active_streams.values())
