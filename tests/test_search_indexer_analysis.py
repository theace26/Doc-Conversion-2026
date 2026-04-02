import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


@pytest.mark.asyncio
async def test_index_document_includes_analysis_results(tmp_path, monkeypatch):
    import core.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()

    # Frontmatter so source_path is known without a DB lookup (markflow nested key)
    md_file = tmp_path / "photo.md"
    md_file.write_text(
        "---\nmarkflow:\n  source_path: /nas/photo.jpg\n  source_format: jpg\n---\n\n# photo.jpg\n\nFormat: JPEG\n",
        encoding="utf-8",
    )

    analysis_row = {
        "description": "A sunset over the ocean",
        "extracted_text": "No Trespassing",
        "status": "completed",
    }

    indexed_docs = []

    async def mock_add_docs(index, docs):
        indexed_docs.extend(docs)
        return "task-1"

    with patch("core.db.analysis.get_analysis_result",
               new_callable=AsyncMock, return_value=analysis_row):
        from core.search_indexer import SearchIndexer
        indexer = SearchIndexer.__new__(SearchIndexer)
        indexer.client = MagicMock()
        indexer.client.add_documents = AsyncMock(side_effect=mock_add_docs)

        await indexer.index_document(md_file, "job-1")

    assert len(indexed_docs) == 1
    doc = indexed_docs[0]
    assert "sunset" in doc["content"]
    assert "No Trespassing" in doc["content"]
