"""End-to-end integration tests for each op_type retrofit (v0.35.0)."""
from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_pipeline_run_now_registers_op(authed_manager_real):
    """POST /api/pipeline/run-now should result in a pipeline.run_now
    op visible in /api/active-ops, and cancel should finish it cleanly.

    Uses HTTP throughout — no direct active_ops module calls — so all
    DB writes stay on the real server's event loop and never cross
    asyncio.Queue boundaries.

    The real lifecycle scan runs; cancel is sent after the op appears,
    and the scan honors the cancel signal via cancel_lifecycle_scan()
    bridged from the active_ops cancel hook.
    """
    resp = await authed_manager_real.post("/api/pipeline/run-now")
    assert resp.status_code == 200

    # Slightly longer wait — real uvicorn dispatches BackgroundTasks
    # asynchronously in its own event loop; give it time to register.
    await asyncio.sleep(1.2)

    # Poll active-ops via HTTP (all ops run in the server's loop)
    ops_resp = await authed_manager_real.get("/api/active-ops")
    assert ops_resp.status_code == 200
    ops = ops_resp.json()["ops"]
    pipeline_ops = [o for o in ops if o["op_type"] == "pipeline.run_now"]
    assert len(pipeline_ops) >= 1, f"Expected pipeline.run_now op, got: {ops}"
    op = pipeline_ops[0]
    assert op["origin_url"] == "/history.html"
    assert op["cancellable"] is True
    assert op["icon"] != ""

    op_id = op["op_id"]

    # The scan may already be done — only cancel if still running
    if op.get("finished_at_epoch") is None:
        cancel_resp = await authed_manager_real.post(f"/api/active-ops/{op_id}/cancel")
        # 200 = cancel sent; 400 = already finished (race, also acceptable)
        assert cancel_resp.status_code in (200, 400)

    # Wait for the background _run to actually finish by polling via HTTP.
    # Real lifecycle scan against /mnt/source may take several seconds even
    # when honoring cancel — allow 20s.
    deadline = time.time() + 20
    while time.time() < deadline:
        poll_resp = await authed_manager_real.get("/api/active-ops")
        if poll_resp.status_code == 200:
            current_ops = poll_resp.json()["ops"]
            matching = [o for o in current_ops if o["op_id"] == op_id]
            if not matching or matching[0].get("finished_at_epoch") is not None:
                break
        await asyncio.sleep(0.2)
    else:
        pytest.fail(f"op {op_id} did not finish within 20s of cancel")


@pytest.mark.asyncio
async def test_convert_selected_registers_op(
    authed_operator_real, sample_pending_file_id,
):
    """POST /api/pipeline/convert-selected with a valid pending file_id
    registers a pipeline.convert_selected op in /api/active-ops with
    cancellable=True.

    Uses HTTP throughout — no direct active_ops module calls — so all
    DB writes stay on the real server's event loop and never cross
    asyncio.Queue boundaries. Same pattern as
    test_pipeline_run_now_registers_op.

    The conversion worker will fail (source file doesn't exist) but
    that's fine — the op is registered before the worker runs and
    list_ops() returns finished ops within the 30s grace window, so
    the assertion holds either way.
    """
    resp = await authed_operator_real.post(
        "/api/pipeline/convert-selected",
        json={"file_ids": [sample_pending_file_id]},
    )
    assert resp.status_code == 200, f"convert-selected returned {resp.status_code}: {resp.text}"

    # Real uvicorn dispatches BackgroundTasks asynchronously in its
    # own event loop; same 1.2s wait as Task 14's run-now test.
    await asyncio.sleep(1.2)

    ops_resp = await authed_operator_real.get("/api/active-ops")
    assert ops_resp.status_code == 200
    ops = ops_resp.json()["ops"]
    cs_ops = [o for o in ops if o["op_type"] == "pipeline.convert_selected"]
    assert len(cs_ops) >= 1, f"Expected pipeline.convert_selected op, got: {ops}"
    op = cs_ops[0]
    assert op["origin_url"] == "/history.html"
    assert op["cancellable"] is True
    assert op["icon"] != ""
