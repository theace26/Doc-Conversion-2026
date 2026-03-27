# MarkFlow — Phase 8c Planning Doc
## Unknown & Unrecognized File Cataloging (v0.8.2)

> **Status**: Queued — do not begin until CLAUDE.md confirms v0.8.1 complete  
> **Builds on**: v0.8.1 (visual enrichment), v0.7.4b (bulk scanner + path safety)  
> **Target tag**: v0.8.2

---

## Why This Phase Exists

The bulk scanner currently ignores any file it doesn't have a handler for — no record,
no log entry, no way to find it later. For a large company repository scan, this means
unknown files (disk images, raw video, archives, executables, etc.) silently disappear
from the results. This phase ensures every file the scanner touches is accounted for,
categorized, and retrievable — even if MarkFlow can't convert it yet.

**Core principle**: The markdown repository stays clean. No stub `.md` files for
unrecognized content. Only the database gets a record. When a handler is eventually
added for a file type, the next bulk run automatically picks up all the backlogged
files because they remain in the database with `status = 'unrecognized'`.

---

## Decisions Already Made

These decisions are locked. Do not re-litigate them:

1. **Database record only** — no stub `.md` files, no Meilisearch entries for
   unrecognized files. Keeps the knowledge base signal clean.

2. **`status = 'unrecognized'`** — new status value in `bulk_files`. Distinct from
   `failed` (which means MarkFlow tried and errored) and `skipped` (which means
   intentionally excluded).

3. **MIME-based categorization via `python-magic`** — do not trust file extensions
   alone. A `.dat` that is actually an ISO gets categorized as `disk_image`.

4. **Inventory IS the work queue** — `get_unprocessed_bulk_files()` already excludes
   `permanently_skipped`. Add `unrecognized` as a re-processable status so future
   handlers automatically pick up the backlog.

5. **Retrieval paths** (in priority order):
   - `/unrecognized` UI page with filters and CSV export
   - Bulk job results page gains an unrecognized count with drilldown
   - New MCP tool `list_unrecognized`
   - Direct SQLite (always available, no build required)

---

## Scope

### In Scope
- MIME detection and category assignment during bulk scan
- Database schema changes to `bulk_files`
- `BulkScanner` changes to record unrecognized files instead of ignoring them
- `GET /api/unrecognized` API endpoint (list, filter, paginate, export CSV)
- `GET /api/unrecognized/stats` summary endpoint
- `/unrecognized` UI page
- Bulk job results page: add unrecognized count + drilldown link
- New MCP tool: `list_unrecognized`
- Tests for all new code paths

### Out of Scope
- Actually processing any unrecognized file type (that is a future handler addition)
- ISO mounting or disk image extraction
- Standalone raster image OCR (separate future handler)
- Any changes to the single-file conversion pipeline

---

## Database Schema Changes

### `bulk_files` table — new columns

Add to existing `bulk_files` table (ALTER TABLE with defaults for backwards compat):

```sql
ALTER TABLE bulk_files ADD COLUMN mime_type TEXT;
ALTER TABLE bulk_files ADD COLUMN file_category TEXT DEFAULT 'unknown';
```

`file_category` values (enforced in Python, not as SQL constraint):
- `disk_image` — ISO, IMG, VHD, VMDK, DMG
- `raster_image` — JPG, PNG, TIFF, BMP, GIF, HEIC, WebP (standalone, not embedded)
- `vector_image` — SVG, EPS (not covered by Adobe indexer)
- `video` — MP4, MKV, MOV, AVI, WMV (not yet handled by v0.8.0 transcription)
- `audio` — MP3, WAV, FLAC, AAC, OGG (not yet handled by v0.8.0 transcription)
- `archive` — ZIP, TAR, GZ, 7Z, RAR, CAB
- `executable` — EXE, MSI, DLL, SO, APP, DMG (when detected as executable)
- `database` — MDB, ACCDB, SQLITE, DB
- `font` — TTF, OTF, WOFF, WOFF2
- `code` — PY, JS, TS, CS, CPP, JAVA, etc. (text files, not document files)
- `unknown` — anything not matched by MIME or extension heuristic

**Note**: Files already handled by MarkFlow (docx, pdf, pptx, xlsx, csv, ai, psd, etc.)
and video/audio files handled by the v0.8.0 transcription pipeline are NEVER written
as `unrecognized` — they go through their normal handler path.

### No new table needed
All unrecognized file data fits in `bulk_files`. A separate table would require
JOIN queries everywhere and offers no benefit at this scale.

---

## New File: `core/mime_classifier.py`

Single-responsibility module. No dependencies on other MarkFlow core modules.

```python
# core/mime_classifier.py

import magic  # python-magic
from pathlib import Path

MIME_TO_CATEGORY: dict[str, str] = {
    # Disk images
    "application/x-iso9660-image": "disk_image",
    "application/x-raw-disk-image": "disk_image",
    "application/x-virtualbox-vdi": "disk_image",
    "application/x-vmdk": "disk_image",
    # Raster images
    "image/jpeg": "raster_image",
    "image/png": "raster_image",
    "image/tiff": "raster_image",
    "image/bmp": "raster_image",
    "image/gif": "raster_image",
    "image/webp": "raster_image",
    "image/heic": "raster_image",
    "image/avif": "raster_image",
    # Vector images
    "image/svg+xml": "vector_image",
    "application/postscript": "vector_image",  # EPS
    # Video
    "video/mp4": "video",
    "video/x-matroska": "video",
    "video/quicktime": "video",
    "video/x-msvideo": "video",
    "video/x-ms-wmv": "video",
    "video/webm": "video",
    # Audio
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/flac": "audio",
    "audio/aac": "audio",
    "audio/ogg": "audio",
    # Archives
    "application/zip": "archive",
    "application/x-tar": "archive",
    "application/gzip": "archive",
    "application/x-7z-compressed": "archive",
    "application/x-rar-compressed": "archive",
    # Executables
    "application/x-dosexec": "executable",
    "application/x-msi": "executable",
    "application/x-executable": "executable",
    "application/x-sharedlib": "executable",
    # Databases
    "application/x-sqlite3": "database",
    "application/msaccess": "database",
    # Fonts
    "font/ttf": "font",
    "font/otf": "font",
    "font/woff": "font",
    "font/woff2": "font",
    "application/font-woff": "font",
}

def detect_mime(path: Path) -> str:
    """Detect MIME type using libmagic. Returns 'application/octet-stream' on failure."""
    try:
        return magic.from_file(str(path), mime=True)
    except Exception:
        return "application/octet-stream"

def classify(path: Path, mime_type: str | None = None) -> tuple[str, str]:
    """
    Returns (mime_type, category).
    Detects MIME if not provided. Falls back to extension heuristic if MIME unknown.
    """
    if mime_type is None:
        mime_type = detect_mime(path)

    # Try MIME lookup first
    category = MIME_TO_CATEGORY.get(mime_type)
    if category:
        return mime_type, category

    # Extension fallback for common types libmagic misses
    ext = path.suffix.lower().lstrip(".")
    ext_fallback: dict[str, str] = {
        "iso": "disk_image", "img": "disk_image", "vhd": "disk_image",
        "vmdk": "disk_image", "dmg": "disk_image",
        "jpg": "raster_image", "jpeg": "raster_image", "png": "raster_image",
        "tiff": "raster_image", "tif": "raster_image", "bmp": "raster_image",
        "gif": "raster_image", "heic": "raster_image", "webp": "raster_image",
        "svg": "vector_image", "eps": "vector_image",
        "mp4": "video", "mkv": "video", "mov": "video",
        "avi": "video", "wmv": "video", "webm": "video",
        "mp3": "audio", "wav": "audio", "flac": "audio",
        "aac": "audio", "ogg": "audio",
        "zip": "archive", "tar": "archive", "gz": "archive",
        "7z": "archive", "rar": "archive", "cab": "archive",
        "exe": "executable", "msi": "executable", "dll": "executable",
        "sqlite": "database", "db": "database", "mdb": "database",
        "ttf": "font", "otf": "font", "woff": "font", "woff2": "font",
        "py": "code", "js": "code", "ts": "code",
        "cs": "code", "cpp": "code", "java": "code",
    }
    return mime_type, ext_fallback.get(ext, "unknown")
```

**Requirements**:
- Add `python-magic` to `requirements.txt`
- Add `libmagic1` to Dockerfile apt-get installs
- All functions handle exceptions gracefully — never raise, always return a safe default
- Module has no side effects at import time

---

## Changes to `core/bulk_scanner.py`

### Current behavior
Scanner calls `_is_supported_format(path)` — if False, it silently moves on.

### New behavior
When a file is not supported, instead of skipping it, call `_record_unrecognized(path, job_id)`.

**New method `_record_unrecognized()`**:
```python
async def _record_unrecognized(self, path: Path, job_id: str) -> None:
    mime_type, category = classify(path)
    file_size = path.stat().st_size if path.exists() else 0
    mtime = path.stat().st_mtime if path.exists() else 0
    await db.upsert_bulk_file(
        job_id=job_id,
        source_path=str(path),
        status="unrecognized",
        source_format=path.suffix.lower().lstrip(".") or "no_extension",
        file_size_bytes=file_size,
        mtime=mtime,
        mime_type=mime_type,
        file_category=category,
    )
```

**Scanner summary**: After scan completes, `_run_scan()` already returns a `ScanSummary`
dataclass. Add `unrecognized_count: int` field to it. The bulk job SSE `scan_complete`
event should include this count.

**`get_unprocessed_bulk_files()` in `core/database.py`**: This function feeds the worker
queue. It must continue to EXCLUDE `unrecognized` files — they are cataloged, not queued
for conversion. They become processable only when a handler is added that supports their
format. At that point, their status would need to be reset to `pending` via an explicit
admin action (out of scope for this phase).

---

## Changes to `core/database.py`

### Schema migration
Add `mime_type` and `file_category` columns to `bulk_files` via `ALTER TABLE IF NOT EXISTS`
pattern (same pattern used for previous schema additions). Run in `init_db()`.

### New helper: `get_unrecognized_files()`
```python
async def get_unrecognized_files(
    job_id: str | None = None,
    category: str | None = None,
    source_format: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Returns paginated unrecognized files with total count."""
```

### New helper: `get_unrecognized_stats()`
```python
async def get_unrecognized_stats(job_id: str | None = None) -> dict:
    """
    Returns:
    {
        "total": int,
        "by_category": {"disk_image": int, "raster_image": int, ...},
        "by_format": {".iso": int, ".png": int, ...},
        "total_bytes": int,
        "job_ids": [str, ...]  # distinct jobs that found unrecognized files
    }
    """
```

---

## New File: `api/routes/unrecognized.py`

```
GET /api/unrecognized
    Query params: job_id, category, source_format, page, per_page
    Returns: { files: [...], total, page, per_page, pages }

GET /api/unrecognized/stats
    Query params: job_id (optional)
    Returns: { total, by_category, by_format, total_bytes, job_ids }

GET /api/unrecognized/export
    Query params: job_id, category, source_format (all optional)
    Returns: CSV download (Content-Disposition: attachment)
    Columns: source_path, source_format, mime_type, file_category,
             file_size_bytes, first_seen, job_id
```

Register router in `main.py` with prefix `/api`.

**CSV export notes**:
- Use Python's stdlib `csv` module, stream via `StreamingResponse`
- No size limit — export all matching rows, not paginated
- Filename: `markflow-unrecognized-{date}.csv`

---

## New File: `static/unrecognized.html`

Add to main nav bar (between Search and History, or after History — your call on nav order).

### Page layout

**Header**: "Unrecognized Files" with subtitle "Files cataloged but not yet convertible"

**Stats bar** (top of page, loads from `/api/unrecognized/stats`):
- Total files | Total size | Number of categories | Number of distinct jobs

**Filter bar**:
- Dropdown: Category (All, disk_image, raster_image, video, audio, archive, executable,
  database, font, code, unknown)
- Dropdown: Extension (populated dynamically from stats)
- Dropdown: Bulk Job (populated from stats `job_ids`, shows job ID + date)
- Button: "Export CSV" — calls `/api/unrecognized/export` with current filters

**Category summary cards** (below filters):
One card per category that has files. Shows icon, category name, count, total size.
Clicking a card filters the table to that category.

**File table**:
| Column | Notes |
|--------|-------|
| File Path | Truncated from left if long (same as active workers panel) |
| Format | Extension badge |
| Category | Colored badge (same color scheme as format badges in existing UI) |
| Size | Human-readable (KB/MB/GB) |
| First Seen | Relative date |
| Job | Abbreviated job ID |

Pagination: same pattern as history.html (page/per_page, prev/next).

**Empty state**: If no unrecognized files, show a friendly "All files in your repository
were recognized" message with an icon. Do not show the table at all.

### No Meilisearch integration
Unrecognized files are NOT indexed in Meilisearch. The UI page queries the SQLite API
directly. This is intentional — these files have no content to search.

---

## Changes to `static/bulk.html`

The bulk job results summary currently shows:
```
✅ N converted    ⚠️  N OCR review    ❌ N failed
```

Add a fourth pill:
```
✅ N converted    ⚠️  N OCR review    ❌ N failed    ❓ N unrecognized
```

The `❓ N unrecognized` pill links to `/unrecognized?job_id=<current_job_id>`.
Only show the pill if `unrecognized_count > 0`.

The `scan_complete` SSE event must include `unrecognized_count` (see bulk_scanner changes).
The job status API (`GET /api/bulk/{id}`) must also return `unrecognized_count`
(query `bulk_files WHERE job_id=? AND status='unrecognized'`).

---

## Changes to `mcp_server/tools.py`

Add 8th MCP tool: `list_unrecognized`.

**APPEND to `mcp_server/tools.py`** — do not replace the file.

```python
@mcp_tool(
    name="list_unrecognized",
    description="""List files found during bulk scans that MarkFlow could not convert,
    grouped by category. Use this to understand what unrecognized file types exist in
    the repository, how many there are, and their total size. Supports filtering by
    category (disk_image, raster_image, video, audio, archive, executable, database,
    font, code, unknown) and by bulk job ID. Returns paginated results with stats.
    Use the stats endpoint for a high-level summary before drilling into file lists."""
)
async def list_unrecognized(
    category: str | None = None,
    job_id: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    ...
```

**Docstring note**: MCP tool docstrings are functional — Claude.ai uses them to decide
when to call the tool. Keep the description specific and include all valid category values.

Update `mcp_server/server.py` tool count comment from 7 to 8.

---

## `requirements.txt` Changes

Add:
```
python-magic>=0.4.27
```

**Note**: `python-magic` requires `libmagic1` system library. Add to Dockerfile:
```dockerfile
RUN apt-get install -y libmagic1
```

Verify it doesn't conflict with existing image manipulation packages.

---

## Tests

### `tests/test_mime_classifier.py`
- `classify()` returns correct category for known MIME types
- `classify()` uses extension fallback when MIME is `application/octet-stream`
- `classify()` returns `("application/octet-stream", "unknown")` for genuinely unknown file
- `detect_mime()` handles nonexistent file gracefully (returns safe default, no exception)
- Extension-only files (no content) categorize via extension fallback

### `tests/test_unrecognized_api.py`
- `GET /api/unrecognized` returns empty list when no unrecognized files exist
- `GET /api/unrecognized` returns files after bulk scan with unrecognized files
- `GET /api/unrecognized?category=disk_image` filters correctly
- `GET /api/unrecognized?job_id=xxx` filters to one job
- `GET /api/unrecognized/stats` returns correct counts by category
- `GET /api/unrecognized/export` returns valid CSV with correct headers
- CSV export respects filters (category, job_id)

### `tests/test_bulk_scanner.py` additions
- Scanner records unrecognized files to DB (not just skips them)
- `ScanSummary.unrecognized_count` is correct after scan
- Supported files are NOT recorded as unrecognized
- Unrecognized files with `status='unrecognized'` are excluded from worker queue
- Re-running scan on same path upserts record (doesn't duplicate)

### `tests/test_database.py` additions
- `get_unrecognized_files()` pagination works correctly
- `get_unrecognized_stats()` `by_category` counts are accurate
- Schema migration adds columns without destroying existing data

---

## Done Criteria

- [ ] `python-magic` + `libmagic1` installed in Docker container, `docker-compose build` succeeds
- [ ] `core/mime_classifier.py` exists with MIME map and `classify()` function
- [ ] Bulk scan records unrecognized files to `bulk_files` with `status='unrecognized'`,
      correct `mime_type`, and correct `file_category`
- [ ] Supported files (docx, pdf, etc.) are never written as `unrecognized`
- [ ] Unrecognized files do NOT enter the worker conversion queue
- [ ] `GET /api/unrecognized` returns paginated file list with filter support
- [ ] `GET /api/unrecognized/stats` returns counts by category and format
- [ ] `GET /api/unrecognized/export` returns downloadable CSV
- [ ] `/unrecognized` page loads, shows stats bar and category cards
- [ ] Category filter, format filter, and job filter all work on the UI page
- [ ] "Export CSV" button downloads correctly from UI
- [ ] Bulk job results page shows `❓ N unrecognized` pill when count > 0
- [ ] Pill links to `/unrecognized?job_id=<id>` correctly
- [ ] MCP tool `list_unrecognized` registered and callable
- [ ] All new tests pass
- [ ] No regressions in existing 543 tests
- [ ] CLAUDE.md updated, version tagged v0.8.2

---

## Architecture Reminders (Carry-Forward)

All existing rules from CLAUDE.md apply. Key ones relevant to this phase:

- **No Pandoc, no SPA** — vanilla HTML + fetch for the new UI page
- **Fail gracefully** — MIME detection failure must not crash the scanner or mark a file
  as `failed`. If `python-magic` throws, log the error and write `mime_type=NULL`,
  `file_category='unknown'`. Record the file as unrecognized anyway.
- **structlog** — use `structlog.get_logger(__name__)` in all new modules
- **aiosqlite pattern** — `async with aiosqlite.connect(path) as conn`, never the
  two-line form
- **Format registry** — unrecognized files bypass the registry entirely; do not add
  a "catch-all" handler to the registry
- **Meilisearch graceful degradation** — unrecognized files are never sent to
  Meilisearch; no Meilisearch code paths touched in this phase
- **MCP tool docstrings are functional** — write them for Claude, not for humans
- **APPEND mcp_server/tools.py** — do not replace it

---

## Session Strategy

This phase is small enough to complete in a single Claude Code session.
Target sequence:

1. Dockerfile + requirements (`libmagic1`, `python-magic`)
2. `core/mime_classifier.py` + tests
3. DB schema migration (`mime_type`, `file_category` columns)
4. `core/database.py` helpers (`get_unrecognized_files`, `get_unrecognized_stats`)
5. `core/bulk_scanner.py` changes (`_record_unrecognized`, `ScanSummary` field)
6. `api/routes/unrecognized.py` + register in `main.py`
7. `static/unrecognized.html`
8. `static/bulk.html` pill addition
9. `mcp_server/tools.py` + `server.py` tool count update
10. Remaining tests
11. Update CLAUDE.md, tag v0.8.2

If the session runs long, the natural split point is after step 6 (API complete,
UI not started). The API can be tested independently before the UI is built.
