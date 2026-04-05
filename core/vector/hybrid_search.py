"""Hybrid search via Reciprocal Rank Fusion (RRF) for MarkFlow.

Merges keyword results from Meilisearch with vector results from Qdrant using
the standard RRF formula (Cormack et al., 2009):

    score(d) = Σ  1 / (k + rank(d, list) + 1)

where rank is 0-based and the sum is taken over every ranked list that contains
the document.

Public API
----------
rrf_merge(keyword_hits, vector_hits, k, limit) -> list[dict]
    Pure function — no async, no side effects.  Easy to unit-test.

hybrid_search(query, keyword_results, vector_manager, filters, limit) -> list[dict]
    Async entry point: runs vector_manager.search() then calls rrf_merge.
    Falls back gracefully to keyword_results if vector search is unavailable.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

# Standard constant from Cormack et al. (2009).  60 works well in practice.
RRF_K = 60


# ---------------------------------------------------------------------------
# Helper: deduplicate vector hits to one-per-document
# ---------------------------------------------------------------------------


def deduplicate_chunks(vector_hits: list[dict]) -> list[dict]:
    """Collapse multiple chunks from the same document to the best-scoring one.

    Vector search returns chunk-level hits where each hit carries a ``doc_id``
    and a ``score``.  When more than one chunk from the same document appears,
    we keep only the chunk with the highest score so that a single document
    does not dominate the ranked list simply by having many chunks.

    Parameters
    ----------
    vector_hits:
        List of dicts, each containing at minimum ``doc_id`` and ``score``.

    Returns
    -------
    list[dict]
        Deduplicated list, retaining original order among kept items and
        preserving the relative ordering of first-seen documents.
    """
    seen: dict[str, dict] = {}
    for hit in vector_hits:
        doc_id = hit.get("doc_id")
        if doc_id is None:
            # Hits without a doc_id are kept as-is (defensive).
            continue
        existing = seen.get(doc_id)
        if existing is None or hit.get("score", 0.0) > existing.get("score", 0.0):
            seen[doc_id] = hit

    # Preserve the order of first occurrence so callers can reason about rank.
    order: list[str] = []
    for hit in vector_hits:
        doc_id = hit.get("doc_id")
        if doc_id is not None and doc_id not in order:
            order.append(doc_id)

    return [seen[doc_id] for doc_id in order if doc_id in seen]


# ---------------------------------------------------------------------------
# Core merge function
# ---------------------------------------------------------------------------


def rrf_merge(
    keyword_hits: list[dict],
    vector_hits: list[dict],
    k: int = RRF_K,
    limit: int = 0,
) -> list[dict]:
    """Merge keyword and vector ranked lists using Reciprocal Rank Fusion.

    Parameters
    ----------
    keyword_hits:
        Ordered list of dicts from Meilisearch.  Each dict must have an ``id``
        field that uniquely identifies the document.

    vector_hits:
        Ordered list of dicts from Qdrant (after chunk deduplication).  Each
        dict must have a ``doc_id`` field.

    k:
        RRF constant (default 60).  Higher values reduce the influence of
        high-ranked documents relative to lower-ranked ones.

    limit:
        Maximum number of results to return.  ``0`` (default) means no limit.

    Returns
    -------
    list[dict]
        Merged list of document dicts sorted by RRF score descending.
        Tiebreaker: documents that appear in the keyword list rank higher than
        vector-only documents.

        For documents that appear *only* in the vector results a minimal
        metadata dict is built containing: ``id``, ``title``,
        ``source_index``, ``source_path``, ``source_format``, and a
        ``_vector_only`` flag.
    """
    # Build a lookup from doc_id → keyword rank (0-based)
    keyword_rank: dict[str, int] = {
        str(hit["id"]): rank for rank, hit in enumerate(keyword_hits)
    }

    # Build a lookup from doc_id → vector rank (0-based)
    deduped_vector = deduplicate_chunks(vector_hits)
    vector_rank: dict[str, int] = {
        str(hit["doc_id"]): rank for rank, hit in enumerate(deduped_vector)
    }

    # Union of all doc_ids
    all_ids: set[str] = set(keyword_rank) | set(vector_rank)

    scores: dict[str, float] = {}
    for doc_id in all_ids:
        score = 0.0
        if doc_id in keyword_rank:
            score += 1.0 / (k + keyword_rank[doc_id] + 1)
        if doc_id in vector_rank:
            score += 1.0 / (k + vector_rank[doc_id] + 1)
        scores[doc_id] = score

    # Build a rich metadata dict for every doc_id.
    # keyword_hits are the primary source; vector-only hits get minimal metadata.
    keyword_meta: dict[str, dict] = {str(hit["id"]): hit for hit in keyword_hits}
    vector_meta: dict[str, dict] = {str(hit["doc_id"]): hit for hit in deduped_vector}

    results: list[dict] = []
    for doc_id in all_ids:
        if doc_id in keyword_meta:
            doc = dict(keyword_meta[doc_id])
        else:
            # Vector-only hit — build minimal metadata
            v = vector_meta[doc_id]
            doc = {
                "id": doc_id,
                "title": v.get("title", ""),
                "source_index": v.get("source_index", ""),
                "source_path": v.get("source_path", ""),
                "source_format": v.get("source_format", ""),
                "_vector_only": True,
            }
        doc["_rrf_score"] = scores[doc_id]
        results.append(doc)

    # Sort: primary key = RRF score (descending), tiebreaker = keyword rank.
    # Docs in keyword list get tiebreaker priority (in_keyword=False sorts last).
    results.sort(
        key=lambda d: (
            -d["_rrf_score"],
            0 if str(d["id"]) in keyword_rank else 1,
            keyword_rank.get(str(d["id"]), len(keyword_hits)),
        )
    )

    if limit and limit > 0:
        results = results[:limit]

    return results


# ---------------------------------------------------------------------------
# Async entry point
# ---------------------------------------------------------------------------


async def hybrid_search(
    query: str,
    keyword_results: list[dict],
    vector_manager,
    filters: dict | None = None,
    limit: int = 20,
) -> list[dict]:
    """Run vector search and merge with keyword results via RRF.

    Parameters
    ----------
    query:
        The user's search query string (used for vector embedding).

    keyword_results:
        Pre-fetched Meilisearch results (list of dicts with ``id``).

    vector_manager:
        An object with an async ``search(query, filters, limit)`` method that
        returns a list of dicts with ``doc_id`` (and optionally ``score`` plus
        other metadata).  If ``None``, keyword results are returned unchanged.

    filters:
        Optional filter dict forwarded to ``vector_manager.search()``.

    limit:
        Maximum number of results to return after merging.

    Returns
    -------
    list[dict]
        Merged and ranked results, or ``keyword_results`` unchanged if vector
        search is unavailable or fails.
    """
    if vector_manager is None:
        log.debug("hybrid_search_no_vector_manager", query=query)
        return keyword_results

    try:
        search_kwargs: dict = {"query": query, "limit": limit}
        if filters:
            if "source_format" in filters:
                search_kwargs["source_format"] = filters["source_format"]
            if "source_index" in filters:
                search_kwargs["source_index"] = filters["source_index"]
        vector_hits: list[dict] = await vector_manager.search(**search_kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "hybrid_search_vector_failed",
            query=query,
            error=str(exc),
            exc_info=True,
        )
        return keyword_results

    merged = rrf_merge(keyword_results, vector_hits, limit=limit)

    log.info(
        "hybrid_search_merged",
        query=query,
        keyword_count=len(keyword_results),
        vector_count=len(vector_hits),
        merged_count=len(merged),
    )

    return merged
