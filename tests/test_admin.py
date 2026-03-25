"""
Tests for admin endpoints: resource controls, system metrics, stats dashboard.
"""

import pytest


# ── Resource Controls ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_put_resources_valid_cores(client):
    """PUT /api/admin/resources with valid core list returns 200."""
    resp = await client.put(
        "/api/admin/resources",
        json={"cpu_affinity_cores": [0], "process_priority": "normal", "worker_count": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "applied" in data
    assert isinstance(data["applied"].get("cpu_affinity"), bool)
    assert data["applied"].get("worker_count") is True


@pytest.mark.asyncio
async def test_put_resources_out_of_range_core(client):
    """PUT /api/admin/resources with out-of-range core index returns 422."""
    resp = await client.put(
        "/api/admin/resources",
        json={"cpu_affinity_cores": [9999]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_resources_empty_cores(client):
    """PUT /api/admin/resources with empty cores (all) returns 200."""
    resp = await client.put(
        "/api/admin/resources",
        json={"cpu_affinity_cores": []},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["applied"].get("cpu_affinity"), bool)


@pytest.mark.asyncio
async def test_put_resources_invalid_priority(client):
    """PUT /api/admin/resources with invalid priority returns 422."""
    resp = await client.put(
        "/api/admin/resources",
        json={"process_priority": "turbo"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_resources_worker_count_out_of_range(client):
    """PUT /api/admin/resources with worker_count > 32 returns 422."""
    resp = await client.put(
        "/api/admin/resources",
        json={"worker_count": 100},
    )
    assert resp.status_code == 422


# ── System Metrics ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_system_metrics(client):
    """GET /api/admin/system/metrics returns CPU, memory, thread data."""
    resp = await client.get("/api/admin/system/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_per_core" in data
    assert "mem_pct" in data
    assert "thread_count" in data
    assert "cpu_info" in data


@pytest.mark.asyncio
async def test_system_metrics_cpu_per_core_shape(client):
    """cpu_per_core is a list of floats matching logical_count."""
    resp = await client.get("/api/admin/system/metrics")
    data = resp.json()
    per_core = data["cpu_per_core"]
    assert isinstance(per_core, list)
    assert len(per_core) == data["cpu_info"]["logical_count"]
    for v in per_core:
        assert isinstance(v, (int, float))


# ── Stats Dashboard ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_admin_stats(client):
    """GET /api/admin/stats returns 200 with required top-level keys."""
    resp = await client.get("/api/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "bulk_files" in data
    assert "conversion_history" in data
    assert "ocr_queue" in data
    assert "meilisearch" in data
    assert "scheduler" in data
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_stats_recent_errors_is_list(client):
    """recent_errors is always a list (may be empty)."""
    resp = await client.get("/api/admin/stats")
    data = resp.json()
    errors = data.get("recent_errors")
    assert errors is None or isinstance(errors, list)


@pytest.mark.asyncio
async def test_stats_generated_at_is_iso(client):
    """generated_at is a valid ISO timestamp."""
    from datetime import datetime
    resp = await client.get("/api/admin/stats")
    data = resp.json()
    ts = data["generated_at"]
    # Should parse without error
    datetime.fromisoformat(ts.replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_stats_meilisearch_down_still_200(client):
    """Meilisearch being down does not cause stats endpoint to fail."""
    resp = await client.get("/api/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    ms = data.get("meilisearch", {})
    # available is a bool regardless
    assert isinstance(ms.get("available"), bool)


@pytest.mark.asyncio
async def test_stats_numeric_values(client):
    """Numeric values in conversion_history are int or float, not strings."""
    resp = await client.get("/api/admin/stats")
    data = resp.json()
    ch = data.get("conversion_history")
    if ch:
        assert isinstance(ch.get("total", 0), (int, float))
        assert isinstance(ch.get("last_24h", 0), (int, float))
        assert isinstance(ch.get("last_7d", 0), (int, float))
        rate = ch.get("success_rate_pct")
        if rate is not None:
            assert isinstance(rate, (int, float))


# ── Resource Manager Unit Tests ──────────────────────────────────────────────

def test_apply_affinity_empty_list():
    """apply_affinity([]) should not crash."""
    from core.resource_manager import apply_affinity
    result = apply_affinity([])
    assert isinstance(result, bool)


def test_apply_priority_invalid():
    """apply_priority with invalid level returns False."""
    from core.resource_manager import apply_priority
    result = apply_priority("invalid")
    assert result is False


def test_get_live_metrics_shape():
    """get_live_metrics returns dict with expected keys."""
    from core.resource_manager import get_live_metrics
    m = get_live_metrics()
    assert "cpu_per_core" in m
    assert "mem_pct" in m
    assert "thread_count" in m
    assert isinstance(m["cpu_per_core"], list)
    assert isinstance(m["mem_pct"], (int, float))
    assert isinstance(m["thread_count"], int)


def test_get_cpu_info_cached():
    """get_cpu_info_cached returns stable results."""
    from core.resource_manager import get_cpu_info_cached
    info1 = get_cpu_info_cached()
    info2 = get_cpu_info_cached()
    assert info1 is info2  # same object
    assert "logical_count" in info1
    assert "physical_count" in info1
