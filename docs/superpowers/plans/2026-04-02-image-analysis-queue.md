# Image Analysis Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a decoupled LLM vision analysis queue for standalone image files — bulk jobs and the lifecycle scanner enqueue images; an APScheduler worker drains them in batches via a single multi-image API call; results are stored in the DB and indexed in Meilisearch; pipeline stage counts appear on the Status and Admin pages.

**Architecture:** New `analysis_queue` SQLite table (migration 19) holds one row per image file with `pending -> batched -> completed | failed` lifecycle. `VisionAdapter.describe_batch()` sends N images in a single API call. An APScheduler job in `core/analysis_worker.py` drains the queue every 5 minutes.

**Tech Stack:** aiosqlite, APScheduler, httpx, Meilisearch, Python 3.11+

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `core/db/schema.py` | Modify | Add `analysis_queue` table as migration 19 |
| `core/db/analysis.py` | Create | All DB helpers for `analysis_queue` |
| `core/db/preferences.py` | Modify | Add `analysis_batch_size` and `analysis_enabled` defaults |
| `core/vision_adapter.py` | Modify | Add `BatchImageResult` dataclass + `describe_batch()` |
| `core/analysis_worker.py` | Create | APScheduler drain job |
| `core/scheduler.py` | Modify | Register analysis worker (5-min interval), update job count |
| `core/bulk_worker.py` | Modify | Enqueue image files after successful conversion |
| `core/lifecycle_scanner.py` | Modify | Enqueue new/changed image files on discovery |
| `core/search_indexer.py` | Modify | Include description + extracted_text in document index |
| `api/routes/pipeline.py` | Modify | Add `GET /api/pipeline/stats` endpoint |
| `static/status.html` | Modify | Add pipeline stat strip above job cards |
| `static/admin.html` | Modify | Add Pipeline Funnel stats section |
| `docs/version-history.md` | Modify | Add v0.18.0 entry + bug log for source_path fix |
| `CLAUDE.md` | Modify | Update Current Status to v0.18.0 |

---

## Task 1: Schema migration + `core/db/analysis.py`

**Files:**
- Modify: `core/db/schema.py` (append to `_MIGRATIONS`)
- Create: `core/db/analysis.py`
- Test: `tests/test_analysis_db.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_analysis_db.py
import pytest
import pytest_asyncio
import os

@pytest_asyncio.fixture
async def db(tmp_path):
    os.environ["MARKFLOW_DB_PATH"] = str(tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield
    os.environ.pop("MARKFLOW_DB_PATH", None)

@pytest.mark.asyncio
async def test_enqueue_new_file(db):
    from core.db.analysis import enqueue_for_analysis, get_analysis_stats
    entry_id = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    assert entry_id is not None
    stats = await get_analysis_stats()
    assert stats["pending"] == 1

@pytest.mark.asyncio
async def test_enqueue_dedup_pending(db):
    from core.db.analysis import enqueue_for_analysis
    id1 = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    id2 = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    assert id1 == id2

@pytest.mark.asyncio
async def test_enqueue_skips_completed_same_hash(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results
    await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    rows = await claim_pending_batch(10)
    await write_batch_results([{
        "id": rows[0]["id"],
        "description": "A cat",
        "extracted_text": "",
        "provider_id": "anthropic",
        "model": "claude-3-opus-20240229",
    }])
    result = await enqueue_for_analysis("/nas/photos/cat.jpg", content_hash="abc123")
    assert result is None

@pytest.mark.asyncio
async def test_claim_batch(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch
    for i in range(5):
        await enqueue_for_analysis(f"/nas/photos/img{i}.jpg")
    rows = await claim_pending_batch(3)
    assert len(rows) == 3
    for r in rows:
        assert r["batch_id"] is not None

@pytest.mark.asyncio
async def test_write_results_completed(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results, get_analysis_stats
    await enqueue_for_analysis("/nas/photos/cat.jpg")
    rows = await claim_pending_batch(10)
    await write_batch_results([{
        "id": rows[0]["id"],
        "description": "A fluffy cat",
        "extracted_text": "No text",
        "provider_id": "anthropic",
        "model": "claude-3-opus-20240229",
    }])
    stats = await get_analysis_stats()
    assert stats["completed"] == 1
    assert stats["pending"] == 0

@pytest.mark.asyncio
async def test_write_results_failed_retry(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results, get_analysis_stats
    await enqueue_for_analysis("/nas/photos/cat.jpg")
    for _ in range(2):
        rows = await claim_pending_batch(10)
        await write_batch_results([{"id": rows[0]["id"], "error": "timeout"}])
    stats = await get_analysis_stats()
    assert stats["pending"] == 1
    assert stats["failed"] == 0

@pytest.mark.asyncio
async def test_write_results_failed_exhausted(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, write_batch_results, get_analysis_stats
    await enqueue_for_analysis("/nas/photos/cat.jpg")
    for _ in range(3):
        rows = await claim_pending_batch(10)
        if not rows:
            break
        await write_batch_results([{"id": rows[0]["id"], "error": "timeout"}])
    stats = await get_analysis_stats()
    assert stats["failed"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_analysis_db.py -v 2>&1 | head -40
```
Expected: `ModuleNotFoundError: No module named 'core.db.analysis'`

- [ ] **Step 3: Add migration 19 to `core/db/schema.py`**

Append after the `(18, "Add skip_reason to bulk_files", ...)` entry in `_MIGRATIONS`:

```python
    (19, "Image analysis queue", [
        """CREATE TABLE IF NOT EXISTS analysis_queue (
            id             TEXT PRIMARY KEY,
            source_path    TEXT NOT NULL,
            file_category  TEXT NOT NULL DEFAULT 'image',
            job_id         TEXT,
            scan_run_id    TEXT,
            enqueued_at    TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending',
            batch_id       TEXT,
            batched_at     TEXT,
            analyzed_at    TEXT,
            description    TEXT,
            extracted_text TEXT,
            provider_id    TEXT,
            model          TEXT,
            error          TEXT,
            content_hash   TEXT,
            retry_count    INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_analysis_queue_status ON analysis_queue(status)",
        "CREATE INDEX IF NOT EXISTS idx_analysis_queue_source_path ON analysis_queue(source_path)",
    ]),
```

- [ ] **Step 4: Create `core/db/analysis.py`**

```python
"""
DB helpers for the analysis_queue table.

Status lifecycle: pending -> batched -> completed | failed
Retry logic: failed rows with retry_count < 3 reset to pending on next claim cycle.
"""

import uuid
from typing import Any

from core.db.connection import db_fetch_one, db_fetch_all, get_db, now_iso

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".eps"}


def is_image_extension(ext: str) -> bool:
    """Return True if ext (with or without leading dot) is a supported image format."""
    return ("." + ext.lstrip(".")).lower() in _IMAGE_EXTENSIONS


async def enqueue_for_analysis(
    source_path: str,
    content_hash: str | None = None,
    job_id: str | None = None,
    scan_run_id: str | None = None,
) -> str | None:
    """
    Enqueue an image file for LLM analysis. Returns entry id or None if skipped.

    Skip conditions:
    - status=completed with same content_hash
    - status=failed with retry_count >= 3 and same content_hash
    If status=pending/batched, returns existing id (no duplicate).
    If content changed (different hash), re-queues unconditionally.
    """
    existing = await db_fetch_one(
        "SELECT id, status, content_hash, retry_count FROM analysis_queue WHERE source_path = ?",
        (source_path,),
    )

    if existing:
        status = existing["status"]
        existing_hash = existing["content_hash"]
        retry_count = existing["retry_count"] or 0

        if status == "completed":
            if not content_hash or existing_hash == content_hash:
                return None
        elif status in ("pending", "batched"):
            return existing["id"]
        elif status == "failed" and retry_count >= 3:
            if not content_hash or existing_hash == content_hash:
                return None

    entry_id = existing["id"] if existing else uuid.uuid4().hex
    now = now_iso()

    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO analysis_queue
               (id, source_path, file_category, job_id, scan_run_id, enqueued_at,
                status, content_hash, retry_count)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status = 'pending',
                 content_hash = excluded.content_hash,
                 job_id = excluded.job_id,
                 scan_run_id = excluded.scan_run_id,
                 enqueued_at = excluded.enqueued_at,
                 batch_id = NULL,
                 batched_at = NULL,
                 analyzed_at = NULL,
                 description = NULL,
                 extracted_text = NULL,
                 error = NULL,
                 retry_count = 0""",
            (entry_id, source_path, "image", job_id, scan_run_id,
             now, "pending", content_hash, 0),
        )
        await conn.commit()
    return entry_id


async def claim_pending_batch(batch_size: int = 10) -> list[dict[str, Any]]:
    """
    Atomically claim up to batch_size pending rows, marking them 'batched'.
    Returns claimed rows, each with batch_id populated.
    """
    batch_id = uuid.uuid4().hex
    now = now_iso()

    async with get_db() as conn:
        async with conn.execute(
            """SELECT id, source_path, content_hash FROM analysis_queue
               WHERE status = 'pending'
               ORDER BY enqueued_at ASC
               LIMIT ?""",
            (batch_size,),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

        if not rows:
            return []

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        await conn.execute(
            f"""UPDATE analysis_queue
                SET status = 'batched', batch_id = ?, batched_at = ?
                WHERE id IN ({placeholders})""",
            [batch_id, now] + ids,
        )
        await conn.commit()

    for row in rows:
        row["batch_id"] = batch_id
    return rows


async def write_batch_results(results: list[dict[str, Any]]) -> None:
    """
    Write analysis results back to analysis_queue.

    Each result dict must have 'id' and either:
    - 'error': str  -> failure: increment retry_count, reset to pending if < 3
    - 'description', 'extracted_text', 'provider_id', 'model'  -> success
    """
    now = now_iso()
    async with get_db() as conn:
        for r in results:
            if r.get("error"):
                await conn.execute(
                    """UPDATE analysis_queue
                       SET status = CASE WHEN retry_count + 1 < 3 THEN 'pending' ELSE 'failed' END,
                           retry_count = retry_count + 1,
                           error = ?,
                           batch_id = NULL,
                           batched_at = NULL
                       WHERE id = ?""",
                    (r["error"], r["id"]),
                )
            else:
                await conn.execute(
                    """UPDATE analysis_queue
                       SET status = 'completed',
                           analyzed_at = ?,
                           description = ?,
                           extracted_text = ?,
                           provider_id = ?,
                           model = ?
                       WHERE id = ?""",
                    (
                        now,
                        r.get("description", ""),
                        r.get("extracted_text", ""),
                        r.get("provider_id"),
                        r.get("model"),
                        r["id"],
                    ),
                )
        await conn.commit()


async def get_analysis_stats() -> dict[str, int]:
    """Return count per status in analysis_queue."""
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) AS cnt FROM analysis_queue GROUP BY status"
    )
    stats: dict[str, int] = {"pending": 0, "batched": 0, "completed": 0, "failed": 0}
    for row in rows:
        s = row["status"]
        if s in stats:
            stats[s] = row["cnt"]
    return stats


async def get_analysis_result(source_path: str) -> dict[str, Any] | None:
    """Return completed analysis row for a given source_path, or None."""
    return await db_fetch_one(
        "SELECT * FROM analysis_queue WHERE source_path = ? AND status = 'completed'",
        (source_path,),
    )
```

- [ ] **Step 5: Run tests**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_analysis_db.py -v
```
Expected: all 7 tests pass

- [ ] **Step 6: Commit**

```bash
cd /opt/doc-conversion-2026
git add core/db/schema.py core/db/analysis.py tests/test_analysis_db.py
git commit -m "feat: analysis_queue table (migration 19) + DB helpers"
```

---

## Task 2: `VisionAdapter.describe_batch()`

**Files:**
- Modify: `core/vision_adapter.py`
- Test: `tests/test_vision_adapter_batch.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_vision_adapter_batch.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

@pytest.mark.asyncio
async def test_describe_batch_returns_one_result_per_image(tmp_path):
    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": json.dumps([
            {"description": "A white rectangle", "extracted_text": ""},
            {"description": "Another white rectangle", "extracted_text": ""},
        ])}]
    }
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from core.vision_adapter import VisionAdapter
        adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
        results = await adapter.describe_batch([img1, img2])

    assert len(results) == 2
    assert results[0].index == 0
    assert results[1].index == 1
    assert "rectangle" in results[0].description

@pytest.mark.asyncio
async def test_describe_batch_empty():
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
    results = await adapter.describe_batch([])
    assert results == []

@pytest.mark.asyncio
async def test_describe_batch_unsupported_provider(tmp_path):
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "custom", "api_key": "k", "model": "m", "api_base_url": ""})
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n" + b"\x00" * 10)
    results = await adapter.describe_batch([img])
    assert len(results) == 1
    assert results[0].error is not None

def test_parse_batch_response_valid_json():
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
    raw = '[{"description": "cat", "extracted_text": "hello"}]'
    parsed = adapter._parse_batch_response(raw, 1)
    assert parsed[0]["description"] == "cat"

def test_parse_batch_response_json_in_prose():
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
    raw = 'Here is the result: [{"description": "cat", "extracted_text": ""}]'
    parsed = adapter._parse_batch_response(raw, 1)
    assert parsed[0]["description"] == "cat"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_vision_adapter_batch.py -v 2>&1 | head -20
```
Expected: `AttributeError: 'VisionAdapter' object has no attribute 'describe_batch'`

- [ ] **Step 3: Add `BatchImageResult` dataclass to `core/vision_adapter.py`**

Add after the `FrameDescription` dataclass (around line 27):

```python
@dataclass
class BatchImageResult:
    index: int
    description: str
    extracted_text: str
    error: str | None = None
```

- [ ] **Step 4: Add `describe_batch()` and helpers to `VisionAdapter` class**

Add after `describe_frame()` method:

```python
    async def describe_batch(
        self, image_paths: list[Path], prompt: str | None = None
    ) -> list["BatchImageResult"]:
        """
        Describe multiple images in a single API call.
        Returns one BatchImageResult per input path, in input order.
        Never raises — all exceptions captured in BatchImageResult.error.
        """
        if not image_paths:
            return []

        if not self.supports_vision():
            return [
                BatchImageResult(
                    index=i, description="", extracted_text="",
                    error=f"[vision unavailable -- {self._provider} does not support image input]",
                )
                for i in range(len(image_paths))
            ]

        if prompt is None:
            prompt = (
                "For each image provided (in order), return a JSON array where each element has:\n"
                "  'description': a factual description of the image content (objects, people, "
                "scenes, charts, diagrams, any visible text). Be concise.\n"
                "  'extracted_text': any legible text found in the image verbatim. "
                "Empty string if none.\n"
                "Return ONLY the JSON array with no prose before or after."
            )

        try:
            if self._provider == "anthropic":
                return await self._batch_anthropic(image_paths, prompt)
            elif self._provider == "openai":
                return await self._batch_openai(image_paths, prompt)
            elif self._provider == "gemini":
                return await self._batch_gemini(image_paths, prompt)
            elif self._provider == "ollama":
                return await self._batch_ollama(image_paths, prompt)
            else:
                return [
                    BatchImageResult(
                        index=i, description="", extracted_text="",
                        error=f"[vision unavailable -- unknown provider {self._provider}]",
                    )
                    for i in range(len(image_paths))
                ]
        except Exception as exc:
            log.error(
                "vision_adapter.describe_batch_failed",
                provider=self._provider,
                count=len(image_paths),
                error=str(exc),
            )
            return [
                BatchImageResult(index=i, description="", extracted_text="", error=str(exc))
                for i in range(len(image_paths))
            ]

    def _parse_batch_response(self, text: str, count: int) -> list[dict]:
        """Parse JSON array from LLM response. Extracts from prose if needed."""
        import json
        import re

        text = text.strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        log.warning(
            "vision_adapter.batch_parse_failed",
            provider=self._provider,
            response_preview=text[:200],
        )
        return [
            {"description": "", "extracted_text": "", "error": "failed to parse LLM response"}
            for _ in range(count)
        ]

    async def _batch_anthropic(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        base = self._base_url or "https://api.anthropic.com"
        content: list[dict] = []
        for path in image_paths:
            image_b64 = base64.b64encode(path.read_bytes()).decode()
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": image_b64},
            })
        content.append({"type": "text", "text": prompt})

        timeout = max(_TIMEOUT, _TIMEOUT * len(image_paths) / 3)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 400 * len(image_paths),
                    "messages": [{"role": "user", "content": content}],
                },
            )
            resp.raise_for_status()
            text = "".join(
                block.get("text", "")
                for block in resp.json().get("content", [])
                if block.get("type") == "text"
            )

        parsed = self._parse_batch_response(text, len(image_paths))
        return [
            BatchImageResult(
                index=i,
                description=item.get("description", ""),
                extracted_text=item.get("extracted_text", ""),
                error=item.get("error"),
            )
            for i, item in enumerate(parsed)
        ]

    async def _batch_openai(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for path in image_paths:
            image_b64 = base64.b64encode(path.read_bytes()).decode()
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}", "detail": "low"},
            })

        timeout = max(_TIMEOUT, _TIMEOUT * len(image_paths) / 3)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={
                    "model": self._model or "gpt-4o",
                    "max_tokens": 400 * len(image_paths),
                    "messages": [{"role": "user", "content": content}],
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]

        parsed = self._parse_batch_response(text, len(image_paths))
        return [
            BatchImageResult(
                index=i,
                description=item.get("description", ""),
                extracted_text=item.get("extracted_text", ""),
                error=item.get("error"),
            )
            for i, item in enumerate(parsed)
        ]

    async def _batch_gemini(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        base = self._base_url or "https://generativelanguage.googleapis.com"
        parts: list[dict] = [{"text": prompt}]
        for path in image_paths:
            image_b64 = base64.b64encode(path.read_bytes()).decode()
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})

        timeout = max(_TIMEOUT, _TIMEOUT * len(image_paths) / 3)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/v1beta/models/{self._model}:generateContent",
                params={"key": self._api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": parts}],
                    "generationConfig": {"maxOutputTokens": 400 * len(image_paths)},
                },
            )
            resp.raise_for_status()
            text = "".join(
                part.get("text", "")
                for candidate in resp.json().get("candidates", [])
                for part in candidate.get("content", {}).get("parts", [])
            )

        parsed = self._parse_batch_response(text, len(image_paths))
        return [
            BatchImageResult(
                index=i,
                description=item.get("description", ""),
                extracted_text=item.get("extracted_text", ""),
                error=item.get("error"),
            )
            for i, item in enumerate(parsed)
        ]

    async def _batch_ollama(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        """Try multi-image batch; fall back to sequential describe_frame() calls if model rejects it."""
        base = self._base_url or "http://localhost:11434"
        images_b64 = [base64.b64encode(p.read_bytes()).decode() for p in image_paths]

        try:
            async with httpx.AsyncClient(timeout=120.0 * len(image_paths)) as client:
                resp = await client.post(
                    f"{base}/api/generate",
                    json={
                        "model": self._model or "llava",
                        "prompt": prompt,
                        "images": images_b64,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                text = resp.json().get("response", "").strip()

            parsed = self._parse_batch_response(text, len(image_paths))
            results = [
                BatchImageResult(
                    index=i,
                    description=item.get("description", ""),
                    extracted_text=item.get("extracted_text", ""),
                    error=item.get("error"),
                )
                for i, item in enumerate(parsed)
            ]
            if all(r.error for r in results):
                raise ValueError("all results failed — falling back to sequential")
            return results

        except Exception:
            log.info("vision_adapter.ollama_batch_fallback_sequential", count=len(image_paths))
            out = []
            for i, path in enumerate(image_paths):
                fd = await self.describe_frame(path, prompt, scene_index=i)
                out.append(BatchImageResult(
                    index=i,
                    description=fd.description,
                    extracted_text="",
                    error=fd.error,
                ))
            return out
```

- [ ] **Step 5: Run tests**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_vision_adapter_batch.py -v
```
Expected: all 5 tests pass

- [ ] **Step 6: Commit**

```bash
cd /opt/doc-conversion-2026
git add core/vision_adapter.py tests/test_vision_adapter_batch.py
git commit -m "feat: VisionAdapter.describe_batch() for multi-image single API call"
```

---

## Task 3: `core/analysis_worker.py` + preferences + scheduler

**Files:**
- Modify: `core/db/preferences.py`
- Create: `core/analysis_worker.py`
- Modify: `core/scheduler.py`
- Test: `tests/test_analysis_worker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_analysis_worker.py
import pytest
import pytest_asyncio
import os
from unittest.mock import AsyncMock, patch, MagicMock

@pytest_asyncio.fixture
async def db(tmp_path):
    os.environ["MARKFLOW_DB_PATH"] = str(tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield
    os.environ.pop("MARKFLOW_DB_PATH", None)

@pytest.mark.asyncio
async def test_drain_skips_when_no_provider(db):
    with patch("core.analysis_worker.get_active_provider", new_callable=AsyncMock, return_value=None), \
         patch("core.analysis_worker.get_preference", new_callable=AsyncMock, return_value="true"), \
         patch("core.analysis_worker.get_all_active_jobs", new_callable=AsyncMock, return_value=[]):
        from core.analysis_worker import run_analysis_drain
        await run_analysis_drain()  # should not raise

@pytest.mark.asyncio
async def test_drain_skips_when_disabled(db):
    with patch("core.analysis_worker.get_preference", new_callable=AsyncMock, return_value="false"):
        from core.analysis_worker import run_analysis_drain
        await run_analysis_drain()

@pytest.mark.asyncio
async def test_drain_processes_pending_images(db, tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    from core.db.analysis import enqueue_for_analysis, get_analysis_stats
    await enqueue_for_analysis(str(img))

    mock_result = MagicMock()
    mock_result.description = "A test image"
    mock_result.extracted_text = "Hello"
    mock_result.error = None

    provider = {"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""}

    with patch("core.analysis_worker.get_active_provider", new_callable=AsyncMock, return_value=provider), \
         patch("core.analysis_worker.get_preference", new_callable=AsyncMock, return_value="10"), \
         patch("core.analysis_worker.get_all_active_jobs", new_callable=AsyncMock, return_value=[]), \
         patch("core.analysis_worker._reindex_completed", new_callable=AsyncMock), \
         patch("core.vision_adapter.VisionAdapter.describe_batch",
               new_callable=AsyncMock, return_value=[mock_result]):
        from core.analysis_worker import run_analysis_drain
        await run_analysis_drain()

    stats = await get_analysis_stats()
    assert stats["completed"] == 1
    assert stats["pending"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_analysis_worker.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'core.analysis_worker'`

- [ ] **Step 3: Add preferences to `core/db/preferences.py`**

Find the `# Cloud file prefetch (v0.15.1)` comment block. Add before it:

```python
    # Image analysis queue (v0.18.0)
    "analysis_enabled": "true",
    "analysis_batch_size": "10",
```

- [ ] **Step 4: Create `core/analysis_worker.py`**

```python
"""
LLM image analysis queue worker.

APScheduler job (5-min interval). Each drain cycle:
  1. Check analysis_enabled preference
  2. Yield to active bulk jobs
  3. Verify active LLM provider supports vision
  4. Claim up to analysis_batch_size pending rows
  5. Call VisionAdapter.describe_batch() — one API call for all images
  6. Write results; re-index completed files in Meilisearch
"""

from pathlib import Path

import structlog

from core.database import get_active_provider, get_preference
from core.db.analysis import claim_pending_batch, write_batch_results

log = structlog.get_logger(__name__)


async def run_analysis_drain() -> None:
    """Drain one batch from analysis_queue. Called by APScheduler every 5 minutes."""
    try:
        enabled = await get_preference("analysis_enabled") or "true"
        if enabled == "false":
            log.debug("analysis_worker.disabled")
            return

        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running") for j in active):
            log.debug("analysis_worker.skipped_bulk_job_active")
            return

        provider_config = await get_active_provider()
        if not provider_config:
            log.debug("analysis_worker.no_active_provider")
            return

        from core.vision_adapter import VisionAdapter
        adapter = VisionAdapter(provider_config)
        if not adapter.supports_vision():
            log.debug("analysis_worker.provider_no_vision", provider=provider_config.get("provider"))
            return

        batch_size_str = await get_preference("analysis_batch_size") or "10"
        batch_size = max(1, min(int(batch_size_str), 20))
        rows = await claim_pending_batch(batch_size)
        if not rows:
            return

        log.info(
            "analysis_worker.batch_start",
            count=len(rows),
            provider=provider_config.get("provider"),
            model=provider_config.get("model"),
        )

        # Skip files no longer on disk
        valid_rows, skip_results = [], []
        for row in rows:
            if Path(row["source_path"]).exists():
                valid_rows.append(row)
            else:
                skip_results.append({"id": row["id"], "error": "source file not found on disk"})
        if skip_results:
            await write_batch_results(skip_results)
        if not valid_rows:
            return

        image_paths = [Path(r["source_path"]) for r in valid_rows]
        descriptions = await adapter.describe_batch(image_paths)

        results = []
        for i, row in enumerate(valid_rows):
            desc = descriptions[i] if i < len(descriptions) else None
            if desc and not desc.error:
                results.append({
                    "id": row["id"],
                    "description": desc.description,
                    "extracted_text": desc.extracted_text,
                    "provider_id": provider_config.get("provider"),
                    "model": provider_config.get("model"),
                })
            else:
                results.append({
                    "id": row["id"],
                    "error": (desc.error if desc else "no result returned"),
                })

        await write_batch_results(results)

        completed = sum(1 for r in results if not r.get("error"))
        failed = sum(1 for r in results if r.get("error"))
        log.info("analysis_worker.batch_complete", completed=completed, failed=failed)

        if completed > 0:
            await _reindex_completed(valid_rows, results)

    except Exception as exc:
        log.error("analysis_worker.drain_failed", error=str(exc))


async def _reindex_completed(rows: list[dict], results: list[dict]) -> None:
    """Re-index Meilisearch for files whose analysis just completed."""
    try:
        from core.search_indexer import get_search_indexer
        from core.db.connection import db_fetch_one

        indexer = get_search_indexer()
        if not indexer:
            return

        completed_paths = {
            rows[i]["source_path"]
            for i, r in enumerate(results)
            if not r.get("error")
        }

        for source_path in completed_paths:
            try:
                row = await db_fetch_one(
                    "SELECT output_path FROM source_files WHERE source_path = ?",
                    (source_path,),
                )
                if row and row.get("output_path"):
                    md_path = Path(row["output_path"])
                    if md_path.exists():
                        await indexer.index_document(md_path)
            except Exception as exc:
                log.warning("analysis_worker.reindex_failed", path=source_path, error=str(exc))

    except Exception as exc:
        log.warning("analysis_worker.reindex_error", error=str(exc))
```

- [ ] **Step 5: Register in `core/scheduler.py`**

In `start_scheduler()`, immediately before `scheduler.start()`, add:

```python
    # v0.18.0: Image analysis queue drain — every 5 minutes
    from core.analysis_worker import run_analysis_drain
    scheduler.add_job(
        run_analysis_drain,
        trigger=IntervalTrigger(minutes=5),
        id="analysis_drain",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
```

Update job count: change `log.info("scheduler.started", jobs=13)` to `jobs=14`.

Add to `job_names` dict in `get_scheduler_status()`:
```python
        "analysis_drain": "analysis_drain_next",
```

- [ ] **Step 6: Run tests**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_analysis_worker.py -v
```
Expected: all 3 tests pass

- [ ] **Step 7: Commit**

```bash
cd /opt/doc-conversion-2026
git add core/db/preferences.py core/analysis_worker.py core/scheduler.py tests/test_analysis_worker.py
git commit -m "feat: analysis drain worker + APScheduler registration (5-min interval)"
```

---

## Task 4: Bulk worker feed point

**Files:**
- Modify: `core/bulk_worker.py`
- Test: `tests/test_bulk_worker_analysis_enqueue.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_bulk_worker_analysis_enqueue.py
import pytest
from pathlib import Path

def test_should_enqueue_for_analysis_image_extensions():
    from core.bulk_worker import _should_enqueue_for_analysis
    assert _should_enqueue_for_analysis(Path("photo.jpg")) is True
    assert _should_enqueue_for_analysis(Path("image.PNG")) is True
    assert _should_enqueue_for_analysis(Path("scan.tif")) is True
    assert _should_enqueue_for_analysis(Path("report.pdf")) is False
    assert _should_enqueue_for_analysis(Path("doc.docx")) is False
    assert _should_enqueue_for_analysis(Path("no_ext")) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_bulk_worker_analysis_enqueue.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name '_should_enqueue_for_analysis'`

- [ ] **Step 3: Add helper and enqueue call to `core/bulk_worker.py`**

Near the top of `core/bulk_worker.py` (after existing module-level imports/constants), add:

```python
_IMAGE_EXTENSIONS_BW = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".eps"}


def _should_enqueue_for_analysis(source_path: Path) -> bool:
    """Return True if source_path is an image file eligible for LLM vision analysis."""
    return source_path.suffix.lower() in _IMAGE_EXTENSIONS_BW
```

In `_process_convertible`, immediately after the `except Exception as exc: log.warning("bulk_meili_index_fail", ...)` block (end of the `if result.status == "success":` branch), add:

```python
            # Enqueue image files for LLM vision analysis
            if _should_enqueue_for_analysis(source_path):
                try:
                    from core.db.analysis import enqueue_for_analysis
                    await enqueue_for_analysis(
                        source_path=str(source_path),
                        content_hash=file_dict.get("content_hash"),
                        job_id=self.job_id,
                    )
                except Exception as exc:
                    log.warning(
                        "bulk_worker.analysis_enqueue_failed",
                        path=str(source_path),
                        error=str(exc),
                    )
```

- [ ] **Step 4: Run tests**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_bulk_worker_analysis_enqueue.py -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd /opt/doc-conversion-2026
git add core/bulk_worker.py tests/test_bulk_worker_analysis_enqueue.py
git commit -m "feat: enqueue image files for LLM analysis after bulk conversion"
```

---

## Task 5: Lifecycle scanner feed point

**Files:**
- Modify: `core/lifecycle_scanner.py`
- Test: `tests/test_lifecycle_analysis_enqueue.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_lifecycle_analysis_enqueue.py
import pytest
import os
from unittest.mock import AsyncMock, patch
from pathlib import Path

@pytest_asyncio_fixture_or_setup
async def db(tmp_path):
    os.environ["MARKFLOW_DB_PATH"] = str(tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield
    os.environ.pop("MARKFLOW_DB_PATH", None)

import pytest_asyncio

@pytest_asyncio.fixture
async def db(tmp_path):
    os.environ["MARKFLOW_DB_PATH"] = str(tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield
    os.environ.pop("MARKFLOW_DB_PATH", None)

@pytest.mark.asyncio
async def test_new_image_enqueued(db, tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    enqueue_calls = []

    async def mock_enqueue(source_path, **kwargs):
        enqueue_calls.append(source_path)
        return "fake-id"

    with patch("core.lifecycle_scanner.enqueue_image_for_analysis", side_effect=mock_enqueue):
        from core.lifecycle_scanner import _process_file
        await _process_file(
            file_path=img,
            path_str=str(img),
            ext=".jpg",
            mtime=img.stat().st_mtime,
            size=img.stat().st_size,
            job_id="test-job",
            scan_run_id="test-scan",
            counters={"files_new": 0, "files_modified": 0, "files_restored": 0,
                      "errors": 0, "files_scanned": 0},
        )

    assert str(img) in enqueue_calls

@pytest.mark.asyncio
async def test_pdf_not_enqueued(db, tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4" + b"\x00" * 100)

    enqueue_calls = []

    async def mock_enqueue(source_path, **kwargs):
        enqueue_calls.append(source_path)
        return "fake-id"

    with patch("core.lifecycle_scanner.enqueue_image_for_analysis", side_effect=mock_enqueue):
        from core.lifecycle_scanner import _process_file
        await _process_file(
            file_path=pdf,
            path_str=str(pdf),
            ext=".pdf",
            mtime=pdf.stat().st_mtime,
            size=pdf.stat().st_size,
            job_id="test-job",
            scan_run_id="test-scan",
            counters={"files_new": 0, "files_modified": 0, "files_restored": 0,
                      "errors": 0, "files_scanned": 0},
        )

    assert enqueue_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_lifecycle_analysis_enqueue.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'enqueue_image_for_analysis'`

- [ ] **Step 3: Modify `core/lifecycle_scanner.py`**

Add to the imports at the top of the file:

```python
from core.db.analysis import enqueue_for_analysis as enqueue_image_for_analysis, _IMAGE_EXTENSIONS as _LIFECYCLE_IMAGE_EXTS
```

In `_process_file`, after `counters["files_new"] += 1` (new file branch), add before `return`:

```python
        if ext.lower() in _LIFECYCLE_IMAGE_EXTS:
            try:
                await enqueue_image_for_analysis(
                    source_path=path_str,
                    content_hash=content_hash,
                    scan_run_id=scan_run_id,
                )
            except Exception as exc:
                log.warning("lifecycle_scanner.analysis_enqueue_failed",
                            path=path_str, error=str(exc))
```

After `counters["files_modified"] += 1` (modified file branch), add:

```python
        if ext.lower() in _LIFECYCLE_IMAGE_EXTS:
            try:
                await enqueue_image_for_analysis(
                    source_path=path_str,
                    content_hash=content_hash,
                    scan_run_id=scan_run_id,
                )
            except Exception as exc:
                log.warning("lifecycle_scanner.analysis_enqueue_failed",
                            path=path_str, error=str(exc))
```

- [ ] **Step 4: Run tests**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_lifecycle_analysis_enqueue.py -v
```
Expected: both tests pass

- [ ] **Step 5: Commit**

```bash
cd /opt/doc-conversion-2026
git add core/lifecycle_scanner.py tests/test_lifecycle_analysis_enqueue.py
git commit -m "feat: lifecycle scanner enqueues new/changed image files for LLM analysis"
```

---

## Task 6: Search indexer — include analysis results

**Files:**
- Modify: `core/search_indexer.py`
- Test: `tests/test_search_indexer_analysis.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_search_indexer_analysis.py
import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

@pytest.mark.asyncio
async def test_index_document_includes_analysis_results(tmp_path):
    os.environ["MARKFLOW_DB_PATH"] = str(tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()

    md_file = tmp_path / "photo.md"
    md_file.write_text("# photo.jpg\n\nFormat: JPEG\n", encoding="utf-8")

    analysis_row = {
        "description": "A sunset over the ocean",
        "extracted_text": "No Trespassing",
        "status": "completed",
    }

    indexed_docs = []

    async def mock_add_docs(index, docs):
        indexed_docs.extend(docs)
        return "task-1"

    with patch("core.db.analysis.get_analysis_result",
               new_callable=AsyncMock, return_value=analysis_row), \
         patch("core.db.connection.db_fetch_one",
               new_callable=AsyncMock, return_value={"source_path": "/nas/photo.jpg"}):
        from core.search_indexer import SearchIndexer
        indexer = SearchIndexer.__new__(SearchIndexer)
        indexer.client = MagicMock()
        indexer.client.add_documents = AsyncMock(side_effect=mock_add_docs)

        await indexer.index_document(md_file, "job-1")

    assert len(indexed_docs) == 1
    doc = indexed_docs[0]
    assert "sunset" in doc["content"]
    assert "No Trespassing" in doc["content"]

    os.environ.pop("MARKFLOW_DB_PATH", None)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_search_indexer_analysis.py -v 2>&1 | head -20
```
Expected: `AssertionError` — description not in content

- [ ] **Step 3: Modify `core/search_indexer.py` `index_document()` method**

In `index_document()`, after the `doc["is_flagged"] = is_flagged` assignment and before `task_uid = await self.client.add_documents(...)`, add:

```python
        # Augment content with LLM vision analysis results if available
        try:
            from core.db.analysis import get_analysis_result
            if source_path:
                analysis = await get_analysis_result(source_path)
                if analysis:
                    analysis_parts = []
                    if analysis.get("description"):
                        analysis_parts.append(analysis["description"])
                    if analysis.get("extracted_text"):
                        analysis_parts.append(analysis["extracted_text"])
                    if analysis_parts:
                        doc["content"] = (doc["content"] + "\n\n" + "\n".join(analysis_parts)).strip()
                        doc["content_preview"] = doc["content"][:500]
        except Exception:
            pass  # Non-critical — index without analysis results if lookup fails
```

- [ ] **Step 4: Run tests**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_search_indexer_analysis.py -v
```
Expected: test passes

- [ ] **Step 5: Commit**

```bash
cd /opt/doc-conversion-2026
git add core/search_indexer.py tests/test_search_indexer_analysis.py
git commit -m "feat: include LLM image analysis results in Meilisearch document index"
```

---

## Task 7: Pipeline stats API endpoint

**Files:**
- Modify: `api/routes/pipeline.py`
- Test: `tests/test_pipeline_stats.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pipeline_stats.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

@pytest.fixture
def client():
    with patch("api.routes.pipeline.get_pipeline_status", return_value={}), \
         patch("api.routes.pipeline.get_coordinator_status", return_value={}), \
         patch("api.routes.pipeline.db_fetch_one", new_callable=AsyncMock, return_value={"cnt": 42}), \
         patch("api.routes.pipeline.get_preference", new_callable=AsyncMock, return_value="true"), \
         patch("api.routes.pipeline.get_analysis_stats",
               new_callable=AsyncMock,
               return_value={"pending": 5, "batched": 2, "completed": 100, "failed": 1}), \
         patch("api.routes.pipeline.get_meili_client", return_value=None):
        from api.routes.pipeline import router
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)

def test_pipeline_stats_all_keys(client):
    resp = client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("scanned", "pending_conversion", "failed", "unrecognized",
                "pending_analysis", "batched_for_analysis", "analysis_failed", "in_search_index"):
        assert key in data, f"missing key: {key}"
    assert data["pending_analysis"] == 5
    assert data["batched_for_analysis"] == 2
    assert data["analysis_failed"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_pipeline_stats.py -v 2>&1 | head -20
```
Expected: `404` or `AttributeError` — no `/stats` route

- [ ] **Step 3: Add imports and `/stats` endpoint to `api/routes/pipeline.py`**

Add to existing imports at the top:

```python
from core.db.analysis import get_analysis_stats
from core.db.connection import db_fetch_one
from core.search_client import get_meili_client
```

Add after the `@router.get("/coordinator")` endpoint:

```python
@router.get("/stats")
async def pipeline_stats():
    """Pipeline funnel statistics across all processing stages."""
    import asyncio

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            return None

    async def _count(query: str) -> int:
        row = await db_fetch_one(query)
        return row["cnt"] if row else 0

    async def _count_search_index() -> int | None:
        client = get_meili_client()
        if not client:
            return None
        total = 0
        for index in ("documents", "adobe-files", "transcripts"):
            stats = await client.get_index_stats(index)
            total += stats.get("numberOfDocuments", 0)
        return total

    scanned, pending_conv, failed, unrecognized, analysis, search_count = await asyncio.gather(
        _safe(_count("SELECT COUNT(*) AS cnt FROM source_files WHERE lifecycle_status = 'active'")),
        _safe(_count("SELECT COUNT(*) AS cnt FROM bulk_files WHERE status = 'pending'")),
        _safe(_count("SELECT COUNT(*) AS cnt FROM bulk_files WHERE status = 'failed'")),
        _safe(_count("SELECT COUNT(*) AS cnt FROM bulk_files WHERE status = 'unrecognized'")),
        _safe(get_analysis_stats()),
        _safe(_count_search_index()),
    )

    analysis = analysis or {}

    return {
        "scanned": scanned or 0,
        "pending_conversion": pending_conv or 0,
        "failed": failed or 0,
        "unrecognized": unrecognized or 0,
        "pending_analysis": analysis.get("pending", 0),
        "batched_for_analysis": analysis.get("batched", 0),
        "analysis_failed": analysis.get("failed", 0),
        "in_search_index": search_count,
    }
```

- [ ] **Step 4: Run tests**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/test_pipeline_stats.py -v
```
Expected: test passes

- [ ] **Step 5: Smoke test endpoint**

```bash
curl -s http://localhost:8000/api/pipeline/stats | python3 -m json.tool
```
Expected: JSON with 8 keys

- [ ] **Step 6: Commit**

```bash
cd /opt/doc-conversion-2026
git add api/routes/pipeline.py tests/test_pipeline_stats.py
git commit -m "feat: GET /api/pipeline/stats — pipeline funnel counts"
```

---

## Task 8: Status page — pipeline stat strip

**Files:**
- Modify: `static/status.html`

- [ ] **Step 1: Add CSS for stat pills**

In `static/status.html`, find the `<style>` block (or `</style>` tag) and insert:

```css
      .stat-pill { display:inline-flex;align-items:center;padding:0.2rem 0.6rem;border-radius:999px;background:var(--bg-tertiary,#252540);color:var(--text-secondary,#aaa);white-space:nowrap;font-size:0.78rem; }
      .stat-pill--analysis { background:rgba(99,102,241,.15);color:#818cf8; }
      .stat-pill--batched   { background:rgba(245,158,11,.15);color:#fbbf24; }
      .stat-pill--afailed   { background:rgba(239,68,68,.15);color:#f87171; }
      .stat-pill--indexed   { background:rgba(34,197,94,.15);color:#4ade80; }
```

- [ ] **Step 2: Add stat strip HTML**

Find `<div id="jobs-container"` (or the first job-card container div). Insert before it:

```html
    <div id="pipeline-stats-strip" style="display:flex;flex-wrap:wrap;gap:0.5rem;margin:0.75rem 0 1rem 0;padding:0.75rem 1rem;background:var(--bg-secondary,#1a1a2e);border-radius:8px;">
      <span style="color:var(--text-muted,#888);align-self:center;margin-right:0.25rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;font-size:0.75rem;">Pipeline</span>
      <span class="stat-pill" id="ps-scanned">— scanned</span>
      <span class="stat-pill" id="ps-pending">— pending</span>
      <span class="stat-pill" id="ps-failed">— failed</span>
      <span class="stat-pill" id="ps-unrecognized">— unrecognized</span>
      <span class="stat-pill stat-pill--analysis" id="ps-panalysis">— pending analysis</span>
      <span class="stat-pill stat-pill--batched"   id="ps-batched">— batched</span>
      <span class="stat-pill stat-pill--afailed"   id="ps-afailed">— analysis failed</span>
      <span class="stat-pill stat-pill--indexed"   id="ps-indexed">— indexed</span>
    </div>
```

- [ ] **Step 3: Add JavaScript fetch function**

In the `<script>` block, add:

```javascript
    async function updatePipelineStats() {
      try {
        var d = await API.get('/api/pipeline/stats');
        var f = function(n) { return n == null ? '?' : n.toLocaleString(); };
        document.getElementById('ps-scanned').textContent    = f(d.scanned) + ' scanned';
        document.getElementById('ps-pending').textContent    = f(d.pending_conversion) + ' pending';
        document.getElementById('ps-failed').textContent     = f(d.failed) + ' failed';
        document.getElementById('ps-unrecognized').textContent = f(d.unrecognized) + ' unrecognized';
        document.getElementById('ps-panalysis').textContent  = f(d.pending_analysis) + ' pending analysis';
        document.getElementById('ps-batched').textContent    = f(d.batched_for_analysis) + ' batched';
        document.getElementById('ps-afailed').textContent    = f(d.analysis_failed) + ' analysis failed';
        document.getElementById('ps-indexed').textContent    = f(d.in_search_index) + ' indexed';
      } catch(e) { /* non-critical */ }
    }
```

Find where the page initializes (look for `refreshJobs()` or `loadJobs()` being called on load, or `window.onload`/`DOMContentLoaded`). Add `updatePipelineStats()` there. Also add it to whatever polling interval refreshes job cards.

- [ ] **Step 4: Verify**

Open `http://192.168.1.208:8000/status.html`. Confirm stat strip appears above job cards with 8 labeled counters.

- [ ] **Step 5: Commit**

```bash
cd /opt/doc-conversion-2026
git add static/status.html
git commit -m "feat: pipeline stat strip on status page"
```

---

## Task 9: Admin page — Pipeline Funnel section

**Files:**
- Modify: `static/admin.html`

- [ ] **Step 1: Add Pipeline Funnel card HTML**

In `static/admin.html`, find the stats cards section (look for existing cards like `id="bulk-files-stats"` or similar). After the last existing card, add:

```html
    <div class="stats-card">
      <h3 class="stats-card-title">Pipeline Funnel</h3>
      <div id="pipeline-funnel-body"><span class="spinner"></span> Loading...</div>
    </div>
```

- [ ] **Step 2: Add JavaScript fetch function**

In the `<script>` block, add:

```javascript
    async function loadPipelineFunnel() {
      var container = document.getElementById('pipeline-funnel-body');
      try {
        var d = await API.get('/api/pipeline/stats');
        var f = function(n) { return n == null ? 'N/A' : n.toLocaleString(); };
        var rows = [
          ['Scanned',              f(d.scanned)],
          ['Pending Conversion',   f(d.pending_conversion)],
          ['Failed',               f(d.failed)],
          ['Unrecognized',         f(d.unrecognized)],
          ['Pending Analysis',     f(d.pending_analysis)],
          ['Batched for Analysis', f(d.batched_for_analysis)],
          ['Analysis Failed',      f(d.analysis_failed)],
          ['In Search Index',      f(d.in_search_index)],
        ];
        var trs = rows.map(function(r) {
          return '<tr><td>' + r[0] + '</td><td style="text-align:right;font-weight:600">' + r[1] + '</td></tr>';
        }).join('');
        container.textContent = '';
        var table = document.createElement('table');
        table.className = 'stats-table';
        table.innerHTML = '<tbody>' + trs + '</tbody>';
        container.appendChild(table);
      } catch(e) {
        container.textContent = 'Failed to load pipeline stats';
      }
    }
```

Find the existing stats load function (look for `loadStats()` or where other admin cards are populated) and add a call to `loadPipelineFunnel()` there.

- [ ] **Step 3: Verify**

Open `http://192.168.1.208:8000/admin.html`. Confirm "Pipeline Funnel" card appears with 8 rows.

- [ ] **Step 4: Commit**

```bash
cd /opt/doc-conversion-2026
git add static/admin.html
git commit -m "feat: Pipeline Funnel stats card on admin page"
```

---

## Task 10: Docs, version bump, final push

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/version-history.md`

- [ ] **Step 1: Run full test suite**

```bash
cd /opt/doc-conversion-2026
docker compose exec markflow pytest tests/ -v --tb=short 2>&1 | tail -40
```
Expected: new tests pass; no regressions

- [ ] **Step 2: Rebuild and smoke test**

```bash
cd /opt/doc-conversion-2026
docker compose build && docker compose up -d
sleep 5
curl -s http://localhost:8000/api/health | python3 -m json.tool | grep -E '"ok"|"version"'
curl -s http://localhost:8000/api/pipeline/stats | python3 -m json.tool
docker compose exec markflow python3 -c "
import asyncio, sys
sys.path.insert(0, '/app')
async def check():
    from core.db.analysis import get_analysis_stats
    print(await get_analysis_stats())
asyncio.run(check())
"
```
Expected: health ok, pipeline stats returns 8 keys, analysis_queue accessible

- [ ] **Step 3: Update `CLAUDE.md`**

Replace the `## Current Status — v0.17.7` line with:

```markdown
## Current Status — v0.18.0

v0.18.0: Image analysis queue + pipeline stats. Standalone image files (JPG, PNG,
TIFF, BMP, GIF, EPS) are now enqueued for LLM vision analysis by the bulk worker
and lifecycle scanner. A new APScheduler job (`core/analysis_worker.py`, 5-min
interval) drains the queue in batches via `VisionAdapter.describe_batch()` — a
single multi-image API call per batch. Results (description + extracted text) stored
in `analysis_queue` (migration 19) and included in Meilisearch. Pipeline stage
counts exposed via `GET /api/pipeline/stats` and shown on Status and Admin pages.

Bug fixed: `lifecycle_scanner.py:924` called `BulkJob(source_path=...)` but
`BulkJob.__init__` expects `source_paths=` (plural). Auto-conversion via lifecycle
scanner was silently broken since v0.17.x. Fixed.

GPU staleness fix: `gpu_detector.py` now validates `worker.lock` presence and
timestamp freshness before trusting `worker_capabilities.json`. Hashcat worker
writes a 2-minute heartbeat. Stale workstation GPU no longer shown as active.
```

Keep the `Previous (v0.17.7):` line intact, just moved under the new block.

- [ ] **Step 4: Add v0.18.0 entry to `docs/version-history.md`**

Insert at the top of the changelog (after the `---` separator before `## v0.17.7`):

```markdown
## v0.18.0 — Image Analysis Queue + Pipeline Stats (2026-04-02)

**Decoupled LLM vision analysis for standalone image files:**
- New `analysis_queue` table (migration 19): `pending -> batched -> completed | failed`.
- Bulk worker enqueues image files after successful conversion.
- Lifecycle scanner enqueues new and content-changed image files on discovery.
- New `core/analysis_worker.py` (APScheduler, 5-min interval): claims up to
  `analysis_batch_size` pending rows, marks them `batched`, calls
  `VisionAdapter.describe_batch()` (one API call for all), writes results, re-indexes.
- `VisionAdapter.describe_batch()`: single multi-image call for Anthropic, OpenAI,
  Gemini. Ollama falls back to sequential if model rejects multiple images.
- LLM description + extracted text appended to Meilisearch `content` field — image
  files are searchable by visual content.
- Retry: failed batches reset to `pending` up to 3 times, then permanently `failed`.
- New preferences: `analysis_enabled` (kill switch), `analysis_batch_size` (default 10).

**Pipeline funnel statistics:**
- `GET /api/pipeline/stats`: scanned, pending conversion, failed, unrecognized,
  pending analysis, batched for analysis, analysis failed, in search index.
- Status page: stat strip above job cards.
- Admin page: Pipeline Funnel stats card.

**Bug fix — lifecycle scanner auto-conversion (source_path kwarg):**
- `core/lifecycle_scanner.py:924` was calling `BulkJob(source_path=...)` but
  `BulkJob.__init__` expects `source_paths=` (plural). Every auto-conversion
  triggered by the lifecycle scanner was silently failing with
  `BulkJob.__init__() got an unexpected keyword argument 'source_path'` since
  approximately 2026-04-02T12:06. Fixed by correcting the kwarg name.

**Bug fix — stale GPU display:**
- `core/gpu_detector.py`: `_read_host_worker_report()` now checks `worker.lock`
  existence and timestamp age before trusting `worker_capabilities.json`.
  Stale workstation GPU (e.g. NVIDIA 1660 Ti from disconnected workstation) no
  longer displayed as the active GPU.
- `tools/markflow-hashcat-worker.py`: writes heartbeat timestamp every 2 minutes.

---
```

- [ ] **Step 5: Commit docs and push**

```bash
cd /opt/doc-conversion-2026
git add CLAUDE.md docs/version-history.md
git commit -m "docs: v0.18.0 — image analysis queue, pipeline stats, bug fixes"
git push origin main
```
