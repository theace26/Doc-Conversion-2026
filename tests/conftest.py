"""
Shared fixtures for MarkFlow test suite.

Provides: async test client, temporary directory fixtures, SQLite DB fixtures,
and runs generate_fixtures.py to ensure test files exist before any test runs.
"""

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Set DB_PATH before any app module is imported ─────────────────────────────
# aiosqlite :memory: creates a new DB per connection and won't persist across
# requests. Use a real temp file for the test session instead.
_TEST_DB = Path(tempfile.mktemp(suffix="_markflow_test.db"))
os.environ["DB_PATH"] = str(_TEST_DB)

# Generate test DOCX fixtures before anything runs
from tests.generate_fixtures import generate_all  # noqa: E402

generate_all()


# ── App + async fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def client():
    """
    Async HTTP client pointed at the FastAPI app with a session-scoped temp DB.

    We explicitly call init_db() because ASGITransport does not guarantee the
    FastAPI lifespan runs before the first test request.
    """
    from core.database import init_db
    from main import app

    # Ensure schema is created before any test uses the DB
    await init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up test DB after session
    _TEST_DB.unlink(missing_ok=True)


# ── Directory fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def fixtures_dir() -> Path:
    """Path to tests/fixtures/."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def simple_docx(fixtures_dir) -> Path:
    return fixtures_dir / "simple.docx"


@pytest.fixture
def complex_docx(fixtures_dir) -> Path:
    return fixtures_dir / "complex.docx"
