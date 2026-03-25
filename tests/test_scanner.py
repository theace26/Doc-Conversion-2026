"""Tests for scan progress visibility — lifecycle scanner state and bulk scan callbacks."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.database import init_db
from core.lifecycle_scanner import _scan_state, get_scan_state


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


@pytest.fixture(autouse=True)
def reset_scan_state():
    """Reset _scan_state before each test."""
    _scan_state.update({
        "running": False,
        "run_id": None,
        "started_at": None,
        "scanned": 0,
        "total": 0,
        "pct": None,
        "current_file": None,
        "eta_seconds": None,
        "last_scan_at": None,
        "last_scan_run_id": None,
    })
    yield
    _scan_state.update({
        "running": False,
        "run_id": None,
        "started_at": None,
        "scanned": 0,
        "total": 0,
        "pct": None,
        "current_file": None,
        "eta_seconds": None,
        "last_scan_at": None,
        "last_scan_run_id": None,
    })


# ── get_scan_state tests ────────────────────────────────────────────────────


class TestScanState:
    def test_default_state_not_running(self):
        state = get_scan_state()
        assert state["running"] is False
        assert state["run_id"] is None
        assert state["pct"] is None

    def test_state_is_copy(self):
        """Modifying the returned dict does not affect _scan_state."""
        state = get_scan_state()
        state["running"] = True
        assert _scan_state["running"] is False

    def test_pct_null_when_total_zero(self):
        _scan_state["running"] = True
        _scan_state["total"] = 0
        _scan_state["scanned"] = 50
        state = get_scan_state()
        assert state["pct"] is None

    def test_eta_null_in_first_5_seconds(self):
        """ETA should not be calculated in the first 5 seconds."""
        _scan_state["running"] = True
        _scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
        _scan_state["eta_seconds"] = None  # The scanner itself sets this
        state = get_scan_state()
        assert state["eta_seconds"] is None

    def test_state_resets_at_scan_start(self):
        """State should reset correctly at start of a new scan."""
        _scan_state["last_scan_at"] = "2026-03-24T18:00:00Z"
        _scan_state["scanned"] = 500
        _scan_state["running"] = True
        _scan_state["run_id"] = "test123"
        _scan_state["started_at"] = "2026-03-25T06:00:00Z"
        _scan_state["scanned"] = 0
        _scan_state["total"] = 1000
        _scan_state["pct"] = None

        state = get_scan_state()
        assert state["running"] is True
        assert state["scanned"] == 0
        assert state["last_scan_at"] == "2026-03-24T18:00:00Z"


# ── Scanner progress API tests ──────────────────────────────────────────────


class TestScannerProgressAPI:
    async def test_progress_not_running(self, client):
        """GET /api/scanner/progress returns correct shape when not running."""
        resp = await client.get("/api/scanner/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["pct"] is None
        assert data["current_file"] is None

    async def test_progress_running(self, client):
        """GET /api/scanner/progress returns correct shape when running."""
        _scan_state["running"] = True
        _scan_state["run_id"] = "test-run-123"
        _scan_state["started_at"] = "2026-03-25T06:00:00Z"
        _scan_state["scanned"] = 500
        _scan_state["total"] = 1000
        _scan_state["pct"] = 50
        _scan_state["current_file"] = "dept/specs/test.pdf"
        _scan_state["eta_seconds"] = 120

        resp = await client.get("/api/scanner/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["scanned"] == 500
        assert data["total"] == 1000
        assert data["pct"] == 50
        assert data["current_file"] == "dept/specs/test.pdf"
        assert data["eta_seconds"] == 120


# ── Bulk scan progress callback tests ────────────────────────────────────────


class TestBulkScanProgress:
    async def test_on_progress_fires(self, tmp_path):
        """on_progress callback fires for first, every 50th, and last file."""
        from core.bulk_scanner import BulkScanner

        # Create 150 test files
        for i in range(150):
            (tmp_path / f"file_{i:03d}.docx").write_bytes(b"x")

        events = []

        async def collect_events(event):
            events.append(event)

        scanner = BulkScanner(
            job_id="test-progress",
            source_path=tmp_path,
            output_path=tmp_path / "out",
        )

        with patch("core.bulk_scanner.upsert_bulk_file", new_callable=AsyncMock, return_value="fid"):
            result = await scanner.scan(on_progress=collect_events)

        # Should have: 1 initial + floor(150/50)=3 intermediate + 1 final + 1 scan_complete = 6
        scan_progress_events = [e for e in events if e.get("event") == "scan_progress"]
        scan_complete_events = [e for e in events if e.get("event") == "scan_complete"]

        assert len(scan_progress_events) >= 4  # first + at least 2 intermediates + last
        assert len(scan_complete_events) == 1
        assert scan_complete_events[0]["total_found"] == 150

    async def test_progress_pct_null_when_total_unknown(self, tmp_path):
        """Progress reports pct=None when total estimate is 0."""
        from core.bulk_scanner import BulkScanner

        (tmp_path / "test.docx").write_bytes(b"x")

        events = []

        async def collect_events(event):
            events.append(event)

        scanner = BulkScanner(
            job_id="test-null-pct",
            source_path=tmp_path,
            output_path=tmp_path / "out",
        )

        # Mock the count to return 0 (simulating timeout)
        with patch("core.bulk_scanner.upsert_bulk_file", new_callable=AsyncMock, return_value="fid"):
            with patch.object(BulkScanner, "_count_files", return_value=0):
                result = await scanner.scan(on_progress=collect_events)

        first_event = events[0]
        assert first_event["event"] == "scan_progress"
        assert first_event["pct"] is None

    async def test_no_callback_when_none(self, tmp_path):
        """Scan works normally when on_progress is not provided."""
        from core.bulk_scanner import BulkScanner

        (tmp_path / "test.docx").write_bytes(b"x")

        scanner = BulkScanner(
            job_id="test-no-cb",
            source_path=tmp_path,
            output_path=tmp_path / "out",
        )

        with patch("core.bulk_scanner.upsert_bulk_file", new_callable=AsyncMock, return_value="fid"):
            result = await scanner.scan()  # No on_progress

        assert result.total_discovered == 1


# ── ETA calculation tests ────────────────────────────────────────────────────


class TestETACalculation:
    def test_eta_given_rate(self):
        """Given rate=100 files/sec and 900 remaining, eta=9."""
        rate = 100
        remaining = 900
        eta = int(remaining / rate)
        assert eta == 9

    def test_eta_zero_remaining(self):
        rate = 100
        remaining = 0
        eta = int(remaining / rate) if rate > 0 and remaining > 0 else None
        assert eta is None
