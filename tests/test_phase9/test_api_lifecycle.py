"""Tests for Phase 9 API endpoints — lifecycle, trash, scanner, db_health."""

import pytest
import pytest_asyncio

from core.database import (
    create_bulk_job,
    create_version_snapshot,
    init_db,
    update_bulk_file,
    upsert_bulk_file,
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()


# ── Lifecycle endpoints ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_version_list(client, tmp_path):
    """GET /api/lifecycle/files/{id}/versions returns list."""
    job_id = await create_bulk_job(str(tmp_path / "s"), str(tmp_path / "o"))
    file_id = await upsert_bulk_file(
        job_id=job_id, source_path="/test/file.docx",
        file_ext=".docx", file_size_bytes=100, source_mtime=1000.0,
    )
    await create_version_snapshot(file_id, {
        "version_number": 1, "change_type": "initial",
        "path_at_version": "/test/file.docx",
    })

    resp = await client.get(f"/api/lifecycle/files/{file_id}/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["versions"][0]["change_type"] == "initial"


@pytest.mark.asyncio
async def test_version_newest_first(client, tmp_path):
    """Versions are returned newest first."""
    job_id = await create_bulk_job(str(tmp_path / "s"), str(tmp_path / "o"))
    file_id = await upsert_bulk_file(
        job_id=job_id, source_path="/test/order.docx",
        file_ext=".docx", file_size_bytes=100, source_mtime=1000.0,
    )
    await create_version_snapshot(file_id, {
        "version_number": 1, "change_type": "initial",
        "path_at_version": "/test/order.docx",
    })
    await create_version_snapshot(file_id, {
        "version_number": 2, "change_type": "content_change",
        "path_at_version": "/test/order.docx",
    })

    resp = await client.get(f"/api/lifecycle/files/{file_id}/versions")
    data = resp.json()
    assert data["versions"][0]["version_number"] == 2
    assert data["versions"][1]["version_number"] == 1


@pytest.mark.asyncio
async def test_diff_endpoint(client, tmp_path):
    """GET /api/lifecycle/files/{id}/diff/{v1}/{v2} returns DiffResponse shape."""
    job_id = await create_bulk_job(str(tmp_path / "s"), str(tmp_path / "o"))
    file_id = await upsert_bulk_file(
        job_id=job_id, source_path="/test/diff.docx",
        file_ext=".docx", file_size_bytes=100, source_mtime=1000.0,
    )
    await create_version_snapshot(file_id, {
        "version_number": 1, "change_type": "initial",
        "path_at_version": "/test/diff.docx",
    })
    await create_version_snapshot(file_id, {
        "version_number": 2, "change_type": "content_change",
        "path_at_version": "/test/diff.docx",
        "diff_summary": '["Added: new content"]',
    })

    resp = await client.get(f"/api/lifecycle/files/{file_id}/diff/1/2")
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "v1" in data
    assert "v2" in data


# ── Trash endpoints ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trash_list(client):
    """GET /api/trash returns paginated list."""
    resp = await client.get("/api/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_trash_restore_404(client):
    """POST /api/trash/{id}/restore returns 404 for unknown file."""
    resp = await client.post("/api/trash/nonexistent_id/restore")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trash_empty(client):
    """POST /api/trash/empty returns purged_count."""
    resp = await client.post("/api/trash/empty")
    assert resp.status_code == 200
    data = resp.json()
    assert "purged_count" in data


# ── Scanner endpoints ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scanner_status(client):
    """GET /api/scanner/status returns expected shape."""
    resp = await client.get("/api/scanner/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_running" in data
    assert "business_hours" in data


@pytest.mark.asyncio
async def test_scanner_run_now(client):
    """POST /api/scanner/run-now returns scan_run_id."""
    resp = await client.post("/api/scanner/run-now")
    assert resp.status_code == 200
    data = resp.json()
    assert "scan_run_id" in data


@pytest.mark.asyncio
async def test_scanner_runs(client):
    """GET /api/scanner/runs returns list."""
    resp = await client.get("/api/scanner/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data


# ── DB health endpoints ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_health(client):
    """GET /api/db/health returns all expected keys."""
    resp = await client.get("/api/db/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "db_size_bytes" in data
    assert "journal_mode" in data


@pytest.mark.asyncio
async def test_db_compact(client):
    """POST /api/db/compact returns message."""
    resp = await client.post("/api/db/compact")
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data


@pytest.mark.asyncio
async def test_db_integrity_check(client):
    """POST /api/db/integrity-check returns result."""
    resp = await client.post("/api/db/integrity-check")
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    assert data["result"] in ("ok", "error")


@pytest.mark.asyncio
async def test_db_stale_check(client):
    """POST /api/db/stale-check returns checks dict."""
    resp = await client.post("/api/db/stale-check")
    assert resp.status_code == 200
    data = resp.json()
    assert "checks" in data


@pytest.mark.asyncio
async def test_db_maintenance_log(client):
    """GET /api/db/maintenance-log returns entries."""
    resp = await client.get("/api/db/maintenance-log")
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
