"""Tests for core/lifecycle_manager.py — lifecycle transitions."""

import pytest
import pytest_asyncio

from core.database import (
    get_version_history,
    init_db,
    upsert_bulk_file,
    update_bulk_file,
    create_bulk_job,
    db_fetch_one,
)
from core.lifecycle_manager import (
    mark_file_for_deletion,
    restore_file,
    move_to_trash,
    purge_file,
    record_file_move,
    record_content_change,
    get_trash_path,
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest_asyncio.fixture
async def sample_file(tmp_path):
    job_id = await create_bulk_job(str(tmp_path / "src"), str(tmp_path / "out"))
    file_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(tmp_path / "src" / "doc.docx"),
        file_ext=".docx",
        file_size_bytes=100,
        source_mtime=1000.0,
    )
    return file_id


@pytest.mark.asyncio
async def test_mark_for_deletion(sample_file):
    await mark_file_for_deletion(sample_file, "scan1")
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (sample_file,))
    assert row["lifecycle_status"] == "marked_for_deletion"
    assert row["marked_for_deletion_at"] is not None
    versions = await get_version_history(sample_file)
    assert len(versions) == 1
    assert versions[0]["change_type"] == "marked_deleted"


@pytest.mark.asyncio
async def test_restore_file(sample_file):
    await mark_file_for_deletion(sample_file, "scan1")
    await restore_file(sample_file, "scan2")
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (sample_file,))
    assert row["lifecycle_status"] == "active"
    versions = await get_version_history(sample_file)
    assert len(versions) == 2
    assert versions[0]["change_type"] == "restored"


@pytest.mark.asyncio
async def test_move_to_trash(sample_file):
    await mark_file_for_deletion(sample_file, "scan1")
    await move_to_trash(sample_file)
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (sample_file,))
    assert row["lifecycle_status"] == "in_trash"
    assert row["moved_to_trash_at"] is not None
    versions = await get_version_history(sample_file)
    assert any(v["change_type"] == "trashed" for v in versions)


@pytest.mark.asyncio
async def test_purge_file(sample_file):
    await move_to_trash(sample_file)
    await purge_file(sample_file)
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (sample_file,))
    # Row should still exist (retained for audit)
    assert row is not None
    assert row["lifecycle_status"] == "purged"
    assert row["purged_at"] is not None
    versions = await get_version_history(sample_file)
    assert any(v["change_type"] == "purged" for v in versions)


@pytest.mark.asyncio
async def test_record_file_move(sample_file):
    old_path = "/old/path/doc.docx"
    new_path = "/new/path/doc.docx"
    await update_bulk_file(sample_file, source_path=old_path)
    await record_file_move(sample_file, old_path, new_path, "scan1")
    row = await db_fetch_one("SELECT * FROM bulk_files WHERE id=?", (sample_file,))
    assert row["source_path"] == new_path
    assert row["previous_path"] == old_path
    versions = await get_version_history(sample_file)
    assert any(v["change_type"] == "moved" for v in versions)


@pytest.mark.asyncio
async def test_record_content_change(sample_file, tmp_path):
    old_md = tmp_path / "old.md"
    new_md = tmp_path / "new.md"
    old_md.write_text("# Title\n\nOld content.\n", encoding="utf-8")
    new_md.write_text("# Title\n\nNew content added.\n", encoding="utf-8")

    await record_content_change(sample_file, old_md, new_md, "scan1")
    versions = await get_version_history(sample_file)
    assert len(versions) == 1
    assert versions[0]["change_type"] == "content_change"
    assert versions[0]["diff_summary"] is not None


@pytest.mark.asyncio
async def test_missing_md_handled_gracefully(sample_file, tmp_path):
    """Missing .md files don't raise exceptions."""
    missing = tmp_path / "does_not_exist.md"
    await record_content_change(sample_file, missing, None, "scan1")
    versions = await get_version_history(sample_file)
    assert len(versions) == 1


def test_get_trash_path(tmp_path):
    output_root = tmp_path / "output"
    output_root.mkdir()
    md_path = output_root / "dept" / "doc.md"
    trash = get_trash_path(output_root, md_path)
    assert ".trash" in str(trash)
    assert "dept" in str(trash)
    assert trash.name == "doc.md"
