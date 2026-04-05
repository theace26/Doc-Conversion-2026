"""
Tests for core.vector.index_manager — VectorIndexManager with mocked Qdrant.

All Qdrant I/O is mocked with AsyncMock; no real Qdrant connection is made.
The qdrant_client package is skipped if not installed (pytest.importorskip).
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip entire module if qdrant_client is not installed
qdrant_client = pytest.importorskip("qdrant_client")

from core.vector.index_manager import VectorIndexManager, _deterministic_id  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_DIM = 384
FAKE_VECTOR = [0.1] * FAKE_DIM


def _make_embedder() -> MagicMock:
    """Return a mock embedder that always returns FAKE_VECTOR per text."""
    embedder = MagicMock()
    embedder.dimension = FAKE_DIM
    embedder.model_name = "all-MiniLM-L6-v2"
    embedder.embed = MagicMock(side_effect=lambda texts: [FAKE_VECTOR for _ in texts])
    return embedder


def _make_client() -> AsyncMock:
    """Return an AsyncMock Qdrant client with sensible defaults."""
    client = AsyncMock()

    # get_collections returns an object with a .collections list
    collections_resp = MagicMock()
    collections_resp.collections = []
    client.get_collections = AsyncMock(return_value=collections_resp)

    # create_collection, create_payload_index, upsert, delete return None
    client.create_collection = AsyncMock(return_value=None)
    client.create_payload_index = AsyncMock(return_value=None)
    client.upsert = AsyncMock(return_value=None)
    client.delete = AsyncMock(return_value=None)

    # get_collection returns an info object
    collection_info = MagicMock()
    collection_info.vectors_count = 42
    client.get_collection = AsyncMock(return_value=collection_info)

    # search returns an empty list by default
    client.search = AsyncMock(return_value=[])

    return client


def _make_manager(client=None, embedder=None, collection="test_col") -> VectorIndexManager:
    if client is None:
        client = _make_client()
    if embedder is None:
        embedder = _make_embedder()
    return VectorIndexManager(client=client, embedder=embedder, collection_name=collection)


# ---------------------------------------------------------------------------
# _deterministic_id helper
# ---------------------------------------------------------------------------

class TestDeterministicId:
    def test_returns_integer(self):
        result = _deterministic_id("doc1", 0)
        assert isinstance(result, int)

    def test_stable(self):
        a = _deterministic_id("doc1", 0)
        b = _deterministic_id("doc1", 0)
        assert a == b

    def test_different_chunk_indices_differ(self):
        assert _deterministic_id("doc1", 0) != _deterministic_id("doc1", 1)

    def test_different_doc_ids_differ(self):
        assert _deterministic_id("docA", 0) != _deterministic_id("docB", 0)

    def test_matches_expected_sha256_slice(self):
        raw = b"doc1:0"
        expected = int(hashlib.sha256(raw).hexdigest()[:16], 16)
        assert _deterministic_id("doc1", 0) == expected


# ---------------------------------------------------------------------------
# ensure_collection
# ---------------------------------------------------------------------------

class TestEnsureCollection:
    @pytest.mark.asyncio
    async def test_creates_collection_when_missing(self):
        client = _make_client()
        manager = _make_manager(client=client, collection="markflow")
        await manager.ensure_collection()
        client.create_collection.assert_called_once()
        call_kwargs = client.create_collection.call_args.kwargs
        assert call_kwargs["collection_name"] == "markflow"

    @pytest.mark.asyncio
    async def test_skips_create_when_collection_exists(self):
        client = _make_client()
        existing = MagicMock()
        existing.name = "markflow"
        client.get_collections.return_value = MagicMock(collections=[existing])

        manager = _make_manager(client=client, collection="markflow")
        await manager.ensure_collection()
        client.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_payload_indexes(self):
        client = _make_client()
        manager = _make_manager(client=client, collection="markflow")
        await manager.ensure_collection()
        # Should create indexes for doc_id, source_index, source_format, is_flagged
        assert client.create_payload_index.call_count == 4
        indexed_fields = {
            call.kwargs["field_name"]
            for call in client.create_payload_index.call_args_list
        }
        assert "doc_id" in indexed_fields
        assert "source_index" in indexed_fields
        assert "source_format" in indexed_fields
        assert "is_flagged" in indexed_fields


# ---------------------------------------------------------------------------
# index_document
# ---------------------------------------------------------------------------

class TestIndexDocument:
    @pytest.mark.asyncio
    async def test_upserts_to_correct_collection(self):
        client = _make_client()
        manager = _make_manager(client=client, collection="my_col")

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Hello\n\nThis is test content for the index.\n")
            tmp_path = Path(f.name)

        count = await manager.index_document(
            md_path=tmp_path,
            doc_id="doc42",
            title="Hello Doc",
            source_path="/mnt/source/hello.pdf",
            source_format="pdf",
        )

        assert count > 0
        client.upsert.assert_called_once()
        call_kwargs = client.upsert.call_args.kwargs
        assert call_kwargs["collection_name"] == "my_col"

    @pytest.mark.asyncio
    async def test_upsert_points_have_correct_payload(self):
        client = _make_client()
        manager = _make_manager(client=client)

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Section\n\nSome meaningful content here.\n")
            tmp_path = Path(f.name)

        await manager.index_document(
            md_path=tmp_path,
            doc_id="docXYZ",
            title="My Title",
            source_path="/mnt/source/file.docx",
            source_format="docx",
            source_index="archive",
            is_flagged=True,
        )

        points = client.upsert.call_args.kwargs["points"]
        assert len(points) > 0
        payload = points[0].payload
        assert payload["doc_id"] == "docXYZ"
        assert payload["title"] == "My Title"
        assert payload["source_path"] == "/mnt/source/file.docx"
        assert payload["source_format"] == "docx"
        assert payload["source_index"] == "archive"
        assert payload["is_flagged"] is True

    @pytest.mark.asyncio
    async def test_point_ids_are_deterministic(self):
        client = _make_client()
        manager = _make_manager(client=client)

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Alpha\n\nContent alpha.\n\n# Beta\n\nContent beta.\n")
            tmp_path = Path(f.name)

        await manager.index_document(
            md_path=tmp_path,
            doc_id="stable_doc",
            title="T",
            source_path="",
            source_format="md",
        )

        points = client.upsert.call_args.kwargs["points"]
        for point in points:
            expected_id = _deterministic_id("stable_doc", point.payload["chunk_index"])
            assert point.id == expected_id

    @pytest.mark.asyncio
    async def test_returns_chunk_count(self):
        client = _make_client()
        embedder = _make_embedder()
        manager = _make_manager(client=client, embedder=embedder)

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# A\n\nContent A.\n\n# B\n\nContent B.\n")
            tmp_path = Path(f.name)

        count = await manager.index_document(
            md_path=tmp_path,
            doc_id="cnt_doc",
            title="Count Test",
            source_path="",
            source_format="md",
        )

        points = client.upsert.call_args.kwargs["points"]
        assert count == len(points)

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_file(self):
        client = _make_client()
        manager = _make_manager(client=client)

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("")  # empty markdown
            tmp_path = Path(f.name)

        count = await manager.index_document(
            md_path=tmp_path,
            doc_id="empty_doc",
            title="Empty",
            source_path="",
            source_format="md",
        )

        assert count == 0
        client.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_embeds_all_chunk_texts_in_one_batch(self):
        client = _make_client()
        embedder = _make_embedder()
        manager = _make_manager(client=client, embedder=embedder)

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# A\n\nContent A.\n\n# B\n\nContent B.\n")
            tmp_path = Path(f.name)

        await manager.index_document(
            md_path=tmp_path,
            doc_id="batch_doc",
            title="Batch",
            source_path="",
            source_format="md",
        )

        # embed should have been called exactly once (batch call)
        assert embedder.embed.call_count == 1
        texts_arg = embedder.embed.call_args.args[0]
        assert len(texts_arg) >= 1


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------

class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_calls_client_delete(self):
        client = _make_client()
        manager = _make_manager(client=client, collection="col")

        await manager.delete_document("doc_to_delete")

        client.delete.assert_called_once()
        call_kwargs = client.delete.call_args.kwargs
        assert call_kwargs["collection_name"] == "col"

    @pytest.mark.asyncio
    async def test_delete_filter_contains_doc_id(self):
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = _make_client()
        manager = _make_manager(client=client)

        await manager.delete_document("target_doc")

        call_kwargs = client.delete.call_args.kwargs
        points_selector = call_kwargs["points_selector"]

        # Inspect the filter structure
        assert isinstance(points_selector, Filter)
        assert len(points_selector.must) == 1
        condition = points_selector.must[0]
        assert isinstance(condition, FieldCondition)
        assert condition.key == "doc_id"
        assert condition.match.value == "target_doc"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:
    def _make_hit(self, score: float, payload: dict) -> MagicMock:
        hit = MagicMock()
        hit.score = score
        hit.payload = payload
        return hit

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        client = _make_client()
        client.search = AsyncMock(return_value=[
            self._make_hit(0.95, {
                "doc_id": "d1",
                "title": "Title 1",
                "heading_path": "Intro",
                "chunk_text": "Some text",
                "source_path": "/path/to/file.pdf",
                "source_format": "pdf",
                "source_index": "documents",
            }),
        ])
        manager = _make_manager(client=client)

        results = await manager.search("my query")

        assert len(results) == 1
        assert results[0]["doc_id"] == "d1"
        assert results[0]["score"] == pytest.approx(0.95)
        assert results[0]["title"] == "Title 1"

    @pytest.mark.asyncio
    async def test_search_embeds_query(self):
        client = _make_client()
        embedder = _make_embedder()
        manager = _make_manager(client=client, embedder=embedder)

        await manager.search("hello world")

        embedder.embed.assert_called_once_with(["hello world"])

    @pytest.mark.asyncio
    async def test_search_excludes_flagged(self):
        from qdrant_client.models import Filter, FieldCondition

        client = _make_client()
        manager = _make_manager(client=client)

        await manager.search("query")

        call_kwargs = client.search.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        assert isinstance(query_filter, Filter)

        field_keys = [c.key for c in query_filter.must if isinstance(c, FieldCondition)]
        assert "is_flagged" in field_keys

        # is_flagged must be False
        flagged_cond = next(c for c in query_filter.must
                            if isinstance(c, FieldCondition) and c.key == "is_flagged")
        assert flagged_cond.match.value is False

    @pytest.mark.asyncio
    async def test_search_applies_source_format_filter(self):
        from qdrant_client.models import FieldCondition

        client = _make_client()
        manager = _make_manager(client=client)

        await manager.search("query", source_format="pdf")

        call_kwargs = client.search.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        field_keys = [c.key for c in query_filter.must if isinstance(c, FieldCondition)]
        assert "source_format" in field_keys

    @pytest.mark.asyncio
    async def test_search_applies_source_index_filter(self):
        from qdrant_client.models import FieldCondition

        client = _make_client()
        manager = _make_manager(client=client)

        await manager.search("query", source_index="archive")

        call_kwargs = client.search.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        field_keys = [c.key for c in query_filter.must if isinstance(c, FieldCondition)]
        assert "source_index" in field_keys

    @pytest.mark.asyncio
    async def test_search_no_optional_filters_when_empty(self):
        from qdrant_client.models import FieldCondition

        client = _make_client()
        manager = _make_manager(client=client)

        await manager.search("query")  # no source_format or source_index

        call_kwargs = client.search.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        field_keys = [c.key for c in query_filter.must if isinstance(c, FieldCondition)]
        # Only is_flagged — no format or index filters
        assert "source_format" not in field_keys
        assert "source_index" not in field_keys

    @pytest.mark.asyncio
    async def test_search_passes_limit(self):
        client = _make_client()
        manager = _make_manager(client=client)

        await manager.search("query", limit=10)

        call_kwargs = client.search.call_args.kwargs
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_search_result_dict_keys(self):
        client = _make_client()
        client.search = AsyncMock(return_value=[
            self._make_hit(0.8, {
                "doc_id": "d2",
                "title": "T2",
                "heading_path": "",
                "chunk_text": "text",
                "source_path": "/f",
                "source_format": "docx",
                "source_index": "docs",
            })
        ])
        manager = _make_manager(client=client)

        results = await manager.search("q")

        expected_keys = {"doc_id", "title", "heading_path", "chunk_text",
                         "source_path", "source_format", "source_index", "score"}
        assert set(results[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    @pytest.mark.asyncio
    async def test_returns_status_dict_when_collection_exists(self):
        client = _make_client()
        manager = _make_manager(client=client, collection="markflow")

        status = await manager.get_status()

        assert status["collection"] == "markflow"
        assert status["exists"] is True
        assert status["vector_count"] == 42
        assert status["model_name"] == "all-MiniLM-L6-v2"

    @pytest.mark.asyncio
    async def test_returns_zero_vectors_when_collection_missing(self):
        from qdrant_client.http.exceptions import UnexpectedResponse

        client = _make_client()
        # Simulate collection not found
        client.get_collection = AsyncMock(
            side_effect=Exception("Collection not found")
        )
        manager = _make_manager(client=client, collection="missing_col")

        status = await manager.get_status()

        assert status["exists"] is False
        assert status["vector_count"] == 0
        assert status["collection"] == "missing_col"

    @pytest.mark.asyncio
    async def test_status_includes_model_name(self):
        embedder = _make_embedder()
        embedder.model_name = "all-mpnet-base-v2"
        manager = _make_manager(embedder=embedder)

        status = await manager.get_status()

        assert status["model_name"] == "all-mpnet-base-v2"
