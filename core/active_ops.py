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
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

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
