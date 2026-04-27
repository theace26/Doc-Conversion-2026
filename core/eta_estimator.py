"""ETA estimator (v0.31.5).

Lightweight throughput tracker. Records observations of the form
`(operation, scope_size, wall_seconds)` and answers "given a future
operation of size N, how long is it likely to take?" using an
exponentially-weighted moving average (EWMA) of throughput
(scope_size / wall_seconds).

Storage: persisted into a single `eta_observations` row per operation
key in the SQLite preferences table — one JSON blob per operation,
small enough that we don't need a dedicated table. The key is the
operation name (e.g. `log_search_gz`, `log_search_7z`,
`log_search_plain`).

Why a single class with operation keys (not separate per-op state):
the framework should be reusable. Adding ETA to bulk-job runs, OCR
queue drain, vector indexing, etc. is just `record_observation(op, ...)`
+ `estimate(op, ...)`. No new class hierarchy needed.

Design notes
------------
- **EWMA over a fixed-window average** because throughput is heavily
  influenced by recent disk cache state, so the most recent
  observations are the most predictive. EWMA's α=0.3 weights the
  newest reading at 30% and the prior trailing average at 70% —
  enough smoothing to swallow outliers, enough recency to react to
  drift (HDD cache warm vs cold, container under heavy bulk load
  vs idle).
- **Scope-size normalization** so small operations (100 lines) and
  big operations (200,000 lines) feed the same estimator without
  one drowning the other. The throughput ratio is what matters.
- **Min-observations gate** before the estimator is willing to
  forecast — three observations on this operation type, otherwise
  `estimate()` returns None and the UI falls back to "no estimate
  available yet" copy. Avoids confidently wrong predictions on a
  cold start.
- **System-resource awareness** comes via the periodic spec
  snapshot (see `system_specs_history` writes from the scheduler
  job below). On a host with vastly different specs from when the
  observation was recorded, the EWMA will drift fast — which is
  what we want.
- **Headless safety**: every method is best-effort. Misshaped JSON
  in the preference, DB unavailable, math errors all return None
  rather than raising. Callers should treat ETA as advisory text,
  never gate logic on it.
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# EWMA weight on the newest observation. Higher α = more responsive
# to recent changes; lower α = smoother but slower to adapt.
_EWMA_ALPHA = 0.3

# Minimum observations before we'll forecast. Below this,
# `estimate()` returns None.
_MIN_OBSERVATIONS = 3

# How many trailing observations we remember per operation. Keeps
# the JSON blob bounded; we only use the EWMA value plus the count.
# History stays for diagnostic purposes (Settings page can show "n
# observations recorded"). Cap at 200 so the blob never exceeds
# ~10 KB.
_HISTORY_CAP = 200


def _pref_key(op: str) -> str:
    """Map an operation name to its preferences-row key."""
    safe = "".join(c if (c.isalnum() or c in "_.-") else "_" for c in op)
    return f"eta_observations__{safe}"


async def record_observation(
    op: str,
    scope_size: int,
    wall_seconds: float,
) -> None:
    """Record one observation of an operation completing.

    `scope_size` is whatever unit makes sense for `op` (lines for
    log search, bytes for ZIP creation, files for bulk job, etc.).
    `wall_seconds` is the actual elapsed wall time. The estimator
    derives throughput = scope_size / wall_seconds and folds it
    into the EWMA for `op`.

    Best-effort: malformed prior state is reset to a fresh blob;
    DB write errors are logged but never raised.
    """
    if scope_size <= 0 or wall_seconds <= 0:
        return  # Garbage input — silently skip rather than poison the EWMA.

    throughput = scope_size / wall_seconds
    key = _pref_key(op)

    try:
        from core.database import get_preference, set_preference
        raw = await get_preference(key)
        state = _parse_state(raw)

        # EWMA update.
        if state["count"] == 0:
            state["throughput_ewma"] = throughput
        else:
            prior = state["throughput_ewma"]
            state["throughput_ewma"] = (
                _EWMA_ALPHA * throughput + (1 - _EWMA_ALPHA) * prior
            )
        state["count"] = min(state["count"] + 1, 1_000_000_000)
        state["last_throughput"] = throughput
        state["last_observed_at"] = time.time()

        # Trailing history (capped).
        history = state.get("history") or []
        history.append({
            "scope_size": scope_size,
            "wall_seconds": round(wall_seconds, 4),
            "throughput": round(throughput, 4),
            "ts": round(time.time(), 0),
        })
        if len(history) > _HISTORY_CAP:
            history = history[-_HISTORY_CAP:]
        state["history"] = history

        await set_preference(key, json.dumps(state))
    except Exception as exc:  # pragma: no cover — defensive
        log.warning(
            "eta.record_failed",
            op=op,
            error=f"{type(exc).__name__}: {exc}",
        )


async def estimate(op: str, scope_size: int) -> dict[str, Any] | None:
    """Return an ETA estimate for an operation of size `scope_size`.

    Returns:
      `None` if the estimator hasn't seen `_MIN_OBSERVATIONS` of `op`
      yet (cold start), or if the prior state can't be parsed.

      Otherwise a dict:
        {
          "estimate_seconds": float,
          "throughput_ewma": float,    # in scope-units per second
          "observations": int,         # how many we've recorded
          "confidence": str,           # "low" | "medium" | "high"
        }

    The `confidence` field is heuristic: <10 observations is "low",
    10-50 is "medium", 50+ is "high". The UI can soften the copy
    accordingly ("estimated ~12 s based on 4 prior runs" vs
    "estimated 12 s").
    """
    if scope_size <= 0:
        return None
    key = _pref_key(op)
    try:
        from core.database import get_preference
        raw = await get_preference(key)
    except Exception:
        return None
    state = _parse_state(raw)
    if state["count"] < _MIN_OBSERVATIONS:
        return None
    throughput = state.get("throughput_ewma") or 0
    if throughput <= 0:
        return None
    seconds = scope_size / throughput

    n = state["count"]
    if n < 10:
        confidence = "low"
    elif n < 50:
        confidence = "medium"
    else:
        confidence = "high"

    return {
        "estimate_seconds": round(seconds, 2),
        "throughput_ewma": round(throughput, 4),
        "observations": n,
        "confidence": confidence,
    }


async def stats(op: str | None = None) -> dict:
    """Diagnostic snapshot for the admin UI.

    With no `op`, returns a list of all known operation keys with
    summary stats. With an `op`, returns the full state including
    a trailing history sample.
    """
    try:
        from core.db.connection import db_fetch_all
        # Settings preferences live in the `preferences` table
        # (key, value) — list every eta_observations__* row.
        rows = await db_fetch_all(
            "SELECT key, value FROM preferences WHERE key LIKE 'eta_observations__%'"
        )
    except Exception:
        return {"operations": []}

    out: list[dict] = []
    for row in rows:
        op_name = row["key"][len("eta_observations__"):]
        if op is not None and op_name != op:
            continue
        st = _parse_state(row["value"])
        entry = {
            "op": op_name,
            "count": st["count"],
            "throughput_ewma": round(st.get("throughput_ewma") or 0, 4),
            "last_throughput": round(st.get("last_throughput") or 0, 4),
            "last_observed_at": st.get("last_observed_at"),
        }
        if op is not None:
            # Include trailing history when caller asks about a
            # single op (otherwise the response could balloon).
            entry["history_tail"] = (st.get("history") or [])[-20:]
        out.append(entry)
    out.sort(key=lambda e: e.get("count", 0), reverse=True)
    return {"operations": out}


def _parse_state(raw: str | None) -> dict[str, Any]:
    """Parse a stored state blob, tolerantly. Bad / missing JSON
    returns the empty-state default so the caller can proceed."""
    default = {
        "count": 0,
        "throughput_ewma": 0.0,
        "last_throughput": 0.0,
        "last_observed_at": None,
        "history": [],
    }
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return default
        for k, v in default.items():
            parsed.setdefault(k, v)
        return parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


# ── System-spec snapshot (24h scheduler job) ────────────────────────


async def record_system_spec_snapshot() -> None:
    """Periodic snapshot of host resources, persisted as a JSON blob
    in `preferences['eta_system_spec_history']`. Writes are bounded
    at 90 entries (~3 months of daily snapshots) so the row stays
    small.

    Called by the scheduler job in `core/scheduler.py`. Best-effort:
    a `/proc` read failure on one field doesn't abort the snapshot;
    the field just gets `None`.
    """
    try:
        from core.log_manager import get_system_resource_snapshot
        snap = get_system_resource_snapshot()
    except Exception as exc:
        log.warning(
            "eta.spec_snapshot_failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    snap["recorded_at"] = time.time()
    key = "eta_system_spec_history"
    try:
        from core.database import get_preference, set_preference
        raw = await get_preference(key)
        if raw:
            try:
                history = json.loads(raw)
                if not isinstance(history, list):
                    history = []
            except (json.JSONDecodeError, ValueError):
                history = []
        else:
            history = []
        history.append(snap)
        if len(history) > 90:
            history = history[-90:]
        await set_preference(key, json.dumps(history))
        log.info(
            "eta.spec_snapshot_recorded",
            entries=len(history),
            cpu=snap.get("cpu_model"),
            mem_total=snap.get("memory_mb_total"),
            mem_free=snap.get("memory_mb_free"),
        )
    except Exception as exc:  # pragma: no cover — defensive
        log.warning(
            "eta.spec_snapshot_persist_failed",
            error=f"{type(exc).__name__}: {exc}",
        )
