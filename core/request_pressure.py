"""
Request-aware backpressure for background tasks (rebuild, lifecycle scan).

Tracks in-flight user-facing HTTP requests and provides an adaptive delay
that background loops can await to yield CPU/event-loop time when users
are actively searching or browsing.

When no user requests are in flight the delay is zero — background work
runs at full speed.  As concurrent user requests increase, the delay
scales linearly (capped) so the event loop stays responsive.
"""

import asyncio
import threading

import structlog

log = structlog.get_logger(__name__)

# ── Tuning knobs ────────────────────────────────────────────────────────────

DELAY_PER_REQUEST_MS: float = 50.0   # ms of sleep per concurrent request
DELAY_CAP_MS: float = 500.0          # hard ceiling regardless of request count
BASE_YIELD_MS: float = 1.0           # tiny yield even at 0 requests (event-loop fairness)


class RequestPressure:
    """Thread-safe counter of in-flight user-facing requests.

    Background tasks call ``await adaptive_delay()`` each iteration.
    FastAPI middleware calls ``enter()`` / ``exit()`` around request handling.
    """

    def __init__(self) -> None:
        self._active = 0
        self._lock = threading.Lock()

    def enter(self) -> None:
        with self._lock:
            self._active += 1

    def exit(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def active_requests(self) -> int:
        return self._active

    async def adaptive_delay(self) -> None:
        """Sleep proportionally to current request pressure.

        0 active requests  →  1 ms   (bare event-loop yield)
        1 active request   →  50 ms
        2 active requests  →  100 ms
        ...capped at 500 ms
        """
        n = self._active
        if n == 0:
            # Still yield to the event loop so search handlers aren't starved
            await asyncio.sleep(BASE_YIELD_MS / 1000)
            return
        delay_ms = min(n * DELAY_PER_REQUEST_MS, DELAY_CAP_MS)
        await asyncio.sleep(delay_ms / 1000)


# ── Module singleton ────────────────────────────────────────────────────────

_pressure = RequestPressure()


def get_request_pressure() -> RequestPressure:
    return _pressure
