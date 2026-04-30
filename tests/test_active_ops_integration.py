"""End-to-end integration tests for each op_type retrofit (v0.35.0)."""
from __future__ import annotations

import asyncio

import pytest

from core import active_ops


@pytest.mark.skip(
    reason=(
        "Hangs under ASGITransport. FastAPI BackgroundTasks runs `_run` in "
        "the same event loop as the test, and `run_lifecycle_scan` does "
        "not promptly honor the active_ops cancel flag — it polls "
        "`is_run_now_cancelled()` only at scan-loop checkpoints, which "
        "may not fire in test conditions. Pytest teardown then waits on "
        "the still-running task. The retrofit code itself is verified by "
        "tests/test_active_ops_endpoint.py + tests/test_active_ops.py (70 "
        "tests covering the registry path). Re-enable once the scan loop "
        "exposes a test-mode short-circuit or this fixture mocks "
        "run_lifecycle_scan."
    )
)
@pytest.mark.asyncio
async def test_pipeline_run_now_registers_op(authed_manager):
    """POST /api/pipeline/run-now should result in a pipeline.run_now
    op visible in /api/active-ops."""
    resp = await authed_manager.post("/api/pipeline/run-now")
    assert resp.status_code == 200

    # Brief wait for the BackgroundTasks dispatcher to fire
    await asyncio.sleep(0.5)

    ops = await active_ops.list_ops()
    pipeline_ops = [o for o in ops if o.op_type == "pipeline.run_now"]
    assert len(pipeline_ops) >= 1
    op = pipeline_ops[0]
    assert op.origin_url == "/history.html"
    assert op.cancellable is True
    assert op.icon != ""

    # Don't leave the op hanging — cancel for test cleanup
    await active_ops.cancel_op(op.op_id)
