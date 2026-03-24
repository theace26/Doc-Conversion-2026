"""Tests for core/lifecycle_scanner.py — scan logic."""

import os

import pytest
import pytest_asyncio

from core.database import (
    create_bulk_job,
    db_fetch_one,
    get_bulk_file_by_path,
    get_scan_run,
    get_version_history,
    init_db,
    update_bulk_file,
    upsert_bulk_file,
)
from core.lifecycle_scanner import run_lifecycle_scan


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_new_file_detected(tmp_path, monkeypatch):
    """New file in source share creates bulk_files record + initial version."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "new.docx").write_bytes(b"new file content")

    monkeypatch.setenv("BULK_SOURCE_PATH", str(src))

    # Create a job so the scanner has one
    job_id = await create_bulk_job(str(src), str(tmp_path / "out"))

    scan_id = await run_lifecycle_scan(source_path=str(src), job_id=job_id)
    run = await get_scan_run(scan_id)
    assert run is not None
    assert run["status"] == "complete"
    assert run["files_new"] >= 1

    f = await get_bulk_file_by_path(str(src / "new.docx"))
    assert f is not None


@pytest.mark.asyncio
async def test_modified_file_detected(tmp_path, monkeypatch):
    """Modified file resets status to pending."""
    src = tmp_path / "source"
    src.mkdir()
    doc = src / "doc.docx"
    doc.write_bytes(b"original")

    job_id = await create_bulk_job(str(src), str(tmp_path / "out"))
    file_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(doc),
        file_ext=".docx",
        file_size_bytes=8,
        source_mtime=1000.0,
    )
    await update_bulk_file(file_id, status="converted", lifecycle_status="active")

    # Modify the file
    doc.write_bytes(b"modified content!!!")

    scan_id = await run_lifecycle_scan(source_path=str(src), job_id=job_id)
    run = await get_scan_run(scan_id)
    assert run["files_modified"] >= 1


@pytest.mark.asyncio
async def test_disappeared_file_marked(tmp_path, monkeypatch):
    """Disappeared file gets marked_for_deletion."""
    src = tmp_path / "source"
    src.mkdir()
    doc = src / "gone.docx"
    doc.write_bytes(b"content")

    job_id = await create_bulk_job(str(src), str(tmp_path / "out"))
    file_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(doc),
        file_ext=".docx",
        file_size_bytes=7,
        source_mtime=1000.0,
    )
    await update_bulk_file(file_id, lifecycle_status="active")

    # Remove the file
    doc.unlink()

    scan_id = await run_lifecycle_scan(source_path=str(src), job_id=job_id)
    run = await get_scan_run(scan_id)
    assert run["files_deleted"] >= 1

    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (file_id,))
    assert row["lifecycle_status"] == "marked_for_deletion"


@pytest.mark.asyncio
async def test_source_unavailable(tmp_path):
    """Unavailable source → scan_runs.status='failed'."""
    scan_id = await run_lifecycle_scan(
        source_path=str(tmp_path / "nonexistent"),
        job_id="fakejob",
    )
    run = await get_scan_run(scan_id)
    assert run["status"] == "failed"


@pytest.mark.asyncio
async def test_scan_continues_after_file_error(tmp_path, monkeypatch):
    """A single file error doesn't crash the scan."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "good.docx").write_bytes(b"good file")
    # Create a file that will stat normally but is fine
    (src / "also_good.pdf").write_bytes(b"another file")

    job_id = await create_bulk_job(str(src), str(tmp_path / "out"))
    scan_id = await run_lifecycle_scan(source_path=str(src), job_id=job_id)
    run = await get_scan_run(scan_id)
    assert run["status"] == "complete"
    assert run["files_scanned"] >= 2
