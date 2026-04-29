"""Active Operations Registry (v0.35.0).

Single source of truth for any long-running file-related operation in
MarkFlow. Workers register at start of work, update on tick, finish at
end. Frontend polls GET /api/active-ops for one unified view.

Spec: docs/superpowers/specs/2026-04-28-active-operations-registry-design.md

DRIFT RULE: bulk_jobs and scan_runs are sources of truth for their
op_types ('bulk.job', 'pipeline.scan'); active_operations is derived
state. On drift, source wins. See spec §17 P3.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from core.database import db_fetch_all
from core.db.connection import db_execute, db_write_with_retry

log = structlog.get_logger(__name__)

# ── op_type whitelist (spec §4) ────────────────────────────────────────
OP_TYPES: frozenset[str] = frozenset({
    "pipeline.run_now",
    "pipeline.convert_selected",
    "pipeline.scan",
    "trash.empty",
    "trash.restore_all",
    "search.rebuild_index",
    "analysis.rebuild",
    "db.backup",
    "db.restore",
    "bulk.job",
})


@dataclass
class ActiveOperation:
    """One row in the registry. See spec §3 for field semantics."""
    op_id: str
    op_type: str
    label: str
    icon: str
    origin_url: str
    started_by: str
    started_at_epoch: float
    last_progress_at_epoch: float
    finished_at_epoch: float | None = None
    total: int = 0
    done: int = 0
    errors: int = 0
    error_msg: str | None = None
    cancelled: bool = False
    cancellable: bool = False
    cancel_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_db_row(self) -> dict[str, Any]:
        """Serialize for SQLite INSERT/UPDATE. Bool → int; extra → JSON."""
        return {
            "op_id": self.op_id,
            "op_type": self.op_type,
            "label": self.label,
            "icon": self.icon,
            "origin_url": self.origin_url,
            "started_by": self.started_by,
            "started_at_epoch": self.started_at_epoch,
            "last_progress_at_epoch": self.last_progress_at_epoch,
            "finished_at_epoch": self.finished_at_epoch,
            "total": self.total,
            "done": self.done,
            "errors": self.errors,
            "error_msg": self.error_msg,
            "cancelled": 1 if self.cancelled else 0,
            "cancellable": 1 if self.cancellable else 0,
            "cancel_url": self.cancel_url,
            "extra_json": json.dumps(self.extra),
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "ActiveOperation":
        """Inverse of to_db_row()."""
        return cls(
            op_id=row["op_id"],
            op_type=row["op_type"],
            label=row["label"],
            icon=row["icon"],
            origin_url=row["origin_url"],
            started_by=row["started_by"],
            started_at_epoch=row["started_at_epoch"],
            last_progress_at_epoch=row["last_progress_at_epoch"],
            finished_at_epoch=row.get("finished_at_epoch"),
            total=row.get("total", 0),
            done=row.get("done", 0),
            errors=row.get("errors", 0),
            error_msg=row.get("error_msg"),
            cancelled=bool(row.get("cancelled", 0)),
            cancellable=bool(row.get("cancellable", 0)),
            cancel_url=row.get("cancel_url"),
            extra=json.loads(row.get("extra_json") or "{}"),
        )

    def to_api_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for HTTP responses. Bools as bools."""
        return {
            "op_id": self.op_id,
            "op_type": self.op_type,
            "label": self.label,
            "icon": self.icon,
            "origin_url": self.origin_url,
            "started_by": self.started_by,
            "started_at_epoch": self.started_at_epoch,
            "last_progress_at_epoch": self.last_progress_at_epoch,
            "finished_at_epoch": self.finished_at_epoch,
            "total": self.total,
            "done": self.done,
            "errors": self.errors,
            "error_msg": self.error_msg,
            "cancelled": self.cancelled,
            "cancellable": self.cancellable,
            "cancel_url": self.cancel_url,
            "extra": self.extra,
        }


# ── Registry state ─────────────────────────────────────────────────────
_lock = asyncio.Lock()
_ops: dict[str, ActiveOperation] = {}
_cancel_hooks: dict[str, Callable[[str], Awaitable[None]]] = {}
_hydration_complete = asyncio.Event()


def register_cancel_hook(op_type: str, hook: Callable[[str], Awaitable[None]]) -> None:
    """Subsystems call this at module import time to register their
    cancel mechanism. Spec §9, P5."""
    if op_type not in OP_TYPES:
        raise ValueError(f"unknown op_type: {op_type}")
    _cancel_hooks[op_type] = hook
    log.info("active_ops.cancel_hook_registered", op_type=op_type)


# ── Public surface ─────────────────────────────────────────────────────
async def register_op(
    *,
    op_type: str,
    label: str,
    icon: str,
    origin_url: str,
    started_by: str,
    cancellable: bool = False,
    cancel_url: str | None = None,
    extra: dict | None = None,
) -> str:
    """Register a new operation in the registry. Returns op_id (uuid4).

    Blocks on _hydration_complete to ensure the registry has hydrated
    from DB before any new op can be registered (spec §10, F5).

    Raises:
        ValueError: unknown op_type.
        RuntimeError: cancellable=True but no cancel hook registered
                      for op_type.
    """
    if op_type not in OP_TYPES:
        raise ValueError(f"unknown op_type: {op_type}")
    if cancellable and op_type not in _cancel_hooks:
        raise RuntimeError(
            f"no cancel hook registered for op_type {op_type!r}; "
            "register one at module import via register_cancel_hook()"
        )

    await _hydration_complete.wait()

    now = time.time()
    op = ActiveOperation(
        op_id=str(uuid.uuid4()),
        op_type=op_type,
        label=label,
        icon=icon,
        origin_url=origin_url,
        started_by=started_by,
        started_at_epoch=now,
        last_progress_at_epoch=now,
        cancellable=cancellable,
        cancel_url=cancel_url,
        extra=extra or {},
    )

    async with _lock:
        _ops[op.op_id] = op

    # Persist to DB via the single-writer queue. In-memory state is
    # canonical during the process lifetime; DB is for restart-survival
    # so persist failures are logged but do not propagate.
    async def _do_insert() -> None:
        row = op.to_db_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        await db_execute(
            f"INSERT INTO active_operations ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )

    try:
        await db_write_with_retry(_do_insert)
    except Exception as exc:
        log.error("active_ops.register_persist_failed",
                  op_id=op.op_id, op_type=op_type,
                  started_by=started_by, error=str(exc))

    log.info("active_ops.registered",
             op_id=op.op_id, op_type=op_type,
             started_by=started_by)
    return op.op_id


# ── Write-through debouncer (spec §10) ─────────────────────────────────
_WRITE_THROTTLE_S = 1.5
_last_persist_at: dict[str, float] = {}


async def _persist_op_update(op: ActiveOperation) -> None:
    """UPDATE the active_operations row from current ActiveOperation
    state. Single source of truth for DB writes during update_op /
    finish_op / cancel_op."""
    row = op.to_db_row()
    set_clauses = ", ".join(f"{k}=?" for k in row.keys() if k != "op_id")
    sql = f"UPDATE active_operations SET {set_clauses} WHERE op_id=?"
    params = tuple(v for k, v in row.items() if k != "op_id") + (op.op_id,)

    async def _do_update() -> None:
        await db_execute(sql, params)

    try:
        await db_write_with_retry(_do_update)
    except Exception as exc:
        log.warning("active_ops.persist_failed",
                    op_id=op.op_id, op_type=op.op_type, error=str(exc))


def _snapshot(op: ActiveOperation) -> ActiveOperation:
    """Defensive copy: shallow-copies fields (most are immutable scalars),
    deep-copies the only mutable field (`extra` dict) so caller mutations
    don't poison registry state. Used by every read path and every persist
    snapshot — single source of truth for the copy idiom."""
    copy = ActiveOperation(**op.__dict__)
    copy.extra = dict(op.extra)
    return copy


async def get_op(op_id: str) -> ActiveOperation | None:
    """Read in-memory snapshot of op_id. Synchronous-style read; takes
    the lock briefly to avoid mid-mutation reads. Returns a defensive
    copy so callers cannot mutate registry state."""
    async with _lock:
        op = _ops.get(op_id)
        if op is None:
            return None
        return _snapshot(op)


async def update_op(
    op_id: str,
    *,
    total: int | None = None,
    done: int | None = None,
    errors: int | None = None,
) -> None:
    """Update progress fields for op_id. No-op + WARN log on
    already-finished rows (spec F1)."""
    snapshot: ActiveOperation | None = None
    should_persist = False
    async with _lock:
        op = _ops.get(op_id)
        if op is None:
            log.warning("active_ops.update_unknown_op", op_id=op_id)
            return
        if op.finished_at_epoch is not None:
            log.warning("active_ops.update_after_finish", op_id=op_id)
            return

        prior_errors = op.errors
        if total is not None:
            op.total = int(total)
        if done is not None:
            op.done = int(done)
        if errors is not None:
            op.errors = int(errors)
        op.last_progress_at_epoch = time.time()

        # Flush triggers (spec §10):
        #   1. Time-based: 1.5s since last flush
        #   2. First-error: errors went from 0 → >0
        first_error = (prior_errors == 0 and op.errors > 0)
        last = _last_persist_at.get(op_id, 0)
        time_based = (time.time() - last) >= _WRITE_THROTTLE_S
        should_persist = first_error or time_based

        if should_persist:
            _last_persist_at[op_id] = time.time()
            # Snapshot so we can persist outside the lock.
            snapshot = _snapshot(op)

    if should_persist and snapshot is not None:
        # Call via module attribute lookup so test monkey-patching of
        # _persist_op_update is observed.
        from core import active_ops as _self
        await _self._persist_op_update(snapshot)


async def finish_op(
    op_id: str,
    *,
    error_msg: str | None = None,
) -> None:
    """Mark op as finished. Synchronously flushes to DB (final state
    must persist — spec §10)."""
    async with _lock:
        op = _ops.get(op_id)
        if op is None:
            log.warning("active_ops.finish_unknown_op", op_id=op_id)
            return
        if op.finished_at_epoch is not None:
            log.warning("active_ops.finish_already_finished",
                        op_id=op_id)
            return
        op.finished_at_epoch = time.time()
        op.last_progress_at_epoch = op.finished_at_epoch
        if error_msg is not None:
            op.error_msg = error_msg
        snapshot = _snapshot(op)
        # Throttle entry is dead — no more update_op allowed (F1).
        _last_persist_at.pop(op_id, None)

    # Synchronous flush — final state is non-negotiable. Use module-attribute
    # lookup so test monkey-patching of _persist_op_update is observed
    # (consistent with update_op's pattern).
    from core import active_ops as _self
    await _self._persist_op_update(snapshot)
    log.info("active_ops.finished",
             op_id=op_id, op_type=snapshot.op_type,
             error_msg=error_msg,
             duration_s=round(snapshot.finished_at_epoch - snapshot.started_at_epoch, 2))


def is_cancelled(op_id: str) -> bool:
    """Synchronous read of the cancelled flag. Workers call this from
    hot loops — no await, no DB round-trip. Returns False if op_id
    unknown.

    NOTE: deliberately NOT async — the lock isn't taken here. The
    cancelled bool is a write-once flag; readers seeing a stale False
    miss one tick at most before observing True. Intentional tradeoff."""
    op = _ops.get(op_id)
    return bool(op and op.cancelled)


async def cancel_op(op_id: str) -> bool:
    """Operator-triggered cancel. Sets cancelled=True, invokes the
    op_type's cancel hook, persists state. Returns True if hook fired,
    False if op already finished or unknown.

    If the hook raises, op is marked finished with error_msg set
    (spec F10 — over-finalize on hook failure).

    Note: lock is released BEFORE awaiting the hook. Hooks may call
    back into the registry; holding the lock would deadlock. The
    resulting race window with a concurrent update_op is benign — once
    the worker observes is_cancelled() and calls finish_op, terminal
    state is reached and F1 protects against further mutation."""
    async with _lock:
        op = _ops.get(op_id)
        if op is None:
            log.warning("active_ops.cancel_unknown_op", op_id=op_id)
            return False
        if op.finished_at_epoch is not None:
            log.info("active_ops.cancel_already_finished", op_id=op_id)
            return False
        op.cancelled = True
        snapshot = _snapshot(op)

    # Invoke hook outside lock (hook may itself call back into registry).
    hook = _cancel_hooks.get(snapshot.op_type)
    if hook is None:
        log.error("active_ops.cancel_no_hook",
                  op_id=op_id, op_type=snapshot.op_type)
        # Still over-finalize: a cancellable op with no hook is a bug,
        # but we mustn't leave the op hanging.
        await finish_op(op_id, error_msg="No cancel hook registered (bug)")
        return False

    # Use module-attr lookup so test monkey-patching of _persist_op_update
    # is observed (consistent with update_op + finish_op).
    from core import active_ops as _self
    try:
        await hook(op_id)
        await _self._persist_op_update(snapshot)
        log.info("active_ops.cancelled", op_id=op_id, op_type=snapshot.op_type)
        return True
    except Exception as exc:
        log.error("active_ops.cancel_hook_failed",
                  op_id=op_id, op_type=snapshot.op_type, error=str(exc))
        await finish_op(
            op_id,
            error_msg=f"Cancel cleanup failed: {type(exc).__name__}: {exc}",
        )
        return False


# ── Listing (spec §10) ─────────────────────────────────────────────────
_GRACE_S = 30.0
_HYDRATE_CAP = 20
# +1s past _GRACE_S so older-than-cap rows are JUST outside the grace
# window — minimizes the visible "ghost time" gap on the show-all UI.
_GRACE_PRE_FINALIZE_S = _GRACE_S + 1   # 31s


async def list_ops(include_finished: bool = True) -> list[ActiveOperation]:
    """Returns running ops + ops finished within last 30s grace window.
    Older finished ops are filtered out for UI hygiene (still in DB
    until daily auto-purge — see spec §10).

    Returns defensive copies so callers cannot mutate registry state."""
    cutoff = time.time() - _GRACE_S
    async with _lock:
        result: list[ActiveOperation] = []
        for op in _ops.values():
            if op.finished_at_epoch is None:
                result.append(_snapshot(op))
            elif include_finished and op.finished_at_epoch >= cutoff:
                result.append(_snapshot(op))
        # Stable order: running first (oldest first), then finished
        # (most recent first)
        result.sort(key=lambda o: (
            o.finished_at_epoch is not None,
            o.started_at_epoch if o.finished_at_epoch is None
            else -o.finished_at_epoch,
        ))
    return result


# ── Startup hydration (spec §10, F5/F6) ────────────────────────────────
async def hydrate_on_startup() -> None:
    """Run from FastAPI lifespan BEFORE scheduler / routers come up.

    Any row with finished_at_epoch IS NULL was running when the previous
    process died. Mark up to 20 most-recent as terminated-by-restart
    visible in the 30s grace window. Older ones get
    finished_at_epoch=now()-31s so they show only via "show all" expand.

    On any failure, set _hydration_complete anyway and log critical
    (spec F6 — graceful degradation, never block startup)."""
    try:
        rows = await db_fetch_all(
            "SELECT op_id FROM active_operations "
            "WHERE finished_at_epoch IS NULL "
            "ORDER BY started_at_epoch DESC"
        )
    except Exception as exc:
        log.critical("active_ops.hydrate_query_failed", error=str(exc))
        _hydration_complete.set()
        return

    if not rows:
        log.info("active_ops.hydrate_complete", terminated_count=0)
        _hydration_complete.set()
        return

    now = time.time()
    msg = "Container restarted; operation state lost"
    for i, row in enumerate(rows):
        # Top 20: visible in 30s grace window
        finished_at = now if i < _HYDRATE_CAP else (now - _GRACE_PRE_FINALIZE_S)

        async def _do_finalize(r=row, fa=finished_at):
            await db_execute(
                "UPDATE active_operations SET "
                "finished_at_epoch=?, error_msg=? "
                "WHERE op_id=?",
                (fa, msg, r["op_id"]),
            )

        try:
            await db_write_with_retry(_do_finalize)
        except Exception as exc:
            log.error("active_ops.hydrate_update_failed",
                      op_id=row["op_id"], error=str(exc))

    # Load the surfaced (top _HYDRATE_CAP) rows into _ops so list_ops()
    # finds them within the 30s grace window. Without this, the spec's
    # "operator sees terminated-by-restart in grace window" promise is
    # unobservable: list_ops() reads only from _ops, not from DB. The
    # rows beyond _HYDRATE_CAP got back-dated finished_at_epoch outside
    # the grace window, so they're intentionally NOT loaded here — they
    # only appear via a future "show all" UI expand.
    surfaced_op_ids = [r["op_id"] for r in rows[:_HYDRATE_CAP]]
    if surfaced_op_ids:
        try:
            placeholders = ",".join("?" * len(surfaced_op_ids))
            full_rows = await db_fetch_all(
                f"SELECT * FROM active_operations WHERE op_id IN ({placeholders})",
                tuple(surfaced_op_ids),
            )
            async with _lock:
                for full_row in full_rows:
                    op = ActiveOperation.from_db_row(full_row)
                    _ops[op.op_id] = op
        except Exception as exc:
            log.error("active_ops.hydrate_load_failed", error=str(exc))

    log.warning(
        "active_ops.terminated_by_restart",
        total=len(rows),
        surfaced_in_grace=min(_HYDRATE_CAP, len(rows)),
    )
    _hydration_complete.set()
