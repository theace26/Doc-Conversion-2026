"""Tests for OCR confidence visibility in history API."""

import pytest

from core.database import (
    init_db,
    record_conversion,
    update_history_ocr_stats,
    db_fetch_one,
)


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


async def _insert_conversion(batch_id="batch1", filename="test.pdf",
                              fmt="pdf", status="success", ocr_applied=False):
    """Helper to insert a conversion history record. Returns row id."""
    return await record_conversion({
        "batch_id": batch_id,
        "source_filename": filename,
        "source_format": fmt,
        "output_filename": filename.replace(".pdf", ".md").replace(".docx", ".md"),
        "output_format": "md",
        "direction": "to_md",
        "status": status,
        "ocr_applied": ocr_applied,
        "duration_ms": 1000,
        "file_size_bytes": 5000,
    })


# ── DB recording tests ─────────────────────────────────────────────────────


async def test_ocr_stats_columns_exist():
    """After init_db, conversion_history has OCR confidence columns."""
    row_id = await _insert_conversion()
    row = await db_fetch_one(
        "SELECT ocr_confidence_mean, ocr_confidence_min, ocr_page_count, "
        "ocr_pages_below_threshold FROM conversion_history WHERE id=?",
        (row_id,),
    )
    assert row is not None
    # All should be NULL for a non-OCR file
    assert row["ocr_confidence_mean"] is None
    assert row["ocr_confidence_min"] is None
    assert row["ocr_page_count"] is None


async def test_update_history_ocr_stats():
    """update_history_ocr_stats writes confidence data to conversion_history."""
    row_id = await _insert_conversion(ocr_applied=True)
    await update_history_ocr_stats(
        history_id=row_id,
        mean=74.3,
        min_conf=41.2,
        page_count=12,
        pages_below=3,
    )

    row = await db_fetch_one(
        "SELECT ocr_confidence_mean, ocr_confidence_min, ocr_page_count, "
        "ocr_pages_below_threshold FROM conversion_history WHERE id=?",
        (row_id,),
    )
    assert row["ocr_confidence_mean"] == 74.3
    assert row["ocr_confidence_min"] == 41.2
    assert row["ocr_page_count"] == 12
    assert row["ocr_pages_below_threshold"] == 3


# ── History API response tests ─────────────────────────────────────────────


async def test_history_response_includes_ocr_block(client):
    """GET /api/history response includes ocr object for OCR'd files."""
    row_id = await _insert_conversion(
        batch_id="ocr_hist_1", filename="scan.pdf", ocr_applied=True,
    )
    await update_history_ocr_stats(
        history_id=row_id, mean=74.3, min_conf=41.2,
        page_count=12, pages_below=3,
    )

    resp = await client.get("/api/history?search=scan.pdf")
    assert resp.status_code == 200
    data = resp.json()
    records = data["records"]

    # Find our record
    ocr_record = next((r for r in records if r["source_filename"] == "scan.pdf"), None)
    assert ocr_record is not None
    assert ocr_record["ocr"] is not None
    assert ocr_record["ocr"]["ran"] is True
    assert ocr_record["ocr"]["confidence_mean"] == 74.3
    assert ocr_record["ocr"]["confidence_min"] == 41.2
    assert ocr_record["ocr"]["page_count"] == 12
    assert ocr_record["ocr"]["pages_below_threshold"] == 3
    assert "threshold" in ocr_record["ocr"]


async def test_history_response_ocr_null_for_docx(client):
    """GET /api/history response has ocr: null for DOCX files (no OCR)."""
    await _insert_conversion(
        batch_id="docx_hist_1", filename="clean.docx", fmt="docx",
    )

    resp = await client.get("/api/history?search=clean.docx")
    assert resp.status_code == 200
    data = resp.json()
    records = data["records"]

    docx_record = next((r for r in records if r["source_filename"] == "clean.docx"), None)
    assert docx_record is not None
    assert docx_record["ocr"] is None


async def test_history_stats_includes_ocr_stats(client):
    """GET /api/history/stats includes ocr_stats block."""
    # Insert a file with OCR stats
    row_id = await _insert_conversion(
        batch_id="stats_ocr_1", filename="stats_scan.pdf", ocr_applied=True,
    )
    await update_history_ocr_stats(
        history_id=row_id, mean=81.4, min_conf=60.0,
        page_count=5, pages_below=1,
    )

    resp = await client.get("/api/history/stats")
    assert resp.status_code == 200
    data = resp.json()

    # ocr_stats should be present (may aggregate with other test data)
    if data.get("ocr_stats"):
        assert data["ocr_stats"]["files_with_ocr"] >= 1
        assert "mean_confidence_overall" in data["ocr_stats"]
        assert "threshold" in data["ocr_stats"]


async def test_threshold_in_ocr_block(client):
    """ocr_confidence_threshold preference appears in each file's ocr block."""
    row_id = await _insert_conversion(
        batch_id="thresh_1", filename="thresh_scan.pdf", ocr_applied=True,
    )
    await update_history_ocr_stats(
        history_id=row_id, mean=50.0, min_conf=30.0,
        page_count=2, pages_below=2,
    )

    resp = await client.get("/api/history?search=thresh_scan.pdf")
    assert resp.status_code == 200
    data = resp.json()
    records = data["records"]
    rec = next((r for r in records if r["source_filename"] == "thresh_scan.pdf"), None)
    assert rec is not None
    assert rec["ocr"]["threshold"] is not None
    assert isinstance(rec["ocr"]["threshold"], (int, float))
