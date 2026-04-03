# Pipeline File Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pipeline stat badges clickable, navigating to a new file explorer page where users can browse files by category with search, pagination, inline detail expansion, and actions (view, browse source).

**Architecture:** New `GET /api/pipeline/files` endpoint queries files from `bulk_files`, `source_files`, and `analysis_queue` based on selected status categories. New `pipeline-files.html` page renders a filter chip bar + paginated table with inline expand. Status page stat pills become clickable links.

**Tech Stack:** Python/FastAPI (backend), vanilla HTML/JS/CSS (frontend), aiosqlite, Meilisearch browse API

**Spec:** `docs/superpowers/specs/2026-04-03-pipeline-file-explorer-design.md`

---

### Task 1: Backend — `get_pipeline_files()` DB helper

**Files:**
- Modify: `core/db/bulk.py` (append new function after `get_pending_files_global` at line ~369)
- Modify: `core/db/__init__.py` (add to imports and `__all__`)

- [ ] **Step 1: Add `get_pipeline_files()` to `core/db/bulk.py`**

Append after the `get_pending_files_global` function (around line 369):

```python
async def get_pipeline_files(
    statuses: list[str],
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "source_path",
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Return files matching one or more pipeline status categories.

    Valid statuses: scanned, pending, failed, unrecognized,
                    pending_analysis, batched, analysis_failed.
    ('indexed' is handled separately via Meilisearch in the route.)

    Returns (rows, total_count).
    """
    ALLOWED_SORTS = {"source_path", "file_ext", "file_size_bytes", "status"}
    if sort not in ALLOWED_SORTS:
        sort = "source_path"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    sub_queries: list[str] = []
    sub_params: list[Any] = []

    for s in statuses:
        if s == "scanned":
            q = ("SELECT sf.id, sf.source_path, sf.file_ext, sf.file_size_bytes, "
                 "sf.source_mtime, 'scanned' AS status, NULL AS error_msg, "
                 "NULL AS skip_reason, NULL AS converted_at, "
                 "sf.last_seen_job_id AS job_id, sf.content_hash "
                 "FROM source_files sf WHERE sf.lifecycle_status = 'active'")
            if search:
                q += " AND sf.source_path LIKE ?"
                sub_params.append(f"%{search}%")
            sub_queries.append(q)

        elif s in ("pending", "failed", "unrecognized"):
            q = ("SELECT bf.id, bf.source_path, bf.file_ext, bf.file_size_bytes, "
                 "bf.source_mtime, bf.status, bf.error_msg, bf.skip_reason, "
                 "bf.converted_at, bf.job_id, sf.content_hash "
                 "FROM bulk_files bf "
                 "LEFT JOIN source_files sf ON bf.source_file_id = sf.id "
                 "WHERE bf.status = ?")
            sub_params.append(s)
            if search:
                q += " AND bf.source_path LIKE ?"
                sub_params.append(f"%{search}%")
            sub_queries.append(q)

        elif s in ("pending_analysis", "batched", "analysis_failed"):
            aq_status = {
                "pending_analysis": "pending",
                "batched": "batched",
                "analysis_failed": "failed",
            }[s]
            q = ("SELECT aq.id, aq.source_path, "
                 "NULL AS file_ext, NULL AS file_size_bytes, "
                 "NULL AS source_mtime, "
                 f"'{s}' AS status, aq.error AS error_msg, "
                 "NULL AS skip_reason, aq.analyzed_at AS converted_at, "
                 "aq.job_id, aq.content_hash "
                 "FROM analysis_queue aq WHERE aq.status = ?")
            sub_params.append(aq_status)
            if search:
                q += " AND aq.source_path LIKE ?"
                sub_params.append(f"%{search}%")
            sub_queries.append(q)

    if not sub_queries:
        return [], 0

    union_sql = " UNION ALL ".join(sub_queries)

    # Count
    count_sql = f"SELECT COUNT(*) AS cnt FROM ({union_sql})"
    count_row = await db_fetch_one(count_sql, tuple(sub_params))
    total = count_row["cnt"] if count_row else 0

    # Data
    data_sql = f"{union_sql} ORDER BY {sort} {sort_dir} LIMIT ? OFFSET ?"
    data_params = list(sub_params) + [limit, offset]
    rows = await db_fetch_all(data_sql, tuple(data_params))

    return rows, total
```

- [ ] **Step 2: Add re-export in `core/db/__init__.py`**

Add `get_pipeline_files` to the import from `core.db.bulk` and to the `__all__` list, following the same pattern as `get_pending_files_global`.

- [ ] **Step 3: Commit**

```bash
git add core/db/bulk.py core/db/__init__.py
git commit -m "feat(api): add get_pipeline_files() DB helper for multi-status file queries"
```

---

### Task 2: Backend — `GET /api/pipeline/files` endpoint

**Files:**
- Modify: `api/routes/pipeline.py` (add new route after the `/stats` endpoint, around line 259)

- [ ] **Step 1: Add the endpoint to `api/routes/pipeline.py`**

Add `Query` to the fastapi import if not already present:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, Query
```

Then add the route after the `pipeline_stats` function (after line 258):

```python
@router.get("/files")
async def pipeline_files(
    status: str = Query(..., description="Comma-separated: scanned,pending,failed,unrecognized,pending_analysis,batched,analysis_failed,indexed"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort: str = Query("source_path"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Paginated file list filtered by one or more pipeline status categories."""
    from core.db.bulk import get_pipeline_files

    statuses = [s.strip() for s in status.split(",") if s.strip()]
    valid = {"scanned", "pending", "failed", "unrecognized",
             "pending_analysis", "batched", "analysis_failed", "indexed"}
    statuses = [s for s in statuses if s in valid]

    if not statuses:
        return {"files": [], "total": 0, "page": 1, "per_page": per_page, "pages": 1}

    has_indexed = "indexed" in statuses
    db_statuses = [s for s in statuses if s != "indexed"]

    offset = (max(1, page) - 1) * per_page
    files: list[dict] = []
    total = 0

    if db_statuses:
        rows, db_total = await get_pipeline_files(
            statuses=db_statuses, search=search,
            limit=per_page, offset=offset,
            sort=sort, sort_dir=sort_dir,
        )
        files.extend(rows)
        total += db_total

    if has_indexed:
        try:
            indexed_files, indexed_total = await _browse_search_index(
                search=search, limit=per_page, offset=offset,
            )
            files.extend(indexed_files)
            total += indexed_total
        except Exception:
            pass

    return {
        "files": files,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


async def _browse_search_index(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Browse Meilisearch indexes and return files in pipeline-files format."""
    client = get_meili_client()
    if not client:
        return [], 0

    files = []
    total = 0

    for index_name in ("documents", "adobe-files", "transcripts"):
        try:
            if search:
                result = await client.search(index_name, search, limit=limit, offset=offset)
            else:
                result = await client.get_documents(index_name, limit=limit, offset=offset)

            hits = result.get("hits") or result.get("results") or []
            total += result.get("estimatedTotalHits") or result.get("total") or len(hits)

            for doc in hits:
                files.append({
                    "id": doc.get("id", ""),
                    "source_path": doc.get("source_path") or doc.get("source_filename", ""),
                    "file_ext": doc.get("source_format", ""),
                    "file_size_bytes": doc.get("file_size_bytes"),
                    "source_mtime": None,
                    "status": "indexed",
                    "error_msg": None,
                    "skip_reason": None,
                    "converted_at": doc.get("converted_at"),
                    "job_id": None,
                    "content_hash": doc.get("content_hash"),
                })
        except Exception:
            continue

    return files, total
```

- [ ] **Step 2: Update the module docstring at top of file**

```python
"""
Pipeline status and control API endpoints.

GET  /api/pipeline/status   -- Pipeline status (enabled, paused, last scan, next scan)
POST /api/pipeline/pause    -- Pause the pipeline (in-memory)
POST /api/pipeline/resume   -- Resume the pipeline
POST /api/pipeline/run-now  -- Trigger immediate scan+convert cycle
GET  /api/pipeline/stats    -- Pipeline funnel statistics
GET  /api/pipeline/files    -- Paginated file list by pipeline status category
"""
```

- [ ] **Step 3: Commit**

```bash
git add api/routes/pipeline.py
git commit -m "feat(api): add GET /api/pipeline/files endpoint for multi-status file browsing"
```

---

### Task 3: Frontend — `pipeline-files.html` page

**Files:**
- Create: `static/pipeline-files.html`

- [ ] **Step 1: Create the page**

Create `static/pipeline-files.html` — full standalone HTML page following MarkFlow patterns (vanilla HTML/JS/CSS, no frameworks). Uses safe DOM construction (createElement/textContent) throughout, never innerHTML with untrusted data.

Key sections:
- Filter chip bar with all 8 categories (multi-select toggle)
- Search input with 300ms debounce
- Large-result warning banner (shown when total > 5000)
- File table with columns: expand arrow, file path, ext, size, status badge, actions
- Inline detail expansion (error msg, skip reason, timestamps, job link, content hash)
- Row actions: eye icon (opens viewer.html), folder icon (opens drive browser)
- Pagination with per-page buttons (10/30/50/100)
- URL state sync via `history.replaceState`

All DOM rendering uses `document.createElement` + `textContent` for safe output. Status badges, detail fields, and file paths are all set via `textContent`, not innerHTML.

The page reads `?status=` from URL params on load, fetches counts from `/api/pipeline/stats`, and files from `/api/pipeline/files`.

- [ ] **Step 2: Commit**

```bash
git add static/pipeline-files.html
git commit -m "feat(ui): add pipeline-files.html — file explorer with category filters"
```

---

### Task 4: Make status page stat pills clickable

**Files:**
- Modify: `static/status.html` (lines 32-42: stat pill HTML)
- Modify: `static/markflow.css` (line ~1386: stat-pill styles)

- [ ] **Step 1: Replace `<span>` pills with `<a>` tags in `status.html`**

Replace lines 32-42 (the pipeline stats strip) — change each `<span class="stat-pill">` to `<a class="stat-pill stat-pill--link" href="/pipeline-files.html?status={category}">`. The `updatePipelineStats()` JS function (lines 115-130) needs no changes since it sets `textContent` which works on both `<span>` and `<a>`.

```html
    <div id="pipeline-stats-strip" style="display:flex;flex-wrap:wrap;gap:0.5rem;margin:0.75rem 0 1rem 0;padding:0.75rem 1rem;background:var(--bg-secondary,#1a1a2e);border-radius:8px;">
      <span style="color:var(--text-muted,#888);align-self:center;margin-right:0.25rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;font-size:0.75rem;">Pipeline</span>
      <a class="stat-pill stat-pill--link" href="/pipeline-files.html?status=scanned" id="ps-scanned">— scanned</a>
      <a class="stat-pill stat-pill--link" href="/pipeline-files.html?status=pending" id="ps-pending">— pending</a>
      <a class="stat-pill stat-pill--link" href="/pipeline-files.html?status=failed" id="ps-failed">— failed</a>
      <a class="stat-pill stat-pill--link" href="/pipeline-files.html?status=unrecognized" id="ps-unrecognized">— unrecognized</a>
      <a class="stat-pill stat-pill--link stat-pill--analysis" href="/pipeline-files.html?status=pending_analysis" id="ps-panalysis">— pending analysis</a>
      <a class="stat-pill stat-pill--link stat-pill--batched" href="/pipeline-files.html?status=batched" id="ps-batched">— batched</a>
      <a class="stat-pill stat-pill--link stat-pill--afailed" href="/pipeline-files.html?status=analysis_failed" id="ps-afailed">— analysis failed</a>
      <a class="stat-pill stat-pill--link stat-pill--indexed" href="/pipeline-files.html?status=indexed" id="ps-indexed">— indexed</a>
    </div>
```

- [ ] **Step 2: Add clickable pill styles to `markflow.css`**

After line 1390 (the existing `.stat-pill--indexed` rule), add:

```css
.stat-pill--link { text-decoration:none;cursor:pointer;transition:opacity 0.15s,transform 0.1s; }
.stat-pill--link:hover { opacity:0.85;transform:scale(1.05); }
```

- [ ] **Step 3: Commit**

```bash
git add static/status.html static/markflow.css
git commit -m "feat(ui): make pipeline stat pills clickable links to file explorer"
```

---

### Task 5: Add to navigation + final integration test

**Files:**
- Modify: `static/app.js` (line ~154: NAV_ITEMS array)

- [ ] **Step 1: Add nav item for pipeline files page**

Add after the Status nav item (line 151) in the `NAV_ITEMS` array:

```javascript
    { href: "/pipeline-files.html", label: "Files", minRole: "operator" },
```

- [ ] **Step 2: Manual integration test**

1. Start the container: `docker-compose up -d --build`
2. Open `http://localhost:8000/status.html`
3. Verify stat pills are now links (hover shows pointer cursor, slight scale effect)
4. Click "failed" pill — navigates to `pipeline-files.html?status=failed`
5. Verify chips load with counts, "failed" chip is active
6. Click another chip (e.g., "pending") — both active, results update
7. Click the expand arrow on a row — inline detail expands with error/job info
8. Click the eye icon — opens viewer in new tab
9. Click the folder icon — opens drive browser to parent directory
10. Test search: type a path fragment, verify debounced filtering
11. Test pagination: switch per-page to 10, navigate pages
12. Click back arrow link — returns to status page

- [ ] **Step 3: Commit**

```bash
git add static/app.js
git commit -m "feat(ui): add Pipeline Files to nav bar"
```

---

### Task 6: Update CLAUDE.md and version

**Files:**
- Modify: `CLAUDE.md` — update Current Status section

- [ ] **Step 1: Update CLAUDE.md current status**

Update the Current Status section to document v0.19.4 with the pipeline file explorer feature: clickable stat badges, new pipeline-files.html page with multi-category filter chips, search, pagination, inline detail expansion, viewer/browse actions.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for pipeline file explorer (v0.19.4)"
```
