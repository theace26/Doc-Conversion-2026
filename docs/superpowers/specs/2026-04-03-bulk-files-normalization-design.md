# Bulk Files Normalization & Pending File Recovery Design

**Date:** 2026-04-03
**Status:** Approved

---

## Problem Statement

Three related symptoms, one root cause:

1. `pending_conversion` count (153,185) exceeds the actual file count on disk (153,486 total scanned) — clearly impossible if each file had one row.
2. The lifecycle scanner restarts from scratch on each run, creating new `bulk_files` rows for files that already have pending rows from previous interrupted runs.
3. There is no way to force-process already-pending files without triggering a full re-scan first.

**Root cause:** `bulk_files` has `UNIQUE(job_id, source_path)`. The same physical file gets one row per job. Workers only process rows for their own job (`WHERE job_id = ? AND status = 'pending'`), so rows from dead/interrupted jobs are orphaned and accumulate forever. The pending count inflates past the real file count because hundreds of jobs each have a pending row for the same file.

---

## Approach: Schema Normalization (One Row Per Physical File)

Change `bulk_files` to `UNIQUE(source_path)`. One row represents one physical file. `job_id` changes meaning from "which job created this row" to "which job currently owns this file" — the "checked out by" field.

**Industry standard:** single-row-per-entity state machine. The row IS the file's current processing state. History lives in `conversion_history` (already exists). Append-on-reprocess is an anti-pattern that trades simplicity for correctness.

Workers are unchanged — they still filter `WHERE job_id = ? AND status = 'pending'`. The only change is that now a file can only be pending for one job at a time.

---

## Section 1 — Migration 20

Migration 20 runs in two parts inside a single transaction:

**Part 1: Deduplicate existing rows**

For each `source_path` with multiple rows, keep exactly one — the one with the "best" status using this priority: `converted > skipped > failed > pending`. Ties broken by most recent `converted_at` or `updated_at`. All other rows are deleted.

```sql
-- Keep best row per source_path, delete the rest
DELETE FROM bulk_files
WHERE id NOT IN (
    SELECT id FROM bulk_files bf1
    WHERE id = (
        SELECT id FROM bulk_files bf2
        WHERE bf2.source_path = bf1.source_path
        ORDER BY
            CASE status
                WHEN 'converted'     THEN 1
                WHEN 'skipped'       THEN 2
                WHEN 'failed'        THEN 3
                WHEN 'unrecognized'  THEN 4
                ELSE 5
            END,
            COALESCE(converted_at, indexed_at, '') DESC
        LIMIT 1
    )
);
```

**Part 2: Recreate table with new constraint**

SQLite cannot drop a UNIQUE constraint in-place. Must rename → create → copy → drop:

```sql
ALTER TABLE bulk_files RENAME TO bulk_files_old;

CREATE TABLE bulk_files (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES bulk_jobs(id),
    source_path     TEXT NOT NULL,
    output_path     TEXT,
    file_ext        TEXT NOT NULL,
    file_size_bytes INTEGER,
    source_mtime    REAL,
    stored_mtime    REAL,
    content_hash    TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    skip_reason     TEXT,
    ocr_skipped_reason TEXT,
    converted_at    TEXT,
    indexed_at      TEXT,
    source_file_id  TEXT,
    UNIQUE(source_path)   -- changed from UNIQUE(job_id, source_path)
);
CREATE INDEX IF NOT EXISTS idx_bulk_files_job_status  ON bulk_files(job_id, status);
CREATE INDEX IF NOT EXISTS idx_bulk_files_source_path ON bulk_files(source_path);
CREATE INDEX IF NOT EXISTS idx_bulk_files_status      ON bulk_files(status);

INSERT INTO bulk_files SELECT * FROM bulk_files_old;
DROP TABLE bulk_files_old;
```

---

## Section 2 — `upsert_bulk_file` New Behavior

The function signature stays identical. The change is internal: look up by `source_path` only (not `job_id + source_path`), then make a status-aware decision.

### Decision Table

| Existing status | mtime unchanged? | Action |
|---|---|---|
| **No row** | — | INSERT, `job_id=current`, `status=pending` |
| **pending** (any job) | — | UPDATE `job_id=current`, refresh `source_mtime`/`file_size_bytes`. Status stays `pending`. |
| **converted** | yes (`stored_mtime == source_mtime`) | Leave completely alone. Return existing `id`. |
| **converted** | no | UPDATE `job_id=current`, `status=pending`. File changed, needs reconversion. |
| **skipped** | yes | Leave alone. Return existing `id`. |
| **skipped** | no | UPDATE `job_id=current`, `status=pending`. Changed since last skip check. |
| **failed** | — | UPDATE `job_id=current`, `status=pending`, clear `error_msg`. Always retry. |
| **unrecognized** | — | Leave alone. We couldn't convert it before. |
| **permanently_skipped** (`ocr_skipped_reason`) | — | Leave alone. Human-marked, even on mtime change. |

**"unchanged?" check** uses `stored_mtime` (mtime at time of last processing), not `source_mtime`. `source_mtime` is "what the disk says now"; `stored_mtime` is "what it was when we last handled it."

**Orphan adoption:** When the scanner restarts after an interruption and re-encounters a file that has a pending row from the previous job, the lookup finds that row and updates `job_id` to the current job. The file is now owned by the current job and will be processed by its workers. No duplicate row, no orphan.

**Worker queries unchanged:** `get_unprocessed_bulk_files(job_id)` still does `WHERE job_id=? AND status='pending'`. No worker code changes.

---

## Section 3 — Process Pending Button & run-now

### `POST /api/pipeline/process-pending`

For when you want to convert already-queued files without triggering a re-scan.

1. Count `SELECT COUNT(*) FROM bulk_files WHERE status='pending'` — if 0, return `{"message": "No pending files", "count": 0, "job_id": null}`
2. Create a new `bulk_jobs` row using source/output paths from active preferences
3. `UPDATE bulk_files SET job_id = <new_job_id> WHERE status = 'pending'` — bulk adopt all pending files in one statement
4. Start bulk workers for the new job (same call the lifecycle scanner uses)
5. Return `{"job_id": ..., "files_queued": N}`

Step 3 is safe because `UNIQUE(source_path)` guarantees at most one pending row per file — the update is deterministic with no ambiguity.

**Requires `UserRole.MANAGER`** (same as run-now).

### run-now Behavior Change

Current: scan → (if auto_convert_mode) trigger conversion.

New: at the start of `_run()`, before calling `run_lifecycle_scan`, check for pending files and process them immediately. Scan then runs in parallel (same background task).

```python
async def _run():
    register_run_now_scan()
    try:
        notify_run_now_started()
        if is_any_bulk_active():
            await wait_if_run_now_paused()
            if is_run_now_cancelled():
                return

        # NEW: kick off any pending files immediately, don't wait for scan
        pending_count = await _get_pending_count()
        if pending_count > 0:
            await _trigger_process_pending()

        # Then scan as normal (finds new/changed files, adds more to queue)
        await run_lifecycle_scan(force=True)
    finally:
        unregister_run_now_scan()
```

`_trigger_process_pending()` is the shared function called by both the endpoint and run-now. No duplication.

---

## Section 4 — Stats Accuracy

The inflated pending count (`COUNT > actual files`) is a direct consequence of the old schema. Once migration 20 deduplicates and `UNIQUE(source_path)` prevents future duplicates, `COUNT(*) FROM bulk_files WHERE status='pending'` equals the number of distinct physical files waiting — no query change needed.

Affected counts that become correct automatically:
- `pending_conversion` in `GET /api/pipeline/status`
- `pending_conversion` in `GET /api/pipeline/stats`
- `get_pending_files_global()` — returns one row per file

Per-job counts (`get_bulk_file_count(job_id, ...)`) remain correct and meaningful for job progress bars.

---

## Files to Change

| File | Change |
|---|---|
| `core/db/schema.py` | Migration 20: deduplicate + recreate `bulk_files` with `UNIQUE(source_path)` |
| `core/db/bulk.py` | `upsert_bulk_file`: lookup by `source_path` only, status-aware decision table |
| `api/routes/pipeline.py` | Add `POST /api/pipeline/process-pending` endpoint |
| `core/scheduler.py` | Add `trigger_process_pending()` public helper (alongside `run_lifecycle_scan`) |
| `api/routes/pipeline.py` | Update `run_pipeline_now` to call `trigger_process_pending()` before scan |
| `static/admin.html` | Add "Process Pending" button to Pipeline section |
| `static/status.html` | Wire "Process Pending" button (if present on status page) |

---

## What Does Not Change

- `get_unprocessed_bulk_files(job_id)` — worker query unchanged
- `get_bulk_file_count(job_id, ...)` — per-job progress bars unchanged
- `get_bulk_files(job_id, ...)` — job detail views unchanged
- `conversion_history` — audit trail unchanged
- `source_files` — lifecycle tracking unchanged
- All worker logic in `core/bulk_worker.py`

---

## Migration Risk

Migration 20 runs inside a transaction. If it fails partway, the rename reverts and data is safe. The deduplication keeps the "best" row per file, so no converted-file records are lost — only redundant pending/failed duplicates are removed. The migration should be tested on a copy of the production DB before deployment.
