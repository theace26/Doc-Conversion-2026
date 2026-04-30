"""HTTP route tests for /api/active-ops (v0.35.0)."""
from __future__ import annotations

import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app


# ── In-memory reset between tests ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_active_ops():
    """Clear in-memory active-ops state before and after each test."""
    from core import active_ops
    active_ops._ops.clear()
    active_ops._last_persist_at.clear()
    active_ops._cancel_hooks.clear()
    yield
    active_ops._ops.clear()
    active_ops._last_persist_at.clear()
    active_ops._cancel_hooks.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_active_ops_requires_operator_role(monkeypatch):
    """Anonymous request → 401 when DEV_BYPASS_AUTH is disabled."""
    import core.auth
    monkeypatch.setattr(core.auth, "DEV_BYPASS_AUTH", False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/active-ops")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_active_ops_returns_running_ops(authed_operator):
    """authed_operator yields an AsyncClient with operator role (via DEV_BYPASS_AUTH)."""
    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="Test op", icon="⚙",
        origin_url="/history.html", started_by="op@test",
    )
    try:
        resp = await authed_operator.get("/api/active-ops")
        assert resp.status_code == 200
        body = resp.json()
        assert "ops" in body
        op_ids = {o["op_id"] for o in body["ops"]}
        assert op_id in op_ids

        # Verify shape of one op
        op_dict = next(o for o in body["ops"] if o["op_id"] == op_id)
        assert op_dict["op_type"] == "pipeline.run_now"
        assert op_dict["label"] == "Test op"
        assert op_dict["origin_url"] == "/history.html"
        assert op_dict["finished_at_epoch"] is None
        assert op_dict["cancellable"] is False
    finally:
        await active_ops.finish_op(op_id)


@pytest.mark.asyncio
async def test_get_active_ops_excludes_finished_older_than_30s(authed_operator):
    """Spec §10 — 30s grace window."""
    from core import active_ops
    from core.db.connection import db_write_with_retry, db_execute

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="op@test",
    )
    await active_ops.finish_op(op_id)
    # Back-date in DB and in-memory
    old = time.time() - 31

    async def _backdate():
        await db_execute(
            "UPDATE active_operations SET finished_at_epoch=? WHERE op_id=?",
            (old, op_id),
        )

    await db_write_with_retry(_backdate)
    async with active_ops._lock:
        active_ops._ops[op_id].finished_at_epoch = old

    resp = await authed_operator.get("/api/active-ops")
    op_ids = {o["op_id"] for o in resp.json()["ops"]}
    assert op_id not in op_ids


@pytest.mark.asyncio
async def test_get_active_ops_no_cache_header(authed_operator):
    resp = await authed_operator.get("/api/active-ops")
    cc = resp.headers.get("cache-control", "").lower()
    assert "no-cache" in cc


@pytest.mark.asyncio
async def test_cancel_requires_manager_role(authed_operator, authed_manager):
    """Operator role can read but not cancel; Manager can cancel.
    authed_manager is a Manager-role-equivalent fixture."""
    from core import active_ops

    async def hook(op_id: str) -> None: ...
    active_ops.register_cancel_hook("pipeline.run_now", hook)

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="op@test",
        cancellable=True,
    )

    # Operator → 403
    resp_op = await authed_operator.post(f"/api/active-ops/{op_id}/cancel")
    assert resp_op.status_code in (401, 403)

    # Manager → 200
    resp_mgr = await authed_manager.post(f"/api/active-ops/{op_id}/cancel")
    assert resp_mgr.status_code == 200
    body = resp_mgr.json()
    assert body["cancelled"] is True


@pytest.mark.asyncio
async def test_cancel_404_on_unknown_op_id(authed_manager):
    resp = await authed_manager.post(
        "/api/active-ops/00000000-0000-0000-0000-000000000000/cancel"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_400_on_already_finished(authed_manager):
    from core import active_ops

    async def hook(op_id: str) -> None: ...
    active_ops.register_cancel_hook("pipeline.run_now", hook)

    op_id = await active_ops.register_op(
        op_type="pipeline.run_now", label="X", icon="⚙",
        origin_url="/", started_by="op@test",
        cancellable=True,
    )
    await active_ops.finish_op(op_id)

    resp = await authed_manager.post(f"/api/active-ops/{op_id}/cancel")
    assert resp.status_code == 400
    assert "finished" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cancel_400_on_uncancellable(authed_manager):
    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="db.backup", label="DB Backup", icon="💾",
        origin_url="/settings.html", started_by="op@test",
        cancellable=False,
    )
    try:
        resp = await authed_manager.post(f"/api/active-ops/{op_id}/cancel")
        assert resp.status_code == 400
        assert "uncancellable" in resp.json()["detail"].lower()
    finally:
        await active_ops.finish_op(op_id)
