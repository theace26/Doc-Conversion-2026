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

    run_lifecycle_scan is patched to a fast no-op for this test.  The
    scan itself is exercised by its own integration tests; here we only
    care that the BackgroundTask lifecycle (register_op / finish_op) and
    the cancel handshake work correctly end-to-end through real HTTP.
    """
    import api.routes.pipeline as _pipeline_mod

    # Replace the module-level reference that _run() closes over.
    # Both the test and the server thread share the same sys.modules
    # entry, so the patch is visible to the server thread immediately.
    _real_run_lifecycle_scan = _pipeline_mod.run_lifecycle_scan

    async def _fast_scan(force: bool = False) -> None:  # noqa: ARG001
        """No-op stand-in so the background task finishes in <1s."""
        await asyncio.sleep(0.1)

    _pipeline_mod.run_lifecycle_scan = _fast_scan
    try:
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

        # The fast scan may already be done — only cancel if still running
        if op.get("finished_at_epoch") is None:
            cancel_resp = await authed_manager_real.post(f"/api/active-ops/{op_id}/cancel")
            # 200 = cancel sent; 400 = already finished (race, also acceptable)
            assert cancel_resp.status_code in (200, 400)

        # Wait for the background _run to actually finish by polling via HTTP
        deadline = time.time() + 10
        while time.time() < deadline:
            poll_resp = await authed_manager_real.get("/api/active-ops")
            if poll_resp.status_code == 200:
                current_ops = poll_resp.json()["ops"]
                matching = [o for o in current_ops if o["op_id"] == op_id]
                if not matching or matching[0].get("finished_at_epoch") is not None:
                    break
            await asyncio.sleep(0.2)
        else:
            pytest.fail(f"op {op_id} did not finish within 10s of cancel")
    finally:
        _pipeline_mod.run_lifecycle_scan = _real_run_lifecycle_scan
