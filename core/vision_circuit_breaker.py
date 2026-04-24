"""Vision-API circuit breaker (v0.29.9).

Prevents burning money on doomed API calls during an Anthropic outage,
bad-key rotation, or quota-exhaustion event.

State machine:
    closed  ─(N consecutive upstream failures)→ open
    open    ─(cooldown elapsed)→ half-open
    half-open ─(next call succeeds)→ closed
    half-open ─(next call fails)→ open (cooldown doubles, capped)

Only UPSTREAM failures count (429 / 5xx / 529 / network/timeout). 400s
do NOT trip the breaker — those are payload problems and feed the
bisection path instead. Bisection failures that eventually isolate a
bad file are successes from the breaker's perspective: the API
responded correctly, we just found a bad input.

Process-local state (not DB-persisted). Restart resets the breaker —
that's intentional; after a restart the operator presumably expects to
try again, and Anthropic's side might have recovered while we were
down.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)


_FAILURE_THRESHOLD = 5            # consecutive upstream failures to open
_INITIAL_COOLDOWN_S = 60          # first cooldown after open
_MAX_COOLDOWN_S = 15 * 60         # cap back-off at 15 minutes
_COOLDOWN_BACKOFF = 2.0           # multiplier on repeated re-open


@dataclass
class _State:
    consecutive_failures: int = 0
    opened_at: float | None = None          # epoch seconds when last opened
    cooldown_s: float = _INITIAL_COOLDOWN_S
    last_error_class: str | None = None     # short label: 'rate_limit', '5xx', 'timeout', etc.
    last_error_detail: str | None = None    # full message for UI display
    half_open_in_flight: bool = False       # exactly one trial call permitted in half-open


_state = _State()
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _epoch_now() -> float:
    return time.time()


def _transition_to_half_open_if_ready() -> bool:
    """If we're open and the cooldown has elapsed, drop to half-open.
    Called under the lock. Returns True if a trial should be allowed."""
    if _state.opened_at is None:
        return False
    elapsed = _now() - _state.opened_at
    if elapsed < _state.cooldown_s:
        return False
    # Cooldown elapsed — drop to half-open. Only ONE trial call allowed
    # at a time; concurrent callers beyond the first see `open`.
    if _state.half_open_in_flight:
        return False
    _state.half_open_in_flight = True
    log.info(
        "vision_circuit_breaker.half_open",
        cooldown_elapsed_s=elapsed,
    )
    return True


def allow_call() -> tuple[bool, str | None]:
    """Call before making an API request. Returns (allowed, reason).

    - closed  -> (True, None)
    - open    -> (False, 'circuit_open')   — short-circuit, skip the call
    - half-open (one trial permitted) -> (True, 'half_open_trial')
    """
    with _lock:
        if _state.opened_at is None:
            return True, None
        if _transition_to_half_open_if_ready():
            return True, "half_open_trial"
        return False, "circuit_open"


def record_success() -> None:
    """Reset the failure counter. If we were half-open, close the circuit."""
    with _lock:
        was_half_open = _state.half_open_in_flight
        _state.consecutive_failures = 0
        _state.opened_at = None
        _state.cooldown_s = _INITIAL_COOLDOWN_S
        _state.last_error_class = None
        _state.last_error_detail = None
        _state.half_open_in_flight = False
    if was_half_open:
        log.info("vision_circuit_breaker.closed")


def record_failure(
    error_class: str,
    detail: str = "",
) -> None:
    """Record an UPSTREAM failure (429 / 5xx / 529 / network/timeout).

    400s should NOT call this — they represent payload-level problems
    that bisection can isolate. Calling record_failure on 400 would
    cause a single bad file to trip the breaker for all traffic.
    """
    with _lock:
        # If we were half-open, this trial failed: re-open with longer cooldown.
        if _state.half_open_in_flight:
            _state.half_open_in_flight = False
            _state.cooldown_s = min(_state.cooldown_s * _COOLDOWN_BACKOFF, _MAX_COOLDOWN_S)
            _state.opened_at = _now()
            _state.last_error_class = error_class
            _state.last_error_detail = detail
            log.warning(
                "vision_circuit_breaker.half_open_trial_failed",
                error_class=error_class,
                new_cooldown_s=_state.cooldown_s,
            )
            return

        _state.consecutive_failures += 1
        _state.last_error_class = error_class
        _state.last_error_detail = detail

        if (
            _state.opened_at is None
            and _state.consecutive_failures >= _FAILURE_THRESHOLD
        ):
            _state.opened_at = _now()
            _state.cooldown_s = _INITIAL_COOLDOWN_S
            log.warning(
                "vision_circuit_breaker.opened",
                consecutive_failures=_state.consecutive_failures,
                error_class=error_class,
                cooldown_s=_state.cooldown_s,
            )


def state_snapshot() -> dict:
    """Return a JSON-safe dict of the current state — for /api/analysis/circuit-breaker."""
    with _lock:
        is_open = _state.opened_at is not None
        elapsed_s = (_now() - _state.opened_at) if is_open else 0.0
        remaining_s = max(0.0, _state.cooldown_s - elapsed_s) if is_open else 0.0
        status = (
            "half_open" if is_open and _state.half_open_in_flight else
            "open" if is_open else
            "closed"
        )
        return {
            "status": status,
            "consecutive_failures": _state.consecutive_failures,
            "threshold": _FAILURE_THRESHOLD,
            "cooldown_s": _state.cooldown_s,
            "cooldown_remaining_s": round(remaining_s, 1),
            "opened_at_epoch": (_epoch_now() - (_now() - _state.opened_at)) if is_open else None,
            "last_error_class": _state.last_error_class,
            "last_error_detail": _state.last_error_detail,
        }


def reset() -> None:
    """Manual reset — available via /api/analysis/circuit-breaker/reset
    for operators who want to retry immediately after fixing the
    upstream issue instead of waiting out the cooldown."""
    with _lock:
        _state.consecutive_failures = 0
        _state.opened_at = None
        _state.cooldown_s = _INITIAL_COOLDOWN_S
        _state.last_error_class = None
        _state.last_error_detail = None
        _state.half_open_in_flight = False
    log.info("vision_circuit_breaker.manually_reset")
