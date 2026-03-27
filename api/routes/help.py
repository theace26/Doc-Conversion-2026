"""
Help wiki API — serves rendered markdown articles.

GET /api/help/index           — Structured article index with categories
GET /api/help/article/{slug}  — Rendered HTML for a single article
GET /api/help/search?q=       — Keyword search across all articles

All endpoints are public (no auth required).
"""

import json
from pathlib import Path
from typing import Optional

import mistune
import structlog
from fastapi import APIRouter, HTTPException

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/help", tags=["help"])

_HELP_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "help"
_INDEX_PATH = _HELP_DIR / "_index.json"

_article_cache: dict[str, dict] = {}
_index_cache: Optional[dict] = None

_markdown = mistune.create_markdown(plugins=["table", "strikethrough", "footnotes"])


def _load_index() -> dict:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    try:
        _index_cache = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        return _index_cache
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("help.index_load_failed", error=str(e))
        return {"categories": []}


def _render_article(slug: str) -> Optional[dict]:
    if slug in _article_cache:
        return _article_cache[slug]

    md_path = _HELP_DIR / f"{slug}.md"
    if not md_path.exists():
        return None

    resolved = md_path.resolve()
    if not str(resolved).startswith(str(_HELP_DIR.resolve())):
        log.warning("help.path_traversal_attempt", slug=slug)
        return None

    raw = md_path.read_text(encoding="utf-8")

    lines = raw.strip().splitlines()
    title = slug.replace("-", " ").title()
    if lines and lines[0].startswith("# "):
        title = lines[0].lstrip("# ").strip()

    html = _markdown(raw)

    result = {"slug": slug, "title": title, "html": html, "raw_length": len(raw)}
    _article_cache[slug] = result
    return result


@router.get("/index")
async def get_help_index():
    return _load_index()


@router.get("/article/{slug}")
async def get_help_article(slug: str):
    if not all(c.isalnum() or c == "-" for c in slug):
        raise HTTPException(status_code=400, detail="Invalid article slug")
    article = _render_article(slug)
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article '{slug}' not found")
    return article


@router.get("/search")
async def search_help(q: str = ""):
    if not q or len(q) < 2:
        return {"results": []}

    q_lower = q.lower()
    results = []
    index = _load_index()

    for category in index.get("categories", []):
        for article_meta in category.get("articles", []):
            slug = article_meta["slug"]
            md_path = _HELP_DIR / f"{slug}.md"
            if not md_path.exists():
                continue
            raw = md_path.read_text(encoding="utf-8").lower()
            if q_lower in raw:
                snippet = ""
                for line in raw.splitlines():
                    if q_lower in line and not line.startswith("#"):
                        snippet = line.strip().lstrip("-*> ")[:200]
                        break
                results.append({
                    "slug": slug,
                    "title": article_meta["title"],
                    "description": article_meta.get("description", ""),
                    "category": category["name"],
                    "snippet": snippet,
                })

    return {"query": q, "results": results}
