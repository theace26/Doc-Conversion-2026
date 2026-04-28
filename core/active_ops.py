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
