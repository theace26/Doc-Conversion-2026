# Audit Remediation & Spec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 17 items from the Health Audit + Specification Review, eliminating DB contention, improving throughput, and fixing broken subsystems.

**Architecture:** Single-writer DB connection pool with async write queue, TTL-cached preferences, provider-aware vision batching, incremental scanning with dedup, and hardware-auto-detected concurrency limits.

**Tech Stack:** Python 3.11+, aiosqlite, FastAPI, asyncio, PyMuPDF (fitz), pdfplumber, structlog

**Spec:** `docs/superpowers/specs/2026-04-09-audit-remediation-design.md`

---

## Dependency Graph & Parallel Execution

```
WAVE 1 (all parallel — no dependencies):
  Task 1: Connection Pool + Write Queue
  Task 2: Preferences Cache
  Task 3: Logging Suppression
  Task 4: Remove Unused Deps
  Task 5: Frontend Polling
  Task 6: Structural Hash
  Task 7: Vision Adapter MIME Fix + Batch Redesign
  Task 8: PDF Engine PyMuPDF Auto-Switch
  Task 9: Vector Indexing Backpressure

WAVE 2 (depends on Wave 1 completions):
  Task 10: Pipeline Stats Caching          [depends: Task 1]
  Task 11: Lifecycle Manager I/O Fix       [depends: Task 1]
  Task 12: bulk_files Dedup + Schema       [depends: Task 1]
  Task 13: Worker Pool + Counter Batching  [depends: Task 1, Task 2]
  Task 14: Conversion Semaphore Auto-Detect [depends: Task 2]
  Task 15: Lifecycle Timers + Trash Expiry [depends: Task 2]

WAVE 3 (depends on Wave 2):
  Task 16: Scanner Incremental Mode        [depends: Task 12]
  Task 17: Scheduler Updates + Housekeeping [depends: Task 2, Task 15]
  Task 18: Stale Job Detection             [depends: Task 1, Task 13]

WAVE 4 (final integration):
  Task 19: markitdown Validation Utility   [depends: Task 6]
  Task 20: Startup Migrations + Version Bump [depends: ALL]
```

---

## WAVE 1 — No Dependencies (all parallel)

---

### Task 1: Connection Pool + Write Queue

**Files:**
- Create: `core/db/pool.py`
- Modify: `core/db/connection.py:43-149`
- Test: `tests/test_db_pool.py`

- [ ] **Step 1: Create `core/db/pool.py` with WriteQueue and ConnectionPool**

```python
"""
SQLite connection pool with single-writer queue and read-only pool.

SQLite allows exactly 1 writer at a time (WAL mode). This pool
serializes all writes through a single connection via an async queue,
eliminating "database is locked" errors entirely. Read-only connections
are pooled separately and never compete for the write lock.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger(__name__)

_DB_PATH: str = ""


@dataclass
class _WriteRequest:
    sql: str
    params: tuple | None
    future: asyncio.Future


@dataclass
class _BatchWriteRequest:
    operations: list[tuple[str, tuple | None]]
    future: asyncio.Future


class WriteQueue:
    """Serializes all DB writes through a single connection."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._depth_gauge = 0

    async def start(self):
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @property
    def depth(self) -> int:
        return self._depth_gauge

    async def _process_loop(self):
        while True:
            req = await self._queue.get()
            self._depth_gauge = self._queue.qsize()
            try:
                if isinstance(req, _BatchWriteRequest):
                    results = []
                    async with self._conn.execute("BEGIN"):
                        pass
                    for sql, params in req.operations:
                        cursor = await self._conn.execute(sql, params or ())
                        results.append(cursor.lastrowid)
                    await self._conn.commit()
                    req.future.set_result(results)
                else:
                    cursor = await self._conn.execute(req.sql, req.params or ())
                    await self._conn.commit()
                    req.future.set_result(cursor.lastrowid)
            except Exception as e:
                try:
                    await self._conn.rollback()
                except Exception:
                    pass
                req.future.set_exception(e)

    async def execute(self, sql: str, params: tuple | None = None) -> Any:
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        await self._queue.put(_WriteRequest(sql, params, future))
        return await future

    async def execute_many(self, operations: list[tuple[str, tuple | None]]) -> list:
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        await self._queue.put(_BatchWriteRequest(operations, future))
        return await future


class ConnectionPool:
    """Fixed-size pool: 1 writer + 3 read-only connections."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._writer: aiosqlite.Connection | None = None
        self._write_queue: WriteQueue | None = None
        self._read_pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
        self._read_connections: list[aiosqlite.Connection] = []
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return

        # Writer connection
        self._writer = await aiosqlite.connect(self._db_path)
        self._writer.row_factory = aiosqlite.Row
        await self._writer.execute("PRAGMA journal_mode=WAL")
        await self._writer.execute("PRAGMA busy_timeout=30000")
        await self._writer.execute("PRAGMA foreign_keys=ON")

        self._write_queue = WriteQueue(self._writer)
        await self._write_queue.start()

        # Read-only connections (3)
        for _ in range(3):
            conn = await aiosqlite.connect(self._db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA busy_timeout=30000")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA query_only=ON")
            self._read_connections.append(conn)
            await self._read_pool.put(conn)

        self._initialized = True
        log.info("db_pool.initialized", writer=1, readers=3)

    async def shutdown(self):
        if self._write_queue:
            await self._write_queue.stop()
        if self._writer:
            await self._writer.close()
        for conn in self._read_connections:
            await conn.close()
        self._initialized = False
        log.info("db_pool.shutdown")

    async def write(self, sql: str, params: tuple | None = None) -> Any:
        if not self._write_queue:
            raise RuntimeError("Pool not initialized")
        return await self._write_queue.execute(sql, params)

    async def write_many(self, operations: list[tuple[str, tuple | None]]) -> list:
        if not self._write_queue:
            raise RuntimeError("Pool not initialized")
        return await self._write_queue.execute_many(operations)

    async def read(self, sql: str, params: tuple | None = None) -> list[dict]:
        conn = await self._read_pool.get()
        try:
            cursor = await conn.execute(sql, params or ())
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await self._read_pool.put(conn)

    async def read_one(self, sql: str, params: tuple | None = None) -> dict | None:
        conn = await self._read_pool.get()
        try:
            cursor = await conn.execute(sql, params or ())
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await self._read_pool.put(conn)

    @property
    def write_queue_depth(self) -> int:
        return self._write_queue.depth if self._write_queue else 0


# Module-level singleton
_pool: ConnectionPool | None = None


async def init_pool(db_path: str):
    global _pool
    _pool = ConnectionPool(db_path)
    await _pool.initialize()


async def shutdown_pool():
    global _pool
    if _pool:
        await _pool.shutdown()
        _pool = None


def get_pool() -> ConnectionPool:
    if not _pool:
        raise RuntimeError("Connection pool not initialized. Call init_pool() first.")
    return _pool
```

- [ ] **Step 2: Write tests for the pool**

```python
# tests/test_db_pool.py
import asyncio
import os
import tempfile
import pytest
from core.db.pool import ConnectionPool

@pytest.fixture
async def pool(tmp_path):
    db_path = str(tmp_path / "test.db")
    p = ConnectionPool(db_path)
    await p.initialize()
    # Create a test table
    await p.write("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
    yield p
    await p.shutdown()

@pytest.mark.asyncio
async def test_write_and_read(pool):
    await pool.write("INSERT INTO items (name) VALUES (?)", ("hello",))
    rows = await pool.read("SELECT name FROM items")
    assert len(rows) == 1
    assert rows[0]["name"] == "hello"

@pytest.mark.asyncio
async def test_write_many_batches(pool):
    ops = [("INSERT INTO items (name) VALUES (?)", (f"item_{i}",)) for i in range(50)]
    await pool.write_many(ops)
    rows = await pool.read("SELECT COUNT(*) as cnt FROM items")
    assert rows[0]["cnt"] == 50

@pytest.mark.asyncio
async def test_read_one(pool):
    await pool.write("INSERT INTO items (name) VALUES (?)", ("single",))
    row = await pool.read_one("SELECT name FROM items WHERE name = ?", ("single",))
    assert row is not None
    assert row["name"] == "single"

@pytest.mark.asyncio
async def test_read_one_missing(pool):
    row = await pool.read_one("SELECT name FROM items WHERE name = ?", ("nonexistent",))
    assert row is None

@pytest.mark.asyncio
async def test_concurrent_writes_no_lock_error(pool):
    """Multiple concurrent writes should all succeed (serialized by queue)."""
    async def do_insert(n):
        await pool.write("INSERT INTO items (name) VALUES (?)", (f"concurrent_{n}",))

    await asyncio.gather(*[do_insert(i) for i in range(100)])
    rows = await pool.read("SELECT COUNT(*) as cnt FROM items")
    assert rows[0]["cnt"] == 100

@pytest.mark.asyncio
async def test_write_queue_depth(pool):
    assert pool.write_queue_depth >= 0

@pytest.mark.asyncio
async def test_write_rollback_on_error(pool):
    """Bad SQL should not corrupt the connection."""
    with pytest.raises(Exception):
        await pool.write("INSERT INTO nonexistent_table VALUES (?)", ("bad",))
    # Connection should still work
    await pool.write("INSERT INTO items (name) VALUES (?)", ("after_error",))
    rows = await pool.read("SELECT name FROM items WHERE name = ?", ("after_error",))
    assert len(rows) == 1
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_db_pool.py -v`
Expected: All 7 tests PASS

- [ ] **Step 4: Update `core/db/connection.py` to use pool**

Replace the existing `db_fetch_one`, `db_fetch_all`, `db_execute` functions to route through the pool when available, falling back to direct connection for backward compat during migration:

In `core/db/connection.py`, replace lines 112-149:

```python
from core.db.pool import get_pool


async def db_fetch_one(query: str, params: tuple | None = None) -> dict | None:
    """SELECT returning first row as dict or None. Uses read-only pool."""
    try:
        pool = get_pool()
        return await pool.read_one(query, params)
    except RuntimeError:
        # Pool not initialized yet (during schema init)
        async with get_db() as conn:
            cursor = await conn.execute(query, params or ())
            row = await cursor.fetchone()
            return dict(row) if row else None


async def db_fetch_all(query: str, params: tuple | None = None) -> list[dict]:
    """SELECT returning all rows as list of dicts. Uses read-only pool."""
    try:
        pool = get_pool()
        return await pool.read(query, params)
    except RuntimeError:
        async with get_db() as conn:
            cursor = await conn.execute(query, params or ())
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def db_execute(query: str, params: tuple | None = None) -> int:
    """INSERT/UPDATE/DELETE via write queue. Returns lastrowid."""
    try:
        pool = get_pool()
        return await pool.write(query, params)
    except RuntimeError:
        async with get_db() as conn:
            cursor = await conn.execute(query, params or ())
            await conn.commit()
            return cursor.lastrowid
```

- [ ] **Step 5: Commit**

```bash
git add core/db/pool.py core/db/connection.py tests/test_db_pool.py
git commit -m "feat: add SQLite connection pool with single-writer queue

1 dedicated writer connection with async write queue eliminates
'database is locked' errors. 3 read-only connections for analytics.
Existing db_fetch_*/db_execute functions transparently route through
pool when initialized, fall back to direct connection during startup."
```

---

### Task 2: Preferences Cache

**Files:**
- Create: `core/preferences_cache.py`
- Modify: `api/routes/preferences.py` (add cache invalidation)
- Test: `tests/test_preferences_cache.py`

- [ ] **Step 1: Create `core/preferences_cache.py`**

```python
"""
In-memory TTL cache for database preferences.

Preferences change rarely (user clicks Save in Settings). Caching them
avoids a DB round-trip on every scheduler tick, every worker file, and
every scan iteration. TTL of 300s means worst-case 5 minutes of stale
data after a Settings change — acceptable for all current consumers.
"""

import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_time)
_TTL = 300  # 5 minutes


async def get_cached_preference(key: str, default: Any = None) -> Any:
    """Read a preference, serving from cache if fresh."""
    now = time.time()
    if key in _cache:
        value, expiry = _cache[key]
        if now < expiry:
            return value

    # Cache miss — read from DB
    from core.db.preferences import get_preference
    value = await get_preference(key, default)
    _cache[key] = (value, now + _TTL)
    return value


def invalidate_preference(key: str):
    """Remove a single key from cache. Call after PUT /api/preferences/<key>."""
    removed = _cache.pop(key, None)
    if removed is not None:
        log.debug("preferences_cache.invalidated", key=key)


def invalidate_all():
    """Clear entire cache. Call after bulk settings save."""
    count = len(_cache)
    _cache.clear()
    if count:
        log.debug("preferences_cache.invalidated_all", count=count)
```

- [ ] **Step 2: Write tests**

```python
# tests/test_preferences_cache.py
import time
import pytest
from unittest.mock import AsyncMock, patch
from core.preferences_cache import (
    get_cached_preference,
    invalidate_preference,
    invalidate_all,
    _cache,
    _TTL,
)


@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.mark.asyncio
@patch("core.preferences_cache.get_preference", new_callable=AsyncMock, return_value=42)
async def test_cache_miss_calls_db(mock_get):
    result = await get_cached_preference("some_key", default=0)
    assert result == 42
    mock_get.assert_called_once_with("some_key", 0)


@pytest.mark.asyncio
@patch("core.preferences_cache.get_preference", new_callable=AsyncMock, return_value=42)
async def test_cache_hit_skips_db(mock_get):
    await get_cached_preference("some_key", default=0)
    mock_get.reset_mock()
    result = await get_cached_preference("some_key", default=0)
    assert result == 42
    mock_get.assert_not_called()


@pytest.mark.asyncio
@patch("core.preferences_cache.get_preference", new_callable=AsyncMock, return_value=99)
async def test_invalidate_forces_refresh(mock_get):
    _cache["my_key"] = (42, time.time() + 9999)
    invalidate_preference("my_key")
    result = await get_cached_preference("my_key", default=0)
    assert result == 99
    mock_get.assert_called_once()


def test_invalidate_all():
    _cache["a"] = (1, time.time() + 9999)
    _cache["b"] = (2, time.time() + 9999)
    invalidate_all()
    assert len(_cache) == 0
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_preferences_cache.py -v`
Expected: All 4 tests PASS

- [ ] **Step 4: Wire cache invalidation into preferences API**

In `api/routes/preferences.py`, find the PUT handler and add invalidation. Search for the function that handles `PUT /api/preferences`:

```python
# Add import at top of file
from core.preferences_cache import invalidate_preference

# Inside the PUT handler, after the DB write succeeds:
    invalidate_preference(key)
```

- [ ] **Step 5: Commit**

```bash
git add core/preferences_cache.py tests/test_preferences_cache.py api/routes/preferences.py
git commit -m "feat: add preferences TTL cache with 5-minute expiry

All get_preference() calls can now use get_cached_preference() to
avoid per-call DB reads. Cache invalidated on PUT /api/preferences."
```

---

### Task 3: Logging Suppression

**Files:**
- Modify: `core/logging_config.py:113-200`

- [ ] **Step 1: Add httpx/httpcore suppression to `configure_logging()`**

In `core/logging_config.py`, inside the `configure_logging()` function (after the existing pdfminer suppression), add:

```python
    # Suppress httpx/httpcore debug noise (~40,000 lines/day from Meilisearch polling)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
    logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
```

- [ ] **Step 2: Verify with py_compile**

Run: `python -m py_compile core/logging_config.py`
Expected: No output (clean)

- [ ] **Step 3: Commit**

```bash
git add core/logging_config.py
git commit -m "fix: suppress httpx/httpcore debug logging

Eliminates ~40,000 log lines/day from Meilisearch polling.
Same pattern as existing pdfminer suppression."
```

---

### Task 4: Remove Unused Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Verify mammoth and markdownify are unused**

Run: `grep -r "import mammoth\|from mammoth\|import markdownify\|from markdownify" --include="*.py" .`
Expected: No matches

- [ ] **Step 2: Remove from requirements.txt**

Remove the lines containing `mammoth` and `markdownify` from `requirements.txt`. Keep `markitdown[all]` (used in Task 19).

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: remove unused mammoth and markdownify dependencies

Neither package is imported anywhere in the codebase.
Reduces Docker image size and pip install time."
```

---

### Task 5: Frontend Polling

**Files:**
- Modify: `static/js/global-status-bar.js:10-51`

- [ ] **Step 1: Rewrite `global-status-bar.js` polling logic**

Replace the entire `startPolling` / `setInterval` section (around lines 36-39 and the visibilitychange handler) with:

```javascript
  var POLL_VISIBLE = 20000;     // 20 seconds when tab visible
  var POLL_HIDDEN = 30000;      // 30 seconds when tab hidden
  var MAX_HIDDEN_MS = 1800000;  // 30 minutes max hidden polling
  var hiddenSince = null;
  var pollTimer = null;

  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(poll, POLL_VISIBLE);
  }

  document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
      hiddenSince = Date.now();
      clearInterval(pollTimer);
      pollTimer = setInterval(function() {
        if (Date.now() - hiddenSince > MAX_HIDDEN_MS) {
          clearInterval(pollTimer);
          pollTimer = null;
          return;
        }
        poll();
      }, POLL_HIDDEN);
    } else {
      hiddenSince = null;
      clearInterval(pollTimer);
      location.reload();
    }
  });

  startPolling();
```

- [ ] **Step 2: Audit other page JS for polling timers**

Run: `grep -rn "setInterval" static/js/ static/*.html --include="*.js" --include="*.html" | grep -v node_modules`

For each file found with a polling interval < 15000 (15s), update to at least 15000.

- [ ] **Step 3: Commit**

```bash
git add static/js/global-status-bar.js
git commit -m "fix: reduce frontend polling from 5s to 20s visible, 30s hidden

Hidden tab stops polling after 30 minutes. Tab re-activation
triggers full page reload for fresh state. Eliminates ~40,000
unnecessary requests/day."
```

---

### Task 6: Structural Hash

**Files:**
- Modify: `core/document_model.py:135-200`
- Modify: `tests/test_roundtrip.py`

- [ ] **Step 1: Add `structural_hash()` method to DocumentModel**

In `core/document_model.py`, add this method to the `DocumentModel` class (after existing methods, around line 184):

```python
    def structural_hash(self) -> str:
        """Generate a single hash representing document structure for comparison."""
        import hashlib
        parts = []

        headings = [e for e in self.elements if e.element_type == ElementType.HEADING]
        parts.append(f"h:{len(headings)}")
        for h in headings:
            parts.append(f"ht:{h.content[:100]}")

        tables = [e for e in self.elements if e.element_type == ElementType.TABLE]
        parts.append(f"t:{len(tables)}")
        for t in tables:
            if t.table_data:
                rows_count = len(t.table_data)
                cols_count = len(t.table_data[0]) if t.table_data else 0
                parts.append(f"td:{rows_count}x{cols_count}")
                for row in t.table_data:
                    for cell in row:
                        parts.append(f"tc:{str(cell)[:50]}")

        images = [e for e in self.elements if e.element_type == ElementType.IMAGE]
        parts.append(f"i:{len(images)}")
        for img in images:
            w = img.metadata.get("width", 0) if img.metadata else 0
            h_val = img.metadata.get("height", 0) if img.metadata else 0
            parts.append(f"id:{w}x{h_val}")

        lists = [e for e in self.elements if e.element_type == ElementType.LIST]
        parts.append(f"l:{len(lists)}")
        for li in lists:
            depth = li.metadata.get("depth", 0) if li.metadata else 0
            parts.append(f"ld:{depth}")

        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()
```

- [ ] **Step 2: Write tests**

Add to `tests/test_roundtrip.py` (or create `tests/test_structural_hash.py`):

```python
from core.document_model import DocumentModel, Element, ElementType

def _make_model():
    m = DocumentModel()
    m.elements = [
        Element(element_type=ElementType.HEADING, content="Title"),
        Element(element_type=ElementType.PARAGRAPH, content="Body text"),
        Element(element_type=ElementType.TABLE, content="", table_data=[["a", "b"], ["c", "d"]]),
        Element(element_type=ElementType.IMAGE, content="img.png", metadata={"width": 100, "height": 50}),
    ]
    return m

def test_structural_hash_consistency():
    m1 = _make_model()
    m2 = _make_model()
    assert m1.structural_hash() == m2.structural_hash()

def test_structural_hash_detects_heading_change():
    m1 = _make_model()
    m2 = _make_model()
    m2.elements.append(Element(element_type=ElementType.HEADING, content="Extra"))
    assert m1.structural_hash() != m2.structural_hash()

def test_structural_hash_detects_table_change():
    m1 = _make_model()
    m2 = _make_model()
    m2.elements[2].table_data.append(["e", "f"])
    assert m1.structural_hash() != m2.structural_hash()

def test_structural_hash_detects_image_dimension_change():
    m1 = _make_model()
    m2 = _make_model()
    m2.elements[3].metadata["width"] = 200
    assert m1.structural_hash() != m2.structural_hash()
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_structural_hash.py -v`
Expected: All 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add core/document_model.py tests/test_structural_hash.py
git commit -m "feat: add structural_hash() to DocumentModel for round-trip testing

Combines heading count+text, table dimensions+content, image
count+dimensions, list count+depth into a single SHA-256 hash."
```

---

### Task 7: Vision Adapter MIME Fix + Batch Redesign

**Files:**
- Modify: `core/vision_adapter.py:22-414`
- Modify: `core/db/analysis.py` (batch status fields)
- Test: `tests/test_vision_mime.py`

- [ ] **Step 1: Add magic-byte MIME detection**

At the top of `core/vision_adapter.py`, after the existing imports (around line 19), add:

```python
import mimetypes
from pathlib import Path

_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF89a", "image/gif"),
    (b"GIF87a", "image/gif"),
    (b"BM", "image/bmp"),
]


def detect_mime(file_path: Path | str) -> str:
    """Detect actual MIME from file magic bytes, fall back to extension."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(32)
        # Check RIFF/WEBP (bytes 0-3 = RIFF, bytes 8-12 = WEBP)
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            return "image/webp"
        for magic, mime in _MAGIC_BYTES:
            if header[: len(magic)] == magic:
                return mime
    except OSError:
        pass
    return mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
```

- [ ] **Step 2: Add provider-aware batch limits**

After the `detect_mime` function, add:

```python
_PROVIDER_LIMITS = {
    "anthropic": {
        "max_request_bytes": 24 * 1024 * 1024,
        "max_image_raw_bytes": 3_500_000,
        "max_images_per_batch": 20,
        "max_edge_px": 1568,
    },
    "openai": {
        "max_request_bytes": 18 * 1024 * 1024,
        "max_image_raw_bytes": 18 * 1024 * 1024,
        "max_images_per_batch": 10,
        "max_edge_px": 2048,
    },
    "gemini": {
        "max_request_bytes": 18 * 1024 * 1024,
        "max_image_raw_bytes": 18 * 1024 * 1024,
        "max_images_per_batch": 16,
        "max_edge_px": 3072,
    },
    "ollama": {
        "max_request_bytes": 50 * 1024 * 1024,
        "max_image_raw_bytes": 50 * 1024 * 1024,
        "max_images_per_batch": 5,
        "max_edge_px": 1568,
    },
}
_DEFAULT_LIMITS = _PROVIDER_LIMITS["anthropic"]


def get_provider_limits(provider: str) -> dict:
    """Return batch limits for the given provider."""
    return _PROVIDER_LIMITS.get(provider, _DEFAULT_LIMITS)


def plan_batches(
    images: list[tuple[Path, int]],
    provider: str,
) -> list[list[Path]]:
    """Bin-pack images into batches sized per provider limits.

    Args:
        images: list of (file_path, file_size_bytes) sorted largest first
        provider: provider name for limit lookup

    Returns:
        list of batches, each a list of file paths
    """
    limits = get_provider_limits(provider)
    max_bytes = limits["max_request_bytes"]
    max_count = limits["max_images_per_batch"]

    batches: list[list[Path]] = []
    current_batch: list[Path] = []
    current_bytes = 0

    for path, size in images:
        # Base64 inflates by ~33%
        encoded_size = int(size * 1.34)
        if current_batch and (
            current_bytes + encoded_size > max_bytes
            or len(current_batch) >= max_count
        ):
            batches.append(current_batch)
            current_batch = []
            current_bytes = 0
        current_batch.append(path)
        current_bytes += encoded_size

    if current_batch:
        batches.append(current_batch)

    return batches
```

- [ ] **Step 3: Replace MIME detection in describe_batch**

In `core/vision_adapter.py`, find where the MIME type is determined for images in `describe_batch()` (around line 163-166 where `_compress_image_for_vision` is called). Replace the extension-based MIME with `detect_mime()`:

Find this pattern:
```python
            raw, mime = _compress_image_for_vision(raw, image_path.suffix)
```

Replace with:
```python
            mime = detect_mime(image_path)
            raw, mime = _compress_image_for_vision(raw, mime)
```

And update `_compress_image_for_vision` signature to accept MIME string directly instead of suffix. In the function (line 38), change:

```python
def _compress_image_for_vision(
    raw: bytes, suffix: str
) -> tuple[bytes, str]:
```

to:

```python
def _compress_image_for_vision(
    raw: bytes, mime_or_suffix: str
) -> tuple[bytes, str]:
```

At the top of the function, normalize:
```python
    if mime_or_suffix.startswith("image/"):
        mime = mime_or_suffix
    else:
        mime = mimetypes.guess_type(f"file{mime_or_suffix}")[0] or "image/png"
```

- [ ] **Step 4: Write MIME detection tests**

```python
# tests/test_vision_mime.py
import tempfile
from pathlib import Path
from core.vision_adapter import detect_mime, plan_batches

def test_detect_jpeg():
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 28)
        f.flush()
        assert detect_mime(f.name) == "image/jpeg"

def test_detect_gif_with_jpg_extension():
    """The bug that caused 115 failures — .jpg file that is actually GIF."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"GIF89a" + b"\x00" * 26)
        f.flush()
        assert detect_mime(f.name) == "image/gif"

def test_detect_png():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
        f.flush()
        assert detect_mime(f.name) == "image/png"

def test_fallback_to_extension():
    with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
        f.write(b"\x00" * 32)  # Unknown magic bytes
        f.flush()
        result = detect_mime(f.name)
        assert "tiff" in result or result == "image/tiff"

def test_plan_batches_respects_max_count():
    images = [(Path(f"/img/{i}.jpg"), 100_000) for i in range(25)]
    batches = plan_batches(images, "anthropic")
    assert all(len(b) <= 20 for b in batches)
    assert sum(len(b) for b in batches) == 25

def test_plan_batches_respects_max_bytes():
    # 5 images at 10MB each = 50MB raw, ~67MB encoded
    # Anthropic limit is 24MB → should split
    images = [(Path(f"/img/{i}.jpg"), 10_000_000) for i in range(5)]
    batches = plan_batches(images, "anthropic")
    assert len(batches) > 1

def test_plan_batches_provider_differences():
    images = [(Path(f"/img/{i}.jpg"), 100_000) for i in range(15)]
    anthropic_batches = plan_batches(images, "anthropic")
    openai_batches = plan_batches(images, "openai")
    # OpenAI has max 10 per batch, Anthropic has 20
    assert len(openai_batches) > len(anthropic_batches)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_vision_mime.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add core/vision_adapter.py tests/test_vision_mime.py
git commit -m "feat: magic-byte MIME detection + provider-aware vision batching

Detects actual image format from file headers instead of trusting
extension. Fixes 115 batch failures from .jpg files that are GIFs.
Batch sizing adapts to active provider limits (anthropic, openai,
gemini, ollama)."
```

---

### Task 8: PDF Engine PyMuPDF Auto-Switch

**Files:**
- Modify: `formats/pdf_handler.py`
- Test: `tests/test_pdf_engine_switch.py`

- [ ] **Step 1: Read the current pdf_handler.py to understand the ingest method**

Read `formats/pdf_handler.py` completely to find the current `ingest()` method and understand how pdfplumber is used.

- [ ] **Step 2: Add PyMuPDF extraction with table detection**

At the top of `formats/pdf_handler.py`, add the fitz import (if not already present):

```python
import fitz  # PyMuPDF
```

Add a table detection helper:

```python
def _has_tables_pymupdf(page) -> bool:
    """Detect table presence via line/rect analysis in PyMuPDF page."""
    try:
        drawings = page.get_drawings()
        h_lines = 0
        v_lines = 0
        for d in drawings:
            for item in d.get("items", []):
                if item[0] == "l" and len(item) >= 3:
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 2:
                        h_lines += 1
                    if abs(p1.x - p2.x) < 2:
                        v_lines += 1
        return h_lines >= 3 and v_lines >= 3
    except Exception:
        return False
```

- [ ] **Step 3: Modify ingest to use PyMuPDF as default with pdfplumber fallback**

In the `ingest()` method, replace the pdfplumber-only extraction with:

```python
    async def ingest(self, file_path: Path) -> DocumentModel:
        from core.preferences_cache import get_cached_preference
        engine = await get_cached_preference("pdf_engine", "pymupdf")

        if engine == "pdfplumber":
            return await self._ingest_pdfplumber(file_path)

        return await self._ingest_pymupdf_with_fallback(file_path)

    async def _ingest_pymupdf_with_fallback(self, file_path: Path) -> DocumentModel:
        """PyMuPDF primary, pdfplumber for pages with tables."""
        import fitz
        model = DocumentModel()
        doc = fitz.open(str(file_path))

        for page_num in range(len(doc)):
            page = doc[page_num]

            if _has_tables_pymupdf(page):
                log.debug("pdf_engine.table_detected_switching",
                          page=page_num + 1, engine="pdfplumber")
                elements = await asyncio.to_thread(
                    self._extract_page_pdfplumber, file_path, page_num
                )
            else:
                elements = self._extract_page_pymupdf(page, page_num)

            model.elements.extend(elements)

        doc.close()
        return model
```

Then add the per-page extraction helpers:

```python
    def _extract_page_pymupdf(self, page, page_num: int) -> list:
        """Extract text from a single page using PyMuPDF."""
        elements = []
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] == 0:  # text block
                for line in block["lines"]:
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if text:
                        elements.append(Element(
                            element_type=ElementType.PARAGRAPH,
                            content=text,
                            metadata={"page": page_num + 1},
                        ))
            elif block["type"] == 1:  # image block
                elements.append(Element(
                    element_type=ElementType.IMAGE,
                    content=f"page_{page_num + 1}_image",
                    metadata={"page": page_num + 1,
                              "width": block.get("width", 0),
                              "height": block.get("height", 0)},
                ))
        return elements

    def _extract_page_pdfplumber(self, file_path: Path, page_num: int) -> list:
        """Extract a single page using pdfplumber (better table extraction)."""
        import pdfplumber
        elements = []
        with pdfplumber.open(str(file_path)) as pdf:
            if page_num < len(pdf.pages):
                page = pdf.pages[page_num]
                tables = page.extract_tables()
                for table in tables:
                    elements.append(Element(
                        element_type=ElementType.TABLE,
                        content="",
                        table_data=table,
                        metadata={"page": page_num + 1},
                    ))
                # Get non-table text
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        elements.append(Element(
                            element_type=ElementType.PARAGRAPH,
                            content=line,
                            metadata={"page": page_num + 1},
                        ))
        return elements
```

Rename the existing `ingest` method to `_ingest_pdfplumber` to preserve backward compat.

- [ ] **Step 4: Verify with py_compile**

Run: `python -m py_compile formats/pdf_handler.py`
Expected: No output (clean)

- [ ] **Step 5: Commit**

```bash
git add formats/pdf_handler.py
git commit -m "feat: PyMuPDF as default PDF engine with auto-switch to pdfplumber on tables

Pages with detected table gridlines switch to pdfplumber for that
page only. All other pages use PyMuPDF (faster). Controlled by
pdf_engine preference (default: pymupdf, override: pdfplumber)."
```

---

### Task 9: Vector Indexing Backpressure

**Files:**
- Modify: `core/bulk_worker.py:879-899`

- [ ] **Step 1: Add bounded semaphore for vector indexing**

At module level in `core/bulk_worker.py` (near the top, around line 71):

```python
_vector_semaphore = asyncio.Semaphore(20)
```

- [ ] **Step 2: Wrap vector indexing calls**

Find the `asyncio.create_task(_index_vector_async...)` call around line 879-899. Replace:

```python
            asyncio.create_task(_index_vector_async(source_path, md_content))
```

with:

```python
            asyncio.create_task(_index_vector_with_backpressure(source_path, md_content))
```

Add the wrapper function:

```python
async def _index_vector_with_backpressure(source_path: str, content: str):
    """Index to Qdrant with bounded concurrency. Skip if queue is full."""
    acquired = _vector_semaphore.acquire_nowait()
    if not acquired:
        log.info("vector_indexing.backpressure_skip", file=source_path)
        return
    try:
        await _index_vector_async(source_path, content)
    finally:
        _vector_semaphore.release()
```

- [ ] **Step 3: Verify with py_compile**

Run: `python -m py_compile core/bulk_worker.py`
Expected: No output (clean)

- [ ] **Step 4: Commit**

```bash
git add core/bulk_worker.py
git commit -m "feat: add vector indexing backpressure with bounded semaphore (20)

Prevents unbounded asyncio task accumulation when Qdrant is slow.
Skipped files picked up on next lifecycle scan."
```

---

## WAVE 2 — Depends on Wave 1

---

### Task 10: Pipeline Stats Caching [depends: Task 1]

**Files:**
- Modify: `api/routes/pipeline.py:226-298`
- Modify: `core/scan_coordinator.py:158-180`

- [ ] **Step 1: Add TTL cache to pipeline_stats()**

At the top of `api/routes/pipeline.py`, add:

```python
import asyncio as _asyncio
import time as _time

_stats_lock = _asyncio.Lock()
_stats_cache: dict = {"result": None, "time": 0.0}
_status_lock = _asyncio.Lock()
_status_cache: dict = {"result": None, "time": 0.0}
_CACHE_TTL = 20  # seconds


def invalidate_stats_cache():
    """Called from scan_coordinator on bulk job start/complete."""
    _stats_cache["time"] = 0.0
    _status_cache["time"] = 0.0
```

- [ ] **Step 2: Wrap pipeline_stats() with cache**

Replace the body of `pipeline_stats()` (lines ~230-298):

```python
async def pipeline_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Pipeline funnel statistics across all processing stages."""
    now = _time.time()
    if _stats_cache["result"] and now - _stats_cache["time"] < _CACHE_TTL:
        return _stats_cache["result"]

    async with _stats_lock:
        # Double-check after acquiring lock
        if _stats_cache["result"] and _time.time() - _stats_cache["time"] < _CACHE_TTL:
            return _stats_cache["result"]

        # ... existing query logic unchanged ...
        result = {
            "scanned": scanned or 0,
            "pending_conversion": pending_conv or 0,
            "failed": failed or 0,
            "unrecognized": unrecognized or 0,
            "pending_analysis": analysis.get("pending", 0),
            "batched_for_analysis": analysis.get("batched", 0),
            "analysis_failed": analysis.get("failed", 0),
            "in_search_index": search_count,
        }
        _stats_cache["result"] = result
        _stats_cache["time"] = _time.time()
        return result
```

Apply the same pattern to `pipeline_status()` (lines ~47-156) using `_status_cache` and `_status_lock`.

- [ ] **Step 3: Wire invalidation into scan_coordinator**

In `core/scan_coordinator.py`, in `notify_bulk_started()` (line ~158) and `notify_bulk_completed()` (line ~172), add:

```python
from api.routes.pipeline import invalidate_stats_cache
invalidate_stats_cache()
```

- [ ] **Step 4: Verify with py_compile**

Run: `python -m py_compile api/routes/pipeline.py && python -m py_compile core/scan_coordinator.py`
Expected: No output

- [ ] **Step 5: Commit**

```bash
git add api/routes/pipeline.py core/scan_coordinator.py
git commit -m "feat: add 20-second TTL cache to pipeline stats endpoints

Eliminates 95%+ of heavy COUNT/NOT EXISTS queries. Cache
invalidated on bulk job start/complete. Uses asyncio.Lock
for thundering herd prevention."
```

---

### Task 11: Lifecycle Manager I/O Fix [depends: Task 1]

**Files:**
- Modify: `core/lifecycle_manager.py:154-206`

- [ ] **Step 1: Refactor move_to_trash() to move I/O outside transaction**

Replace the `move_to_trash()` function (around line 154) with the two-transaction pattern:

```python
async def move_to_trash(file_id: str) -> bool:
    """Move file to .trash directory using two-transaction pattern.

    Transaction 1: Read metadata + set status='moving' (fast, no I/O)
    File I/O: shutil.move (no DB lock held)
    Transaction 2: Set status='in_trash' + record trash_path (fast)
    """
    # Transaction 1: Read metadata, set transitional status
    row = await db_fetch_one(
        "SELECT source_path, lifecycle_status FROM source_files WHERE id = ?",
        (file_id,),
    )
    if not row:
        return False
    if row["lifecycle_status"] not in ("marked_for_deletion",):
        return False

    source_path = row["source_path"]
    await db_execute(
        "UPDATE source_files SET lifecycle_status = 'moving' WHERE id = ?",
        (file_id,),
    )

    # File I/O — no DB lock held
    trash_dir = Path("/app/data/.trash")
    trash_dir.mkdir(parents=True, exist_ok=True)
    trash_dest = trash_dir / Path(source_path).name
    try:
        import shutil
        await asyncio.to_thread(shutil.move, source_path, str(trash_dest))
    except Exception as e:
        # Move failed — revert to marked_for_deletion
        await db_execute(
            "UPDATE source_files SET lifecycle_status = 'marked_for_deletion' WHERE id = ?",
            (file_id,),
        )
        log.error("lifecycle.trash_move_failed", file_id=file_id, error=str(e))
        return False

    # Transaction 2: Record final status
    await db_execute(
        """UPDATE source_files
           SET lifecycle_status = 'in_trash', trash_path = ?, trashed_at = ?
           WHERE id = ?""",
        (str(trash_dest), now_iso(), file_id),
    )

    log.info("lifecycle.trashed", bulk_file_id=file_id)
    return True
```

- [ ] **Step 2: Apply same pattern to purge_file()**

Similar refactor for `purge_file()` (around line 206): read metadata in one transaction, do `os.remove()` outside, update status in second transaction.

- [ ] **Step 3: Add startup recovery for 'moving' status**

In the same file, add a function that will be called from `main.py:lifespan`:

```python
async def recover_moving_files():
    """On startup, retry any files stuck in 'moving' status (crash recovery)."""
    rows = await db_fetch_all(
        "SELECT id FROM source_files WHERE lifecycle_status = 'moving'"
    )
    for row in rows:
        log.warning("lifecycle.recovering_stuck_move", file_id=row["id"])
        await db_execute(
            "UPDATE source_files SET lifecycle_status = 'marked_for_deletion' WHERE id = ?",
            (row["id"],),
        )
```

- [ ] **Step 4: Verify with py_compile**

Run: `python -m py_compile core/lifecycle_manager.py`
Expected: No output

- [ ] **Step 5: Commit**

```bash
git add core/lifecycle_manager.py
git commit -m "fix: move file I/O outside DB transactions in lifecycle manager

Two-transaction pattern: read metadata → commit → shutil.move
(no lock held) → update status. Eliminates 'database is locked'
errors during trash operations. Adds crash recovery for 'moving' state."
```

---

### Task 12: bulk_files Dedup + Schema [depends: Task 1]

**Files:**
- Modify: `core/db/schema.py:96-113`
- Modify: `core/db/bulk.py:140-199`
- Create: `core/db/migrations.py`

- [ ] **Step 1: Create migration module**

```python
# core/db/migrations.py
"""One-time database migrations gated by preference flags."""

import structlog
from core.db.connection import db_execute, db_fetch_one, db_fetch_all
from core.db.preferences import get_preference, set_preference

log = structlog.get_logger(__name__)


async def run_bulk_files_dedup():
    """One-time dedup of bulk_files: keep latest row per source_path.

    Gated by preference 'bulk_dedup_v0_23_done'. Expected to delete
    ~187,784 duplicate rows on first run.
    """
    done = await get_preference("bulk_dedup_v0_23_done", "false")
    if done == "true":
        return

    log.info("migration.bulk_dedup_starting")

    # Count before
    row = await db_fetch_one("SELECT COUNT(*) as cnt FROM bulk_files")
    before = row["cnt"] if row else 0

    # Delete all but the latest row per source_path (keep highest rowid)
    await db_execute("""
        DELETE FROM bulk_files
        WHERE rowid NOT IN (
            SELECT MAX(rowid) FROM bulk_files GROUP BY source_path
        )
    """)

    row = await db_fetch_one("SELECT COUNT(*) as cnt FROM bulk_files")
    after = row["cnt"] if row else 0

    log.info("migration.bulk_dedup_complete",
             before=before, after=after, deleted=before - after)

    await set_preference("bulk_dedup_v0_23_done", "true")


async def run_bulk_files_schema_migration():
    """Migrate bulk_files to unique(source_path) instead of unique(job_id, source_path).

    Must run AFTER dedup to avoid constraint violations.
    Gated by preference 'bulk_schema_v0_23_done'.
    """
    done = await get_preference("bulk_schema_v0_23_done", "false")
    if done == "true":
        return

    log.info("migration.bulk_schema_starting")

    # SQLite can't ALTER CONSTRAINT, so: create new table, copy, swap
    from core.db.pool import get_pool
    pool = get_pool()

    # Use the write queue for the migration (serialized, safe)
    await pool.write("""
        CREATE TABLE IF NOT EXISTS bulk_files_new (
            id TEXT PRIMARY KEY,
            job_id TEXT REFERENCES bulk_jobs(id),
            source_path TEXT NOT NULL UNIQUE,
            output_path TEXT,
            file_ext TEXT,
            file_size_bytes INTEGER,
            source_mtime REAL,
            stored_mtime REAL,
            content_hash TEXT,
            status TEXT DEFAULT 'pending',
            error_msg TEXT,
            converted_at TEXT,
            indexed_at TEXT,
            source_file_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    await pool.write("""
        INSERT OR IGNORE INTO bulk_files_new
        SELECT * FROM bulk_files
    """)

    await pool.write("DROP TABLE bulk_files")
    await pool.write("ALTER TABLE bulk_files_new RENAME TO bulk_files")

    # Recreate indexes
    await pool.write("CREATE INDEX IF NOT EXISTS idx_bulk_files_job_status ON bulk_files(job_id, status)")
    await pool.write("CREATE INDEX IF NOT EXISTS idx_bulk_files_source_path ON bulk_files(source_path)")

    await set_preference("bulk_schema_v0_23_done", "true")
    log.info("migration.bulk_schema_complete")
```

- [ ] **Step 2: Update upsert_bulk_file to use source_path key**

In `core/db/bulk.py`, update `upsert_bulk_file()` (around line 140). Change the ON CONFLICT clause:

Find:
```python
ON CONFLICT(job_id, source_path)
```
Replace with:
```python
ON CONFLICT(source_path)
```

And update the SET clause to also update `job_id`:
```python
DO UPDATE SET job_id=excluded.job_id, stored_mtime=excluded.stored_mtime, ...
```

- [ ] **Step 3: Verify with py_compile**

Run: `python -m py_compile core/db/migrations.py && python -m py_compile core/db/bulk.py`
Expected: No output

- [ ] **Step 4: Commit**

```bash
git add core/db/migrations.py core/db/bulk.py
git commit -m "feat: bulk_files dedup migration + source_path unique constraint

One-time migration deletes ~187K duplicate rows. Schema migrated
from unique(job_id, source_path) to unique(source_path) so rescans
update in place."
```

---

### Task 13: Worker Pool + Counter Batching [depends: Task 1, Task 2]

**Files:**
- Modify: `core/bulk_worker.py:71,245-302,575-576,631-632,834-836`

- [ ] **Step 1: Add CounterAccumulator class**

At the top of `core/bulk_worker.py` (after imports), add:

```python
import time as _time


class CounterAccumulator:
    """Batch counter updates to reduce DB writes from per-file to per-batch."""

    def __init__(self, job_id: str, flush_interval: int = 50, flush_timeout: float = 5.0):
        self.job_id = job_id
        self.counts: dict[str, int] = {"converted": 0, "failed": 0, "skipped": 0, "adobe_indexed": 0}
        self.since_flush = 0
        self.last_flush = _time.time()
        self.flush_interval = flush_interval
        self.flush_timeout = flush_timeout

    def increment(self, field: str):
        self.counts[field] = self.counts.get(field, 0) + 1
        self.since_flush += 1

    async def maybe_flush(self):
        if self.since_flush >= self.flush_interval or \
           _time.time() - self.last_flush > self.flush_timeout:
            await self._flush()

    async def _flush(self):
        if self.since_flush == 0:
            return
        from core.db.bulk import increment_bulk_job_counter
        for field, count in self.counts.items():
            if count > 0:
                await increment_bulk_job_counter(self.job_id, field, count)
        self.counts = {k: 0 for k in self.counts}
        self.since_flush = 0
        self.last_flush = _time.time()

    async def flush_final(self):
        await self._flush()
```

- [ ] **Step 2: Update increment_bulk_job_counter to accept count parameter**

In `core/db/bulk.py`, update `increment_bulk_job_counter()` (around line 69-76):

```python
async def increment_bulk_job_counter(job_id: str, field: str, count: int = 1):
    """Atomically increment a bulk job counter by count."""
    valid = {"converted", "skipped", "failed", "adobe_indexed"}
    if field not in valid:
        return
    await db_execute(
        f"UPDATE bulk_jobs SET {field} = {field} + ? WHERE id = ?",
        (count, job_id),
    )
```

- [ ] **Step 3: Replace per-file counter increments in BulkJob**

In `core/bulk_worker.py`, in `BulkJob.__init__` or `run()`, create the accumulator:

```python
self._counter = CounterAccumulator(self.job_id)
```

Then replace every instance of:
```python
await increment_bulk_job_counter(self.job_id, "skipped")
```
with:
```python
self._counter.increment("skipped")
await self._counter.maybe_flush()
```

Same for "failed" (line ~631-632) and "converted" (line ~834-836).

At job completion (in `run()`, around line 485), add:
```python
await self._counter.flush_final()
```

- [ ] **Step 4: Make worker count configurable from preferences**

In `BulkJob.run()` (around line 304), replace the hardcoded worker count:

```python
from core.preferences_cache import get_cached_preference
worker_count = int(await get_cached_preference("bulk_worker_count", 8))
```

- [ ] **Step 5: Verify with py_compile**

Run: `python -m py_compile core/bulk_worker.py && python -m py_compile core/db/bulk.py`
Expected: No output

- [ ] **Step 6: Commit**

```bash
git add core/bulk_worker.py core/db/bulk.py
git commit -m "feat: batch counter updates (50/flush) + configurable worker count

CounterAccumulator reduces DB writes from ~800K to ~16K per full scan.
Worker count read from preferences (default 8, range 1-16)."
```

---

### Task 14: Conversion Semaphore Auto-Detect [depends: Task 2]

**Files:**
- Modify: `core/converter.py:71`

- [ ] **Step 1: Replace hardcoded semaphore with auto-detected value**

In `core/converter.py`, replace line 71:

```python
_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_CONVERSIONS", "3")))
```

with:

```python
def _detect_default_concurrency() -> int:
    """Auto-detect optimal concurrent conversions based on host CPU."""
    cpu_count = os.cpu_count() or 4
    physical = max(2, min(cpu_count // 2, 8))
    return physical

_semaphore_limit = _detect_default_concurrency()
_semaphore = asyncio.Semaphore(_semaphore_limit)


async def refresh_semaphore():
    """Rebuild semaphore when max_concurrent_conversions preference changes."""
    global _semaphore, _semaphore_limit
    from core.preferences_cache import get_cached_preference
    limit = int(await get_cached_preference("max_concurrent_conversions", _detect_default_concurrency()))
    if limit != _semaphore_limit:
        _semaphore = asyncio.Semaphore(limit)
        _semaphore_limit = limit
        log.info("converter.semaphore_updated", limit=limit)
```

- [ ] **Step 2: Verify with py_compile**

Run: `python -m py_compile core/converter.py`
Expected: No output

- [ ] **Step 3: Commit**

```bash
git add core/converter.py
git commit -m "feat: auto-detect conversion semaphore from CPU count

Default: cpu_count // 2, capped at 8, floor at 2. Configurable
via max_concurrent_conversions preference. i7-10750H gets 6."
```

---

### Task 15: Lifecycle Timers + Trash Expiry Force [depends: Task 2]

**Files:**
- Modify: `core/scheduler.py:109-159`

- [ ] **Step 1: Add forced trash expiry every 4th run**

In `core/scheduler.py`, add module-level counter (near the top):

```python
_trash_expiry_run_count = 0
```

In `run_trash_expiry()` (around line 109), replace the active-jobs check:

```python
async def run_trash_expiry():
    global _trash_expiry_run_count
    _trash_expiry_run_count += 1

    force = (_trash_expiry_run_count % 4 == 0)

    if not force:
        active = await get_all_active_jobs()
        if active:
            log.info("trash_expiry.skipped_bulk_active")
            return

    if force:
        log.info("trash_expiry.forced_housekeeping_run", run_count=_trash_expiry_run_count)

    # ... existing trash expiry logic continues unchanged ...
```

- [ ] **Step 2: Verify with py_compile**

Run: `python -m py_compile core/scheduler.py`
Expected: No output

- [ ] **Step 3: Commit**

```bash
git add core/scheduler.py
git commit -m "fix: force trash expiry every 4th run regardless of active bulk jobs

Housekeeping priority: every 4th trash_expiry run bypasses the
active-jobs check to prevent indefinite maintenance deferral."
```

---

## WAVE 3 — Depends on Wave 2

---

### Task 16: Scanner Incremental Mode [depends: Task 12]

**Files:**
- Modify: `core/bulk_scanner.py:201-590`

- [ ] **Step 1: Add cross-job dedup after scan completes**

In `core/bulk_scanner.py`, in the `BulkScanner.scan()` method, after the scan loop completes (around line 446 or wherever the scan finishes), add:

```python
        # Post-scan dedup — remove any older duplicate rows per source_path
        # (safety net after schema migration to unique(source_path))
        try:
            from core.db.connection import db_execute
            await db_execute("""
                DELETE FROM bulk_files
                WHERE rowid NOT IN (
                    SELECT MAX(rowid) FROM bulk_files GROUP BY source_path
                )
            """)
        except Exception as e:
            log.warning("scan.post_dedup_failed", error=str(e))
```

- [ ] **Step 2: Add incremental skip for already-converted files**

In the per-file processing loop (inside `_serial_scan` or the parallel scan equivalent), before the upsert call, add:

```python
            # Skip files already successfully converted and unchanged
            existing = await db_fetch_one(
                "SELECT status, stored_mtime FROM bulk_files WHERE source_path = ?",
                (path_str,),
            )
            if existing and existing["status"] == "converted" and existing["stored_mtime"] == mtime:
                counters["skipped_unchanged"] += 1
                continue
```

- [ ] **Step 3: Verify with py_compile**

Run: `python -m py_compile core/bulk_scanner.py`
Expected: No output

- [ ] **Step 4: Commit**

```bash
git add core/bulk_scanner.py
git commit -m "feat: incremental scanning — skip converted+unchanged files, post-scan dedup

Files already converted with same mtime are skipped. Cross-job
dedup query runs after each scan as safety net."
```

---

### Task 17: Scheduler Housekeeping Job [depends: Task 2, Task 15]

**Files:**
- Modify: `core/scheduler.py:491-657`

- [ ] **Step 1: Add housekeeping job**

In `core/scheduler.py`, add a new function:

```python
async def run_housekeeping():
    """Periodic housekeeping — supersedes all other tasks.

    Does NOT check get_all_active_jobs(). Runs regardless of active bulk jobs.
    """
    log.info("housekeeping.start")

    # 1. Cross-job dedup (safety net)
    try:
        result = await db_execute("""
            DELETE FROM bulk_files
            WHERE rowid NOT IN (
                SELECT MAX(rowid) FROM bulk_files GROUP BY source_path
            )
        """)
        log.info("housekeeping.dedup_complete", deleted=result or 0)
    except Exception as e:
        log.warning("housekeeping.dedup_failed", error=str(e))

    # 2. PRAGMA optimize
    try:
        await db_execute("PRAGMA optimize")
    except Exception:
        pass

    # 3. Check free pages — VACUUM if > 10%
    try:
        from core.db.connection import db_fetch_one
        free = await db_fetch_one("PRAGMA freelist_count")
        total = await db_fetch_one("PRAGMA page_count")
        if free and total:
            free_count = list(free.values())[0]
            total_count = list(total.values())[0]
            if total_count > 0 and free_count / total_count > 0.10:
                log.info("housekeeping.vacuum_starting",
                         free_pages=free_count, total_pages=total_count)
                await db_execute("VACUUM")
                log.info("housekeeping.vacuum_complete")
    except Exception as e:
        log.warning("housekeeping.vacuum_failed", error=str(e))

    log.info("housekeeping.complete")
```

- [ ] **Step 2: Register in start_scheduler()**

In `start_scheduler()` (around line 491-657), add:

```python
    scheduler.add_job(
        run_housekeeping,
        "interval",
        hours=2,
        id="run_housekeeping",
        max_instances=1,
        replace_existing=True,
    )
```

- [ ] **Step 3: Verify with py_compile**

Run: `python -m py_compile core/scheduler.py`
Expected: No output

- [ ] **Step 4: Commit**

```bash
git add core/scheduler.py
git commit -m "feat: add 2-hour housekeeping job that supersedes all other tasks

Dedup + PRAGMA optimize + conditional VACUUM. Does NOT yield
to active bulk jobs — housekeeping is non-negotiable."
```

---

### Task 18: Stale Job Detection [depends: Task 1, Task 13]

**Files:**
- Modify: `core/db/schema.py:76-94`
- Modify: `core/bulk_worker.py`
- Modify: `core/db/migrations.py`

- [ ] **Step 1: Add last_heartbeat column migration**

In `core/db/migrations.py`, add:

```python
async def add_heartbeat_column():
    """Add last_heartbeat column to bulk_jobs if missing."""
    try:
        await db_execute(
            "ALTER TABLE bulk_jobs ADD COLUMN last_heartbeat TEXT"
        )
        log.info("migration.heartbeat_column_added")
    except Exception:
        pass  # Column already exists


async def cleanup_stale_jobs():
    """Mark jobs stuck in 'running' with stale heartbeat as 'interrupted'."""
    from core.db.connection import db_fetch_all
    stale = await db_fetch_all("""
        SELECT id FROM bulk_jobs
        WHERE status = 'running'
          AND (last_heartbeat IS NULL OR last_heartbeat < datetime('now', '-30 minutes'))
    """)
    for row in stale:
        await db_execute(
            "UPDATE bulk_jobs SET status = 'interrupted' WHERE id = ?",
            (row["id"],),
        )
        log.warning("migration.stale_job_interrupted", job_id=row["id"])
    if stale:
        log.info("migration.stale_jobs_cleaned", count=len(stale))
```

- [ ] **Step 2: Add heartbeat update to BulkJob**

In `core/bulk_worker.py`, in `BulkJob.run()` method, add heartbeat tracking. Near the top of the run loop:

```python
self._last_heartbeat_time = _time.time()
```

Inside the worker loop (or at the start of each iteration in `run()`), add:

```python
if _time.time() - self._last_heartbeat_time > 60:
    await db_execute(
        "UPDATE bulk_jobs SET last_heartbeat = datetime('now') WHERE id = ?",
        (self.job_id,),
    )
    self._last_heartbeat_time = _time.time()
```

- [ ] **Step 3: Verify with py_compile**

Run: `python -m py_compile core/db/migrations.py && python -m py_compile core/bulk_worker.py`
Expected: No output

- [ ] **Step 4: Commit**

```bash
git add core/db/migrations.py core/bulk_worker.py
git commit -m "feat: stale job detection with 60s heartbeat + startup cleanup

Bulk workers update last_heartbeat every 60s. On startup, jobs
with status='running' and heartbeat > 30 min old are marked
'interrupted'."
```

---

## WAVE 4 — Final Integration

---

### Task 19: markitdown Validation Utility [depends: Task 6]

**Files:**
- Create: `core/validation/__init__.py`
- Create: `core/validation/markitdown_compare.py`

- [ ] **Step 1: Create the validation package**

```python
# core/validation/__init__.py
```

```python
# core/validation/markitdown_compare.py
"""
Compare MarkFlow conversion output against Microsoft markitdown.

NOT in the hot path. Used for:
- Manual validation: python -m core.validation.markitdown_compare <file>
- Edge case detection during development
"""

import re
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


def _count_markdown_headings(text: str) -> int:
    return len(re.findall(r"^#{1,6}\s", text, re.MULTILINE))


def _count_markdown_tables(text: str) -> int:
    return len(re.findall(r"^\|.*\|$", text, re.MULTILINE)) // 2  # header + separator = 1 table


def compare_with_markitdown(file_path: str | Path) -> dict:
    """Run markitdown and compare against MarkFlow structurally."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return {"error": "markitdown not installed"}

    file_path = Path(file_path)
    if not file_path.exists():
        return {"error": f"File not found: {file_path}"}

    md = MarkItDown()
    result = md.convert(str(file_path))
    markitdown_text = result.text_content or ""

    return {
        "file": str(file_path),
        "markitdown_headings": _count_markdown_headings(markitdown_text),
        "markitdown_tables": _count_markdown_tables(markitdown_text),
        "markitdown_length": len(markitdown_text),
    }


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 2:
        print("Usage: python -m core.validation.markitdown_compare <file>")
        sys.exit(1)
    result = compare_with_markitdown(sys.argv[1])
    print(json.dumps(result, indent=2))
```

- [ ] **Step 2: Commit**

```bash
git add core/validation/__init__.py core/validation/markitdown_compare.py
git commit -m "feat: add markitdown validation comparison utility

CLI tool for comparing MarkFlow output against Microsoft markitdown.
Not in hot path — manual/development use only."
```

---

### Task 20: Startup Migrations + Version Bump [depends: ALL]

**Files:**
- Modify: `main.py:56-252`
- Modify: `core/version.py:3`

- [ ] **Step 1: Wire all startup migrations into lifespan**

In `main.py`, inside the `lifespan()` context manager, after `init_db()` (line ~68) and before scheduler start (line ~204), add:

```python
    # --- v0.23.0 migrations ---
    from core.db.pool import init_pool, shutdown_pool, get_pool
    from core.db.connection import get_db_path

    # Initialize connection pool (must be before any pool-dependent code)
    await init_pool(get_db_path())

    # Stale job cleanup (idempotent, no gate needed)
    from core.db.migrations import add_heartbeat_column, cleanup_stale_jobs
    await add_heartbeat_column()
    await cleanup_stale_jobs()

    # bulk_files dedup (one-time, gated)
    from core.db.migrations import run_bulk_files_dedup, run_bulk_files_schema_migration
    await run_bulk_files_dedup()
    await run_bulk_files_schema_migration()

    # Vision re-queue MIME failures (one-time)
    try:
        from core.db.connection import db_execute
        await db_execute("""
            UPDATE analysis_queue
            SET status = 'pending', retry_count = 0
            WHERE status = 'failed'
              AND error LIKE '%media type%'
        """)
    except Exception:
        pass

    # Lifecycle timer warnings
    from core.preferences_cache import get_cached_preference
    grace = await get_cached_preference("lifecycle_grace_period_hours", 36)
    retention = await get_cached_preference("lifecycle_trash_retention_days", 60)
    if isinstance(grace, (int, float)) and grace < 24:
        log.warning("lifecycle_timer_below_production",
                    setting="grace_period", current=grace, recommended=36)
    if isinstance(retention, (int, float)) and retention < 30:
        log.warning("lifecycle_timer_below_production",
                    setting="trash_retention", current=retention, recommended=60)

    # Recover files stuck in 'moving' status (crash recovery)
    from core.lifecycle_manager import recover_moving_files
    await recover_moving_files()
```

And in the shutdown section of lifespan (after yield):

```python
    # Shutdown connection pool
    await shutdown_pool()
```

- [ ] **Step 2: Set production lifecycle timers**

```python
    # Set production lifecycle timers if still at testing values
    from core.db.preferences import set_preference
    if isinstance(grace, (int, float)) and grace < 24:
        await set_preference("lifecycle_grace_period_hours", 36)
        log.info("lifecycle_timer_restored", setting="grace_period", value=36)
    if isinstance(retention, (int, float)) and retention < 30:
        await set_preference("lifecycle_trash_retention_days", 60)
        log.info("lifecycle_timer_restored", setting="trash_retention", value=60)
```

- [ ] **Step 3: Bump version**

In `core/version.py`, change:

```python
__version__ = "0.23.0"
```

- [ ] **Step 4: Verify all files compile**

Run: `python -m py_compile main.py && python -m py_compile core/version.py`
Expected: No output

- [ ] **Step 5: Commit**

```bash
git add main.py core/version.py
git commit -m "feat: v0.23.0 — startup migrations + version bump

Wires all v0.23.0 changes into lifespan: connection pool init,
stale job cleanup, bulk_files dedup, vision re-queue, lifecycle
timer restoration, crash recovery for stuck moves."
```

---

## Post-Implementation Verification

After all tasks are complete:

- [ ] **Full py_compile sweep**: `find . -name "*.py" -path "*/core/*" -exec python -m py_compile {} +`
- [ ] **Run test suite**: `python -m pytest tests/ -v --timeout=30`
- [ ] **Docker build**: `docker-compose build`
- [ ] **Start + health check**: `docker-compose up -d && sleep 20 && curl localhost:8000/api/health`
- [ ] **Verify pool metrics**: Check logs for `db_pool.initialized` message
- [ ] **Verify stats cache**: Hit `/api/pipeline/stats` twice rapidly — second should be <10ms
- [ ] **Verify polling**: Open browser, check Network tab shows 20s intervals
- [ ] **Verify vision MIME**: Check logs for `vision_adapter.describe_batch_failed` — should be zero new ones
- [ ] **Verify dedup**: Query `SELECT COUNT(*) FROM bulk_files` — should be ~88K (down from 276K)
- [ ] **Verify lifecycle timers**: `GET /api/preferences` — grace=36, retention=60
