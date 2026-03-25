"""
Tests for active jobs endpoints and stop controls.
"""

import pytest

from core.stop_controller import reset_stop


@pytest.fixture(autouse=True)
def _reset_stop():
    """Ensure stop state is clean."""
    reset_stop()
    yield
    reset_stop()


@pytest.mark.asyncio
async def test_get_active_jobs_shape(client):
    """GET /api/admin/active-jobs returns correct shape."""
    resp = await client.get("/api/admin/active-jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert "running_count" in data
    assert "stop_requested" in data
    assert "bulk_jobs" in data
    assert "lifecycle_scan" in data
    assert isinstance(data["bulk_jobs"], list)
    assert isinstance(data["running_count"], int)


@pytest.mark.asyncio
async def test_stop_all_sets_flag(client):
    """POST /api/admin/stop-all sets stop flag and returns stopped list."""
    resp = await client.post("/api/admin/stop-all")
    assert resp.status_code == 200
    data = resp.json()
    assert "stopped_jobs" in data
    assert "at" in data

    # Verify flag is set via stop-state
    resp2 = await client.get("/api/admin/stop-state")
    assert resp2.status_code == 200
    assert resp2.json()["stop_requested"] is True


@pytest.mark.asyncio
async def test_reset_stop_clears_flag(client):
    """POST /api/admin/reset-stop clears stop flag."""
    # Set the flag first
    await client.post("/api/admin/stop-all")

    # Reset it
    resp = await client.post("/api/admin/reset-stop")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify it's cleared
    resp2 = await client.get("/api/admin/stop-state")
    assert resp2.json()["stop_requested"] is False


@pytest.mark.asyncio
async def test_get_stop_state(client):
    """GET /api/admin/stop-state returns current flag state."""
    resp = await client.get("/api/admin/stop-state")
    assert resp.status_code == 200
    data = resp.json()
    assert "stop_requested" in data
    assert "stop_reason" in data
    assert "registered_tasks" in data


@pytest.mark.asyncio
async def test_active_jobs_no_running(client):
    """With no active jobs, running_count is 0."""
    resp = await client.get("/api/admin/active-jobs")
    data = resp.json()
    assert data["running_count"] == 0
    assert data["stop_requested"] is False
