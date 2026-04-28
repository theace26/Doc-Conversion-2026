"""Unit tests for core.active_ops — Active Operations Registry (v0.35.0)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest

from core.database import db_fetch_all, db_fetch_one


@pytest.mark.asyncio
async def test_migration_v29_creates_active_operations_table(client):
    """Migration v29 must create the table with the schema in spec §3.

    Depends on the session-scoped ``client`` fixture so ``init_db()`` runs
    (and applies all _MIGRATIONS) against the test temp DB before assertions.
    """
    # Schema check: table exists
    row = await db_fetch_one(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='active_operations'"
    )
    assert row is not None, "active_operations table not created"

    # Column shape (PRAGMA table_info returns rows of cid/name/type/...)
    cols = await db_fetch_all("PRAGMA table_info(active_operations)")
    col_map = {c["name"]: c["type"] for c in cols}

    expected = {
        "op_id": "TEXT",
        "op_type": "TEXT",
        "label": "TEXT",
        "icon": "TEXT",
        "origin_url": "TEXT",
        "started_by": "TEXT",
        "started_at_epoch": "REAL",
        "last_progress_at_epoch": "REAL",
        "finished_at_epoch": "REAL",
        "total": "INTEGER",
        "done": "INTEGER",
        "errors": "INTEGER",
        "error_msg": "TEXT",
        "cancelled": "INTEGER",
        "cancellable": "INTEGER",
        "cancel_url": "TEXT",
        "extra_json": "TEXT",
    }
    for col, typ in expected.items():
        assert col in col_map, f"missing column: {col}"
        assert col_map[col] == typ, (
            f"column {col} type mismatch: expected {typ}, got {col_map[col]}"
        )

    # Indexes — partial indexes for running and finished
    idx = await db_fetch_all(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='active_operations'"
    )
    idx_names = {r["name"] for r in idx}
    assert "idx_active_ops_running" in idx_names
    assert "idx_active_ops_finished_at" in idx_names


def test_active_operation_dataclass_round_trip():
    """Dataclass converts to dict and back losslessly via to_db / from_db."""
    from core.active_ops import ActiveOperation

    op = ActiveOperation(
        op_id="abc-123",
        op_type="pipeline.run_now",
        label="Force Transcribe",
        icon="⚙",
        origin_url="/history.html",
        started_by="op@example.com",
        started_at_epoch=1700000000.0,
        last_progress_at_epoch=1700000005.0,
        cancellable=True,
        extra={"scan_run_id": 42},
    )
    row = op.to_db_row()
    assert row["op_id"] == "abc-123"
    assert row["cancellable"] == 1   # bool → int
    assert json.loads(row["extra_json"]) == {"scan_run_id": 42}

    rebuilt = ActiveOperation.from_db_row(row)
    assert rebuilt == op


def test_op_type_whitelist_rejects_unknown():
    """register_op() with an unknown op_type raises ValueError."""
    from core.active_ops import OP_TYPES
    assert "pipeline.run_now" in OP_TYPES
    assert "pipeline.convert_selected" in OP_TYPES
    assert "pipeline.scan" in OP_TYPES
    assert "trash.empty" in OP_TYPES
    assert "trash.restore_all" in OP_TYPES
    assert "search.rebuild_index" in OP_TYPES
    assert "analysis.rebuild" in OP_TYPES
    assert "db.backup" in OP_TYPES
    assert "db.restore" in OP_TYPES
    assert "bulk.job" in OP_TYPES
    assert "bogus.op" not in OP_TYPES


@pytest.mark.asyncio
async def test_register_op_returns_unique_uuid_and_persists(client):
    """register_op returns a UUID4 string, persists to DB,
    and adds the op to the in-memory dict."""
    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now",
        label="Force Transcribe",
        icon="⚙",
        origin_url="/history.html",
        started_by="test@example.com",
        cancellable=True,
        cancel_url=None,
        extra={"scan_run_id": 99},
    )
    assert isinstance(op_id, str)
    assert len(op_id) == 36   # uuid4 length

    # Two registrations get different IDs
    op_id_2 = await active_ops.register_op(
        op_type="pipeline.run_now",
        label="X",
        icon="⚙",
        origin_url="/history.html",
        started_by="test@example.com",
    )
    assert op_id_2 != op_id

    # Persisted to DB
    row = await db_fetch_one(
        "SELECT * FROM active_operations WHERE op_id=?", (op_id,)
    )
    assert row is not None
    assert row["label"] == "Force Transcribe"
    assert row["cancellable"] == 1
    assert json.loads(row["extra_json"])["scan_run_id"] == 99
    assert row["finished_at_epoch"] is None    # still running
    assert row["total"] == 0
    assert row["done"] == 0


@pytest.mark.asyncio
async def test_register_op_unknown_op_type_raises():
    from core import active_ops
    with pytest.raises(ValueError, match="unknown op_type"):
        await active_ops.register_op(
            op_type="bogus.op",
            label="X", icon="?",
            origin_url="/", started_by="x@x",
        )


@pytest.mark.asyncio
async def test_register_op_cancellable_without_hook_raises():
    """If cancellable=True but no cancel hook is registered for the
    op_type, register_op refuses (spec F9). The hook itself is registered
    by the subsystem at module import — for this test, we use an op_type
    we know hasn't had its hook registered yet (use db.backup which is
    uncancellable; flip cancellable=True to force the error)."""
    from core import active_ops
    with pytest.raises(RuntimeError, match="no cancel hook"):
        await active_ops.register_op(
            op_type="db.backup",
            label="X", icon="?",
            origin_url="/", started_by="x@x",
            cancellable=True,
        )


@pytest.mark.asyncio
async def test_update_op_modifies_in_memory_immediately(client):
    """update_op reflects in-memory state synchronously — no waiting
    for the DB debouncer."""
    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )

    await active_ops.update_op(op_id, total=100, done=10)

    # In-memory check (synchronous via lock)
    op = await active_ops.get_op(op_id)
    assert op is not None
    assert op.total == 100
    assert op.done == 10


@pytest.mark.asyncio
async def test_update_op_debounces_db_writes(client):
    """100 update_op calls within 1.5s produce ≤ 2 DB writes
    (1 throttled + the final flush on subsequent update)."""
    from core import active_ops
    from core.active_ops import ActiveOperation

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )

    write_count = 0
    real_persist = active_ops._persist_op_update

    async def counting_persist(op: ActiveOperation) -> None:
        nonlocal write_count
        write_count += 1
        await real_persist(op)

    active_ops._persist_op_update = counting_persist
    try:
        for i in range(100):
            await active_ops.update_op(op_id, done=i)
        # Wait briefly for any in-flight debounced write
        await asyncio.sleep(0.1)
    finally:
        active_ops._persist_op_update = real_persist

    # First write happens (no prior throttle), subsequent throttled.
    # Allow up to 2 writes (initial + one throttled boundary cross).
    assert write_count <= 2, f"expected ≤2 DB writes, got {write_count}"


@pytest.mark.asyncio
async def test_update_op_first_error_forces_immediate_flush(client):
    """Going from errors=0 to errors>0 flushes synchronously (operator
    alerting is non-negotiable)."""
    from core import active_ops
    from core.active_ops import ActiveOperation

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )

    write_count = 0
    real_persist = active_ops._persist_op_update

    async def counting_persist(op: ActiveOperation) -> None:
        nonlocal write_count
        write_count += 1
        await real_persist(op)

    active_ops._persist_op_update = counting_persist
    try:
        # 5 done-only updates (debounced)
        for i in range(5):
            await active_ops.update_op(op_id, done=i)
        write_count_before_error = write_count

        # First error — immediate flush
        await active_ops.update_op(op_id, done=5, errors=1)
    finally:
        active_ops._persist_op_update = real_persist

    assert write_count > write_count_before_error, (
        "first-error update did not force a flush"
    )


@pytest.mark.asyncio
async def test_finish_op_marks_finished_at_epoch(client):
    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    await active_ops.update_op(op_id, total=100, done=100)
    before = time.time()
    await active_ops.finish_op(op_id)
    after = time.time()

    op = await active_ops.get_op(op_id)
    assert op.finished_at_epoch is not None
    assert before <= op.finished_at_epoch <= after

    # Persisted to DB
    row = await db_fetch_one(
        "SELECT finished_at_epoch FROM active_operations WHERE op_id=?",
        (op_id,),
    )
    assert row["finished_at_epoch"] is not None


@pytest.mark.asyncio
async def test_finish_op_with_error_msg(client):
    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    await active_ops.finish_op(op_id, error_msg="failed: connection lost")

    op = await active_ops.get_op(op_id)
    assert op.error_msg == "failed: connection lost"
    assert op.finished_at_epoch is not None


@pytest.mark.asyncio
async def test_update_after_finish_is_noop(client):
    """Spec F1: update_op on a finished row is a no-op + WARN.

    Sets a non-zero baseline before finish so the assertion proves
    the post-finish update was REJECTED (not just trivially zero)."""
    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    await active_ops.update_op(op_id, done=50)   # baseline
    await active_ops.finish_op(op_id)
    finished_at = (await active_ops.get_op(op_id)).finished_at_epoch

    # Try to update — should be ignored, baseline preserved
    await active_ops.update_op(op_id, done=999)
    op = await active_ops.get_op(op_id)
    assert op.done == 50   # baseline preserved, 999 rejected
    assert op.finished_at_epoch == finished_at   # not reopened


@pytest.mark.asyncio
async def test_finish_op_twice_is_noop(client):
    """Second finish_op on same op is WARN-only — no DB write, no
    overwrite of error_msg, no timestamp change."""
    from core import active_ops
    from core.active_ops import ActiveOperation

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    await active_ops.finish_op(op_id, error_msg="first")
    finished_at_1 = (await active_ops.get_op(op_id)).finished_at_epoch

    write_count = 0
    real_persist = active_ops._persist_op_update

    async def counting_persist(op: ActiveOperation) -> None:
        nonlocal write_count
        write_count += 1
        await real_persist(op)

    active_ops._persist_op_update = counting_persist
    try:
        await active_ops.finish_op(op_id, error_msg="second")
    finally:
        active_ops._persist_op_update = real_persist

    op = await active_ops.get_op(op_id)
    assert op.error_msg == "first"   # second call did NOT overwrite
    assert op.finished_at_epoch == finished_at_1   # timestamp unchanged
    assert write_count == 0   # no second DB write
