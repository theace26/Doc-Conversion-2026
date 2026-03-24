"""Tests for trash page API flows end-to-end."""

import pytest
import pytest_asyncio

from core.database import (
    create_bulk_job,
    db_fetch_one,
    init_db,
    update_bulk_file,
    upsert_bulk_file,
)
from core.lifecycle_manager import mark_file_for_deletion, move_to_trash


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_trash_restore_flow(client, tmp_path):
    """Full restore flow: mark -> trash -> restore via API."""
    job_id = await create_bulk_job(str(tmp_path / "s"), str(tmp_path / "o"))
    file_id = await upsert_bulk_file(
        job_id=job_id, source_path="/test/restorable.docx",
        file_ext=".docx", file_size_bytes=100, source_mtime=1000.0,
    )
    await mark_file_for_deletion(file_id, "scan1")
    await move_to_trash(file_id)

    # Verify it's in trash
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (file_id,))
    assert row["lifecycle_status"] == "in_trash"

    # Restore via API
    resp = await client.post(f"/api/trash/{file_id}/restore")
    assert resp.status_code == 200

    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (file_id,))
    assert row["lifecycle_status"] == "active"


@pytest.mark.asyncio
async def test_trash_purge_flow(client, tmp_path):
    """Full purge flow: mark -> trash -> purge via API."""
    job_id = await create_bulk_job(str(tmp_path / "s"), str(tmp_path / "o"))
    file_id = await upsert_bulk_file(
        job_id=job_id, source_path="/test/purgeable.docx",
        file_ext=".docx", file_size_bytes=100, source_mtime=1000.0,
    )
    await mark_file_for_deletion(file_id, "scan1")
    await move_to_trash(file_id)

    # Purge via API
    resp = await client.delete(f"/api/trash/{file_id}")
    assert resp.status_code == 200

    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (file_id,))
    assert row["lifecycle_status"] == "purged"


@pytest.mark.asyncio
async def test_trash_list_includes_trashed(client, tmp_path):
    """Trashed files appear in the trash list."""
    job_id = await create_bulk_job(str(tmp_path / "s"), str(tmp_path / "o"))
    file_id = await upsert_bulk_file(
        job_id=job_id, source_path="/test/inlist.docx",
        file_ext=".docx", file_size_bytes=500, source_mtime=1000.0,
    )
    await update_bulk_file(
        file_id,
        lifecycle_status="in_trash",
        moved_to_trash_at="2026-03-01T00:00:00+00:00",
    )

    resp = await client.get("/api/trash")
    assert resp.status_code == 200
    data = resp.json()
    paths = [f["source_path"] for f in data["files"]]
    assert "/test/inlist.docx" in paths


@pytest.mark.asyncio
async def test_restore_non_trashed_fails(client, tmp_path):
    """Restoring an active file returns 400."""
    job_id = await create_bulk_job(str(tmp_path / "s"), str(tmp_path / "o"))
    file_id = await upsert_bulk_file(
        job_id=job_id, source_path="/test/nottrashed.docx",
        file_ext=".docx", file_size_bytes=100, source_mtime=1000.0,
    )

    resp = await client.post(f"/api/trash/{file_id}/restore")
    assert resp.status_code == 400
