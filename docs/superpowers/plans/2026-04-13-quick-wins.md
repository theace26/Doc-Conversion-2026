# Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline job file lists on the bulk page, DB backup/restore with UI, and register the hardware specs help page.

**Architecture:** Feature 1 is frontend-only (the API exists). Feature 3 adds backend functions + API endpoints + UI on two pages. Feature 4 (hardware specs help page) is already written and committed -- just needs registration in the help sidebar.

**Tech Stack:** Python/FastAPI (backend), vanilla HTML/JS/CSS (frontend), SQLite, shutil

**Spec:** `docs/superpowers/specs/2026-04-13-quick-wins-design.md`

**XSS Note:** All JS code that renders user-supplied data (file paths, error messages) MUST use `textContent` for plain text and safe DOM methods (`createElement`, `appendChild`) for structured content. Never interpolate user strings into raw HTML.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `static/bulk.html` | Clickable counters + inline file list panel |
| Modify | `static/status.html` | Clickable counters in job cards + inline panel |
| Create | `core/db_backup.py` | `backup_database()`, `restore_database()`, `list_backups()` |
| Create | `tests/test_db_backup.py` | Unit tests for backup/restore |
| Modify | `api/routes/db_health.py` | 3 new endpoints: backup, restore, list-backups |
| Modify | `static/db-health.html` | Backup/restore buttons + modals |
| Modify | `static/settings.html` | New "Database Maintenance" subsection |
| Create | `static/js/db-backup.js` | Shared backup/restore modal logic |
| Modify | `static/help.html` | Register hardware-specs.md in sidebar TOC |

---

### Task 1: Inline File Lists -- Bulk Page

**Files:**
- Modify: `static/bulk.html`

The counters at lines 284-291 are plain `<span>` elements. Make them clickable links that toggle an inline file list.

- [ ] **Step 1: Make counter values clickable**

Replace the counter divs (lines 284-289) with anchor-wrapped versions. Each counter value becomes a link styled with the appropriate color (green/red/gray). Use `onclick="toggleFileList(event,'converted')"` pattern.

Converted = green (`var(--success)`), Failed = red (`var(--error)`), Skipped = gray (`var(--text-muted)`).

- [ ] **Step 2: Add CSS for counter links and inline panel**

Add styles for `.counter-link` (no text-decoration, pointer cursor, underline on hover), color variants (`--success`, `--error`, `--muted`), and `#inline-file-list` (scrollable panel, table styles, load-more button).

- [ ] **Step 3: Add collapsible panel div**

Insert `<div id="inline-file-list" hidden></div>` after the counters div, before the active-workers-panel.

- [ ] **Step 4: Add toggleFileList JavaScript**

Implement using safe DOM construction (createElement/textContent, NOT innerHTML with user data):

```javascript
// Key functions to implement:
// toggleFileList(event, status) - toggles the panel, fetches files
// loadFileListPage(status, page, replace) - fetches /api/bulk/jobs/{jobId}/files?status=...&page=N&per_page=50
// loadMoreFiles() - loads next page
// formatBytes(b) - human-readable file size
//
// Build table rows with createElement:
//   const td = document.createElement('td');
//   td.textContent = filename;  // SAFE: no XSS
//   row.appendChild(td);
```

The function should:
- Track `_activeFileListStatus` and `_fileListPage`
- Only one list open at a time (clicking same counter collapses)
- Build table with columns: File, Path, Size, Duration (converted) or Error (failed)
- "Load more" button at bottom if >= 50 results
- Use the existing `_currentJobId` variable (verify actual name in bulk.html JS)

- [ ] **Step 5: Test in browser**

Start or use an existing bulk job. Verify:
1. Counter values are colored and show pointer on hover
2. Click "converted" -- file list expands below
3. Click "converted" again -- collapses
4. Click "failed" -- switches to failed files with error column
5. "Load more" paginates correctly

- [ ] **Step 6: Commit**

```bash
git add static/bulk.html
git commit -m "feat: clickable job counters with inline file list on bulk page"
```

---

### Task 2: Inline File Lists -- Status Page Job Cards

**Files:**
- Modify: `static/status.html`

The status page renders job cards via `renderJobCard()`. The counter line inside each card shows converted/failed/skipped counts.

- [ ] **Step 1: Update renderJobCard counter line**

Find the counter rendering inside `renderJobCard()` (around lines 264-267). Wrap each count in an anchor tag with `onclick="toggleJobFileList(event,'${jobId}','${status}')"`.

Use the same color scheme: green for converted, red for failed, gray for skipped.

Add a `<div id="job-files-${jobId}" hidden></div>` below the counter line for the inline panel.

- [ ] **Step 2: Add toggleJobFileList JS + styles**

Same pattern as Task 1 but adapted for per-job-card panels. Each job card gets its own expandable file list. Use safe DOM construction.

- [ ] **Step 3: Test in browser**

Visit status.html with a completed job. Click counters, verify expand/collapse.

- [ ] **Step 4: Commit**

```bash
git add static/status.html
git commit -m "feat: clickable job counters with inline file list on status page"
```

---

### Task 3: DB Backup -- Backend

**Files:**
- Create: `core/db_backup.py`
- Create: `tests/test_db_backup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_db_backup.py` with test classes:

**TestBackup:**
- `test_backup_creates_file` -- backup produces a file that exists
- `test_backup_is_valid_sqlite` -- backup file is queryable
- `test_backup_creates_dir_if_missing` -- auto-creates backup directory

**TestRestore:**
- `test_restore_from_file` -- restores data from backup
- `test_restore_creates_pre_restore_backup` -- saves current DB before replacing
- `test_restore_rejects_invalid_file` -- non-SQLite file returns error

**TestListBackups:**
- `test_list_empty` -- empty dir returns []
- `test_list_after_backup` -- lists created backups with name/size/date

All functions are async. Use `tmp_path` fixture for test DBs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec doc-conversion-2026-markflow-1 python -m pytest tests/test_db_backup.py -v`

- [ ] **Step 3: Implement core/db_backup.py**

Three async functions:

`backup_database(db_path, backup_dir)`:
- Flush WAL with `PRAGMA wal_checkpoint(TRUNCATE)`
- Copy file with `shutil.copy2` to `markflow-{timestamp}.db`
- Return `{ok, backup_path, size_mb, timestamp}`

`restore_database(db_path, backup_path=None, upload_bytes=None)`:
- Validate source: `sqlite3.connect` + `PRAGMA integrity_check`
- Save current DB as `markflow.pre-restore-{timestamp}.db.bak`
- Copy restore source over current DB
- Return `{ok, restored_from, previous_backup, size_mb}`

`list_backups(backup_dir)`:
- Glob `markflow-*.db`, return list of `{name, size_mb, created_at, path}`

- [ ] **Step 4: Run tests -- all pass**

- [ ] **Step 5: Commit**

```bash
git add core/db_backup.py tests/test_db_backup.py
git commit -m "feat: DB backup/restore/list backend"
```

---

### Task 4: DB Backup -- API Endpoints

**Files:**
- Modify: `api/routes/db_health.py`

- [ ] **Step 1: Add three endpoints**

`POST /api/db/backup` -- requires ADMIN. Query param `?download=true` returns FileResponse. Otherwise returns JSON with backup_path/size.

`POST /api/db/restore` -- requires ADMIN. Accepts `UploadFile` or JSON `backup_path`. Guards against active jobs (same pattern as repair endpoint). Validates uploaded file.

`GET /api/db/backups` -- requires ADMIN. Returns list from `list_backups()`.

Add `UploadFile` to FastAPI imports, `Path` from pathlib.

- [ ] **Step 2: Test manually with curl**

- [ ] **Step 3: Commit**

```bash
git add api/routes/db_health.py
git commit -m "feat: DB backup/restore/list API endpoints"
```

---

### Task 5: DB Backup -- UI on DB Health Page

**Files:**
- Modify: `static/db-health.html`
- Create: `static/js/db-backup.js`

- [ ] **Step 1: Add backup/restore buttons**

Add "Backup Database" and "Restore Database" buttons to the action bar alongside existing maintenance buttons.

- [ ] **Step 2: Create shared JS module `static/js/db-backup.js`**

Functions: `showBackupModal()`, `showRestoreModal()`, `hideModal(id)`, `doBackup(mode)`, `loadBackupList()`, `doRestore(mode, serverPath)`.

Use safe DOM construction for the backup list (createElement, textContent for file names and paths). Use `fetch` for download mode with blob URL creation.

Backup modal: two buttons -- "Download to Browser" and "Save on Server".
Restore modal: file upload input + server backup list with per-row Restore buttons. Confirmation dialog before restore.

- [ ] **Step 3: Add modal HTML to db-health.html**

Two modal overlays: backup-modal and restore-modal. Add `<script src="/js/db-backup.js"></script>`.

- [ ] **Step 4: Add modal CSS**

`.modal-overlay` (fixed, centered, dark backdrop), `.modal-box` (card style).

- [ ] **Step 5: Test in browser**

DB Health page: Backup (download + server save), Restore (upload + server backup list).

- [ ] **Step 6: Commit**

```bash
git add static/db-health.html static/js/db-backup.js
git commit -m "feat: backup/restore UI on DB Health page"
```

---

### Task 6: DB Backup -- Settings Page

**Files:**
- Modify: `static/settings.html`

- [ ] **Step 1: Add "Database Maintenance" subsection**

Insert between "Info" and "Storage Connections" sections. Contains hint text linking to DB Health page, plus Backup and Restore buttons that trigger the same modals.

Add `<script src="/js/db-backup.js"></script>` and copy the modal HTML (or better: both pages include the same `db-backup.js` which injects the modal HTML on first call).

- [ ] **Step 2: Test in browser**

Settings > Database Maintenance > Backup/Restore buttons work.

- [ ] **Step 3: Commit**

```bash
git add static/settings.html
git commit -m "feat: Database Maintenance section in Settings"
```

---

### Task 7: Register Hardware Specs in Help Sidebar

**Files:**
- Modify: `static/help.html`

- [ ] **Step 1: Find help article registration**

Read `static/help.html` to find how articles are listed (JS array or HTML links).

- [ ] **Step 2: Add hardware-specs entry**

Add near "GPU Setup" in the TOC/sidebar.

- [ ] **Step 3: Verify in browser**

Help page shows "Hardware Specifications", content renders correctly.

- [ ] **Step 4: Commit**

```bash
git add static/help.html
git commit -m "docs: register hardware-specs.md in help sidebar"
```

---

### Task 8: Final Verification

- [ ] **Step 1: Run backend tests**

```bash
docker exec doc-conversion-2026-markflow-1 python -m pytest tests/test_db_backup.py -v
```

- [ ] **Step 2: Browser test all features**

1. Bulk page: clickable counters with inline file lists
2. Status page: clickable counters in job cards
3. DB Health: backup/restore modals
4. Settings: Database Maintenance section
5. Help: Hardware Specifications article

- [ ] **Step 3: Commit any fixes**
