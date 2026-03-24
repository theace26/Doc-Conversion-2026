"""
Tests for Track A — Auto-OCR gap-fill.

Covers:
  - Gap-fill pending count query
  - Gap-fill dry run
  - Deferred OCR on single-file upload
  - Gap-fill pass updating history records
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.database import (
    get_ocr_gap_fill_candidates,
    get_ocr_gap_fill_count,
    init_db,
    record_conversion,
    update_history_ocr_stats,
    db_fetch_one,
)


@pytest.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    """Use a temporary database for each test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("core.database.DB_PATH", db_path)
    await init_db()
    yield


# ── Pending count tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gap_fill_count_empty():
    """No PDFs → count should be 0."""
    result = await get_ocr_gap_fill_count()
    assert result["count"] == 0
    assert result["oldest_conversion"] is None


@pytest.mark.asyncio
async def test_gap_fill_count_with_un_ocrd_pdf():
    """A PDF without OCR stats should appear in the count."""
    await record_conversion({
        "batch_id": "batch1",
        "source_filename": "report.pdf",
        "source_format": "pdf",
        "output_filename": "report.md",
        "output_format": "md",
        "direction": "to_md",
        "source_path": "/tmp/report.pdf",
        "output_path": "/tmp/output/report.md",
        "status": "success",
    })
    result = await get_ocr_gap_fill_count()
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_gap_fill_count_excludes_ocrd_pdf():
    """A PDF with OCR stats should NOT appear in the count."""
    history_id = await record_conversion({
        "batch_id": "batch2",
        "source_filename": "scanned.pdf",
        "source_format": "pdf",
        "output_filename": "scanned.md",
        "output_format": "md",
        "direction": "to_md",
        "source_path": "/tmp/scanned.pdf",
        "output_path": "/tmp/output/scanned.md",
        "status": "success",
    })
    await update_history_ocr_stats(
        history_id=history_id, mean=85.0, min_conf=60.0,
        page_count=3, pages_below=1,
    )
    result = await get_ocr_gap_fill_count()
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_gap_fill_count_excludes_failed():
    """Failed conversions should not appear."""
    await record_conversion({
        "batch_id": "batch3",
        "source_filename": "bad.pdf",
        "source_format": "pdf",
        "output_filename": "",
        "output_format": "",
        "direction": "to_md",
        "source_path": "/tmp/bad.pdf",
        "output_path": "",
        "status": "error",
        "error_message": "Corrupt PDF",
    })
    result = await get_ocr_gap_fill_count()
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_gap_fill_count_excludes_non_pdf():
    """Non-PDF formats should not appear."""
    await record_conversion({
        "batch_id": "batch4",
        "source_filename": "doc.docx",
        "source_format": "docx",
        "output_filename": "doc.md",
        "output_format": "md",
        "direction": "to_md",
        "status": "success",
    })
    result = await get_ocr_gap_fill_count()
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_gap_fill_candidates_returns_records():
    """Candidates query returns full records."""
    await record_conversion({
        "batch_id": "batch5",
        "source_filename": "report.pdf",
        "source_format": "pdf",
        "output_filename": "report.md",
        "output_format": "md",
        "direction": "to_md",
        "source_path": "/tmp/report.pdf",
        "output_path": "/tmp/output/report.md",
        "status": "success",
    })
    candidates = await get_ocr_gap_fill_candidates()
    assert len(candidates) == 1
    assert candidates[0]["source_filename"] == "report.pdf"


# ── API endpoint tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gap_fill_pending_count_api(tmp_path, monkeypatch):
    """GET /api/bulk/ocr-gap-fill/pending-count returns correct count."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/bulk/ocr-gap-fill/pending-count")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data


@pytest.mark.asyncio
async def test_gap_fill_dry_run_api(tmp_path, monkeypatch):
    """POST /api/bulk/ocr-gap-fill with dry_run returns count without processing."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/bulk/ocr-gap-fill",
            json={"dry_run": True, "worker_count": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert "files_found" in data


# ── Deferred OCR check test ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deferred_ocr_skips_non_pdf():
    """Deferred OCR check returns immediately for non-PDF formats."""
    from core.converter import ConversionOrchestrator, ConvertResult

    orch = ConversionOrchestrator()
    result = ConvertResult(
        source_filename="doc.docx",
        output_filename="doc.md",
        source_format="docx",
        output_format="md",
        direction="to_md",
        batch_id="batch_test",
        status="success",
    )
    # Should not raise — just returns
    await orch._check_and_run_deferred_ocr(1, result, Path("/tmp/doc.docx"))


@pytest.mark.asyncio
async def test_deferred_ocr_skips_if_already_ran():
    """Deferred OCR does not re-run if OCR already produced flags."""
    from core.converter import ConversionOrchestrator, ConvertResult

    orch = ConversionOrchestrator()
    result = ConvertResult(
        source_filename="scan.pdf",
        output_filename="scan.md",
        source_format="pdf",
        output_format="md",
        direction="to_md",
        batch_id="batch_test2",
        status="success",
        ocr_flags_total=5,
    )
    # Should not call into PDF handler — flags already exist
    await orch._check_and_run_deferred_ocr(1, result, Path("/tmp/scan.pdf"))


# ── BulkOcrGapFillJob tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gap_fill_job_dry_run():
    """Dry run returns count without processing."""
    from core.bulk_worker import BulkOcrGapFillJob

    job = BulkOcrGapFillJob(
        gap_fill_id="test-gf-1",
        dry_run=True,
    )
    result = await job.run()
    assert result["dry_run"] is True
    assert result["files_found"] == 0


@pytest.mark.asyncio
async def test_gap_fill_job_no_candidates():
    """Gap-fill with no candidates finishes immediately."""
    from core.bulk_worker import BulkOcrGapFillJob

    job = BulkOcrGapFillJob(
        gap_fill_id="test-gf-2",
        worker_count=1,
    )
    result = await job.run()
    assert result["total"] == 0
    assert result["processed"] == 0
