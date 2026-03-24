"""Phase 9 test fixtures."""

import os
import uuid

import pytest
import pytest_asyncio

from core.database import DB_PATH, get_db, init_db


@pytest.fixture
def mock_source_share(tmp_path):
    """Temp directory tree mimicking a source share with a few files."""
    src = tmp_path / "source"
    src.mkdir()
    # Create some test files
    (src / "report.docx").write_bytes(b"fake docx content A")
    (src / "data.xlsx").write_bytes(b"fake xlsx content B")
    sub = src / "dept"
    sub.mkdir()
    (sub / "memo.pdf").write_bytes(b"fake pdf content C")
    return src


@pytest.fixture
def mock_output_repo(tmp_path):
    """Temp directory mimicking the output markdown repo."""
    out = tmp_path / "output-repo"
    out.mkdir()
    (out / "report.md").write_text("# Report\n\nConverted content.", encoding="utf-8")
    sub = out / "dept"
    sub.mkdir()
    (sub / "memo.md").write_text("# Memo\n\nConverted memo.", encoding="utf-8")
    return out


@pytest_asyncio.fixture
async def db_with_lifecycle_files(tmp_path):
    """Pre-populated DB with files in each lifecycle state for testing."""
    from core.database import upsert_bulk_file, update_bulk_file, create_bulk_job

    # Ensure DB is initialized
    await init_db()

    job_id = await create_bulk_job(
        source_path=str(tmp_path / "source"),
        output_path=str(tmp_path / "output"),
    )

    # Create files in various states
    active_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(tmp_path / "source" / "active.docx"),
        file_ext=".docx",
        file_size_bytes=1000,
        source_mtime=1000.0,
    )
    await update_bulk_file(active_id, lifecycle_status="active")

    marked_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(tmp_path / "source" / "marked.docx"),
        file_ext=".docx",
        file_size_bytes=2000,
        source_mtime=2000.0,
    )
    await update_bulk_file(
        marked_id,
        lifecycle_status="marked_for_deletion",
        marked_for_deletion_at="2026-01-01T00:00:00+00:00",
    )

    trashed_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(tmp_path / "source" / "trashed.docx"),
        file_ext=".docx",
        file_size_bytes=3000,
        source_mtime=3000.0,
    )
    await update_bulk_file(
        trashed_id,
        lifecycle_status="in_trash",
        moved_to_trash_at="2026-01-01T00:00:00+00:00",
    )

    purged_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(tmp_path / "source" / "purged.docx"),
        file_ext=".docx",
        file_size_bytes=4000,
        source_mtime=4000.0,
    )
    await update_bulk_file(
        purged_id,
        lifecycle_status="purged",
        purged_at="2026-01-01T00:00:00+00:00",
    )

    return {
        "job_id": job_id,
        "active_id": active_id,
        "marked_id": marked_id,
        "trashed_id": trashed_id,
        "purged_id": purged_id,
    }
