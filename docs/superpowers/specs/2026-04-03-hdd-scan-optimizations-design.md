# HDD Scan Optimizations — Design Spec

**Date:** 2026-04-03
**Status:** Draft
**Scope:** Three optimizations to speed up mechanical HDD scans without compromising robustness

## Summary

Three complementary optimizations for scanning on mechanical hard drives:

1. **Directory mtime skip** — skip entire directory subtrees that haven't changed since the last scan. Applies to bulk scanner (serial + parallel) and lifecycle scanner. Full walk forced every Nth scan and when running outside business hours (overnight).

2. **Batch serial DB writes** — the bulk scanner's serial (HDD) path still does 2 SQLite commits per file. Apply the same `upsert_bulk_files_batch` pattern already built for the parallel path.

3. **Overlap disk read with DB write** — in the bulk serial path, overlap the next round of `stat()` calls with the current batch's DB write. Disk stays strictly serial; only DB writes run concurrently.

## 1. Directory Mtime Skip

### How it works

Operating systems update a directory's mtime when files are added, removed, or renamed inside it. If a directory's mtime hasn't changed since the last scan, none of its direct children changed — safe to skip the entire subtree.

### Storage: `scan_dir_mtimes` table

New table (migration 21):

```sql
CREATE TABLE IF NOT EXISTS scan_dir_mtimes (
    dir_path    TEXT PRIMARY KEY,
    dir_mtime   REAL NOT NULL,
    scan_run_id TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
```

Both bulk scanner and lifecycle scanner share this table. Whichever scanner ran last provides the cache for the next run.

### Scan flow

1. At scan start, load all `scan_dir_mtimes` rows into a dict: `{dir_path: dir_mtime}`
2. During `os.walk` (or parallel walker), for each directory:
   - `stat()` the directory to get current mtime
   - If current mtime matches cached mtime → prune from `dirnames[:]` (skip subtree)
   - If different or not in cache → descend normally
3. After scan completes, persist current directory mtimes for all visited directories
4. Bulk-insert/update using a single transaction (same batch pattern)

### Full walk trigger

Not every scan should use the mtime cache. Two triggers for a full walk:

- **Every Nth scan:** New preference `scan_full_walk_interval` (default: 5). A counter in the `scan_dir_mtimes` table (or a preference) tracks how many incremental scans have run since the last full walk.
- **Outside business hours:** If the current time is outside `scanner_business_hours_start` / `scanner_business_hours_end` (existing preferences, defaults 06:00–22:00), force a full walk. This means overnight scans are always comprehensive.

When a full walk runs, it ignores the mtime cache entirely, walks everything, and refreshes the entire `scan_dir_mtimes` table.

New preference `scan_incremental_enabled` (default: `true`) — master toggle to disable mtime skip entirely.

### Where it applies

- **Bulk scanner `_serial_scan`** — prune `dirnames[:]` in the `os.walk` loop (line ~353 in `bulk_scanner.py`)
- **Bulk scanner `_parallel_scan`** — walker threads check mtime before descending into subdirectories
- **Lifecycle scanner parallel walker** — same pattern, check mtime in the walker thread before descending

### Edge cases

- **Directory mtime doesn't update for content changes to existing files.** This is by design — the mtime-skip optimization skips the *walk*, but files that were already discovered in previous scans have their `source_mtime` tracked in `source_files`. The lifecycle scanner's modification detection catches content changes on the next full walk.
- **Clock skew:** Full walk every N scans catches any files missed due to clock skew.
- **New mount or first scan:** Empty `scan_dir_mtimes` table means no cache hits — effectively a full walk.
- **Cancelled scans:** Don't update `scan_dir_mtimes` for a cancelled scan (incomplete data).

## 2. Batch Serial DB Writes

### Current state

The serial scan path in `_serial_scan` calls `_process_discovered_file` per file, which calls `upsert_bulk_file` (2 commits per file). The parallel path already uses `upsert_bulk_files_batch`.

### Change

Accumulate discovered files in a buffer inside `_serial_scan`. When the buffer hits 200 files (or at scan end), flush via `upsert_bulk_files_batch`.

- Convertible files accumulate as `(source_path, file_ext, file_size_bytes, source_mtime)` tuples
- Unrecognized files still go per-file (need MIME classification via `_record_unrecognized`)
- Progress tracking updates per-batch (call `tracker.record_completion()` for each file in the batch after flush)
- Error monitor records success for the whole batch on successful flush
- The `_process_discovered_file` method is no longer called for convertible files in serial mode — its logic (NTFS ADS skip, blocklist check, stat, classify) moves inline into `_serial_scan`'s loop, with the upsert deferred to batch flush

### Lifecycle scanner

The lifecycle scanner cannot easily batch its DB writes because `_process_file` does conditional per-file logic: check if file exists in DB, compute content hash (reads entire file), create version snapshot, detect modifications. These are inherently per-file operations. The lifecycle scanner's main win comes from optimization #1 (mtime skip), which eliminates most of these calls.

## 3. Overlap Disk Read with DB Write

### Current flow (serial)

```
stat file 1 → write file 1 to DB → stat file 2 → write file 2 to DB → ...
```

### New flow

```
stat files 1-200 → [start DB write for batch 1, stat files 201-400 concurrently] → ...
```

### Implementation

Split the serial scan loop into two phases that overlap:

1. **Stat phase:** Walk directories, `stat()` each file, accumulate into a buffer of 200. This is synchronous and sequential (no parallel disk I/O).
2. **Write phase:** When buffer is full, fire off the DB write as an `asyncio.Task` and immediately start filling the next buffer with more `stat()` calls.
3. Before starting a new write, `await` the previous write task (if any) to ensure we don't pile up DB writes.

The disk stays strictly serial — only one `stat()` at a time. The DB write overlaps with the next round of stats. On an HDD where each stat takes ~5-10ms, a batch of 200 stats takes ~1-2 seconds, which is roughly the same time as a batched DB write — so they overlap nicely.

### Error handling

- If the DB write task raises, catch the exception on the next `await` and fall back to per-file writes for that batch (same fallback pattern as `upsert_bulk_files_batch`)
- The stat phase continues regardless — it's just collecting data, not writing anything

## New Preferences

| Preference | Default | Description |
|-----------|---------|-------------|
| `scan_incremental_enabled` | `true` | Enable directory mtime skip for faster rescans |
| `scan_full_walk_interval` | `5` | Full walk every N scans (also forced outside business hours) |

## New DB Migration (21)

```sql
CREATE TABLE IF NOT EXISTS scan_dir_mtimes (
    dir_path    TEXT PRIMARY KEY,
    dir_mtime   REAL NOT NULL,
    scan_run_id TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
CREATE INDEX IF NOT EXISTS idx_scan_dir_mtimes_run ON scan_dir_mtimes(scan_run_id)
```

## Files Affected

| File | Change |
|------|--------|
| `core/db/schema.py` | Migration 21: `scan_dir_mtimes` table |
| `core/db/bulk.py` | New helpers: `load_dir_mtimes()`, `save_dir_mtimes_batch()`, `get_incremental_scan_counter()`, `increment_scan_counter()` |
| `core/db/__init__.py` | Re-export new helpers |
| `core/db/preferences.py` | Add `scan_incremental_enabled`, `scan_full_walk_interval` defaults |
| `core/bulk_scanner.py` | `_serial_scan`: batch writes + disk/DB overlap + mtime skip. `_parallel_scan` walker: mtime skip. |
| `core/lifecycle_scanner.py` | Walker threads: mtime skip. Post-scan: persist dir mtimes. |

## Not In Scope

- Settings UI for new preferences (can use existing Settings page which auto-discovers preferences)
- Changing the parallel scan consumer (already optimized with batch writes)
- Lifecycle scanner batch DB writes (per-file logic is inherently sequential)
