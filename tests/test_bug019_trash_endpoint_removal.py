"""BUG-019: deprecated /api/trash/empty/status and /api/trash/restore-all/status removed."""
import pytest


@pytest.mark.asyncio
async def test_empty_status_endpoint_removed(client):
    resp = await client.get("/api/trash/empty/status")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_all_status_endpoint_removed(client):
    resp = await client.get("/api/trash/restore-all/status")
    assert resp.status_code == 404
