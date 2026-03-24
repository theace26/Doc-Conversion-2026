"""
Tests for bulk path safety integration — scanner, DB, API.

Covers:
  - Scanner records path issues in DB
  - bulk_jobs counters updated
  - Path issues API endpoints
  - CSV export
"""

import pytest
from pathlib import Path

from core.database import (
    create_bulk_job,
    get_bulk_job,
    get_path_issue_summary,
    get_path_issues,
    init_db,
    record_path_issue,
    get_collision_group,
)


@pytest.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("core.database.DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret-for-path-safety!")
    await init_db()
    yield


# ── DB helper tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_path_issue():
    job_id = await create_bulk_job("/src", "/out")
    issue_id = await record_path_issue(
        job_id=job_id,
        issue_type="path_too_long",
        source_path="/src/very/long/path.docx",
        output_path="/out/very/long/path.md",
        resolution="skipped",
    )
    assert issue_id
    issues = await get_path_issues(job_id)
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "path_too_long"


@pytest.mark.asyncio
async def test_record_collision():
    job_id = await create_bulk_job("/src", "/out")
    await record_path_issue(
        job_id=job_id,
        issue_type="collision",
        source_path="/src/report.docx",
        output_path="/out/report.md",
        collision_group="/out/report.md",
        collision_peer="/src/report.pdf",
        resolution="renamed",
        resolved_path="/out/report.docx.md",
    )
    await record_path_issue(
        job_id=job_id,
        issue_type="collision",
        source_path="/src/report.pdf",
        output_path="/out/report.md",
        collision_group="/out/report.md",
        collision_peer="/src/report.docx",
        resolution="renamed",
        resolved_path="/out/report.pdf.md",
    )
    issues = await get_path_issues(job_id, issue_type="collision")
    assert len(issues) == 2


@pytest.mark.asyncio
async def test_path_issue_summary():
    job_id = await create_bulk_job("/src", "/out")
    await record_path_issue(job_id=job_id, issue_type="path_too_long",
                             source_path="/src/a.docx", resolution="skipped")
    await record_path_issue(job_id=job_id, issue_type="collision",
                             source_path="/src/b.docx", resolution="renamed")
    await record_path_issue(job_id=job_id, issue_type="collision",
                             source_path="/src/b.pdf", resolution="renamed")
    await record_path_issue(job_id=job_id, issue_type="case_collision",
                             source_path="/src/C.docx", resolution="renamed")

    summary = await get_path_issue_summary(job_id)
    assert summary["path_too_long"] == 1
    assert summary["collision"] == 2
    assert summary["case_collision"] == 1
    assert summary["total"] == 4


@pytest.mark.asyncio
async def test_collision_group():
    job_id = await create_bulk_job("/src", "/out")
    await record_path_issue(
        job_id=job_id, issue_type="collision",
        source_path="/src/report.docx", collision_group="/out/report.md",
        resolution="renamed",
    )
    await record_path_issue(
        job_id=job_id, issue_type="collision",
        source_path="/src/report.pdf", collision_group="/out/report.md",
        resolution="renamed",
    )
    group = await get_collision_group(job_id, "/out/report.md")
    assert len(group) == 2


@pytest.mark.asyncio
async def test_filter_by_issue_type():
    job_id = await create_bulk_job("/src", "/out")
    await record_path_issue(job_id=job_id, issue_type="path_too_long",
                             source_path="/src/a.docx")
    await record_path_issue(job_id=job_id, issue_type="collision",
                             source_path="/src/b.docx")

    too_long = await get_path_issues(job_id, issue_type="path_too_long")
    assert len(too_long) == 1
    collisions = await get_path_issues(job_id, issue_type="collision")
    assert len(collisions) == 1


# ── API endpoint tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_path_issues_api():
    job_id = await create_bulk_job("/src", "/out")
    await record_path_issue(
        job_id=job_id, issue_type="collision",
        source_path="/src/report.docx", resolution="renamed",
    )

    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/bulk/jobs/{job_id}/path-issues")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "issues" in data
        assert len(data["issues"]) == 1


@pytest.mark.asyncio
async def test_path_issues_export_csv():
    job_id = await create_bulk_job("/src", "/out")
    await record_path_issue(
        job_id=job_id, issue_type="path_too_long",
        source_path="/src/long.docx",
        output_path="/out/long.md",
        resolution="skipped",
    )

    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/bulk/jobs/{job_id}/path-issues/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        content = resp.text
        assert "path_too_long" in content
        assert "/src/long.docx" in content


@pytest.mark.asyncio
async def test_path_issues_404_for_missing_job():
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/bulk/jobs/nonexistent/path-issues")
        assert resp.status_code == 404
