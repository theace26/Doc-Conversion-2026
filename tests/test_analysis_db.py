import pytest
import pytest_asyncio
from pathlib import Path


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    import core.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield


@pytest.mark.asyncio
async def test_enqueue_new_file(db):
    from core.db.analysis import enqueue_for_analysis, get_analysis_stats
    entry_id = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    assert entry_id is not None
    stats = await get_analysis_stats()
    assert stats["pending"] == 1


@pytest.mark.asyncio
async def test_enqueue_dedup_pending(db):
    from core.db.analysis import enqueue_for_analysis
    id1 = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    id2 = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    assert id1 == id2


@pytest.mark.asyncio
async def test_enqueue_skips_completed_same_hash(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results
    await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    rows = await claim_pending_batch(10)
    await write_batch_results([{
        "id": rows[0]["id"],
        "description": "A cat",
        "extracted_text": "",
        "provider_id": "anthropic",
        "model": "claude-3-opus-20240229",
    }])
    result = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    assert result is None


@pytest.mark.asyncio
async def test_claim_batch(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch
    for i in range(5):
        await enqueue_for_analysis(f"/nas/photos/img{i}.jpg")
    rows = await claim_pending_batch(3)
    assert len(rows) == 3
    for r in rows:
        assert r["batch_id"] is not None


@pytest.mark.asyncio
async def test_write_results_completed(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results, get_analysis_stats
    await enqueue_for_analysis("/nas/photos/cat.jpg")
    rows = await claim_pending_batch(10)
    await write_batch_results([{
        "id": rows[0]["id"],
        "description": "A fluffy cat",
        "extracted_text": "No text",
        "provider_id": "anthropic",
        "model": "claude-3-opus-20240229",
        "tokens_used": 1500,
    }])
    stats = await get_analysis_stats()
    assert stats["completed"] == 1
    assert stats["pending"] == 0


@pytest.mark.asyncio
async def test_token_summary(db):
    from core.db.analysis import (
        enqueue_for_analysis, claim_pending_batch,
        write_batch_results, get_analysis_token_summary,
    )
    for i in range(3):
        await enqueue_for_analysis(f"/nas/photos/img{i}.jpg", content_hash=f"hash{i}")
    rows = await claim_pending_batch(10)
    await write_batch_results([
        {"id": rows[0]["id"], "description": "A", "extracted_text": "",
         "provider_id": "anthropic", "model": "claude-sonnet-4-20250514", "tokens_used": 1000},
        {"id": rows[1]["id"], "description": "B", "extracted_text": "",
         "provider_id": "anthropic", "model": "claude-sonnet-4-20250514", "tokens_used": 2000},
        {"id": rows[2]["id"], "description": "C", "extracted_text": "",
         "provider_id": "openai", "model": "gpt-4o", "tokens_used": 500},
    ])
    summary = await get_analysis_token_summary()
    assert summary["total_analyzed"] == 3
    assert summary["total_tokens"] == 3500
    assert len(summary["by_model"]) == 2


@pytest.mark.asyncio
async def test_write_results_failed_retry(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results, get_analysis_stats
    await enqueue_for_analysis("/nas/photos/cat.jpg")
    for _ in range(2):
        rows = await claim_pending_batch(10)
        await write_batch_results([{"id": rows[0]["id"], "error": "timeout"}])
    stats = await get_analysis_stats()
    assert stats["pending"] == 1
    assert stats["failed"] == 0


@pytest.mark.asyncio
async def test_write_results_failed_exhausted(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results, get_analysis_stats
    await enqueue_for_analysis("/nas/photos/cat.jpg")
    for _ in range(3):
        rows = await claim_pending_batch(10)
        if not rows:
            break
        await write_batch_results([{"id": rows[0]["id"], "error": "timeout"}])
    stats = await get_analysis_stats()
    assert stats["failed"] == 1
