"""
Qdrant index manager for MarkFlow vector search.

Handles all Qdrant interaction: collection lifecycle, document indexing
(chunk → embed → upsert), semantic search, deletion, and status reporting.

Configuration
-------------
QDRANT_HOST        — hostname/URL of the Qdrant instance (e.g. "localhost" or
                     "http://qdrant:6333").  Leave empty to disable vector search.
QDRANT_COLLECTION  — collection name (default: "markflow").

Usage
-----
    from core.vector.index_manager import get_vector_indexer

    indexer = await get_vector_indexer()
    if indexer:
        count = await indexer.index_document(
            md_path=Path("output/doc.md"),
            doc_id="abc123",
            title="My Document",
            source_path="/mnt/source-share/doc.pdf",
            source_format="pdf",
        )
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

import structlog

from core.vector.chunker import chunk_markdown
from core.vector.embedder import LocalEmbedder, get_embedder

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton cache
# ---------------------------------------------------------------------------

_cached_indexer: Optional["VectorIndexManager"] = None


# ---------------------------------------------------------------------------
# VectorIndexManager
# ---------------------------------------------------------------------------


class VectorIndexManager:
    """
    High-level interface to a Qdrant collection for MarkFlow documents.

    Parameters
    ----------
    client:
        An ``AsyncQdrantClient`` instance (injected for testability).
    embedder:
        A :class:`~core.vector.embedder.LocalEmbedder` instance.
    collection_name:
        Name of the Qdrant collection to operate on.
    """

    def __init__(
        self,
        client,  # qdrant_client.AsyncQdrantClient
        embedder: LocalEmbedder,
        collection_name: str,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._collection_name = collection_name

    # ------------------------------------------------------------------
    # Collection lifecycle
    # ------------------------------------------------------------------

    async def ensure_collection(self) -> None:
        """
        Create the Qdrant collection if it does not already exist.

        Vector size is taken from ``embedder.dimension``; distance metric is
        cosine.  Payload indexes are created for common filter fields.
        """
        from qdrant_client.models import (  # noqa: PLC0415
            Distance,
            VectorParams,
            PayloadSchemaType,
        )

        collections = await self._client.get_collections()
        existing_names = {c.name for c in collections.collections}

        if self._collection_name not in existing_names:
            log.info(
                "qdrant_creating_collection",
                collection=self._collection_name,
                dim=self._embedder.dimension,
            )
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=self._embedder.dimension,
                    distance=Distance.COSINE,
                ),
            )

        # Ensure payload indexes exist (idempotent — Qdrant ignores duplicates)
        keyword_fields = ("doc_id", "source_index", "source_format")
        for field_name in keyword_fields:
            await self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )

        await self._client.create_payload_index(
            collection_name=self._collection_name,
            field_name="is_flagged",
            field_schema=PayloadSchemaType.BOOL,
        )

        log.debug("qdrant_collection_ready", collection=self._collection_name)

    # ------------------------------------------------------------------
    # Document indexing
    # ------------------------------------------------------------------

    async def index_document(
        self,
        md_path: Path,
        doc_id: str,
        title: str,
        source_path: str,
        source_format: str,
        source_index: str = "documents",
        is_flagged: bool = False,
    ) -> int:
        """
        Read *md_path*, chunk it, embed all chunks, and upsert to Qdrant.

        Point IDs are deterministic SHA-256 hashes of ``"{doc_id}:{chunk_index}"``
        (first 16 hex characters, interpreted as a 64-bit unsigned integer).

        Parameters
        ----------
        md_path:
            Path to the markdown file to index.
        doc_id:
            Opaque document identifier (used for filtering / deletion).
        title:
            Human-readable document title.
        source_path:
            Original source file path (stored as payload).
        source_format:
            Format string, e.g. ``"pdf"``, ``"docx"``.
        source_index:
            Logical index/collection the document belongs to.
        is_flagged:
            Whether the document is flagged (flagged docs are excluded from search).

        Returns
        -------
        int
            Number of chunks upserted.
        """
        from qdrant_client.models import PointStruct  # noqa: PLC0415

        markdown = Path(md_path).read_text(encoding="utf-8")
        chunks = chunk_markdown(markdown, doc_title=title, doc_id=doc_id, source_path=source_path)

        if not chunks:
            log.warning("qdrant_no_chunks", doc_id=doc_id, path=str(md_path))
            return 0

        texts = [c.text for c in chunks]
        vectors = self._embedder.embed(texts)

        points = []
        for chunk, vector in zip(chunks, vectors):
            point_id = _deterministic_id(doc_id, chunk.chunk_index)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "doc_id": doc_id,
                        "title": title,
                        "heading_path": chunk.heading_path,
                        "chunk_index": chunk.chunk_index,
                        "chunk_text": chunk.text,
                        "source_path": source_path,
                        "source_format": source_format,
                        "source_index": source_index,
                        "is_flagged": is_flagged,
                    },
                )
            )

        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
        )

        log.info(
            "qdrant_indexed",
            doc_id=doc_id,
            chunks=len(points),
            collection=self._collection_name,
        )
        return len(points)

    # ------------------------------------------------------------------
    # Document deletion
    # ------------------------------------------------------------------

    async def delete_document(self, doc_id: str) -> None:
        """
        Delete all points for *doc_id* from the collection.

        Uses a payload filter so all chunks belonging to the document are
        removed in a single request.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue  # noqa: PLC0415

        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="doc_id",
                        match=MatchValue(value=doc_id),
                    )
                ]
            ),
        )
        log.info("qdrant_deleted", doc_id=doc_id, collection=self._collection_name)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 50,
        source_format: str = "",
        source_index: str = "",
    ) -> list[dict]:
        """
        Semantic search over the collection.

        Flagged documents (``is_flagged=True``) are always excluded.  Optional
        ``source_format`` and ``source_index`` filters narrow results further.

        Parameters
        ----------
        query:
            Natural-language query string.
        limit:
            Maximum number of results to return.
        source_format:
            If non-empty, restrict to documents with this format.
        source_index:
            If non-empty, restrict to documents in this logical index.

        Returns
        -------
        list[dict]
            Each dict contains: ``doc_id``, ``title``, ``heading_path``,
            ``chunk_text``, ``source_path``, ``source_format``,
            ``source_index``, ``score``.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue  # noqa: PLC0415

        query_vector = self._embedder.embed([query])[0]

        # Build filter — always exclude flagged documents
        must_conditions = [
            FieldCondition(key="is_flagged", match=MatchValue(value=False))
        ]
        if source_format:
            must_conditions.append(
                FieldCondition(key="source_format", match=MatchValue(value=source_format))
            )
        if source_index:
            must_conditions.append(
                FieldCondition(key="source_index", match=MatchValue(value=source_index))
            )

        search_filter = Filter(must=must_conditions)

        hits = await self._client.search(
            collection_name=self._collection_name,
            query_vector=query_vector,
            query_filter=search_filter,
            limit=limit,
            with_payload=True,
        )

        results = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                {
                    "doc_id": payload.get("doc_id", ""),
                    "title": payload.get("title", ""),
                    "heading_path": payload.get("heading_path", ""),
                    "chunk_text": payload.get("chunk_text", ""),
                    "source_path": payload.get("source_path", ""),
                    "source_format": payload.get("source_format", ""),
                    "source_index": payload.get("source_index", ""),
                    "score": hit.score,
                }
            )

        return results

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_status(self) -> dict:
        """
        Return a status summary for the collection.

        Returns
        -------
        dict
            Keys: ``collection`` (str), ``exists`` (bool),
            ``vector_count`` (int), ``model_name`` (str).
        """
        from qdrant_client.http.exceptions import UnexpectedResponse  # noqa: PLC0415

        try:
            info = await self._client.get_collection(self._collection_name)
            vector_count = info.vectors_count or 0
            exists = True
        except (UnexpectedResponse, Exception) as exc:
            # Collection does not exist or Qdrant unavailable
            log.debug(
                "qdrant_status_collection_missing",
                collection=self._collection_name,
                error=str(exc),
            )
            vector_count = 0
            exists = False

        return {
            "collection": self._collection_name,
            "exists": exists,
            "vector_count": vector_count,
            "model_name": self._embedder.model_name,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deterministic_id(doc_id: str, chunk_index: int) -> int:
    """
    Return a stable 64-bit unsigned integer ID for a (doc_id, chunk_index) pair.

    Uses the first 8 bytes (16 hex chars) of SHA-256 to minimise collision risk
    while staying within Qdrant's u64 point ID range.
    """
    raw = f"{doc_id}:{chunk_index}".encode()
    hex16 = hashlib.sha256(raw).hexdigest()[:16]
    return int(hex16, 16)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------


async def get_vector_indexer() -> Optional[VectorIndexManager]:
    """
    Return a cached :class:`VectorIndexManager` singleton.

    Reads ``QDRANT_HOST`` and ``QDRANT_COLLECTION`` from the environment.
    Returns ``None`` if ``QDRANT_HOST`` is empty or the connection fails.
    Calls :meth:`~VectorIndexManager.ensure_collection` on first initialisation.
    """
    global _cached_indexer

    if _cached_indexer is not None:
        return _cached_indexer

    host = os.environ.get("QDRANT_HOST", "").strip()
    if not host:
        log.debug("qdrant_disabled", reason="QDRANT_HOST not set")
        return None

    collection = os.environ.get("QDRANT_COLLECTION", "markflow").strip()

    try:
        from qdrant_client import AsyncQdrantClient  # noqa: PLC0415

        # Support bare hostname ("localhost") or full URL
        if host.startswith("http://") or host.startswith("https://"):
            client = AsyncQdrantClient(url=host)
        else:
            client = AsyncQdrantClient(host=host)

        embedder = get_embedder()
        manager = VectorIndexManager(
            client=client,
            embedder=embedder,
            collection_name=collection,
        )
        await manager.ensure_collection()
        _cached_indexer = manager
        log.info("qdrant_indexer_ready", host=host, collection=collection)
        return _cached_indexer

    except Exception as exc:
        log.warning("qdrant_indexer_unavailable", host=host, error=str(exc))
        return None
