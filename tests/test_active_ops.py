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


@pytest.mark.asyncio
async def test_cancel_op_invokes_registered_hook(client):
    from core import active_ops

    hook_called_with: list[str] = []

    async def my_hook(op_id: str) -> None:
        hook_called_with.append(op_id)

    active_ops.register_cancel_hook("pipeline.run_now", my_hook)

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
        cancellable=True,
    )

    cancelled = await active_ops.cancel_op(op_id)
    assert cancelled is True
    assert hook_called_with == [op_id]

    # cancelled flag is set in-memory
    assert active_ops.is_cancelled(op_id) is True

    op = await active_ops.get_op(op_id)
    assert op.cancelled is True


@pytest.mark.asyncio
async def test_cancel_op_on_finished_returns_false(client):
    from core import active_ops

    async def hook(op_id: str) -> None: ...
    active_ops.register_cancel_hook("pipeline.run_now", hook)

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
        cancellable=True,
    )
    await active_ops.finish_op(op_id)

    result = await active_ops.cancel_op(op_id)
    assert result is False


@pytest.mark.asyncio
async def test_cancel_hook_raises_marks_op_failed_and_finished(client):
    """Spec F10 — over-finalize on hook failure."""
    from core import active_ops

    async def bad_hook(op_id: str) -> None:
        raise RuntimeError("native cancel failed")

    active_ops.register_cancel_hook("pipeline.run_now", bad_hook)

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
        cancellable=True,
    )

    await active_ops.cancel_op(op_id)

    op = await active_ops.get_op(op_id)
    assert op.finished_at_epoch is not None
    assert op.error_msg is not None
    assert "native cancel failed" in op.error_msg


def test_is_cancelled_synchronous():
    """is_cancelled MUST be synchronous so workers can call it from
    hot loops without awaiting."""
    from core import active_ops
    import inspect
    assert not inspect.iscoroutinefunction(active_ops.is_cancelled)


@pytest.mark.asyncio
async def test_list_ops_returns_running_plus_recently_finished(client):
    from core import active_ops

    op_run = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="x@x",
    )

    op_done = await active_ops.register_op(
        op_type="pipeline.run_now", label="Y", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    await active_ops.finish_op(op_done)   # finished now → in 30s window

    ops = await active_ops.list_ops()
    op_ids = {o.op_id for o in ops}
    assert op_run in op_ids
    assert op_done in op_ids


@pytest.mark.asyncio
async def test_list_ops_excludes_finished_older_than_30s(client):
    """Manually back-date a finished_at_epoch to 31s ago and expect it
    to be excluded from list_ops()."""
    from core import active_ops
    from core.db.connection import db_execute, db_write_with_retry

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="Z", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    await active_ops.finish_op(op_id)

    # Back-date in DB
    old_finish = time.time() - 31

    async def _do_backdate() -> None:
        await db_execute(
            "UPDATE active_operations SET finished_at_epoch=? WHERE op_id=?",
            (old_finish, op_id),
        )

    await db_write_with_retry(_do_backdate)
    # And in in-memory state
    async with active_ops._lock:
        active_ops._ops[op_id].finished_at_epoch = old_finish

    ops = await active_ops.list_ops()
    op_ids = {o.op_id for o in ops}
    assert op_id not in op_ids


@pytest.mark.asyncio
async def test_list_ops_orders_running_before_finished(client):
    """Spec §5: stable order — running ops first, finished ops after."""
    from core import active_ops

    op_a = await active_ops.register_op(
        op_type="pipeline.run_now", label="A", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    op_b = await active_ops.register_op(
        op_type="pipeline.run_now", label="B", icon="⚙",
        origin_url="/", started_by="x@x",
    )
    await active_ops.finish_op(op_b)   # finished
    op_c = await active_ops.register_op(
        op_type="pipeline.run_now", label="C", icon="⚙",
        origin_url="/", started_by="x@x",
    )

    ops = await active_ops.list_ops()
    op_ids = [o.op_id for o in ops]
    # Both running ops appear before the finished one
    assert op_ids.index(op_a) < op_ids.index(op_b)
    assert op_ids.index(op_c) < op_ids.index(op_b)


@pytest.mark.asyncio
async def test_hydrate_marks_running_rows_as_terminated_by_restart(client):
    """Pre-seed 5 rows with finished_at_epoch=NULL; hydrate must
    flag them as terminated-by-restart."""
    from core import active_ops
    from core.db.connection import db_execute, db_write_with_retry

    # Reset state: clear any prior in-memory ops, clear hydration event
    async with active_ops._lock:
        active_ops._ops.clear()
    active_ops._hydration_complete.clear()

    # Seed 5 running rows directly
    now = time.time()
    for i in range(5):
        async def _do_seed(i=i, now=now):
            await db_execute(
                "INSERT INTO active_operations "
                "(op_id, op_type, label, icon, origin_url, started_by, "
                "started_at_epoch, last_progress_at_epoch) "
                "VALUES (?, 'pipeline.run_now', 'X', '⚙', '/', 'x@x', ?, ?)",
                (f"hydrate-test-{i}", now - i, now - i),
            )
        await db_write_with_retry(_do_seed)

    # Run hydration
    await active_ops.hydrate_on_startup()
    assert active_ops._hydration_complete.is_set()

    # All 5 rows now have finished_at_epoch set
    rows = await db_fetch_all(
        "SELECT op_id, finished_at_epoch, error_msg "
        "FROM active_operations WHERE op_id LIKE 'hydrate-test-%'"
    )
    assert len(rows) == 5
    for r in rows:
        assert r["finished_at_epoch"] is not None
        assert "restart" in (r["error_msg"] or "").lower()


@pytest.mark.asyncio
async def test_hydrate_caps_visible_at_20(client):
    """If 25 rows were running, the top 20 (most-recent) get a
    finished_at_epoch within the 30s grace window; older 5 get
    finished_at_epoch=now-31s so they fall outside."""
    from core import active_ops
    from core.db.connection import db_execute, db_write_with_retry

    async with active_ops._lock:
        active_ops._ops.clear()
    active_ops._hydration_complete.clear()

    # Clean any leftover hydrate-cap-* rows from prior test runs
    async def _do_cleanup():
        await db_execute(
            "DELETE FROM active_operations WHERE op_id LIKE 'hydrate-cap-%'"
        )
    await db_write_with_retry(_do_cleanup)

    now = time.time()
    for i in range(25):
        async def _do_seed(i=i, now=now):
            await db_execute(
                "INSERT INTO active_operations "
                "(op_id, op_type, label, icon, origin_url, started_by, "
                "started_at_epoch, last_progress_at_epoch) "
                "VALUES (?, 'pipeline.run_now', 'X', '⚙', '/', 'x@x', ?, ?)",
                (f"hydrate-cap-{i:02d}", now - i, now - i),
            )
        await db_write_with_retry(_do_seed)

    await active_ops.hydrate_on_startup()

    rows = await db_fetch_all(
        "SELECT op_id, finished_at_epoch FROM active_operations "
        "WHERE op_id LIKE 'hydrate-cap-%' ORDER BY started_at_epoch DESC"
    )
    assert len(rows) == 25
    # Compare against current time (not the pre-seed `now`): seeding
    # 25 rows through the single-writer queue can take seconds, so
    # `now` may be 5-10s stale by the time we reach the assertions.
    check_at = time.time()
    # Top 20 (most-recent — i=0..19) within grace window
    for r in rows[:20]:
        assert (check_at - r["finished_at_epoch"]) < 30
    # Bottom 5 (i=20..24) outside grace window
    for r in rows[20:]:
        assert (check_at - r["finished_at_epoch"]) > 30


@pytest.mark.asyncio
async def test_hydrate_failure_does_not_crash(client):
    """Spec F6 — hydration failure logs critical and sets event anyway,
    so workers can still register (degraded mode)."""
    from core import active_ops
    from unittest.mock import patch

    async with active_ops._lock:
        active_ops._ops.clear()
    active_ops._hydration_complete.clear()

    with patch("core.active_ops.db_fetch_all",
               side_effect=RuntimeError("db gone")):
        await active_ops.hydrate_on_startup()

    # Event still set (degraded mode)
    assert active_ops._hydration_complete.is_set()


@pytest.mark.asyncio
async def test_hydrate_makes_surfaced_rows_visible_via_list_ops(client):
    """Spec §10/§13: terminated-by-restart rows must appear in list_ops()
    within the 30s grace window — i.e. hydrate must populate _ops, not
    just write to DB. Caught a critical bug where the original Task 8
    only wrote to DB, leaving _ops empty so list_ops returned [] after
    a restart and the operator never saw the restart-terminated rows."""
    from core import active_ops
    from core.db.connection import db_execute, db_write_with_retry

    # Reset state
    async with active_ops._lock:
        active_ops._ops.clear()
    active_ops._hydration_complete.clear()

    # Wipe any leftover test rows
    async def _do_cleanup():
        await db_execute(
            "DELETE FROM active_operations WHERE op_id LIKE 'hydrate-vis-%'"
        )
    await db_write_with_retry(_do_cleanup)

    # Seed 3 running rows
    now = time.time()
    for i in range(3):
        async def _do_seed(i=i, now=now):
            await db_execute(
                "INSERT INTO active_operations "
                "(op_id, op_type, label, icon, origin_url, started_by, "
                "started_at_epoch, last_progress_at_epoch) "
                "VALUES (?, 'pipeline.run_now', ?, '⚙', '/', 'x@x', ?, ?)",
                (f"hydrate-vis-{i}", f"label-{i}", now - i, now - i),
            )
        await db_write_with_retry(_do_seed)

    await active_ops.hydrate_on_startup()

    # The 3 surfaced rows MUST appear in list_ops()
    ops = await active_ops.list_ops()
    op_ids = {o.op_id for o in ops}
    for i in range(3):
        assert f"hydrate-vis-{i}" in op_ids, (
            f"hydrate-vis-{i} missing from list_ops — "
            "hydrate did not populate _ops, breaks 30s grace window UI"
        )

    # And each surfaced row carries the restart marker
    surfaced = [o for o in ops if o.op_id.startswith("hydrate-vis-")]
    for op in surfaced:
        assert op.error_msg is not None
        assert "restart" in op.error_msg.lower()
        assert op.finished_at_epoch is not None


@pytest.mark.asyncio
async def test_purge_deletes_rows_older_than_7d_excludes_running(client):
    from core import active_ops
    from core.db.connection import db_execute, db_write_with_retry

    now = time.time()
    eight_days_ago = now - (8 * 24 * 3600)
    six_days_ago = now - (6 * 24 * 3600)

    # Wipe leftover purge-* rows from prior runs
    async def _do_cleanup():
        await db_execute(
            "DELETE FROM active_operations WHERE op_id LIKE 'purge-%'"
        )
    await db_write_with_retry(_do_cleanup)

    # Seed: 1 old finished, 1 recent finished, 1 running
    rows = [
        ("purge-old", eight_days_ago, eight_days_ago),
        ("purge-recent", now, six_days_ago),
        ("purge-running", None, now),
    ]
    for op_id, finished, started in rows:
        async def _do_seed(o=op_id, f=finished, s=started):
            await db_execute(
                "INSERT INTO active_operations "
                "(op_id, op_type, label, icon, origin_url, started_by, "
                "started_at_epoch, last_progress_at_epoch, "
                "finished_at_epoch) "
                "VALUES (?, 'pipeline.run_now', 'X', '⚙', '/', 'x@x', "
                "?, ?, ?)",
                (o, s, s, f),
            )
        await db_write_with_retry(_do_seed)

    deleted = await active_ops.purge_old_active_ops()
    assert deleted == 1   # only purge-old qualifies

    remaining = await db_fetch_all(
        "SELECT op_id FROM active_operations "
        "WHERE op_id LIKE 'purge-%'"
    )
    op_ids = {r["op_id"] for r in remaining}
    assert op_ids == {"purge-recent", "purge-running"}
