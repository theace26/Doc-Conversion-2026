import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    import core.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield


@pytest.mark.asyncio
async def test_drain_skips_when_no_provider(db):
    with patch("core.analysis_worker.get_active_provider", new_callable=AsyncMock, return_value=None), \
         patch("core.analysis_worker.get_preference", new_callable=AsyncMock, return_value="true"), \
         patch("core.analysis_worker.get_all_active_jobs", new_callable=AsyncMock, return_value=[]):
        from core.analysis_worker import run_analysis_drain
        await run_analysis_drain()  # should not raise


@pytest.mark.asyncio
async def test_drain_skips_when_disabled(db):
    with patch("core.analysis_worker.get_preference", new_callable=AsyncMock, return_value="false"):
        from core.analysis_worker import run_analysis_drain
        await run_analysis_drain()


@pytest.mark.asyncio
async def test_drain_processes_pending_images(db, tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    from core.db.analysis import enqueue_for_analysis, get_analysis_stats
    await enqueue_for_analysis(str(img))

    mock_result = MagicMock()
    mock_result.description = "A test image"
    mock_result.extracted_text = "Hello"
    mock_result.error = None

    provider = {"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""}

    with patch("core.analysis_worker.get_active_provider", new_callable=AsyncMock, return_value=provider), \
         patch("core.analysis_worker.get_preference", new_callable=AsyncMock, return_value="10"), \
         patch("core.analysis_worker.get_all_active_jobs", new_callable=AsyncMock, return_value=[]), \
         patch("core.analysis_worker._reindex_completed", new_callable=AsyncMock), \
         patch("core.vision_adapter.VisionAdapter.describe_batch",
               new_callable=AsyncMock, return_value=[mock_result]):
        from core.analysis_worker import run_analysis_drain
        await run_analysis_drain()

    stats = await get_analysis_stats()
    assert stats["completed"] == 1
    assert stats["pending"] == 0
