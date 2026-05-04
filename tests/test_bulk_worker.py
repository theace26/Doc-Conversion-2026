"""Tests for the bulk worker pool."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.bulk_worker import (
    BulkJob,
    _map_output_path,
    _map_sidecar_dir,
    get_active_job,
    register_job,
    deregister_job,
)
from core.database import (
    init_db,
    create_bulk_job,
    get_bulk_job,
    get_bulk_files,
    upsert_bulk_file,
)


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


# ── Path mapping tests ───────────────────────────────────────────────────────


def test_map_output_path():
    source_file = Path("/mnt/source/dept/finance/Q4_Report.docx")
    source_root = Path("/mnt/source")
    output_root = Path("/mnt/output-repo")
    result = _map_output_path(source_file, source_root, output_root)
    assert result == Path("/mnt/output-repo/dept/finance/Q4_Report.md")


def test_map_output_path_nested():
    source_file = Path("/mnt/source/a/b/c/file.pdf")
    result = _map_output_path(source_file, Path("/mnt/source"), Path("/out"))
    assert result == Path("/out/a/b/c/file.md")


def test_map_sidecar_dir():
    md_path = Path("/mnt/output-repo/dept/finance/Q4_Report.md")
    result = _map_sidecar_dir(md_path)
    assert result == Path("/mnt/output-repo/dept/finance/_markflow")


# ── Job registry tests ──────────────────────────────────────────────────────


def test_job_registry():
    job = BulkJob(
        job_id="test1",
        source_paths=Path("/src"),
        output_path=Path("/out"),
    )
    assert get_active_job("test1") is None
    register_job(job)
    assert get_active_job("test1") is job
    deregister_job("test1")
    assert get_active_job("test1") is None


# ── BulkJob lifecycle tests ─────────────────────────────────────────────────


async def test_bulk_job_run_empty_source(tmp_path):
    """A job with an empty source directory completes with 0 files."""
    source = tmp_path / "empty_source"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    job_id = await create_bulk_job(str(source), str(output))
    job = BulkJob(
        job_id=job_id,
        source_paths=source,
        output_path=output,
        worker_count=1,
    )
    await job.run()

    db_job = await get_bulk_job(job_id)
    assert db_job["status"] == "completed"
    assert db_job["total_files"] == 0


async def test_bulk_job_cancel(tmp_path):
    """Cancelling a job sets status to cancelled."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "doc.docx").write_bytes(b"data")
    output = tmp_path / "output"
    output.mkdir()

    job_id = await create_bulk_job(str(source), str(output))
    job = BulkJob(
        job_id=job_id,
        source_paths=source,
        output_path=output,
        worker_count=1,
    )

    # Cancel immediately
    await job.cancel()
    assert job._cancel_event.is_set()

    db_job = await get_bulk_job(job_id)
    assert db_job["status"] == "cancelled"


async def test_bulk_job_pause_resume(tmp_path):
    """Pause/resume toggles the pause event."""
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    job_id = await create_bulk_job(str(source), str(output))
    job = BulkJob(
        job_id=job_id,
        source_paths=source,
        output_path=output,
        worker_count=1,
    )

    assert job._pause_event.is_set()  # not paused initially
    await job.pause()
    assert not job._pause_event.is_set()
    db_job = await get_bulk_job(job_id)
    assert db_job["status"] == "paused"

    await job.resume()
    assert job._pause_event.is_set()
    db_job = await get_bulk_job(job_id)
    assert db_job["status"] == "running"


async def test_bulk_job_worker_count():
    """Worker count is clamped to 1-16."""
    job = BulkJob("test", Path("/src"), Path("/out"), worker_count=0)
    assert job.worker_count == 1

    job = BulkJob("test", Path("/src"), Path("/out"), worker_count=20)
    assert job.worker_count == 16

    job = BulkJob("test", Path("/src"), Path("/out"), worker_count=8)
    assert job.worker_count == 8


async def test_bulk_job_failed_file_does_not_stop_job(tmp_path):
    """A failed file should increment failed counter but not stop the job."""
    source = tmp_path / "source"
    source.mkdir()
    # Create a file that will fail conversion (empty file)
    (source / "bad.docx").write_bytes(b"not a real docx")
    (source / "also_bad.pdf").write_bytes(b"not a real pdf")
    output = tmp_path / "output"
    output.mkdir()

    job_id = await create_bulk_job(str(source), str(output))
    job = BulkJob(
        job_id=job_id,
        source_paths=source,
        output_path=output,
        worker_count=1,
    )

    # Patch converter to return an error result
    from core.converter import ConvertResult
    with patch("core.converter._convert_file_sync") as mock_convert:
        mock_convert.return_value = ConvertResult(
            source_filename="bad.docx",
            output_filename="",
            source_format="docx",
            output_format="",
            direction="to_md",
            batch_id=job_id,
            status="error",
            error_message="Corrupt file",
        )
        await job.run()

    db_job = await get_bulk_job(job_id)
    assert db_job["status"] == "completed"
    assert db_job["failed"] >= 1
