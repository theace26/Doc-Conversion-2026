"""
Tests for the history API endpoints.

GET /api/history — filter, sort, search, paginate
GET /api/history/{id}/redownload
GET /api/history/stats
"""

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


# ── Helper: run a conversion so there's something in history ─────────────────

async def _ensure_history(client, simple_docx):
    """Upload and convert a file, wait for completion. Returns batch_id."""
    with open(simple_docx, "rb") as f:
        resp = await client.post(
            "/api/convert",
            files={"files": ("simple.docx", f, "application/octet-stream")},
            data={"direction": "to_md"},
        )
    assert resp.status_code == 200
    batch_id = resp.json()["batch_id"]

    for _ in range(40):
        status_resp = await client.get(f"/api/batch/{batch_id}/status")
        if status_resp.status_code == 200:
            data = status_resp.json()
            if data.get("status") in ("done", "partial", "failed"):
                break
        await asyncio.sleep(0.5)

    return batch_id


# ── GET /api/history ─────────────────────────────────────────────────────────

async def test_history_list_returns_records(client, simple_docx):
    """GET /api/history returns a list of records."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert "total" in data
    assert data["total"] >= 1
    assert len(data["records"]) >= 1


async def test_history_filter_by_format(client, simple_docx):
    """GET /api/history?format=docx returns only DOCX records."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history?format=docx")
    assert resp.status_code == 200
    data = resp.json()
    for r in data["records"]:
        assert r["source_format"] == "docx"


async def test_history_filter_by_status(client, simple_docx):
    """GET /api/history?status=success returns only success records."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history?status=success")
    assert resp.status_code == 200
    data = resp.json()
    for r in data["records"]:
        assert r["status"] == "success"


async def test_history_search_by_filename(client, simple_docx):
    """GET /api/history?search=simple returns filename-matched records."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history?search=simple")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for r in data["records"]:
        assert "simple" in r["source_filename"].lower() or "simple" in r["output_filename"].lower()


async def test_history_sort_by_duration(client, simple_docx):
    """GET /api/history?sort=duration_asc returns sorted results."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history?sort=duration_asc")
    assert resp.status_code == 200
    data = resp.json()
    durations = [r["duration_ms"] or 0 for r in data["records"]]
    assert durations == sorted(durations)


async def test_history_pagination(client, simple_docx):
    """GET /api/history?page=1&per_page=1 returns correct slice."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history?page=1&per_page=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 1
    assert len(data["records"]) <= 1
    assert data["total_pages"] >= 1


async def test_history_response_includes_extended_fields(client, simple_docx):
    """Response includes formats_available and has_errors fields."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history")
    data = resp.json()
    assert "formats_available" in data
    assert "has_errors" in data
    assert isinstance(data["formats_available"], list)


# ── GET /api/history/{id}/redownload ─────────────────────────────────────────

async def test_redownload_returns_file(client, simple_docx):
    """GET /api/history/{id}/redownload returns 200 if output exists."""
    await _ensure_history(client, simple_docx)
    # Get the first record
    hist = await client.get("/api/history?per_page=1")
    records = hist.json()["records"]
    assert len(records) >= 1
    record_id = records[0]["id"]

    resp = await client.get(f"/api/history/{record_id}/redownload")
    # Should be 200 (file exists) or 410 (cleaned up)
    assert resp.status_code in (200, 410)


async def test_redownload_nonexistent_returns_404(client):
    """GET /api/history/99999/redownload returns 404."""
    resp = await client.get("/api/history/99999/redownload")
    assert resp.status_code == 404


# ── GET /api/history/stats ───────────────────────────────────────────────────

async def test_history_stats_returns_extended_fields(client, simple_docx):
    """GET /api/history/stats includes avg_duration_ms and by_format."""
    await _ensure_history(client, simple_docx)
    resp = await client.get("/api/history/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_conversions" in data
    assert "avg_duration_ms" in data
    assert "total_size_bytes_processed" in data
    assert "by_format" in data
    assert data["total_conversions"] >= 1
