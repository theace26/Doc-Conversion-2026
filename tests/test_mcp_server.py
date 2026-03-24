"""
Tests for Track D — MCP server tools.

Tests the tool implementations directly (not the MCP transport layer).
"""

import pytest
from pathlib import Path

from core.database import init_db


@pytest.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("core.database.DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-mcp-tests!")
    await init_db()
    yield


# ── Tool: list_directory ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_directory_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    from mcp_server.tools import list_directory
    result = await list_directory()
    assert "Contents of" in result


@pytest.mark.asyncio
async def test_list_directory_with_files(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    (tmp_path / "doc.md").write_text("# Hello")
    (tmp_path / "subdir").mkdir()
    from mcp_server.tools import list_directory
    result = await list_directory()
    assert "doc.md" in result
    assert "subdir" in result


@pytest.mark.asyncio
async def test_list_directory_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    from mcp_server.tools import list_directory
    result = await list_directory("nonexistent")
    assert "not found" in result


# ── Tool: read_document ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_document_success(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    (tmp_path / "report.md").write_text("# Report\n\nSome content.")
    from mcp_server.tools import read_document
    result = await read_document("report.md")
    assert "# Report" in result
    assert "Some content" in result


@pytest.mark.asyncio
async def test_read_document_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    from mcp_server.tools import read_document
    result = await read_document("missing.md")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_read_document_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    (tmp_path / "big.md").write_text("x" * 100000)
    from mcp_server.tools import read_document
    result = await read_document("big.md", max_tokens=100)
    assert "Truncated" in result


# ── Tool: get_conversion_status ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_conversion_status_no_conversions():
    from mcp_server.tools import get_conversion_status
    result = await get_conversion_status()
    assert "No recent" in result


@pytest.mark.asyncio
async def test_get_conversion_status_with_history():
    from core.database import record_conversion
    await record_conversion({
        "batch_id": "mcp_test_batch",
        "source_filename": "test.pdf",
        "source_format": "pdf",
        "output_filename": "test.md",
        "output_format": "md",
        "direction": "to_md",
        "status": "success",
    })
    from mcp_server.tools import get_conversion_status
    result = await get_conversion_status()
    assert "test.pdf" in result


@pytest.mark.asyncio
async def test_get_conversion_status_specific_batch():
    from mcp_server.tools import get_conversion_status
    result = await get_conversion_status(batch_id="nonexistent")
    assert "not found" in result.lower()


# ── Tool: search_documents ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_documents_no_meilisearch():
    """Search gracefully handles Meilisearch being unavailable."""
    from mcp_server.tools import search_documents
    result = await search_documents("test query")
    # Either returns "unavailable" or "error" — shouldn't crash
    assert isinstance(result, str)


# ── Tool: get_document_summary ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_document_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    content = "---\ntitle: Test Doc\nsource_format: pdf\n---\n# Test\nContent here."
    (tmp_path / "test.md").write_text(content)
    from mcp_server.tools import get_document_summary
    result = await get_document_summary("test.md")
    assert "Test Doc" in result
    assert "pdf" in result


@pytest.mark.asyncio
async def test_get_document_summary_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.tools.OUTPUT_DIR", tmp_path)
    from mcp_server.tools import get_document_summary
    result = await get_document_summary("missing.md")
    assert "not found" in result.lower()


# ── Tool: convert_document ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_convert_document_file_not_found():
    from mcp_server.tools import convert_document
    result = await convert_document("/nonexistent/file.docx")
    assert "not found" in result.lower()


# ── MCP info endpoint ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_connection_info_api():
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/mcp/connection-info")
        assert resp.status_code == 200
        data = resp.json()
        assert "mcp_url" in data
        assert "mcp_running" in data
        assert "tool_count" in data
        assert data["tool_count"] == 7
