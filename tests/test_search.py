"""Tests for Meilisearch integration — client, indexer, and search API."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.search_client import MeilisearchClient
from core.search_indexer import (
    SearchIndexer,
    _doc_id,
    _extract_headings,
    _strip_for_indexing,
)
from core.database import init_db


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


# ── Helper function tests ────────────────────────────────────────────────────


def test_doc_id_deterministic():
    id1 = _doc_id("/mnt/source/test.docx")
    id2 = _doc_id("/mnt/source/test.docx")
    assert id1 == id2
    assert len(id1) == 16


def test_doc_id_different_paths():
    id1 = _doc_id("/a/test.docx")
    id2 = _doc_id("/b/test.docx")
    assert id1 != id2


def test_extract_headings():
    content = "# Title\n\nSome text\n\n## Section\n\n### Subsection\n\n#### Too deep"
    headings = _extract_headings(content)
    assert headings == ["Title", "Section", "Subsection"]


def test_extract_headings_empty():
    assert _extract_headings("No headings here") == []


def test_strip_for_indexing():
    content = "---\ntitle: Test\n---\n# Heading\n\n![img](path/to/img.png)\n\nSome `code` text."
    stripped = _strip_for_indexing(content)
    assert "---" not in stripped
    assert "![img]" not in stripped
    assert "code" not in stripped  # inline code stripped
    assert "Heading" in stripped
    assert "Some" in stripped


# ── MeilisearchClient tests ──────────────────────────────────────────────────


class TestMeilisearchClient:
    async def test_health_check_unavailable(self):
        """Health check returns False when Meilisearch is down."""
        client = MeilisearchClient(host="http://localhost:19999")
        result = await client.health_check()
        assert result is False

    async def test_search_unavailable(self):
        """Search returns empty hits when unavailable."""
        client = MeilisearchClient(host="http://localhost:19999")
        result = await client.search("documents", "test")
        assert result == {"hits": [], "estimatedTotalHits": 0, "processingTimeMs": 0}

    async def test_get_index_stats_unavailable(self):
        client = MeilisearchClient(host="http://localhost:19999")
        result = await client.get_index_stats("documents")
        assert result == {}

    async def test_add_documents_unavailable(self):
        client = MeilisearchClient(host="http://localhost:19999")
        result = await client.add_documents("documents", [{"id": "test"}])
        assert result is None


# ── SearchIndexer tests ──────────────────────────────────────────────────────


class TestSearchIndexer:
    async def test_index_document(self, tmp_path):
        """index_document reads .md and calls add_documents with correct shape."""
        md_file = tmp_path / "test.md"
        md_file.write_text(
            "---\nmarkflow:\n  source_file: test.docx\n  source_format: docx\n"
            "  converted_at: '2026-03-21'\n  fidelity_tier: 2\n  ocr_applied: false\n"
            "title: Test Document\n---\n\n# Introduction\n\nThis is a test document.\n",
            encoding="utf-8",
        )

        mock_client = AsyncMock(spec=MeilisearchClient)
        mock_client.add_documents.return_value = "task_123"
        indexer = SearchIndexer(client=mock_client)

        result = await indexer.index_document(md_file, job_id="job1")
        assert result is True

        mock_client.add_documents.assert_called_once()
        call_args = mock_client.add_documents.call_args
        assert call_args[0][0] == "documents"
        doc = call_args[0][1][0]
        assert doc["title"] == "Test Document"
        assert doc["source_format"] == "docx"
        assert doc["job_id"] == "job1"
        assert "Introduction" in doc["headings"]

    async def test_index_document_missing_file(self, tmp_path):
        """Missing .md file returns False."""
        mock_client = AsyncMock(spec=MeilisearchClient)
        indexer = SearchIndexer(client=mock_client)
        result = await indexer.index_document(tmp_path / "missing.md", "job1")
        assert result is False

    async def test_index_adobe_file(self):
        """index_adobe_file calls add_documents on adobe-files index."""
        from core.adobe_indexer import AdobeIndexResult

        mock_client = AsyncMock(spec=MeilisearchClient)
        mock_client.add_documents.return_value = "task_456"
        indexer = SearchIndexer(client=mock_client)

        result_obj = AdobeIndexResult(
            source_path=Path("/src/logo.psd"),
            file_ext=".psd",
            file_size_bytes=5000,
            metadata={"Title": "Logo", "Creator": "Photoshop"},
            text_layers=["Layer text"],
        )

        with patch("core.database.get_adobe_index_entry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"id": "entry123"}
            with patch("core.database.mark_adobe_meili_indexed", new_callable=AsyncMock):
                ok = await indexer.index_adobe_file(result_obj, "job1")

        assert ok is True
        mock_client.add_documents.assert_called_once()
        call_args = mock_client.add_documents.call_args
        assert call_args[0][0] == "adobe-files"
        doc = call_args[0][1][0]
        assert doc["file_ext"] == ".psd"
        assert doc["title"] == "Logo"

    async def test_ensure_indexes(self):
        """ensure_indexes creates indexes and updates settings."""
        mock_client = AsyncMock(spec=MeilisearchClient)
        mock_client.health_check.return_value = True
        indexer = SearchIndexer(client=mock_client)

        await indexer.ensure_indexes()

        assert mock_client.create_index.call_count == 2
        assert mock_client.update_index_settings.call_count == 2


# ── Search API tests ─────────────────────────────────────────────────────────


class TestSearchAPI:
    async def test_search_query_too_short(self, client):
        """Query < 2 chars returns 422."""
        resp = await client.get("/api/search?q=x")
        assert resp.status_code == 422

    async def test_search_meilisearch_unavailable(self, client):
        """Returns 503 when Meilisearch is down."""
        with patch("api.routes.search.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = False
            mock_fn.return_value = mock_client

            resp = await client.get("/api/search?q=test+query")
            assert resp.status_code == 503

    async def test_search_index_status(self, client):
        """GET /api/search/index/status returns structure."""
        with patch("api.routes.search.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = False
            mock_fn.return_value = mock_client

            resp = await client.get("/api/search/index/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "available" in data
            assert "documents" in data
            assert "adobe_files" in data

    async def test_search_returns_hits(self, client):
        """Successful search returns hits array."""
        with patch("api.routes.search.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = True
            mock_client.search.return_value = {
                "hits": [
                    {
                        "id": "abc123",
                        "title": "Q4 Report",
                        "source_filename": "Q4.docx",
                        "source_format": "docx",
                        "content_preview": "Financial results...",
                        "_formatted": {"content": "<em>Q4</em> results..."},
                    }
                ],
                "estimatedTotalHits": 1,
                "processingTimeMs": 2,
            }
            mock_fn.return_value = mock_client

            resp = await client.get("/api/search?q=Q4+results")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_hits"] == 1
            assert len(data["hits"]) == 1
            assert data["hits"][0]["title"] == "Q4 Report"
