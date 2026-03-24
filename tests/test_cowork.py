"""Tests for the Cowork integration API."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api.routes.cowork import _truncate_at_paragraph
from core.database import init_db


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


# ── Truncation helper tests ─────────────────────────────────────────────────


def test_truncate_under_limit():
    content = "Short paragraph.\n\nAnother paragraph."
    result, truncated = _truncate_at_paragraph(content, 1000)
    assert result == content
    assert truncated is False


def test_truncate_at_paragraph_boundary():
    content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph that is very long."
    result, truncated = _truncate_at_paragraph(content, 40)
    assert truncated is True
    # Should truncate at paragraph boundary
    assert result.endswith("Second paragraph.")


def test_truncate_at_newline_fallback():
    content = "Line one\nLine two\nLine three\nLine four that is very long and goes on"
    result, truncated = _truncate_at_paragraph(content, 30)
    assert truncated is True


def test_truncate_no_boundary():
    content = "Onelongwordwithoutbreaks" * 20
    result, truncated = _truncate_at_paragraph(content, 50)
    assert truncated is True
    assert len(result) <= 50


# ── Cowork API tests ────────────────────────────────────────────────────────


class TestCoworkSearch:
    async def test_search_returns_content(self, client, tmp_path):
        """GET /api/cowork/search returns full md content."""
        md_file = tmp_path / "test.md"
        md_file.write_text(
            "---\ntitle: Test\n---\n\n# Introduction\n\nFull document content here.\n",
            encoding="utf-8",
        )

        with patch("api.routes.cowork.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = True
            mock_client.search.return_value = {
                "hits": [
                    {
                        "title": "Test",
                        "source_filename": "test.docx",
                        "source_format": "docx",
                        "relative_path": "test.md",
                        "source_path": "/src/test.docx",
                        "output_path": str(md_file),
                        "converted_at": "2026-03-21",
                    }
                ],
                "estimatedTotalHits": 1,
            }
            mock_fn.return_value = mock_client

            resp = await client.get("/api/cowork/search?q=test+content")
            assert resp.status_code == 200
            data = resp.json()
            assert data["result_count"] == 1
            result = data["results"][0]
            assert "Introduction" in result["content"]
            assert "Full document content" in result["content"]
            assert result["content_truncated"] is False

    async def test_search_truncates_long_content(self, client, tmp_path):
        """Content exceeding token limit is truncated."""
        long_content = ("This is a paragraph.\n\n") * 500
        md_file = tmp_path / "long.md"
        md_file.write_text(f"---\ntitle: Long\n---\n\n{long_content}", encoding="utf-8")

        with patch("api.routes.cowork.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = True
            mock_client.search.return_value = {
                "hits": [{"title": "Long", "output_path": str(md_file)}],
                "estimatedTotalHits": 1,
            }
            mock_fn.return_value = mock_client

            resp = await client.get("/api/cowork/search?q=test&max_tokens_per_doc=1000")
            assert resp.status_code == 200
            data = resp.json()
            if data["results"]:
                result = data["results"][0]
                assert result["content_truncated"] is True
                assert len(result["content"]) <= 4000  # 1000 tokens * 4 chars

    async def test_search_skips_missing_md(self, client):
        """Missing .md files are skipped gracefully."""
        with patch("api.routes.cowork.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = True
            mock_client.search.return_value = {
                "hits": [{"title": "Missing", "output_path": "/nonexistent/file.md"}],
                "estimatedTotalHits": 1,
            }
            mock_fn.return_value = mock_client

            resp = await client.get("/api/cowork/search?q=test+query")
            assert resp.status_code == 200
            data = resp.json()
            assert data["result_count"] == 0

    async def test_search_unavailable(self, client):
        """503 when Meilisearch is down."""
        with patch("api.routes.cowork.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = False
            mock_fn.return_value = mock_client

            resp = await client.get("/api/cowork/search?q=test")
            assert resp.status_code == 503


class TestCoworkStatus:
    async def test_status_available(self, client):
        """Status endpoint reports available state."""
        with patch("api.routes.cowork.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = True
            mock_client.get_index_stats.return_value = {"numberOfDocuments": 500}
            mock_fn.return_value = mock_client

            resp = await client.get("/api/cowork/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["available"] is True
            assert data["document_count"] == 500

    async def test_status_unavailable(self, client):
        """Status endpoint reports unavailable state."""
        with patch("api.routes.cowork.get_meili_client") as mock_fn:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = False
            mock_fn.return_value = mock_client

            resp = await client.get("/api/cowork/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["available"] is False
            assert data["document_count"] == 0
