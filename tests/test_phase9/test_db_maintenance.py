"""Tests for core/db_maintenance.py — DB health functions."""

import pytest
import pytest_asyncio

from core.database import init_db, get_maintenance_log
from core.db_maintenance import (
    get_health_summary,
    run_compaction,
    run_integrity_check,
    run_stale_data_check,
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_integrity_check_ok():
    """Clean DB returns ok."""
    result = await run_integrity_check()
    assert result["result"] == "ok"
    assert "ok" in result["findings"]


@pytest.mark.asyncio
async def test_compaction_logs():
    """Compaction creates a maintenance log entry."""
    await run_compaction()
    logs = await get_maintenance_log(limit=5)
    compaction_logs = [l for l in logs if l["operation"] == "compaction"]
    assert len(compaction_logs) >= 1
    assert compaction_logs[0]["result"] == "ok"


@pytest.mark.asyncio
async def test_stale_data_check_runs():
    """Stale check returns dict with all expected keys."""
    result = await run_stale_data_check()
    expected_keys = {
        "orphaned_versions",
        "missing_md_files",
        "stale_meilisearch",
        "dangling_trash",
        "expired_trash",
        "expired_grace",
    }
    assert expected_keys.issubset(set(result.keys()))
    for key, val in result.items():
        assert "severity" in val
        assert val["severity"] in ("ok", "warning", "error")


@pytest.mark.asyncio
async def test_health_summary():
    """get_health_summary returns well-formed dict."""
    summary = await get_health_summary()
    assert "db_size_bytes" in summary
    assert "page_count" in summary
    assert "journal_mode" in summary
    assert "last_compaction" in summary
    assert "last_integrity_check" in summary
