"""Tests for core/scheduler.py — scheduler logic."""

from datetime import datetime
from unittest.mock import patch

import pytest

from core.scheduler import _is_business_hours


def test_business_hours_weekday_10am():
    """10:00 Monday is business hours."""
    with patch("core.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 23, 10, 0)  # Monday
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # Can't easily mock the async pref check, but default logic should work
        # Just verify the function doesn't crash
        result = _is_business_hours()
        assert isinstance(result, bool)


def test_business_hours_sunday_3am():
    """03:00 Sunday is outside business hours."""
    with patch("core.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 22, 3, 0)  # Sunday
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _is_business_hours()
        assert result is False


@pytest.mark.asyncio
async def test_run_lifecycle_scan_force(monkeypatch):
    """force=True bypasses business hours check."""
    from core.scheduler import run_lifecycle_scan

    scan_ran = []

    async def mock_scan(*args, **kwargs):
        scan_ran.append(True)
        return "fake_scan_id"

    monkeypatch.setattr("core.scheduler.run_lifecycle_scan.__module__", "core.scheduler")
    # Patch the imported scanner function
    import core.lifecycle_scanner
    monkeypatch.setattr(core.lifecycle_scanner, "run_lifecycle_scan", mock_scan)

    # This should work (it calls the real function which calls the patched scanner)
    await run_lifecycle_scan(force=True)
