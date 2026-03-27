"""Tests for the help wiki API — article rendering, index, search, security."""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from main import app

_HELP_DIR = Path(__file__).resolve().parent.parent / "docs" / "help"
_INDEX_PATH = _HELP_DIR / "_index.json"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_help_index_returns_categories(client):
    r = await client.get("/api/help/index")
    assert r.status_code == 200
    data = r.json()
    assert "categories" in data
    assert len(data["categories"]) > 0
    assert "articles" in data["categories"][0]


@pytest.mark.asyncio
async def test_help_article_renders_html(client):
    r = await client.get("/api/help/article/getting-started")
    assert r.status_code == 200
    data = r.json()
    assert "html" in data
    assert "<h1>" in data["html"] or "<h1" in data["html"]
    assert data["title"]


@pytest.mark.asyncio
async def test_help_article_not_found(client):
    r = await client.get("/api/help/article/nonexistent-article-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_help_article_invalid_slug(client):
    r = await client.get("/api/help/article/../../etc/passwd")
    # URL encoding may transform slashes; either 400 (caught by validation) or 404 (not found) is safe
    assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_help_article_path_traversal(client):
    r = await client.get("/api/help/article/..--..--etc--passwd")
    # Should be 404 (not found) not 500
    assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_help_search_finds_results(client):
    r = await client.get("/api/help/search?q=conversion")
    assert r.status_code == 200
    data = r.json()
    assert "results" in data


@pytest.mark.asyncio
async def test_help_search_empty_query(client):
    r = await client.get("/api/help/search?q=")
    assert r.status_code == 200
    assert r.json()["results"] == []


@pytest.mark.asyncio
async def test_help_search_short_query(client):
    r = await client.get("/api/help/search?q=a")
    assert r.status_code == 200
    assert r.json()["results"] == []


@pytest.mark.asyncio
async def test_help_no_auth_required(client):
    """Help endpoints should work without any auth headers."""
    r = await client.get("/api/help/index")
    assert r.status_code == 200


def test_all_index_articles_exist():
    """Every slug in _index.json should have a matching .md file."""
    if not _INDEX_PATH.exists():
        pytest.skip("Index file not found")
    index = json.loads(_INDEX_PATH.read_text())
    missing = []
    for cat in index.get("categories", []):
        for art in cat.get("articles", []):
            md_path = _HELP_DIR / f"{art['slug']}.md"
            if not md_path.exists():
                missing.append(art["slug"])
    assert missing == [], f"Missing articles: {missing}"


def test_all_articles_have_title():
    """Every article should render with a non-empty title."""
    if not _INDEX_PATH.exists():
        pytest.skip("Index file not found")
    index = json.loads(_INDEX_PATH.read_text())
    for cat in index.get("categories", []):
        for art in cat.get("articles", []):
            md_path = _HELP_DIR / f"{art['slug']}.md"
            if not md_path.exists():
                continue
            content = md_path.read_text(encoding="utf-8").strip()
            first_line = content.splitlines()[0] if content else ""
            assert first_line.startswith("# "), f"{art['slug']}.md missing # title on line 1"
