# Source Files Dedup — Global File Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate bulk_files row duplication across scan jobs by introducing a `source_files` table with `source_path` as the unique key, so cross-job queries return accurate distinct file counts.

**Architecture:** Add a `source_files` table that owns file-intrinsic data (path, size, mtime, hash, lifecycle status). `bulk_files` keeps a FK reference (`source_file_id`) and retains job-specific data (status, error_msg, converted_at). `upsert_bulk_file()` upserts into `source_files` first, then links via `bulk_files`. Cross-job queries (admin stats, lifecycle) query `source_files` for distinct counts. Per-job queries still filter `bulk_files` by `job_id`. Existing data migrated via INSERT...SELECT DISTINCT.

**Tech Stack:** SQLite (aiosqlite), Python 3.11, existing `_add_column_if_missing()` migration pattern

---

### Task 1: Create `source_files` table and migration

**Files:**
- Modify: `core/database.py` — add CREATE TABLE + migration logic in `init_db()`

- [ ] **Step 1: Add CREATE TABLE for source_files**

In `core/database.py`, add after the `bulk_files` CREATE TABLE block (around line 202):

```sql
CREATE TABLE IF NOT EXISTS source_files (
    id              TEXT PRIMARY KEY,
    source_path     TEXT NOT NULL UNIQUE,
    file_ext        TEXT NOT NULL,
    file_size_bytes INTEGER,
    source_mtime    REAL,
    stored_mtime    REAL,
    content_hash    TEXT,
    output_path     TEXT,
    mime_type       TEXT,
    file_category   TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    marked_for_deletion_at DATETIME,
    moved_to_trash_at DATETIME,
    purged_at       DATETIME,
    previous_path   TEXT,
    protection_type TEXT DEFAULT 'none',
    password_method TEXT,
    password_attempts INTEGER DEFAULT 0,
    is_archive      INTEGER NOT NULL DEFAULT 0,
    archive_member_count INTEGER,
    archive_total_uncompressed INTEGER,
    is_media        INTEGER NOT NULL DEFAULT 0,
    media_engine    TEXT,
    ocr_confidence_mean REAL,
    ocr_skipped_reason TEXT,
    first_seen_job_id TEXT REFERENCES bulk_jobs(id),
    last_seen_job_id  TEXT REFERENCES bulk_jobs(id),
    created_at      DATETIME DEFAULT (datetime('now')),
    updated_at      DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_source_files_path ON source_files(source_path);
CREATE INDEX IF NOT EXISTS idx_source_files_lifecycle ON source_files(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_source_files_ext ON source_files(file_ext);
CREATE INDEX IF NOT EXISTS idx_source_files_hash ON source_files(content_hash);
```

- [ ] **Step 2: Add source_file_id FK column to bulk_files**

In `init_db()`, add after the existing ALTER TABLE migrations (around line 584):

```python
await _add_column_if_missing(conn, "bulk_files", "source_file_id", "TEXT REFERENCES source_files(id)")
```

- [ ] **Step 3: Add data migration function**

Add a new function in `core/database.py`:

```python
async def _migrate_bulk_files_to_source_files(conn) -> int:
    """One-time migration: populate source_files from existing bulk_files data.

    For each distinct source_path, takes the most recent bulk_files row
    (by ROWID) and copies file-intrinsic columns to source_files.
    Updates bulk_files.source_file_id to point back.
    Returns count of migrated files.
    """
    # Check if migration already ran (source_files has data)
    row = await conn.execute_fetchone("SELECT COUNT(*) as c FROM source_files")
    if row and row["c"] > 0:
        return 0

    # Check if there's anything to migrate
    row = await conn.execute_fetchone("SELECT COUNT(*) as c FROM bulk_files")
    if not row or row["c"] == 0:
        return 0

    import uuid

    # Get distinct source_paths with their most recent bulk_files row
    rows = await conn.execute_fetchall("""
        SELECT bf.* FROM bulk_files bf
        INNER JOIN (
            SELECT source_path, MAX(ROWID) as max_rowid
            FROM bulk_files
            GROUP BY source_path
        ) latest ON bf.source_path = latest.source_path AND bf.ROWID = latest.max_rowid
    """)

    count = 0
    for r in rows:
        sf_id = uuid.uuid4().hex
        await conn.execute(
            """INSERT OR IGNORE INTO source_files (
                id, source_path, file_ext, file_size_bytes, source_mtime,
                stored_mtime, content_hash, output_path, mime_type, file_category,
                lifecycle_status, marked_for_deletion_at, moved_to_trash_at,
                purged_at, previous_path, protection_type, password_method,
                password_attempts, is_archive, archive_member_count,
                archive_total_uncompressed, is_media, media_engine,
                ocr_confidence_mean, ocr_skipped_reason,
                first_seen_job_id, last_seen_job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sf_id, r["source_path"], r["file_ext"], r["file_size_bytes"],
                r["source_mtime"], r.get("stored_mtime"), r.get("content_hash"),
                r.get("output_path"), r.get("mime_type"), r.get("file_category"),
                r.get("lifecycle_status", "active"),
                r.get("marked_for_deletion_at"), r.get("moved_to_trash_at"),
                r.get("purged_at"), r.get("previous_path"),
                r.get("protection_type", "none"), r.get("password_method"),
                r.get("password_attempts", 0),
                r.get("is_archive", 0), r.get("archive_member_count"),
                r.get("archive_total_uncompressed"),
                r.get("is_media", 0), r.get("media_engine"),
                r.get("ocr_confidence_mean"), r.get("ocr_skipped_reason"),
                r["job_id"], r["job_id"],
            ),
        )

        # Link all bulk_files rows for this source_path back to the source_file
        await conn.execute(
            "UPDATE bulk_files SET source_file_id = ? WHERE source_path = ?",
            (sf_id, r["source_path"]),
        )
        count += 1

    await conn.commit()
    return count
```

- [ ] **Step 4: Call migration in init_db()**

At the end of `init_db()`, after all ALTER TABLE migrations:

```python
migrated = await _migrate_bulk_files_to_source_files(conn)
if migrated:
    log.info("db.source_files_migration", migrated_count=migrated)
```

- [ ] **Step 5: Run init_db() and verify migration**

```bash
docker exec doc-conversion-2026-markflow-1 bash -c "python -c \"
import asyncio
from core.database import init_db, db_fetch_one
async def check():
    await init_db()
    r = await db_fetch_one('SELECT COUNT(*) as c FROM source_files')
    print(f'source_files rows: {r[\"c\"]}')
    r2 = await db_fetch_one('SELECT COUNT(*) as c FROM bulk_files WHERE source_file_id IS NOT NULL')
    print(f'bulk_files with source_file_id: {r2[\"c\"]}')
asyncio.run(check())
\""
```

Expected: `source_files rows: ~12847` (distinct files), all bulk_files rows linked.

- [ ] **Step 6: Commit**

```bash
git add core/database.py
git commit -m "feat: add source_files table + migrate existing bulk_files data"
```

---

### Task 2: Refactor `upsert_bulk_file()` to use source_files

**Files:**
- Modify: `core/database.py` — rewrite `upsert_bulk_file()`

- [ ] **Step 1: Add `upsert_source_file()` function**

```python
async def upsert_source_file(
    source_path: str,
    file_ext: str,
    file_size_bytes: int,
    source_mtime: float,
    job_id: str,
) -> str:
    """Insert or update a source_files record. Returns source_file_id."""
    row = await db_fetch_one(
        "SELECT id, source_mtime FROM source_files WHERE source_path = ?",
        (source_path,),
    )
    if row is not None:
        # Update last_seen_job_id and file metadata
        await db_execute(
            """UPDATE source_files
               SET file_size_bytes = ?, source_mtime = ?, file_ext = ?,
                   last_seen_job_id = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (file_size_bytes, source_mtime, file_ext, job_id, row["id"]),
        )
        return row["id"]
    else:
        import uuid
        sf_id = uuid.uuid4().hex
        await db_execute(
            """INSERT INTO source_files
               (id, source_path, file_ext, file_size_bytes, source_mtime,
                first_seen_job_id, last_seen_job_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sf_id, source_path, file_ext, file_size_bytes, source_mtime,
             job_id, job_id),
        )
        return sf_id
```

- [ ] **Step 2: Rewrite `upsert_bulk_file()` to delegate to source_files**

```python
async def upsert_bulk_file(
    job_id: str,
    source_path: str,
    file_ext: str,
    file_size_bytes: int,
    source_mtime: float,
) -> str:
    """Insert or update a bulk_files record linked to source_files. Returns file_id."""
    # Upsert into source_files first
    source_file_id = await upsert_source_file(
        source_path, file_ext, file_size_bytes, source_mtime, job_id,
    )

    # Check if this job already has a row for this source_path
    row = await db_fetch_one(
        "SELECT id, source_mtime FROM bulk_files WHERE job_id = ? AND source_path = ?",
        (job_id, source_path),
    )

    if row is not None:
        stored = row.get("source_mtime")
        if stored and abs(float(stored) - source_mtime) < 0.001:
            # Unchanged — skip
            await db_execute(
                "UPDATE bulk_files SET status = 'skipped', source_file_id = ? WHERE id = ?",
                (source_file_id, row["id"]),
            )
        else:
            # Changed — re-queue
            await db_execute(
                """UPDATE bulk_files SET status = 'pending',
                   source_mtime = ?, file_size_bytes = ?, source_file_id = ?
                   WHERE id = ?""",
                (source_mtime, file_size_bytes, source_file_id, row["id"]),
            )
        return row["id"]
    else:
        import uuid
        file_id = uuid.uuid4().hex
        await db_execute(
            """INSERT INTO bulk_files
               (id, job_id, source_path, file_ext, file_size_bytes,
                source_mtime, status, source_file_id)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (file_id, job_id, source_path, file_ext, file_size_bytes,
             source_mtime, source_file_id),
        )
        return file_id
```

- [ ] **Step 3: Commit**

```bash
git add core/database.py
git commit -m "feat: upsert_bulk_file now delegates to source_files for dedup"
```

---

### Task 3: Add source_files query functions

**Files:**
- Modify: `core/database.py` — add new query functions for source_files

- [ ] **Step 1: Add source_files query helpers**

```python
async def get_source_file_by_path(source_path: str) -> dict[str, Any] | None:
    """Fetch a source file by its unique path."""
    return await db_fetch_one(
        "SELECT * FROM source_files WHERE source_path = ?",
        (source_path,),
    )


async def get_source_file_count(
    lifecycle_status: str | None = None,
    file_ext: str | None = None,
) -> int:
    """Count distinct source files with optional filters."""
    sql = "SELECT COUNT(*) as c FROM source_files WHERE 1=1"
    params: list[Any] = []
    if lifecycle_status:
        sql += " AND lifecycle_status = ?"
        params.append(lifecycle_status)
    if file_ext:
        sql += " AND file_ext = ?"
        params.append(file_ext.lower().lstrip("."))
    row = await db_fetch_one(sql, tuple(params))
    return row["c"] if row else 0


async def update_source_file(source_file_id: str, **fields: Any) -> None:
    """Update arbitrary fields on a source_files row."""
    if not fields:
        return
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [source_file_id]
    await db_execute(
        f"UPDATE source_files SET {set_clause} WHERE id = ?",
        tuple(values),
    )


async def get_source_files_by_lifecycle_status(
    status: str, limit: int = 500, offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch source files by lifecycle status."""
    return await db_fetch_all(
        "SELECT * FROM source_files WHERE lifecycle_status = ? ORDER BY source_path LIMIT ? OFFSET ?",
        (status, limit, offset),
    )


async def get_source_files_pending_trash(grace_period_hours: int = 36) -> list[dict[str, Any]]:
    """Return source files marked_for_deletion whose grace period has expired."""
    return await db_fetch_all(
        """SELECT * FROM source_files
           WHERE lifecycle_status='marked_for_deletion'
           AND marked_for_deletion_at IS NOT NULL
           AND datetime(marked_for_deletion_at, '+' || ? || ' hours') < datetime('now')""",
        (grace_period_hours,),
    )


async def get_source_files_pending_purge(trash_retention_days: int = 60) -> list[dict[str, Any]]:
    """Return source files in_trash whose retention period has expired."""
    return await db_fetch_all(
        """SELECT * FROM source_files
           WHERE lifecycle_status='in_trash'
           AND moved_to_trash_at IS NOT NULL
           AND datetime(moved_to_trash_at, '+' || ? || ' days') < datetime('now')""",
        (trash_retention_days,),
    )
```

- [ ] **Step 2: Commit**

```bash
git add core/database.py
git commit -m "feat: add source_files query and update helpers"
```

---

### Task 4: Migrate lifecycle_manager to use source_files

**Files:**
- Modify: `core/lifecycle_manager.py` — lifecycle transitions operate on source_files

- [ ] **Step 1: Update lifecycle_manager imports**

Add imports for the new source_files functions:

```python
from core.database import (
    update_bulk_file,
    update_source_file,
    get_source_file_by_path,
)
```

- [ ] **Step 2: Update `_get_bulk_file()` to also return source_file_id**

No change needed — `SELECT * FROM bulk_files WHERE id=?` already returns `source_file_id`.

- [ ] **Step 3: Update `mark_file_for_deletion()`**

After the existing `update_bulk_file()` call, also update the source file:

```python
async def mark_file_for_deletion(bulk_file_id: str, scan_run_id: str) -> None:
    """Mark an active file for deletion (grace period begins)."""
    now = datetime.now(timezone.utc).isoformat()
    file_rec = await _get_bulk_file(bulk_file_id)

    await update_bulk_file(
        bulk_file_id,
        lifecycle_status="marked_for_deletion",
        marked_for_deletion_at=now,
    )

    # Also update source_files if linked
    sf_id = file_rec.get("source_file_id") if file_rec else None
    if sf_id:
        await update_source_file(
            sf_id,
            lifecycle_status="marked_for_deletion",
            marked_for_deletion_at=now,
        )

    # ... rest of function (version snapshot) unchanged
```

- [ ] **Step 4: Apply same pattern to `restore_file()`, `move_to_trash()`, `purge_file()`, `record_file_move()`**

Each function already calls `update_bulk_file()`. Add a matching `update_source_file()` call using the `source_file_id` from the bulk_file record. The source_file gets the same lifecycle_status transition.

For `record_file_move()`, also update source_files.source_path:

```python
if sf_id:
    await update_source_file(
        sf_id,
        source_path=str(new_path),
        previous_path=str(old_path),
        lifecycle_status="active",
    )
```

- [ ] **Step 5: Commit**

```bash
git add core/lifecycle_manager.py
git commit -m "feat: lifecycle transitions now update source_files alongside bulk_files"
```

---

### Task 5: Migrate lifecycle_scanner to query source_files

**Files:**
- Modify: `core/lifecycle_scanner.py` — deletion detection uses source_files

- [ ] **Step 1: Update deletion detection query**

Change the active-files scan (line ~241) from:

```sql
SELECT * FROM bulk_files WHERE lifecycle_status='active' ORDER BY source_path LIMIT ? OFFSET ?
```

To query source_files instead:

```sql
SELECT * FROM source_files WHERE lifecycle_status='active' ORDER BY source_path LIMIT ? OFFSET ?
```

The `mark_file_for_deletion()` call needs the bulk_file ID. Look up the corresponding bulk_files row:

```python
# After determining a source_file is missing:
bf_rows = await db_fetch_all(
    "SELECT id FROM bulk_files WHERE source_file_id = ? AND lifecycle_status = 'active'",
    (sf["id"],),
)
for bf in bf_rows:
    await mark_file_for_deletion(bf["id"], scan_run_id)
```

- [ ] **Step 2: Update moved-file detection query**

Change content_hash lookup (line ~428) from:

```sql
SELECT source_path FROM bulk_files WHERE content_hash=? AND job_id=? AND lifecycle_status='active'
```

To:

```sql
SELECT source_path FROM source_files WHERE content_hash=? AND lifecycle_status='active'
```

No job_id filter needed since source_files is already deduplicated.

- [ ] **Step 3: Update `get_bulk_file_by_path()` calls to use `get_source_file_by_path()`**

The lifecycle scanner calls `get_bulk_file_by_path()` to check if a file already exists. Replace with `get_source_file_by_path()` which returns the canonical record.

- [ ] **Step 4: Commit**

```bash
git add core/lifecycle_scanner.py
git commit -m "feat: lifecycle scanner queries source_files for dedup-safe deletion detection"
```

---

### Task 6: Migrate admin stats to use source_files

**Files:**
- Modify: `api/routes/admin.py` — cross-job stats query source_files

- [ ] **Step 1: Update status distribution query**

Change (line ~244):

```sql
-- Old: counts duplicated across jobs
SELECT status, COUNT(*) as count FROM bulk_files GROUP BY status

-- New: distinct file count from source_files + per-job status from bulk_files
SELECT lifecycle_status, COUNT(*) as count FROM source_files GROUP BY lifecycle_status
```

- [ ] **Step 2: Update category and size queries**

```sql
-- Category breakdown (was bulk_files)
SELECT file_category, COUNT(*) as count FROM source_files GROUP BY file_category ORDER BY count DESC

-- Total converted size (was bulk_files)
SELECT SUM(file_size_bytes) as total FROM source_files WHERE lifecycle_status='active'
```

- [ ] **Step 3: Keep per-job status queries on bulk_files**

The per-job status distribution (pending/converted/failed/skipped) should still come from `bulk_files` filtered by `job_id` — that's job-specific data.

- [ ] **Step 4: Commit**

```bash
git add api/routes/admin.py
git commit -m "feat: admin stats use source_files for accurate cross-job counts"
```

---

### Task 7: Migrate trash routes and scheduler

**Files:**
- Modify: `api/routes/trash.py` — query source_files for trash view
- Modify: `core/scheduler.py` — use source_files pending functions

- [ ] **Step 1: Update trash.py**

Change `get_bulk_files_by_lifecycle_status("in_trash")` to `get_source_files_by_lifecycle_status("in_trash")`. The trash view should show distinct files, not per-job duplicates.

- [ ] **Step 2: Update scheduler.py `run_trash_expiry()`**

Change:
```python
# Old
pending_trash = await get_bulk_files_pending_trash(grace_period_hours=grace_hours)
# New
pending_trash = await get_source_files_pending_trash(grace_period_hours=grace_hours)
```

And similarly for purge:
```python
# Old
pending_purge = await get_bulk_files_pending_purge(trash_retention_days=retention_days)
# New
pending_purge = await get_source_files_pending_purge(trash_retention_days=retention_days)
```

The `move_to_trash()` and `purge_file()` calls still accept bulk_file_id. Look up linked bulk_files:

```python
for sf in pending_trash:
    bf_rows = await db_fetch_all(
        "SELECT id FROM bulk_files WHERE source_file_id = ?", (sf["id"],),
    )
    for bf in bf_rows:
        await move_to_trash(bf["id"])
```

- [ ] **Step 3: Commit**

```bash
git add api/routes/trash.py core/scheduler.py
git commit -m "feat: trash and scheduler use source_files for dedup-safe lifecycle"
```

---

### Task 8: Migrate db_maintenance and search_indexer

**Files:**
- Modify: `core/db_maintenance.py` — use source_files for integrity checks
- Modify: `core/search_indexer.py` — reindex from source_files

- [ ] **Step 1: Update db_maintenance direct SQL**

Active converted files query (line ~132):
```sql
-- Old
SELECT id, output_path FROM bulk_files WHERE lifecycle_status='active' AND status='converted'
-- New
SELECT id, source_path, output_path FROM source_files WHERE lifecycle_status='active'
```

Active file paths (line ~153):
```sql
-- Old
SELECT source_path FROM bulk_files WHERE lifecycle_status='active'
-- New
SELECT source_path FROM source_files WHERE lifecycle_status='active'
```

Trashed files (line ~170):
```sql
-- Old
SELECT id, output_path FROM bulk_files WHERE lifecycle_status='in_trash'
-- New
SELECT id, output_path FROM source_files WHERE lifecycle_status='in_trash'
```

- [ ] **Step 2: Update search_indexer reindex query**

```sql
-- Old
SELECT * FROM bulk_files WHERE status='converted'
-- New: join to get distinct files with their latest conversion status
SELECT sf.*, bf.status, bf.converted_at
FROM source_files sf
JOIN bulk_files bf ON bf.source_file_id = sf.id AND bf.status = 'converted'
GROUP BY sf.id
```

- [ ] **Step 3: Commit**

```bash
git add core/db_maintenance.py core/search_indexer.py
git commit -m "feat: db_maintenance and search_indexer use source_files"
```

---

### Task 9: Update MCP tools and bulk_worker

**Files:**
- Modify: `mcp_server/tools.py` — use source_files for file inspection
- Modify: `core/bulk_worker.py` — link updates to source_files

- [ ] **Step 1: Update MCP tools**

Replace `get_bulk_file_by_path()` with `get_source_file_by_path()` for unique file lookups. Replace `get_bulk_files_by_lifecycle_status()` with `get_source_files_by_lifecycle_status()`.

- [ ] **Step 2: Update bulk_worker status updates**

When `_process_file()` updates a bulk_file status (converted, failed, skipped), also propagate key fields to source_files:

```python
# After successful conversion:
await update_bulk_file(file_id, status='converted', output_path=out, ...)

# Also update source_files with output_path and content_hash
sf_id = file_rec.get("source_file_id")
if sf_id:
    await update_source_file(sf_id, output_path=out, content_hash=hash, stored_mtime=mtime)
```

Only propagate file-intrinsic data (output_path, content_hash, stored_mtime, ocr_confidence_mean). Job-specific data (status, error_msg) stays in bulk_files only.

- [ ] **Step 3: Update bulk_scanner `_record_unrecognized()`**

After calling `upsert_bulk_file()` and `update_bulk_file()`, also update source_files:

```python
sf_id = (await db_fetch_one(
    "SELECT source_file_id FROM bulk_files WHERE id = ?", (file_id,),
) or {}).get("source_file_id")
if sf_id:
    await update_source_file(sf_id, mime_type=mime, file_category=category)
```

- [ ] **Step 4: Commit**

```bash
git add mcp_server/tools.py core/bulk_worker.py core/bulk_scanner.py
git commit -m "feat: bulk_worker and MCP tools propagate data to source_files"
```

---

### Task 10: Update CLAUDE.md and docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/version-history.md`
- Modify: `docs/key-files.md`
- Modify: `docs/gotchas.md`

- [ ] **Step 1: Update CLAUDE.md known issues**

Remove the bulk_files dedup known issue. Add a note about the source_files table in Architecture Reminders:

```markdown
- **Source files registry** — `source_files` table is the single source of truth for file-intrinsic data
  (path, size, lifecycle status). `bulk_files` links jobs to source files via `source_file_id`.
  Cross-job queries (admin stats, lifecycle, trash) use `source_files`. Per-job queries use `bulk_files`.
```

- [ ] **Step 2: Update version-history.md**

Add entry for the dedup fix under v0.13.8.

- [ ] **Step 3: Add gotcha**

```markdown
- **source_files vs bulk_files**: File-intrinsic data (path, size, hash, lifecycle) lives in
  `source_files`. Job-specific data (status, error_msg, converted_at) lives in `bulk_files`.
  Always update both when changing file-intrinsic fields. Cross-job queries must use `source_files`
  to avoid counting duplicates.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/version-history.md docs/key-files.md docs/gotchas.md
git commit -m "docs: document source_files dedup architecture"
```

---

### Task 11: Verification and cleanup

- [ ] **Step 1: Verify distinct counts match**

```sql
-- These should return the same count:
SELECT COUNT(*) FROM source_files;
SELECT COUNT(DISTINCT source_path) FROM bulk_files;
```

- [ ] **Step 2: Run a scan and verify no new duplicates**

Trigger a bulk scan, then verify:

```sql
-- source_files should NOT grow (same files re-scanned)
SELECT COUNT(*) FROM source_files;

-- bulk_files grows (new job rows) but source_files stays stable
SELECT COUNT(*) FROM bulk_files;
```

- [ ] **Step 3: Verify lifecycle works end-to-end**

Check that marking a file for deletion in source_files propagates correctly:

```sql
SELECT sf.lifecycle_status, COUNT(*)
FROM source_files sf
GROUP BY sf.lifecycle_status;
```

- [ ] **Step 4: Final commit and push**

```bash
git add -A
git commit -m "feat: source_files global registry — eliminates bulk_files cross-job duplication"
git push origin main
```
