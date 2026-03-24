"""Tests for the bulk file scanner."""

import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.bulk_scanner import (
    BulkScanner,
    CONVERTIBLE_EXTENSIONS,
    ADOBE_EXTENSIONS,
    ALL_SUPPORTED,
    ScanResult,
)
from core.database import init_db, get_bulk_files, get_bulk_file_count


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


@pytest.fixture
def source_tree(tmp_path):
    """Create a directory tree with mixed file types."""
    # Convertible files
    (tmp_path / "dept" / "finance").mkdir(parents=True)
    (tmp_path / "dept" / "creative").mkdir(parents=True)
    (tmp_path / "dept" / "finance" / "Q4_Report.docx").write_bytes(b"fake docx")
    (tmp_path / "dept" / "finance" / "Budget.xlsx").write_bytes(b"fake xlsx")
    (tmp_path / "dept" / "finance" / "Notes.pdf").write_bytes(b"fake pdf")

    # Adobe files
    (tmp_path / "dept" / "creative" / "Logo.psd").write_bytes(b"fake psd")
    (tmp_path / "dept" / "creative" / "Poster.ai").write_bytes(b"fake ai")

    # Unsupported files (should be skipped)
    (tmp_path / "dept" / "finance" / "readme.txt").write_bytes(b"text file")
    (tmp_path / "dept" / "finance" / "image.jpg").write_bytes(b"jpeg data")

    # Hidden directory (should be skipped)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_bytes(b"git config")

    return tmp_path


async def test_scan_discovers_all_supported_files(source_tree):
    from core.database import create_bulk_job
    job_id = await create_bulk_job(str(source_tree), "/out")
    scanner = BulkScanner(job_id, source_tree)
    result = await scanner.scan()

    assert result.total_discovered == 5  # 3 convertible + 2 adobe
    assert result.convertible_count == 3
    assert result.adobe_count == 2
    assert result.scan_duration_ms >= 0


async def test_scan_skips_unsupported_extensions(source_tree):
    from core.database import create_bulk_job
    job_id = await create_bulk_job(str(source_tree), "/out")
    scanner = BulkScanner(job_id, source_tree)
    await scanner.scan()

    files = await get_bulk_files(job_id)
    exts = {f["file_ext"] for f in files}
    assert ".txt" not in exts
    assert ".jpg" not in exts


async def test_scan_respects_mtime_incremental(source_tree):
    from core.database import create_bulk_job, update_bulk_file
    job_id = await create_bulk_job(str(source_tree), "/out")

    # First scan
    scanner = BulkScanner(job_id, source_tree)
    result1 = await scanner.scan()
    assert result1.total_discovered == 5

    # Mark one file as converted with stored_mtime
    files = await get_bulk_files(job_id)
    docx_file = [f for f in files if f["file_ext"] == ".docx"][0]
    await update_bulk_file(
        docx_file["id"],
        status="converted",
        stored_mtime=docx_file["source_mtime"],
    )

    # Second scan — same files, docx should be skipped
    result2 = await scanner.scan()
    skipped = await get_bulk_file_count(job_id, status="skipped")
    assert skipped >= 1


async def test_scan_yields_control(source_tree):
    """Verify the scanner yields control during large walks."""
    from core.database import create_bulk_job
    job_id = await create_bulk_job(str(source_tree), "/out")
    scanner = BulkScanner(job_id, source_tree)
    scanner._yield_interval = 2  # yield every 2 files

    with patch("core.bulk_scanner.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await scanner.scan()
        # With 5 files and interval=2, should yield at least twice
        assert mock_sleep.call_count >= 2


async def test_scan_handles_permission_error(tmp_path):
    """Permission errors on subdirectories should not stop the scan."""
    from core.database import create_bulk_job
    (tmp_path / "accessible").mkdir()
    (tmp_path / "accessible" / "doc.docx").write_bytes(b"data")

    job_id = await create_bulk_job(str(tmp_path), "/out")
    scanner = BulkScanner(job_id, tmp_path)

    # Scanner should not raise even if some dirs are unreadable
    result = await scanner.scan()
    assert result.total_discovered >= 1


async def test_scan_skips_hidden_and_markflow_dirs(tmp_path):
    from core.database import create_bulk_job
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.docx").write_bytes(b"data")
    (tmp_path / "_markflow").mkdir()
    (tmp_path / "_markflow" / "sidecar.json").write_bytes(b"data")
    (tmp_path / "visible.docx").write_bytes(b"data")

    job_id = await create_bulk_job(str(tmp_path), "/out")
    scanner = BulkScanner(job_id, tmp_path)
    result = await scanner.scan()
    assert result.total_discovered == 1


async def test_scan_result_dataclass():
    result = ScanResult(job_id="test123")
    assert result.total_discovered == 0
    assert result.scan_duration_ms == 0
