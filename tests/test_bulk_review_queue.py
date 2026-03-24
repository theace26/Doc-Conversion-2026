"""Tests for the bulk review queue system."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.database import (
    add_to_review_queue,
    create_bulk_job,
    get_bulk_job,
    get_review_queue,
    get_review_queue_count,
    get_review_queue_entry,
    get_review_queue_summary,
    increment_bulk_job_counter,
    init_db,
    update_bulk_file,
    update_bulk_job_status,
    update_review_queue_entry,
    upsert_bulk_file,
)


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


async def _create_job_with_file(tmp_path, file_ext=".pdf"):
    """Helper: create a bulk job and a file, return (job_id, file_id, source_path)."""
    source_dir = tmp_path / "source"
    source_dir.mkdir(exist_ok=True)
    output_dir = tmp_path / "output"

    job_id = await create_bulk_job(str(source_dir), str(output_dir))

    source_file = source_dir / f"scan001{file_ext}"
    source_file.write_bytes(b"fake content")

    file_id = await upsert_bulk_file(
        job_id=job_id,
        source_path=str(source_file),
        file_ext=file_ext,
        file_size_bytes=100,
        source_mtime=1000.0,
    )
    return job_id, file_id, str(source_file)


# ── Database helper tests ─────────────────────────────────────────────────


async def test_add_to_review_queue(tmp_path):
    """Adding a file to the review queue creates a valid entry."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)

    entry_id = await add_to_review_queue(
        job_id=job_id,
        bulk_file_id=file_id,
        source_path=source_path,
        file_ext=".pdf",
        estimated_confidence=38.4,
        skip_reason="below_threshold",
    )

    assert entry_id
    entry = await get_review_queue_entry(entry_id)
    assert entry is not None
    assert entry["job_id"] == job_id
    assert entry["bulk_file_id"] == file_id
    assert entry["estimated_confidence"] == 38.4
    assert entry["status"] == "pending"
    assert entry["skip_reason"] == "below_threshold"


async def test_get_review_queue_filters_by_status(tmp_path):
    """get_review_queue filters by status."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)

    await add_to_review_queue(job_id, file_id, source_path, ".pdf", 30.0)

    pending = await get_review_queue(job_id, status="pending")
    assert len(pending) == 1

    converted = await get_review_queue(job_id, status="converted")
    assert len(converted) == 0


async def test_update_review_queue_entry(tmp_path):
    """Updating a review queue entry changes status and resolution."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    entry_id = await add_to_review_queue(job_id, file_id, source_path, ".pdf", 45.0)

    await update_review_queue_entry(
        entry_id,
        status="skipped_permanently",
        resolution="skipped",
        notes="Not needed",
        resolved_at="2026-03-24T00:00:00Z",
    )

    entry = await get_review_queue_entry(entry_id)
    assert entry["status"] == "skipped_permanently"
    assert entry["resolution"] == "skipped"
    assert entry["notes"] == "Not needed"


async def test_get_review_queue_summary(tmp_path):
    """get_review_queue_summary returns correct counts."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)

    e1 = await add_to_review_queue(job_id, file_id, source_path, ".pdf", 30.0)
    e2 = await add_to_review_queue(job_id, file_id, source_path + "2", ".pdf", 40.0)
    e3 = await add_to_review_queue(job_id, file_id, source_path + "3", ".pdf", 50.0)

    # Resolve one as skipped
    await update_review_queue_entry(e2, status="skipped_permanently", resolution="skipped")
    # Resolve one as converted
    await update_review_queue_entry(e3, status="converted", resolution="converted")

    summary = await get_review_queue_summary(job_id)
    assert summary["pending"] == 1
    assert summary["skipped_permanently"] == 1
    assert summary["converted"] == 1
    assert summary["total"] == 3


async def test_review_queue_count(tmp_path):
    """get_review_queue_count returns correct count with status filter."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    await add_to_review_queue(job_id, file_id, source_path, ".pdf", 30.0)
    await add_to_review_queue(job_id, file_id, source_path + "2", ".pdf", 40.0)

    assert await get_review_queue_count(job_id) == 2
    assert await get_review_queue_count(job_id, status="pending") == 2
    assert await get_review_queue_count(job_id, status="converted") == 0


async def test_bulk_jobs_review_queue_count_column(tmp_path):
    """bulk_jobs.review_queue_count is incremented when files are skipped for review."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    await increment_bulk_job_counter(job_id, "review_queue_count")
    await increment_bulk_job_counter(job_id, "review_queue_count")

    job = await get_bulk_job(job_id)
    assert job["review_queue_count"] == 2


# ── Bulk worker pre-scan skip tests ────────────────────────────────────────


async def test_file_below_threshold_added_to_review_queue(tmp_path):
    """File with estimated confidence below threshold is added to review queue."""
    from core.bulk_worker import BulkJob

    job_id, file_id, source_path = await _create_job_with_file(tmp_path)

    job = BulkJob(
        job_id=job_id,
        source_path=tmp_path / "source",
        output_path=tmp_path / "output",
        ocr_mode="auto",
    )

    file_dict = {
        "id": file_id,
        "source_path": source_path,
        "file_ext": ".pdf",
    }

    # Mock estimate to return below threshold (default threshold 80)
    with patch("core.bulk_worker._estimate_ocr_confidence", return_value=30.0), \
         patch("core.bulk_worker.get_preference", return_value="80"):
        skipped = await job._check_confidence_prescan(file_dict)

    assert skipped is True

    # Verify entry was added to review queue
    entries = await get_review_queue(job_id, status="pending")
    assert len(entries) >= 1
    assert any(e["bulk_file_id"] == file_id for e in entries)


async def test_file_above_threshold_proceeds(tmp_path):
    """File with estimated confidence above threshold proceeds to conversion."""
    from core.bulk_worker import BulkJob

    job_id, file_id, source_path = await _create_job_with_file(tmp_path)

    job = BulkJob(
        job_id=job_id,
        source_path=tmp_path / "source",
        output_path=tmp_path / "output",
        ocr_mode="auto",
    )

    file_dict = {
        "id": file_id,
        "source_path": source_path,
        "file_ext": ".pdf",
    }

    with patch("core.bulk_worker._estimate_ocr_confidence", return_value=95.0), \
         patch("core.bulk_worker.get_preference", return_value="80"):
        skipped = await job._check_confidence_prescan(file_dict)

    assert skipped is False


async def test_file_with_none_confidence_proceeds(tmp_path):
    """File where confidence estimation returns None proceeds normally."""
    from core.bulk_worker import BulkJob

    job_id, file_id, source_path = await _create_job_with_file(tmp_path)

    job = BulkJob(
        job_id=job_id,
        source_path=tmp_path / "source",
        output_path=tmp_path / "output",
    )

    file_dict = {
        "id": file_id,
        "source_path": source_path,
        "file_ext": ".pdf",
    }

    with patch("core.bulk_worker._estimate_ocr_confidence", return_value=None):
        skipped = await job._check_confidence_prescan(file_dict)

    assert skipped is False


# ── Bulk review queue API tests ────────────────────────────────────────────


async def test_get_review_queue_api(client, tmp_path):
    """GET /api/bulk/jobs/{id}/review-queue returns entries."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    await add_to_review_queue(job_id, file_id, source_path, ".pdf", 38.4)

    resp = await client.get(f"/api/bulk/jobs/{job_id}/review-queue")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["summary"]["pending"] >= 1
    assert data["summary"]["total"] >= 1
    assert len(data["entries"]) >= 1
    assert data["entries"][0]["estimated_confidence"] == 38.4


async def test_resolve_entry_skip(client, tmp_path):
    """POST resolve with action=skip sets status to skipped_permanently."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    entry_id = await add_to_review_queue(job_id, file_id, source_path, ".pdf", 38.4)

    resp = await client.post(
        f"/api/bulk/jobs/{job_id}/review-queue/{entry_id}/resolve",
        json={"action": "skip", "notes": "Not needed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "skipped_permanently"
    assert data["action"] == "skip"

    # Verify in DB
    entry = await get_review_queue_entry(entry_id)
    assert entry["status"] == "skipped_permanently"
    assert entry["notes"] == "Not needed"


async def test_resolve_all_with_skip(client, tmp_path):
    """POST resolve-all with action=skip marks all pending as skipped."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    await add_to_review_queue(job_id, file_id, source_path, ".pdf", 30.0)
    await add_to_review_queue(job_id, file_id, source_path + "2", ".pdf", 35.0)

    resp = await client.post(
        f"/api/bulk/jobs/{job_id}/review-queue/resolve-all",
        json={"action": "skip"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued"] == 2
    assert data["action"] == "skip"

    # Verify both are skipped
    summary = await get_review_queue_summary(job_id)
    assert summary["pending"] == 0
    assert summary["skipped_permanently"] == 2


async def test_resolve_all_review_action_rejected(client, tmp_path):
    """resolve-all with action=review returns 422."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    await add_to_review_queue(job_id, file_id, source_path, ".pdf", 30.0)

    resp = await client.post(
        f"/api/bulk/jobs/{job_id}/review-queue/resolve-all",
        json={"action": "review"},
    )
    assert resp.status_code == 422


async def test_resolve_entry_convert(client, tmp_path):
    """POST resolve with action=convert starts conversion."""
    job_id, file_id, source_path = await _create_job_with_file(tmp_path)
    entry_id = await add_to_review_queue(job_id, file_id, source_path, ".pdf", 38.4)

    # Mock the conversion to prevent actual file processing
    with patch("api.routes.bulk._convert_single_review_entry", new_callable=AsyncMock) as mock_convert:
        mock_convert.return_value = "batch_123"
        resp = await client.post(
            f"/api/bulk/jobs/{job_id}/review-queue/{entry_id}/resolve",
            json={"action": "convert"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "convert"
    assert data["status"] == "converting"


async def test_review_queue_for_nonexistent_job(client):
    """GET review-queue for nonexistent job returns 404."""
    resp = await client.get("/api/bulk/jobs/nonexistent/review-queue")
    assert resp.status_code == 404
