# MarkFlow Phase 7 Build Prompt
# Bulk Conversion, Adobe Indexing, Meilisearch Search, Cowork Integration

**Version:** v1.0  
**Targets:** v0.7.0 tag  
**Prerequisite:** Phase 6 complete — 378 tests passing, full UI live, tagged v0.6.0

---

## 0. Read First

Load `CLAUDE.md` before writing a single line. Phase 7 is the largest phase in the project.
It introduces three new subsystems that must work together: the bulk pipeline, the Adobe indexer,
and the Meilisearch search layer. Read the full CLAUDE.md gotchas section — the Phase 6 changes
to preferences, history pagination, and SSE queues all have downstream implications here.

**This phase does not touch existing single-file conversion logic.** The `ConversionOrchestrator`
from earlier phases is reused as-is inside the bulk worker. Do not refactor it. Build around it.

---

## 1. Phase 7 Scope

| Track | Deliverable |
|-------|-------------|
| A | Database schema extensions for bulk jobs, file tracking, and Adobe index |
| B | Bulk scanner — file discovery, mtime-based incremental tracking |
| C | Bulk worker — async worker pool, per-file conversion, graceful pause/resume/cancel |
| D | Adobe indexer — Level 2 indexing for .ai, .psd, .indd, .aep, .prproj, .xd |
| E | Meilisearch integration — Docker service, index schema, indexing pipeline, search API |
| F | Search UI — `static/search.html` |
| G | Bulk job UI — `static/bulk.html` |
| H | Cowork API — search endpoint optimized for AI assistant consumption |
| I | Tests — full coverage for all new subsystems |

---

## 2. Architecture Decisions (Locked)

These decisions were made before build. Do not revisit them during implementation.
If a decision causes a problem, document it in CLAUDE.md and flag it — do not quietly change the architecture.

**Source share:**
- Mounted into the container at `/mnt/source` (read-only)
- SMB/CIFS — Docker handles the mount externally. MarkFlow sees a POSIX path.
- MarkFlow never writes to `/mnt/source`. Any write attempt is a bug.

**Output repository:**
- Written to `/mnt/output-repo` (read-write)
- Mirrors the source directory structure exactly.
  `source: /mnt/source/dept/finance/Q4_Report.docx`
  `output: /mnt/output-repo/dept/finance/Q4_Report.md`
- Sidecar JSON, images, and OCR debug files go in a `_markflow/` subdirectory alongside each `.md`:
  `output: /mnt/output-repo/dept/finance/_markflow/Q4_Report.styles.json`
- The source share is never modified. The output repo is a derived artifact.

**Incremental processing:**
- A file is considered "needs processing" if:
  - It has never been seen before (not in `bulk_files` table), OR
  - Its `mtime` on disk differs from the stored `mtime` in `bulk_files`
- Content hashing is NOT used for change detection (too expensive at scale). mtime only.
- Already-converted, unchanged files are skipped silently (logged at DEBUG level, not INFO).

**Concurrency:**
- Worker pool size: `BULK_WORKER_COUNT` env var (default 4). Max 16.
- One asyncio task per worker. Workers pull from an asyncio Queue fed by the scanner.
- CPU-bound work (OCR, image extraction) uses `asyncio.to_thread()` inside each worker.
- The bulk job runs in the background — it does not block API responses.

**Adobe indexing levels:**
- Level 2 only in this phase: metadata (XMP/EXIF via pyexiftool) + text layer extraction.
  - `.ai`: treat as PDF (AI files contain an embedded PDF stream). Use `pdfplumber`.
  - `.psd`: use `psd-tools` to extract text layers.
  - `.indd`, `.aep`, `.prproj`, `.xd`: exiftool metadata only. No text extraction.
- Level 3 (OCR + AI vision pass) is deferred. The schema must accommodate it but the code does not implement it.
- Adobe files are indexed into `adobe_index` table AND a separate Meilisearch index (`adobe-files`).
- Adobe files are never converted to Markdown (they're indexed, not converted).

**Meilisearch:**
- Runs as a separate Docker service (`meilisearch:latest`) on port 7700.
- Two indexes: `documents` (converted markdown files) and `adobe-files` (Adobe index entries).
- MarkFlow talks to Meilisearch via its HTTP API using `httpx` (no heavy SDK).
- If Meilisearch is unavailable, bulk conversion continues — indexing failures are logged and
  retried on the next run, not treated as conversion failures.
- Master key: `MEILI_MASTER_KEY` env var. Required in production; optional in dev (use empty string).

**Cowork integration:**
- MarkFlow exposes `GET /api/cowork/search` — a search endpoint purpose-built for AI assistant use.
- Cowork queries this endpoint, gets ranked results with full `.md` file content inline
  (up to 5,000 tokens per result, top 10 results). Cowork does reasoning; MarkFlow does retrieval.
- No authentication in Phase 7. Authentication is a Phase 8+ concern.

---

## 3. Track A — Database Schema Extensions

### `core/database.py` (modify)

Add three new tables. Existing tables are not modified.

#### Table: `bulk_jobs`

```sql
CREATE TABLE IF NOT EXISTS bulk_jobs (
    id              TEXT PRIMARY KEY,           -- UUID
    source_path     TEXT NOT NULL,              -- /mnt/source or subfolder
    output_path     TEXT NOT NULL,              -- /mnt/output-repo or subfolder
    status          TEXT NOT NULL DEFAULT 'pending',
                                                -- pending | scanning | running | paused
                                                -- | completed | cancelled | failed
    worker_count    INTEGER NOT NULL DEFAULT 4,
    include_adobe   INTEGER NOT NULL DEFAULT 1, -- boolean: index Adobe files
    fidelity_tier   INTEGER NOT NULL DEFAULT 2,
    ocr_mode        TEXT NOT NULL DEFAULT 'auto',
                                                -- auto | force | skip
    total_files     INTEGER,                    -- set after scan completes
    converted       INTEGER NOT NULL DEFAULT 0,
    skipped         INTEGER NOT NULL DEFAULT 0, -- unchanged since last run
    failed          INTEGER NOT NULL DEFAULT 0,
    adobe_indexed   INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT,                       -- ISO-8601
    completed_at    TEXT,
    paused_at       TEXT,
    error_msg       TEXT                        -- set if status=failed
);
```

#### Table: `bulk_files`

```sql
CREATE TABLE IF NOT EXISTS bulk_files (
    id              TEXT PRIMARY KEY,           -- UUID
    job_id          TEXT NOT NULL REFERENCES bulk_jobs(id),
    source_path     TEXT NOT NULL,              -- absolute path on /mnt/source
    output_path     TEXT,                       -- absolute path on /mnt/output-repo (null until converted)
    file_ext        TEXT NOT NULL,              -- .docx, .pdf, .ai, etc.
    file_size_bytes INTEGER,
    source_mtime    REAL,                       -- Unix timestamp float
    stored_mtime    REAL,                       -- mtime at time of last successful conversion
    content_hash    TEXT,                       -- SHA-256 of output .md (null for Adobe files)
    status          TEXT NOT NULL DEFAULT 'pending',
                                                -- pending | converting | converted | skipped
                                                -- | failed | adobe_indexed | adobe_failed
    error_msg       TEXT,
    converted_at    TEXT,
    indexed_at      TEXT,
    UNIQUE(job_id, source_path)
);
CREATE INDEX IF NOT EXISTS idx_bulk_files_job_status ON bulk_files(job_id, status);
CREATE INDEX IF NOT EXISTS idx_bulk_files_source_path ON bulk_files(source_path);
```

#### Table: `adobe_index`

```sql
CREATE TABLE IF NOT EXISTS adobe_index (
    id              TEXT PRIMARY KEY,           -- UUID
    source_path     TEXT NOT NULL UNIQUE,       -- absolute path on /mnt/source
    file_ext        TEXT NOT NULL,              -- .ai, .psd, .indd, .aep, .prproj, .xd
    file_size_bytes INTEGER,
    metadata        TEXT,                       -- JSON: XMP/EXIF via exiftool
    text_layers     TEXT,                       -- JSON array of extracted text strings (null for metadata-only formats)
    indexing_level  INTEGER NOT NULL DEFAULT 2, -- 2 = metadata+text, 3 = OCR+AI (future)
    meili_indexed   INTEGER NOT NULL DEFAULT 0, -- boolean
    indexed_at      TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_adobe_index_ext ON adobe_index(file_ext);
```

#### New DB helper functions

Add to `core/database.py`:

- `create_bulk_job(source_path, output_path, worker_count, include_adobe, fidelity_tier, ocr_mode) -> str` — returns job_id
- `get_bulk_job(job_id) -> dict | None`
- `list_bulk_jobs(limit=20) -> list[dict]`
- `update_bulk_job_status(job_id, status, **fields)` — updates status + any provided fields
- `upsert_bulk_file(job_id, source_path, file_ext, file_size_bytes, source_mtime) -> str` — insert or update, returns file_id
- `get_bulk_files(job_id, status=None, limit=None) -> list[dict]`
- `update_bulk_file(file_id, **fields)` — update any combination of status/output_path/content_hash/error_msg/converted_at/indexed_at/stored_mtime
- `get_unprocessed_bulk_files(job_id) -> list[dict]` — status=pending AND (stored_mtime IS NULL OR source_mtime != stored_mtime)
- `upsert_adobe_index(source_path, file_ext, file_size_bytes, metadata, text_layers) -> str` — returns entry id
- `get_adobe_index_entry(source_path) -> dict | None`
- `get_unindexed_adobe_entries(limit=100) -> list[dict]` — meili_indexed=0

### Track A Done Criteria

- [ ] All three tables created on startup (add to schema init in `core/database.py`)
- [ ] All helper functions implemented and covered by unit tests
- [ ] Existing tables and helpers are not modified
- [ ] `docker-compose up` creates the new tables cleanly on first run

---

## 4. Track B — Bulk Scanner

### `core/bulk_scanner.py` (new file)

Responsible for walking the source directory, discovering convertible files, and recording them
into `bulk_files`. The scanner runs as a coroutine — it yields control frequently so the API
remains responsive during large directory walks.

#### Supported extensions

**Conversion targets** (will be converted to Markdown):
```python
CONVERTIBLE_EXTENSIONS = {
    ".docx", ".doc",
    ".pdf",
    ".pptx", ".ppt",
    ".xlsx", ".xls",
    ".csv", ".tsv",
}
```

**Adobe index targets** (will be indexed but not converted):
```python
ADOBE_EXTENSIONS = {
    ".ai", ".psd", ".indd", ".aep", ".prproj", ".xd"
}
```

All other extensions are silently skipped (logged at DEBUG).

#### `BulkScanner` class

```python
class BulkScanner:
    def __init__(self, job_id: str, source_path: Path, db_path: str):
        ...

    async def scan(self) -> ScanResult:
        """
        Walk source_path recursively. For each file:
          1. Check extension — skip if not in CONVERTIBLE_EXTENSIONS | ADOBE_EXTENSIONS
          2. Get mtime and size
          3. Call upsert_bulk_file() — inserts new or updates existing record
          4. Yield control every 1000 files (await asyncio.sleep(0))
        Returns ScanResult with total counts.
        """

    async def get_pending_files(self) -> AsyncIterator[BulkFileRecord]:
        """
        Yield files that need processing (new or mtime-changed).
        Does NOT yield already-converted unchanged files.
        """
```

#### `ScanResult` dataclass

```python
@dataclass
class ScanResult:
    job_id: str
    total_discovered: int
    convertible_count: int
    adobe_count: int
    skipped_count: int       # already converted and unchanged
    new_count: int           # never seen before
    changed_count: int       # mtime differs from stored_mtime
    scan_duration_ms: int
```

#### Failure handling

- A directory that cannot be read (permissions) → log warning with path, continue walking siblings.
- A file that cannot be stat'd → log warning, skip file, continue.
- The scanner never raises. `scan()` always returns a `ScanResult`, even if empty.

### Track B Done Criteria

- [ ] `BulkScanner.scan()` walks a directory tree and upserts all discovered files
- [ ] Files not in supported extensions are silently skipped
- [ ] Already-converted unchanged files are marked `skipped` and not re-queued
- [ ] Changed files (mtime differs) are re-queued for conversion
- [ ] `scan()` yields control every 1000 files (verified by test with mock sleep)
- [ ] Permission errors on subdirectories are logged and do not stop the scan
- [ ] `ScanResult` counts are accurate

---

## 5. Track C — Bulk Worker

### `core/bulk_worker.py` (new file)

The worker pool pulls files from a queue and processes them. Workers reuse the existing
`ConversionOrchestrator` for convertible files and call the `AdobeIndexer` for Adobe files.

#### `BulkJob` class

```python
class BulkJob:
    def __init__(self, job_id: str, source_path: Path, output_path: Path,
                 worker_count: int, fidelity_tier: int, ocr_mode: str,
                 include_adobe: bool):
        self.job_id = job_id
        self._queue: asyncio.Queue[BulkFileRecord | None] = asyncio.Queue()
        self._pause_event: asyncio.Event = asyncio.Event()
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()  # not paused initially
        ...

    async def run(self) -> None:
        """
        Full job lifecycle:
          1. Update job status → 'scanning'
          2. Run BulkScanner.scan() — populate bulk_files table, get ScanResult
          3. Update job: total_files, status → 'running'
          4. Enqueue all pending BulkFileRecords into self._queue
          5. Enqueue N None sentinels (one per worker) to signal completion
          6. Start worker_count worker tasks
          7. Await all workers
          8. Update job: status → 'completed' (or 'failed' if fatal error)
          9. Emit final SSE event (see Track C SSE section)
        """

    async def _worker(self, worker_id: int) -> None:
        """
        Pull from queue until sentinel (None) received.
        On each file:
          1. Check cancel event — if set, drain queue silently and return
          2. Wait on pause event (blocks if job is paused)
          3. Process file: convert or Adobe-index
          4. Update bulk_files record
          5. Update bulk_jobs counters (converted/skipped/failed/adobe_indexed)
          6. Emit SSE event
        """

    async def pause(self) -> None:
        """Clear pause event. Workers block at step 2 above."""

    async def resume(self) -> None:
        """Set pause event. Blocked workers continue."""

    async def cancel(self) -> None:
        """Set cancel event. Workers drain queue and exit."""
```

#### Output path mapping

```python
def _map_output_path(source_file: Path, source_root: Path, output_root: Path) -> Path:
    """
    Maps source path to mirrored output path.
    source_root: /mnt/source
    source_file: /mnt/source/dept/finance/Q4_Report.docx
    output_root: /mnt/output-repo
    returns:     /mnt/output-repo/dept/finance/Q4_Report.md
    """
    relative = source_file.relative_to(source_root)
    return output_root / relative.with_suffix(".md")
```

#### Sidecar path mapping

Sidecar files go in `_markflow/` subdirectory alongside the `.md`:
```python
def _map_sidecar_dir(output_md_path: Path) -> Path:
    """
    output_md_path: /mnt/output-repo/dept/finance/Q4_Report.md
    returns:        /mnt/output-repo/dept/finance/_markflow/
    """
    return output_md_path.parent / "_markflow"
```

#### Conversion flow per file

For convertible files:
1. Resolve output path via `_map_output_path()`
2. Create output directory tree (`mkdir -p`)
3. Create sidecar dir via `_map_sidecar_dir()`
4. Call `ConversionOrchestrator.convert_file(source_path, output_path, sidecar_dir, fidelity_tier)`
5. On success: update `bulk_files` with `status=converted`, `stored_mtime=source_mtime`, `content_hash`
6. On failure: update `bulk_files` with `status=failed`, `error_msg`; increment `bulk_jobs.failed`

For Adobe files:
1. Call `AdobeIndexer.index_file(source_path)` (Track D)
2. On success: update `bulk_files` with `status=adobe_indexed`; increment `bulk_jobs.adobe_indexed`
3. On failure: update `bulk_files` with `status=adobe_failed`, `error_msg`; increment `bulk_jobs.failed`

After each successful conversion: call `SearchIndexer.index_document(output_md_path)` (Track E).
If Meilisearch is unavailable, log warning, do not fail the file.

#### Job registry

```python
# In core/bulk_worker.py module level
_active_jobs: dict[str, BulkJob] = {}

def get_active_job(job_id: str) -> BulkJob | None: ...
def register_job(job: BulkJob) -> None: ...
def deregister_job(job_id: str) -> None: ...
```

#### SSE progress events (bulk-specific)

The bulk job emits SSE events to a queue keyed by `job_id` in a separate registry from
the single-file batch queues (to avoid key collisions). Use the same pattern as Phase 6 SSE
but a new module-level dict in `bulk_worker.py`: `_bulk_progress_queues`.

Event types:

```
event: scan_complete
data: {"job_id": "...", "total": 84231, "convertible": 78450,
       "adobe": 4821, "skipped": 22000, "new": 56450, "changed": 5781}

event: file_converted
data: {"job_id": "...", "file_id": "...", "source_path": "dept/finance/Q4.docx",
       "status": "converted", "duration_ms": 840, "tier": 2,
       "converted": 1200, "total": 56450}

event: file_skipped
data: {"job_id": "...", "converted": 1201, "skipped": 22001, "total": 56450}
(Note: skipped events are batched — emit one event per 100 skipped files, not per file)

event: file_failed
data: {"job_id": "...", "file_id": "...", "source_path": "...",
       "error": "Password-protected PDF", "failed": 3}

event: adobe_indexed
data: {"job_id": "...", "file_id": "...", "source_path": "...",
       "format": ".psd", "adobe_indexed": 45}

event: job_paused
data: {"job_id": "...", "converted": 1200, "remaining": 55250}

event: job_resumed
data: {"job_id": "..."}

event: job_complete
data: {"job_id": "...", "converted": 56200, "skipped": 22000,
       "failed": 250, "adobe_indexed": 4821, "duration_ms": 3600000}

event: done
data: {}
```

### `api/routes/bulk.py` (new file)

Router with prefix `/api/bulk`. Mount in `main.py`.

**`POST /api/bulk/jobs`** — create and start a bulk job

Request body:
```json
{
  "source_path": "/mnt/source",
  "output_path": "/mnt/output-repo",
  "worker_count": 4,
  "fidelity_tier": 2,
  "ocr_mode": "auto",
  "include_adobe": true
}
```

Validation:
- `source_path` must exist and be readable. Return 422 if not.
- `output_path` parent must exist. Return 422 if not (MarkFlow creates subdirs but not the root).
- `worker_count` must be 1–16.
- Only one job can be in `running` status at a time. Return 409 if a job is already running.

Response: `{"job_id": "...", "stream_url": "/api/bulk/jobs/{id}/stream"}`

Start the job in the background: `asyncio.create_task(job.run())`.

**`GET /api/bulk/jobs`** — list jobs (most recent 20)

**`GET /api/bulk/jobs/{job_id}`** — job status and counters

**`GET /api/bulk/jobs/{job_id}/stream`** — SSE stream (same pattern as Phase 6 batch stream)

**`POST /api/bulk/jobs/{job_id}/pause`** — pause running job

**`POST /api/bulk/jobs/{job_id}/resume`** — resume paused job

**`POST /api/bulk/jobs/{job_id}/cancel`** — cancel running or paused job

**`GET /api/bulk/jobs/{job_id}/files`** — paginated file list for a job
- Query params: `status`, `ext`, `page`, `per_page`

**`GET /api/bulk/jobs/{job_id}/errors`** — all failed files for a job (no pagination, max 1000)

### Track C Done Criteria

- [ ] `POST /api/bulk/jobs` starts a job and returns `job_id`
- [ ] Workers run in parallel up to `worker_count`
- [ ] Each converted file is written to the mirrored output path
- [ ] Sidecar files go in `_markflow/` subdirectory
- [ ] Pause/resume stops and restarts workers correctly
- [ ] Cancel drains the queue and sets all pending files to cancelled status
- [ ] Failed file increments `bulk_jobs.failed` but does not stop the job
- [ ] Source share is never written to (verified in test with read-only mock)
- [ ] SSE stream emits correct events in correct order
- [ ] 409 returned if a job is already running when POST is called

---

## 6. Track D — Adobe Indexer

### `core/adobe_indexer.py` (new file)

Indexes Adobe creative files at Level 2: metadata + text layer extraction.

#### Dependencies

Add to `requirements.txt`:
- `pyexiftool` — Python wrapper for exiftool
- `psd-tools` — PSD text layer extraction

Add to `Dockerfile`:
- `apt-get install -y exiftool` (package: `libimage-exiftool-perl`)

#### `AdobeIndexer` class

```python
class AdobeIndexer:
    def __init__(self, db_path: str):
        ...

    async def index_file(self, source_path: Path) -> AdobeIndexResult:
        """
        Dispatch by extension:
          .ai   → _index_ai()
          .psd  → _index_psd()
          .indd / .aep / .prproj / .xd → _index_metadata_only()
        Upserts result into adobe_index table.
        Returns AdobeIndexResult.
        """

    async def _extract_metadata(self, path: Path) -> dict:
        """
        Run exiftool on path. Returns dict of XMP/EXIF fields.
        Fields to extract at minimum:
          - FileName, FileSize, FileModifyDate, FileType, MIMEType
          - Creator, Author, Title, Subject, Keywords, Description
          - CreateDate, ModifyDate
          - ColorSpace, BitsPerSample, ImageWidth, ImageHeight (if applicable)
          - XMP:* fields (all)
        Strip binary/null values. Truncate any single value > 2000 chars.
        """

    async def _index_ai(self, path: Path) -> tuple[dict, list[str]]:
        """
        .ai files contain an embedded PDF stream.
        Use pdfplumber to extract text (same as pdf_handler.py ingest).
        Return (metadata_dict, text_list).
        text_list: list of text strings, one per page.
        If pdfplumber fails (malformed AI): return (metadata, []) — do not raise.
        """

    async def _index_psd(self, path: Path) -> tuple[dict, list[str]]:
        """
        Use psd-tools to open PSD and extract text layers.
        Walk all layers recursively. For layers with kind == 'type':
          extract layer.text_data.text (the raw text string).
        Return (metadata_dict, text_list).
        If psd-tools fails: return (metadata, []) — do not raise.
        """

    async def _index_metadata_only(self, path: Path) -> tuple[dict, list[str]]:
        """
        .indd, .aep, .prproj, .xd — exiftool metadata only, no text extraction.
        Return (metadata_dict, []).
        """
```

#### `AdobeIndexResult` dataclass

```python
@dataclass
class AdobeIndexResult:
    source_path: Path
    file_ext: str
    file_size_bytes: int
    metadata: dict
    text_layers: list[str]
    indexing_level: int       # always 2 in this phase
    success: bool
    error_msg: str | None
    duration_ms: int
```

#### Text layer storage

`text_layers` is stored in `adobe_index.text_layers` as a JSON array of strings. Each string
is a raw text block from one layer or page. Whitespace is preserved but not normalized.
Maximum total text size: 500 KB per file. Truncate cleanest (drop later layers first) if exceeded.

#### Error handling

Every indexing method catches all exceptions. A corrupt file produces an `AdobeIndexResult`
with `success=False` and the error message. Never raises out of `index_file()`.

### Track D Done Criteria

- [ ] `.ai` files: metadata extracted + text from embedded PDF stream
- [ ] `.psd` files: metadata extracted + text layers from all type layers
- [ ] `.indd`, `.aep`, `.prproj`, `.xd`: metadata only, no text extraction, no error
- [ ] Corrupt/unreadable file returns `success=False`, does not raise
- [ ] Results upserted into `adobe_index` table
- [ ] Text layers > 500 KB are truncated (last layers dropped first)
- [ ] `exiftool` subprocess error (tool not found) returns `success=False` with clear message

---

## 7. Track E — Meilisearch Integration

### 7.1 Docker Compose

#### `docker-compose.yml` (modify)

Add Meilisearch service:

```yaml
services:
  meilisearch:
    image: getmeili/meilisearch:latest
    ports:
      - "7700:7700"
    environment:
      - MEILI_MASTER_KEY=${MEILI_MASTER_KEY:-}
      - MEILI_ENV=development
    volumes:
      - meilisearch-data:/meili_data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7700/health"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  meilisearch-data:
```

Add `MEILI_HOST` and `MEILI_MASTER_KEY` to `.env.example`:
```
MEILI_HOST=http://meilisearch:7700
MEILI_MASTER_KEY=
```

MarkFlow app uses `MEILI_HOST` env var (default `http://localhost:7700` locally,
`http://meilisearch:7700` in Docker).

### 7.2 Search Client

#### `core/search_client.py` (new file)

Thin async client wrapping Meilisearch HTTP API via `httpx`. No SDK dependency.

```python
class MeilisearchClient:
    def __init__(self, host: str, master_key: str = ""):
        self._host = host.rstrip("/")
        self._headers = {"Authorization": f"Bearer {master_key}"} if master_key else {}

    async def health_check(self) -> bool:
        """GET /health → True if 200, False otherwise. Never raises."""

    async def create_index(self, uid: str, primary_key: str) -> None:
        """POST /indexes — idempotent (200 or 202 both ok)."""

    async def update_index_settings(self, uid: str, settings: dict) -> None:
        """PATCH /indexes/{uid}/settings"""

    async def add_documents(self, uid: str, documents: list[dict]) -> str:
        """POST /indexes/{uid}/documents — returns task_uid."""

    async def delete_document(self, uid: str, doc_id: str) -> None:
        """DELETE /indexes/{uid}/documents/{doc_id}"""

    async def search(self, uid: str, query: str, options: dict | None = None) -> dict:
        """POST /indexes/{uid}/search — returns raw Meilisearch response dict."""

    async def get_index_stats(self, uid: str) -> dict:
        """GET /indexes/{uid}/stats"""

    async def wait_for_task(self, task_uid: str, timeout_ms: int = 5000) -> bool:
        """Poll GET /tasks/{task_uid} until succeeded/failed. Returns True if succeeded."""
```

All methods treat Meilisearch as optional infrastructure. If the host is unreachable,
methods return safe defaults (`health_check → False`, `search → {"hits": []}`) and log a warning.
They never raise connection errors to callers.

### 7.3 Search Indexer

#### `core/search_indexer.py` (new file)

Manages index creation, schema setup, and document indexing.

#### Index: `documents`

Schema and settings:
```python
DOCUMENTS_INDEX_SETTINGS = {
    "searchableAttributes": [
        "title",
        "content",
        "headings",
        "source_filename"
    ],
    "filterableAttributes": [
        "source_format",
        "fidelity_tier",
        "has_ocr",
        "job_id",
        "relative_path_prefix"
    ],
    "sortableAttributes": [
        "converted_at",
        "file_size_bytes"
    ],
    "displayedAttributes": [
        "id", "title", "source_filename", "source_format", "relative_path",
        "output_path", "source_path", "content_preview", "headings",
        "fidelity_tier", "has_ocr", "converted_at", "file_size_bytes", "job_id"
    ],
    "rankingRules": [
        "words", "typo", "proximity", "attribute", "sort", "exactness"
    ]
}
```

Document shape (what gets indexed):
```python
{
    "id": "<sha256 of source_path>[:16]",  # Meilisearch primary key
    "title": "<H1 from markdown frontmatter title field>",
    "source_filename": "Q4_Report.docx",
    "source_format": "docx",
    "source_path": "/mnt/source/dept/finance/Q4_Report.docx",
    "output_path": "/mnt/output-repo/dept/finance/Q4_Report.md",
    "relative_path": "dept/finance/Q4_Report.md",
    "relative_path_prefix": "dept/finance",  # for folder-scoped filtering
    "content": "<full markdown text, stripped of YAML frontmatter and image refs>",
    "content_preview": "<first 500 chars of content>",
    "headings": ["Introduction", "Q4 Results", "Appendix"],  # all H1-H3 text
    "fidelity_tier": 2,
    "has_ocr": false,
    "converted_at": "2026-03-21T14:32:01Z",
    "file_size_bytes": 45231,
    "job_id": "<bulk_job_id>"
}
```

Content extraction for indexing:
- Read the `.md` file from `output_path`
- Parse YAML frontmatter with `core/metadata.parse_frontmatter()`
- Strip frontmatter, strip image references (`![...](...)`), strip inline code blocks
- Extract all H1–H3 text as the `headings` list
- Store remaining text as `content` (no truncation — Meilisearch handles large documents)
- `content_preview`: first 500 chars of content (for display in search results)

#### Index: `adobe-files`

Settings:
```python
ADOBE_INDEX_SETTINGS = {
    "searchableAttributes": ["title", "text_content", "source_filename", "keywords"],
    "filterableAttributes": ["file_ext", "creator", "job_id"],
    "sortableAttributes": ["indexed_at"],
    "displayedAttributes": [
        "id", "source_filename", "file_ext", "source_path", "title",
        "creator", "keywords", "text_preview", "indexed_at"
    ]
}
```

Adobe document shape:
```python
{
    "id": "<sha256 of source_path>[:16]",
    "source_filename": "Logo_Final.psd",
    "file_ext": ".psd",
    "source_path": "/mnt/source/creative/Logo_Final.psd",
    "title": "<metadata Title or filename stem>",
    "creator": "<metadata Creator/Author>",
    "keywords": "<metadata Keywords as string>",
    "text_content": "<all text_layers joined with newline>",
    "text_preview": "<first 300 chars of text_content>",
    "indexed_at": "ISO-8601"
}
```

#### `SearchIndexer` class

```python
class SearchIndexer:
    def __init__(self, client: MeilisearchClient):
        ...

    async def ensure_indexes(self) -> None:
        """Create both indexes with correct settings if they don't exist."""

    async def index_document(self, md_path: Path, job_id: str) -> bool:
        """
        Read md_path, extract content, build document dict, add to 'documents' index.
        Returns True if indexed, False if Meilisearch unavailable.
        """

    async def index_adobe_file(self, adobe_result: AdobeIndexResult, job_id: str) -> bool:
        """
        Build adobe document dict from AdobeIndexResult, add to 'adobe-files' index.
        Returns True if indexed, False if Meilisearch unavailable.
        """

    async def remove_document(self, source_path: str) -> None:
        """Remove document from 'documents' index by source_path hash."""

    async def rebuild_index(self, job_id: str | None = None) -> RebuildStatus:
        """
        Walk all converted files in bulk_files (for job_id if provided, else all).
        Re-index everything. Used for recovery after Meilisearch data loss.
        """
```

### 7.4 Search API

#### `api/routes/search.py` (new file)

Router with prefix `/api/search`. Mount in `main.py`.

**`GET /api/search`** — full-text search across documents

Query params:
- `q` — search query (required, min 2 chars)
- `index` — `documents` (default) or `adobe-files`
- `format` — filter by source format (documents index only)
- `path_prefix` — filter by relative path prefix (documents index only)
- `page` — 1-indexed (default 1)
- `per_page` — 5, 10, 25 (default 10)
- `highlight` — `true`/`false` (default true) — include Meilisearch highlight snippets

Response:
```json
{
  "query": "Q4 financial results",
  "index": "documents",
  "total_hits": 23,
  "page": 1,
  "per_page": 10,
  "processing_time_ms": 4,
  "hits": [
    {
      "id": "...",
      "title": "Q4 Report",
      "source_filename": "Q4_Report.docx",
      "source_format": "docx",
      "source_path": "/mnt/source/dept/finance/Q4_Report.docx",
      "output_path": "/mnt/output-repo/dept/finance/Q4_Report.md",
      "relative_path": "dept/finance/Q4_Report.md",
      "content_preview": "...",
      "highlight": "<em>Q4</em> financial results summary...",
      "fidelity_tier": 2,
      "converted_at": "2026-03-21T14:32:01Z"
    }
  ]
}
```

If Meilisearch is unavailable: return 503 with `{"error": "search_unavailable", "message": "Search index is not available. Check /debug for status."}`.
If query < 2 chars: return 422.

**`GET /api/search/index/status`** — index health and stats

```json
{
  "available": true,
  "documents": {
    "index": "documents",
    "document_count": 56200,
    "is_indexing": false
  },
  "adobe_files": {
    "index": "adobe-files",
    "document_count": 4821,
    "is_indexing": false
  }
}
```

**`POST /api/search/index/rebuild`** — trigger a full index rebuild

Request body: `{"job_id": "..." }` (optional — rebuild for a specific job only)
Starts rebuild in background. Returns `{"task_id": "..."}` immediately.
This is a destructive admin operation — document it clearly.

### Track E Done Criteria

- [ ] Meilisearch service starts via `docker-compose up`
- [ ] `ensure_indexes()` creates both indexes with correct settings on startup
- [ ] `GET /api/search?q=Q4+results` returns ranked hits with highlights
- [ ] `GET /api/search?q=logo&index=adobe-files` searches Adobe index
- [ ] `GET /api/search/index/status` reflects true document count
- [ ] If Meilisearch is down, search returns 503 (does not crash the app)
- [ ] Index rebuild works via `POST /api/search/index/rebuild`
- [ ] Documents indexed during bulk conversion are findable in search

---

## 8. Track F — Search UI

### `static/search.html` (new)

A dedicated search page. Uses `markflow.css` and `app.js`. Nav bar included.

Layout:
```
┌──────────────────────────────────────────────────────────┐
│  MarkFlow          [Convert] [Bulk] [History] [Settings]  │
├──────────────────────────────────────────────────────────┤
│                                                           │
│     🔍  ___________________________________  [Search]     │
│         56,200 documents indexed                         │
│                                                           │
│  [All formats ▾]  [All folders ▾]  [● Documents  ○ Adobe]│
├──────────────────────────────────────────────────────────┤
│  23 results for "Q4 financial results"  (4ms)            │
│  ──────────────────────────────────────────────────────  │
│  📄 Q4 Report                              DOCX          │
│     dept/finance/Q4_Report.md                            │
│     ...the <em>Q4</em> financial results show a 12%...  │
│     [Open Original ↗]  [View Markdown ↗]                │
│                                                          │
│  📄 Q4 Budget Summary                      XLSX          │
│     dept/finance/Q4_Budget.md                            │
│     ...                                                  │
│  ──────────────────────────────────────────────────────  │
│  ← 1 2 3 →                                              │
└──────────────────────────────────────────────────────────┘
```

Behaviors:
- Search input debounces 400ms before firing request (search is expensive, don't hammer).
- Enter key fires immediately.
- URL query param `?q=...` — search term is bookmarkable and loaded on page open.
- Format filter and index toggle (Documents / Adobe) update URL params.
- Result highlight: render Meilisearch `_formatted` field as HTML (the API returns `<em>` tags).
  Use `innerHTML` only for the highlight snippet — not for other fields (XSS risk).
- "Open Original" link: `source_path` is a server-side path (not a web URL). Show it as text
  in the result, not as a clickable link (it's a filesystem path, not accessible from the browser).
  For the "View Markdown" link: link to `/api/bulk/jobs/{job_id}/file?path={relative_path}`
  (add this endpoint in Track C if not already present — it serves the raw `.md` file).
- Index status (document count) shown below search box. Fetched from `/api/search/index/status`
  on page load. If unavailable: "Search index offline — check debug dashboard".
- Empty state (no results): "No results for '{query}'" with suggested filters to try.
- Adobe results: show file extension badge, text preview, no "View Markdown" link (Adobe files
  are not converted to Markdown).

### Track F Done Criteria

- [ ] Search results appear after debounce
- [ ] Highlights render `<em>` tags correctly (not escaped)
- [ ] URL params update on search and filter change
- [ ] Page loads with pre-filled query from URL param
- [ ] Adobe index search shows `.psd`/`.ai` results with correct badges
- [ ] Index offline state shows clear message, not a crash

---

## 9. Track G — Bulk Job UI

### `static/bulk.html` (new)

Bulk job management page. Uses `markflow.css` and `app.js`. Nav bar included (add "Bulk" link to nav).

Layout — two sections:

**Section 1: Start a New Job**
```
┌──────────────────────────────────────────────────────┐
│  New Bulk Job                                        │
│  ─────────────────────────────────────────────────  │
│  Source path      [/mnt/source              ]        │
│  Output path      [/mnt/output-repo         ]        │
│  Workers          [4    ] (1–16)                     │
│  Fidelity tier    [Tier 2 ▾]                         │
│  OCR mode         [Auto ▾]                           │
│  Index Adobe      [✓]                                │
│                                                      │
│  [Start Job]                                         │
└──────────────────────────────────────────────────────┘
```

**Section 2: Job History + Active Job**

```
┌──────────────────────────────────────────────────────┐
│  Jobs                                                │
│  ─────────────────────────────────────────────────  │
│  ● RUNNING   Started 14:32  [Pause] [Cancel]         │
│    Scanning... 84,231 files found                    │
│    ████████████░░░░░░░░░░  21,450 / 56,450           │
│    Converted: 21,200  Failed: 250  Skipped: 22,000  │
│    Adobe: 1,200 indexed                              │
│                                                      │
│  ─────────────────────────────────────────────────  │
│  ✓ COMPLETED  2026-03-20  56,200 converted  [Details]│
│  ✗ FAILED     2026-03-19  [Details]                  │
└──────────────────────────────────────────────────────┘
```

Behaviors:
- Active job: open SSE stream to `/api/bulk/jobs/{id}/stream`. Update counters and progress
  bar on each event.
- Progress bar: based on `(converted + failed + skipped) / total_files`.
- During scan phase (`scan_complete` not yet received): show "Scanning..." with indeterminate bar.
- Pause button: POST `/api/bulk/jobs/{id}/pause`. Changes to "Resume" button after paused event.
- Cancel button: confirm dialog before sending POST `/api/bulk/jobs/{id}/cancel`.
- "Details" for completed/failed jobs: expands an inline panel showing file counts, duration,
  and a link to `/api/bulk/jobs/{id}/errors` for failed files.
- Start Job form: validate source_path and output_path are non-empty before submitting.
  Disable Start button if a job is already running (show tooltip: "Wait for current job to complete").
- 409 response from POST: show inline "A job is already running. Wait for it to complete."
- File error count: if > 0, show as a clickable link that downloads the errors JSON from
  `/api/bulk/jobs/{id}/errors`.

### Track G Done Criteria

- [ ] Start Job form submits and redirects to live progress view
- [ ] Running job shows SSE-driven live counters and progress bar
- [ ] Pause/resume works and updates button state
- [ ] Cancel requires confirmation, stops the job
- [ ] Completed jobs show in history with correct counts
- [ ] Failed file count is a download link when > 0
- [ ] Start button disabled while a job is running

---

## 10. Track H — Cowork API

### `api/routes/cowork.py` (new file)

Router with prefix `/api/cowork`. Mount in `main.py`.

This endpoint is purpose-built for AI assistant consumption (Cowork or similar). It differs
from the standard search endpoint in:
- Returns full `.md` file content inline (not just previews)
- Content is token-budget-aware (default 5,000 tokens per result, top 10 results)
- Response format is designed for easy LLM consumption (clean text, minimal metadata noise)

**`GET /api/cowork/search`**

Query params:
- `q` — search query (required)
- `max_results` — 1–20 (default 10)
- `max_tokens_per_doc` — 1000–10000 (default 5000)
- `format` — filter by source format (optional)
- `path_prefix` — restrict to a folder (optional)

Response:
```json
{
  "query": "Q4 financial results",
  "result_count": 3,
  "total_hits": 23,
  "token_budget_used": 12400,
  "results": [
    {
      "rank": 1,
      "title": "Q4 Report",
      "source_filename": "Q4_Report.docx",
      "source_format": "docx",
      "relative_path": "dept/finance/Q4_Report.md",
      "source_path": "/mnt/source/dept/finance/Q4_Report.docx",
      "converted_at": "2026-03-21T14:32:01Z",
      "content": "<full markdown content, truncated to max_tokens_per_doc>",
      "content_truncated": false
    }
  ]
}
```

Implementation:
1. Call `MeilisearchClient.search("documents", q, {"limit": max_results * 2})` — fetch extra
   results in case some `.md` files are unreadable.
2. For each hit: read the `.md` file from `output_path` on disk.
3. Estimate token count: `len(content) // 4` (rough 4-chars-per-token heuristic). If content
   exceeds `max_tokens_per_doc * 4` chars: truncate at nearest paragraph boundary, set
   `content_truncated: true`.
4. Accumulate results until `max_results` readable files found or hits exhausted.
5. Return results ranked by Meilisearch score.

If Meilisearch is unavailable: return 503 with message.
If a `.md` file referenced in the index no longer exists on disk: skip it (log warning),
try next hit.

**`GET /api/cowork/status`** — health check for Cowork to poll before querying

```json
{
  "available": true,
  "document_count": 56200,
  "last_indexed": "2026-03-21T14:32:01Z",
  "meilisearch_available": true
}
```

### Track H Done Criteria

- [ ] `GET /api/cowork/search?q=Q4+results` returns full `.md` content in `content` field
- [ ] Content truncated at paragraph boundary when > `max_tokens_per_doc * 4` chars
- [ ] `content_truncated: true` set correctly when truncation occurs
- [ ] Missing `.md` files are skipped gracefully (not a 500)
- [ ] 503 returned if Meilisearch is unavailable
- [ ] `GET /api/cowork/status` returns correct `document_count`

---

## 11. Health Check Extension

#### `core/health.py` (modify)

Add Meilisearch to the startup health check and `/debug/api/health` response:

```json
"meilisearch": {
  "status": "ok",
  "host": "http://meilisearch:7700",
  "documents_index_count": 56200,
  "adobe_index_count": 4821
}
```

If Meilisearch is unreachable at startup: `"status": "not_available"` — log warning but do NOT
fail startup. MarkFlow starts without Meilisearch; indexing will retry when Meilisearch comes up.

#### `static/debug.html` (modify)

Add to the health status row: Meilisearch pill with document count.
Add to Activity section: bulk job stats (running/completed/failed job counts).

---

## 12. Navigation Update

#### `static/markflow.css` + all user-facing pages (modify)

Add "Bulk" and "Search" links to the shared nav bar:
```html
<a href="/bulk.html" class="nav-link">Bulk</a>
<a href="/search.html" class="nav-link">Search</a>
```

The nav link highlighter in `app.js` already handles active state by `window.location.pathname`.
No code changes needed beyond adding the links.

---

## 13. Tests

### `tests/test_bulk_scanner.py` (new)

- [ ] `scan()` discovers all convertible files in a fixture directory tree
- [ ] Adobe files are discovered and typed correctly
- [ ] Non-supported extensions are skipped
- [ ] Permission error on subdirectory does not raise, logs warning
- [ ] `get_pending_files()` returns only new and changed files
- [ ] Already-converted unchanged files are not in pending list
- [ ] `scan()` yields control (mock `asyncio.sleep`, assert called)

### `tests/test_bulk_worker.py` (new)

- [ ] `BulkJob.run()` calls `ConversionOrchestrator` for each convertible file
- [ ] `BulkJob.run()` calls `AdobeIndexer` for each Adobe file
- [ ] Output path mirrors source path correctly
- [ ] Sidecar dir is `_markflow/` alongside output `.md`
- [ ] Failed file increments `bulk_jobs.failed`, does not stop the job
- [ ] Pause blocks workers (mock pause_event, assert workers wait)
- [ ] Cancel drains queue (assert no files processed after cancel)
- [ ] Worker count respected (assert asyncio tasks created == worker_count)
- [ ] Source path is never written to (mock filesystem writes, assert only output_path written)

### `tests/test_adobe_indexer.py` (new)

- [ ] `.ai` file: metadata extracted, text extracted via pdfplumber mock
- [ ] `.psd` file: metadata extracted, text layers extracted via psd-tools mock
- [ ] `.indd` file: metadata extracted, empty text_layers
- [ ] Corrupt `.ai` file: returns `success=False`, does not raise
- [ ] Text > 500 KB truncated (drop last layers)
- [ ] Result upserted into `adobe_index` table

### `tests/test_search.py` (new)

- [ ] `SearchIndexer.index_document()` calls `MeilisearchClient.add_documents()` with correct shape
- [ ] `SearchIndexer.index_adobe_file()` adds to `adobe-files` index
- [ ] `GET /api/search?q=test` returns 200 with `hits` array
- [ ] `GET /api/search?q=t` (too short) returns 422
- [ ] `GET /api/search?q=test` with Meilisearch unavailable returns 503
- [ ] `GET /api/search/index/status` returns document counts

### `tests/test_cowork.py` (new)

- [ ] `GET /api/cowork/search?q=Q4` returns full content in `content` field
- [ ] Content exceeding `max_tokens_per_doc * 4` chars is truncated at paragraph boundary
- [ ] `content_truncated: true` when truncated
- [ ] Missing `.md` file is skipped, next hit tried
- [ ] `GET /api/cowork/status` returns `available: true` when Meilisearch is up

### `tests/test_bulk_api.py` (new)

- [ ] `POST /api/bulk/jobs` returns `job_id` and `stream_url`
- [ ] `POST /api/bulk/jobs` returns 422 if source_path doesn't exist
- [ ] `POST /api/bulk/jobs` returns 409 if a job is already running
- [ ] `GET /api/bulk/jobs/{id}` returns correct status and counters
- [ ] `POST /api/bulk/jobs/{id}/pause` → job status changes to `paused`
- [ ] `POST /api/bulk/jobs/{id}/cancel` → job status changes to `cancelled`
- [ ] `GET /api/bulk/jobs/{id}/stream` streams SSE events

---

## 14. Environment Variables Reference

Document all new env vars in `.env.example`:

```bash
# Meilisearch
MEILI_HOST=http://localhost:7700          # http://meilisearch:7700 in Docker
MEILI_MASTER_KEY=                         # Leave empty for dev, set in production

# Bulk conversion
BULK_WORKER_COUNT=4                       # Number of parallel workers (1-16)
BULK_SOURCE_PATH=/mnt/source              # Default source path for new jobs
BULK_OUTPUT_PATH=/mnt/output-repo         # Default output path for new jobs

# Existing (for reference)
DB_PATH=markflow.db
OUTPUT_DIR=output
LOG_LEVEL=INFO
```

---

## 15. docker-compose.yml — Volume Mounts

Add to `docker-compose.yml` app service:

```yaml
volumes:
  - markflow-db:/app/data
  - ./logs:/app/logs
  - ./output:/app/output
  - /mnt/source:/mnt/source:ro          # Source share — READ ONLY
  - /mnt/output-repo:/mnt/output-repo   # Output repo — read-write
```

The `/mnt/source` and `/mnt/output-repo` paths are mount points on the Docker host.
How they're mounted on the host (SMB/CIFS, NFS, local) is outside MarkFlow's scope.
MarkFlow only cares that these paths exist and have the correct permissions.

Add a comment in `docker-compose.yml`:
```yaml
# NOTE: /mnt/source must be mounted READ-ONLY on the host before starting.
# MarkFlow will never write to /mnt/source. Any write attempt is a bug.
# Mount example (host): sudo mount -t cifs //server/share /mnt/source -o ro,credentials=/etc/smbcredentials
```

---

## 16. Done Criteria (Full Phase)

- [ ] Track A: All three new tables created, all helpers implemented and tested
- [ ] Track B: Scanner discovers files, handles permissions errors, respects mtime incremental logic
- [ ] Track C: Bulk job runs end-to-end, pause/resume/cancel work, SSE streams events
- [ ] Track D: Adobe indexer handles all six formats, errors contained
- [ ] Track E: Meilisearch docker service, both indexes, search API, rebuild endpoint
- [ ] Track F: Search UI returns results with highlights, handles offline state
- [ ] Track G: Bulk UI shows live progress, pause/cancel work
- [ ] Track H: Cowork endpoint returns full content, truncates correctly
- [ ] All prior 378 tests still passing
- [ ] New tests bring total to 450+
- [ ] `docker-compose up` brings up app + Meilisearch cleanly
- [ ] Manual smoke: mount a test directory at `/mnt/source`, start bulk job, watch progress,
  search results appear, Cowork endpoint returns content

---

## 17. CLAUDE.md Update

After all done criteria pass:

```markdown
**Phase 7 complete** — Bulk conversion pipeline (scanner, worker pool, pause/resume/cancel),
  Adobe Level 2 indexing (.ai/.psd text + .indd/.aep/.prproj/.xd metadata), Meilisearch
  full-text search (documents + adobe-files indexes), search UI, bulk job UI,
  Cowork search API. 450+ tests. Tagged v0.7.0.
**Project complete at v0.7.0.** Future work: Phase 8 (authentication, multi-user, cloud storage),
  Level 3 Adobe enrichment pass, UnionCore integration.
```

Update phase checklist:
```
| 7 | Bulk conversion, Adobe indexing, Meilisearch search, Cowork integration | ✅ Done |
```

Document all new gotchas in the **Gotchas & Fixes Found** section. Expect at least:
- Meilisearch primary key constraints (IDs must be strings, no slashes)
- `psd-tools` layer traversal for nested layer groups
- exiftool subprocess timeout handling
- asyncio.Queue sentinel pattern for worker shutdown
- SMB mount permission error behaviors on Linux

Tag: `git tag v0.7.0 && git push origin v0.7.0`

---

## 18. Output Cap Warning

Phase 7 is the largest phase. Recommended turn boundaries:

1. **Turn 1**: Track A — database schema + helpers + tests
2. **Turn 2**: Track B — `bulk_scanner.py` + tests
3. **Turn 3**: Track C (backend) — `bulk_worker.py`, `api/routes/bulk.py`
4. **Turn 4**: Track C (tests) — `test_bulk_worker.py`, `test_bulk_api.py`
5. **Turn 5**: Track D — `adobe_indexer.py` + tests
6. **Turn 6**: Track E — `search_client.py`, `search_indexer.py`, `api/routes/search.py`,
   `docker-compose.yml` Meilisearch addition + tests
7. **Turn 7**: Track F — `static/search.html`
8. **Turn 8**: Track G — `static/bulk.html`
9. **Turn 9**: Track H — `api/routes/cowork.py` + tests, health check extension, nav update
10. **Turn 10**: Final integration — full test suite, fix failures, env docs, CLAUDE.md update, tag

Update CLAUDE.md at the end of every turn. Each turn must be independently committable.
If Meilisearch integration is causing problems, implement Track E as a stub (always returns
empty results) and complete Tracks F–H against the stub before wiring up the real client.
