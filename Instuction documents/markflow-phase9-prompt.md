# MarkFlow Phase 9 — File Lifecycle Management, Version Tracking & Database Health
# Claude Code Prompt — v0.8.5

---

## Read This First

You are continuing development of **MarkFlow** (GitHub: `github.com/theace26/Doc-Conversion-2026`),
a Python/FastAPI document conversion and repository indexing application. Read `CLAUDE.md` in full
before writing any code — it is the source of truth for current status, file locations, naming
conventions, and gotchas discovered during previous phases.

**Current version:** v0.8.2  
**This phase targets:** v0.8.5  
**Tests passing at start of this phase:** ~543 (check exact count in CLAUDE.md)

This prompt is written against the actual codebase as of v0.8.2. Every file reference, table name,
column name, and import path below matches what was actually built. Do not invent new abstractions
that duplicate existing ones.

---

## What This Phase Builds

Phase 9 adds a **file lifecycle management system** that watches the source repository on a
schedule, tracks every change, manages a soft-delete pipeline with a trash can, records full
version history with diff summaries, and maintains the health of the SQLite database over time.

This phase applies to **all files tracked in `bulk_files`** — converted documents, Adobe-indexed
files, and unrecognized file catalog entries alike.

The six capabilities:

1. **Periodic scanner** — APScheduler job runs every 15 minutes during business hours, detects
   new/modified/moved/deleted files in the source share
2. **Lifecycle state machine** — `active → marked_for_deletion → in_trash → purged` pipeline
   with a 36-hour grace period and 60-day trash retention
3. **Version history** — snapshot of every file change with unified diff patch + bullet summary
4. **UI** — lifecycle badges on all file views, version timeline panel, trash management page,
   deletion warning banners in search results
5. **Database health** — scheduled VACUUM, WAL mode, integrity checks, stale data detection
6. **MCP tools** — two new tools: `list_deleted_files` and `get_file_history`

---

## Architecture Constraints — Non-Negotiable

Carry forward all existing architecture rules from CLAUDE.md. Additional rules for this phase:

- **Do not modify `bulk_files` schema in a destructive way** — only ADD new columns via
  `ALTER TABLE ... ADD COLUMN`. Existing columns are in production use.
- **Schema changes via `_ensure_schema()` in `core/database.py`** — this project does not use
  Alembic. Add new `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  statements to the existing `_ensure_schema()` function, after all existing statements.
  Use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (SQLite 3.37+) so the function is idempotent.
- **APScheduler via lifespan** — use the `lifespan` async context manager in `main.py`.
  Do NOT use `@app.on_event` (deprecated). Do not start scheduler outside lifespan.
- **Scanner enqueues, does not convert** — the scanner detects changes and updates database state.
  It does NOT run conversions inline. New/modified files get their `bulk_files.status` reset
  to `pending` so the existing bulk worker pipeline picks them up on the next bulk job.
- **Structlog everywhere** — `structlog.get_logger(__name__)` in all new modules. No
  `logging.getLogger()` outside `core/logging_config.py`.
- **aiosqlite pattern** — `async with aiosqlite.connect(DB_PATH) as conn:`. Never
  `conn = await aiosqlite.connect()` then `async with conn`. See CLAUDE.md gotcha.
- **Meilisearch sync on lifecycle transitions** — when a file is trashed or purged, delete its
  document from the Meilisearch index immediately via `core/search_indexer.py`. When restored,
  re-index. Use `core/search_client.py` — do not make raw httpx calls to Meilisearch.
- **No new provider infrastructure** — lifecycle/versioning do not touch `core/llm_client.py`,
  `core/llm_providers.py`, or `core/crypto.py`.
- **VACUUM defers if scan in progress** — the weekly compaction job checks `scan_runs` for any
  run with `status='running'` and defers 30 minutes if found.

---

## Phase 9 Sub-phases

Implement in this order. Each sub-phase must pass its tests before proceeding.

---

### Sub-phase A: Schema Extension

**File to modify:** `core/database.py`

Add the following to `_ensure_schema()`, after all existing `CREATE TABLE IF NOT EXISTS` blocks:

#### New columns on `bulk_files`

```sql
ALTER TABLE bulk_files ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE bulk_files ADD COLUMN IF NOT EXISTS marked_for_deletion_at DATETIME;
ALTER TABLE bulk_files ADD COLUMN IF NOT EXISTS moved_to_trash_at DATETIME;
ALTER TABLE bulk_files ADD COLUMN IF NOT EXISTS purged_at DATETIME;
ALTER TABLE bulk_files ADD COLUMN IF NOT EXISTS previous_path TEXT;
```

Valid `lifecycle_status` values: `active`, `marked_for_deletion`, `in_trash`, `purged`

#### New table: `file_versions`

```sql
CREATE TABLE IF NOT EXISTS file_versions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bulk_file_id        INTEGER NOT NULL REFERENCES bulk_files(id),
    version_number      INTEGER NOT NULL,
    recorded_at         DATETIME NOT NULL DEFAULT (datetime('now')),
    change_type         TEXT NOT NULL,
    path_at_version     TEXT NOT NULL,
    mtime_at_version    REAL,
    size_at_version     INTEGER,
    content_hash        TEXT,
    md_content_hash     TEXT,
    diff_summary        TEXT,
    diff_patch          TEXT,
    diff_truncated      INTEGER NOT NULL DEFAULT 0,
    scan_run_id         TEXT,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_file_versions_bulk_file_id ON file_versions(bulk_file_id);
CREATE INDEX IF NOT EXISTS idx_file_versions_recorded_at ON file_versions(recorded_at);
```

Valid `change_type` values:
`initial`, `content_change`, `metadata_change`, `moved`, `restored`,
`marked_deleted`, `trashed`, `purged`

#### New table: `scan_runs`

```sql
CREATE TABLE IF NOT EXISTS scan_runs (
    id              TEXT PRIMARY KEY,
    started_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    finished_at     DATETIME,
    status          TEXT NOT NULL DEFAULT 'running',
    files_scanned   INTEGER DEFAULT 0,
    files_new       INTEGER DEFAULT 0,
    files_modified  INTEGER DEFAULT 0,
    files_moved     INTEGER DEFAULT 0,
    files_deleted   INTEGER DEFAULT 0,
    files_restored  INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    error_log       TEXT
);
```

Valid `status` values: `running`, `complete`, `failed`, `interrupted`

#### New table: `db_maintenance_log`

```sql
CREATE TABLE IF NOT EXISTS db_maintenance_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    operation   TEXT NOT NULL,
    result      TEXT NOT NULL,
    details     TEXT,
    duration_ms INTEGER
);
```

Valid `operation` values: `integrity_check`, `foreign_key_check`, `compaction`, `stale_purge`, `wal_checkpoint`  
Valid `result` values: `ok`, `warning`, `error`

#### Enable WAL mode and incremental auto-vacuum

Add at the end of `_ensure_schema()`, after all table creation:

```python
await conn.execute("PRAGMA journal_mode = WAL")
await conn.execute("PRAGMA wal_autocheckpoint = 1000")
await conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
await conn.execute("PRAGMA foreign_keys = ON")
```

#### New DB helper functions in `core/database.py`

Add these async helper functions alongside the existing helpers:

```python
async def get_bulk_file_by_path(source_path: str) -> dict | None
async def get_bulk_file_by_content_hash(content_hash: str) -> dict | None
async def get_bulk_files_by_lifecycle_status(status: str) -> list[dict]
async def get_bulk_files_pending_trash(grace_period_hours: int = 36) -> list[dict]
async def get_bulk_files_pending_purge(trash_retention_days: int = 60) -> list[dict]
async def create_version_snapshot(bulk_file_id: int, version_data: dict) -> int
async def get_version_history(bulk_file_id: int) -> list[dict]
async def get_version(bulk_file_id: int, version_number: int) -> dict | None
async def get_next_version_number(bulk_file_id: int) -> int
async def create_scan_run(run_id: str) -> None
async def update_scan_run(run_id: str, updates: dict) -> None
async def get_scan_run(run_id: str) -> dict | None
async def get_latest_scan_run() -> dict | None
async def log_maintenance(operation: str, result: str, details: dict | None, duration_ms: int) -> None
async def get_maintenance_log(limit: int = 50) -> list[dict]
```

---

### Sub-phase B: Diff Engine

**New file:** `core/differ.py`

This module computes diffs between two versions of a converted `.md` file and produces both a
unified patch and a human-readable bullet summary.

#### `DiffResult` dataclass

```python
@dataclass
class DiffResult:
    patch: str | None          # Unified diff text; None if > DIFF_MAX_PATCH_BYTES
    patch_truncated: bool
    summary: list[str]         # Bullet-point strings, max 20 items
    lines_added: int
    lines_removed: int
```

#### `compute_diff(old_text: str, new_text: str) -> DiffResult`

- Use `difflib.unified_diff` with `lineterm=""` and `n=3` context lines.
- If the raw patch exceeds `DIFF_MAX_PATCH_BYTES` (1 MB = 1_048_576 bytes), store `patch=None`
  and `patch_truncated=True`. The summary is ALWAYS computed regardless of patch size.
- Summary generation rules:
  1. Parse the diff output line by line.
  2. Group consecutive changed lines within 3 lines of each other into one bullet.
  3. For lines that look like Markdown headings (`^#+ `), call out explicitly:
     `"Section '[heading text]' modified"`
  4. For added lines: `"Added: [first 80 chars]"`
  5. For removed lines: `"Removed: [first 80 chars]"`
  6. For table rows (lines starting with `|`): aggregate runs of table changes into
     `"Table updated: N rows added, M rows removed"` — still store the full raw patch.
  7. If summary would exceed 20 bullets, truncate and append `"… and N more changes"`
- Return `DiffResult` with `patch`, `patch_truncated`, `summary`, `lines_added`, `lines_removed`.

**Tests for `core/differ.py`** in `tests/test_phase9/test_differ.py`:
- Empty diff (identical files) → `summary=[]`, `lines_added=0`, `lines_removed=0`
- Heading change detected and named in summary
- Table row changes produce aggregated bullet
- Patch truncation when text > 1 MB
- Summary never exceeds 20 items
- XLSX/CSV tabular markdown produces same patch storage as DOCX (no special-casing)

---

### Sub-phase C: Lifecycle Manager

**New file:** `core/lifecycle_manager.py`

This module applies lifecycle state transitions and creates version snapshots. It is called by
the scanner (Sub-phase D) and by the maintenance jobs (Sub-phase F). It does not run the scanner
itself — it only processes decisions the scanner has already made.

#### Configuration constants (read from `_PREFERENCE_SCHEMA` at runtime)

```python
GRACE_PERIOD_HOURS = 36       # marked_for_deletion → in_trash
TRASH_RETENTION_DAYS = 60     # in_trash → purged
TRASH_DIR_NAME = ".trash"     # Subdirectory within output-repo root
```

#### Key functions

```python
async def mark_file_for_deletion(bulk_file_id: int, scan_run_id: str) -> None
```
- Sets `lifecycle_status = 'marked_for_deletion'`, `marked_for_deletion_at = now()`
- Creates `file_versions` record with `change_type = 'marked_deleted'`
- Does NOT move files or update Meilisearch yet

```python
async def restore_file(bulk_file_id: int, scan_run_id: str) -> None
```
- Called when a `marked_for_deletion` file reappears in a scan
- Sets `lifecycle_status = 'active'`, clears `marked_for_deletion_at`
- Creates `file_versions` record with `change_type = 'restored'`
- If file was `in_trash`: moves `.md` back from `.trash/` to original output path, updates
  Meilisearch index (re-index the document)

```python
async def move_to_trash(bulk_file_id: int) -> None
```
- Called by maintenance job when grace period expires
- Moves `.md` file from output-repo path to `.trash/` mirror path, creating parent dirs as needed
- Sets `lifecycle_status = 'in_trash'`, `moved_to_trash_at = now()`
- Removes document from Meilisearch index (via `search_indexer.py`)
- Creates `file_versions` record with `change_type = 'trashed'`
- If `.md` file does not exist (was never converted or already gone), still updates DB record

```python
async def purge_file(bulk_file_id: int) -> None
```
- Called by maintenance job when trash retention expires
- Deletes `.md` file from `.trash/` path (if it exists)
- Sets `lifecycle_status = 'purged'`, `purged_at = now()`
- Creates `file_versions` record with `change_type = 'purged'`
- The `bulk_files` row is RETAINED for audit history — never deleted

```python
async def record_file_move(bulk_file_id: int, old_path: str, new_path: str, scan_run_id: str) -> None
```
- Updates `bulk_files.source_path` to `new_path`, sets `previous_path = old_path`
- Sets `lifecycle_status = 'active'`
- Creates `file_versions` record with `change_type = 'moved'`,
  `notes = f"Moved from {old_path}"`

```python
async def record_content_change(
    bulk_file_id: int,
    old_md_path: Path | None,
    new_md_path: Path | None,
    scan_run_id: str
) -> None
```
- Reads text from `old_md_path` and `new_md_path` (if they exist — handle missing gracefully)
- Calls `differ.compute_diff(old_text, new_text)`
- Creates `file_versions` record with `change_type = 'content_change'`
- Stores `diff_summary` as JSON-encoded list, `diff_patch`, `diff_truncated`
- Does NOT re-trigger conversion — that is handled by resetting `status = 'pending'` in the
  scanner and letting the bulk worker pipeline handle it

#### Trash path helper

```python
def get_trash_path(output_repo_root: Path, md_path: Path) -> Path
```
- Returns `.trash/` mirror of `md_path` relative to `output_repo_root`
- Example: `output_repo_root=/mnt/output-repo`, `md_path=/mnt/output-repo/Dept/doc.md`
  → `/mnt/output-repo/.trash/Dept/doc.md`
- Creates a `.trash/README.txt` on first use explaining the trash directory structure
  and retention policy (60 days from `moved_to_trash_at`)

**Tests** in `tests/test_phase9/test_lifecycle_manager.py`:
- `mark_file_for_deletion` creates correct DB state and version record
- `restore_file` clears deletion mark and creates restored version record
- `move_to_trash` moves file and updates Meilisearch (mock the search client)
- `purge_file` deletes file, keeps DB record
- `record_file_move` updates path and creates version record
- `record_content_change` with real diff content creates correct version record
- All functions handle missing `.md` files gracefully (no exception)

---

### Sub-phase D: Lifecycle Scanner

**New file:** `core/lifecycle_scanner.py`

This is the core scan logic. It is called by the APScheduler job. One scan cycle:

1. Generate a UUID `scan_run_id`, create `scan_runs` record via `create_scan_run()`
2. Walk the source share (`BULK_SOURCE_PATH` / configured location, same as `bulk_scanner.py`)
3. For each file found:
   - Update `scan_runs.files_scanned += 1`
   - Look up in `bulk_files` by `source_path`
   - If not found: upsert new record via existing `bulk_scanner.py` logic,
     create `file_versions` record with `change_type = 'initial'`. Increment `files_new`.
   - If found and `mtime` or `size` changed: compute new `content_hash`, reset
     `bulk_files.status = 'pending'` (triggers re-conversion on next bulk job),
     call `record_content_change()`, update mtime/size in `bulk_files`. Increment `files_modified`.
   - If found, was `marked_for_deletion`, and grace period has NOT expired: call `restore_file()`.
     Increment `files_restored`.
   - If file's `lifecycle_status != 'active'` and `!= 'marked_for_deletion'`: skip it
     (in_trash and purged files are not expected to reappear on the source share).
4. After walking all found files, query `bulk_files` for files with `lifecycle_status = 'active'`
   where `source_path` was NOT seen in this scan cycle:
   - Call `mark_file_for_deletion()` for each. Increment `files_deleted`.
5. **Move detection:** Before step 4, check if any "disappeared" file's content_hash matches
   a newly-seen file that is not yet in `bulk_files`. If match found:
   - Call `record_file_move()` instead of `mark_file_for_deletion()`. Increment `files_moved`.
6. Update `scan_runs` record: `finished_at = now()`, `status = 'complete'`, all counters.
7. Log a structured summary via structlog: scan_run_id, duration, all counters.

#### Content hash computation

Use SHA-256 of the raw source file bytes (not the `.md` content). This is consistent with what
Phase 7's bulk scanner may already be doing — check `core/bulk_scanner.py` before implementing
and reuse if the helper already exists. Store in `bulk_files.content_hash` (add this column
if it does not already exist via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).

#### Scan scope

The scanner only walks files that would be processed by the bulk pipeline (i.e., files matching
the existing extension whitelist in the bulk scanner). Unrecognized files already cataloged with
`status = 'unrecognized'` are checked for deletion/move the same as any other tracked file.

#### Error handling

Any exception during processing of a single file must be caught, logged with structlog at ERROR
level including `source_path` and `scan_run_id`, and the scan must continue to the next file.
Append a summary to `scan_runs.error_log` (JSON array of `{path, error}` objects).
If the entire walk fails (e.g., source share unmounted), set `scan_runs.status = 'failed'`
and log at ERROR level. Never raise from the scheduler job.

**Tests** in `tests/test_phase9/test_lifecycle_scanner.py`:

Use `tmp_path` pytest fixture to create a mock filesystem. Pre-populate `bulk_files` with
known state. Mock the source share as a temp directory.

- New file detected → `bulk_files` upsert + `initial` version record
- Modified file (mtime changed) → `status = 'pending'`, `content_change` version record
- Disappeared file → `marked_for_deletion` in DB
- Disappeared file reappears within grace → `restored`
- Move detected via hash match → `record_file_move()` called, not mark_for_deletion
- Source share unmounted → `scan_runs.status = 'failed'`, no exception propagated
- Single file error → scan continues, error logged to `scan_runs.error_log`

---

### Sub-phase E: Scheduler

**New file:** `core/scheduler.py`

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import structlog

logger = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler()

def start_scheduler() -> None:
    """Register all jobs and start the scheduler. Called from lifespan."""
    ...

def stop_scheduler() -> None:
    """Gracefully shut down scheduler. Called from lifespan."""
    ...
```

#### Jobs to register

| Job | Trigger | Function |
|-----|---------|----------|
| `lifecycle_scan` | `IntervalTrigger(minutes=15)` — but only fires inside business hours | `run_lifecycle_scan()` |
| `trash_expiry` | `IntervalTrigger(hours=1)` | `run_trash_expiry()` |
| `db_compaction` | `CronTrigger(day_of_week='sun', hour=2, minute=0)` | `run_db_compaction()` |
| `db_integrity` | `CronTrigger(day_of_week='sun', hour=2, minute=15)` | `run_db_integrity_check()` |
| `stale_check` | `CronTrigger(day_of_week='sun', hour=2, minute=30)` | `run_stale_data_check()` |

#### Business hours enforcement for `lifecycle_scan`

Business hours: Monday–Friday, 06:00–18:00 local server time (configurable via preferences).
At the start of `run_lifecycle_scan()`, check the current local time. If outside business hours,
log at DEBUG level and return immediately without running the scan. This keeps the scheduler
simple (interval-based) while respecting business hours.

On startup: always run one immediate scan regardless of business hours by calling
`run_lifecycle_scan(force=True)`.

#### `run_lifecycle_scan(force: bool = False)`

- If not `force`, enforce business hours check
- Call `core/lifecycle_scanner.py` scan logic
- Log start/finish with structlog

#### `run_trash_expiry()`

- Query `get_bulk_files_pending_trash(grace_period_hours=36)` — files `marked_for_deletion`
  where `marked_for_deletion_at < now() - 36 hours`
- Call `lifecycle_manager.move_to_trash()` for each
- Query `get_bulk_files_pending_purge(trash_retention_days=60)` — files `in_trash`
  where `moved_to_trash_at < now() - 60 days`
- Call `lifecycle_manager.purge_file()` for each
- Log counts

#### `run_db_compaction()`

- Check `scan_runs` for any `status = 'running'` record. If found, defer by 30 minutes
  (reschedule this job, log warning, return).
- Run `db_maintenance.run_compaction()`

#### `run_db_integrity_check()` and `run_stale_data_check()`

- Call the corresponding functions in `core/db_maintenance.py`

#### Modify `main.py` lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...
    from core.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()
    # ... existing shutdown code ...
```

**Add to `requirements.txt`:**
```
apscheduler>=3.10.0
```

**Tests** in `tests/test_phase9/test_scheduler.py`:
- Business hours check returns False at 03:00 Sunday, True at 10:00 Monday
- `run_lifecycle_scan` with `force=True` bypasses business hours check
- Trash expiry job calls `move_to_trash` for expired records
- Purge job calls `purge_file` for expired trash
- Compaction defers when scan running (mock `scan_runs` table)

---

### Sub-phase F: Database Maintenance

**New file:** `core/db_maintenance.py`

```python
async def run_compaction() -> None
async def run_integrity_check() -> None
async def run_foreign_key_check() -> None
async def run_stale_data_check() -> dict
async def run_wal_checkpoint() -> None
async def get_health_summary() -> dict
```

#### `run_compaction()`

1. Record start time
2. `PRAGMA incremental_vacuum(100)` — reclaim up to 100 pages incrementally
3. `PRAGMA wal_checkpoint(TRUNCATE)` — flush WAL
4. If `(freelist_count / page_count) > 0.25`: run full `VACUUM` (rewrite entire DB)
5. Record result to `db_maintenance_log` with `operation='compaction'`, duration
6. Log with structlog

#### `run_integrity_check()`

1. Execute `PRAGMA integrity_check`
2. If result is not `["ok"]`: log at ERROR level, surface in `db_maintenance_log` with
   `result='error'`, `details={"findings": [...]}`. Otherwise `result='ok'`.

#### `run_foreign_key_check()`

1. Execute `PRAGMA foreign_key_check`
2. Any rows returned = foreign key violation. Log result to `db_maintenance_log`.

#### `run_stale_data_check() -> dict`

Runs 6 checks. Each finding is logged as a row in `db_maintenance_log`. Returns a summary dict.

| Check | Query | Severity |
|-------|-------|----------|
| Orphaned versions | `file_versions` rows where `bulk_file_id` not in `bulk_files` | warning |
| Missing .md files | `bulk_files` where `lifecycle_status='active'` AND `status='success'` but `.md` output path doesn't exist on disk | warning |
| Stale Meilisearch entries | Documents in Meilisearch `documents` index whose `id` isn't in `bulk_files` | warning |
| Dangling trash entries | `bulk_files` where `lifecycle_status='in_trash'` but `.trash/` path doesn't exist | warning |
| Expired trash not purged | `bulk_files` where `lifecycle_status='in_trash'` AND `moved_to_trash_at < now() - 60 days` | error |
| Expired grace not trashed | `bulk_files` where `lifecycle_status='marked_for_deletion'` AND `marked_for_deletion_at < now() - 36 hours` | error |

For the Meilisearch check: use `search_client.py` to get all document IDs. If Meilisearch is
down, skip this check and log a warning — do not fail the stale check.

#### `get_health_summary() -> dict`

Returns the most recent result of each check type from `db_maintenance_log`, plus:
- SQLite page count, freelist count, database size in bytes
- WAL mode status
- Last compaction time
- Last integrity check time and result

**Tests** in `tests/test_phase9/test_db_maintenance.py`:
- Integrity check returns `ok` on clean DB, `error` with synthetic corruption (mock query)
- Stale data check finds orphaned version records
- Stale data check handles Meilisearch being down gracefully
- Compaction logs result to `db_maintenance_log`
- `get_health_summary` returns well-formed dict with all expected keys

---

### Sub-phase G: API Routes

#### `api/routes/lifecycle.py` (NEW)

Mount at `/api/lifecycle`.

```
GET  /api/lifecycle/files/{bulk_file_id}/versions
     → list[VersionRecord]  (all versions for a file, newest first)

GET  /api/lifecycle/files/{bulk_file_id}/versions/{version_number}
     → VersionRecord  (single version with full diff_patch)

GET  /api/lifecycle/files/{bulk_file_id}/diff/{v1}/{v2}
     → DiffResponse: {summary: list[str], patch: str|null, patch_truncated: bool,
                      v1: VersionRecord, v2: VersionRecord}
     Computes diff between any two stored versions on demand if diff not pre-stored.
```

Pydantic models in `api/models.py`:

```python
class VersionRecord(BaseModel):
    id: int
    bulk_file_id: int
    version_number: int
    recorded_at: datetime
    change_type: str
    path_at_version: str
    size_at_version: int | None
    content_hash: str | None
    diff_summary: list[str] | None   # decoded from JSON
    diff_truncated: bool
    scan_run_id: str | None
    notes: str | None
    # diff_patch excluded from list endpoint for payload size; included in single-version GET

class VersionListResponse(BaseModel):
    file_id: int
    versions: list[VersionRecord]
    total: int

class DiffResponse(BaseModel):
    summary: list[str]
    patch: str | None
    patch_truncated: bool
    lines_added: int
    lines_removed: int
    v1: VersionRecord
    v2: VersionRecord
```

#### `api/routes/trash.py` (NEW)

Mount at `/api/trash`.

```
GET    /api/trash
       Query params: page=1, per_page=25, sort=moved_to_trash_at|path (default: moved_to_trash_at desc)
       → {files: [TrashRecord], total: int, page: int, per_page: int}

POST   /api/trash/{bulk_file_id}/restore
       → {success: bool, message: str}
       Calls lifecycle_manager.restore_file()

DELETE /api/trash/{bulk_file_id}
       → {success: bool, message: str}
       Calls lifecycle_manager.purge_file() (immediate, ignores timer)

POST   /api/trash/empty
       → {purged_count: int}
       Purges all in_trash files immediately

class TrashRecord(BaseModel):
    id: int
    source_path: str
    moved_to_trash_at: datetime
    purge_at: datetime          # moved_to_trash_at + 60 days
    days_remaining: int
    file_format: str | None
    size_at_version: int | None
```

#### `api/routes/scanner.py` (NEW)

Mount at `/api/scanner`.

```
GET  /api/scanner/status
     → {last_run: ScanRunRecord | None, is_running: bool, next_run_estimate: datetime | None,
        business_hours: {start: "06:00", end: "18:00", days: [1,2,3,4,5]}}

POST /api/scanner/run-now
     → {scan_run_id: str, message: str}
     Triggers immediate out-of-schedule scan (runs in background task)

GET  /api/scanner/runs
     Query params: limit=10
     → {runs: [ScanRunRecord]}

class ScanRunRecord(BaseModel):
    id: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    files_scanned: int
    files_new: int
    files_modified: int
    files_moved: int
    files_deleted: int
    files_restored: int
    errors: int
```

#### `api/routes/db_health.py` (NEW)

Mount at `/api/db`.

```
GET  /api/db/health
     → db_maintenance.get_health_summary()

POST /api/db/compact
     → {message: str, deferred: bool}
     Runs in background task; returns immediately

POST /api/db/integrity-check
     → {result: str, findings: list[str]}
     Runs synchronously (fast)

POST /api/db/stale-check
     → {checks: dict}   (output of run_stale_data_check())
     Runs synchronously

GET  /api/db/maintenance-log
     Query params: limit=50
     → {entries: [MaintenanceLogRecord]}
```

#### Register all new routers in `main.py`

```python
from api.routes.lifecycle import router as lifecycle_router
from api.routes.trash import router as trash_router
from api.routes.scanner import router as scanner_router
from api.routes.db_health import router as db_health_router

app.include_router(lifecycle_router, prefix="/api/lifecycle")
app.include_router(trash_router, prefix="/api/trash")
app.include_router(scanner_router, prefix="/api/scanner")
app.include_router(db_health_router, prefix="/api/db")
```

**Tests** in `tests/test_phase9/test_api_lifecycle.py`:
- All endpoints return correct HTTP status codes
- Version list returns newest-first ordering
- Diff endpoint returns valid DiffResponse shape
- Trash restore returns 404 for unknown file_id
- Trash empty returns correct purged_count
- Scanner run-now returns scan_run_id
- DB health endpoint returns all expected keys

---

### Sub-phase H: UI

All frontend work uses vanilla HTML/JS and `markflow.css`. No new frameworks.
Follow the existing patterns in `static/app.js` for API calls, toast notifications, and
error handling. Reuse CSS variables from `markflow.css` for all new styles.

#### `static/js/lifecycle-badge.js` (NEW)

Shared module. `renderLifecycleBadge(status, details) -> HTMLElement`

| Status | Color CSS var | Label |
|--------|--------------|-------|
| `active` | `--color-success` | Active |
| `marked_for_deletion` | `--color-warning` | Marked for Deletion |
| `in_trash` | `--color-danger` | In Trash |
| `purged` | `--color-muted` | Purged |

For `marked_for_deletion`: tooltip text `"Marked X hours ago — moves to trash in Y hours"`
For `in_trash`: tooltip text `"Trashed X days ago — deleted in Y days"`

Use the existing tooltip pattern from `markflow.css` if one exists, otherwise use the
`title` attribute as a fallback — do not introduce a new tooltip library.

#### `static/js/version-panel.js` (NEW)

Renders a version history timeline for a file. Calls `GET /api/lifecycle/files/{id}/versions`.

Timeline format per version:
```
v3  content_change  March 24, 2026 10:15 AM
    • Added section "Safety Requirements"
    • Table updated: 2 rows added
    • Removed: "This procedure was…"

v2  moved  March 21, 2026 02:30 PM
    • Moved from /Dept/Old/path/doc.docx

v1  initial  February 14, 2026 09:00 AM
    • First indexed
```

Include a "Compare" button that opens a modal with a side-by-side diff view.
Call `GET /api/lifecycle/files/{id}/diff/{v1}/{v2}` and render `summary` as bullets and
`patch` as a `<pre>` block (if not truncated). If `patch_truncated` is true, show a note
that the full diff is too large to display.

#### `static/js/deletion-banner.js` (NEW)

Scans a list of file records and injects a dismissible banner at the top of the page if any
have `lifecycle_status != 'active'`. Uses `sessionStorage` to track dismissed banners
(keyed by search query or page ID) so they don't re-appear on the same session.

Note: Do not use `localStorage` — that is not supported in the Claude.ai artifact environment.
`sessionStorage` is fine for regular browser use.

#### Extend `static/history.html`

- Add lifecycle badge to every file row using `lifecycle-badge.js`
- Add version history panel to the inline detail drawer (already exists from Phase 6)
  using `version-panel.js`
- Include `lifecycle-badge.js` and `version-panel.js` in page scripts

#### Extend `static/search.html`

- Add lifecycle badge to each search result item
- Include `deletion-banner.js` — fire after results load
- Include `lifecycle-badge.js` in page scripts

#### `static/trash.html` (NEW)

Dedicated trash management page. Structure:

- Page header: "Trash" with subtitle "Files are permanently deleted 60 days after being trashed"
- Stats bar: total in trash, total size, earliest auto-delete date
- Table: filename, original path, trashed date, auto-delete date, days remaining, Restore / Delete Now buttons
- Bulk actions: "Restore All", "Empty Trash" (with confirmation dialog using `<dialog>` element —
  same pattern as `FolderPicker` in `static/js/folder-picker.js`)
- Empty state: friendly message with link to Search

Add "Trash" to the main navigation bar (same nav as `history.html`, `search.html`, `bulk.html`).
Edit `markflow.css` nav styles if needed.

#### `static/db-health.html` (NEW)

Admin page for database health monitoring. Link from `settings.html` under an "Advanced" section
(do NOT add to main nav — this is an admin tool, not an end-user feature).

Sections:
- **Overview card**: DB size, WAL mode status, page count, last compaction, last integrity check
- **Maintenance actions**: "Run Compaction", "Run Integrity Check", "Run Stale Data Check" buttons
  (each shows a spinner and toasts result)
- **Recent maintenance log**: table of last 20 `db_maintenance_log` entries
- **Stale data results**: after running stale check, displays count per check type with
  `ok` / `warning` / `error` badges. Does NOT auto-fix — this page is informational only.

---

### Sub-phase I: MCP Tools

**File to modify:** `mcp_server/tools.py`

**APPEND** two new tool functions after the existing 8 tools. Do NOT replace or restructure
existing tools — `mcp_server/tools.py` is append-only per CLAUDE.md architecture rules.

#### Tool 9: `list_deleted_files`

```python
async def list_deleted_files(
    status: str = "marked_for_deletion",   # "marked_for_deletion" | "in_trash" | "purged"
    limit: int = 20
) -> str
```

Returns a formatted list of files in the given lifecycle state with path, status, and
relevant timestamps. If no files found, returns a message saying so.

Docstring must clearly describe: what each status means, what timestamps are shown, and
typical use case (e.g., "use this to check what files are scheduled for deletion before
they are trashed"). Docstrings drive Claude.ai tool selection — keep them informative.

#### Tool 10: `get_file_history`

```python
async def get_file_history(
    source_path: str    # Full source path of the file to look up
) -> str
```

Returns the version history for a file identified by its source path. Includes all version
records with change type, timestamp, and diff summary bullets. If the file is not found,
returns a clear message. If found but has no history yet (newly indexed), says so.

Update `mcp_server/server.py` to register the two new tools if registration is explicit
(check how existing 8 tools are registered and follow the same pattern).

---

### Sub-phase J: Settings Integration

#### New preference keys in `_PREFERENCE_SCHEMA`

Add to the existing `_PREFERENCE_SCHEMA` dict in `api/routes/preferences.py`:

```python
"scanner_enabled": {
    "type": "bool", "default": True,
    "label": "Periodic file scanner",
    "description": "Scan source repository every 15 minutes during business hours"
},
"scanner_interval_minutes": {
    "type": "int", "default": 15, "min": 5, "max": 120,
    "label": "Scan interval (minutes)",
    "description": "How often to scan during business hours"
},
"scanner_business_hours_start": {
    "type": "str", "default": "06:00",
    "label": "Business hours start (HH:MM)",
    "description": "Scanner only runs between start and end times on weekdays"
},
"scanner_business_hours_end": {
    "type": "str", "default": "18:00",
    "label": "Business hours end (HH:MM)"
},
"lifecycle_grace_period_hours": {
    "type": "int", "default": 36, "min": 1, "max": 168,
    "label": "Deletion grace period (hours)",
    "description": "How long before a missing file moves to trash. Default: 36 hours."
},
"lifecycle_trash_retention_days": {
    "type": "int", "default": 60, "min": 1, "max": 365,
    "label": "Trash retention (days)",
    "description": "How long files stay in trash before permanent deletion. Default: 60 days."
},
```

#### Add to `static/settings.html`

Add a new **"File Lifecycle"** section to the settings page (after the existing sections,
before any "Advanced" section). Include toggles/inputs for:
- Scanner enabled (toggle)
- Scan interval (number input, 5–120)
- Business hours start / end (time inputs)
- Grace period hours (number input)
- Trash retention days (number input)

Include a "Database Health" link button in an "Advanced" section at the bottom of settings
that navigates to `db-health.html`.

---

### Sub-phase K: Tests

**Test directory:** `tests/test_phase9/`

Create `tests/test_phase9/__init__.py` (empty).

Test files:
- `test_differ.py` — diff engine (covered in Sub-phase B)
- `test_lifecycle_manager.py` — lifecycle transitions (covered in Sub-phase C)
- `test_lifecycle_scanner.py` — scan logic (covered in Sub-phase D)
- `test_scheduler.py` — scheduler logic (covered in Sub-phase E)
- `test_db_maintenance.py` — DB health functions (covered in Sub-phase F)
- `test_api_lifecycle.py` — all new API endpoints (covered in Sub-phase G)
- `test_trash.py` — trash page API flows end-to-end

**Fixtures** — add to `tests/conftest.py` or `tests/test_phase9/conftest.py`:

```python
@pytest.fixture
async def db_with_lifecycle_files(tmp_path):
    """Pre-populated DB with files in each lifecycle state for testing."""

@pytest.fixture
def mock_source_share(tmp_path):
    """Temp directory tree mimicking a source share with a few files."""

@pytest.fixture
def mock_output_repo(tmp_path):
    """Temp directory mimicking the output markdown repo."""
```

**Coverage target:** ≥ 85% on all new modules in this phase.

**Do not break existing tests.** Run `pytest` (all tests) after each sub-phase. The existing
~543 tests must continue to pass.

---

## Done Criteria

Work through this checklist before tagging v0.8.5.

### Schema & Data
- [ ] `bulk_files` has all 5 new lifecycle columns (idempotent `ALTER TABLE`)
- [ ] `file_versions` table exists with correct schema and indexes
- [ ] `scan_runs` table exists
- [ ] `db_maintenance_log` table exists
- [ ] WAL mode, incremental auto-vacuum, foreign keys enabled in `_ensure_schema()`
- [ ] All new DB helper functions implemented and tested

### Scanner & Lifecycle
- [ ] APScheduler starts/stops cleanly via lifespan
- [ ] Startup scan runs immediately on container start
- [ ] Scanner runs every 15 minutes during Mon–Fri 06:00–18:00 local time
- [ ] Scanner pauses (no-op) outside business hours
- [ ] New files detected → `bulk_files` upserted + `initial` version record
- [ ] Modified files detected → `status = 'pending'`, `content_change` version record
- [ ] Deleted files → `marked_for_deletion` with timestamp
- [ ] File reappears within 36h grace period → auto-restored to `active`
- [ ] Move detected via content hash → `record_file_move()`, not mark_for_deletion
- [ ] Grace period expiry (36h) → `move_to_trash()`, `.md` moved to `.trash/`, Meilisearch entry removed
- [ ] Trash expiry (60 days) → `purge_file()`, `.md` deleted, DB record retained
- [ ] `scan_runs` record created and updated for every scan cycle
- [ ] Single-file errors logged and counted; scan continues
- [ ] Source share mount failure → `scan_runs.status = 'failed'`

### Version History
- [ ] Every lifecycle transition creates a `file_versions` record
- [ ] Version numbers are monotonically increasing per file
- [ ] `content_change` records include `diff_summary` (JSON array) and `diff_patch`
- [ ] Diff patch > 1 MB → `diff_patch = NULL`, `diff_truncated = 1`, summary still populated
- [ ] XLSX/CSV diffs store full raw patch + summary (no special-casing)
- [ ] Table-format diff lines produce "Table updated: N rows added, M rows removed" bullets

### API
- [ ] `GET /api/lifecycle/files/{id}/versions` returns version list newest-first
- [ ] `GET /api/lifecycle/files/{id}/diff/{v1}/{v2}` returns DiffResponse
- [ ] `GET /api/trash` returns paginated list with `days_remaining`
- [ ] `POST /api/trash/{id}/restore` restores correctly
- [ ] `DELETE /api/trash/{id}` purges immediately
- [ ] `POST /api/trash/empty` purges all in_trash
- [ ] `GET /api/scanner/status` shows last run and business hours config
- [ ] `POST /api/scanner/run-now` triggers background scan, returns scan_run_id
- [ ] `GET /api/db/health` returns well-formed summary
- [ ] `POST /api/db/compact` triggers compaction (defers if scan running)
- [ ] `POST /api/db/integrity-check` runs and returns result
- [ ] `POST /api/db/stale-check` runs all 6 checks

### UI
- [ ] Lifecycle badge visible on every file row in `history.html`
- [ ] Lifecycle badge visible on every result in `search.html`
- [ ] Deletion warning banner appears in search when results include deleted/trashed files
- [ ] Version history panel in history detail drawer shows timeline with bullets
- [ ] Compare any two versions via modal diff viewer
- [ ] `trash.html` loads, lists files, restore/delete controls work
- [ ] "Trash" link in main nav
- [ ] `db-health.html` shows health summary and action buttons
- [ ] "Database Health" link in Settings page Advanced section

### MCP
- [ ] Tool 9 `list_deleted_files` registered and functional
- [ ] Tool 10 `get_file_history` registered and functional
- [ ] Existing 8 tools unmodified and still passing

### Settings
- [ ] All 6 new preference keys in `_PREFERENCE_SCHEMA` with correct types and defaults
- [ ] Settings page "File Lifecycle" section renders and saves
- [ ] Business hours settings respected by scanner

### Tests & Quality
- [ ] All new tests in `tests/test_phase9/` pass
- [ ] Existing ~543 tests still pass (no regressions)
- [ ] ≥ 85% coverage on all new modules
- [ ] No new structlog violations (no `logging.getLogger` in new modules)
- [ ] No new aiosqlite anti-patterns

### Release
- [ ] `CLAUDE.md` updated:
  - Phase 9 added to phase checklist as ✅ Done
  - Version bump to v0.8.5
  - All new files added to Key Files table
  - New gotchas documented (APScheduler lifespan pattern, WAL mode, trash path mirror)
  - New preferences documented
- [ ] Git tag: `v0.8.5`

---

## New Files Summary

| File | Purpose |
|------|---------|
| `core/differ.py` | Unified diff engine + bullet summary generator |
| `core/lifecycle_manager.py` | Lifecycle state transitions, trash/purge operations |
| `core/lifecycle_scanner.py` | Source share walker, change detection, move detection |
| `core/scheduler.py` | APScheduler setup, job registration, business hours enforcement |
| `core/db_maintenance.py` | VACUUM, integrity checks, stale data detection |
| `api/routes/lifecycle.py` | Version history and diff API endpoints |
| `api/routes/trash.py` | Trash management API endpoints |
| `api/routes/scanner.py` | Scanner status and control API endpoints |
| `api/routes/db_health.py` | Database health and maintenance API endpoints |
| `static/js/lifecycle-badge.js` | Reusable lifecycle status badge component |
| `static/js/version-panel.js` | Version history timeline + compare modal |
| `static/js/deletion-banner.js` | Dismissible banner for search results with deleted files |
| `static/trash.html` | Trash can management page |
| `static/db-health.html` | Admin database health dashboard |
| `tests/test_phase9/` | All Phase 9 tests |

---

## Files Modified

| File | Change |
|------|--------|
| `core/database.py` | New columns, new tables, WAL/FK PRAGMAs, new helper functions |
| `main.py` | Scheduler start/stop in lifespan, new router registrations |
| `api/models.py` | New Pydantic models: VersionRecord, TrashRecord, ScanRunRecord, etc. |
| `api/routes/preferences.py` | 6 new keys in `_PREFERENCE_SCHEMA` |
| `mcp_server/tools.py` | Append tool 9 and tool 10 |
| `mcp_server/server.py` | Register new tools (if explicit registration exists) |
| `static/history.html` | Lifecycle badges, version panel in detail drawer |
| `static/search.html` | Lifecycle badges, deletion banner |
| `static/settings.html` | File Lifecycle section, Database Health link |
| `static/app.js` | Any shared lifecycle helpers if needed |
| `requirements.txt` | `apscheduler>=3.10.0` |

---

*This prompt was written against CLAUDE.md as of v0.8.2. If CLAUDE.md has been updated
since this prompt was written, CLAUDE.md takes precedence on all naming, schema, and
implementation details. The spec above reflects intent; CLAUDE.md reflects reality.*
