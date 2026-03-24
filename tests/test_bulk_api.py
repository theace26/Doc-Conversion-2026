"""Tests for the bulk job API endpoints."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from core.database import init_db, create_bulk_job, update_bulk_job_status


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


class TestCreateJob:
    async def test_create_job_returns_job_id(self, client, tmp_path):
        """POST /api/bulk/jobs creates a job and returns job_id."""
        source = tmp_path / "source"
        source.mkdir()
        output = tmp_path / "output"

        # Patch BulkJob.run to prevent actual execution
        with patch("api.routes.bulk.BulkJob") as MockJob:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock()
            MockJob.return_value = mock_instance

            resp = await client.post("/api/bulk/jobs", json={
                "source_path": str(source),
                "output_path": str(output),
                "worker_count": 2,
                "fidelity_tier": 2,
                "ocr_mode": "auto",
                "include_adobe": True,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "stream_url" in data
        assert data["stream_url"].startswith("/api/bulk/jobs/")

    async def test_create_job_invalid_source(self, client):
        """422 if source path doesn't exist."""
        resp = await client.post("/api/bulk/jobs", json={
            "source_path": "/nonexistent/path",
            "output_path": "/tmp/output",
        })
        assert resp.status_code == 422

    async def test_create_job_conflict(self, client, tmp_path):
        """409 if a job is already running."""
        source = tmp_path / "source"
        source.mkdir()

        # Create a running job first
        job_id = await create_bulk_job(str(source), "/out")
        await update_bulk_job_status(job_id, "running")

        resp = await client.post("/api/bulk/jobs", json={
            "source_path": str(source),
            "output_path": str(tmp_path / "output"),
        })
        assert resp.status_code == 409


class TestListJobs:
    async def test_list_jobs(self, client):
        """GET /api/bulk/jobs returns job list."""
        await create_bulk_job("/src", "/out")
        resp = await client.get("/api/bulk/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert len(data["jobs"]) >= 1


class TestJobStatus:
    async def test_get_job_status(self, client):
        """GET /api/bulk/jobs/{id} returns job details."""
        job_id = await create_bulk_job("/src", "/out")
        resp = await client.get(f"/api/bulk/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id
        assert data["status"] == "pending"

    async def test_get_nonexistent_job(self, client):
        """404 for unknown job."""
        resp = await client.get("/api/bulk/jobs/nonexistent")
        assert resp.status_code == 404


class TestPauseResumeCancel:
    async def test_pause_not_running(self, client):
        """Pause returns 404 if job not in active registry."""
        resp = await client.post("/api/bulk/jobs/nonexistent/pause")
        assert resp.status_code == 404

    async def test_resume_not_running(self, client):
        resp = await client.post("/api/bulk/jobs/nonexistent/resume")
        assert resp.status_code == 404

    async def test_cancel_not_running(self, client):
        resp = await client.post("/api/bulk/jobs/nonexistent/cancel")
        assert resp.status_code == 404

    async def test_pause_active_job(self, client, tmp_path):
        """Pausing an active job returns success."""
        from core.bulk_worker import BulkJob, register_job, deregister_job

        source = tmp_path / "source"
        source.mkdir()
        job_id = await create_bulk_job(str(source), "/out")
        job = BulkJob(job_id=job_id, source_path=source, output_path=Path("/out"))
        register_job(job)

        try:
            resp = await client.post(f"/api/bulk/jobs/{job_id}/pause")
            assert resp.status_code == 200
            assert resp.json()["status"] == "paused"
        finally:
            deregister_job(job_id)


class TestJobFiles:
    async def test_job_files_pagination(self, client):
        """GET /api/bulk/jobs/{id}/files returns paginated files."""
        from core.database import upsert_bulk_file
        job_id = await create_bulk_job("/src", "/out")
        for i in range(5):
            await upsert_bulk_file(
                job_id=job_id, source_path=f"/src/file{i}.docx",
                file_ext=".docx", file_size_bytes=100, source_mtime=float(i),
            )

        resp = await client.get(f"/api/bulk/jobs/{job_id}/files?page=1&per_page=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["files"]) == 3
        assert data["total_pages"] == 2

    async def test_job_files_not_found(self, client):
        resp = await client.get("/api/bulk/jobs/nonexistent/files")
        assert resp.status_code == 404


class TestJobErrors:
    async def test_job_errors(self, client):
        """GET /api/bulk/jobs/{id}/errors returns failed files."""
        from core.database import upsert_bulk_file, update_bulk_file
        job_id = await create_bulk_job("/src", "/out")
        fid = await upsert_bulk_file(
            job_id=job_id, source_path="/src/bad.docx",
            file_ext=".docx", file_size_bytes=100, source_mtime=1.0,
        )
        await update_bulk_file(fid, status="failed", error_msg="Corrupt file")

        resp = await client.get(f"/api/bulk/jobs/{job_id}/errors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_errors"] == 1
        assert data["errors"][0]["error_msg"] == "Corrupt file"

    async def test_job_errors_not_found(self, client):
        resp = await client.get("/api/bulk/jobs/nonexistent/errors")
        assert resp.status_code == 404


class TestJobStream:
    async def test_stream_completed_job(self, client):
        """SSE stream for completed job emits summary and done."""
        job_id = await create_bulk_job("/src", "/out")
        await update_bulk_job_status(job_id, "completed", converted=10, failed=1)

        resp = await client.get(f"/api/bulk/jobs/{job_id}/stream")
        assert resp.status_code == 200
        text = resp.text
        assert "job_complete" in text
        assert "done" in text

    async def test_stream_nonexistent_job(self, client):
        resp = await client.get("/api/bulk/jobs/nonexistent/stream")
        assert resp.status_code == 404
