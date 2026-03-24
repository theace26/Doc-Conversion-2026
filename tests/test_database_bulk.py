"""Tests for Phase 7 database schema extensions and helper functions."""

import pytest

from core.database import (
    create_bulk_job,
    get_bulk_job,
    list_bulk_jobs,
    update_bulk_job_status,
    increment_bulk_job_counter,
    upsert_bulk_file,
    get_bulk_files,
    get_bulk_file_count,
    update_bulk_file,
    get_unprocessed_bulk_files,
    upsert_adobe_index,
    get_adobe_index_entry,
    get_unindexed_adobe_entries,
    mark_adobe_meili_indexed,
    init_db,
)


@pytest.fixture(autouse=True)
async def ensure_schema():
    """Ensure the DB schema is initialized before each test."""
    await init_db()


# ── Bulk job helpers ─────────────────────────────────────────────────────────


class TestBulkJobHelpers:
    async def test_create_and_get_bulk_job(self):
        job_id = await create_bulk_job(
            source_path="/mnt/source",
            output_path="/mnt/output",
            worker_count=4,
            include_adobe=True,
            fidelity_tier=2,
            ocr_mode="auto",
        )
        assert job_id
        assert len(job_id) == 32  # UUID hex

        job = await get_bulk_job(job_id)
        assert job is not None
        assert job["source_path"] == "/mnt/source"
        assert job["output_path"] == "/mnt/output"
        assert job["status"] == "pending"
        assert job["worker_count"] == 4
        assert job["include_adobe"] == 1
        assert job["fidelity_tier"] == 2
        assert job["ocr_mode"] == "auto"

    async def test_get_nonexistent_job(self):
        job = await get_bulk_job("nonexistent")
        assert job is None

    async def test_list_bulk_jobs(self):
        for _ in range(3):
            await create_bulk_job("/src", "/out")
        jobs = await list_bulk_jobs(limit=10)
        assert len(jobs) >= 3

    async def test_update_bulk_job_status(self):
        job_id = await create_bulk_job("/src", "/out")
        await update_bulk_job_status(job_id, "running", total_files=100)
        job = await get_bulk_job(job_id)
        assert job["status"] == "running"
        assert job["total_files"] == 100

    async def test_increment_bulk_job_counter(self):
        job_id = await create_bulk_job("/src", "/out")
        await increment_bulk_job_counter(job_id, "converted", 5)
        await increment_bulk_job_counter(job_id, "converted", 3)
        job = await get_bulk_job(job_id)
        assert job["converted"] == 8


# ── Bulk file helpers ────────────────────────────────────────────────────────


class TestBulkFileHelpers:
    async def test_upsert_new_file(self):
        job_id = await create_bulk_job("/src", "/out")
        file_id = await upsert_bulk_file(
            job_id=job_id,
            source_path="/src/doc.docx",
            file_ext=".docx",
            file_size_bytes=1024,
            source_mtime=1000.0,
        )
        assert file_id
        files = await get_bulk_files(job_id)
        assert len(files) == 1
        assert files[0]["source_path"] == "/src/doc.docx"
        assert files[0]["status"] == "pending"

    async def test_upsert_unchanged_file_skipped(self):
        job_id = await create_bulk_job("/src", "/out")
        file_id = await upsert_bulk_file(
            job_id=job_id, source_path="/src/doc.docx",
            file_ext=".docx", file_size_bytes=1024, source_mtime=1000.0,
        )
        # Simulate successful conversion by setting stored_mtime
        await update_bulk_file(file_id, stored_mtime=1000.0, status="converted")

        # Upsert again with same mtime — should be skipped
        file_id2 = await upsert_bulk_file(
            job_id=job_id, source_path="/src/doc.docx",
            file_ext=".docx", file_size_bytes=1024, source_mtime=1000.0,
        )
        assert file_id2 == file_id
        files = await get_bulk_files(job_id, status="skipped")
        assert len(files) == 1

    async def test_upsert_changed_file_pending(self):
        job_id = await create_bulk_job("/src", "/out")
        file_id = await upsert_bulk_file(
            job_id=job_id, source_path="/src/doc.docx",
            file_ext=".docx", file_size_bytes=1024, source_mtime=1000.0,
        )
        await update_bulk_file(file_id, stored_mtime=1000.0, status="converted")

        # Upsert with new mtime — should be pending
        file_id2 = await upsert_bulk_file(
            job_id=job_id, source_path="/src/doc.docx",
            file_ext=".docx", file_size_bytes=2048, source_mtime=2000.0,
        )
        assert file_id2 == file_id
        files = await get_bulk_files(job_id, status="pending")
        assert len(files) == 1

    async def test_get_bulk_file_count(self):
        job_id = await create_bulk_job("/src", "/out")
        for i in range(5):
            await upsert_bulk_file(
                job_id=job_id, source_path=f"/src/file{i}.docx",
                file_ext=".docx", file_size_bytes=100, source_mtime=float(i),
            )
        assert await get_bulk_file_count(job_id) == 5
        assert await get_bulk_file_count(job_id, status="pending") == 5

    async def test_get_unprocessed_bulk_files(self):
        job_id = await create_bulk_job("/src", "/out")
        await upsert_bulk_file(
            job_id=job_id, source_path="/src/a.docx",
            file_ext=".docx", file_size_bytes=100, source_mtime=1.0,
        )
        f2 = await upsert_bulk_file(
            job_id=job_id, source_path="/src/b.docx",
            file_ext=".docx", file_size_bytes=100, source_mtime=2.0,
        )
        # Mark b as converted with stored_mtime
        await update_bulk_file(f2, status="converted", stored_mtime=2.0)

        # Re-upsert b with same mtime — it should be skipped
        await upsert_bulk_file(
            job_id=job_id, source_path="/src/b.docx",
            file_ext=".docx", file_size_bytes=100, source_mtime=2.0,
        )

        pending = await get_unprocessed_bulk_files(job_id)
        assert len(pending) == 1
        assert pending[0]["source_path"] == "/src/a.docx"

    async def test_update_bulk_file(self):
        job_id = await create_bulk_job("/src", "/out")
        file_id = await upsert_bulk_file(
            job_id=job_id, source_path="/src/a.docx",
            file_ext=".docx", file_size_bytes=100, source_mtime=1.0,
        )
        await update_bulk_file(file_id, status="converted", output_path="/out/a.md")
        files = await get_bulk_files(job_id, status="converted")
        assert len(files) == 1
        assert files[0]["output_path"] == "/out/a.md"


# ── Adobe index helpers ──────────────────────────────────────────────────────


class TestAdobeIndexHelpers:
    async def test_upsert_and_get_adobe_entry(self):
        entry_id = await upsert_adobe_index(
            source_path="/src/logo.psd",
            file_ext=".psd",
            file_size_bytes=5000,
            metadata={"Title": "Logo", "Creator": "Photoshop"},
            text_layers=["Layer 1 text", "Layer 2 text"],
        )
        assert entry_id

        entry = await get_adobe_index_entry("/src/logo.psd")
        assert entry is not None
        assert entry["file_ext"] == ".psd"
        assert entry["metadata"]["Title"] == "Logo"
        assert len(entry["text_layers"]) == 2
        assert entry["meili_indexed"] == 0

    async def test_upsert_updates_existing(self):
        await upsert_adobe_index(
            source_path="/src/logo.psd", file_ext=".psd",
            file_size_bytes=5000, metadata={"Title": "V1"}, text_layers=[],
        )
        await upsert_adobe_index(
            source_path="/src/logo.psd", file_ext=".psd",
            file_size_bytes=6000, metadata={"Title": "V2"}, text_layers=["new text"],
        )
        entry = await get_adobe_index_entry("/src/logo.psd")
        assert entry["metadata"]["Title"] == "V2"
        assert entry["file_size_bytes"] == 6000
        assert entry["meili_indexed"] == 0  # Reset on update

    async def test_get_nonexistent_adobe_entry(self):
        entry = await get_adobe_index_entry("/nonexistent.ai")
        assert entry is None

    async def test_unindexed_entries(self):
        await upsert_adobe_index(
            "/src/a.psd", ".psd", 100, {}, [],
        )
        await upsert_adobe_index(
            "/src/b.ai", ".ai", 200, {}, [],
        )
        entries = await get_unindexed_adobe_entries(limit=10)
        assert len(entries) >= 2

    async def test_mark_meili_indexed(self):
        entry_id = await upsert_adobe_index(
            "/src/indexed.psd", ".psd", 100, {}, [],
        )
        await mark_adobe_meili_indexed(entry_id)
        entry = await get_adobe_index_entry("/src/indexed.psd")
        assert entry["meili_indexed"] == 1

        # Should not appear in unindexed list
        entries = await get_unindexed_adobe_entries(limit=100)
        paths = [e["source_path"] for e in entries]
        assert "/src/indexed.psd" not in paths
