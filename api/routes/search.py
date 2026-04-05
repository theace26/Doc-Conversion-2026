"""
Full-text search API powered by Meilisearch.

GET  /api/search              — Search documents or Adobe index
GET  /api/search/all          — Unified search across all indexes with facets
GET  /api/search/autocomplete — Lightweight suggestions for search box
GET  /api/search/index/status — Index health and stats
POST /api/search/index/rebuild — Trigger full index rebuild
GET  /api/search/view/{index}/{doc_id}   — Serve converted markdown for a search hit
GET  /api/search/source/{index}/{doc_id} — Serve original source file for browser viewing
GET  /api/search/download/{index}/{doc_id} — Download original source file
GET  /api/search/doc-info/{index}/{doc_id} — File metadata for viewer page
POST /api/search/batch-download — Download multiple source files as ZIP
"""

import asyncio
import io
import mimetypes
import zipfile
from pathlib import Path

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from core.auth import AuthenticatedUser, UserRole, require_role, role_satisfies
from core.database import db_fetch_one
from core.search_client import get_meili_client
from core.search_indexer import get_search_indexer

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])

# MIME types that browsers can display inline
_INLINE_MIMES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "image/tiff", "image/bmp",
    "text/plain", "text/html", "text/csv",
}


async def _resolve_source_path(output_path: str, source_filename: str) -> Path | None:
    """Look up the original source file path from the source_files DB table."""
    if not output_path:
        return None

    # Try DB lookup by output_path
    row = await db_fetch_one(
        "SELECT source_path FROM source_files WHERE output_path = ?",
        (output_path,),
    )
    if row and row["source_path"]:
        p = Path(row["source_path"])
        if p.exists():
            return p

    # Fallback: try matching by filename pattern in the output path
    # output: /mnt/output-repo/<rel_dirs>/<job_id>/filename.md
    # source: /mnt/source/<rel_dirs>/filename.<ext>
    if source_filename:
        row = await db_fetch_one(
            "SELECT source_path FROM source_files WHERE source_path LIKE ?",
            (f"%/{source_filename}",),
        )
        if row and row["source_path"]:
            p = Path(row["source_path"])
            if p.exists():
                return p

    return None


async def _get_meili_doc(index: str, doc_id: str) -> dict:
    """Fetch a single document from Meilisearch by index and ID."""
    client = get_meili_client()
    resp = await client._request("GET", f"/indexes/{index}/documents/{doc_id}")
    if resp is None or resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Document not found in search index.")
    return resp.json()


# ── GET /api/search ──────────────────────────────────────────────────────────

@router.get("")
async def search(
    q: str = Query(..., min_length=2),
    index: str = Query("documents", pattern="^(documents|adobe-files|transcripts)$"),
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
        highlight_attrs = ["content", "title", "text_content"]
        if index == "transcripts":
            highlight_attrs = ["raw_text", "title"]
        options["attributesToHighlight"] = highlight_attrs
        options["highlightPreTag"] = "<em>"
        options["highlightPostTag"] = "</em>"

    # Build filters
    filters = []
    if format and index == "documents":
        filters.append(f'source_format = "{format}"')
    if path_prefix and index == "documents":
        filters.append(f'relative_path_prefix = "{path_prefix}"')
    # Hide flagged files from non-admin users
    if not role_satisfies(user.role, UserRole.ADMIN):
        filters.append("is_flagged != true")
    if filters:
        options["filter"] = " AND ".join(filters)

    result = await client.search(index, q, options)

    # Map hits
    hits = []
    for hit in result.get("hits", []):
        entry = {k: v for k, v in hit.items() if not k.startswith("_")}
        if highlight and "_formatted" in hit:
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


# ── GET /api/search/all ──────────────────────────────────────────────────────

@router.get("/all")
async def search_all(
    q: str = Query("", min_length=0),
    format: str | None = None,
    sort: str = Query("relevance", pattern="^(relevance|date|size|format)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=5, le=100),
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Unified search across all indexes with faceted format counts."""
    client = get_meili_client()

    if not await client.health_check():
        raise HTTPException(
            status_code=503,
            detail={"error": "search_unavailable", "message": "Search index is not available."},
        )

    # Build base options — only retrieve fields the frontend needs
    _RETRIEVE_FIELDS = [
        "id", "title", "source_filename", "source_format", "source_path",
        "output_path", "relative_path", "content_preview", "fidelity_tier",
        "has_ocr", "converted_at", "file_size_bytes", "job_id", "scene_count",
        "enrichment_level", "vision_provider", "is_flagged",
        # adobe/transcript extras
        "file_ext", "indexed_at", "created_at", "text_preview",
    ]
    options: dict = {
        "limit": per_page,
        "offset": (page - 1) * per_page,
        "facets": ["source_format"],
        "attributesToRetrieve": _RETRIEVE_FIELDS,
    }

    # Only highlight when there's an actual query
    if q.strip():
        options["attributesToHighlight"] = ["content", "title", "text_content", "raw_text"]
        options["highlightPreTag"] = "<em>"
        options["highlightPostTag"] = "</em>"

    # Sort mapping — default to date for empty queries (browse mode)
    effective_sort = sort if q.strip() else "date"
    if effective_sort == "date":
        options["sort"] = ["converted_at:desc"]
    elif effective_sort == "size":
        options["sort"] = ["file_size_bytes:desc"]
    elif sort == "format":
        options["sort"] = ["converted_at:desc"]

    # Build document filter
    doc_filters = []
    if format:
        doc_filters.append(f'source_format = "{format}"')
    if not role_satisfies(user.role, UserRole.ADMIN):
        doc_filters.append("is_flagged != true")
    if doc_filters:
        options["filter"] = " AND ".join(doc_filters)

    # Fan out to all 3 indexes concurrently
    docs_task = client.search("documents", q, options)

    other_options: dict = {
        "limit": per_page,
        "offset": (page - 1) * per_page,
        "attributesToHighlight": ["title", "text_content", "raw_text"],
        "highlightPreTag": "<em>",
        "highlightPostTag": "</em>",
    }

    # Build other-index filters
    other_filters = []
    if not role_satisfies(user.role, UserRole.ADMIN):
        other_filters.append("is_flagged != true")

    if format:
        adobe_filter_parts = [f'file_ext = ".{format}"'] + other_filters
        other_options_adobe = {**other_options, "filter": " AND ".join(adobe_filter_parts)}
    elif other_filters:
        other_options_adobe = {**other_options, "filter": " AND ".join(other_filters)}
    else:
        other_options_adobe = other_options

    if other_filters:
        other_options_transcripts = {**other_options, "filter": " AND ".join(other_filters)}
    else:
        other_options_transcripts = other_options

    adobe_task = client.search("adobe-files", q, other_options_adobe)
    transcript_task = client.search("transcripts", q, other_options_transcripts)

    docs_result, adobe_result, transcript_result = await asyncio.gather(
        docs_task, adobe_task, transcript_task
    )

    # Merge hits with source-index tag
    all_hits = []
    for hit in docs_result.get("hits", []):
        all_hits.append(_map_hit(hit, "documents"))
    for hit in adobe_result.get("hits", []):
        all_hits.append(_map_hit(hit, "adobe-files"))
    for hit in transcript_result.get("hits", []):
        all_hits.append(_map_hit(hit, "transcripts"))

    # ── Hybrid search: blend with vector results if available ───────────
    try:
        from core.vector.index_manager import get_vector_indexer
        from core.vector.hybrid_search import hybrid_search as _hybrid_search
        from core.vector.query_preprocessor import preprocess_query

        vec_indexer = await get_vector_indexer()
        if vec_indexer and q:
            intent = preprocess_query(q)
            all_hits = await _hybrid_search(
                query=intent.normalized_query,
                keyword_results=all_hits,
                vector_manager=vec_indexer,
                filters={"source_format": format} if format else None,
                limit=per_page,
            )
            # If temporal intent detected, prefer date sort
            if intent.has_temporal_intent and sort == "relevance":
                sort = "date"
    except Exception as exc:
        log.warning("hybrid_search.skip", error=str(exc))

    facets = docs_result.get("facetDistribution", {}).get("source_format", {})

    total = (
        docs_result.get("estimatedTotalHits", 0)
        + adobe_result.get("estimatedTotalHits", 0)
        + transcript_result.get("estimatedTotalHits", 0)
    )

    return {
        "query": q,
        "total_hits": total,
        "page": page,
        "per_page": per_page,
        "processing_time_ms": max(
            docs_result.get("processingTimeMs", 0),
            adobe_result.get("processingTimeMs", 0),
            transcript_result.get("processingTimeMs", 0),
        ),
        "hits": all_hits[:per_page],
        "facets": facets,
    }


def _map_hit(hit: dict, source_index: str) -> dict:
    """Normalize a hit from any index into a unified result format."""
    formatted = hit.get("_formatted", {})

    entry: dict = {
        "id": hit.get("id", ""),
        "source_index": source_index,
        "source_filename": hit.get("source_filename", ""),
        "source_path": hit.get("source_path", ""),
        "output_path": hit.get("output_path", ""),
        "relative_path": hit.get("relative_path", ""),
        "content_preview": (hit.get("content_preview") or "")[:500],
        "fidelity_tier": hit.get("fidelity_tier"),
        "has_ocr": hit.get("has_ocr", False),
        "file_size_bytes": hit.get("file_size_bytes"),
        "job_id": hit.get("job_id", ""),
        "scene_count": hit.get("scene_count", 0),
        "enrichment_level": hit.get("enrichment_level"),
        "vision_provider": hit.get("vision_provider"),
        "is_flagged": hit.get("is_flagged", False),
    }

    entry["title"] = hit.get("title") or hit.get("source_filename") or ""

    entry["highlight"] = (
        formatted.get("content", "")[:300]
        or formatted.get("text_content", "")[:300]
        or formatted.get("raw_text", "")[:300]
        or hit.get("content_preview", "")[:300]
        or hit.get("text_preview", "")[:300]
        or ""
    )

    entry["format"] = (
        hit.get("source_format")
        or (hit.get("file_ext") or "").lstrip(".")
        or ""
    )

    entry["path"] = hit.get("relative_path") or hit.get("source_path") or ""

    entry["date"] = (
        hit.get("converted_at")
        or hit.get("indexed_at")
        or hit.get("created_at")
        or ""
    )

    return entry


# ── GET /api/search/doc-info/{index}/{doc_id} ────────────────────────────────

@router.get("/doc-info/{index}/{doc_id}")
async def doc_info(
    index: str,
    doc_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Return file metadata for the document viewer page."""
    doc = await _get_meili_doc(index, doc_id)
    output_path = doc.get("output_path", "")
    source_filename = doc.get("source_filename", "")
    source_format = doc.get("source_format") or (doc.get("file_ext") or "").lstrip(".")

    source_path = await _resolve_source_path(output_path, source_filename)
    has_source = source_path is not None and source_path.exists()

    # Determine if source can be viewed inline in browser
    can_inline = False
    source_size = 0
    if has_source:
        mime, _ = mimetypes.guess_type(str(source_path))
        can_inline = mime in _INLINE_MIMES if mime else False
        source_size = source_path.stat().st_size

    has_markdown = False
    if output_path:
        has_markdown = Path(output_path).exists()

    return {
        "id": doc_id,
        "index": index,
        "title": doc.get("title") or source_filename or "",
        "source_filename": source_filename,
        "source_format": source_format,
        "has_source": has_source,
        "can_inline": can_inline,
        "source_size": source_size,
        "has_markdown": has_markdown,
        "date": doc.get("converted_at") or doc.get("indexed_at") or "",
        "file_size_bytes": doc.get("file_size_bytes", 0),
        "fidelity_tier": doc.get("fidelity_tier"),
        "has_ocr": doc.get("has_ocr", False),
    }


# ── GET /api/search/source/{index}/{doc_id} ──────────────────────────────────

@router.get("/source/{index}/{doc_id}")
async def serve_source(
    index: str,
    doc_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Serve the original source file for inline browser viewing."""
    doc = await _get_meili_doc(index, doc_id)
    source_filename = doc.get("source_filename", "")
    output_path = doc.get("output_path", "")

    source_path = await _resolve_source_path(output_path, source_filename)
    if source_path is None or not source_path.exists():
        raise HTTPException(status_code=404, detail="Original source file not found.")

    # Block flagged files for non-admin users
    from core.flag_manager import is_file_flagged_by_path
    if await is_file_flagged_by_path(str(source_path)):
        if not role_satisfies(user.role, UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="This file has been flagged for review.")

    mime, _ = mimetypes.guess_type(str(source_path))
    if not mime:
        mime = "application/octet-stream"

    # Serve inline for browser-viewable types
    if mime in _INLINE_MIMES:
        return FileResponse(
            path=str(source_path),
            filename=source_path.name,
            media_type=mime,
            headers={"Content-Disposition": f'inline; filename="{source_path.name}"'},
        )

    # For non-inline types, still serve the file (viewer page will handle display)
    return FileResponse(
        path=str(source_path),
        filename=source_path.name,
        media_type=mime,
    )


# ── GET /api/search/download/{index}/{doc_id} ────────────────────────────────

@router.get("/download/{index}/{doc_id}")
async def download_source(
    index: str,
    doc_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Download the original source file as an attachment."""
    doc = await _get_meili_doc(index, doc_id)
    source_filename = doc.get("source_filename", "")
    output_path = doc.get("output_path", "")

    source_path = await _resolve_source_path(output_path, source_filename)
    if source_path is None or not source_path.exists():
        raise HTTPException(status_code=404, detail="Original source file not found.")

    # Block flagged files for non-admin users
    from core.flag_manager import is_file_flagged_by_path
    if await is_file_flagged_by_path(str(source_path)):
        if not role_satisfies(user.role, UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="This file has been flagged for review.")

    mime, _ = mimetypes.guess_type(str(source_path))
    return FileResponse(
        path=str(source_path),
        filename=source_path.name,
        media_type=mime or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{source_path.name}"',
            "Content-Length": str(source_path.stat().st_size),
        },
    )


# ── GET /api/search/view/{index}/{doc_id} ────────────────────────────────────

@router.get("/view/{index}/{doc_id}")
async def view_markdown(
    index: str,
    doc_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Serve the converted markdown output file."""
    doc = await _get_meili_doc(index, doc_id)
    output_path = doc.get("output_path", "")

    if not output_path:
        raise HTTPException(status_code=404, detail="No output file path for this document.")

    path = Path(output_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="Output file no longer exists on disk.")

    if path.suffix.lower() == ".md":
        content = path.read_text(encoding="utf-8", errors="replace")
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")

    return FileResponse(path=str(path), filename=path.name, media_type="application/octet-stream")


# ── POST /api/search/batch-download ──────────────────────────────────────────

@router.post("/batch-download")
async def batch_download(
    items: list[dict] = Body(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Download multiple source files as a ZIP archive.

    Body: [{"index": "documents", "doc_id": "abc123"}, ...]
    """
    if not items or len(items) > 500:
        raise HTTPException(status_code=400, detail="Provide 1-500 items.")

    client = get_meili_client()
    buf = io.BytesIO()
    added_names: dict[str, int] = {}  # track duplicates
    skipped_flagged = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            idx = item.get("index", "documents")
            doc_id = item.get("doc_id", "")
            if not doc_id:
                continue

            try:
                resp = await client._request("GET", f"/indexes/{idx}/documents/{doc_id}")
                if resp is None or resp.status_code != 200:
                    continue
                doc = resp.json()
                source_path = await _resolve_source_path(
                    doc.get("output_path", ""),
                    doc.get("source_filename", ""),
                )
                if source_path is None or not source_path.exists():
                    continue

                # Skip flagged files
                from core.flag_manager import is_file_flagged_by_path
                if await is_file_flagged_by_path(str(source_path)):
                    skipped_flagged += 1
                    continue

                # Handle duplicate filenames
                name = source_path.name
                if name in added_names:
                    added_names[name] += 1
                    stem = source_path.stem
                    suffix = source_path.suffix
                    name = f"{stem} ({added_names[name]}){suffix}"
                else:
                    added_names[name] = 0

                zf.write(str(source_path), name)
            except Exception as exc:
                log.warning("batch_download_skip", doc_id=doc_id, error=str(exc))
                continue

    buf.seek(0)
    size = buf.getbuffer().nbytes

    if size <= 22:  # empty ZIP
        raise HTTPException(status_code=404, detail="No files could be found for download.")

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="markflow-search-results.zip"',
            "Content-Length": str(size),
            "X-Skipped-Flagged": str(skipped_flagged),
        },
    )


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

    for index_uid in ("documents", "adobe-files", "transcripts"):
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
    transcripts_stats = {}
    if available:
        docs_stats = await client.get_index_stats("documents")
        adobe_stats = await client.get_index_stats("adobe-files")
        transcripts_stats = await client.get_index_stats("transcripts")

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
        "transcripts": {
            "index": "transcripts",
            "document_count": transcripts_stats.get("numberOfDocuments", 0),
            "is_indexing": transcripts_stats.get("isIndexing", False),
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
