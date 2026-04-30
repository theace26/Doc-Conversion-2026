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


@pytest.mark.asyncio
async def test_pipeline_scan_registers_op(authed_manager_real):
    """Triggering /api/pipeline/run-now results in BOTH a pipeline.run_now
    op AND a pipeline.scan op being registered in /api/active-ops.
    pipeline.run_now is the orchestration shell; pipeline.scan is the
    actual scanner work, registered from inside
    core.lifecycle_scanner.run_lifecycle_scan.

    Uses HTTP only — same cross-loop safety as
    test_pipeline_run_now_registers_op.

    On dev machines without configured source paths, the scan exits
    very quickly (returns at the no-source-path / no-valid-roots paths
    of run_lifecycle_scan), but list_ops()'s 30s grace window means
    the op is still visible to this test either way.
    """
    resp = await authed_manager_real.post("/api/pipeline/run-now")
    assert resp.status_code == 200

    # Wait long enough for run_now's BackgroundTask to invoke
    # run_lifecycle_scan, which is where pipeline.scan registers.
    await asyncio.sleep(2.0)

    ops_resp = await authed_manager_real.get("/api/active-ops")
    assert ops_resp.status_code == 200
    ops = ops_resp.json()["ops"]
    op_types = {o["op_type"] for o in ops}
    assert "pipeline.scan" in op_types, (
        f"Expected pipeline.scan op, got types: {sorted(op_types)} (ops: {ops})"
    )

    scan_op = next(o for o in ops if o["op_type"] == "pipeline.scan")
    assert scan_op["origin_url"] == "/status.html"
    assert scan_op["cancellable"] is True
    assert scan_op["icon"] != ""


@pytest.mark.asyncio
async def test_trash_empty_registers_op_replacing_old_dict(
    authed_manager_real, sample_in_trash_source_file_id,
):
    """POST /api/trash/empty registers a trash.empty op visible in
    /api/active-ops, AND the deprecated /api/trash/empty/status facade
    still returns the legacy shape with a ``Deprecation: true`` header.

    Uses HTTP only via authed_manager_real because the endpoint spawns
    work via ``asyncio.create_task`` — under ASGITransport that runs
    in the test loop and risks the same teardown stall the real-server
    fixture was created to avoid.

    The ``sample_in_trash_source_file_id`` fixture seeds one trashed
    row so the endpoint actually invokes ``purge_all_trash`` (and thus
    registers the op).  Without it, the endpoint short-circuits with
    "status: done" when count_source_files_by_lifecycle_status returns
    0, and no op ever registers.
    """
    resp = await authed_manager_real.post("/api/trash/empty")
    assert resp.status_code == 200, f"POST /empty -> {resp.status_code}: {resp.text}"

    # Wait for asyncio.create_task to actually run + register the op
    await asyncio.sleep(0.8)

    ops_resp = await authed_manager_real.get("/api/active-ops")
    assert ops_resp.status_code == 200
    ops = ops_resp.json()["ops"]
    trash_ops = [o for o in ops if o["op_type"] == "trash.empty"]
    assert len(trash_ops) >= 1, (
        f"Expected trash.empty op, got types: "
        f"{sorted({o['op_type'] for o in ops})} (ops: {ops})"
    )
    op = trash_ops[0]
    assert op["origin_url"] == "/trash.html"
    assert op["cancellable"] is True
    assert op["icon"] != ""

    # Deprecated facade still works + carries Deprecation header
    facade = await authed_manager_real.get("/api/trash/empty/status")
    assert facade.status_code == 200
    body = facade.json()
    assert {"running", "total", "done", "errors"}.issubset(body.keys()), (
        f"Facade missing legacy keys, got: {sorted(body.keys())}"
    )
    assert facade.headers.get("Deprecation", "").lower() == "true"


@pytest.mark.asyncio
async def test_trash_restore_all_registers_op(
    authed_manager_real, sample_in_trash_source_file_id,
):
    """POST /api/trash/restore-all registers a trash.restore_all op
    visible in /api/active-ops, AND the deprecated
    /api/trash/restore-all/status facade still returns the legacy shape
    with a ``Deprecation: true`` header.

    Same shape as test_trash_empty_registers_op_replacing_old_dict
    (recon §D.2 — restore-all has the same chunk/loop semantics, no
    pre-existing cancel mechanism, and the same legacy dict pattern
    as empty-trash).
    """
    resp = await authed_manager_real.post("/api/trash/restore-all")
    assert resp.status_code == 200, f"POST /restore-all -> {resp.status_code}: {resp.text}"

    await asyncio.sleep(0.8)

    ops_resp = await authed_manager_real.get("/api/active-ops")
    assert ops_resp.status_code == 200
    ops = ops_resp.json()["ops"]
    matching = [o for o in ops if o["op_type"] == "trash.restore_all"]
    assert len(matching) >= 1, (
        f"Expected trash.restore_all op, got types: "
        f"{sorted({o['op_type'] for o in ops})} (ops: {ops})"
    )
    op = matching[0]
    assert op["origin_url"] == "/trash.html"
    assert op["cancellable"] is True
    assert op["icon"] != ""

    facade = await authed_manager_real.get("/api/trash/restore-all/status")
    assert facade.status_code == 200
    body = facade.json()
    assert {"running", "total", "done", "errors"}.issubset(body.keys()), (
        f"Facade missing legacy keys, got: {sorted(body.keys())}"
    )
    assert facade.headers.get("Deprecation", "").lower() == "true"
