"""
Tests for transcript indexing in Meilisearch and search API integration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── SearchIndexer.index_transcript ───────────────────────────────────────────


async def test_index_transcript_calls_add_documents():
    """index_transcript should build a document dict and add to 'transcripts' index."""
    from core.search_indexer import SearchIndexer

    mock_client = AsyncMock()
    mock_client.add_documents.return_value = "task_123"

    indexer = SearchIndexer(client=mock_client)

    result = await indexer.index_transcript(
        history_id="hist_001",
        title="Test Video",
        raw_text="Hello world this is a transcript",
        source_path="/mnt/source/test.mp4",
        source_format="mp4",
        duration_seconds=120.5,
        engine="whisper_local",
        whisper_model="base",
        language="en",
        word_count=7,
    )

    assert result is True
    mock_client.add_documents.assert_awaited_once()
    call_args = mock_client.add_documents.call_args
    assert call_args[0][0] == "transcripts"
    docs = call_args[0][1]
    assert len(docs) == 1
    assert docs[0]["id"] == "hist_001"
    assert docs[0]["title"] == "Test Video"
    assert docs[0]["engine"] == "whisper_local"
    assert docs[0]["word_count"] == 7


async def test_index_transcript_returns_false_on_failure():
    """index_transcript should return False if add_documents returns None."""
    from core.search_indexer import SearchIndexer

    mock_client = AsyncMock()
    mock_client.add_documents.return_value = None

    indexer = SearchIndexer(client=mock_client)

    result = await indexer.index_transcript(
        history_id="hist_002",
        title="Fail",
        raw_text="test",
        source_path="/test.mp3",
        source_format="mp3",
        duration_seconds=None,
        engine="whisper_local",
        whisper_model=None,
        language=None,
        word_count=1,
    )

    assert result is False


# ── ensure_indexes includes transcripts ──────────────────────────────────────


async def test_ensure_indexes_creates_transcripts():
    """ensure_indexes should create the 'transcripts' index."""
    from core.search_indexer import SearchIndexer

    mock_client = AsyncMock()
    mock_client.health_check.return_value = True
    mock_client.create_index.return_value = None
    mock_client.update_index_settings.return_value = None

    indexer = SearchIndexer(client=mock_client)
    await indexer.ensure_indexes()

    # Verify transcripts index was created
    create_calls = [c[0][0] for c in mock_client.create_index.call_args_list]
    assert "transcripts" in create_calls

    settings_calls = [c[0][0] for c in mock_client.update_index_settings.call_args_list]
    assert "transcripts" in settings_calls


# ── Search API with transcripts index ────────────────────────────────────────


async def test_search_api_accepts_transcripts_index(client):
    """GET /api/search?q=test&index=transcripts should not 422."""
    resp = await client.get("/api/search", params={"q": "test query", "index": "transcripts"})
    # May return 503 if Meilisearch is down, but should NOT return 422
    assert resp.status_code in (200, 503)


async def test_search_api_rejects_invalid_index(client):
    """GET /api/search?q=test&index=invalid should 422."""
    resp = await client.get("/api/search", params={"q": "test query", "index": "invalid"})
    assert resp.status_code == 422


# ── Search index/status includes transcripts ────────────────────────────────


async def test_index_status_includes_transcripts(client):
    """GET /api/search/index/status should include transcripts."""
    resp = await client.get("/api/search/index/status")
    if resp.status_code == 200:
        data = resp.json()
        assert "transcripts" in data


# ── Cowork search with transcripts ───────────────────────────────────────────


async def test_cowork_search_includes_transcripts_param(client):
    """GET /api/cowork/search should accept include_transcripts parameter."""
    resp = await client.get(
        "/api/cowork/search",
        params={"q": "test query", "include_transcripts": "false"},
    )
    # May return 503 if Meilisearch is down, but should NOT return 422
    assert resp.status_code in (200, 503)
