# Batch Management Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a batch management page for controlling LLM analysis submissions — pause/resume/cancel, view batch contents, exclude files, preview, download.

**Architecture:** New page `/batch-management.html` backed by new API routes in `api/routes/analysis.py`. The analysis pipeline's batch submission loop gains a pause gate controlled by an in-memory flag + DB preference. File operations (preview, download) proxy through the API since source shares are read-only mounted.

**Tech Stack:** Python/FastAPI, vanilla HTML/JS, SQLite, PIL (thumbnails)

**Spec:** `docs/superpowers/specs/2026-04-13-batch-management-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `core/db/analysis.py` | `get_batches()`, `get_batch_files()`, `exclude_files()`, `recalculate_batches()`, `cancel_all_pending()` |
| Modify | `core/db/preferences.py` | Add `analysis_submission_paused` preference |
| Create | `api/routes/analysis.py` | New router: pause/resume, status, batches, exclude, file ops |
| Create | `static/batch-management.html` | New page with batch cards, file tables, modals |
| Create | `tests/test_analysis_batches.py` | Backend tests for batch management functions |
| Modify | `api/routes/preferences.py` | Schema entry for new preference |
| Modify | `static/app.js` | Add "Batches" to NAV_ITEMS |
| Modify | `static/status.html` | Change "batched" pill href |
| Modify | `static/bulk.html` | Change "batched" pill href (if present) |
| Modify | `main.py` | Mount analysis router |

---

### Task 1: Analysis DB Functions — Tests

**Files:**
- Create: `tests/test_analysis_batches.py`
- Modify: `core/db/analysis.py`

- [ ] **Step 1: Write failing tests for batch listing and exclusion**

```python
# tests/test_analysis_batches.py
"""Tests for analysis batch management functions."""

import pytest
import aiosqlite

from core.db.analysis import (
    get_batches,
    get_batch_files,
    exclude_files,
    cancel_all_batched,
)


@pytest.fixture
async def analysis_db(tmp_path):
    """Create a minimal DB with analysis_queue table and test data."""
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute("""
            CREATE TABLE source_files (
                id INTEGER PRIMARY KEY,
                source_path TEXT,
                file_size INTEGER DEFAULT 0,
                modified_at TEXT DEFAULT '',
                extension TEXT DEFAULT ''
            )
        """)
        await conn.execute("""
            CREATE TABLE analysis_queue (
                id INTEGER PRIMARY KEY,
                source_file_id INTEGER,
                batch_id TEXT,
                status TEXT DEFAULT 'pending',
                batched_at TEXT,
                submitted_at TEXT,
                completed_at TEXT,
                error_msg TEXT,
                retry_count INTEGER DEFAULT 0,
                enqueued_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Insert test source files
        for i in range(1, 11):
            await conn.execute(
                "INSERT INTO source_files (id, source_path, file_size, extension) VALUES (?, ?, ?, ?)",
                (i, f"/mnt/source/test/file_{i}.png", 1000 * i, ".png"),
            )
        # Insert batched entries — 2 batches of 5
        for i in range(1, 6):
            await conn.execute(
                "INSERT INTO analysis_queue (source_file_id, batch_id, status, batched_at) VALUES (?, 'batch_a', 'batched', datetime('now'))",
                (i,),
            )
        for i in range(6, 11):
            await conn.execute(
                "INSERT INTO analysis_queue (source_file_id, batch_id, status, batched_at) VALUES (?, 'batch_b', 'batched', datetime('now'))",
                (i,),
            )
        await conn.commit()
    return db_path


class TestGetBatches:
    @pytest.mark.anyio
    async def test_returns_two_batches(self, analysis_db):
        batches = await get_batches(analysis_db)
        assert len(batches) == 2

    @pytest.mark.anyio
    async def test_batch_has_metadata(self, analysis_db):
        batches = await get_batches(analysis_db)
        b = batches[0]
        assert "batch_id" in b
        assert "file_count" in b
        assert "total_size_bytes" in b
        assert b["file_count"] == 5


class TestGetBatchFiles:
    @pytest.mark.anyio
    async def test_returns_five_files(self, analysis_db):
        files = await get_batch_files(analysis_db, "batch_a")
        assert len(files) == 5

    @pytest.mark.anyio
    async def test_file_has_path_and_size(self, analysis_db):
        files = await get_batch_files(analysis_db, "batch_a")
        f = files[0]
        assert "source_path" in f
        assert "file_size" in f


class TestExcludeFiles:
    @pytest.mark.anyio
    async def test_exclude_marks_status(self, analysis_db):
        result = await exclude_files(analysis_db, file_ids=[1, 2, 3])
        assert result["excluded_count"] == 3
        # Verify status changed
        async with aiosqlite.connect(str(analysis_db)) as conn:
            row = await conn.execute_fetchall(
                "SELECT status FROM analysis_queue WHERE source_file_id IN (1,2,3)"
            )
            for r in row:
                assert r[0] == "excluded"

    @pytest.mark.anyio
    async def test_exclude_batch(self, analysis_db):
        result = await exclude_files(analysis_db, batch_id="batch_b")
        assert result["excluded_count"] == 5


class TestCancelAllBatched:
    @pytest.mark.anyio
    async def test_resets_to_pending(self, analysis_db):
        result = await cancel_all_batched(analysis_db)
        assert result["reset_count"] == 10
        async with aiosqlite.connect(str(analysis_db)) as conn:
            rows = await conn.execute_fetchall(
                "SELECT DISTINCT status FROM analysis_queue"
            )
            statuses = [r[0] for r in rows]
            assert "batched" not in statuses
            assert "pending" in statuses
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec doc-conversion-2026-markflow-1 python -m pytest tests/test_analysis_batches.py -v`
Expected: ImportError

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_analysis_batches.py
git commit -m "test: add failing tests for analysis batch management"
```

---

### Task 2: Analysis DB Functions — Implementation

**Files:**
- Modify: `core/db/analysis.py`

- [ ] **Step 1: Add batch listing and management functions**

Append to `core/db/analysis.py`:

```python
async def get_batches(db_path=None) -> list[dict]:
    """List all batches with metadata, newest first."""
    from core.database import DB_PATH
    _path = db_path or DB_PATH
    async with aiosqlite.connect(str(_path)) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await conn.execute_fetchall("""
            SELECT
                aq.batch_id,
                COUNT(*) as file_count,
                COALESCE(SUM(sf.file_size), 0) as total_size_bytes,
                aq.status,
                MIN(aq.batched_at) as batched_at,
                MIN(aq.submitted_at) as submitted_at,
                MIN(aq.completed_at) as completed_at
            FROM analysis_queue aq
            LEFT JOIN source_files sf ON sf.id = aq.source_file_id
            WHERE aq.batch_id IS NOT NULL AND aq.status != 'excluded'
            GROUP BY aq.batch_id
            ORDER BY MIN(aq.batched_at) DESC
        """)
        return [dict(r) for r in rows]


async def get_batch_files(db_path=None, batch_id: str = "") -> list[dict]:
    """List files in a specific batch with source file metadata."""
    from core.database import DB_PATH
    _path = db_path or DB_PATH
    async with aiosqlite.connect(str(_path)) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await conn.execute_fetchall("""
            SELECT
                aq.id as queue_id,
                aq.source_file_id,
                aq.status,
                aq.batch_id,
                sf.source_path,
                sf.file_size,
                sf.modified_at,
                sf.extension
            FROM analysis_queue aq
            LEFT JOIN source_files sf ON sf.id = aq.source_file_id
            WHERE aq.batch_id = ?
            ORDER BY sf.source_path
        """, (batch_id,))
        return [dict(r) for r in rows]


async def exclude_files(
    db_path=None,
    file_ids: list[int] | None = None,
    batch_id: str | None = None,
) -> dict:
    """Mark files as excluded from analysis."""
    from core.database import DB_PATH
    _path = db_path or DB_PATH
    async with aiosqlite.connect(str(_path)) as conn:
        if batch_id:
            cursor = await conn.execute(
                "UPDATE analysis_queue SET status = 'excluded' WHERE batch_id = ? AND status = 'batched'",
                (batch_id,),
            )
        elif file_ids:
            placeholders = ",".join("?" * len(file_ids))
            cursor = await conn.execute(
                f"UPDATE analysis_queue SET status = 'excluded' WHERE source_file_id IN ({placeholders}) AND status = 'batched'",
                file_ids,
            )
        else:
            return {"excluded_count": 0}
        await conn.commit()
        return {"excluded_count": cursor.rowcount}


async def cancel_all_batched(db_path=None) -> dict:
    """Reset all batched rows back to pending."""
    from core.database import DB_PATH
    _path = db_path or DB_PATH
    async with aiosqlite.connect(str(_path)) as conn:
        cursor = await conn.execute(
            "UPDATE analysis_queue SET status = 'pending', batch_id = NULL WHERE status = 'batched'"
        )
        await conn.commit()
        return {"reset_count": cursor.rowcount}
```

- [ ] **Step 2: Run tests**

Run: `docker exec doc-conversion-2026-markflow-1 python -m pytest tests/test_analysis_batches.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add core/db/analysis.py
git commit -m "feat: batch listing, file listing, exclude, cancel functions"
```

---

### Task 3: Analysis Pause Preference

**Files:**
- Modify: `core/db/preferences.py`
- Modify: `api/routes/preferences.py`

- [ ] **Step 1: Add preference default**

In `core/db/preferences.py`, add to `DEFAULT_PREFERENCES`:

```python
"analysis_submission_paused": "false",
```

- [ ] **Step 2: Add preference schema**

In `api/routes/preferences.py`, add to `_PREFERENCE_SCHEMA`:

```python
"analysis_submission_paused": {
    "type": "toggle",
    "label": "Pause analysis submissions",
    "description": "When enabled, batched files will not be submitted to the LLM provider. Existing in-flight submissions complete normally.",
},
```

- [ ] **Step 3: Commit**

```bash
git add core/db/preferences.py api/routes/preferences.py
git commit -m "feat: add analysis_submission_paused preference"
```

---

### Task 4: Analysis API Router

**Files:**
- Create: `api/routes/analysis.py`
- Modify: `main.py`

- [ ] **Step 1: Create the analysis router**

```python
# api/routes/analysis.py
"""Analysis batch management API endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthenticatedUser, UserRole, require_role

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# In-memory pause flag (also persisted as preference)
_analysis_paused = False


class ExcludeRequest(BaseModel):
    file_ids: list[int] | None = None
    batch_id: str | None = None


@router.get("/status")
async def analysis_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Get analysis pipeline status."""
    from core.db.analysis import get_batches
    from core.preferences_cache import get_cached_preference

    paused = await get_cached_preference("analysis_submission_paused", "false")
    batches = await get_batches()

    pending = sum(1 for b in batches if b["status"] == "pending")
    batched = sum(1 for b in batches if b["status"] == "batched")
    completed = sum(1 for b in batches if b["status"] == "completed")
    failed = sum(1 for b in batches if b["status"] == "failed")

    status = "paused" if paused == "true" else ("idle" if not batched else "running")

    return {
        "status": status,
        "pending": pending,
        "batched": batched,
        "completed": completed,
        "failed": failed,
    }


@router.post("/pause")
async def pause_submissions(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Pause analysis batch submissions."""
    from core.db.preferences import set_preference
    from core.preferences_cache import invalidate_preference

    await set_preference("analysis_submission_paused", "true")
    invalidate_preference("analysis_submission_paused")
    global _analysis_paused
    _analysis_paused = True
    return {"status": "paused"}


@router.post("/resume")
async def resume_submissions(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Resume analysis batch submissions."""
    from core.db.preferences import set_preference
    from core.preferences_cache import invalidate_preference

    await set_preference("analysis_submission_paused", "false")
    invalidate_preference("analysis_submission_paused")
    global _analysis_paused
    _analysis_paused = False
    return {"status": "running"}


@router.post("/cancel-pending")
async def cancel_pending(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Reset all batched rows back to pending."""
    from core.db.analysis import cancel_all_batched
    return await cancel_all_batched()


@router.get("/batches")
async def list_batches(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """List all analysis batches with metadata."""
    from core.db.analysis import get_batches
    return await get_batches()


@router.get("/batches/{batch_id}/files")
async def batch_files(
    batch_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """List files in a specific batch."""
    from core.db.analysis import get_batch_files
    return await get_batch_files(batch_id=batch_id)


@router.post("/exclude")
async def exclude(
    req: ExcludeRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Exclude files from analysis batches."""
    from core.db.analysis import exclude_files

    if not req.file_ids and not req.batch_id:
        raise HTTPException(400, "Provide file_ids or batch_id")
    return await exclude_files(file_ids=req.file_ids, batch_id=req.batch_id)


@router.get("/files/{source_file_id}/preview")
async def file_preview(
    source_file_id: int,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return a preview/thumbnail of a source file."""
    from core.db.bulk import get_source_file_by_id
    from fastapi.responses import FileResponse, JSONResponse

    sf = await get_source_file_by_id(source_file_id)
    if not sf:
        raise HTTPException(404, "File not found")

    path = Path(sf["source_path"])
    if not path.exists():
        raise HTTPException(404, "Source file not accessible")

    ext = path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"):
        return FileResponse(str(path), media_type=f"image/{ext.lstrip('.')}")

    return JSONResponse({
        "name": path.name,
        "size": path.stat().st_size,
        "extension": ext,
        "preview_available": False,
    })


@router.get("/files/{source_file_id}/download")
async def file_download(
    source_file_id: int,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Stream a source file as a browser download."""
    from core.db.bulk import get_source_file_by_id
    from fastapi.responses import FileResponse

    sf = await get_source_file_by_id(source_file_id)
    if not sf:
        raise HTTPException(404, "File not found")

    path = Path(sf["source_path"])
    if not path.exists():
        raise HTTPException(404, "Source file not accessible")

    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=path.name,
    )
```

- [ ] **Step 2: Mount the router in main.py**

Find where other routers are included (search for `app.include_router`). Add:

```python
from api.routes.analysis import router as analysis_router
app.include_router(analysis_router)
```

- [ ] **Step 3: Commit**

```bash
git add api/routes/analysis.py main.py
git commit -m "feat: analysis batch management API router"
```

---

### Task 5: Wire Pause Gate into Analysis Worker

**Files:**
- Modify: The file that calls `claim_pending_batch()` in a loop

- [ ] **Step 1: Find the analysis submission loop**

Search for where `claim_pending_batch` is called:

```bash
grep -rn "claim_pending_batch" core/ api/
```

- [ ] **Step 2: Add pause gate**

Before the call to `claim_pending_batch`, add:

```python
from core.preferences_cache import get_cached_preference

paused = await get_cached_preference("analysis_submission_paused", "false")
if paused == "true":
    log.info("analysis.paused", msg="Submission paused by user")
    return
```

- [ ] **Step 3: Commit**

```bash
git add <the modified file>
git commit -m "feat: analysis submission pause gate"
```

---

### Task 6: Batch Management Page — HTML/JS

**Files:**
- Create: `static/batch-management.html`

- [ ] **Step 1: Create the page**

Create `static/batch-management.html` with:

**Top bar:**
- Pipeline status indicator (fetches `/api/analysis/status`)
- Pause/Resume toggle button
- Cancel All Pending button
- Stats row (pending, batched, completed, failed)

**Batch list:**
- Fetches `/api/analysis/batches`
- Each batch is a collapsible card showing: batch_id, file_count, total_size, status, timestamp
- Clicking expands the file table via `/api/analysis/batches/{batch_id}/files`

**File table (inside expanded batch):**
- Checkbox column for bulk selection
- Filename (click → download via `/api/analysis/files/{id}/download`)
- Path, Size, Date, Type columns
- Exclude button per row
- "Exclude Selected" action bar appears when checkboxes are checked
- Hover preview on filename (fetches `/api/analysis/files/{id}/preview`, shows image thumbnail in a tooltip)

**Polling:**
- Poll `/api/analysis/status` every 5 seconds to update the status indicator and stats
- Refresh batch list when status changes

The page structure follows the same patterns as `bulk.html` and `status.html`:
- Same nav bar (via app.js `buildNav()`)
- Same card styling
- Same button classes

- [ ] **Step 2: Add to NAV_ITEMS in app.js**

In `static/app.js`, find the `NAV_ITEMS` array (around line 169). Add between "Files" and "Bulk Jobs":

```javascript
{ href: "/batch-management.html", label: "Batches", minRole: "operator" },
```

- [ ] **Step 3: Update "batched" pill links**

In `static/status.html` line 39, change:
```html
<a class="stat-pill stat-pill--link stat-pill--batched" href="/pipeline-files.html?status=batched" id="ps-batched">— batched</a>
```
To:
```html
<a class="stat-pill stat-pill--link stat-pill--batched" href="/batch-management.html" id="ps-batched">— batched</a>
```

If `bulk.html` has a similar "batched" pill, update it too.

- [ ] **Step 4: Test in browser**

1. Navigate to Batches page from nav bar
2. See batch list (or empty state if no batches)
3. Click Pause — status changes
4. Click Resume — status changes
5. Expand a batch — see file table
6. Hover a file — preview tooltip
7. Click a file — browser download dialog
8. Exclude a file — removed from batch
9. Bulk select + Exclude Selected — multiple removed

- [ ] **Step 5: Commit**

```bash
git add static/batch-management.html static/app.js static/status.html static/bulk.html
git commit -m "feat: batch management page with pause/resume/exclude/preview"
```

---

### Task 7: Final Verification

- [ ] **Step 1: Run all backend tests**

```bash
docker exec doc-conversion-2026-markflow-1 python -m pytest tests/test_analysis_batches.py -v
```

- [ ] **Step 2: Full browser walkthrough**

1. Nav bar shows "Batches" link
2. Batch management page loads with status indicator
3. Pause/Resume works and persists across page refresh
4. Batch cards expand to show file tables
5. File hover preview works for images
6. File click downloads
7. Exclude removes file from batch
8. Cancel All Pending resets everything
9. Status page "batched" pill links to batch-management.html

- [ ] **Step 3: Commit any fixes**
