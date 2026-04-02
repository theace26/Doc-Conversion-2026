import pytest
import pytest_asyncio
import os
from unittest.mock import AsyncMock, patch
from pathlib import Path


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    import core.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield


@pytest.mark.asyncio
async def test_new_image_enqueued(db, tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    enqueue_calls = []

    async def mock_enqueue(source_path, **kwargs):
        enqueue_calls.append(source_path)
        return "fake-id"

    with patch("core.lifecycle_scanner.enqueue_image_for_analysis", side_effect=mock_enqueue), \
         patch("core.lifecycle_scanner.upsert_bulk_file", new_callable=AsyncMock, return_value="file-id-1"), \
         patch("core.lifecycle_scanner.update_bulk_file", new_callable=AsyncMock), \
         patch("core.lifecycle_scanner.get_next_version_number", new_callable=AsyncMock, return_value=1), \
         patch("core.lifecycle_scanner.create_version_snapshot", new_callable=AsyncMock):
        from core.lifecycle_scanner import _process_file
        await _process_file(
            file_path=img,
            path_str=str(img),
            ext=".jpg",
            mtime=img.stat().st_mtime,
            size=img.stat().st_size,
            job_id="test-job",
            scan_run_id="test-scan",
            counters={"files_new": 0, "files_modified": 0, "files_restored": 0,
                      "errors": 0, "files_scanned": 0},
        )

    assert str(img) in enqueue_calls


@pytest.mark.asyncio
async def test_pdf_not_enqueued(db, tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4" + b"\x00" * 100)

    enqueue_calls = []

    async def mock_enqueue(source_path, **kwargs):
        enqueue_calls.append(source_path)
        return "fake-id"

    with patch("core.lifecycle_scanner.enqueue_image_for_analysis", side_effect=mock_enqueue), \
         patch("core.lifecycle_scanner.upsert_bulk_file", new_callable=AsyncMock, return_value="file-id-2"), \
         patch("core.lifecycle_scanner.update_bulk_file", new_callable=AsyncMock), \
         patch("core.lifecycle_scanner.get_next_version_number", new_callable=AsyncMock, return_value=1), \
         patch("core.lifecycle_scanner.create_version_snapshot", new_callable=AsyncMock):
        from core.lifecycle_scanner import _process_file
        await _process_file(
            file_path=pdf,
            path_str=str(pdf),
            ext=".pdf",
            mtime=pdf.stat().st_mtime,
            size=pdf.stat().st_size,
            job_id="test-job",
            scan_run_id="test-scan",
            counters={"files_new": 0, "files_modified": 0, "files_restored": 0,
                      "errors": 0, "files_scanned": 0},
        )

    assert enqueue_calls == []
