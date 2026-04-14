"""
In-memory TTL cache for database preferences.

Preferences change rarely (user clicks Save in Settings). Caching them
avoids a DB round-trip on every scheduler tick, every worker file, and
every scan iteration. TTL of 300s means worst-case 5 minutes of stale
data after a Settings change — acceptable for all current consumers.
"""

import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_time)
_TTL = 300  # 5 minutes


async def get_cached_preference(key: str, default: Any = None) -> Any:
    """Read a preference, serving from cache if fresh."""
    now = time.time()
    if key in _cache:
        value, expiry = _cache[key]
        if now < expiry:
            return value

    # Cache miss — read from DB
    from core.db.preferences import get_preference
    value = await get_preference(key)
    if value is None:
        value = default
    _cache[key] = (value, now + _TTL)
    return value


def peek_cached_preference(key: str, default: Any = None) -> Any:
    """Synchronous cache peek. Returns the cached value or ``default``.

    Does NOT hit the DB on miss. Safe to call from threads. Intended for
    sync-only code paths (e.g., handlers running inside asyncio.to_thread)
    that previously opened raw sqlite connections to read a preference.
    After the first async read (which populates the cache), this returns
    the same value without I/O. A Settings change invalidates the key so
    the next async read refreshes it.
    """
    now = time.time()
    if key in _cache:
        value, expiry = _cache[key]
        if now < expiry:
            return value
    return default


def invalidate_preference(key: str):
    """Remove a single key from cache. Call after PUT /api/preferences/<key>."""
    removed = _cache.pop(key, None)
    if removed is not None:
        log.debug("preferences_cache.invalidated", key=key)


def invalidate_all():
    """Clear entire cache. Call after bulk settings save."""
    count = len(_cache)
    _cache.clear()
    if count:
        log.debug("preferences_cache.invalidated_all", count=count)
