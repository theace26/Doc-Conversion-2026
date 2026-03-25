"""
Full-text search API powered by Meilisearch.

GET  /api/search              — Search documents or Adobe index
GET  /api/search/autocomplete — Lightweight suggestions for search box
GET  /api/search/index/status — Index health and stats
POST /api/search/index/rebuild — Trigger full index rebuild
"""

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthenticatedUser, UserRole, require_role
from core.search_client import get_meili_client
from core.search_indexer import get_search_indexer

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


# ── GET /api/search ──────────────────────────────────────────────────────────

@router.get("")
async def search(
    q: str = Query(..., min_length=2),
    index: str = Query("documents", pattern="^(documents|adobe-files)$"),
    format: str | None = None,
    path_prefix: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=5, le=25),
    highlight: bool = True,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Full-text search across documents or Adobe index."""
    client = get_meili_client()

    if not await client.health_check():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "search_unavailable",
                "message": "Search index is not available. Check /debug for status.",
            },
        )

    options: dict = {
        "limit": per_page,
        "offset": (page - 1) * per_page,
    }

    if highlight:
        options["attributesToHighlight"] = ["content", "title", "text_content"]
        options["highlightPreTag"] = "<em>"
        options["highlightPostTag"] = "</em>"

    # Build filters
    filters = []
    if format and index == "documents":
        filters.append(f'source_format = "{format}"')
    if path_prefix and index == "documents":
        filters.append(f'relative_path_prefix = "{path_prefix}"')
    if filters:
        options["filter"] = " AND ".join(filters)

    result = await client.search(index, q, options)

    # Map hits
    hits = []
    for hit in result.get("hits", []):
        entry = {k: v for k, v in hit.items() if not k.startswith("_")}
        if highlight and "_formatted" in hit:
            # Extract highlight snippet from formatted content
            formatted = hit["_formatted"]
            entry["highlight"] = (
                formatted.get("content", "")[:300]
                or formatted.get("text_content", "")[:300]
            )
        hits.append(entry)

    return {
        "query": q,
        "index": index,
        "total_hits": result.get("estimatedTotalHits", 0),
        "page": page,
        "per_page": per_page,
        "processing_time_ms": result.get("processingTimeMs", 0),
        "hits": hits,
    }


# ── GET /api/search/autocomplete ─────────────────────────────────────────────

@router.get("/autocomplete")
async def autocomplete(
    q: str = Query("", min_length=0),
    limit: int = Query(5, ge=1, le=8),
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Lightweight suggestions for search box autocomplete."""
    if len(q.strip()) < 2:
        return {"suggestions": []}

    client = get_meili_client()

    options = {
        "limit": limit,
        "attributesToRetrieve": ["title", "format", "source_format", "id", "file_ext"],
    }

    seen_titles: set[str] = set()
    suggestions: list[dict] = []

    for index_uid in ("documents", "adobe-files"):
        try:
            result = await client.search(index_uid, q.strip(), options)
            for hit in result.get("hits", []):
                title = hit.get("title") or hit.get("source_filename") or ""
                if not title:
                    continue
                title_lower = title.lower()
                if title_lower in seen_titles:
                    continue
                seen_titles.add(title_lower)
                fmt = hit.get("source_format") or hit.get("format") or hit.get("file_ext") or ""
                suggestions.append({
                    "title": title,
                    "format": fmt.lstrip("."),
                    "id": hit.get("id", ""),
                })
        except Exception:
            # Meilisearch down or error — silently return what we have
            pass

    return {"suggestions": suggestions[:limit]}


# ── GET /api/search/index/status ─────────────────────────────────────────────

@router.get("/index/status")
async def index_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Index health and document counts."""
    client = get_meili_client()
    available = await client.health_check()

    docs_stats = {}
    adobe_stats = {}
    if available:
        docs_stats = await client.get_index_stats("documents")
        adobe_stats = await client.get_index_stats("adobe-files")

    return {
        "available": available,
        "documents": {
            "index": "documents",
            "document_count": docs_stats.get("numberOfDocuments", 0),
            "is_indexing": docs_stats.get("isIndexing", False),
        },
        "adobe_files": {
            "index": "adobe-files",
            "document_count": adobe_stats.get("numberOfDocuments", 0),
            "is_indexing": adobe_stats.get("isIndexing", False),
        },
    }


# ── POST /api/search/index/rebuild ───────────────────────────────────────────

@router.post("/index/rebuild")
async def rebuild_index(
    body: dict | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Trigger a full index rebuild."""
    client = get_meili_client()
    if not await client.health_check():
        raise HTTPException(
            status_code=503,
            detail="Meilisearch is not available for rebuild.",
        )

    job_id = (body or {}).get("job_id")
    indexer = get_search_indexer()
    if not indexer:
        raise HTTPException(status_code=503, detail="Search indexer not initialized.")

    # Run rebuild in background
    async def _rebuild():
        result = await indexer.rebuild_index(job_id=job_id)
        log.info(
            "search_rebuild_complete",
            documents=result.documents_indexed,
            adobe=result.adobe_indexed,
            errors=result.errors,
        )

    asyncio.create_task(_rebuild())
    return {"status": "rebuild_started", "job_id": job_id}
