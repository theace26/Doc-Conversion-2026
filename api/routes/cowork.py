"""
Cowork integration API — search endpoint optimized for AI assistant consumption.

GET /api/cowork/search  — Returns full .md content inline with token-budget awareness
GET /api/cowork/status  — Health check for Cowork polling
"""

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthenticatedUser, UserRole, require_role
from core.search_client import get_meili_client
from core.search_indexer import get_search_indexer

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/cowork", tags=["cowork"])


def _truncate_at_paragraph(content: str, max_chars: int) -> tuple[str, bool]:
    """Truncate content at nearest paragraph boundary before max_chars."""
    if len(content) <= max_chars:
        return content, False

    # Find last double newline before max_chars
    truncated = content[:max_chars]
    last_para = truncated.rfind("\n\n")
    if last_para > max_chars // 2:
        return truncated[:last_para].rstrip(), True

    # Fall back to last single newline
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        return truncated[:last_nl].rstrip(), True

    return truncated.rstrip(), True


# ── GET /api/cowork/search ───────────────────────────────────────────────────

@router.get("/search")
async def cowork_search(
    q: str = Query(..., min_length=2),
    max_results: int = Query(10, ge=1, le=20),
    max_tokens_per_doc: int = Query(5000, ge=1000, le=10000),
    format: str | None = None,
    path_prefix: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Search with full .md content inline for AI assistant consumption."""
    client = get_meili_client()

    if not await client.health_check():
        raise HTTPException(
            status_code=503,
            detail="Search index is not available.",
        )

    # Fetch extra results in case some .md files are unreadable
    options: dict = {"limit": max_results * 2}
    filters = []
    if format:
        filters.append(f'source_format = "{format}"')
    if path_prefix:
        filters.append(f'relative_path_prefix = "{path_prefix}"')
    if filters:
        options["filter"] = " AND ".join(filters)

    result = await client.search("documents", q, options)

    max_chars = max_tokens_per_doc * 4  # rough 4-chars-per-token heuristic
    results = []
    token_budget_used = 0

    for hit in result.get("hits", []):
        if len(results) >= max_results:
            break

        output_path = hit.get("output_path", "")
        if not output_path:
            continue

        md_path = Path(output_path)
        if not md_path.exists():
            log.warning("cowork_missing_md", path=output_path)
            continue

        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("cowork_read_fail", path=output_path, error=str(exc))
            continue

        # Strip frontmatter for clean content
        import re
        content = re.sub(r"^---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)
        content = content.strip()

        content, was_truncated = _truncate_at_paragraph(content, max_chars)
        token_estimate = len(content) // 4

        results.append({
            "rank": len(results) + 1,
            "title": hit.get("title", md_path.stem),
            "source_filename": hit.get("source_filename", ""),
            "source_format": hit.get("source_format", ""),
            "relative_path": hit.get("relative_path", ""),
            "source_path": hit.get("source_path", ""),
            "converted_at": hit.get("converted_at", ""),
            "content": content,
            "content_truncated": was_truncated,
        })
        token_budget_used += token_estimate

    return {
        "query": q,
        "result_count": len(results),
        "total_hits": result.get("estimatedTotalHits", 0),
        "token_budget_used": token_budget_used,
        "results": results,
    }


# ── GET /api/cowork/status ───────────────────────────────────────────────────

@router.get("/status")
async def cowork_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Health check for Cowork to poll."""
    client = get_meili_client()
    available = await client.health_check()

    doc_count = 0
    if available:
        stats = await client.get_index_stats("documents")
        doc_count = stats.get("numberOfDocuments", 0)

    return {
        "available": available,
        "document_count": doc_count,
        "meilisearch_available": available,
    }
