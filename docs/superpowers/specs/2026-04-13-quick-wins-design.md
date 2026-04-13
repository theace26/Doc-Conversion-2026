# Spec A: Quick Wins — Inline File Lists, DB Backup/Restore, Hardware Specs

**Date:** 2026-04-13
**Status:** Approved
**Scope:** Three independent features that can be implemented in a single session.

---

## Feature 1: Inline Job File Lists on Bulk Page

### Problem

The bulk page shows "147 converted", "42 failed", "560 skipped" as plain text.
Users must navigate elsewhere to see which files failed or were skipped. The
directory progress counters ("23 failed") are also not clickable.

### Design

**Counter links:** Each counter value (`c-converted`, `c-failed`, `c-skipped`)
becomes a styled `<a>` element:
- Green for converted, red for failed, muted gray for skipped
- Underline on hover, cursor pointer
- Clicking toggles an inline collapsible `<div>` directly below the counters

**Inline file list panel:**
- Appears below the counter row inside the existing job card
- Fetches `/api/bulk/jobs/{job_id}/files?status={status}&per_page=50`
- Renders a compact table:

| Column | Source | Notes |
|--------|--------|-------|
| Filename | `source_path` (basename) | Truncate at 60 chars |
| Path | `source_path` (dirname) | Relative to source root |
| Size | `file_size` | Human-readable (KB/MB) |
| Duration | `duration_ms` | Converted files only |
| Error | `error_msg` | Failed files only, first 120 chars |

- "Load more" button at the bottom if total > 50 (paginate with offset)
- Only one list open at a time — clicking "failed" closes "converted"
- Clicking the same counter again collapses the list
- Subtle slide animation on expand/collapse

**Directory progress links:** The per-directory "done" and "failed" counts
also become clickable. Clicking "23 failed" in APPLICANT_INFORMATION/ expands
the same inline panel but filtered to files within that directory prefix.

### Files to Modify

- `static/bulk.html` — counter markup, new collapsible panel div
- `static/bulk.html` (JS section) — fetch + render logic, toggle behavior
- `static/css/bulk.css` or inline styles — link colors, panel styling

### No Backend Changes

The API endpoint `/api/bulk/jobs/{job_id}/files?status=...` already exists
and supports pagination.

---

## Feature 3: DB Backup & Restore

### Problem

No way to backup or restore the database from the UI. The only related
function is the repair endpoint which does a destructive dump-and-restore.

### Design

#### Backup

**API endpoint:** `POST /api/db/backup`
- Requires `UserRole.ADMIN`
- Query param `?download=true` — streams the file as a browser download
- Without `?download` — copies DB to `/data/backups/markflow-{timestamp}.db`
- Returns `{"backup_path": str, "size_mb": float, "timestamp": str}`

**Implementation:**
- Use `shutil.copy2()` on the DB file (not `iterdump()` — too slow on 200MB+)
- Before copying: `PRAGMA wal_checkpoint(TRUNCATE)` to flush WAL
- Create `/data/backups/` directory if it doesn't exist
- For download mode: use `FileResponse` with `media_type="application/octet-stream"`

**Guard:** Block if any bulk jobs are actively writing (same check as repair).

#### Restore

**API endpoint:** `POST /api/db/restore`
- Requires `UserRole.ADMIN`
- Accepts multipart file upload OR JSON body with `{"backup_path": str}`
- Validates uploaded file: open with `sqlite3`, run `PRAGMA integrity_check`
- Rotates current DB: `markflow.db` -> `markflow.db.pre-restore-{timestamp}.bak`
- Places restored file as `markflow.db`
- Closes all DB connections, reinitializes pool
- Returns `{"restored_from": str, "previous_backup": str, "size_mb": float}`

**Guard:** Block if any bulk jobs are running. Return 409 Conflict with message.

**List backups endpoint:** `GET /api/db/backups`
- Returns list of files in `/data/backups/` with name, size, modified date
- Sorted newest first

#### UI: DB Health Page

Add two buttons next to existing maintenance buttons (Compaction, Integrity,
Stale Check):

- **"Backup Database"** — opens a small modal:
  - "Download to browser" button (triggers `POST /api/db/backup?download=true`)
  - "Save on server" button (triggers `POST /api/db/backup`, shows success toast)

- **"Restore Database"** — opens a modal with two tabs:
  - **"Upload file"** tab: drag-and-drop zone for `.db` file upload
  - **"Server backups"** tab: lists backups from `GET /api/db/backups` with
    timestamp, size, and "Restore" button per row
  - Confirmation dialog: "This will replace the current database. A backup of
    the current DB will be saved automatically. Continue?"

#### UI: Settings Page

New subsection **"Database Maintenance"** inside "Files and Locations" group:

```html
<details class="settings-section">
  <summary>Database Maintenance</summary>
  <div class="card">
    <p class="hint">Create backups of the MarkFlow database or restore from
    a previous backup. For advanced maintenance, visit the
    <a href="/db-health.html">DB Health</a> page.</p>
    <div class="form-group">
      <button id="btn-backup-settings" class="btn btn-secondary">
        Backup Database
      </button>
      <button id="btn-restore-settings" class="btn btn-secondary">
        Restore Database
      </button>
    </div>
  </div>
</details>
```

These buttons trigger the same modals as the DB Health page (shared JS module).

### Files to Create/Modify

- `core/db_maintenance.py` — `backup_database()`, `restore_database()`,
  `list_backups()` functions
- `api/routes/db_health.py` — 3 new endpoints
- `static/db-health.html` — backup/restore buttons + modals
- `static/settings.html` — new "Database Maintenance" subsection
- `static/js/db-backup.js` — shared modal logic (or inline in both pages)

---

## Feature 4: Hardware Specs Help Page

### Problem

No documentation on minimum or recommended hardware. Users deploying
MarkFlow (including friend-deploys) don't know what machine to use.

### Design

New help article: `docs/help/hardware-specs.md`

**Content outline:**

1. **Quick Reference Table** — minimum vs recommended specs
2. **What the specs mean** — brief explanation of each component's role
3. **Concurrent user estimates** — how many users can search simultaneously
4. **What eats resources** — per-component breakdown
5. **GPU: optional but useful** — what GPU enables (Whisper, hashcat, vision)
6. **Storage sizing** — estimate based on source file volume
7. **Docker resource allocation** — recommended Docker Desktop memory/CPU settings

**Specs table:**

| | Minimum | Recommended |
|---|---|---|
| CPU | 4-core / 2.5 GHz | 6+ core / 2.6 GHz+ |
| RAM | 16 GB | 32-64 GB |
| GPU | None (CPU-only) | NVIDIA 6 GB+ VRAM (CUDA) |
| Storage | 50 GB SSD | 500 GB+ SSD |
| OS | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| Docker | Docker Desktop 4.x | Docker Desktop 4.x |

**Concurrent user estimates:**

| Spec tier | Concurrent search users | Notes |
|-----------|------------------------|-------|
| Minimum | ~5-10 | Keyword search only, no vector |
| Recommended (no GPU) | ~20-30 | Keyword + vector search |
| Recommended (with GPU) | ~20-50 | Same search, plus Whisper/hashcat/vision |

**Resource breakdown:**

| Component | RAM | CPU | Notes |
|-----------|-----|-----|-------|
| Meilisearch | ~1 GB baseline | Low | Scales with index size |
| Qdrant | ~500 MB baseline | Low | Scales with vector count |
| FastAPI app | ~200-500 MB | Moderate | Depends on concurrent requests |
| Bulk conversion | ~200 MB per worker | High (CPU-bound) | Throttled by max_concurrent (default 3) |
| LibreOffice headless | ~200 MB per instance | Moderate | Spawned per .ppt/.rtf conversion |
| OCR (Tesseract) | ~100 MB per page | High (CPU-bound) | Per-page, doesn't block search |
| Whisper (GPU) | ~1-2 GB VRAM | GPU | Only when transcribing audio/video |

### Files to Create/Modify

- `docs/help/hardware-specs.md` — new help article
- `CLAUDE.md` — add to help wiki inventory table

### Registration

Add to the help article inventory in CLAUDE.md and ensure `help.html`
includes the new article in its sidebar/TOC.

---

## Implementation Order

1. Feature 4 (hardware specs) — pure docs, zero risk, ship immediately
2. Feature 1 (inline file lists) — frontend-only, no backend changes
3. Feature 3 (DB backup/restore) — backend + frontend, most complex

Features 1 and 4 can be implemented in parallel.
