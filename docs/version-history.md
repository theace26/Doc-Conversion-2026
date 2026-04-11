# MarkFlow Version History

Detailed changelog for each version/phase. Referenced from CLAUDE.md.

---

## v0.23.6 — Spec remediation Batch 1 (2026-04-10)

Six-item landing of the first batch of the v0.23.5 spec-review
remediation. No user-visible redesign — this release is about
hardening and small quality-of-life wins on top of the conversion
pipeline and the lifecycle manager. See `docs/superpowers/` for the
original audit and `memory/project_batch2_spec_remediation.md` for
the deferred Batch 2 scope.

### M1 — Width/height hints in markdown image output

`formats/markdown_handler.py` now emits images in the CommonMark
attribute-list form `![alt](src){width=Wpx height=Hpx}` when the
source `ImageData` carries dimensions. Previously dimensions were
encoded in the markdown title string (`![alt](src "WxH")`) which
was legal but noisy and harder to reason about. The ingest-side
parser in `_ast_to_elements` now recognises both the new attr-list
syntax AND the legacy `"WxH"` title form, so round-tripping an
old-format .md file still restores dims on the DocumentModel.

**Why it matters:** Tier 2 DOCX round-trip now keeps image
dimensions end-to-end, and any downstream tooling that reads the
generated markdown can size images without having to re-open the
PNG from `assets/`.

**Files touched:** `formats/markdown_handler.py`.

### M2 — Pre-conversion disk space check

Both the bulk worker and the single-file converter path now run a
disk-space pre-flight check before any files are touched.
`core/bulk_worker.py` adds `BulkJob._precheck_disk_space()`, called
immediately after the scan phase completes and before workers
start. It sums the input sizes, multiplies by a 3× conservative
buffer (markdown + sidecars + intermediates), and compares against
`shutil.disk_usage(output_path).free` on the nearest existing
parent directory. A failing job transitions cleanly to the
`failed` state with `cancellation_reason=Insufficient disk space:
…` and emits a `job_failed_disk_space` SSE event for the UI.

`core/converter._convert_file_sync` performs the same check
per-file, with the multiplier applied to `file_path.stat().st_size`.
Failures raise `ValueError("Insufficient disk space for
conversion: …")` which the existing exception handler converts
into a recorded `ConvertResult` with status `error`.

The feature logs `convert_disk_precheck` /
`bulk_disk_precheck` events with the full reasoning (input bytes,
required bytes, free bytes, probe path) so post-mortems are
trivial.

**Files touched:** `core/bulk_worker.py`, `core/converter.py`.

### M4 — Configurable trash retention + scheduled auto-purge

Two new preferences:

- `trash_auto_purge_enabled` (default `true`) — master switch for
  the automatic retention-based purge job
- (existing) `lifecycle_trash_retention_days` — authoritative
  retention window (already read by `run_trash_expiry` since
  v0.22.x, but with this release the purge branch moves to a
  dedicated daily job)

`core/scheduler.py` adds `_purge_aged_trash()`, registered as a
cron job at `04:00` local time. It respects the new master
switch, yields to active bulk jobs (like every other scheduled
job), reads `lifecycle_trash_retention_days`, and deletes trashed
rows older than the window. Log event
`scheduler.purge_aged_trash_complete` includes `purged_count` and
`bytes_freed`. The existing hourly `run_trash_expiry` job no
longer purges — it only moves expired marks into trash — which
means the two responsibilities are cleanly separated in the
scheduler registry (now reporting 17 jobs, up from 16).

`core/lifecycle_manager.py:32` gets a comment clarifying that
`TRASH_RETENTION_DAYS = 60` is just a default used in the trash
README text; the authoritative value lives in the preference.

Settings UI: new toggle **Auto-purge aged trash (v0.23.6)** under
the **File Lifecycle** section in `static/settings.html`, wired
through the generic `updateToggleLabel` handler that already
covers all toggles.

**Files touched:** `core/db/preferences.py`, `core/scheduler.py`,
`core/lifecycle_manager.py`, `static/settings.html`.

### C5 — Per-job force-OCR flag

New preference `force_ocr_default` (default `false`) plus a
per-job override exposed on the bulk job config modal as a
checkbox **Force OCR on every PDF page**. When enabled,
`PdfHandler.ingest()` dispatches to a new
`_ingest_pdfplumber_force_ocr()` path that skips text-layer
extraction entirely and marks every page as scanned, stashing
the per-page PIL images on `model._scanned_pages` so the deferred
OCR runner in `ConversionOrchestrator._check_and_run_deferred_ocr`
picks them up and runs Tesseract on each one.

The flag is plumbed end-to-end:

- `api/routes/bulk.py` adds a `force_ocr: bool | None` field to
  `CreateBulkJobRequest` and includes it in the overrides dict
  passed into `BulkJob`.
- `core/bulk_worker.py` reads `self.overrides.get("force_ocr")`
  in `_process_convertible` and plants it in `convert_opts`.
- `core/converter._convert_file_sync` reads
  `options.get("force_ocr")`, and when the format is PDF, calls
  `handler.ingest(working_path, force_ocr=True)` with a
  `TypeError` fallback for handlers that don't support the kwarg
  (all non-PDF handlers).

Settings UI: new toggle **Force OCR by default (v0.23.6)** under
the **OCR** section. Bulk modal UI: new checkbox next to the
**OCR mode** dropdown. Both hydrate from `force_ocr_default` on
page load.

**Why it matters:** PDFs that have a text layer but bad
character-set mapping (a very common failure mode of old scanners
that ran an OCR pass before saving) previously forced the user to
drop the text layer manually. Now the operator just ticks the
box.

**Files touched:** `core/db/preferences.py`, `formats/pdf_handler.py`,
`core/converter.py`, `core/bulk_worker.py`, `api/routes/bulk.py`,
`static/bulk.html`, `static/settings.html`.

### S4 — Structural hash helper + round-trip test

New helper `compute_structural_hash(model)` in
`core/document_model.py` that returns a deterministic SHA-256 hex
digest of a canonical representation of document structure:
heading count + levels + text, table count + dimensions + cell
text, image count + dimensions, list count + nesting depths. The
canonical rep is serialised via `json.dumps(sort_keys=True)` so
key ordering is stable across Python versions.

Added `_list_depths()` helper that recursively walks list items
and records nesting depth — the old `structural_hash()`
instance-method forgot about nested lists entirely.

`DocumentModel.structural_hash()` stays as an instance-method
wrapper for callers that already use that API.

New round-trip test `test_structural_hash_survives_roundtrip` in
`tests/test_roundtrip.py` asserts that DOCX → MD → DOCX
round-tripping preserves heading/table/image/list counts — strict
hash equality is too brittle because the DOCX round-trip can add
a trailing empty paragraph, but the core structural dimensions
are preserved.

**Files touched:** `core/document_model.py`,
`tests/test_roundtrip.py`.

### S1 — POST /api/convert/preview dry-run endpoint (enhanced)

The endpoint already existed in a minimal form (filename, format,
page count, element counts, warnings). This release rounds it out
with:

- Pre-flight zip-bomb check via the existing `check_zip_bomb()`
  helper — returns a warning and sets `ready_to_convert=false`
  when a file's compression ratio exceeds the threshold
- Size-limit check against `MAX_UPLOAD_MB` (default 100) —
  same behaviour
- `estimated_conversion_seconds` field — rough estimate based on
  ingest wall time × 2 (for export + IO), plus 5s/page when OCR
  is likely
- `ready_to_convert` boolean — drives the Convert button state in
  the UI

The Preview button on `static/index.html` existed but had a
minimal one-line `alert()` output. It now renders a formatted
multi-line block with all fields, warnings as a bulleted list,
and the `ready_to_convert` verdict.

`api/models.py` `PreviewResponse` grows the two new fields.
`core/converter.PreviewResult` dataclass matches.

**Files touched:** `core/converter.py`, `api/models.py`,
`api/routes/convert.py`, `static/index.html`.

### Documentation

- `docs/help/whats-new.md` — new v0.23.6 entry at top
- `docs/help/settings-guide.md` — documents the three new
  preferences (`trash_auto_purge_enabled`, `force_ocr_default`,
  plus the already-existing `lifecycle_trash_retention_days`)
- `docs/help/ocr-pipeline.md` — new "Forcing OCR on a file"
  section
- `docs/help/file-lifecycle.md` — mentions configurable retention
  and scheduled auto-purge
- `docs/help/document-conversion.md` — mentions the enhanced
  Preview button
- `docs/help/bulk-conversion.md` — documents the per-job
  force-OCR checkbox

### Gotchas introduced in this release

1. **force_ocr kwarg is PDF-only** — the converter uses a
   `TypeError` fallback so other handlers don't break, but no
   other handler honours the flag. Adding force_ocr to, say, an
   image handler would require a per-handler opt-in.
2. **Disk-space multiplier is 3×** — deliberately conservative.
   If a pipeline sees false-positive failures on a tight volume,
   the multiplier constant
   (`_DISK_SPACE_REQUIRED_MULTIPLIER` in `core/bulk_worker.py`)
   is the knob to turn. Not exposed as a preference yet.
3. **Daily purge runs at 04:00 local, not UTC** — matches the
   existing `run_db_compaction` cron trigger style. Operators
   running in a different tz should be aware.

---

## v0.23.5 — Search shortcuts, migration FK fix, MCP race fix (2026-04-10)

Two-track release: a set of new keyboard shortcuts on the Search
page, plus a pair of critical startup crash fixes discovered during
the v0.23.4 → v0.23.5 upgrade on the dev instance.

### Search Page Keyboard Shortcuts

Added ten shortcuts to `static/search.html` via a single global
`keydown` handler appended to the main IIFE. All `Alt`-based combos
to avoid conflicts with typing into the search input.

| Key | Action |
|-----|--------|
| `/` | Focus the search input from anywhere on the page |
| `Esc` | Contextual close: preview popup → AI drawer → flag modal → autocomplete → batch selection → blur search |
| `Alt + Shift + A` | Toggle AI Assist |
| `Alt + A` | Select every visible result on the current page |
| `Alt + C` | Clear batch selection |
| `Alt + Shift + D` | Download the current batch as ZIP (uses Shift to avoid Chrome's `Alt+D` address bar shortcut) |
| `Alt + B` | Trigger Browse All |
| `Alt + R` | Re-run the current search |
| `Alt + Click` on a result | Download the original source file directly instead of opening the viewer |
| `Shift + Click` on a checkbox | Range-select from the last-checked row to this one |

Implementation notes:
- `Alt+Click` on the hit-link diverts navigation to
  `/api/search/download/{index}/{doc_id}` via `e.preventDefault()` +
  `window.location.href`.
- `Shift+Click` range-select tracks `window._lastCheckedIdx` and
  dispatches synthetic `change` events on the in-range checkboxes so
  the existing batch-bar update logic fires.
- Global keydown listener checks `isEditable(e.target)` before
  handling `/` so it doesn't steal the key mid-input.
- `handleEscape()` returns `true` if it handled the key so we can
  `preventDefault()` conditionally.
- Discoverability: the search input gets a `title` tooltip on init.

### Help Documentation Updates

- **New:** `docs/help/whats-new.md` — user-facing version page
  listing changes v0.20.0 → v0.23.5, most recent on top. Registered
  as the first entry under **Basics** in `docs/help/_index.json`.
- **Rewritten:** `docs/help/search.md` — now covers the three search
  layers (keyword Meilisearch / vector Qdrant / AI Assist Claude)
  with worked examples per layer. Keyword syntax cheatsheet
  documents phrase `"quotes"`, negative `-term`, typo tolerance, and
  prefix match — with the honest note that AND/OR/NOT don't exist.
  AI Assist section has five example question categories.
- **Rewritten:** `docs/help/settings-guide.md` — matches the v0.23.4
  section layout (Files and Locations / Conversion Options / AI
  Options groups). Adds docs for `scan_skip_extensions`,
  `handwriting_confidence_threshold`, Database sample rows per table,
  Pipeline master switch, Cloud Prefetch, Auto-Conversion, Debug
  DB contention, Advanced.
- **Expanded:** `docs/help/keyboard-shortcuts.md` — three new
  subsections for the Search page: search box + autocomplete,
  page-level shortcuts, and result-row shortcuts. Full Esc priority
  order documented.
- **Unchanged:** `docs/help/ocr-pipeline.md` (already had v0.20.3
  handwriting fallback section), `docs/help/database-files.md`
  (already matched v0.23.1 handler reality).

### Crash Fix A — Migration FK Enforcement

**Symptom:** On startup after pulling v0.23.4 onto a long-running
dev instance, both containers crash-looped. MCP logs showed
`sqlite3.IntegrityError: FOREIGN KEY constraint failed` during
`_run_migrations`. Main container logs showed `database is locked`
because the two containers were racing on migration.

**Root cause:** `core/db/connection.py` sets `PRAGMA foreign_keys=ON`
on every connection open. Migration 27 (v0.23.3 re-run of the
`bulk_files` rebuild) does the standard SQLite "new table / insert
from old / drop / rename" pattern. With FK enforcement on,
`INSERT INTO bulk_files_new SELECT ... FROM bulk_files` rejects any
row whose `job_id` no longer exists in `bulk_jobs` or whose
`source_file_id` no longer exists in `source_files`. The dev
instance had accumulated orphans over 20+ releases.

**Fix (`core/db/schema.py`):** At the start of `_run_migrations`,
`await conn.commit()` to flush any implicit transaction, then
`await conn.execute("PRAGMA foreign_keys = OFF")`. This is the
standard SQLite recommendation for schema rebuilds (see
<https://sqlite.org/lang_altertable.html#otheralter>). `init_db()`
already calls `PRAGMA foreign_keys = ON` at line 916 immediately
after `_run_migrations` returns, so enforcement is restored for
normal operation. Historical orphans get copied through to the new
table; going-forward inserts with bad FKs continue to be rejected.

### Crash Fix B — MCP Migration Race

**Symptom:** `mcp_server/server.py:304` called
`asyncio.run(init_db())` on startup, and so did the main container.
With `docker-compose depends_on` providing only start-order
guarantees (not readiness), both processes hit the migration
runner concurrently. The loser got `database is locked` because the
winner held an exclusive lock.

**Fix (`mcp_server/server.py`):** MCP is a reader. The main
container owns schema setup and migrations. Removed the `init_db()`
call. Replaced with a 2-minute polling loop that waits for the
`schema_migrations` table to exist (via
`SELECT COUNT(*) FROM sqlite_master WHERE ... name='schema_migrations'`)
before proceeding. If the wait times out, MCP logs a warning and
starts anyway — the first query will surface any real problem.

### Files

- Modified: `core/version.py` (0.23.4 → 0.23.5)
- Modified: `CLAUDE.md` (current version section)
- Modified: `core/db/schema.py` (`_run_migrations` FK-off prologue)
- Modified: `mcp_server/server.py` (init_db removed, DB-ready poll added)
- Modified: `static/search.html` (keyboard shortcut handler, Alt-click download, shift-click range select)
- Modified: `docs/help/search.md` (rewrite)
- Modified: `docs/help/settings-guide.md` (rewrite for v0.23.4 layout)
- Modified: `docs/help/keyboard-shortcuts.md` (Search page expansion)
- Modified: `docs/help/_index.json` (registered whats-new under Basics)
- Created: `docs/help/whats-new.md`
- Modified: `docs/version-history.md` (this entry)

---

## v0.23.4 — Settings page reorganization (2026-04-10)

UX pass on the Settings page. Reorganized 21 sections into logical
groups with clearer naming.

### Section Renames
- **Locations** → **Files and Locations**
- **Conversion** → **Conversion Options**
- **AI Enhancement** → **AI Options**

### Section Regrouping
- **Files and Locations** group: Password Recovery, File Flagging,
  Info, Storage Connections now follow immediately after the renamed
  "Files and Locations" section.
- **Conversion Options** group: OCR, Path Safety now follow
  immediately after "Conversion Options".
- **AI Options** group: Vision & Frame Description, Claude Integration
  (MCP), Transcription, AI-Assisted Search now follow immediately
  after "AI Options".

### New Section Order
1. Files and Locations, 2. Password Recovery, 3. File Flagging,
4. Info, 5. Storage Connections, 6. Conversion Options, 7. OCR,
8. Path Safety, 9. AI Options, 10. Vision & Frame Description,
11. Claude Integration (MCP), 12. Transcription, 13. AI-Assisted Search,
14. Logging, 15. File Lifecycle, 16. Pipeline, 17. Cloud Prefetch,
18. Search Preview, 19. Auto-Conversion, 20. Debug: DB Contention
Logging, 21. Advanced

### Files
- Modified: `static/settings.html` (section moves + renames only,
  no content changes)

---

## v0.23.3 — UX responsiveness, bulk restore, extension exclude, migration hardening (2026-04-10)

Focused on user-perceived responsiveness for heavy operations and two new
features. Also fixes the migration runner bug that silently dropped DDL.

### Migration Hardening
- **Migration 27:** Re-runs the `bulk_files` table rebuild that migration 26
  silently failed on. Converts `UNIQUE(job_id, source_path)` to
  `UNIQUE(source_path)` — fixes the `ON CONFLICT` crash that killed every
  bulk job since v0.23.0.
- **`INSERT OR IGNORE` on `schema_migrations`:** Prevents restart crash when
  a migration version row already exists.
- **`except: pass` narrowed to ALTER TABLE only:** Non-ALTER DDL failures
  (CREATE, DROP, INSERT, RENAME) now propagate instead of being silently
  swallowed. Root cause of the migration 26 failure.
- **`get_preference()` signature fixes:** `migrations.py` and
  `preferences_cache.py` were calling `get_preference(key, default)` but
  the function only takes `key`. Default handling moved to the cache layer.

### UX Responsiveness
- **Empty Trash:** Batched DB operations (chunks of 200), disk deletions in
  parallel (batches of 50 via thread pool), `asyncio.sleep(0)` between
  chunks. Returns immediately, runs in background. Frontend polls
  `GET /api/trash/empty/status` every 2s showing "Purging X / Y..."
- **Rebuild Search Index:** Polls `/api/search/index/status` every 3s,
  shows "Rebuilding (X docs)..." until all sub-indexes finish.
- **DB Compaction:** Shows "Compacting..." with 10s hold, then confirms
  via health poll.
- **Integrity Check:** Button text "Checking... (this may take a minute)".
- **Stale Data Check:** Button text "Checking... (scanning tables)".
- **Trash confirm dialog:** Was unstyled native `<dialog>` anchored to
  top-left. Now centered with backdrop, border-radius, padding.

### New Features
- **Bulk Restore** (`POST /api/trash/restore-all`): Background task +
  progress polling. "Restore All" button on trash page with
  "Restoring X / Y..." feedback. Processes in batches of 50 with
  event loop yields.
- **Extension Exclude** (`scan_skip_extensions` preference): JSON list of
  file extensions to skip during scanning (without dots). Wired into both
  `core/bulk_scanner.py` and `core/lifecycle_scanner.py`. Configurable
  via Settings > Conversion. Example: `["tmp", "bak", "log"]`.

### Files
- Modified: `core/db/schema.py` (migration 27 + runner hardening),
  `core/db/migrations.py` (get_preference fix), `core/preferences_cache.py`
  (default handling fix), `core/lifecycle_manager.py` (batch purge +
  restore_all), `api/routes/trash.py` (4 new endpoints), `static/trash.html`
  (dialog fix + restore all + progress polling), `static/bulk.html` (index
  rebuild polling), `static/db-health.html` (compaction/integrity/stale
  feedback), `core/bulk_scanner.py` (extension exclude), `core/lifecycle_scanner.py`
  (extension exclude), `core/db/preferences.py` (scan_skip_extensions),
  `api/routes/preferences.py` (extension exclude schema), `Dockerfile.base`
  (pysqlcipher3 removed — build failure)

---

## v0.23.2 — Critical bug fixes: bulk upsert, scheduler coroutine, vision MIME (2026-04-10)

Three bugs fixed, one critical (all bulk conversions stalled since schema/code mismatch).

### Bug fixes

- **`bulk_job_fatal` ON CONFLICT mismatch (critical)** — The audit remediation plan
  (v0.23.0) changed all upsert SQL from `ON CONFLICT(job_id, source_path)` to
  `ON CONFLICT(source_path)`, but the `bulk_files` table schema still had
  `UNIQUE(job_id, source_path)`. Every bulk conversion job failed immediately,
  leaving 1,654 files permanently stuck in pending. Migration 26 rebuilds the table
  with `UNIQUE(source_path)`, deduplicating on `MAX(ROWID)` per `source_path`.

- **Unawaited `get_all_active_jobs()` coroutine** — `_bulk_files_self_correction`
  in `core/scheduler.py:481` and the admin cleanup endpoint in
  `api/routes/admin.py:421` called `get_all_active_jobs()` without `await`.
  The coroutine was truthy (always non-empty object), so the scheduler always
  skipped self-correction and the admin endpoint always returned 409. Added `await`.

- **Vision adapter MIME mislabeling** — All four provider batch methods
  (`_batch_anthropic`, `_batch_openai`, `_batch_gemini`, single-image path) used
  `path.suffix` to guess MIME type via `mimetypes.guess_type()`. Files with
  mismatched extensions (e.g. GIF saved as `.png`) sent the wrong `media_type` to
  the API, causing HTTP 400 and failing entire 10-image batches. Now uses
  `detect_mime()` (magic-byte header detection) which was already defined but unused
  in these code paths.

### Files changed
- `core/db/schema.py` — base DDL: `UNIQUE(source_path)`, migration 26 (table rebuild)
- `core/scheduler.py` — `await get_all_active_jobs()` in self-correction job
- `api/routes/admin.py` — `await get_all_active_jobs()` in cleanup endpoint
- `core/vision_adapter.py` — `detect_mime(path)` replaces `path.suffix` in 4 locations
- `core/version.py` — bump to 0.23.2

---

## v0.23.1 — Database file handler: schema + sample data extraction (2026-04-09)

New `DatabaseHandler` replaces `BinaryHandler` for database file extensions,
extracting full schema, sample data, relationships, and indexes into structured
Markdown summaries.

### Supported Formats
- **SQLite** (`.sqlite`, `.db`, `.sqlite3`, `.s3db`) — Python built-in `sqlite3`
- **Microsoft Access** (`.mdb`, `.accdb`) — engine cascade: mdbtools -> pyodbc -> jackcess
- **dBase / FoxPro** (`.dbf`) — `dbfread` (pure Python)
- **QuickBooks** (`.qbb`, `.qbw`) — best-effort binary header parse; metadata-only
  for encrypted/newer files with QuickBooks Desktop export instructions

### Architecture
- Engine-per-format behind a common ABC (`DatabaseEngine` in `formats/database/engine.py`)
- Five dataclasses: `TableInfo`, `ColumnInfo`, `RelationshipInfo`, `IndexInfo`
- Engine cascade for Access: `MdbtoolsBackend` (CLI) -> `pyodbc` (ODBC) -> `jackcess` (Java)
- Capability detection (`formats/database/capability.py`) probes installed backends at startup
- Password cascade reuses existing archive handler pattern (empty -> static list -> dictionary)

### Markdown Output
Each database produces: H1 title, metadata property table, schema overview table,
per-table column definitions + sample data (default 25 rows, configurable via
`database_sample_rows` preference, max 1000), relationships table, indexes table.
QuickBooks files include company name extraction and manual export instructions.

### Limits
- Max 50 tables with full detail sections (remaining counted in summary)
- Max 20 columns in sample data tables (remaining noted)
- Max 1000 sample rows per table (hard cap)

### Dependencies Added (Dockerfile.base)
- `mdbtools`, `unixodbc-dev`, `odbc-mdbtools` (apt)
- `dbfread`, `pyodbc`, `pysqlcipher3` (pip)
- Optional: Java JRE + jackcess JAR for full .accdb support

### Files
- Created: `formats/database/` package (7 files: `__init__.py`, `engine.py`,
  `sqlite_engine.py`, `access_engine.py`, `dbase_engine.py`, `quickbooks_engine.py`,
  `capability.py`)
- Created: `formats/database_handler.py`
- Created: `tests/test_database_engines.py`, `tests/test_database_handler.py`
- Created: `docs/help/database-files.md`
- Modified: `formats/__init__.py`, `formats/binary_handler.py`,
  `core/db/preferences.py`, `api/routes/preferences.py`, `Dockerfile.base`,
  `docs/formats.md`

---

## v0.23.0 — Audit remediation: DB pool, pipeline hardening, vision MIME fix (2026-04-09)

20-task overhaul addressing all 17 items from the Health Audit + Specification
Review. Organized into 4 waves for maximum parallelism.

### DB Layer
- **Connection pool** (`core/db/pool.py`): Single-writer async write queue + 3
  read-only connections. WAL mode, 30s busy timeout. `db_fetch_one/all` and
  `db_execute` in `core/db/connection.py` transparently route through pool when
  initialized, falling back to direct connection during startup schema init.
  Eliminates "database is locked" errors under concurrent bulk + lifecycle scans.
- **Preferences TTL cache** (`core/preferences_cache.py`): 5-minute in-memory
  cache. Invalidated on PUT via `api/routes/preferences.py`. Eliminates ~50K
  DB reads/day from scheduler ticks, worker files, and scan iterations.
- **bulk_files dedup migration** (`core/db/migrations.py:run_bulk_files_dedup`):
  One-time cleanup keeping only the latest row per `source_path`. Expected to
  delete ~187K rows. Schema migrated from `unique(job_id, source_path)` to
  `unique(source_path)` so rescans update in place instead of creating duplicates.
- **Stale job detection** (`core/db/migrations.py:add_heartbeat_column` +
  `cleanup_stale_jobs`): `bulk_jobs` gets `last_heartbeat` column. Workers update
  every 60s. Startup cleans jobs stuck in 'running' with heartbeat > 30 min old.
- **Counter batching** (`core/bulk_worker.py:CounterAccumulator`): Batches
  converted/failed/skipped counter updates (flush every 50 files or 5s). Reduces
  per-scan DB writes from ~800K to ~16K.

### Pipeline
- **Incremental scanning** (`core/bulk_scanner.py`): Files already converted with
  same mtime are skipped. Post-scan cross-job dedup DELETE as safety net.
- **Pipeline stats cache** (`api/routes/pipeline.py`): 20s TTL on `/api/pipeline/stats`.
  Invalidated on bulk job start/complete via `core/scan_coordinator.py`.
- **Lifecycle I/O fix** (`core/lifecycle_manager.py`): `shutil.move` and
  `unlink` wrapped in `asyncio.to_thread()`. Added `recover_moving_files()`
  for startup crash recovery.
- **Forced trash expiry** (`core/scheduler.py`): Every 4th `run_trash_expiry`
  invocation bypasses the active-jobs check.
- **Housekeeping job** (`core/scheduler.py:run_housekeeping`): Every 2 hours.
  Cross-job dedup + PRAGMA optimize + conditional VACUUM (>10% free pages).
  Does NOT yield to active bulk jobs.
- **Vector backpressure** (`core/bulk_worker.py`): Bounded semaphore (20) on
  Qdrant indexing tasks. Skipped files picked up on next lifecycle scan.

### PDF Engine
- **PyMuPDF as default** (`formats/pdf_handler.py`): Pages with table gridlines
  (detected via `get_drawings()` line analysis) switch to pdfplumber for that
  page only. All other pages use PyMuPDF (~3x faster). Full pdfplumber fallback
  on any PyMuPDF failure. Controlled by `pdf_engine` preference.

### Vision Adapter
- **Magic-byte MIME detection** (`core/vision_adapter.py:detect_mime`): Detects
  JPEG, PNG, GIF, BMP, WebP from file headers. Fixes 115 batch failures from
  .jpg files that were actually GIFs.
- **Provider-aware batch limits** (`core/vision_adapter.py:plan_batches`):
  Per-provider caps for anthropic (24MB/20img), openai (18MB/10img), gemini
  (18MB/16img), ollama (50MB/5img).

### Frontend
- **Polling reduction** (`static/js/global-status-bar.js`): 20s visible (was 5s),
  30s hidden, stops after 30 min hidden. Tab re-activation reloads page.
  Eliminates ~40K unnecessary requests/day.

### Other
- **Conversion semaphore auto-detect** (`core/converter.py`): `cpu_count // 2`,
  capped 2–8. Configurable via `max_concurrent_conversions` preference.
- **Removed unused deps** (`requirements.txt`): `mammoth` and `markdownify`
  deleted (zero imports found).
- **Logging suppression** (`core/logging_config.py`): httpx/httpcore set to
  WARNING (~40K debug lines/day from Meilisearch polling).
- **Structural hash** (`core/document_model.py:DocumentModel.structural_hash`):
  SHA-256 of heading/table/image/list structure for round-trip comparison.
- **markitdown validation** (`core/validation/markitdown_compare.py`): CLI tool
  for comparing MarkFlow output against Microsoft markitdown. Dev use only.
- **Startup migrations** (`main.py:lifespan`): Pool init, heartbeat column,
  stale job cleanup, bulk dedup, vision MIME re-queue, lifecycle timer warnings,
  crash recovery.

### Files modified (18) + created (4)
Modified: `main.py`, `core/version.py`, `core/db/connection.py`, `core/db/bulk.py`,
`core/bulk_worker.py`, `core/bulk_scanner.py`, `core/converter.py`,
`core/document_model.py`, `core/lifecycle_manager.py`, `core/logging_config.py`,
`core/scan_coordinator.py`, `core/scheduler.py`, `core/vision_adapter.py`,
`formats/pdf_handler.py`, `api/routes/pipeline.py`, `api/routes/preferences.py`,
`requirements.txt`, `static/js/global-status-bar.js`

Created: `core/db/pool.py`, `core/db/migrations.py`, `core/preferences_cache.py`,
`core/validation/` (package with `markitdown_compare.py`)

### Validation
`python -m py_compile` clean on all 22 files.

---

## v0.22.19 — Scan-time junk-file filter + historical cleanup (2026-04-08)

Direct follow-up to the v0.22.18 sweep. Triggered by a UI screenshot of
a cancelled bulk job (`c0ae5913`) showing 90 failed files, ~43 of which
displayed `"Cannot convert ~$xxx.doc: LibreOffice not found. Install
libreoffice-headless."` in the error column. v0.22.18's libreoffice
helper fix would have shown the *real* error instead, but didn't address
the deeper issue: **these files should never have been queued in the
first place**.

### What was wrong

The failing file paths followed an unmistakable pattern:

```
~$-09-17 MLA Official Redline.doc
~$.lois.agency fee payer memo.doc
~$cific Fisherman Inc Wage Report 2008-2009.doc
~$2017.CEWW.JM.Support.Letter.docx
~$00789-MG SIH Grant Award.docx
~WRL2619.tmp
```

Every one starts with `~$` — Microsoft Office's **lock-file prefix**.
When you open a document in Word/Excel/PowerPoint/Visio, Office
creates a hidden ~162-byte sentinel file with the same name prefixed
by `~$`. It's not a real document, just an "I'm in use" marker that
gets cleaned up when you close the file. They linger forever if Office
crashes mid-edit.

When the bulk scanner walked the source share, it picked up these
sentinel files (since they have valid `.doc` / `.docx` / `.xlsx`
extensions), queued them into `bulk_files`, and a worker eventually
shipped them to `libreoffice --headless --convert-to docx`. LibreOffice
correctly exited non-zero (the file isn't a real document), and the
*pre-v0.22.18* helper then raised the misleading
`"LibreOffice not found. Install libreoffice-headless."` error.

The accumulated damage from no scanner-side filtering, observed in
the live DB at upgrade time:

| Junk type | bulk_files rows | source_files rows |
|---|---|---|
| `Thumbs.db` (Windows thumbnail cache) | 1,327 | 453 |
| `~$*` Office lock files | (subset of failed rows above) | (similar) |
| `~WRL*.tmp` Word recovery temp | 3 in last cancelled job | similar |

Plus inflated `total_files` counts on every bulk job and inflated
`source_files` lifecycle scan counts on every cycle.

### The fix

**`core/bulk_scanner.py` — new `is_junk_filename()` helper.** Defines
two constants and one helper function near the top of the module:

```python
_JUNK_BASENAME_PREFIXES_LOWER = (
    "~$",        # MS Office lock files (Word/Excel/PowerPoint/Visio)
    "~wrl",      # Word recovery temp files
)
_JUNK_BASENAMES_LOWER = frozenset({
    "thumbs.db", "desktop.ini", ".ds_store", ".appledouble",
    "ehthumbs.db", "ehthumbs_vista.db",
})

def is_junk_filename(name: str) -> bool: ...
```

Pure case-insensitive string ops, no regex — runs millions of times
per scan and a regex compile is overkill for six fixed patterns.
Case-insensitive because Windows filesystems are case-insensitive
and the same artifact can appear as `Thumbs.db` / `THUMBS.DB` /
`thumbs.db`.

**`BulkScanner._is_excluded()`** now calls `is_junk_filename()` first
(cheapest check, catches the noisiest leaks), before the existing
exclusion-prefix and skip-pattern checks.

**`core/lifecycle_scanner.py`** — both `_is_excluded` closures (one in
`_serial_lifecycle_walk`, one in `_parallel_lifecycle_walk`) get the
same prepended check, importing `is_junk_filename` from
`core.bulk_scanner`. This means:

- New scans never queue junk files
- Existing pending junk rows stay until cleaned up (next item)

**`main.py:lifespan` — one-time historical cleanup migration.** A
DELETE migration runs once on startup, gated by the
`junk_cleanup_v0_22_19_done` preference flag. Mirrors the same patterns
the scanner now filters, expressed as SQL `LIKE` over `source_path`
suffixes (handles both POSIX `/` and Windows `\` separators on
UNC-mounted paths). Deletes from `bulk_files` first, then `source_files`,
to handle the FK relationship cleanly. Logs counts via
`markflow.junk_cleanup_v0_22_19`. Idempotent — runs exactly once per
database, then the preference flag short-circuits all future startups.

### Why this matters for prod-readiness

The 43 misleading errors per job were the loud visible symptom, but
the real cost was cumulative:

- Every scan added more junk rows to `source_files`
- Every bulk job re-processed the same lock files
- The file count UI badge overstated by ~5%
- The `lifecycle_scan.file_error` count was inflated
- Users saw "LibreOffice not found" messages and started chasing a
  Dockerfile bug that didn't exist (Dockerfile.base correctly installs
  `libreoffice-writer` + `libreoffice-impress`)

This is the same "noise hides real signal" pattern v0.22.18 set out
to fix — the difference is v0.22.18 fixed the *symptom layer* (error
messages, retry logic, timeouts) and v0.22.19 fixes the *data layer*
(don't queue garbage in the first place). Together they eliminate
roughly **2,521 noisy log/DB events / 24h** without adding any new
code paths to maintain.

### Validation performed

- `python -m py_compile` clean on all four edited files
  (`core/bulk_scanner.py`, `core/lifecycle_scanner.py`, `main.py`,
  `core/version.py`).
- Diagnostic SQL confirmed the upgrade-time leak counts (1,327 / 453)
  via `core/database` queries against the live DB.

### Not yet validated

- **Live deploy verification.** After rebuild + restart, expect:
  1. Startup log line `markflow.junk_cleanup_v0_22_19` with
     `bulk_files_deleted` and `source_files_deleted` counts roughly
     matching the diagnostic's 1,327 / 453.
  2. Post-startup query `SELECT count(*) FROM bulk_files WHERE
     source_path LIKE '%Thumbs.db'` returning 0.
  3. Next bulk scan over the same source share producing zero junk
     rows in `bulk_files`.

### Known follow-ups still outstanding

- v0.22.15: broken Convert-page SSE, uncancellable `asyncio.wait_for`
  on Whisper, corrupt-audio tensor reshape.
- Pre-prod: lifecycle timers at testing values, security audit
  (62 findings), UX overhaul, DB contention instrumentation cleanup
  (now safe to remove once v0.22.18 + v0.22.19 burn-in confirms zero
  contention errors).

---

## v0.22.18 — Production-readiness sweep: lifecycle/vision/qdrant/libreoffice (2026-04-08)

Four targeted fixes from a runtime-log audit of the live `vector` branch
stack. Each one closes a recurring failure mode that was bleeding errors
into the logs without crashing the app, masking real signal and blocking
the path to production.

### What was wrong (from the audit)

A scan of `markflow.log` / `db-active.log` / `db-contention.log` over
the previous 24h surfaced four buckets:

1. **1,929 "database is locked" errors / 24h** — lifecycle scanner
   colliding with bulk_worker writes. Root cause was structural: the
   scheduler-level "skip if bulk active" guard only checks at scan
   *kickoff*. A 45-min lifecycle scan keeps walking even if a bulk job
   starts on minute 2, and the per-file `_process_file` writes don't
   use `db_write_with_retry` (bulk_worker has used it from day one for
   exactly this reason). Cancel checks existed at the directory
   boundary in the serial walk and at the *batch* boundary in the
   parallel walk — neither was checked between individual files.

2. **154 vision_adapter `describe_batch_failed` / 24h** — every single
   one was Anthropic's per-image 5 MB hard cap. The adapter already
   had a 24 MB *total request* sub-batch cap (good for the 32 MB
   request limit), but no per-image enforcement. A single 22 MB camera
   image in a batch of 10 still under-budgets the request envelope and
   then explodes on the per-image limit.

3. **381 `bulk_vector_index_fail` / 24h** — all
   `ResponseHandlingException(ReadTimeout)`. The bulk_worker already
   wraps `index_document` in try/except → `log.warning` (the audit
   overstated this as a critical failure; vector indexing is
   documented as best-effort and runs in a detached background task).
   Real fix is just bumping `AsyncQdrantClient(timeout=…)` from the
   default 5s to 60s — under bulk load, legitimate upserts were
   tripping the default.

4. **14 LibreOffice "not found" errors** — the helper raises
   `"LibreOffice not found. Install libreoffice-headless."` in TWO
   different cases: (a) neither `libreoffice` nor `soffice` is on
   PATH, and (b) one or both binaries ran fine but the conversion
   exited nonzero on a corrupt file. `Dockerfile.base` does install
   `libreoffice-writer` + `libreoffice-impress`, so the 14 errors are
   case (b) — file-level conversion failures masquerading as missing
   binary errors. Misleading message, real bug.

### Fixes

**1. `core/lifecycle_scanner.py` — yield + retry-on-lock**

- New `_process_file_with_retry()` wraps `_process_file` with
  3-attempt exponential-backoff retry on
  `OperationalError("database is locked")`. Mirrors the
  `db_write_with_retry` pattern bulk_worker uses on line 661 and the
  ETA writer.
- Both `_serial_lifecycle_walk` (per-file inner loop) and
  `_parallel_lifecycle_walk` (per-file batch loop) now check
  `_should_cancel()` between files, not just between directories /
  batches. A 10k-file folder no longer keeps writing for several
  minutes after the scan_coordinator has signalled cancel.
- Both call sites updated from `_process_file` to
  `_process_file_with_retry`.

**2. `core/vision_adapter.py` — per-image size cap**

- New module-level `_compress_image_for_vision(raw, suffix)` helper.
  Strategy: pass-through if already under 3.5 MB raw (≈4.7 MB base64,
  comfortably under Anthropic's 5 MB cap); otherwise downscale longest
  edge to 1568 px (Anthropic's own vision recommendation) and
  re-encode JPEG q=85, with q=70 fallback if still oversized.
- Wired into `describe_frame` (single-frame), `_batch_anthropic`,
  `_batch_openai`, `_batch_gemini`. Ollama is local-only and unaffected.
- Pillow is already a base dep (used by EPS/raster handlers); local
  import inside the helper avoids loading it on cold start.
- `_compress_image_for_vision` never raises — on PIL failure it
  returns the original bytes so the existing 5 MB error path still
  fires with the real provider message (just for the unfixable cases).

**3. `core/libreoffice_helper.py` — distinguish binary-missing from conversion-failed**

- Track `binary_found` flag across the
  `("libreoffice", "soffice")` loop.
- On loop exit: if `binary_found` is False, raise the existing
  "LibreOffice not found on PATH" message. If True, raise a new
  message that includes the actual stderr and exit code from the
  failing binary, e.g.
  `"LibreOffice failed to convert FOO.doc to docx (exit=77): source file could not be loaded"`.
- New `libreoffice_convert_no_output` log event for the rare
  exit-0-but-no-output-file case (corrupt files that LibreOffice
  silently drops).

**4. `core/vector/index_manager.py` — Qdrant client timeout**

- `AsyncQdrantClient(timeout=…)` now defaults to 60s (was qdrant-client's
  default 5s). Override via `QDRANT_TIMEOUT_S` env var. Vector
  indexing runs in a detached background task in `bulk_worker`, so a
  60s budget per upsert is harmless to throughput.

### Why it matters

Together these clear roughly **2,478 noisy log events / 24h** without
adding any new code paths to maintain. The 1,929 lock errors were the
loudest symptom of "MarkFlow is fragile under sustained load" — none
of them caused user-visible failures, but they made the logs unusable
for spotting real regressions. The vision and LibreOffice fixes
restore conversions that were genuinely failing every day. The Qdrant
timeout fix means vector index completeness should jump significantly
during the next sustained bulk run.

### Validation performed

- `python -m py_compile` clean on all four edited files.

### Not yet validated

- **Live rebuild + 24h burn-in.** The next overnight rebuild
  (v0.22.17 self-healing pipeline) is the natural validation window.
  Re-scan the same log buckets after one full day and confirm:
  lifecycle lock errors trend toward zero, vision batch failures
  trend toward zero, Qdrant timeouts trend toward zero, and the
  surviving LibreOffice errors carry the new specific stderr message
  instead of the old "not found" red herring.
- **Contention instrumentation cleanup.** Once the lifecycle lock
  count is verified at zero, `core/db/contention_logger.py` and the
  `db-contention.log` / `db-queries.log` / `db-active.log` writers
  can be removed (they're explicitly tagged as temporary in CLAUDE.md
  pre-prod checklist).

### Known follow-ups still outstanding

- v0.22.15: broken Convert-page SSE, uncancellable `asyncio.wait_for`
  on Whisper, corrupt-audio tensor reshape.
- Pre-prod: lifecycle timers at testing values, security audit
  (62 findings), UX overhaul.

---

## v0.22.17 — Overnight rebuild self-healing pipeline (2026-04-08)

Full refactor of `Scripts/work/overnight/rebuild.ps1` from a linear
"halt on first failure" script into a phased pipeline with retry,
rollback, and auto-diagnostics. Ships against the design spec at
`docs/superpowers/specs/2026-04-08-overnight-rebuild-self-healing-design.md`
(see §11 of that spec for two live-probe deviations from the draft).

### Why

The v0.22.16 follow-up fixes made the script's output and race handling
honest, but the script still halted on the first transient failure (a
single `git fetch` flake, a pip mirror hiccup during the 2.5 GB torch
wheel pull, a compose race the override couldn't suppress) and left
nothing actionable behind when a genuine new-build regression shipped
from a late commit. The Whisper-on-CPU (v0.22.15) and GPU-detector-
lying (v0.22.16) class of bug would both have been caught in the
morning by the user reading a dead-stack transcript — not by the
script itself. The 3 AM "stack is broken and the morning log has no
follow-up data" failure mode had to stop.

### Design principles (from the spec §2)

- **Transient tolerance (A):** retry the network-sensitive steps
  within a bounded budget. Never retry steps whose failure is
  structural (missing NVIDIA Container Toolkit, etc.).
- **Honest failure, no silent remediation:** never auto-restart
  crashed containers, never `docker system prune` on disk pressure,
  never `git reset --hard` on conflicts. These hide real bugs.
  (Auto-remediation was option B in the brainstorm — explicitly
  rejected and stays rejected.)
- **Blue/green rollback (C):** if a new build fails verification,
  retag the previous image as `:latest` and recreate. One rollback
  target only (`:last-good`), no time-travel. Refuse rollback if
  `docker-compose.yml` / `Dockerfile` / `Dockerfile.base` changed
  since the last-good commit, because a compose-old-image mismatch
  would silently half-work.
- **Morning-ready diagnostics (D):** on any non-success exit, the
  transcript contains 13 items (compose ps, logs from four services,
  two health curls, host GPU + disk, git state, sidecar, app log
  tail) — everything needed to diagnose without running a follow-up
  command.
- **Portable by default:** the GPU verification gate auto-detects
  expectation from the host, so friend-deploys on CPU-only Windows
  boxes use the script unchanged.

### Phased pipeline

```
Phase 0    Preflight       - prerequisites, record HEAD commit,
                             auto-detect expectGpu via nvidia-smi.exe
Phase 1    Source sync     - git fetch/checkout/pull     [retry 3x]
Phase 1.5  Anchor last-good - capture :latest IDs, tag as :last-good,
                              write sidecar (BEFORE build - BuildKit
                              GCs the old image as soon as :latest
                              is reassigned)
Phase 2    Image build     - docker build base + app     [retry 2x]
Phase 3    Start           - docker-compose up -d          [20s wait + race override]
Phase 4    Verify          - containers + /api/health + GPU + MCP
Phase 5    Success         - compact FINAL STATE block
```

Phases 0-2 never touch the running stack — `docker build` writes to
the image store out-of-band. On failure there, exit 1 and yesterday's
build keeps serving. Phases 3-4 have already run `up -d`, so a failure
there triggers `Invoke-Rollback`. The `$script:PreCommit` flag makes
this distinction unambiguous in the catch handler.

### Exit codes (new contract)

| Code | Meaning | Morning stack state |
|---|---|---|
| 0 | Clean success, new build verified | New build running, healthy |
| 1 | Pre-commit failure (phases 0-2) | Old build still running, untouched |
| 2 | Rollback succeeded — old build running; new build needs investigation | Old build running, healthy |
| 3 | Rollback failed — stack DOWN | Stack DOWN |
| 4 | Rollback refused — compose/Dockerfile diverged since last-good commit | New build stopped, stack DOWN |

### Key implementation details

**`Invoke-Retryable`** — wraps `Invoke-Logged` with linear-backoff
retry (5s → 10s → 20s). On success after >1 attempt, emits
`RETRY-OK: <label> succeeded on attempt N` so the morning review can
grep `RETRY-OK` to see what flaked overnight. Applied to `git fetch`,
`git pull`, `docker build` (base), and `docker-compose build`. Not
applied to `git checkout` (local, no network), the GPU toolkit smoke
test (missing toolkit is structural, not transient), or
`docker-compose up -d` (already has the race override via
`Test-StackHealthy`).

**`Invoke-RetagImage`** — Phase 1.5 helper. Tags a captured image ID
as `<image>:last-good` with one retry on failure. Atomicity is
enforced across the pair: if the markflow retag succeeds but the
mcp retag fails after its retry, Phase 1.5 aborts as exit 1 rather
than proceeding into Phase 2/3 with an out-of-sync image pair (no
safety net → don't do the risky thing).

**`Invoke-Rollback`** — five steps from spec §5.4: compose/Dockerfile
divergence check against `last-good.commit`, sidecar validation that
both image IDs still resolve via `docker image inspect` (catches a
stray `docker image prune`), retag of both `:last-good` → `:latest`,
`docker-compose up -d --force-recreate markflow markflow-mcp` (the
`--force-recreate` is load-bearing — compose won't see a tag change
as a reason to recreate by default), 20s lifespan pause, then full
re-verification via `Test-StackHealthy` + `Test-GpuExpectation` +
`Test-McpHealth` against the rolled-back stack.

**`Test-GpuExpectation`** — new Phase 4 check that closes the gap
which let v0.22.15 and v0.22.16 ship. Parses `/api/health` for
`components.gpu.execution_path` and `components.whisper.cuda`. When
`$expectGpu="container"`, asserts execution_path ∉ {container_cpu,
none} AND whisper.cuda=true. When `$expectGpu="none"`, skips the
check (CPU-only friend-deploy path). Field names were corrected
against the live `/api/health` payload during implementation —
CLAUDE.md v0.22.16 had referenced `cuda_available`, which is a
structlog event field and an internal attribute but not the HTTP
response key (see spec §11).

**`Test-McpHealth`** — new Phase 4 check, curls
`http://localhost:8001/health` (the Starlette route manually
registered in the MCP server — FastMCP.run does not accept
host/port). Catches the case where `docker-compose ps` reports
markflow-mcp as running but the MCP process inside has crashed or
failed to bind.

**`Write-Diagnostics`** — 13-item dump emitted on every non-success
exit (plus a compact `FINAL STATE` block on exit 0). Budget ~20s
total. Every command wrapped in `Invoke-Logged -AllowNonZero` so a
failing diagnostic command can't abort the capture. Dumps:
`docker-compose ps`, 100-line tail of markflow + markflow-mcp logs,
20-line tail of meilisearch + qdrant logs, verbose curl of both
`/api/health` endpoints, `nvidia-smi.exe`, `wsl df -h /`,
`git log -5 --oneline` + `git status --short`, the `last-good.json`
sidecar, and the last 100 lines of `logs/app.log`.

**Phase 0 GPU auto-detection — diverges from spec §6.3 intentionally.**
The spec called for `wsl.exe -e nvidia-smi` as the host probe, but
that fails on the reference workstation (WSL2 default distro has no
nvidia-smi — Docker Desktop's GPU passthrough uses the NVIDIA
Container Toolkit independently). `nvidia-smi.exe` from the Windows
driver install (in System32, on PATH) is the authoritative probe
and correctly resolves `expectGpu=container` on the reference host.

### Sidecar file

`Scripts/work/overnight/last-good.json` — per-machine, gitignored via
a new rule in `.gitignore`. Written by Phase 2.5 on a successful
retag. Schema:

```json
{
  "commit": "<HEAD SHA before tonight's pull>",
  "tagged_at": "2026-04-08T03:14:27-07:00",
  "markflow_image_id": "sha256:...",
  "mcp_image_id": "sha256:...",
  "host_expects_gpu": true
}
```

The `commit` field is the pre-pull HEAD recorded in Phase 0 — i.e.
the commit that PRODUCED the image currently being tagged as
`:last-good`, not tonight's new HEAD. This is what the rollback
compose-divergence check compares against.

### New parameters

`-DryRun` — runs Phase 0 preflight + GPU detection for real, but
logs-and-skips every git/docker command. Validates script-level
control flow without side effects. Always exits 0. Used during
implementation to verify all seven phase transitions before any
live runs.

### Validation performed

- PowerShell parser clean (`[Parser]::ParseFile`).
- Dry-run end-to-end: all phases 0 → 5 transition cleanly,
  `expectGpu=container` correctly resolved via nvidia-smi.exe.
- `Get-ImageId` against live `doc-conversion-2026-markflow:latest`
  and `doc-conversion-2026-markflow-mcp:latest` — returns the
  expected sha256 IDs.
- `Test-GpuExpectation` against the currently running stack — passes
  with `execution_path='container', whisper.cuda=true`.
- `Test-McpHealth` against `http://localhost:8001/health` — passes.
- `Test-StackHealthy` regexes confirmed to match the real
  `/api/health` response shape (components are nested under
  `components.*` but the regexes happen to work because they scan
  the full body and no nested `{}` appears between each component's
  opening brace and its `ok` field).

### Bugs caught and fixed during staged live-run validation

The first staged live run (`-SkipPull -SkipBase -SkipGpuCheck`,
invoked as the "refresh container" step of this release cycle)
surfaced four real bugs in the initial implementation. All fixed
before committing.

**Bug A — Phase 2.5 retag-after-build was structurally impossible.**
The draft spec assumed "build N is still resident on the host but
reachable only by sha ID" after `docker-compose build` replaces
`:latest`. That assumption is wrong on modern BuildKit: the old
image is garbage-collected the moment its `:latest` tag is dropped.
Phase 2.5's `docker tag <prev-sha> :last-good` failed with `Error
response from daemon: No such image: sha256:...`. **Fix:** moved the
retag + sidecar write into Phase 1.5 (renamed "Anchor last-good"),
BEFORE Phase 2 build. Tagging the current `:latest` as `:last-good`
pre-build gives the image store a second reference that keeps the
old image resident across the build. Phase 2.5 deleted.

**Bug B — `Test-StackHealthy` leaked `NativeCommandError` decoration
on every `docker-compose ps` call.** Same class as the v0.22.16
follow-up (commit 54d6808). The helper used `$ErrorActionPreference
= "Continue"` locally and relied on `2>$null` to suppress
docker-compose's symlink-warning stderr. With EAP=Continue, PS 5.1
auto-displays native stderr as `NativeCommandError` ErrorRecords
BEFORE the `2>$null` redirection takes effect, so the transcript
filled with `docker-compose.exe : time="..." level=warning ...  /
At ...rebuild.ps1:300 char:20 / FullyQualifiedErrorId :
NativeCommandError` spam on every probe attempt. **Fix:**
`$ErrorActionPreference = "SilentlyContinue"` inside
`Test-StackHealthy` (same pattern as Invoke-Logged). Documented in
the function's comment block so future edits can't re-regress this.

**Bug C — Invoke-RetagImage swallowed stderr with `Out-Null`,
hiding the actual docker error from the morning log.** Made it
impossible to diagnose Bug A without manually re-running the tag
command. **Fix:** capture stderr into a variable and `Write-Host`
each line (with ErrorRecord -> Exception.Message projection) on
retag failure.

**Bug D — Phase 3's race-override path called `Test-StackHealthy`
immediately after `up -d` non-zero exit, without any lifespan
wait.** The 3x5s=15s retry budget is not enough for a cold
container start that takes ~20s for FastAPI lifespan startup. On
the second staged run, a perfectly healthy new build got rolled
back unnecessarily because the health probe hit the container
before uvicorn finished binding. This was actually a FALSE
ROLLBACK - the build was functionally identical to the one being
rolled back to. The self-healing pipeline did the right thing
gracefully on a false positive, but the gate was over-eager.
**Fix:** moved the 20-second lifespan pause from Phase 4 to the
END of Phase 3 (after `up -d`, BEFORE any health probe, on both
the clean-exit and race-override branches). Also added the same
lifespan pause before `Test-StackHealthy` in `Invoke-Rollback`'s
recreate step, which had the symmetric race. Phase 4 no longer
sleeps - Phase 3 already did.

### Final validation — third live run

After fixes A-D, re-ran `-SkipPull -SkipBase -SkipGpuCheck`:
- Phase 1.5 captured both image IDs AND successfully tagged them
  as `:last-good` AND wrote `last-good.json` BEFORE the build.
- Phase 2 rebuilt the app layer in ~57s.
- Phase 3 `up -d` exited 1 (compose post-start race, as expected
  from v0.22.16), waited 20s, `Test-StackHealthy` passed on the
  first attempt, race override engaged.
- Phase 4: `Test-StackHealthy`, `Test-GpuExpectation` (reporting
  `execution_path='container', whisper.cuda=true`), and
  `Test-McpHealth` all passed.
- Phase 5: FINAL STATE block clean, exit 0, total runtime 1:36.
- **No NativeCommandError decoration anywhere in the transcript.**
- Stack now running image from commit d46944c with
  `core/version.py = 0.22.17`.

### Still deferred — requires deliberate break, not a normal run

- Forced rollback rehearsal (break a runtime import to fail
  Phase 4; observe rollback path + exit 2). The self-healing
  pipeline already executed a successful rollback during Bug D
  surfacing, but that was a false-positive scenario - a true
  runtime-broken-build rehearsal has not been performed.
- Compose-divergence rehearsal (edit docker-compose.yml after a
  successful run, force Phase 4 failure, expect exit 4).

Recommended before the next unattended cycle.

### Modified files

- `Scripts/work/overnight/rebuild.ps1` — full refactor (~730 lines).
- `.gitignore` — added `Scripts/work/overnight/last-good.json`.
- `docs/gotchas.md` — two new entries in a new "Overnight Rebuild &
  PowerShell Native-Command Handling" section: (1) Start-Transcript
  does not capture native output → the Invoke-Logged +
  SilentlyContinue + variable-capture pattern; (2) docker-compose ps
  --format json cannot be regex'd across fields because Publishers
  has nested `{}`, use per-line ConvertFrom-Json.
- `docs/superpowers/specs/2026-04-08-overnight-rebuild-self-healing-design.md` —
  status flipped to Implemented, §10 open questions resolved, new
  §11 "Implementation notes & spec deviations" documents the GPU
  probe change and the `cuda_available` → `cuda` field correction.

### Known v0.22.15 follow-ups still outstanding

(Unchanged from v0.22.16.) Broken Convert-page SSE; uncancellable
`asyncio.wait_for` on Whisper; corrupt-audio tensor reshape.

---

## v0.22.16 — GPU detector WSL2 honesty + overnight rebuild resilience (2026-04-08)

Two follow-ups to the v0.22.15 GPU work, both surfaced the same night by
the overnight rebuild script and the Resources-page widget reporting
`CPU (no GPU detected)` on a host where Whisper was clearly running on
CUDA.

### Issue #1 — GPU detector lied on WSL2 Docker Desktop

**Symptom:** After v0.22.15, `docker-compose logs markflow | grep whisper`
showed `cuda_available=true, gpu_name="NVIDIA GeForce GTX 1660 Ti"`, yet
`/api/health` and the Resources widget reported
`gpu.execution_path="container_cpu"` and
`gpu.effective_gpu="CPU (no GPU detected)"`. Same GPU, two sources of
truth disagreeing.

**Root cause:** `core/gpu_detector.py` resolved `execution_path` by
requiring BOTH `container_gpu_available` AND
`container_hashcat_backend in ("CUDA","OpenCL")`. On WSL2 Docker Desktop,
`nvidia-smi` succeeds inside the container (the NVIDIA Container Toolkit
injects `libcuda.so`), but `hashcat -I` reports CPU (pocl) only because
the toolkit's WSL2 path does not inject `libnvidia-opencl.so.1` — the
`opencl` driver capability is rejected. CUDA workloads (torch, Whisper)
are unaffected; hashcat falls back to CPU. The old resolver treated
"hashcat can't see the GPU" as "there is no GPU," which was never the
intent.

**Fix:** New second tier in the `detect_gpu()` / `get_gpu_info_live()`
priority ladder: if `container_gpu_available` is true but the hashcat
backend is not CUDA/OpenCL, still resolve `execution_path="container"`,
use the real `container_gpu_name`, and set `effective_backend="CUDA"`.
Consumers that specifically need hashcat GPU acceleration can inspect
`container_hashcat_backend` directly — they weren't getting GPU hashcat
in either the old or new behavior, the lie was just one level removed.
The resolver is now a documented 5-tier ladder (see the priority comment
in `detect_gpu()`): container GPU+hashcat → container GPU+CUDA-only →
host worker GPU → container CPU → none. `get_gpu_info_live()` carries
the same ladder verbatim so the live re-resolve after the host worker
file appears doesn't diverge.

**Logging:** Added `container_hashcat_backend` to the `gpu.resolution`
log line so future diagnostics don't have to cross-reference two events.

**Test:** New `test_detect_nvidia_container_hashcat_cpu_only` in
`tests/test_gpu_detector.py` asserts the WSL2 case: nvidia-smi returns a
1660 Ti, hashcat `-I` returns CPU (pocl), and the detector resolves
`execution_path="container"` with the real GPU name and
`effective_backend="CUDA"`. All 14 tests in the module pass.

**Modified files:**
- `core/gpu_detector.py` — new priority tier in `detect_gpu()` and
  `get_vector_info_live()` [sic: `get_gpu_info_live()`], documented
  5-tier comment, `container_hashcat_backend` in resolution log.
- `tests/test_gpu_detector.py` — WSL2 CPU-only hashcat regression test.

### Issue #2 — Overnight rebuild script had empty transcript logs and false failures

**Symptom #1:** `Scripts/work/overnight/rebuild.ps1` runs unattended at
~3 AM and writes a transcript log. Morning review on 2026-04-08 found
section headers (`>>> git fetch origin`, `>>> docker build...`) with
empty bodies — none of the native command output was captured. Useless
for forensics.

**Symptom #2:** On a successful rebuild where the stack came up fine,
`docker-compose up -d` returned exit code 1 because its post-start
cleanup lost a race with the Docker Desktop reconciler
(`No such container: <old id>`) even though the replacement container
was already running. The script threw, the user was paged, but the
stack was actually healthy.

**Root causes:**
1. **PS 5.1 `Start-Transcript` does not capture native stdout/stderr.**
   Native executables (docker, git, curl, nvidia-smi) bypass the PS host
   and write directly to the console device. Transcript only records
   output that goes *through* the host.
2. **`2>&1` in PS 5.1 wraps native stderr as `RemoteException` records.**
   Even when those are piped through `Write-Host`, the default render
   adds the full error-decoration envelope (`CategoryInfo`, etc.) and
   dominates the log.
3. **`$ErrorActionPreference = "Stop"` + native stderr warnings** (e.g.
   docker-compose's "project has been loaded without an explicit name
   from a symlink") cause `2>&1` to terminate the whole pipeline before
   `$LASTEXITCODE` can even be inspected.
4. **Compose exit 1 on a working stack.** No way to distinguish the
   race-override case from a real failure without probing the stack.

**Fix:** New `Invoke-Logged` helper replaces `Assert-ExitCode`. It:
  - Wraps the native invocation in a `scriptblock` passed as `-Command`.
  - Temporarily relaxes `$ErrorActionPreference` to `Continue` so
    harmless stderr warnings don't abort the pipeline.
  - Pipes output through `ForEach-Object { Write-Host }`, stringifying
    `ErrorRecord` objects via `$_.Exception.Message` so the log shows
    plain text instead of PS decoration.
  - Checks `$LASTEXITCODE` authoritatively and throws on non-zero
    unless `-AllowNonZero` is given.

Every step in `rebuild.ps1` (GPU smoke test, git fetch/checkout/pull,
base image build, app build, `docker-compose up`, container status,
health check) now routes through `Invoke-Logged` — the transcript now
captures every line of native output.

New `Test-StackHealthy` function handles the compose race: when
`docker-compose up -d` exits non-zero under `-AllowNonZero`, the script
probes `docker-compose ps --format json` (markflow + markflow-mcp both
running) and `curl /api/health` (top-level status ok, database ok,
meilisearch ok). Policy is deliberately conservative: 3 attempts, 5
seconds apart, all checks must pass, false = genuine failure. Whisper
CUDA is intentionally *not* required so the script stays portable to
friend-deploys on CPU-only hosts. On true healthy-but-compose-returned-1,
the rebuild is marked successful and no one gets woken up.

**Modified files:**
- `Scripts/work/overnight/rebuild.ps1` — `Invoke-Logged` helper,
  `Test-StackHealthy` post-start probe, every native call routed through
  the helper, health-check banner updated to mention v0.22.16
  `gpu.execution_path="container"` expectation.

### Why it matters

The widget lie was a trust issue — users would see "CPU" and assume
v0.22.15 hadn't landed, then either disable Whisper or file a ghost bug.
The rebuild script issues meant overnight automation couldn't be trusted
to self-report: every morning needed a manual status check, and the one
time the stack *did* come up through a compose race, it looked like a
failure. Both fixes restore honesty in the reporting layer without
touching any workload code.

### Known follow-ups (not in this release)

- The v0.22.15 SSE / `asyncio.wait_for` / corrupt-audio items are still
  outstanding.
- `Test-StackHealthy`'s regex JSON matching is fine for today's health
  payload but will need a proper parser if the shape grows nested.

---

## v0.22.15 — GPU Whisper + Audio Fallback Graceful Fail (2026-04-07)

Two related problems surfaced by diagnosing a stuck manual-convert batch
of four MP3 files on the Convert page. Batch `20260408_021247_8847` stalled
after 17 hours with one file failing on a Whisper tensor-reshape error,
one failing on an empty cloud-provider list, and two others stuck mid-load.

### Issue #1 — Whisper was running on CPU despite having a GTX 1660 Ti

**Symptom:** `whisper_device_auto` events logged `"device": "cpu",
"cuda_available": false` on every batch. A 75-minute MP3 (`240306_1116.mp3`)
sat for hours with no progress after the model-load event. The machine
has a GTX 1660 Ti (Turing / CC 7.5) that should have been doing the work
in ~10-15 minutes instead of ~17 hours.

**Root cause:** Two bugs stacked, either of which would have been enough
on its own:

1. **`Dockerfile.base:63`** installed the CPU-only PyTorch wheel via
   `pip install torch --index-url https://download.pytorch.org/whl/cpu`.
   That wheel ships no CUDA libraries at all, so `torch.cuda.is_available()`
   returned `False` inside the container regardless of what Docker passed
   through. The CPU-only wheel was chosen to keep the base image small
   (~200 MB vs ~2.5 GB) during early development, and that choice became
   a silent production cap.
2. **`docker-compose.yml`** had no GPU reservation on the `markflow`
   service — no `deploy.resources.reservations.devices` block, no
   `runtime: nvidia`, no `NVIDIA_VISIBLE_DEVICES` env var. Even if torch
   had been CUDA-enabled, the container had zero visibility into host
   GPU devices.

**Fix:** Switched the base image to the CUDA 12.1 wheel
(`whl/cu121`) and added a `deploy.resources.reservations.devices` block
to the `markflow` service requesting `driver: nvidia, count: 1`. On
hosts without an NVIDIA GPU, `torch.cuda.is_available()` returns `False`
and Whisper transparently falls back to CPU — so the same image works
on GPU and CPU-only machines. Friends deploying on GPU-less hosts can
comment out the compose block and the app still runs. Host prereq:
NVIDIA Container Toolkit installed inside the WSL2 distro (Windows) or
the `nvidia-container-toolkit` package (Linux).

**Why CUDA 12.1 specifically:** GTX 1660 Ti is Turing (CC 7.5) and
supports every current CUDA release; cu121 is the mainstream default
with broad driver compatibility (≥ 525), smaller than cu124 (~2.5 GB vs
~2.7 GB), and large enough to cover any modern RTX card a friend-deploy
might have.

**Modified files:**
- `Dockerfile.base:61-70` — comment block + `whl/cu121` index URL
- `docker-compose.yml:64-75` — `deploy.resources.reservations.devices`
  block with inline commenting explaining how to disable for CPU-only hosts

### Issue #2 — Cloud fallback failed cryptically when no audio provider exists

**Symptom:** When Whisper crashed on `240306_1004.mp3` (corrupt audio →
tensor reshape error), the cloud fallback logged:

```
All cloud providers failed. Last error: None.
Audio-capable providers checked: []
```

This is a two-part problem: (a) the empty list shows no eligible provider
was ever found, so the loop didn't iterate and `last_error` stayed `None`;
(b) the final user-facing error was the generic "all transcription methods
failed", which gave the user no indication of what to actually fix.

**Root cause:** The user has only Anthropic / Claude configured as an AI
provider. Claude does not support audio input (it handles text, images,
and PDFs, but not audio). `AUDIO_CAPABLE_PROVIDERS` in `cloud_transcriber.py`
correctly maps `anthropic: False`, so the loop skipped every candidate and
fell through to the terminal `RuntimeError` with a meaningless message.
There was no pre-flight check, no distinct exception type, and no
user-actionable guidance — just a stack trace mentioning "Last error: None".

**Fix:** Three-layer graceful-fail:

1. **New exception type** — `NoAudioProviderError` in `core/cloud_transcriber.py`,
   subclass of `RuntimeError`, raised when the eligible-provider list is
   empty. Distinct from generic provider failures (rate limits, API errors)
   so the caller can distinguish "config issue, user action needed" from
   "transient failure, maybe retry".
2. **Pre-flight in `CloudTranscriber.transcribe()`** — compute the eligible
   list (audio-capable provider type AND api_key present) up front. If
   empty, raise `NoAudioProviderError` with the full context: which providers
   the user has configured, which provider types support audio, and
   exactly what to do (add an OpenAI or Gemini key). Logs a `warning`-level
   event `cloud_transcribe_no_audio_provider` with both lists for post-mortem.
3. **Dedicated catch in `transcription_engine.py`** — separate `except
   NoAudioProviderError` clause that logs the condition at `info` level
   (this is a config state, not a bug) and raises a user-facing `RuntimeError`
   with actionable text: "Cannot transcribe <file>: local Whisper failed or
   is unavailable, and no cloud provider that supports audio is configured.
   Add an OpenAI or Gemini API key in Settings → AI Providers, or
   troubleshoot Whisper/GPU setup. (Anthropic/Claude does not currently
   support audio.)"

The existing terminal `RuntimeError` message was also tightened — it now
only fires when eligible providers exist but all actually failed, so the
"Last error" field is always populated with a real cause.

**Why distinguish the two failure modes:** They lead to different user
actions. "No provider configured" is a Settings-screen fix. "All providers
failed with real errors" is a "check API key expiry / billing / outage"
fix. Lumping them into one message left the user guessing.

**Modified files:**
- `core/cloud_transcriber.py:29-48` — added `NoAudioProviderError` class,
  enriched the `AUDIO_CAPABLE_PROVIDERS` comment with the Anthropic caveat
- `core/cloud_transcriber.py:67-105` — pre-flight eligibility check, logs
  `cloud_transcribe_no_audio_provider` warning, raises typed exception
- `core/cloud_transcriber.py:117-124` — tightened terminal error message
- `core/transcription_engine.py:104-148` — `NoAudioProviderError` catch
  + branched user-facing error message
- `docs/gotchas.md` — Media & Transcription section updated with GPU
  passthrough, Anthropic no-audio graceful fail, and Dockerfile.base
  CUDA wheel entries
- `docs/help/troubleshooting.md` — new "Audio or Video Transcription
  Fails" section with Whisper model sizing table and ffmpeg re-encode
  recipe for corrupt audio
- `core/version.py` — 0.22.14 → 0.22.15

### Side-findings (flagged for a future release, not fixed here)

These surfaced during the log diagnostic but are out of scope for this
release:

- **`/api/batch/.../stream` returned 404** on the Convert page SSE
  progress channel at batch start. The UI has no live progress for
  manual-convert batches.
- **`asyncio.wait_for` does not cancel threadpool work.**
  `transcription_engine.py:73-81` wraps `WhisperTranscriber.transcribe`
  in `asyncio.wait_for(timeout=3600)`, but the actual transcription runs
  inside `asyncio.to_thread`. CPython cannot cancel a running thread, so
  the timeout fires at 3600 s but the thread keeps running — which
  explains why the 75-min file's timeout event never logged.
- **Whisper should catch and re-raise corrupt-audio errors with a
  cleaner message.** The `cannot reshape tensor of 0 elements into
  shape [1, 0, 16, -1]` error on `240306_1004.mp3` should surface as
  "audio file contains no decodable frames" so the user can re-encode.
- **`convert_batch_completed` event never fires** in `api/routes/convert.py`
  — only the per-file `file_conversion_complete` or `_error` events. Makes
  "is the batch done?" hard to answer from logs alone.

---

## v0.22.14 — Log Diagnostic Fixes (2026-04-07)

A diagnostic log scan after v0.22.13 surfaced four issues. All four
addressed in this release.

### Issue #1 — Vector indexing was blocking conversion (BIGGEST IMPACT)

**Symptom:** `bulk_vector_index_fail` warnings every 2-3 files with an
empty error string. Conversion rate dropped to **0.048 files/sec → ETA
6.6 days for the in-flight 28k-file job**.

**Root cause:** `core/bulk_worker.py:819` did
`await vec_indexer.index_document(...)` synchronously inside the worker
loop. When Qdrant timed out (60s default httpx timeout) the worker
blocked for the full timeout per file. Math: 5s convert + 60s qdrant
timeout = 65s/file = ~0.015 files/sec; observed 0.048 ≈ ~1 in 3 files
hitting the timeout.

The empty error string was a separate logging defect: `ReadTimeout(TimeoutError())`
stringifies to empty when the inner `TimeoutError()` has no message.
`str(exc)` produced `""`, masking the failure entirely.

**Fix:** New module-level helper `_index_vector_async()` in
`core/bulk_worker.py`. The worker now does:

```python
asyncio.create_task(_index_vector_async(...))
```

instead of `await vec_indexer.index_document(...)`. The vector indexing
runs as a detached background task; the worker immediately moves to the
next file. Errors logged with `repr(exc)` and `exc_type=type(exc).__name__`
so empty stringify no longer hides the failure.

**Expected impact:** 5-10x throughput restoration when Qdrant is slow.
Worker rate should return to its natural conversion speed; vector
indexing catches up async.

### Issue #2 — `database is locked` was permanently failing files

**Symptom:** 13 lock-contention events / 30 min, 4 of which were
non-recoverable:

- `bulk_worker_unhandled error='database is locked'` — file marked
  `failed` (real bug, lost work)
- `analysis_worker.drain_failed`
- `auto_metrics_aggregation_failed`
- `adobe_index_error` + `adobe_l2_index_failed`

**Root cause:** Multiple writers (4 bulk workers + Adobe L2 indexer +
analysis worker drain + auto_metrics aggregator + cleanup jobs +
contention logger) all competing for the SQLite WAL. The in-flight
retry helper `db_write_with_retry()` saved most cases, but several code
paths bypassed it.

**Fix:**

1. **`core/bulk_worker.py` `_worker()` top-level except**: now
   distinguishes `"database is locked"` from real failures. On lock
   error, logs a `bulk_worker_db_lock_requeue` warning and `continue`s
   (leaves the file `pending`); does NOT update status, NOT increment
   the failed counter, NOT emit `file_failed`. The next worker pass
   over the pending list retries the file naturally.

2. **`core/adobe_indexer.py`**: `upsert_adobe_index()` is now wrapped in
   `db_write_with_retry()`. Lock errors are retried with backoff
   instead of bubbling out as a permanent `adobe_index_error`.

3. **`core/analysis_worker.py`** and **`core/auto_metrics_aggregator.py`**:
   the top-level `except` blocks now check for `"database is locked"` in
   the error string and downgrade to a warning. The next scheduled drain /
   aggregation tick retries naturally — these are already periodic jobs,
   so missing one tick during heavy contention is harmless.

### Issue #3 — Vision API 400 errors had no diagnostic detail

**Symptom:** `vision_adapter.describe_batch_failed count=10 error="Client
error '400 Bad Request' for url '.../v1/messages'"`. The
`analysis_queue` had **1,150 failed vs 90 completed** — vision pipeline
mostly broken with no way to identify the offending image.

**Fix:** `core/vision_adapter.py:describe_batch()` `except` block now
captures the HTTP response body via `getattr(exc, "response", None)` and
logs:

```python
log.error(
    "vision_adapter.describe_batch_failed",
    provider=...,
    count=...,
    error=str(exc),
    exc_type=type(exc).__name__,
    response_body=response.text[:500],
    first_image=str(image_paths[0]),
)
```

The actual Anthropic error message (e.g. "Image exceeds 5MB", "Invalid
base64") and the first image path now appear in logs. Also propagated
into the per-row `BatchImageResult.error` field so the `analysis_queue`
table itself shows the real reason. Next log scan will be able to
bisect the offending images.

### Issue #4 — Ghostscript missing for `.eps` conversion

**Symptom:** `image_handler.convert_failed Unable to locate Ghostscript
on paths`. EPS files in source share were uniformly failing.

**Fix:** Added `ghostscript` to `Dockerfile.base`'s apt install list for
the long term. Also added a separate `apt-get install -y ghostscript`
layer in the app `Dockerfile` so this version can ship without a 25-min
base image rebuild. The next time `Dockerfile.base` is rebuilt, the
duplicate becomes a no-op (apt-get reports already-installed) and the
app-Dockerfile line can be removed.

### Modified files

- `core/version.py` — 0.22.13 → 0.22.14
- `core/bulk_worker.py` — `_index_vector_async()` helper, async vector
  task, db-lock requeue branch in worker handler
- `core/analysis_worker.py` — db-locked downgrade
- `core/auto_metrics_aggregator.py` — db-locked downgrade
- `core/adobe_indexer.py` — `upsert_adobe_index` via `db_write_with_retry`
- `core/vision_adapter.py` — capture response body + first_image path
- `Dockerfile.base` — add `ghostscript`
- `Dockerfile` — temporary `apt-get install ghostscript` layer
- `CLAUDE.md`, `docs/version-history.md` — updates

### Verification plan

1. Rebuild + restart container.
2. Trigger lifecycle scan.
3. Wait 5 minutes for the bulk worker to process some files.
4. Re-run the log scan from this session and confirm:
   - `bulk_progress` rate has jumped (target: at least 5x previous)
   - No `bulk_worker_unhandled error='database is locked'` events
   - Adobe L2 errors gone (or reduced to retried warnings)
   - Vision 400 logs now include response body
   - `image_handler.convert_failed` for EPS gone

---

## v0.22.13 — Active Connections Widget (2026-04-07)

**Asked in chat:** "Under the resources page — are you able to show how
many connections are active on the website?"

The Resources page previously tracked CPU/RAM/disk metrics, activity log,
OCR quality, and scan throttle history but had no concept of "who/what is
currently using MarkFlow". This release adds a small in-memory tracker
plus a polled widget to show:

1. **Recently active users** — sliding window (default 5 minutes) of who
   has made an authenticated request, sorted most-recent-first.
2. **Live SSE / streaming connections** — exact count of long-lived
   StreamingResponse generators currently open, bucketed by endpoint
   label so admins can see which features are in active use.

### Why no DB schema

Both counters are in-process dicts. Resets on container restart are
**intentional** — these are "right now" diagnostics, not historical
metrics. The widget shows 0 immediately after a rebuild and refills
within seconds as clients reconnect. Avoiding the DB also avoids write
contention with the bulk worker / scanner during heavy load.

### Code changes

- **`core/active_connections.py`** (new, ~150 lines):
  - `_user_last_seen: dict[str, tuple[str, str]]` — sub → (iso_ts, email)
  - `_active_streams: dict[str, int]` — endpoint label → count
  - `record_request_activity(user_sub, user_email)` — middleware hook
  - `get_active_users(window_seconds)` — sliding window query that
    drops stale entries on every call (so the dict can't grow unbounded
    over a long-running process)
  - `track_stream(endpoint)` — async context manager that increments
    on enter and decrements in `finally`. Exception-safe so client
    disconnects (`CancelledError` / `BrokenPipeError`) still drop the
    counter back.
  - `get_active_streams()` / `get_total_active_streams()`

- **`core/auth.py`** — `get_current_user()` stashes the resolved
  `AuthenticatedUser` on `request.state.user` (in all 3 auth paths:
  DEV_BYPASS_AUTH, X-API-Key, JWT Bearer). This is the integration point
  the middleware needs.

- **`api/middleware.py`** — `RequestContextMiddleware.dispatch()` reads
  `getattr(request.state, "user", None)` after `call_next()` returns and
  fires `record_request_activity(user.sub, user.email)`. Skips silently
  for unauthenticated routes (e.g. `/api/health`, static assets).

- **SSE generators wrapped** with `async with track_stream(...)`:
  - `api/routes/bulk.py` — `bulk_job_events`, `ocr_gap_fill`
  - `api/routes/batch.py` — `batch_progress` (refactored: outer
    `event_generator()` wraps the body in `track_stream`, original body
    moved to inner `_batch_event_generator()`)
  - `core/ai_assist.py` — `ai_assist_search`, `ai_assist_expand`
    (same refactor pattern: outer wrapper + inner `_impl()` body)

- **`api/routes/resources.py`** — new admin-only endpoint:
  ```
  GET /api/resources/active?window_seconds=300
  ```
  Returns:
  ```json
  {
    "window_seconds": 300,
    "users": [{"sub": "...", "email": "...", "last_seen": "..."}, ...],
    "total_users": 5,
    "total_streams": 3,
    "streams_by_endpoint": {"bulk_job_events": 2, "ai_assist_search": 1}
  }
  ```

- **`static/resources.html`** — new "Active Connections" section between
  the Live System Metrics and Activity Log sections. Two cards
  side-by-side:
  - **Active Users** — count badge + scrollable list
    (`email` left-aligned, "Xs ago" right-aligned). 200px max height.
  - **Live Streams** — count badge + scrollable list (endpoint label
    monospaced, count badge right-aligned). Sorted by count desc.
  Both rendered with safe DOM construction (no innerHTML / template
  injection). Polled every 5 seconds via `pollActiveConnections()`.
  Polling pauses when the tab is hidden (visibility change handler).

### Limitations / known non-features

- **Anonymous traffic is invisible.** The auth model has no concept of an
  unauthenticated visitor identity, so there's nothing to count. Anyone
  hitting the app is either authenticated (counted under users) or holds
  an SSE stream (counted under streams).
- **Two browser tabs in one browser look like one user** because they
  share the same JWT `sub`.
- **DEV_BYPASS_AUTH=true makes everything look like the user "dev"** —
  expected, since that's the only identity the auth dependency hands out
  in dev mode.
- The endpoint requires admin role. Non-admins polling it get a silent
  failure in the widget (the "--" badges stay).

### Modified files

- `core/version.py` — 0.22.12 → 0.22.13
- `core/active_connections.py` — new
- `core/auth.py` — stash user on request.state
- `api/middleware.py` — record activity hook
- `core/ai_assist.py` — wrap both stream functions
- `api/routes/bulk.py` — wrap two SSE generators
- `api/routes/batch.py` — wrap batch progress generator
- `api/routes/resources.py` — `/api/resources/active` endpoint
- `static/resources.html` — new section + JS poller
- `CLAUDE.md`, `docs/version-history.md` — updates

---

## v0.22.12 — AI Assist Settings Copy Fix + Provider Badge (2026-04-07)

**Problem:** The Settings page "AI-Assisted Search" section still carried
v0.21.0-era copy under the "Enable AI Assist" toggle:

> Allows users to synthesize search results via Claude.
> Requires `ANTHROPIC_API_KEY` in the environment.

This was wrong as of v0.22.10 (AI Assist reads from `llm_providers`) and
doubly wrong as of v0.22.11 (per-provider opt-in flag). Admins reading the
text would still think they needed to set an env var.

The user also wanted the section to clearly tell them that AI Assist uses
the same provider system as **Vision & Frame Description** and **AI
Enhancement** above it on the same page.

**Fix:** `static/settings.html`:

- Replaced the stale "Requires `ANTHROPIC_API_KEY`" line with:
  > Allows users to synthesize search results via Claude. Uses the
  > provider shown above — no environment variable required.
- Added a top-of-section blurb above the toggle:
  > AI Assist uses the same LLM provider system as **Vision & Frame
  > Description** and **AI Enhancement** above. By default it uses the
  > provider marked _Active_ on the Providers page; you can override
  > this by clicking _Use for AI Assist_ on a specific provider. AI
  > Assist requires an Anthropic provider.
- Added a new live provider-info badge (`#ai-assist-provider-info`)
  rendered from the `/api/ai-assist/status` response. It shows
  `Provider: anthropic · claude-opus-4-6 · opted-in via "Use for AI
  Assist"` (or `falling back to the Active provider`, or `using the
  legacy ANTHROPIC_API_KEY env var (deprecated)`, or `no provider
  configured`) plus a "Manage Providers →" link. Built with safe DOM
  construction (no innerHTML).

**Why this matters:** UX clarity. The previous text was a recipe for
support tickets ("I set ANTHROPIC_API_KEY in .env but the toggle still
won't enable"). Now the section explicitly tells admins which provider
record AI Assist will use, where it came from, and how to switch it.

### Modified files

- `core/version.py` — 0.22.11 → 0.22.12
- `static/settings.html` — section copy + provider info badge + JS render
- `CLAUDE.md`, `docs/version-history.md` — updates

---

## v0.22.11 — Per-Provider "Use for AI Assist" Opt-In (2026-04-07)

**Problem (raised in chat):** v0.22.10 wired AI Assist to use the active
`llm_providers` record. But what if the admin wants AI Assist to use a
DIFFERENT provider than the image scanner? For example: image analysis
runs against a cheap Gemini provider for vision OCR, while AI Assist runs
against an Anthropic provider for natural-language synthesis. With v0.22.10
the two features were locked to the same active provider.

**Fix:** Add a per-provider opt-in flag (`use_for_ai_assist`) and a
checkbox/button on the Providers page. The flag is mutually exclusive across
providers (exactly like `is_active`) but **independent** from `is_active`.

### Schema

Migration #25:
```sql
ALTER TABLE llm_providers ADD COLUMN use_for_ai_assist INTEGER NOT NULL DEFAULT 0;
```

The base `CREATE TABLE` definition for `llm_providers` was also updated so
fresh installs get the column without relying on the migration.

### Code changes

- **`core/db/catalog.py`** — two new helpers:
  - `get_ai_assist_provider()` — returns the row with `use_for_ai_assist=1`,
    api_key DECRYPTED, or None.
  - `set_ai_assist_provider(provider_id | None)` — clears the flag on every
    row, then sets it on the named row. Pass `None` to clear entirely.

- **`core/db/__init__.py`** — re-exports the two new helpers via the
  `core.db` package so `from core.database import ...` works.

- **`core/ai_assist.py`** — `_get_provider_config()` is now a 3-step lookup:
  1. **Opted-in provider** — `get_ai_assist_provider()`. Preferred path.
  2. **Active provider** — `get_active_provider()`. Backward-compat fallback
     for users who haven't opted in a specific AI Assist provider yet.
  3. **`ANTHROPIC_API_KEY` env var** — last-resort legacy fallback.
  Returns a new field `provider_source` with one of `"opted_in"`,
  `"active_fallback"`, `"env_fallback"`, or `"none"` so the UI can render
  an accurate state indicator.

- **`api/routes/llm_providers.py`**:
  - `CreateProviderRequest` and `UpdateProviderRequest` gain an optional
    `use_for_ai_assist: bool` field. When True on create, the new provider
    is opted in immediately (and the flag is cleared on all others).
  - `update_provider()` handles the flag separately from other fields
    because the flip-others-to-zero behavior is mutually exclusive and
    cannot be done via a generic UPDATE — calls `set_ai_assist_provider()`
    instead.
  - New endpoint `POST /api/llm-providers/{id}/use-for-ai-assist` that
    accepts a literal `id` to opt in, or `id="none"` to clear.

- **`static/providers.html`**:
  - Add-provider form gains a "Also use this provider for the AI Assist
    search feature" checkbox with an explanatory hint.
  - Save logic warns (but allows) opting in a non-Anthropic provider —
    AI Assist will then surface a clear "incompatible" notice when invoked.
  - Provider cards refactored from template-string injection to safe DOM
    construction (`_renderProviderCards()`). Each card shows:
    - Existing **Active** badge (green) if `is_active`
    - New **AI Assist** badge (purple) if `use_for_ai_assist`
    - Existing Verify / Activate / Delete buttons
    - New **Use for AI Assist** button (or **Disable AI Assist** if it's
      already opted in) wired to `setAIAssistProvider(id)`.

### Independence from `is_active`

The two flags (`is_active` and `use_for_ai_assist`) are completely
orthogonal. Common configurations:

| `is_active` | `use_for_ai_assist` | Effect |
|---|---|---|
| Provider A | Provider A | Same provider for both (the v0.22.10 default) |
| Provider A | Provider B | Image scanner uses A, AI Assist uses B |
| Provider A | (none) | AI Assist falls back to A — v0.22.10 behavior |
| (none)      | Provider B | Image scanner has no provider; AI Assist uses B |

### Modified files

- `core/version.py` — 0.22.10 → 0.22.11
- `core/db/schema.py` — migration #25 + base CREATE TABLE update
- `core/db/catalog.py` — `get_ai_assist_provider()`, `set_ai_assist_provider()`
- `core/db/__init__.py` — re-exports
- `core/ai_assist.py` — 3-step lookup chain, `provider_source` field
- `api/routes/llm_providers.py` — request models, create/update flag, new endpoint
- `static/providers.html` — checkbox, badge, button, safe DOM rendering
- `CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md` — updates

---

## v0.22.10 — AI Assist Uses llm_providers (2026-04-07)

**Problem:** AI Assist read its API key from `os.environ["ANTHROPIC_API_KEY"]`
in `core/ai_assist.py:_get_api_key()`. Meanwhile the image scanner / vision
pipeline read it from the `llm_providers` SQLite table managed via the
Settings → Providers page (encrypted at rest, set per-deployment in the UI).
Two separate configurations for what was effectively the same Anthropic key.
This was confusing — users who set up image analysis assumed AI Assist
"just worked" too, but it silently fell back to the env var (almost always
empty in this deployment).

**Fix:** AI Assist now resolves its key/model/base URL from the same source.

### Code changes

- **`core/ai_assist.py`**
  - New async helper `_get_provider_config()` that:
    1. Calls `core.db.catalog.get_active_provider()` (the same call the
       vision pipeline uses).
    2. If the active provider is `anthropic` and has an `api_key`, returns
       `{api_key, model, api_url, provider, configured: True, compatible: True}`.
       The provider's `model` and `api_base_url` (if set) override the
       defaults — so an admin can point AI Assist at a different Anthropic
       model or a self-hosted Anthropic-compatible proxy from the UI.
    3. If the active provider is set but is NOT `anthropic` (openai, gemini,
       ollama, custom), returns `compatible: False` with a clear error
       message ("Active LLM provider is 'openai'. AI Assist currently
       requires an Anthropic provider..."). AI Assist's SSE format and
       `x-api-key` header are Anthropic-specific.
    4. As a fallback only when there is NO provider record at all, reads
       `ANTHROPIC_API_KEY` from env (legacy compatibility — should be
       considered deprecated). Returned with `provider="env_fallback"`.
  - `stream_search_synthesis()` and `stream_document_expand()` both
    call `await _get_provider_config()` and short-circuit with a clear SSE
    error event if `compatible` is false or `configured` is false.
  - The hard-coded `ANTHROPIC_API_URL` constant became
    `ANTHROPIC_API_URL_DEFAULT`. The actual URL used per request comes
    from `cfg["api_url"]` so a custom `api_base_url` in the provider
    record is honored.
  - Added `provider=cfg["provider"]` to the start/complete log events for
    observability.

- **`api/routes/ai_assist.py`**
  - Imported `_get_provider_config` from `core.ai_assist`.
  - `_api_key_configured()` is now async and delegates to
    `_get_provider_config()` — returns true iff a usable
    (configured + compatible) provider exists.
  - `GET /api/ai-assist/status` response gained four new fields:
    - `provider_source` — "anthropic" / "env_fallback" / "openai" / etc.
    - `provider_compatible` — bool
    - `provider_error` — human-readable reason when not usable
    - `model` — the actual model that will be used
  - `key_configured` is unchanged in shape (still bool) so existing
    frontends keep working.

- **`static/settings.html`**
  - The "Not configured" notice in the AI Assist section was rewritten to
    point users at the **Providers page** (`/providers.html`) instead of
    asking them to edit `.env`.
  - The `_initAIAssistSettings()` JS now reads `status.provider_error`
    and substitutes it into the notice when present, so a user with the
    wrong provider active sees "Active LLM provider is 'openai'..." with a
    direct link to fix it.

- **`static/js/ai-assist.js`**
  - The `_showNotConfiguredNotice('missing_key')` drawer message now uses
    `_serverStatus.provider_error` when present and links to
    `/providers.html`. The old `.env` / `docker-compose restart` snippet
    was removed.

- **`core/version.py`** — 0.22.9 → 0.22.10
- **`CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md`** — updates.

### Why this matters

1. **Single source of truth.** Setting up an Anthropic key in the
   Providers page is now sufficient to enable both image analysis AND AI
   Assist. No more split-brain config.
2. **Per-deployment overrides.** The provider record's `model` and
   `api_base_url` columns flow through to AI Assist, so an admin can point
   it at a non-default model or an Anthropic-compatible proxy without
   touching environment variables.
3. **Encrypted at rest.** Provider API keys are stored encrypted in
   `llm_providers.api_key` (via `core.crypto.encrypt_value`). Env-var
   storage was plaintext.
4. **Clearer error UX.** A user with OpenAI active no longer sees AI
   Assist silently disabled — they see "Active LLM provider is 'openai'.
   AI Assist currently requires an Anthropic provider. Switch the active
   provider on the Settings → Providers page."

### Backward compatibility

- The `ANTHROPIC_API_KEY` env var still works as a fallback when there is
  no `llm_providers` record at all. This keeps existing dev/test setups
  working without immediate config migration. The env-var path should be
  considered deprecated and removed in a future release.
- The `/api/ai-assist/status` response shape is a strict superset of the
  old shape — existing callers reading only `key_configured`/`org_enabled`/
  `enabled` keep working unchanged.

---

## v0.22.9 — UX + Data Integrity Pass (2026-04-07)

A grab-bag of UX and pipeline-truthfulness fixes that emerged from a single
diagnostic session.

### 1. Search default view

**Problem:** Clicking Search in the nav bar opened the search page in "browse
all" mode by default, immediately running an empty-query search and showing
date-sorted hits. Users expected an empty input waiting for them to type or
click Browse All explicitly.

**Fix:** `static/search.html` init block now only auto-runs a search when a
`?q=` URL param is present. Otherwise it hides all results UI (`results-card`,
`results-toolbar`, `search-meta`, `pagination`, `empty-state`) and focuses
the input. Browse All button is still available as an explicit one-click
action.

### 2. AI Assist "needs configuration" UX

**Problem:** When `ANTHROPIC_API_KEY` is not set in the environment:
- The search-page AI Assist toggle button was silently `display: none`'d
  by `js/ai-assist.js` after `/api/ai-assist/status` returned
  `key_configured: false`.
- The Settings page "AI-Assisted Search" section was likewise
  `style="display:none"` until JS toggled it on, and the toggle never fired
  because the same status check returned early.

The user couldn't tell the feature existed, let alone how to enable it.

**Fix:**
- `static/settings.html` — section is always rendered. A new
  `#ai-assist-not-configured` notice element shows clear setup instructions
  (`ANTHROPIC_API_KEY=...` in `.env`, then `docker-compose restart markflow`)
  when the status endpoint reports `key_configured: false`. The configured
  controls are wrapped in `#ai-assist-configured-controls` and only shown
  when the key IS configured.
- `static/js/ai-assist.js` — server status is cached in module state. The
  toggle button stays visible at all times. A new `.needs-config` CSS class
  paints it amber. Clicking the button when misconfigured opens the drawer
  with an inline help message (missing key vs. admin disabled) instead of
  toggling the local enabled flag.
- `static/css/ai-assist.css` — `.ai-assist-toggle.needs-config` styling.

### 3. Pipeline "pending" count was 2-3× inflated

**Problem:** Pipeline status badge reported 84,656 pending while only 36,296
distinct files existed. Root cause: `bulk_files` is keyed by
`(job_id, source_path)`, so each new scan job inserts its own row for every
file — including files that were already successfully converted in older
jobs. The naive `COUNT(*) FROM bulk_files WHERE status='pending'` query in
`/api/pipeline/status` and `/api/pipeline/status-overview` summed across all
those duplicate rows.

The v0.22.7 self-correction job's "cross-job dedup" step kept only the most
recent job's row per source_path, but new scan runs immediately recreated the
duplication and the cleanup only ran every 6 hours.

**Fix (two layers):**

a) **Query layer** (`api/routes/pipeline.py`) — both endpoints now use a
   `NOT EXISTS` subquery against `bulk_files`:

   ```sql
   SELECT COUNT(*) FROM source_files sf
   WHERE sf.lifecycle_status = 'active'
     AND NOT EXISTS (
         SELECT 1 FROM bulk_files bf
         WHERE bf.source_path = sf.source_path
           AND bf.status = 'converted'
     )
   ```

   This counts truly-distinct unconverted source files. The `failed` and
   `unrecognized` counts in `status-overview` were rewritten the same way
   (`COUNT(DISTINCT source_path)` + same `NOT EXISTS` guard) so a file
   that failed in one job and converted in another no longer shows up in
   the failed bucket.

b) **Cleanup layer** (`core/db/bulk.py`) — `cleanup_stale_bulk_files()` now
   has a 4th deletion step, **pending-superseded prune**:

   ```sql
   DELETE FROM bulk_files
   WHERE status = 'pending'
     AND job_id NOT IN ({active_job_statuses})
     AND EXISTS (
         SELECT 1 FROM bulk_files bf2
         WHERE bf2.source_path = bulk_files.source_path
           AND bf2.status = 'converted'
     )
   ```

   This catches the common case where a newer scan job inserts a fresh
   `pending` row for a file that was already converted in an older job.
   Active jobs (scanning/running/paused/pending) are still excluded so
   in-flight work is never disturbed. Counts are returned via a new
   `pending_superseded_deleted` key in the cleanup result dict.

### 4. Adobe-files index regression — silently empty since "unified dispatch"

**Problem:** The Meilisearch `adobe-files` index reported 0 documents and the
`adobe_index` SQLite table was empty, despite ~1,400 .ai/.psd/.indd files
being scanned and 100+ .ai files showing `status='converted'` in `bulk_files`.

**Root cause:** `core/bulk_worker.py:_worker()` dispatch routes ALL files
through `_process_convertible()` (per the "unified scanning" architecture
note in CLAUDE.md). Adobe files therefore go through the regular conversion
pipeline → `AdobeHandler.ingest()` → markdown summary → `documents`
Meilisearch index. That's correct as far as it goes.

But the older `_process_adobe()` method, which calls
`AdobeIndexer.index_file()` to extract XMP/EXIF metadata + text layers and
upserts them into the `adobe_index` table (the data backing the
`adobe-files` Meilisearch index), was **never called** from the dispatch
loop. It became dead code at some point during the unified-dispatch
refactor. Result: rich Level-2 metadata for Adobe files was being silently
dropped.

**Fix:** `core/bulk_worker.py` —
- Added `_index_adobe_l2(file_dict)`: a focused method that runs
  `AdobeIndexer().index_file(source_path)` to populate `adobe_index` (via
  `upsert_adobe_index()`), then calls
  `search_indexer.index_adobe_file(result, job_id)` to push the result into
  the `adobe-files` Meilisearch index. Does NOT touch `bulk_files` status —
  the markdown conversion above already handled that. Files with extensions
  AdobeIndexer doesn't support (.ait/.indt templates, .psb) return an
  "Unsupported Adobe extension" result and are debug-logged + skipped.
- `_worker()` now invokes `_index_adobe_l2(file_dict)` immediately after
  `_process_convertible(file_dict, worker_id)` returns successfully, gated
  on `ext in ADOBE_EXTENSIONS and self.include_adobe`. Wrapped in
  `try/except` so an L2 failure never aborts the conversion.

The dead `_process_adobe()` method was left in place for now (unused but
harmless) — can be removed in a follow-up cleanup pass.

### 5. Other findings (not fixed this round)

Diagnostic findings recorded for follow-up:

- **Vector search IS working.** Qdrant has 14,377 points in collection
  `markflow_chunks` and `hybrid_search_merged` events show successful
  RRF fusion (`keyword=10, vector=10, merged=10`). `indexed_vectors_count: 0`
  in the collection info is misleading — it just means HNSW per-segment
  threshold (10k) hasn't been crossed across the 5 segments, so Qdrant uses
  brute-force search. Still returns results correctly.
- **`analysis_queue` is mostly stalled** — 2,078 pending + 1,010 failed +
  190 batched + 90 completed. Likely tied to LLM provider config and/or
  the missing ANTHROPIC_API_KEY. Worth investigating in a dedicated session.

### Modified files

- `core/version.py` — 0.22.8 → 0.22.9
- `core/db/bulk.py` — 4th cleanup step + extended docstring/return dict
- `core/bulk_worker.py` — `_index_adobe_l2()` + dispatch hook
- `api/routes/pipeline.py` — both pending queries rewritten
- `static/search.html` — init block, no auto browse-all
- `static/settings.html` — AI Assist section restructured + JS init
- `static/js/ai-assist.js` — server status caching + needs-config UX
- `static/css/ai-assist.css` — `.needs-config` styling
- `CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md` — updates

---

## v0.22.8 — GPU Detector Live Re-Resolution Fix (2026-04-07)

**Fix:** `get_gpu_info_live()` in `core/gpu_detector.py` re-reads the
`host_worker_*` fields on every health check (correctly), but never re-resolved
the derived `execution_path`, `effective_gpu_name`, or `effective_backend`
values. Those are computed once during `detect_gpu()` at container startup
and cached on the singleton `_gpu_info`. If `worker_capabilities.json` did
not exist at startup but appeared later (common during dev when running the
refresh script after the container was already up), the health page kept
reporting "CPU (no GPU detected)" even though the live re-read had populated
`host_worker_available=true` with the correct GPU details.

**Symptom:** The Status page System Health Check showed `gpu: FAIL / CPU`
while the underlying API response had a fully-populated `host_worker` block
with the correct NVIDIA / AMD / Apple GPU identified.

**Fix:** Added the same execution-path resolution block from `detect_gpu()`
to the end of `get_gpu_info_live()`. Now the live re-read also re-evaluates:

```python
if container_gpu_available and container_hashcat_backend in ("CUDA", "OpenCL"):
    -> "container"
elif host_worker_available and host_worker_gpu_backend in _gpu_backends:
    -> "host"   # this branch was being missed
elif container_hashcat_available:
    -> "container_cpu"
else:
    -> "none"
```

**Modified files:**
- `core/gpu_detector.py` — Added execution-path resolution to `get_gpu_info_live()`
- `core/version.py` — 0.22.7 → 0.22.8
- `CLAUDE.md`, `docs/version-history.md` — Updates

---

## v0.22.7 — bulk_files Self-Correction (2026-04-07)

**Feature:** Periodic cleanup sweep for the `bulk_files` table that prunes
phantom rows, purged rows, and cross-job duplicates. Solves the long-standing
issue where the pipeline status badge reported nonsensical pending counts
(observed: 325,186 pending for 34,814 unique source files — a ~9.3x
duplication factor across 9-10 historical bulk jobs).

**Background:**
The `bulk_files` table is keyed by `(job_id, source_path)`, so each new scan
job inserts a fresh row for every file even if previous jobs already converted
it. Over time the table balloons to many multiples of the unique source file
count. The pipeline status badge sums across all `bulk_files` rows without
deduplicating by `source_path`, producing inflated and misleading pending
counts. Documented as a known issue in `docs/gotchas.md`.

**The cleanup performs three deletions in a single transaction:**

1. **Phantom prune**: `DELETE FROM bulk_files WHERE source_path NOT IN
   (SELECT source_path FROM source_files)` — removes rows for files that no
   longer exist in the source registry (file deleted from disk).
2. **Purged prune**: `DELETE FROM bulk_files WHERE source_path IN (SELECT
   source_path FROM source_files WHERE lifecycle_status='purged')` — removes
   rows for files that were permanently trashed.
3. **Cross-job dedup**: For each `source_path`, keep only the row from the
   most recent job (by `bulk_jobs.started_at`) and delete older duplicates.

**Safety:** All three deletions exclude rows belonging to active jobs
(status in `scanning`, `running`, `paused`, `pending`). The scheduler
wrapper additionally skips the entire job if `get_all_active_jobs()` is
non-empty, providing two layers of protection against touching in-flight rows.

**Schedule:** Every 6 hours via `_bulk_files_self_correction()` in
`core/scheduler.py`. Job ID `bulk_files_self_correction`.

**Manual trigger:** `POST /api/admin/cleanup-bulk-files` (admin role required).
Returns 409 Conflict if a bulk job is currently active. Response payload:
```json
{
  "phantom_deleted": 12,
  "purged_deleted": 0,
  "dedup_deleted": 290847,
  "total_deleted": 290859
}
```

**Modified files:**
- `core/db/bulk.py` — New `cleanup_stale_bulk_files()` function with
  three-pass deletion logic and active-job exclusion
- `core/db/__init__.py` — Export `cleanup_stale_bulk_files`
- `core/scheduler.py` — New `_bulk_files_self_correction()` wrapper that
  checks `get_all_active_jobs()` before delegating, plus job registration
  in `start_scheduler()` (now reports 15 jobs)
- `api/routes/admin.py` — New `POST /api/admin/cleanup-bulk-files` endpoint
- `core/version.py` — 0.22.6 → 0.22.7
- `CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md` — Updates

---

## v0.22.6 — Critical hashlib Bug + Vision Payload Splitter (2026-04-06)

**Critical Fixes:**

- **`hashlib` UnboundLocalError in bulk_worker**: A local `import hashlib` inside
  the vector-indexing block (line 802) shadowed the module-level import. Python's
  scoping rules then treated `hashlib` as a local variable for the **entire function**,
  causing the earlier `hashlib.sha256(...)` call on line 726 to raise
  `UnboundLocalError: cannot access local variable 'hashlib' where it is not
  associated with a value`. This caused **every file in every bulk job to fail**,
  triggering the 100% error-rate auto-abort in a runaway cascade.
  - Log impact: 124,216 `bulk_worker_error_rate_abort` events, 67
    `bulk_worker_unhandled` errors, 506 files marked failed, 19+ jobs cancelled.
  - **Fix:** Removed the redundant inner import (`hashlib` is already imported
    at module level).

- **Vision adapter `413 Payload Too Large` from Anthropic API**:
  `_batch_anthropic()` sent up to 10 base64-encoded images per request without
  checking total size. Large keyframes pushed requests over Anthropic's 32 MB
  hard limit, killing entire vision batches.
  - **Fix:** Rewrote `_batch_anthropic()` with a size-aware greedy splitter.
    Pre-encodes all images, groups into sub-batches that stay under 24 MB (leaving
    8 MB headroom for JSON envelope, headers, and prompt text), and makes
    multiple sequential API calls per logical batch. Results are reassembled in
    original input order. New constant `_ANTHROPIC_MAX_PAYLOAD_BYTES = 24 MB`.

**Modified files:**
- `core/bulk_worker.py` — Removed shadowing inner `import hashlib`
- `core/vision_adapter.py` — Size-aware batch splitter for Anthropic vision

---

## v0.22.5 — Bulk Scanner files/sec Display Fix (2026-04-07)

**Fix:** The Active Job panel on the Bulk Jobs page displayed nonsensical scan
rates like `783184.5 files/sec` and a meaningless `~0s remaining` ETA during
parallel scans. Root cause was in `core/bulk_scanner.py` — the parallel drain
loop collected up to 200 files from the worker queue per cycle, then called
`tracker.record_completion()` once per file in a tight loop. All ~200 entries
landed in `RollingWindowETA`'s 100-slot deque with near-identical
`time.monotonic()` timestamps (sub-millisecond apart), so the fps math
(`(newest_count - oldest_count) / elapsed`) divided ~100 files by a ~127µs
span, producing ~787k files/sec.

Replaced the per-file loop with a single
`await tracker.record_completion(count=len(batch))` so each drain cycle yields
exactly one window entry. Window entries are now spaced by the real wall-clock
interval between drains (tens of ms to seconds), giving a realistic files/sec
and a usable scan ETA.

The serial scan path and single-file path were unaffected — they already call
`record_completion()` once per discovered file with real wall-clock pacing.
`RollingWindowETA.record_completion()` already accepted a `count` parameter;
this fix just uses it instead of iterating.

**Modified files:**
- `core/bulk_scanner.py` — parallel drain loop records batch as single window entry

---

## v0.22.4 — Help Link Fix + Auto-Conversion Article (2026-04-06)

**Fixes:**
- **Help icon links broken**: The `?` icons added by `static/js/help-link.js` linked to
  `/help#slug`, but the static catch-all in `main.py` only matches paths ending in
  `.html`. Updated to `/help.html#slug`.
- **Missing auto-conversion help article**: Added `docs/help/auto-conversion.md`
  covering modes (immediate/business-hours/scheduled/manual), workers, batch sizing,
  the pipeline master switch, decision logging, Run Now, priority interaction with
  manual jobs, and troubleshooting. Registered in `_index.json` under "Core Features".

**Modified files:**
- `static/js/help-link.js` — `/help#` -> `/help.html#`
- `docs/help/auto-conversion.md` — New help article
- `docs/help/_index.json` — Added auto-conversion entry

---

## v0.22.3 — Settings Toggle State Persistence Fix (2026-04-06)

**Fix:** Toggle switches on the Settings page did not display their saved state on
page load. `updateToggleLabel()` was hardcoded to update only the "unattended" toggle
label ID, so all other toggles always showed "OFF" regardless of their actual saved
value. Users attempting to re-save saw "nothing to save" because the underlying
checkbox values were correct -- only the visible labels were wrong.

- Rewrote `updateToggleLabel()` to generically find the sibling `.toggle-label`
  within the same `.toggle` parent via `el.closest('.toggle')`.
- Added a single `document.querySelectorAll('.toggle input')` change handler for
  all toggles, replacing scattered per-toggle event wiring.

**Modified files:**
- `static/settings.html` — Generic `updateToggleLabel()`, bulk change handler

---

## v0.22.2 — Toggle Switch UX Redesign, SQLite Timestamp Fix (2026-04-06)

**Fixes:**
- **Toggle switches redesigned**: Settings page toggles now have a visible track outline
  showing the knob travel path, dim knob/track when off, accent-colored glow when on,
  and label text to the right that lights up with the accent color on check. Replaces the
  cramped "OFF" text that overlapped the switch bubble.
- **SQLite `datetime('now')` timestamps**: `cleanup_orphaned_jobs()` now uses `now_iso()`
  instead of SQLite's `datetime('now')` for consistent `+00:00` offset formatting.
  Frontend `parseUTC()` also handles legacy space-separated timestamps from SQLite.

**Modified files:**
- `static/markflow.css` — Toggle switch redesign (`.toggle-track`, `.toggle-label`)
- `static/app.js` — `parseUTC()` handles `YYYY-MM-DD HH:MM:SS` format
- `core/db/schema.py` — `cleanup_orphaned_jobs()` uses `now_iso()` instead of `datetime('now')`

---

## v0.22.1 — Timestamp Localization, GPU Detection Fix, Script Portability (2026-04-06)

**Fixes:**
- **UTC timestamps displayed as local time**: All user-facing pages now correctly convert
  UTC timestamps to the browser's local timezone. Added `parseUTC()` helper in `app.js`
  that appends `Z` to bare ISO timestamps (no timezone suffix) before parsing. Updated
  `formatLocalTime()` and fixed 6 pages that bypassed it with raw `new Date()` calls:
  `bulk.html`, `db-health.html`, `trash.html`, `pipeline-files.html`, `version-panel.js`.
- **GPU health check showing wrong hardware**: `worker_capabilities.json` was committed
  to git with stale Apple M4 Pro data from a different machine. Now gitignored — each
  machine generates it at deploy time via the refresh/reset scripts. Added `.json.example`
  for reference.
- **PowerShell script parse errors**: All `.ps1` and `.sh` scripts under `Scripts/` had
  non-ASCII characters (em dashes, box-drawing, emojis) that broke Windows PowerShell 5.1
  (reads BOM-less UTF-8 as Windows-1252, where byte 0x94 from em dash becomes a right
  double quote, breaking string parsing). Replaced with ASCII equivalents across all 18
  script files for cross-platform safety (Windows PS5.1, macOS zsh, Linux bash over SSH).

**Modified files:**
- `static/app.js` — `parseUTC()` helper, `formatLocalTime()` rewrite
- `static/bulk.html` — Use `parseUTC()` for last-scan time
- `static/db-health.html` — Use `formatLocalTime()` for compaction/integrity dates
- `static/trash.html` — Use `formatLocalTime()` for trash/purge dates
- `static/pipeline-files.html` — Use `parseUTC()` in local `formatLocalTime()`
- `static/js/version-panel.js` — Use `parseUTC()` for recorded_at
- `.gitignore` — Add `hashcat-queue/worker_capabilities.json`
- `hashcat-queue/worker_capabilities.json.example` — New reference template
- `Scripts/**/*.ps1`, `Scripts/**/*.sh` — ASCII-only characters (18 files)

---

## v0.22.0 — Hybrid Vector Search (2026-04-05)

**Feature:** Semantic vector search augmenting existing Meilisearch keyword search.
Documents are chunked with contextual headers, embedded locally via sentence-transformers,
and stored in Qdrant. At query time, both systems run in parallel and results merge
via Reciprocal Rank Fusion (RRF). Graceful fallback to keyword-only when Qdrant is
unavailable. Query preprocessor detects temporal intent and biases toward recent docs.

**New files:**
- `core/vector/chunker.py` — Markdown to contextual chunks (heading-based + fixed-size fallback)
- `core/vector/embedder.py` — Pluggable embedding (local sentence-transformers default)
- `core/vector/index_manager.py` — Qdrant collection lifecycle, document indexing, search
- `core/vector/hybrid_search.py` — RRF merge of keyword + vector results
- `core/vector/query_preprocessor.py` — Temporal intent detection, query normalization

**Modified files:**
- `docker-compose.yml` — Qdrant container + volume
- `requirements.txt` — sentence-transformers, qdrant-client
- `core/bulk_worker.py` — Vector indexing parallel to Meilisearch (fire-and-forget)
- `api/routes/search.py` — Hybrid search in `/api/search/all`
- `main.py` — Vector search startup health check

**Infrastructure:**
- Qdrant container (internal port 6333, not exposed to host)
- Single collection `markflow_chunks` with payload filtering
- `all-MiniLM-L6-v2` embedding model (384 dimensions, ~80MB, CPU inference)
- Embedding model version tracked in collection metadata for future upgrade path

---

## v0.21.0 — AI-Assisted Search (2026-04-05)

**Feature:** Opt-in AI synthesis layer on top of existing Meilisearch results. A
persistent toggle in the search bar activates a right-side drawer that streams a
Claude-synthesized answer grounded in the top matching documents. A "Read full doc"
button per cited source triggers a deeper single-document analysis.

**New files:**
- `core/ai_assist.py` — Claude API streaming (search synthesis + document expand)
- `api/routes/ai_assist.py` — FastAPI endpoints (`/api/ai-assist/search`, `/expand`, `/status`)
- `static/js/ai-assist.js` — Toggle, drawer, SSE streaming, source expansion
- `static/css/ai-assist.css` — Drawer styles, loading/streaming/error states

**Modified files:**
- `main.py` — Register ai_assist router
- `.env.example` — Add `ANTHROPIC_API_KEY`, `AI_ASSIST_MODEL`, `AI_ASSIST_MAX_TOKENS`, `AI_ASSIST_EXPAND_MAX_TOKENS`
- `static/search.html` — Add toggle button, drawer scaffold, CSS/JS links, init + onResults calls
- `docker-compose.yml` — Pass AI env vars to markflow service

**Behaviour:**
- Feature is completely opt-in — hidden when `ANTHROPIC_API_KEY` is not set
- Toggle state persists across page reloads via localStorage
- Streams SSE events: `chunk` (text delta), `sources` (citation metadata), `done`, `error`
- Expand endpoint reads converted markdown from `source_files.output_path`
- Uses `httpx` for streaming (already in requirements.txt)

**Amendment 1 — Org toggle + usage tracking:**
- Org-wide on/off toggle in Settings (admin only), stored in `user_preferences` table
- `ai_assist_usage` table (migration 24) logs user, query, mode, estimated tokens per call
- Admin endpoints: `PUT /api/ai-assist/admin/toggle`, `GET /api/ai-assist/admin/usage`
- Settings page shows per-user totals and recent calls with estimated token spend
- `/api/ai-assist/status` now returns `{key_configured, org_enabled, enabled}`
- Search/expand endpoints return 503 when org toggle is off
- New module: `core/db/ai_usage.py`

---

## v0.20.3 — Handwriting Recognition via LLM Vision Fallback (2026-04-05)

**Feature:** Automatic handwriting detection and LLM-powered transcription. When
Tesseract OCR produces results that match handwriting patterns (very low confidence,
high flagged word ratio, unrecognisable words), the page image is sent to the active
LLM vision provider for transcription.

**How it works:**
1. Tesseract runs as normal on every scanned page
2. `detect_handwriting()` analyses the OCR output for three signals:
   - Average confidence below threshold (default 40%)
   - More than 60% of words below the confidence threshold
   - Low dictionary hit rate (most "words" aren't recognisable English)
3. If all three signals fire, the page image is sent to the LLM vision adapter
4. In unattended mode: LLM text automatically replaces Tesseract output
5. In review mode: both outputs shown, user picks or edits

**Configuration:**
- `handwriting_confidence_threshold` preference (default: 40)
- Requires an active LLM vision provider (Claude, GPT-4V, Gemini, or Ollama)
- Falls back gracefully to manual review if no provider is configured

**Files changed:**
- `core/ocr.py` — added `detect_handwriting()` and `_llm_handwriting_fallback()`
- `core/ocr_models.py` — added `handwriting_detected` field to `OCRFlag`
- `core/db/schema.py` — migration 23 (handwriting_detected column on ocr_flags)
- `core/db/conversions.py` — persist handwriting_detected in insert_ocr_flag
- `core/version.py` — bump to 0.20.3
- `docs/help/ocr-pipeline.md` — updated handwriting FAQ
- `README.md` — updated OCR description, version
- `CLAUDE.md` — updated current status

---

## v0.20.2 — Binary File Handler Expansion (2026-04-05)

**Feature:** Expanded the binary metadata handler to cover 30+ common binary file
types. Executables, DLLs, shared libraries, disk images, virtual disks, databases,
firmware, bytecode, and object files are now recognized and cataloged with metadata
(size, MIME type, magic bytes) instead of appearing as "unrecognized."

Also fixes `.heic` and `.heif` missing from `SUPPORTED_EXTENSIONS` (they were
handled by `image_handler.py` since v0.19.6.8 but never added to the scanner set,
so bulk scans marked them as unrecognized).

**New extensions in binary handler:**
- Executables & libraries: `.exe`, `.dll`, `.so`, `.msi`, `.sys`, `.drv`, `.ocx`, `.cpl`, `.scr`, `.com`
- macOS binaries: `.dylib`, `.app`, `.dmg`
- Disk images: `.img`, `.vhd`, `.vhdx`, `.vmdk`, `.vdi`, `.qcow2`
- Databases: `.sqlite`, `.db`, `.mdb`, `.accdb`
- Firmware & ROM: `.rom`, `.fw`, `.efi`
- Bytecode: `.class`, `.pyc`, `.pyo`
- Object files: `.o`, `.obj`, `.lib`, `.a`
- Misc: `.dat`, `.dmp`

**DB migration 22:** Re-queues all formerly unrecognized files of the above types
(and `.heic`/`.heif`) by setting their status from `unrecognized` to `pending`.
They will be processed by the binary handler (or image handler) on the next bulk run.

**Files changed:**
- `formats/binary_handler.py` — added 30 extensions + type descriptions
- `core/bulk_scanner.py` — added 32 extensions to SUPPORTED_EXTENSIONS (30 binary + .heic/.heif)
- `core/db/schema.py` — migration 22
- `core/version.py` — bump to 0.20.2
- `README.md` — updated format table, version, file count
- `docs/help/unrecognized-files.md` — updated extension count, notes on binary handler
- `docs/help/document-conversion.md` — expanded binary row, added .heic/.heif to images
- `CLAUDE.md` — updated current status

---

## v0.20.1 — 20 New File Format Handlers (2026-04-05)

**Feature:** Added support for 20 new file extensions across 6 new handlers and
6 extended existing handlers. Total supported formats: ~80 extensions.

**Extended existing handlers:**
- `txt_handler.py` — added `.lst` (list files), `.cc` (C++ source), `.css` (stylesheets)
- `csv_handler.py` — added `.tab` (tab-delimited data, same treatment as .tsv)
- `pptx_handler.py` — added `.pptm` (PowerPoint macro-enabled)
- `docx_handler.py` — added `.wbk` (Word backup), `.pub` (Publisher), `.p65` (PageMaker) via LibreOffice
- `adobe_handler.py` — added `.psb` (Photoshop Big, same as PSD)
- `image_handler.py` — added `.cr2` (Canon RAW)

**New handlers:**
- `font_handler.py` — `.otf`, `.ttf` — extracts font metadata via fonttools
- `shortcut_handler.py` — `.lnk` (Windows shortcut), `.url` (URL shortcut)
- `vcf_handler.py` — `.vcf` — parses vCard contacts
- `svg_handler.py` — `.svg` — parses SVG XML, extracts dimensions/elements/text
- `sniff_handler.py` — `.tmp` — MIME-detects content, delegates to matching handler
- `binary_handler.py` — `.bin`, `.cl4` — metadata-only (size, MIME, magic bytes)

**Files changed:**
- 6 modified handlers, 6 new handler files
- `formats/__init__.py` — register new handlers
- `core/bulk_scanner.py` — add all 20 extensions to SUPPORTED_EXTENSIONS
- `core/version.py` — bump to 0.20.1

---

## v0.20.0 — NFS Mount Support + Mount Settings UI (2026-04-05)

**Feature:** Network mount configuration is no longer hardcoded to SMB/CIFS. MarkFlow
now supports SMB/CIFS, NFSv3, and NFSv4 (with optional Kerberos) as mount protocols.

**New components:**
- `core/mount_manager.py` — Protocol-agnostic mount abstraction. Generates mount commands
  and fstab entries, handles live mount/unmount, tests connections, persists config to
  `/etc/markflow/mounts.json`. Supports `dry_run=True` for config-generation mode.
- `api/routes/mounts.py` — REST endpoints: GET status, POST test, POST apply.
- Settings UI "Storage Connections" section — radio buttons for protocol, conditional
  SMB credentials / NFSv4 Kerberos fields, test and apply buttons with live status.
- Setup script protocol selection — choose SMB/NFSv3/NFSv4 during initial VM provisioning.

**Files changed:**
- `core/mount_manager.py` — NEW
- `api/routes/mounts.py` — NEW
- `tests/test_mount_manager.py` — NEW
- `static/settings.html` — Storage Connections section
- `Scripts/proxmox/setup-markflow.sh` — protocol selection menu
- `Dockerfile.base` — added `nfs-common` package
- `main.py` — register mounts router
- `core/version.py` — bump to 0.20.0

---

## v0.19.6.11 — Fix Three Scan Failures (2026-04-05)

**Problem:** Bulk scan reported 12 failed files across three distinct root causes.

**Bug 1 — Read-only FS crash on media files (2 files):**
`audio_handler.py` and `media_handler.py` computed the MediaOrchestrator output dir
as `file_path.parent / "_markflow"`, which writes into the source mount. Since
`/mnt/source` is mounted read-only, this raised `[Errno 30] Read-only file system`.

**Fix:** Both handlers now use `tempfile.mkdtemp()` for the orchestrator's scratch
output. The bulk worker already places the final `.md` and sidecar into the correct
output tree independently.

**Bug 2 — INI parser crash on XGI driver config files (8 files):**
Python's `configparser` with `allow_no_value=True` raises `AttributeError`
(`'NoneType' object has no attribute 'append'`) on INI files with continuation
lines after a no-value key. The exception handler only caught `configparser.Error`
and `KeyError`, not `AttributeError`, so the fallback line parser never ran.

**Fix:** Added `AttributeError` to the `_try_configparser` exception handler so
these files fall through to the line-by-line parser.

**Bug 3 — Markdown handler UTF-8 decode error (1 file):**
`markdown_handler.py` called `read_text(encoding="utf-8")` with no fallback.
A LICENSE-MIT.md file encoded in Latin-1 (byte `0xa9` = `©`) crashed with
`UnicodeDecodeError`.

**Fix:** Added `try/except UnicodeDecodeError` with Latin-1 fallback.

**Files changed:**
- `formats/audio_handler.py` — use tempdir for orchestrator output
- `formats/media_handler.py` — use tempdir for orchestrator output
- `formats/ini_handler.py` — catch `AttributeError` in `_try_configparser`
- `formats/markdown_handler.py` — Latin-1 fallback for non-UTF-8 `.md` files
- `core/version.py` — bump to 0.19.6.11

---

## v0.19.6.10 — Reduce PDF Image Extraction Log Noise (2026-04-05)

**Problem:** WSJ newspaper PDFs embed images as raw FlateDecode pixel streams (no image
headers). The image handler tried `PIL.Image.open()` on these headerless byte buffers,
producing hundreds of `image_handler.convert_failed` warnings per PDF file — flooding logs
during bulk conversion.

**Root cause:** `_extract_page_images()` in `pdf_handler.py` hardcoded `format="png"` for
all PDF image streams, regardless of the actual encoding. FlateDecode streams contain raw
pixel data that requires Width/Height/BPC metadata from the PDF dictionary to interpret.

**Fix (4 changes):**

1. **Format detection via magic bytes** — PDF handler now checks `\xff\xd8` (JPEG) and
   `\x89PNG` headers before calling `extract_image()`. Passes `"jpeg"`, `"png"`, or `"raw"`
   accordingly.

2. **Stream metadata passthrough** — For raw streams, Width and Height from
   `stream.attrs` are passed as `raw_width`/`raw_height` keyword args.

3. **Raw pixel reconstruction** — New `_reconstruct_raw_pixels()` function infers PIL
   colour mode (L/RGB/CMYK) from data length vs. dimensions, then uses
   `Image.frombytes()` to build a valid image and export as PNG.

4. **Log level downgrade** — `UnidentifiedImageError` now logs at debug level
   (`image_handler.raw_unidentified`) instead of warning. Unexpected errors still warn.

**Files changed:**
- `core/image_handler.py` — added `raw_width`/`raw_height` params, `_reconstruct_raw_pixels()`, split `UnidentifiedImageError` from general exceptions
- `formats/pdf_handler.py` — magic-byte format detection, stream metadata extraction
- `core/version.py` — bump to 0.19.6.10

---

## v0.19.6.9 — Fix Search Page Crash & Optimize Search API (2026-04-04)

**Two fixes that made the search page non-functional:**

1. **Search page JS crash (DOM ordering)** — The `preview-popup` and `flag-modal-backdrop`
   divs were placed after the `</script>` tag in `search.html`. An IIFE that wired up
   preview mouse events ran during parse and called `getElementById('preview-popup')`, which
   returned `null` because the element hadn't been parsed yet. The resulting `TypeError`
   killed the entire script block — `doSearch()`, event listeners, and all search
   functionality never initialized. Fix: moved both div blocks before the script tag.

2. **Search API response bloat (2.7 MB → 13 KB)** — `_map_hit()` in `api/routes/search.py`
   copied every field from Meilisearch results including `content` (full document text) and
   `headings` (1.38 MB for a single archive file). Added `attributesToRetrieve` whitelist
   to the Meilisearch query and rewrote `_map_hit()` to only include fields the frontend
   actually renders. Response size dropped from 2.7 MB to 13 KB for 10 results (205× reduction).

**Files changed:**
- `static/search.html` — moved preview-popup and flag-modal before script block
- `api/routes/search.py` — `attributesToRetrieve` whitelist, `_map_hit()` field whitelist
- `core/version.py` — bump to 0.19.6.9

---

## v0.19.6.8 — HEIC/HEIF Support & Search Auto-Browse (2026-04-04)

**Two improvements: new image format support and search page UX.**

1. **HEIC/HEIF image conversion** — Added `pillow-heif` dependency and registered the HEIF
   opener in `formats/image_handler.py`. HEIC/HEIF files (common iPhone photo format) are
   now handled like any other image, routed through `core.image_handler.extract_image` for
   consistent PNG normalization into the document model's asset pipeline. Extension list
   updated in handler and README.

2. **Search page auto-browse on load** — `static/search.html` now automatically loads all
   documents sorted by date when the page opens with no query, instead of showing a blank
   page. Users see their most recent documents immediately.

**Files changed:**
- `formats/image_handler.py` — HEIC/HEIF extensions, pillow-heif import, extract_image routing
- `requirements.txt` — added `pillow-heif`
- `static/search.html` — auto-browse on empty query
- `core/version.py` — bump to 0.19.6.8
- `README.md` — version bump, HEIC/HEIF in supported formats table
- `CLAUDE.md` — current status updated

---

## v0.19.6.7 — Scan Coordinator Crash Resilience (2026-04-04)

**Three fixes for scanner runs getting stuck after container restarts:**

1. **Coordinator state reset on startup** — Added `reset_coordinator()` called during
   app lifespan after `cleanup_orphaned_jobs()`. Previously, in-memory coordinator flags
   (`run_now_running`, `lifecycle_running`) persisted as ghost state if the container
   restarted mid-scan, blocking future scans indefinitely.

2. **Periodic counter flush during scan** — Scan run counters (`files_scanned`, `files_new`,
   etc.) are now flushed to the DB every 500 files during both serial and parallel walks.
   Previously, counters were only written at scan completion, so crash recovery left all
   counters at zero.

3. **Stale scan watchdog** — New `check_stale_scans()` runs every 5 minutes via the
   scheduler. If a run-now or lifecycle scan has been "running" for longer than 4 hours
   without completing (e.g. async task died silently), the watchdog resets the coordinator
   flag. The coordinator status API now includes elapsed time and timeout info.

**Files changed:**
- `core/scan_coordinator.py` — `reset_coordinator()`, `check_stale_scans()`, timestamp tracking, enriched status
- `core/lifecycle_scanner.py` — `_flush_counters_to_db()`, flush calls in serial and parallel walkers
- `core/scheduler.py` — `check_stale_scans` job (5-minute interval)
- `main.py` — call `reset_coordinator()` on startup
- `core/version.py` — bump to 0.19.6.7

---

## v0.19.6.6 — Fix OCR Confidence Threshold Slider Display (2026-04-03)

**Bug fix — OCR confidence threshold showed incorrect percentage (e.g. 400%):**

- `populateForm()` in `settings.html` had a generic `el.type === 'range'` branch that
  wrote every range slider's value to the shared `range-output` element. The conservatism
  factor slider (0.3–1.0) overwrote the OCR confidence display on page load.
- Fixed by routing each range slider to its own output element based on the preference key.

**Files changed:**
- `static/settings.html` — key-specific output updates in `populateForm()`

---

## v0.19.6.5 — DB Contention Logging for Lock Diagnosis (2026-04-03)

**TEMPORARY instrumentation to diagnose recurring "database is locked" errors:**

- New `core/db/contention_logger.py` module with three dedicated log files:
  - `db-contention.log` — every write acquire/release with caller identity, hold duration,
    and active connection count
  - `db-queries.log` — full SQL query log (statement, params, duration, caller, row count)
  - `db-active.log` — active-connection snapshots dumped whenever "database is locked" fires,
    showing exactly who is holding the lock
- All three logs capped at 1 GB with 3 sequential backup files
- `ActiveConnectionTracker` maintains a thread-safe registry of open DB connections;
  on lock error, dumps every active holder with caller, intent, thread, and hold time
- Instrumented `get_db()`, `db_fetch_one()`, `db_fetch_all()`, `db_execute()`, and
  `db_write_with_retry()` in `core/db/connection.py`
- **Deactivate once lock contention is resolved** — flagged in CLAUDE.md and gotchas.md

**Files changed:**
- `core/db/contention_logger.py` — new module (loggers, tracker, helpers)
- `core/db/connection.py` — instrumented all DB access paths

---

## v0.19.6.4 — Fix Scan Crash: Wrong Table Name in Incremental Counter (2026-04-03)

**Bug fix — scans crashed immediately with `no such table: preferences`:**

- Three raw SQL queries in `core/db/bulk.py` (`get_incremental_scan_count()`,
  `increment_scan_count()`, `reset_scan_count()`) referenced `preferences` instead of
  the correct `user_preferences` table.
- Any scan trigger (run-now, lifecycle) hit `OperationalError: no such table: preferences`
  and failed before scanning a single file.
- Root cause: the incremental scan counter functions added in v0.19.5 used hardcoded
  table names instead of the DB helper layer.

**Files changed:**
- `core/db/bulk.py` — `preferences` → `user_preferences` in 3 queries

---

## v0.19.6.3 — Pipeline Files Chip Colors UI Revision (2026-04-03)

**Minor UI revision for the pipeline files page filter chips:**

- Filter chips on `pipeline-files.html` now always display their category colors (matching the 
  status page pipeline pills), not just when the filter is active.
- Color scheme: purple for pending analysis, yellow for batched, red for failed/analysis failed, 
  green for indexed.
- Active state adds a border highlight and bold text weight for visual emphasis.

**Files changed:**
- `static/pipeline-files.html` — chip color styling and active state CSS

---

## v0.19.6.2 — LLM Banner CSS Fix (2026-04-03)

**Patch fix for the LLM provider status banner CSS on `pipeline-files.html`:**

- `.llm-banner` had `display: flex` which overrode the HTML `hidden` attribute, causing an
  empty red banner to render even when the provider was verified and active.
- Fixed by removing `hidden` from the HTML and defaulting `.llm-banner` to `display: none`.
  A new `.visible` class sets `display: flex`, toggled via `classList.add/remove('visible')` in JS.

**Files changed:**
- `static/pipeline-files.html` — CSS default `display: none` + `.visible` class toggle

---

## v0.19.6.1 — LLM Banner Empty Display Fix (2026-04-03)

**Patch fix for the LLM provider status banner on `pipeline-files.html`:**

- Banner was rendering as an empty red box even when the active provider was verified and
  active. Root cause: SQLite returns `is_active` / `is_verified` as integers (`0`/`1`), not
  Python booleans. Truthy checks passed for both truthy (`1`) and falsy (`0`) values in some
  code paths. Fixed with explicit `== 1` equality checks.
- Banner now hides (sets `display: none`) on fetch error instead of remaining visible in its
  default state, preventing a spurious red box when the provider API is unreachable.

**Files changed:**
- `static/pipeline-files.html` — integer equality checks for `is_active`/`is_verified`; hide banner on fetch error

---

## v0.19.6 — Pipeline Files Fixes + Provider UX (2026-04-03)

**Multiple fixes and features for the pipeline files page and LLM provider workflow:**

### 1. Pipeline files display fixes
- HTTP 500 on the `pending` filter resolved: the UNION query in `GET /api/pipeline/files`
  had ambiguous column names across joined tables. Fixed by wrapping the UNION in a
  subquery so ORDER BY / column references are unambiguous.
- Unicode escape sequences (e.g., `\u2190`, `\u2014`) were rendering as literal text
  in the HTML page. Replaced all JS `\u` escapes in HTML files with proper HTML entities
  (`&larr;`, `&mdash;`, etc.). JS escapes are only valid inside `<script>` blocks, not
  in HTML attribute values or `innerHTML`.

### 2. LLM provider status banner on pipeline files page
- Red eye-catching banner appears when the active AI provider is missing, inactive, or
  unverified.
- Shows a contextual message: "No AI provider configured", "No active AI provider", or
  "Active AI provider needs verification".
- Clickable link to the providers page. The link appends `?return=pipeline-files.html`
  so the user can navigate back with context after fixing the provider.

### 3. Return-to workflow on providers page
- When `static/providers.html` is loaded with a `?return=` query parameter, a blue
  banner appears at the top with a "Return to previous page" link.
- Minimizes workflow interruption when navigating from another page to fix a provider.

### 4. Auto-requeue failed analysis on provider verify
- `POST /api/llm-providers/{id}/verify` now resets all `analysis_queue` rows with
  `status='failed'` to `status='pending'` with `retry_count=0` on successful verification.
- Handles the common case where images failed analysis because the provider wasn't
  configured or verified — they automatically re-enter the processing queue.
- API response now includes a `requeued_analysis` field with the count of reset rows.

### 5. GPU health display fix
- `_read_host_worker_report()` in `core/gpu_detector.py` no longer requires `worker.lock`
  or a fresh timestamp check. Reads hardware capabilities directly from the reset script's
  `worker_capabilities.json`. Health check now correctly considers `host_worker_available`
  when determining OK status.

### 6. Providers page delete button fix
- `API.delete` → `API.del` in `static/providers.html`. `delete` is a JavaScript reserved
  word and cannot be used as a method name via dot notation.

**Files changed:**
- `api/routes/pipeline.py` — subquery fix for UNION ambiguous column names
- `api/routes/llm_providers.py` — auto-requeue failed analysis on verify; `requeued_analysis` in response
- `core/gpu_detector.py` — read capabilities from `worker_capabilities.json` directly
- `static/pipeline-files.html` — HTML entity fix for unicode escapes; LLM provider status banner
- `static/providers.html` — return-to banner; `API.delete` → `API.del`

---

## v0.19.5 — HDD Scan Optimizations (2026-04-03)

**Three targeted improvements to reduce mechanical HDD scan time:**

### 1. Directory mtime skip (incremental scanning)
- New `scan_dir_mtimes` table (migration 21): stores `(location_id, dir_path, mtime)`
  across scan runs for both bulk and lifecycle scanners.
- `core/db/bulk.py`: 5 new helpers — `load_dir_mtimes()`, `save_dir_mtimes_batch()`,
  `get_incremental_scan_count()`, `increment_scan_count()`, `reset_scan_count()`.
- `core/db/preferences.py`: 2 new defaults — `scan_incremental_enabled` (true),
  `scan_full_walk_interval` (5).
- On rescan, directories with unchanged mtimes are skipped entirely (no `os.walk`
  descent). Full walk is forced every Nth scan (preference-configurable) and any time
  the scan runs outside business hours (using `scanner_business_hours_start/end`).
- Applies to all 3 scan paths: bulk serial, bulk parallel (`_walker_thread`),
  and lifecycle (`_walker_thread`).

### 2. Batched serial DB writes
- The bulk serial (HDD) scan path now accumulates files in a 200-file buffer
  and flushes via `upsert_bulk_files_batch()` (introduced in v0.19.3) instead
  of committing per file. Previously the serial path did not use the batch helper.

### 3. Disk/DB overlap in serial scan
- After flushing a batch, DB writes are launched as `asyncio.create_task()` so the
  next round of stat() calls starts immediately without waiting for the DB commit.
  Disk I/O stays strictly serial; only DB writes run concurrently.
- Each pending write task is awaited before a new one is created to prevent unbounded
  task accumulation.

**Files changed:**
- `core/db/schema.py` — migration 21: `scan_dir_mtimes` table
- `core/db/bulk.py` — `load_dir_mtimes()`, `save_dir_mtimes_batch()`,
  `get_incremental_scan_count()`, `increment_scan_count()`, `reset_scan_count()`
- `core/db/preferences.py` — `scan_incremental_enabled`, `scan_full_walk_interval` defaults
- `core/bulk_scanner.py` — incremental decision in `scan()`, mtime skip in `_serial_scan`
  and `_walker_thread`, batched writes + async overlap in `_serial_scan`
- `core/lifecycle_scanner.py` — mtime skip in walker threads, incremental decision
  + mtime persistence

---

## v0.19.4 — Pipeline File Explorer (2026-04-03)

**Clickable stat badges and a dedicated file browser page for the pipeline:**
- `static/status.html`: Status page stat pills converted from `<span>` to `<a>` tags
  linking to `pipeline-files.html?status={category}`.
- New `static/pipeline-files.html`: Full-featured file browser page.
  - 8 filter chips (scanned, pending, failed, unrecognized, pending_analysis, batched,
    analysis_failed, indexed) as multi-select toggles.
  - Search with 300ms debounce.
  - Full-width paginated table with inline detail expansion (error msg, skip reason,
    timestamps, job links).
  - Row actions: open in viewer, browse to source location.
- New `GET /api/pipeline/files` endpoint in `api/routes/pipeline.py` — multi-status
  UNION queries across `source_files`, `bulk_files`, `analysis_queue`, and Meilisearch
  browse for indexed files.
- New `get_pipeline_files()` DB helper in `core/db/bulk.py`.
- New `_browse_search_index()` helper in `api/routes/pipeline.py`.
- "Files" nav item added to `static/app.js` NAV_ITEMS array.
- Hover styles added to `static/markflow.css` (`.stat-pill--link`).

---

## v0.19.3 — Batched Bulk Scanner DB Upserts (2026-04-03)

**100x faster scan phase for large file sets:**
- `core/db/bulk.py`: New `upsert_bulk_files_batch()` writes batches of up to 200
  files in a single SQLite transaction (one `BEGIN`/`COMMIT` per batch). Previously,
  each file triggered 2 commits (~72,600 commits for 36K files ≈ 5 hours at ~2 files/sec).
  Now ~220 files/sec on NAS (~3–5 min for 36K files).
  Falls back to per-file upserts on error (logged as `batch_upsert_fallback`).
- Re-exported through `core/db/__init__.py`.
- `core/bulk_scanner.py`: Consumer loop updated — batch size increased from 100 to 200,
  separates convertible vs. unrecognized files, calls `upsert_bulk_files_batch()` for
  convertible files.

---

## v0.19.2 — LLM Token Usage Tracking (2026-04-03)

**Token cost tracking for the image analysis queue:**
- New `tokens_used INTEGER` column on `analysis_queue` (migration 20).
- `VisionAdapter.describe_batch()`: Anthropic, OpenAI, and Gemini batch methods
  now extract token usage from API responses (previously discarded). Token count
  is distributed evenly per image in the batch and carried on `BatchImageResult`.
- `core/db/analysis.py`: `write_batch_results()` persists `tokens_used` per row.
  New `get_analysis_token_summary()` returns aggregate totals and per-model
  breakdowns (total files analyzed, total tokens, average tokens/file, grouped
  by provider + model).
- `core/analysis_worker.py`: passes `tokens_used` from vision results through to
  `write_batch_results()`.
- Tests: `test_token_summary` validates multi-model aggregation; existing test
  updated with `tokens_used` field.

**Why:** At 100K+ images, duplicate or untracked LLM calls have real monetary
cost. Token counts were already returned by every provider API but discarded at
the vision adapter layer. This change closes the loop so usage is auditable
from the DB without log parsing.

---

## v0.19.1 — Fix Concurrent Bulk Job Race Condition (2026-04-03)

**Bug fix — duplicate bulk jobs caused SQLite deadlock and permanent stall:**
- Two independent code paths could create bulk jobs simultaneously:
  (1) the backlog poller in `_run_deferred_conversions` and (2) the
  auto-conversion trigger in `_execute_auto_conversion` after lifecycle scan
  completion. Neither path checked whether the other had already started a job.
- Concurrent jobs scanning the same source path into `bulk_files` caused SQLite
  write contention. Both jobs stalled at ~85-90% of their scan phase and never
  transitioned from "scanning" to "running" — zero files were ever converted.
- The in-memory `get_all_active_jobs()` misreported scanning jobs as `"done"`
  because `_total_pending == 0` during the scan phase, allowing the guard in the
  backlog poller to pass when it should have blocked.

**Fixes applied:**
- `core/bulk_worker.py`: Added `_scanning` flag to `BulkJob.__init__()`, set to
  `True` during scan phase, cleared before transitioning to "running". Updated
  `get_all_active_jobs()` status derivation to return `"scanning"` when flag is set.
- `core/lifecycle_scanner.py`: Added concurrency guard to `_execute_auto_conversion()` —
  checks `get_all_active_jobs()` and refuses to create a new job if any existing
  job has status `scanning`, `running`, or `paused`.
- `core/scheduler.py`: Hardened the backlog poller guard with an explicit status
  filter on the in-memory check AND a DB-level fallback query against `bulk_jobs`
  to catch jobs that exist in the DB but not yet in memory.

---

## v0.19.0 — Decoupled Conversion Pipeline + Fast NAS Scanning (2026-04-03)

**Decoupled conversion from scan completion (producer-consumer pattern):**
- `core/scheduler.py`: `_run_deferred_conversions` now works in all modes
  (`immediate`, `queued`, `scheduled`), not just `scheduled`.
- Every 15 minutes, checks `bulk_files WHERE status='pending'`. If pending > 0
  and no active bulk job, creates a BulkJob and starts conversion immediately.
- Conversion no longer requires `on_scan_complete()` — scanner and converter
  run independently. Scanner produces work items, poller drains them.
- Fixes pipeline stall where 100K+ NAS files couldn't finish scanning within
  the 15-min interval, permanently blocking auto-conversion.

**Fast NAS detection in storage probe:**
- `core/storage_probe.py`: New `nas_fast` classification for network mounts
  with SSD-like latency (< 0.1ms, ratio < 2.0).
- Checks filesystem type via `stat -f -c %T` with `/proc/mounts` fallback
  to distinguish local SSD from CIFS/NFS/sshfs mounts.
- `nas_fast` gets 4 parallel scan threads (was 1 when misclassified as `ssd`).

**Scanner interval increased:**
- Default `scanner_interval_minutes` preference: 15 → 45 minutes.
- Scheduler hardcoded interval: 15 → 45 minutes.

---

## v0.18.1 — Bulk Upsert Race Condition Fix (2026-04-03)

**Bug fix — UNIQUE constraint race in `upsert_bulk_file()`:**
- `core/db/bulk.py`: Replaced SELECT-then-INSERT pattern with atomic
  `INSERT ... ON CONFLICT(job_id, source_path) DO UPDATE SET ...`.
- The old pattern checked for an existing row with SELECT, then INSERTed if not
  found. On rescans, previously-registered files caused `UNIQUE constraint failed:
  bulk_files.job_id, bulk_files.source_path` errors (286+ per scan cycle).
- The errors were caught per-file (scan continued), but the cumulative overhead of
  89K+ files on a NAS mount with per-file error handling prevented the scan from
  completing within the 15-minute scheduler interval.
- Since `on_scan_complete()` was never reached, auto-conversion was never triggered,
  leaving all files stuck at `pending_conversion` with 0 files converted or indexed.
- The atomic upsert preserves the same skip/pending logic via SQL CASE expressions:
  if `stored_mtime` matches the incoming `source_mtime`, status is set to `skipped`;
  otherwise status is reset to `pending` for re-conversion.

---

## v0.18.0 — Image Analysis Queue + Pipeline Stats (2026-04-02)

**Decoupled LLM vision analysis for standalone image files:**
- New `analysis_queue` table (migration 19): `pending -> batched -> completed | failed`.
- Bulk worker enqueues image files after successful conversion.
- Lifecycle scanner enqueues new and content-changed image files on discovery.
- New `core/analysis_worker.py` (APScheduler, 5-min interval): claims up to
  `analysis_batch_size` pending rows, marks them `batched`, calls
  `VisionAdapter.describe_batch()` (one API call for all), writes results, re-indexes.
- `VisionAdapter.describe_batch()`: single multi-image call for Anthropic, OpenAI,
  Gemini. Ollama falls back to sequential if model rejects multiple images.
- LLM description + extracted text appended to Meilisearch `content` field — image
  files are searchable by visual content.
- Retry: failed batches reset to `pending` up to 3 times, then permanently `failed`.
- New preferences: `analysis_enabled` (kill switch), `analysis_batch_size` (default 10).

**Pipeline funnel statistics:**
- `GET /api/pipeline/stats`: scanned, pending conversion, failed, unrecognized,
  pending analysis, batched for analysis, analysis failed, in search index.
- Status page: stat strip above job cards.
- Admin page: Pipeline Funnel stats card.

**Bug fix — lifecycle scanner auto-conversion (source_path kwarg):**
- `core/lifecycle_scanner.py:924` was calling `BulkJob(source_path=...)` but
  `BulkJob.__init__` expects `source_paths=` (plural). Every auto-conversion
  triggered by the lifecycle scanner was silently failing with
  `BulkJob.__init__() got an unexpected keyword argument 'source_path'` since
  approximately 2026-04-02T12:06. Fixed by correcting the kwarg name.

**Bug fix — stale GPU display:**
- `core/gpu_detector.py`: `_read_host_worker_report()` now checks `worker.lock`
  existence and timestamp age before trusting `worker_capabilities.json`.
  Stale workstation GPU (e.g. NVIDIA 1660 Ti from disconnected workstation) no
  longer displayed as the active GPU.
- `tools/markflow-hashcat-worker.py`: writes heartbeat timestamp every 2 minutes.

---

## v0.17.7 — Scan Priority Coordinator (2026-04-01)

**Scan priority hierarchy: Bulk Job > Run Now > Lifecycle Scan:**
- New `core/scan_coordinator.py` manages mutual exclusion between scan types
  using asyncio Events for cancel/pause signaling.
- **Bulk jobs** are highest priority: starting a bulk job cancels any active
  lifecycle scan (clean cancel, releases DB) and pauses any active run-now
  scan (resumes automatically when bulk completes).
- **Run-now** is mid priority: cancels lifecycle scans on start. If a bulk
  job is active, run-now pauses and waits for it to finish before proceeding.
- **Lifecycle scans** are lowest priority: never pause, only cancel. On
  cancellation, the scan finalizes with status "cancelled", skips deletion
  detection (incomplete seen_paths would incorrectly mark files as deleted),
  skips auto-conversion trigger, and picks up at the next scheduled interval.
- Lifecycle scanner walker loops (`_serial_lifecycle_walk`,
  `_parallel_lifecycle_walk`, `_walker_thread`) now check
  `is_lifecycle_cancelled()` alongside `should_stop()` at every file.
- `BulkJob.run()` calls `notify_bulk_started()` on entry and
  `notify_bulk_completed()` in `finally` block.
- New `/api/pipeline/coordinator` debug endpoint exposes coordinator state.
- Eliminates "database is locked" errors from concurrent lifecycle + bulk
  DB writes — lifecycle cleanly exits before bulk starts writing.

---

## v0.17.6 — Scheduler Yield Guards (2026-04-01)

**Scheduled jobs yield to bulk jobs:**
- Trash expiry, DB compaction, integrity check, and stale data check now all
  yield to active bulk jobs (matching the existing lifecycle scan pattern).
- Each job calls `get_all_active_jobs()` and returns early if any bulk job
  has status scanning/running/paused.
- Previously only the lifecycle scan checked for active jobs; trash moves
  during bulk scans caused "database is locked" errors.

---

## v0.17.5 — Scrollable Interactive Search Preview (2026-04-01)

- Preview popup body changed from `overflow: hidden` to `overflow: auto` —
  enables vertical and horizontal scrolling of preview content.
- Markdown preview changed from `overflow-y: auto` to `overflow: auto` —
  wide tables and code blocks now scroll horizontally.
- Re-applied v0.17.4 interactive preview + auto-dodge code that was overwritten
  by a concurrent git pull (pointer-events, idle timer, dodge transition).

---

## v0.17.4 — Interactive Search Preview with Auto-Dodge (2026-04-01)

**Interactive hover preview:**
- Search result hover preview popup is now interactive (`pointer-events: auto`).
- Users can scroll preview content, click the "Open" link to view in the document
  viewer, and interact with embedded iframes.
- After 2 seconds of mouse inactivity on the popup, it slides offscreen via CSS
  `transform: translateY(120vh)` with a smooth 0.3s ease transition ("dodge").
- If the mouse re-enters the dodged popup, it slides back and interaction resumes.
- Each period of 2 seconds idle triggers another dodge — the cycle repeats.
- 300ms grace period on row `mouseleave` prevents flicker when moving between the
  search result row and the preview popup.

**macOS deployment scripts:**
- New `Scripts/macos/` directory with `build-base.sh`, `reset-markflow.sh`, and
  `refresh-markflow.sh` for personal macOS machine.
- Hardcoded source/output paths for local development.
- `reset-markflow.sh` generates `.env` with hardware-tuned settings (worker count,
  Meilisearch memory) and macOS-compatible `DRIVE_C`/`DRIVE_D` variables.
- `.env` now includes `DRIVE_C` and `DRIVE_D` for macOS drive browser mounts
  (replaces Windows `C:/` and `D:/` defaults that caused container startup failure).

---

## v0.17.3 — Skip Reason Tracking & Startup Crash Fix (2026-04-01)

**Skip reason tracking:**
- New `skip_reason` column on `bulk_files` table (schema migration #18).
- Every file skip now records a human-readable reason:
  - **Path too long**: `"Output path too long (X chars, max Y)"`
  - **Output collision**: `"Output collision (skip strategy)"`
  - **OCR below threshold**: `"OCR confidence X% below threshold Y%"`
  - **Unchanged file**: `"Unchanged since last scan"`
- Path safety skips now properly update `bulk_files` status to `"skipped"` with
  counter increments (previously silently skipped with status left as `"pending"`).
- Job detail page displays skip reasons in amber text in the Details column,
  matching the existing `error_msg` pattern for failed files.

**Scheduled jobs yield to bulk jobs:**
- Trash expiry, DB compaction, integrity check, and stale data check now all
  yield to active bulk jobs (matching the existing lifecycle scan pattern).
  Previously only the lifecycle scan checked for active jobs; trash moves
  during bulk scans caused "database is locked" errors.

**Startup crash fix:**
- Fixed missing `Query` import in `api/routes/bulk.py` that caused a `NameError`
  on container startup, crash-looping the markflow service. The pending files
  endpoint (added in v0.17.2) used `Query()` for parameter validation without
  importing it from FastAPI.

---

## v0.17.2 — UI Layout Cleanup & Pending Files Viewer (2026-04-01)

- System Status health check moved from Convert page to Status page.
- Pending Files viewer on History page with live count, search, pagination,
  color-coded status badges.
- Convert page: Browse button for output directory, session-sticky path,
  Conversion Options section with disclaimer.

---

## v0.17.1 — Job Config Modal, Browse All, Auto-Convert Backlog Fix (2026-04-01)

**Job configuration modal:**
- "Start Job" now opens a configuration dialog before launching the job.
- Modal sections: **Conversion** (workers, fidelity, OCR mode, Adobe indexing),
  **Scan Options** (threads, collision strategy, max files), **OCR** (confidence
  threshold, unattended mode), **Password Recovery** (dictionary, brute-force,
  timeout, GPU acceleration).
- Each section shows global defaults with per-job override capability.
- API extended: `CreateBulkJobRequest` accepts optional override fields
  (`scan_max_threads`, `collision_strategy`, `max_files`, `ocr_confidence_threshold`,
  `unattended`, `password_*`). `BulkJob` stores overrides dict for downstream use.

**Search "Browse All":**
- New "Browse All" button on the Search page shows all indexed documents sorted
  by date when no query is entered.
- API `GET /api/search/all` now accepts empty queries (`q=""`) — Meilisearch
  natively supports empty-string queries returning all documents.
- Empty queries default to sort-by-date and skip highlighting.

**Auto-converter backlog fix:**
- The auto-converter previously only triggered on new/modified files from lifecycle
  scans. If a prior bulk job failed (e.g., due to the `_is_excluded` bug), the
  60K+ pending files were orphaned and never retried.
- New `_get_pending_backlog_count()` method checks `bulk_files` for pending rows
  when no new files are discovered. If backlog exists and no job is active,
  auto-conversion triggers to process it.

---

## v0.17.0 — Job Detail Page & Enhanced Viewer (2026-04-01)

**Job Detail page (industry-standard batch job monitoring):**
- Click any Job History row to open `/job-detail.html` with full job details.
- Summary header: status badge, job ID, source/output paths, timing (started/finished/duration).
- Cancellation/error reason banner — prominently displayed for cancelled/failed jobs.
- Stats bar: total/converted/failed/skipped/adobe counts with color-coded segmented progress bar.
- Three tabs: **Files** (paginated table with status filter chips + search), **Errors** (searchable
  list with expandable error details), **Info** (full job configuration).
- Re-run button starts a new job with identical settings.
- Error links in Job History now navigate to the Errors tab (were: broken raw JSON links).

**Cancellation reasons tracked:**
- New `cancellation_reason` column on `bulk_jobs` (migration #17).
- User cancel: "Cancelled by user". Error-rate abort: "Aborted: error rate X%...".
- Fatal exceptions: "Fatal error: ...". Container restart orphans: "Cancelled: container restarted...".

**Enhanced Document Viewer:**
- Three view modes: Source (iframe), Rendered (markdown via marked.js + DOMPurify), Raw (line numbers).
- In-document search: Ctrl+F opens search bar, highlights matches, navigate with arrows/Enter.
- Word wrap toggle for raw view. Copy to clipboard button. Sticky toolbar.

**Search preview upgrade:**
- Preview popup now renders markdown (was: raw text truncated at 2000 chars).
- Uses marked.js + DOMPurify for safe HTML rendering, shows up to 5000 chars.
- "Open" link in preview header opens the full viewer page.
- Proper CSS for tables, code blocks, and headings in preview popup.

**Bug fix — Scanner `_is_excluded` scope error:**
- `_is_excluded()` was a local function in `run_scan()` but referenced in `_walker_thread()`
  inside `_parallel_scan()` — a separate method. Closures don't cross method boundaries.
  All worker threads crashed with `NameError`, causing every scan to find 0 files.
- Fix: moved to `BulkScanner._is_excluded()` class method.

**Other:**
- Job History rows: clickable with hover effect, show start time + finish time + duration.
- Locations page: "Close & return to Bulk Jobs" link when opened from Manage link.
- Job History timestamps: added "Started" / "Finished" labels and computed duration display.

---

## v0.16.9 — Multi-Source Scanning (2026-04-01)

**All source locations scanned in a single run:**
- Lifecycle scanner now resolves all configured source locations (was: first only).
  Validates each root, skips inaccessible ones, walks the rest sequentially within
  the same scan run. Shared counters, `seen_paths`, and error tracking accumulate
  across roots. Each root gets its own storage probe (different mounts may be
  different hardware types).
- Bulk jobs accept `scan_all_sources: bool` in the API request. `BulkJob` accepts
  `source_paths: list[Path]` and loops the scanning phase, merging `ScanResult`
  fields. Workers convert the combined file queue as one batch — same job ID,
  same worker pool, same DB pipeline.
- New "Scan all source locations" checkbox on the Bulk Jobs page. When checked,
  disables the source dropdown and sends the flag. One job, one queue.
- All existing settings (throttling, error-rate abort, exclusions, pipeline
  controls, stop/cancel) apply per-root as before. No new settings needed.

---

## v0.16.8 — Job History Cleanup (2026-04-01)

**Job History readability improvements (Bulk page):**
- Timestamps now use `formatLocalTime()` — displays as "Apr 1, 2026, 3:13 PM"
  instead of raw ISO strings like `2026-04-01T15:13:45.077192+00:00`.
- Status labels title-cased: "Completed" instead of "COMPLETED".
- Stats show "X of Y converted" when total file count is available.
- Exclusion count now shown in Settings page Locations summary card
  (e.g. "3 locations: 2 source · 1 output · 1 exclusion").

---

## v0.16.7 — Collapsible Settings Sections (2026-04-01)

**Settings page UX cleanup:**
- All 16 settings sections wrapped in native `<details>/<summary>` collapsible elements.
- Only Locations and Conversion sections open by default; all others start collapsed.
- "Expand All / Collapse All" toggle button in the page header.
- Animated chevron (right-pointing triangle rotates 90 degrees on open).
- Smooth slide-down animation when opening a section.
- Uses semantic HTML — no JavaScript for open/close behavior.

---

## v0.16.6 — Location Exclusions (2026-04-01)

**Path exclusion for scanning:**
- New "Exclude Location" feature on the Locations page.
- Exclusions use prefix matching — excluding `/host/c/Archive` skips all files and
  subdirectories under that path during both bulk and lifecycle scans.
- New `location_exclusions` DB table with full CRUD.
- API endpoints: `GET/POST /api/locations/exclusions`, `GET/PUT/DELETE /api/locations/exclusions/{id}`.
- Both `BulkScanner` and lifecycle scanner load exclusion paths once at scan start.
- Filtering at the `os.walk()` level: excluded directories are pruned from `dirnames[:]`
  so Python never descends into them. File-level check as safety net.
- Fast walk counter (file count estimator) also respects exclusions.
- UI mirrors the existing Add Location form: name, path, notes, Browse, Check Access,
  inline edit/delete with confirmation.

---

## v0.16.5 — Activity Log Pagination (2026-04-01)

**Activity log UX improvements (Resources page):**
- Per-page buttons (10/30/50/100/All) matching search page pattern for consistency.
- Fixed-height scrollable container (600px max) with sticky table header.
- Default reduced from 100 to 10 rows to keep page manageable.
- "Showing X of Y events" count summary below table.
- "All" sends limit=500 (API max).

---

## v0.16.4 — Filename Search Normalization (2026-04-01)

**Filename-aware search matching:**
- New `filename_search` field added to all three Meilisearch indexes (documents,
  adobe-files, transcripts). Populated at index time by `normalize_filename_for_search()`.
- Normalizer splits filenames on:
  - Explicit separators: `_`, `.`, `-`
  - camelCase/PascalCase boundaries: `getUserName` -> `get User Name`
  - Letter/number transitions: `Resume2024` -> `Resume 2024`
- File extensions stripped before normalization (`.pdf`, `.docx`, etc.)
- Original `source_filename` preserved for display; `filename_search` is a shadow
  field used only for matching.
- Requires index rebuild after deploy to backfill existing documents.

**Rebuild Index button:**
- Added "Rebuild Index" button to Bulk page pipeline controls (between Pause and Run Now).
- Triggers `POST /api/search/index/rebuild` with toast confirmation.
- Button disables for 5 seconds to prevent double-clicks.

---

## v0.16.3 — Search Hover Preview (2026-04-01)

**Search result hover preview:**
- Hovering over a search result shows a preview popup of the file content after a
  configurable delay (default 400ms). Smart hybrid strategy selects the best preview:
  - **Inline-able files** (PDF, images, text, HTML, CSV) — rendered in a sandboxed iframe
    via the existing `/api/search/source/` endpoint
  - **Other converted files** — first 2000 characters of the converted markdown shown as
    plain text via `/api/search/view/`
  - **No preview available** — displays "Cannot render preview" message
- Preview popup positioned to the right of the hovered result, flips left when near
  viewport edge, clamped to stay on screen.
- Client-side doc-info cache avoids redundant API calls on repeated hovers.
- Three new user preferences (Settings > Search Preview):
  - `preview_enabled` — toggle on/off (default: on)
  - `preview_size` — small (320x240), medium (480x360), large (640x480)
  - `preview_delay_ms` — hover delay before popup appears (100-2000ms, default: 400)

---

## v0.16.2 — Streamlining Audit Complete + Search UX Fix (2026-04-01)

**Search viewer back-button fix:**
- Viewer pages (opened in new tabs from search results) now close the tab on back-button
  press or "Back to Search" click, returning focus to the search results page. Falls back
  to navigation if `window.close()` is blocked by the browser.

**Final 3 streamlining items resolved (24/24 complete):**
- **STR-05: database.py module split** — 2,300-line monolith split into `core/db/` package
  with 8 domain modules: `connection.py` (path, get_db, helpers), `schema.py` (DDL, migrations,
  init_db), `preferences.py`, `bulk.py` (jobs + files + source files), `conversions.py`
  (history, batch state, OCR, review queue), `catalog.py` (adobe, locations, LLM providers,
  unrecognized, archives), `lifecycle.py` (lifecycle queries, versions, path issues, scans,
  maintenance), `auth.py` (API keys). `core/database.py` remains as a backward-compatible
  re-export wrapper — all 40+ external import sites unchanged.
- **STR-13: upsert_source_file UPSERT** — converted from SELECT-then-INSERT/UPDATE to
  `INSERT ... ON CONFLICT(source_path) DO UPDATE SET ...`. Dynamic `**extra_fields` handled
  in both insert columns and conflict-update clause. Single atomic statement replaces two
  separate connection opens.
- **STR-17: Schema migration table** — new `schema_migrations` table replaces 40+
  `_add_column_if_missing()` calls (each doing `PRAGMA table_info()`). 16 versioned migration
  batches covering all historical ALTER TABLE additions. On startup: check one table, skip
  all applied migrations. First run on existing DBs: applies all (no-ops), records them.
  Subsequent startups: zero schema introspection queries.

---

## v0.16.1 — Code Streamlining + Security/Quality Audit (2026-04-01)

**Code quality (21 of 24 items resolved):**
- **Shared ODF utils** — new `formats/odf_utils.py` with `extract_odf_fonts()` and `get_odf_text()`.
  Replaces 3 near-identical implementations across odt/ods/odp handlers.
- **ALLOWED_EXTENSIONS from registry** — `converter.py` now derives upload extensions from the
  handler registry (`list_supported_extensions()`), auto-syncing when new formats are added.
- **`db_write_with_retry()` exported** — moved from private `bulk_worker.py` function to
  public `database.py` export. Available to all concurrent DB writers.
- **`now_iso()` consolidated** — single source in `database.py`, removed 3 duplicate definitions
  in lifecycle_scanner, metadata, and bulk routes.
- **`verify_source_mount()` shared** — renamed from `_verify_source_mount` in bulk_scanner,
  imported by lifecycle_scanner (replaced inline duplicate).
- **Singleton indexer enforced** — `flag_manager.py` now uses `get_search_indexer()` instead of
  `SearchIndexer()` direct instantiation.
- **Hoisted deferred imports** — `asyncio` in lifecycle_scanner (4 sites), `get_preference` in
  scheduler (5 sites), `record_activity_event` in 6 files.
- **`upsert_adobe_index`** — converted to `INSERT ... ON CONFLICT DO UPDATE` (single DB call).
- **`_count_by_status()` helper** — shared GROUP BY status reduce logic in database.py.
- **Removed legacy `formatDate()`** — all callers migrated to `formatLocalTime()`.
- **`_throwOnError()` helper** — deduplicated 4-copy API error extraction in app.js. `err.data`
  now consistently available on all error methods.
- **Dead code cleanup** — removed unused `aiosqlite` imports (auto_converter, auto_metrics_aggregator),
  redundant `_log` in database.py, inline `import os` in flag_manager.
- **Logger naming** — renamed `logger` to `log` in auto_converter and auto_metrics_aggregator.

**Deferred to future sessions:**
- STR-05: Split `database.py` into domain modules (1,800+ lines, 40+ importers)
- STR-17: Replace `_add_column_if_missing` chain with schema migration table

**Audit documentation:**
- `docs/security-audit.md` — 62 findings (10 critical, 18 high, 22 medium, 12 low/info)
- `docs/streamlining-audit.md` — 24 findings with resolution status

---

## v0.16.0 — File Flagging & Content Moderation (2026-04-01)

**New features:**
- **Self-service file flagging** — Any authenticated user can flag a file from search results,
  temporarily suppressing it from search and download. Flag includes a reason and configurable
  expiry (default from `flag_default_expiry_days` preference).
- **Admin triage page** — Dedicated admin page (`flagged.html`) with three-action escalation:
  dismiss (restore file to search), extend (keep suppressed longer), or remove (permanent
  blocklist). Filters by status, sort by date/filename, pagination.
- **Blocklist enforcement** — `blocklisted_files` table stores permanently removed files by
  content hash and source path. Scanner checks both during indexing — prevents re-indexing of
  removed files even if they reappear or are copied elsewhere.
- **Meilisearch `is_flagged` attribute** — Filterable attribute added to all 3 indexes
  (documents, adobe-files, transcripts). Search endpoint filters out flagged files by default;
  admins can override with `?include_flagged=true`.
- **Webhook notifications** — All flag events (create, dismiss, extend, remove) send webhook
  POST to `flag_webhook_url` preference if configured.
- **Hourly auto-expiry** — Scheduler job expires active flags past their `expires_at` timestamp.
- **File size fix** — Search results now show original source file size from `source_files`
  table instead of markdown output size.
- **New preferences**: `flag_webhook_url` (default empty), `flag_default_expiry_days` (default `7`).

**New files:**
- `core/flag_manager.py` — flag business logic, blocklist checks, Meilisearch is_flagged sync, webhooks
- `api/routes/flags.py` — flag API: user flagging + admin triage (dismiss/extend/remove/blocklist)
- `static/flagged.html` — admin flagged files page with filters, sort, pagination

**Modified files:**
- `core/database.py` — `file_flags` and `blocklisted_files` table schemas, flag preference defaults
- `core/search_indexer.py` — sets `is_flagged` attribute during indexing, checks `file_flags` table
- `core/search_client.py` — `is_flagged` added to filterable attributes for all indexes
- `core/bulk_scanner.py` — blocklist check during scan (skips blocklisted files)
- `core/scheduler.py` — hourly flag expiry job
- `api/routes/search.py` — flag filtering in search results, access blocking for flagged files
- `static/search.html` — flag button on search results, flag modal
- `static/admin.html` — flagged files KPI card, nav entry
- `static/settings.html` — flag preferences section
- `static/app.js` — nav entry for flagged files page
- `main.py` — mount flags router
- `core/version.py` — bumped to 0.16.0

**Design notes:**
- Multiple flags can exist per file. The file stays hidden while ANY flag has `status` in
  (`active`, `extended`). `is_flagged` is only set to `false` when the last active/extended
  flag resolves or expires.
- Flag state survives Meilisearch index rebuilds — `search_indexer.py` checks `file_flags`
  during re-indexing and sets `is_flagged=true` for any file with an active/extended flag.
- Blocklist uses dual-match: both `content_hash` (catches copies) and `source_path` (catches
  re-appearances at the same location). A file matches if either field matches a blocklist entry.
- Fixed-path routes (`/mine`, `/stats`, `/blocklist`, `/lookup-source`) are defined before the
  `/{flag_id}` catch-all in `flags.py` to prevent FastAPI from matching literal paths as flag IDs.

---

## v0.15.1 — Cloud File Prefetch (2026-03-31)

**New features:**
- **CloudDetector** — Platform-agnostic detection of cloud placeholder files. Probes via disk block
  allocation (`st_blocks == 0`) and a timed read-latency test. Covers OneDrive, Google Drive,
  Nextcloud, Dropbox, iCloud, and NAS tiered storage. Configurable via `cloud_prefetch_probe_all`
  to force-probe all files regardless of block count.
- **PrefetchManager** — Background worker pool that materializes cloud placeholders before
  conversion. Features: configurable concurrency, per-minute token-bucket rate limiting, adaptive
  per-file timeouts, retry with exponential backoff, and backpressure via queue size cap.
- **Scanner integration** — `bulk_scanner.py` and `lifecycle_scanner.py` enqueue detected
  placeholder files to the prefetch queue during scan, so prefetch runs ahead of conversion.
- **Converter integration** — `converter.py` waits for in-flight prefetch before opening a file.
  Falls back to inline prefetch if the file was never queued (still works, just slower).
- **Health check** — Prefetch stats (queue depth, active workers, completion rate) added to
  `/api/health` response.
- **Settings page** — New Cloud Prefetch section with all preference controls.
- **New preferences**: `cloud_prefetch_enabled` (default `true`),
  `cloud_prefetch_concurrency` (default `4`), `cloud_prefetch_rate_limit` (requests/min, default `60`),
  `cloud_prefetch_timeout_seconds` (default `120`), `cloud_prefetch_min_size_bytes` (default `0`),
  `cloud_prefetch_probe_all` (default `false`).

**New files:**
- `core/cloud_detector.py` — placeholder detection via st_blocks + read latency
- `core/cloud_prefetch.py` — background prefetch worker pool

**Modified files:**
- `core/bulk_scanner.py` — enqueue files for prefetch during scan
- `core/lifecycle_scanner.py` — enqueue files for prefetch during lifecycle scan
- `core/converter.py` — wait for prefetch before reading file; inline prefetch fallback
- `core/health.py` — prefetch stats in health response
- `core/database.py` — cloud prefetch preference defaults
- `static/settings.html` — Cloud Prefetch settings section
- `core/version.py` — bumped to 0.15.1

**Design notes:**
- Prefetch is purely additive — disabling `cloud_prefetch_enabled` restores original behavior
  exactly. No code paths change; the wait in converter.py short-circuits immediately.
- Prefetch state is ephemeral — the queue and worker pool are in-memory only. Container restart
  clears all state; the next scan re-enqueues any remaining placeholders.
- Rate limit tokens refill per minute, not per second. Expect bursty traffic at startup when
  many placeholders are discovered at once; the token bucket smooths sustained throughput.
- `st_blocks == 0` is a reliable placeholder signal on most FUSE-based cloud mounts, but some
  mount types do not populate `st_blocks` correctly. The timed read-latency probe is the fallback
  for those cases.
- Inline prefetch in converter.py covers files that were not pre-queued (e.g., single-file
  uploads, or files discovered after the queue was already drained). It is slower than pre-queued
  prefetch because it blocks the conversion worker, but it is never a correctness failure.

---

## v0.15.0 — Search UX Overhaul + Enterprise Scanner Robustness (2026-03-31)

**New features:**
- **Unified search** — New `/api/search/all` endpoint searches all 3 Meilisearch indexes
  (documents, adobe-files, transcripts) concurrently and merges results. Faceted format filtering
  with clickable chips. Sort by relevance/date/size/format.
- **Document viewer** — New `static/viewer.html` page. Click a search result to view the original
  source file (PDF inline, other formats show fallback). Toggle between Source and Markdown views.
  Download button.
- **Source file serving** — New endpoints: `/api/search/source/{index}/{doc_id}` (view original),
  `/api/search/download/{index}/{doc_id}` (download original),
  `/api/search/doc-info/{index}/{doc_id}` (metadata for viewer).
- **Batch download** — `POST /api/search/batch-download` accepts a list of doc IDs, creates a ZIP
  of original source files. Multi-select checkboxes on search results.
- **Search UX improvements** — Per-page buttons (10/30/50/100), fixed autocomplete (was broken due
  to competing input handlers), local time display instead of UTC, middle-click opens viewer in
  new tab.
- **Source path in search index** — `search_indexer.py` now looks up `source_path` from the
  `source_files` DB table when frontmatter doesn't have it.
- **AD-credentialed folder handling** — All `os.walk()` calls in `bulk_scanner.py`,
  `lifecycle_scanner.py`, and `storage_probe.py` now use `onerror` callbacks that log
  `scan_permission_denied` with an AD hint instead of silently skipping.
- **Enterprise scanner robustness** — FileNotFoundError handling (AV quarantine), NTFS ADS
  filtering (skip files with `:` in name), stale SMB connection retry, explicit PermissionError
  logging.
- **Global `formatLocalTime()`** — Added to `app.js` for consistent local time display across all
  pages.

**New files:**
- `static/viewer.html` — document viewer page

**Modified files:**
- `api/routes/search.py` — all new endpoints (unified search, source file serving, batch download)
- `static/search.html` — complete UX redesign (format chips, per-page, multi-select, viewer links)
- `static/app.js` — `formatLocalTime()` helper
- `core/search_indexer.py` — source_path DB lookup, source_format made sortable
- `core/bulk_scanner.py` — AD/permission/ADS/quarantine handling on all walks
- `core/lifecycle_scanner.py` — AD/permission handling on all walks
- `core/storage_probe.py` — permission handling on probe walk
- `core/version.py` — bumped to 0.15.0

**Design notes:**
- Unified search merges results from all 3 indexes in a single response, deduplicating by source
  path where applicable. Each result carries its index origin for viewer routing.
- Source file serving resolves the original file path from the Meilisearch document's `source_path`
  field, with a DB fallback for older entries that predate the frontmatter change.
- AD-credentialed folders are common on enterprise file servers. The `onerror` callback pattern
  ensures nothing is silently skipped — operators see exactly which folders need ACL adjustments.
- NTFS Alternate Data Streams (files with `:` in the name) are metadata, not user files. Skipping
  them prevents confusing errors downstream.

---

## v0.14.1 — Health-Gated Startup + Pipeline Watchdog (2026-03-31)

**New features:**
- **Health-gated startup** — `core/pipeline_startup.py` replaces the old immediate force-scan at
  boot. On startup, the pipeline waits the configured delay (`pipeline_startup_delay_minutes`,
  default 5), then polls health checks before triggering the first scan+convert cycle. Critical
  services (DB, disk) must pass; preferred services (Meilisearch, Tesseract, LibreOffice) produce
  warnings but do not block. Max additional wait: 3 minutes of retries.
- **Pipeline watchdog** — `_pipeline_watchdog()` in `scheduler.py` runs hourly when the pipeline is
  disabled. Logs WARN every hour and ERROR every 24h. After `pipeline_auto_reset_days` (default 3),
  it auto-re-enables the pipeline and clears `pipeline_disabled_at`.
- **`disabled_info` in pipeline status API** — `GET /api/pipeline/status` now includes
  `disabled_info` with the disabled timestamp and auto-reset countdown (days/hours remaining).
- **Disabled warning banner on Bulk page** — `static/bulk.html` shows a dismissible banner when the
  pipeline is disabled, including the auto-reset countdown.
- New preferences: `pipeline_startup_delay_minutes` (default 5), `pipeline_auto_reset_days`
  (default 3), `pipeline_disabled_at` (auto-set timestamp when pipeline is disabled).

**Modified files:**
- `core/pipeline_startup.py` — new file: health-gated startup task
- `core/scheduler.py` — `_pipeline_watchdog()` job, sets/clears `pipeline_disabled_at`
- `core/database.py` — added `pipeline_startup_delay_minutes`, `pipeline_auto_reset_days`,
  `pipeline_disabled_at` default preferences
- `api/routes/pipeline.py` — `disabled_info` field in status response
- `main.py` — launch `pipeline_startup.py` background task instead of immediate force-scan
- `static/bulk.html` — disabled warning banner with auto-reset countdown
- `static/settings.html` — pipeline startup delay and auto-reset days inputs
- `core/version.py` — bumped to 0.14.1

**Design notes:**
- Startup delay prevents race conditions where the first scan fires before NAS mounts or
  Meilisearch finishes initializing.
- Watchdog auto-reset is a self-healing safeguard — if an operator accidentally disables the
  pipeline and forgets, it recovers automatically after N days without manual intervention.
- `pipeline_disabled_at` is set by the disable/pause path and cleared on re-enable; the watchdog
  reads it to compute the auto-reset deadline.

---

## v0.14.0 — Automated Conversion Pipeline (2026-03-31)

**New features:**
- **Pipeline control system** — the lifecycle scanner is now the sole trigger for conversion. When it
  detects new or changed files, it automatically spins up bulk conversion. No manual scan/convert
  triggers needed.
- `pipeline_enabled` preference — master on/off for the entire scan+convert pipeline (default: true)
- `pipeline_max_files_per_run` preference — cap on files converted per pipeline cycle (default: 0 = unlimited)
- Pipeline API endpoints: `GET /api/pipeline/status`, `POST /api/pipeline/pause`, `POST /api/pipeline/resume`, `POST /api/pipeline/run-now`
- Pipeline status card on Bulk Conversion page — shows mode, last/next scan, pending files, pause/resume/run-now controls
- Pipeline settings section on Settings page — master toggle and per-cycle file cap

**Modified files:**
- `core/database.py` — added `pipeline_enabled` and `pipeline_max_files_per_run` default preferences
- `core/scheduler.py` — pipeline master gate (checks `pipeline_enabled` and `_pipeline_paused`), `get_pipeline_status()`, `set_pipeline_paused()`/`is_pipeline_paused()` functions
- `core/lifecycle_scanner.py` — `_execute_auto_conversion()` now applies `pipeline_max_files_per_run` cap
- `api/routes/pipeline.py` — new router: status, pause, resume, run-now endpoints
- `main.py` — register pipeline router
- `static/bulk.html` — pipeline status card with live refresh
- `static/settings.html` — pipeline settings section with toggle and max files input
- `core/version.py` — bumped to 0.14.0

**Design notes:**
- Two layers of control: `pipeline_enabled` (persistent DB preference, survives restarts) and `_pipeline_paused` (in-memory, resets on restart)
- "Run Now" bypasses both pause and business hours via `force=True`
- Existing bulk job API endpoints are preserved for backward compatibility
- Auto-conversion engine continues to handle worker count, batch size, and scheduling decisions

---

## v0.13.9 — Source Files Dedup + Image/Format Support (2026-03-31)

**New features:**
- **Global file registry (`source_files` table)** — eliminates cross-job row duplication in `bulk_files`.
  `source_files` holds one row per unique `source_path` with all file-intrinsic data. `bulk_files`
  retains per-job data and links via `source_file_id` FK. Existing data auto-migrated on startup.
- Image files (.jpg, .jpeg, .png, .tif, .tiff, .bmp, .gif, .eps) via ImageHandler
- `.docm` (macro-enabled Word) and `.wpd` (WordPerfect) via DocxHandler + LibreOffice
- `.ait` / `.indt` (Adobe templates) via AdobeHandler
- All previously unrecognized file types now have handlers

**Modified files:**
- `core/database.py` — source_files CREATE TABLE, migration, upsert_source_file, query helpers
- `core/lifecycle_manager.py` — lifecycle transitions update source_files alongside bulk_files
- `core/lifecycle_scanner.py` — deletion/move detection queries source_files
- `core/bulk_worker.py` — propagates file-intrinsic data to source_files after conversion
- `core/bulk_scanner.py` — propagates MIME classification to source_files
- `core/scheduler.py` — trash expiry uses source_files pending functions
- `core/db_maintenance.py` — integrity checks use source_files
- `core/search_indexer.py` — reindex joins source_files for dedup
- `api/routes/admin.py` — cross-job stats query source_files
- `api/routes/trash.py` — trash view queries source_files
- `mcp_server/tools.py` — file lookup uses source_files
- `formats/image_handler.py` — new ImageHandler
- `formats/docx_handler.py` — added .docm, .wpd extensions
- `formats/adobe_handler.py` — added .ait, .indt extensions

**Design notes:**
- source_files UNIQUE(source_path) prevents duplication regardless of scan job count
- Migration is idempotent — safe to run multiple times
- Admin stats response includes both old keys (by_status, unrecognized_by_category) and new keys (by_lifecycle, by_category) for frontend backward compatibility

---

## v0.13.8 — Image File Support (2026-03-31)

NOTE: Superseded by v0.13.9 which includes all v0.13.8 features plus dedup.

## Previous v0.13.8 — Image File Support (2026-03-31)

**New features:**
- Image files (.jpg, .jpeg, .png, .tif, .tiff, .bmp, .gif, .eps) now supported via `ImageHandler`
- Extracts image metadata (dimensions, color mode, EXIF data) using Pillow and exiftool
- Produces a DocumentModel with metadata summary, embedded IMAGE element, and EXIF details
- Previously the largest group of unrecognized files (~7,347 images) — now handled natively

**Modified files:**
- `formats/image_handler.py` — new handler: ingest extracts metadata + embeds image, export writes Markdown
- `formats/__init__.py` — register ImageHandler import
- `core/bulk_scanner.py` — add image extensions to SUPPORTED_EXTENSIONS

**Design notes:**
- Follows AdobeHandler pattern: ingest extracts metadata, export writes Markdown (can't author binary images from text)
- Uses Pillow (already in requirements.txt) for dimensions/color mode/EXIF
- Uses exiftool (already in Dockerfile.base) for extended metadata (same subprocess pattern as AdobeHandler)
- No new dependencies required
- EPS support via Pillow's GhostScript integration (if GhostScript is installed)
- `.docm` (macro-enabled Word) now handled by DocxHandler via LibreOffice preprocessing
- `.wpd` (WordPerfect) now handled by DocxHandler via LibreOffice preprocessing
- `.ait` / `.indt` (Adobe Illustrator/InDesign templates) now handled by AdobeHandler
- All previously unrecognized file types now have handlers

---

## v0.13.7 — Legacy Office Format Support + Scheduler Fix (2026-03-31)

**New features:**
- `.xls` files now convert to Markdown via LibreOffice → openpyxl pipeline (same as `.xlsx`)
- `.ppt` files now convert to Markdown via LibreOffice → python-pptx pipeline (same as `.pptx`)
- Shared `core/libreoffice_helper.py` extracts the LibreOffice headless conversion logic used by all three legacy format handlers (`.doc`, `.xls`, `.ppt`)
- Lifecycle scan now yields to active bulk jobs — skips entirely if any bulk job is scanning/running/paused, preventing SQLite lock contention

**Modified files:**
- `core/libreoffice_helper.py` — new shared helper: `convert_with_libreoffice(source, target_format, timeout)`
- `formats/xlsx_handler.py` — EXTENSIONS now includes "xls"; ingest + extract_styles preprocess via LibreOffice
- `formats/pptx_handler.py` — EXTENSIONS now includes "ppt"; ingest + extract_styles preprocess via LibreOffice
- `formats/docx_handler.py` — `_doc_to_docx()` now delegates to shared helper
- `core/scheduler.py` — `run_lifecycle_scan()` checks `get_all_active_jobs()` before proceeding

**Design notes:**
- Same pattern as existing `.doc` → `.docx` preprocessing in DocxHandler
- Temp files cleaned in `finally` blocks to avoid disk leaks on conversion errors
- Default timeout increased to 120s (legacy files can be larger/slower to convert)
- Bulk scanner already had `.xls` and `.ppt` in `SUPPORTED_EXTENSIONS` — files were being scanned but failing with "No handler registered"
- Lifecycle scan guard: checks in-memory `_active_jobs` registry (not DB) — zero overhead, instant check. Deferred conversion runner inherits the guard since it calls `run_lifecycle_scan()` internally
- Root cause of "database is locked" errors: lifecycle scan (every 15 min) + metrics collector (every 2 min) + bulk workers all competing for SQLite. The lifecycle scan was the heaviest contender — scanning the entire source directory while bulk conversion was already doing the same

**Known issues identified (not yet fixed):**
- `bulk_files` table keyed by `(job_id, source_path)` — each new scan job inserts duplicate rows for the same files. 12,847 distinct source paths → 34K+ rows across 5 jobs. Per-job counts correct, but DB grows unbounded with repeated scans
- 4,237 unrecognized files in source repo: mostly images (.jpg 4211, .png 1349, .tif/.tiff 787, .eps 714, .gif 211), plus .wpd (WordPerfect, 277), .docm (20), .ait/.indt (Adobe templates, 115)
- LLM providers configured but not yet verified: Anthropic (529 overload, transient), OpenAI (429 rate limit, likely billing/quota)

---

## v0.13.6 — ErrorRateMonitor Across All I/O Subsystems (2026-03-31)

**New features:**
- Meilisearch `rebuild_index()`: aborts early if search service unreachable (50% error rate in last 50 ops)
- Cloud transcriber: session-level monitor disables cloud fallback after repeated API failures (60% rate in last 20 calls)
- EML/MSG handler: attachment processing aborts if conversion failures cascade (50% rate in last 20 attachments)
- Archive password cracking: distinguishes I/O errors (OSError = file unreadable) from wrong-password exceptions, aborts only on I/O failures (95% threshold — most attempts are expected to fail)

**Modified files:**
- `core/search_indexer.py` — `rebuild_index()` uses ErrorRateMonitor
- `core/cloud_transcriber.py` — session-level `_cloud_error_monitor` with fast-fail
- `formats/eml_handler.py` — both `_process_attachments_eml()` and `_process_attachments_msg()`
- `formats/archive_handler.py` — `_find_password()` with I/O-specific error detection

**Design notes:**
- Cloud transcriber monitor is session-scoped (module-level singleton) — persists across files. Once cloud APIs are known-bad, skip immediately for all subsequent transcriptions
- Password cracking monitor uses 95% threshold because wrong-password exceptions are normal. Only triggers on actual I/O failures (OSError, IOError)
- EML/MSG monitors are per-email — each email gets a fresh monitor since attachments are independent

---

## v0.13.5 — Archive Handler Optimization (2026-03-31)

**New features:**
- Batch extraction: `extractall()` for zip/tar/7z/rar/cab — one archive open/read cycle instead of N per-member cycles. Massive speedup over NAS (one network read vs hundreds)
- Parallel inner-file conversion: after batch extraction, inner files converted via ThreadPoolExecutor (up to 8 threads, capped to CPU count)
- ISO batch extraction: single `PyCdlib.open()` for all members instead of open/close per member
- ErrorRateMonitor integrated: aborts archive processing gracefully if error rate spikes (NAS disconnect mid-extraction), cleans up temp directory
- Nested archives processed sequentially after parallel files (recursive depth tracking requires serial)
- Summary line now shows extraction mode (batch/per-member) and thread count used
- Batch extraction falls back to per-member if `extractall()` fails (e.g., corrupted member)

**Modified files:**
- `formats/archive_handler.py` — batch extraction functions, parallel conversion, error-rate abort

**Design notes:**
- Batch vs per-member: batch is always tried first. If it fails (corrupted archive, partial password protection), falls back to the original per-member path
- Thread count for conversion: `min(file_count, cpu_count, 8)` — conversion is CPU-bound, not I/O-bound (files are already on local temp dir)
- Nested archives are NOT parallelized — each recursive call modifies the shared `ExtractionTracker` (quine detection, total size tracking)
- Temp dir cleanup in `finally` block is preserved — even on error-rate abort, temp dir is always removed

---

## v0.13.4 — OCR Quality Dashboard & Scan Throttle History (2026-03-31)

**New features:**
- Resources page: OCR Quality section with avg/min/max confidence KPIs, color-coded gauge, confidence timeline chart, distribution histogram bar chart
- Resources page: Scan Throttle History section with adjustment events table and scan summary cards
- Throttle adjustment events persisted to `activity_events` table (event types: `scan_throttle`, `scan_throttle_summary`)
- New API: `GET /api/resources/ocr-quality?range=30d` — returns confidence stats, distribution buckets, daily timeline
- New API: `GET /api/resources/scan-throttle?range=7d` — returns throttle adjustments and scan summaries

**Modified files:**
- `api/routes/resources.py` — added 2 new endpoints
- `static/resources.html` — added 2 new sections with Chart.js rendering
- `core/bulk_scanner.py` — added `_persist_throttle_events()` helper
- `core/lifecycle_scanner.py` — calls `_persist_throttle_events()` after parallel walk
- `core/storage_probe.py` — added `adjustments` property to `ScanThrottler`

---

## v0.13.3 — Error-Rate Monitoring & Abort (2026-03-31)

**New features:**
- `ErrorRateMonitor` class: rolling-window success/failure tracking with configurable thresholds
- Abort triggers: >50% error rate in last 100 operations, or 20 consecutive errors
- Integrated into all scanning paths: bulk serial, bulk parallel, lifecycle serial, lifecycle parallel
- Integrated into bulk conversion workers: if conversion failure rate spikes, job auto-cancels
- SSE events: `scan_aborted` (scanners), `job_error_rate_abort` (workers)
- Once triggered, abort is sticky — prevents restart-and-fail loops within same job

**Modified files:**
- `core/storage_probe.py` — added `ErrorRateMonitor` class
- `core/bulk_scanner.py` — both `_serial_scan()` and `_parallel_scan()` use error monitoring
- `core/lifecycle_scanner.py` — both serial and parallel walks use error monitoring
- `core/bulk_worker.py` — `_worker()` checks error rate before each file, records success/failure

**Design notes:**
- 20-consecutive-error fast path catches mount failures instantly (no need to wait for 100 ops)
- Rolling window (deque) bounds memory regardless of scan size
- `should_abort()` is idempotent — once triggered, always returns True (no flapping)
- Walker threads check `error_monitor.should_abort()` alongside `should_stop()` via `_should_bail()`

---

## v0.13.2 — Feedback-Loop Scan Throttling (2026-03-31)

**New features:**
- `ScanThrottler` class provides TCP-style congestion control for parallel scan workers
- Workers report stat() latency in real-time; throttler parks/unparks threads dynamically
- If NAS latency exceeds 3x baseline: shed 2 threads. 2x baseline: shed 1. Below 1.5x: restore 1
- 5-second cooldown between adjustments prevents oscillation
- Both bulk scanner and lifecycle scanner use throttled parallel scanning
- Completion logs show `threads_initial`, `threads_final`, and `throttle_adjustments` counts

**Modified files:**
- `core/storage_probe.py` — added `ScanThrottler` class
- `core/bulk_scanner.py` — `_parallel_scan()` now creates throttler, workers report latency + check pause
- `core/lifecycle_scanner.py` — `_parallel_lifecycle_walk()` same throttling integration

**Design notes:**
- `record_latency()` is ~0.001ms (deque append under lock) — negligible vs 3-10ms stat calls
- `should_pause(worker_id)` reads a single int (no lock) — zero overhead for active workers
- `check_and_adjust()` runs once per 500 files, computes median of last 100 latencies
- Workers with higher IDs are parked first (clean priority ordering)

---

## v0.13.1 — Adaptive Scan Parallelism (2026-03-31)

**New features:**
- Storage latency probe auto-detects storage type (SSD, HDD, NAS) before each scan
- Parallel directory walkers for NAS/SMB/NFS sources (4-12 threads hide network latency)
- Serial scan preserved for local disks (avoids HDD seek thrashing)
- Probe uses sequential-vs-random stat() timing ratio — stable even under background I/O load
- Both bulk scanner and lifecycle scanner benefit from adaptive parallelism
- New `scan_max_threads` preference: `"auto"` (default, probe decides) or manual override
- Settings page gains Scan Performance section
- SSE event `storage_probe_result` emitted so UI can display detected storage type

**New files:**
- `core/storage_probe.py` — `StorageProfile` dataclass, `probe_storage_latency()` async function

**Modified files:**
- `core/bulk_scanner.py` — integrated probe + `_parallel_scan()` / `_serial_scan()` split
- `core/lifecycle_scanner.py` — integrated probe + `_parallel_lifecycle_walk()` / `_serial_lifecycle_walk()`
- `core/database.py` — added `scan_max_threads` preference
- `api/routes/preferences.py` — added schema + system key for scan_max_threads

**Design notes:**
- The sequential-vs-random stat ratio is the key discriminator: HDD shows ratio > 3x (seek penalty), NAS shows ratio < 2x (uniform network latency), SSD shows both fast + low ratio
- A busy HDD under background I/O still shows the seek penalty ratio — avoids misclassification
- Thread workers push `(path, ext, size, mtime)` tuples into a `queue.Queue`; a single async consumer drains to SQLite. DB writes never bottleneck because local SSD writes are ~100x faster than NAS reads

---

## v0.13.0 — Media Transcription Pipeline (2026-03-30)

**New features:**
- Audio/video files (.mp3, .mp4, .wav, .mkv, etc.) now convert to Markdown transcripts with timestamped segments
- Three output files per media conversion: `.md` (timestamped transcript), `.srt`, `.vtt`
- Local Whisper transcription with GPU auto-detect (CUDA when available, CPU fallback)
- Cloud transcription fallback — tries OpenAI Whisper API and Gemini audio in provider priority order
- Existing caption files (SRT/VTT/SBV) detected alongside media files and parsed automatically (no transcription cost)
- Meilisearch `transcripts` index for full-text search across spoken content
- Cowork search extended to cover documents + transcripts
- 2 new MCP tools: `search_transcripts`, `read_transcript`
- Visual enrichment (scene detection + keyframe pipeline) optionally interleaved into video transcripts
- Settings page gains Transcription section (Whisper model, device, language, cloud fallback, timeout, caption extensions)
- History page shows media-specific metadata: duration, engine badge, language
- Health check includes Whisper availability and device info
- Bulk conversion counters include "Transcribed" count

**New files (10 core + 2 handlers + 1 API route):**
- `core/media_probe.py`, `core/audio_extractor.py`, `core/whisper_transcriber.py`
- `core/cloud_transcriber.py`, `core/caption_ingestor.py`, `core/transcription_engine.py`
- `core/transcript_formatter.py`, `core/media_orchestrator.py`
- `formats/audio_handler.py`, `formats/media_handler.py`
- `api/routes/media.py`

**Database changes:**
- New table: `transcript_segments` (history_id, segment_index, start/end seconds, text, speaker, confidence)
- New columns on `conversion_history`: media_duration_seconds, media_engine, media_whisper_model, media_language, media_word_count, media_speaker_count, media_caption_path, media_vtt_path
- New columns on `bulk_files`: is_media, media_engine
- New columns on `bulk_jobs`: transcribed, transcript_failed

**Dependencies:**
- Added: `openai-whisper`, `ffmpeg-python`
- `torch` (CPU) pre-installed in Dockerfile.base for faster rebuilds
- `whisper-cache` Docker volume for persistent model storage

---

**Phase 0 complete** — Docker scaffold running. All system deps verified.

**Phase 1 complete** — DOCX → Markdown pipeline fully implemented. 60 tests passing. Tagged v0.1.0.

**Phase 2 complete** — Markdown → DOCX round-trip with fidelity tiers. 96 tests passing. Tagged v0.2.0.

**Phase 3 complete** — OCR pipeline: multi-signal detection, preprocessing, Tesseract extraction,
  confidence flagging, review API + UI, unattended mode, SQLite persistence. Tagged v0.3.0.

**Phase 4 complete** — PDF, PPTX, XLSX/CSV format handlers (both directions). 231 tests passing. Tagged v0.4.0.

**Phase 5 complete** — Full test suite (350+ tests), structured JSON logging throughout all
  pipeline stages, debug dashboard at /debug. Tagged v0.5.0.

**Phase 6 complete** — Full UI: live SSE batch progress, history page (filter/sort/search/
  redownload), settings page (preferences with validation), shared CSS design system,
  dark mode, comprehensive error UX. 378 tests passing. Tagged v0.6.0.

**Phase 7 complete** — Bulk conversion pipeline (scanner, worker pool, pause/resume/cancel),
  Adobe Level 2 indexing (.ai/.psd text + .indd/.aep/.prproj/.xd metadata), Meilisearch
  full-text search (documents + adobe-files indexes), search UI, bulk job UI,
  Cowork search API. 467 tests. Tagged v0.7.0.

**v0.7.1** — Named Locations system: friendly aliases for container paths used in bulk jobs.
  First-run wizard guides setup. Bulk form uses dropdowns instead of raw path inputs.
  Backwards compatible with BULK_SOURCE_PATH / BULK_OUTPUT_PATH env vars. 496 tests.

**v0.7.2** — Directory browser: Windows drives mounted at /host/c, /host/d etc.
  Browse endpoint (GET /api/browse) with path traversal protection.
  FolderPicker widget on Locations page — no need to type container paths manually.
  Unmounted drives show setup instructions inline.

**v0.7.3** — OCR confidence visibility and bulk skip-and-review. Confidence scores
  (mean, min, pages below threshold) recorded per file and shown in history with
  color-coded badges. Bulk mode skips PDFs below confidence threshold into a review
  queue instead of failing them. Post-job review UI (bulk-review.html) lets user
  convert anyway, skip permanently, or open per-page OCR review per file.

**v0.7.4** — LLM providers (Anthropic, OpenAI, Gemini, Ollama, custom), API key
  encryption, connection verification, opt-in OCR correction + summarization +
  heading inference. Auto-OCR gap-fill for PDFs converted without OCR.
  MCP server (port 8001) exposes 7 tools to Claude.ai (later expanded to 10): search, read, list,
  convert, adobe search, get summary, conversion status. 543 tests.

**v0.7.4b** — Path safety and collision handling. Deeply nested paths checked
  against configurable max length (default 240 chars). Output path collisions
  (same stem, different extension) detected at scan time and resolved per
  strategy: rename (default, no data loss), skip, or error. Case-sensitivity
  collisions detected separately. All issues recorded in bulk_path_issues table,
  reported in manifest, downloadable as CSV.

**v0.7.4c** — Active file display in bulk progress. Collapsible panel shows
  one row per worker with current filename. Worker count matches Settings value.
  Collapse state persists in localStorage. Hidden when preference is off.
  `file_start` SSE event added; `worker_id` added to all worker SSE events.

**v0.8.1** — Visual enrichment pipeline. Scene detection (PySceneDetect), keyframe
  extraction (ffmpeg), and AI frame descriptions via the existing LLM provider system.
  VisionAdapter wraps the active provider for image input (Anthropic, OpenAI, Gemini,
  Ollama). Vision preferences stored in existing preferences table (not a separate
  settings system). DB: scene_keyframes table, vision columns on conversion_history.
  Meilisearch index extended with frame_descriptions field. Settings UI Vision section
  with provider display linking to existing providers.html. History detail panel shows
  scenes/enrichment/descriptions. Debug dashboard shows vision stats.

**v0.8.2** — Unknown & unrecognized file cataloging. Bulk scanner records every
  file it encounters, even without a handler. MIME detection via python-magic with
  extension fallback classifies files into categories (disk_image, raster_image,
  video, audio, archive, executable, database, font, code, unknown). New columns
  mime_type and file_category on bulk_files. Unrecognized files get
  status='unrecognized' (distinct from failed/skipped). API: GET /api/unrecognized
  (list, filter, paginate), /stats, /export (CSV). UI: /unrecognized.html with
  category cards, filters, table. Bulk progress shows unrecognized count pill.
  MCP tool: list_unrecognized (8th tool).

**v0.8.5** — File lifecycle management, version tracking & database health.
  APScheduler runs lifecycle scans every 15 min during business hours. Detects
  new/modified/moved/deleted files in source share. Soft-delete pipeline:
  active → marked_for_deletion (36h grace) → in_trash (60d retention) → purged.
  Full version history with unified diff patches and bullet summaries per file.
  Trash management page, DB health dashboard, lifecycle badges on all file views.
  6 new preference keys for scanner and lifecycle config. DB maintenance: weekly
  compaction, integrity checks, stale data detection. WAL mode enabled.
  MCP tools 9-10: list_deleted_files, get_file_history.

**v0.9.0** — Auth layer & UnionCore integration contract. JWT-based auth
  middleware with HS256 validation (UnionCore as identity provider). Role-based
  route guards: search_user < operator < manager < admin. API key service
  accounts for UnionCore backend (BLAKE2b hashed, `mf_` prefixed). Admin panel
  for key management. CORS configured for UnionCore origin. DEV_BYPASS_AUTH=true
  for local dev (all requests treated as admin). `/` redirects to search page.
  Role-aware dynamic navigation (nav items filtered by user role). Preferences
  split: system-level keys require manager role. Integration contract at
  `docs/unioncore-integration-contract.md`. New env vars: UNIONCORE_JWT_SECRET,
  UNIONCORE_ORIGIN, DEV_BYPASS_AUTH, API_KEY_SALT.

**v0.9.1** — Search autocomplete & scan progress visibility.
  Autocomplete dropdown on search.html powered by Meilisearch (debounced 200ms,
  keyboard navigable, deduplicates across documents + adobe-files indexes).
  `GET /api/search/autocomplete` endpoint. Bulk scan phase now emits
  `scan_progress` SSE events (count, pct, current_file) every 50 files with
  pre-counted total estimate. Background lifecycle scanner exposes in-memory
  `_scan_state` via `GET /api/scanner/progress` (polled every 3s by UI).
  Lifecycle scan status bar on bulk.html and db-health.html shows progress
  or last-scan timestamp. New tests in test_search.py and test_scanner.py.

**v0.9.2** — Admin page: resource controls, task manager & stats dashboard.
  `core/resource_manager.py` wraps psutil for CPU affinity, process priority,
  and live metrics. Admin page gains three sections: Repository Overview
  (KPI cards, file/lifecycle/OCR/format/Meilisearch/scheduler/error stats),
  Task Manager (per-core CPU bars, memory, threads, 2s polling), Resource
  Controls (worker count, priority, core pinning). New endpoints:
  `PUT /api/admin/resources`, `GET /api/admin/system/metrics`,
  `GET /api/admin/stats`. New preferences: worker_count, cpu_affinity_cores,
  process_priority. `get_scheduler_status()` added to scheduler.py.
  psutil primed at startup in lifespan. 16 new tests in test_admin.py.

**v0.9.3** — Global stop controls, active jobs panel, admin DB tools, locations
  flagged for UX redesign. `core/stop_controller.py`: cooperative global stop
  flag checked by bulk workers, bulk scanner, and lifecycle scanner before each
  file. `POST /api/admin/stop-all` cancels all registered asyncio tasks.
  `POST /api/admin/reset-stop` clears the flag. `GET /api/admin/active-jobs`
  returns all running jobs for the global status bar. Persistent floating status
  bar (`global-status-bar.js`) on every page shows job count, STOP ALL button,
  and stop-requested banner. Active Jobs slide-in panel (`active-jobs-panel.js`)
  shows per-job detail with progress bars, active workers, per-directory stats,
  and individual stop buttons. `dir_stats` on BulkJob tracks top-level
  subdirectory counts. Admin DB Tools section: quick health check, full integrity
  check, dump-and-restore repair (blocked if jobs running). Locations page flagged
  for UX redesign with visible banner. New tests in test_stop_controller.py,
  test_active_jobs.py, and additions to test_admin.py.

**v0.9.4** — Status page & nav redesign. Floating global-status-bar and
  slide-in active-jobs-panel replaced by dedicated `/status.html` with
  stacked per-job cards (progress bars, active workers, per-dir stats,
  pause/resume/stop controls). STOP ALL button and lifecycle scanner card
  live on status page. Nav gains "Status" link with active-job count
  badge (pulses red when stop requested). `global-status-bar.js` rewritten
  to badge-only polling; `active-jobs-panel.js` retired and deleted.
  `app.js` dynamically loads badge script after `buildNav()`. Old `.gsb-*`
  and `.ajp-*` CSS replaced by `.job-card`, `.status-pill`, `.nav-badge`
  design system classes. No backend changes.

**v0.9.5** — Configurable logging levels with dual-file strategy. Three levels:
  Normal (WARNING+), Elevated (INFO+), Developer (DEBUG + frontend trace).
  Operational log always active (logs/markflow.log, 30-day rotation).
  Debug trace log (logs/markflow-debug.log, 7-day) only active in Developer mode.
  Dynamic level switching — no container restart required. Settings UI Logging section
  with log file downloads. POST /api/log/client-event instruments ~15 JS actions in
  Developer mode (rate-limited, silently dropped at other levels).
  log_level is a system-level preference requiring Manager role.

**v0.9.6** — Admin disk usage dashboard. `GET /api/admin/disk-usage` walks all
  MarkFlow directories in a thread and reports per-directory byte counts, file
  counts, and volume info. Trash excluded from output-repo total (no double-count).
  DB + WAL reported separately in API, combined in UI. Admin page gains Disk Usage
  section with volume progress bars, breakdown cards, and manual Refresh button.
  No auto-polling — directory walks can take seconds on large repos.

**v0.9.7** — Resources page & activity monitoring. New `system_metrics` table
  (30s samples via APScheduler), `disk_metrics` (6h snapshots), `activity_events`
  (bulk start/end, lifecycle scan, index rebuild, startup/shutdown, DB maintenance).
  `core/metrics_collector.py` owns collection, queries, and 90-day purge.
  Resources page (`/resources.html`, manager+ role) with: executive summary card
  (IT admin pitch with description sentences), CPU/memory Chart.js time-series,
  disk growth stacked area chart, live system metrics (moved from Admin), activity
  log with type filters and expandable metadata, repository overview. CSV export
  for all three metrics tables. Admin Task Manager replaced with link card to
  Resources; resource controls remain on Admin. 5 new API endpoints under
  `/api/resources/` (metrics, disk, events, summary, export).

**v0.9.8** — Password-protected document handling. `core/password_handler.py`
  detects two layers: restrictions (edit/print flags stripped automatically via
  pikepdf/lxml) and real encryption (password cascade: empty → user-supplied →
  org list → found-reuse → dictionary → brute-force → john). `pikepdf` handles
  PDF owner/user passwords. `msoffcrypto-tool` handles OOXML + legacy Office
  encryption. OOXML restriction tags (`documentProtection`, `sheetProtection`,
  `workbookProtection`, `modifyVerifier`) stripped via ZIP+lxml rewrite.
  Converter preprocesses files before `handler.ingest()` — no handler signature
  changes. Bulk worker shares `PasswordHandler` instance across files for
  found-password reuse. Convert page gains password input field. Settings page
  gains Password Recovery section (6 new preferences). DB columns:
  `protection_type`, `password_method`, `password_attempts` on both
  `conversion_history` and `bulk_files`. `john` installed in Docker for
  enhanced PDF cracking. Bundled `common.txt` dictionary (top passwords).

**v0.9.9** — GPU auto-detection & dual-path hashcat integration.
  `core/gpu_detector.py` probes container for NVIDIA (nvidia-smi) and reads
  host worker capabilities from `/mnt/hashcat-queue/worker_capabilities.json`.
  Execution path priority: NVIDIA container > host worker > hashcat CPU > none.
  `tools/markflow-hashcat-worker.py` runs outside Docker, watches shared queue
  volume for crack jobs, runs hashcat with host GPU (AMD ROCm, Intel OpenCL).
  Job queue is file-based JSON over a bind-mounted volume. `docker-compose.gpu.yml`
  overlay provides NVIDIA Container Toolkit GPU reservation. Dockerfile adds
  hashcat, OpenCL packages, clinfo. `CrackMethod` enum gains `HASHCAT_GPU`,
  `HASHCAT_CPU`, `HASHCAT_HOST`. New preferences: `password_hashcat_enabled`,
  `password_hashcat_workload`. Health endpoint reports dual-path GPU info.
  Settings page gains GPU Acceleration status card. Container starts normally
  with no GPU present — graceful degradation to CPU/john fallback.
  Apple Silicon Macs: Metal backend detection, unified memory estimation,
  Rosetta 2 binary guard, hashcat >= 6.2.0 version gate, thermal-safe
  workload profile (-w 2). macOS Intel discrete GPUs (Radeon Pro) supported
  via OpenCL.

**v0.10.0** — In-app help wiki & contextual help system. 19 markdown articles
  in `docs/help/` rendered via mistune at `GET /api/help/article/{slug}`.
  Searchable via `GET /api/help/search?q=`. Help page (`/help.html`) with sidebar
  TOC, search, hash-based navigation. Contextual "?" icons via `data-help`
  attributes + `static/js/help-link.js`. Nav gains "Help" link (all roles, no auth).
  Help API endpoints are public. CSS: help-layout classes in markflow.css.

**v0.10.1** — Apple Silicon Metal support for GPU hashcat worker.
  `tools/markflow-hashcat-worker.py` gains macOS detection: Apple Silicon
  (M1/M2/M3/M4) via Metal backend, Intel Mac discrete GPU via OpenCL.
  Rosetta 2 binary warning prevents silent Metal loss. hashcat version
  gated at >= 6.2.0 for Metal. Unified memory estimation (~75% of system
  RAM) replaces VRAM reporting on Apple Silicon. Thermal-safe workload
  profile (-w 2, not -w 3) prevents throttling on fanless Macs.
  `core/gpu_detector.py` recognizes vendor=apple/backend=Metal in worker
  capabilities. Settings GPU status card updated for Apple display.

**v0.11.0** — Intelligent auto-conversion engine. When the lifecycle
  scanner finds new/modified files, the engine decides whether, when,
  and how aggressively to convert them. Three modes: immediate (same
  scan cycle), queued (background task), scheduled (time-window only).
  Dynamic worker scaling and batch sizing based on real-time CPU/memory
  load + historical hourly averages. `core/auto_converter.py` (decision
  engine), `core/auto_metrics_aggregator.py` (hourly rollup from
  system_metrics into auto_metrics table). Two new SQLite tables:
  `auto_metrics` (hourly aggregated system metrics for pattern learning),
  `auto_conversion_runs` (decision/execution audit log). 9 new preferences
  (auto_convert_mode, workers, batch_size, schedule_windows,
  decision_log_level, metrics_retention_days, business_hours_start/end,
  conservative_factor). `BulkJob` gains `max_files` parameter for batch
  capping. `bulk_jobs` gains `auto_triggered` column. APScheduler gains
  hourly aggregation job (:05 past each hour) and 15-min deferred
  conversion runner. Status page gains mode override card (ephemeral,
  resets on container restart). Settings page gains Auto-Conversion
  section. API: GET/POST/DELETE /api/auto-convert/override,
  GET /api/auto-convert/status, /history, /metrics.

**v0.12.0** — Universal format support, unified scanning & folder drop UI.
  10 new format handlers: RTF (`rtf_handler.py`, control-word parser with font
  mapping), HTML/HTM (`html_handler.py`, BeautifulSoup + CSS font extraction),
  ODT/ODS/ODP (`odt_handler.py`, `ods_handler.py`, `odp_handler.py` via odfpy),
  TXT/LOG (`txt_handler.py`, encoding detection + heading heuristics),
  XML (`xml_handler.py`, DOM traversal + element extraction),
  EPUB (`epub_handler.py`, ebooklib chapter structure preservation),
  EML/MSG (`eml_handler.py`, RFC 5322 + Outlook OLE via olefile),
  Adobe unified handler (`adobe_handler.py`, PSD/AI/INDD/AEP/PRPROJ/XD
  metadata extraction via exiftool). Total supported extensions: 26 across
  16 handlers. Bulk scanner unified — no separate Adobe/convertible split;
  all formats go through the same scanning pipeline with single-pass
  extension lookup against the format registry. Font recognition added to
  `extract_styles()` across handlers for Tier 2 reconstruction fidelity.
  Convert page (`index.html`) gains folder drop: drag-and-drop entire
  directories, auto-scans for valid formats, queues matching files for
  conversion. `formats/__init__.py` imports all new handlers at module load.
  `core/bulk_scanner.py` refactored to use `list_supported_extensions()`
  instead of hardcoded extension sets. `core/converter.py` and
  `core/bulk_worker.py` updated for new handler lookup path.

**v0.12.1** — Data format handlers + recursive email attachment conversion.
  Three new handlers: `json_handler.py` (JSON with summary + structure outline +
  secret redaction), `yaml_handler.py` (YAML/YML with multi-document support,
  comments preservation in source block), `ini_handler.py` (INI/CFG/CONF/properties
  with configparser + line-by-line fallback; `.conf` without sections treated as
  plain text). All three produce Summary + Structure + Source markdown layout.
  Secret value redaction (password, token, api_key, credential, auth key patterns).
  EmlHandler upgraded with recursive attachment conversion — attachments with
  registered handlers are converted and embedded inline under `## Attachments`.
  Depth-limited to 3 for nested emails. Non-fatal failures. MSG attachments
  supported via olefile stream traversal. 7 new extensions registered:
  `.json`, `.yaml`, `.yml`, `.ini`, `.cfg`, `.conf`, `.properties`.
  Total supported extensions: 33 across 19 handlers. Convert page and folder
  drop UI updated for new extensions.

**v0.12.2** — Size-based log rotation + settings download loop fix.
  Replaced `TimedRotatingFileHandler` with `RotatingFileHandler` (50 MB main,
  100 MB debug, configurable via `LOG_MAX_SIZE_MB` / `DEBUG_LOG_MAX_SIZE_MB`).
  Log download endpoint gets size guard (HTTP 413 for files >500 MB) and
  explicit `Content-Length` header to prevent browser download restart loops.

**v0.12.3** — Compressed file scanning, archive extraction, file tracking.
  New `ArchiveHandler` for ZIP, TAR, TAR.GZ, 7z, RAR, CAB, ISO. Recursive
  extraction and conversion of inner documents (depth limit 20). Archive
  summary markdown per file. Zip-bomb protection (`core/archive_safety.py`):
  ratio check, total size cap, entry count cap, quine detection. Compound
  extension support in format registry (`_get_compound_extension()`) and
  bulk scanner (`_get_effective_extension()`). New `archive_members` DB table.
  Dependencies: py7zr, rarfile, pycdlib, cabextract, unrar-free, p7zip-full.
  Password file at `config/archive_passwords.txt`. 12 new extensions registered.
  Total supported extensions: 45 across 20 handlers.

**v0.12.4** — Archive password writeback and session-level reuse.
  Successful archive passwords saved back to `archive_passwords.txt` and
  cached in-memory for the process lifetime. Found passwords tried first
  on subsequent archives. Thread-safe via lock.

**v0.12.5** — Full password cracking cascade for encrypted archives.
  Archive handler now mirrors the PDF/Office password handler cascade:
  known passwords, dictionary attack (common.txt + mutations), brute-force.
  Respects user preferences for charset, max length, timeout. Settings read
  sync-safely via direct sqlite3 connection.

**v0.12.6** — Brute-force charset fixed to all printable characters as default
  for both archive and PDF/Office crackers. Fallback charset updated.

**v0.12.7** — Full ASCII charset (0x01-0x7F) including control characters.
  New `all_ascii` charset option in Settings UI. Default for both archive
  and PDF/Office brute-force. Encrypted ZIP, 7z, and RAR archives —
  including nested ones — get the full cracking cascade at every depth.

**v0.12.8** — Progress tracking and ETA for scan and bulk conversion jobs.
  New `core/progress_tracker.py`: `RollingWindowETA` (last 100 items),
  `ProgressSnapshot`, `format_eta()`, `estimate_single_file_eta()`.
  Concurrent fast-walk counter in `bulk_scanner.py` via `asyncio.create_task`
  — scan starts immediately, file count arrives in parallel (no blocking).
  Bulk worker writes ETA to DB every 2s and emits `progress_update` SSE
  events with `eta_human`, `files_per_second`, `percent`. All job status
  API endpoints (`GET /api/bulk/jobs/{id}`, active jobs) return `progress`
  block. DB: added `eta_seconds`, `files_per_second`, `eta_updated_at`,
  `total_files_counted`, `count_status` columns to `scan_runs`, `bulk_jobs`,
  `conversion_history`. UI: ETA display and speed indicator on bulk page,
  scan progress shows "X of Y files" with streaming count.

**v0.12.9** — Startup crash fix, log noise suppression, Docker build optimization (2026-03-30).
**Bugfixes:**
- Fixed: `NameError: name 'structlog' is not defined` in `database.py` — missing
  `import structlog` caused `cleanup_orphaned_jobs()` to crash on every startup,
  putting the markflow container in a restart loop (exit code 3).
- Suppressed pdfminer debug/info logging — pdfminer (used internally by pdfplumber)
  emits thousands of per-token debug messages during PDF extraction. A single bulk job
  was inflating the debug log to 500+ MB. All `pdfminer.*` loggers now set to WARNING
  in `configure_logging()`, matching existing pattern for noisy third-party libraries.
**Infrastructure:**
- Split Dockerfile into `Dockerfile.base` (system deps, ~25-30 min on HDD) and
  `Dockerfile` (pip + code copy, ~3-5 min). Daily rebuilds skip the heavy apt layer.
- Added deployment scripts for Windows work machine: `build-base.ps1` (one-time base
  image builder), `refresh-markflow.ps1` (quick code-only rebuild), `reset-markflow.ps1`
  and `pull-logs.ps1` (PowerShell equivalents of the Proxmox bash scripts).
- Updated reset scripts (both Proxmox and Windows) to preserve `markflow-base:latest`
  during Docker prune, auto-building it if missing.

**v0.12.10** — MCP server fixes, multi-machine Docker support, settings UI improvements (2026-03-30).
**Bugfixes:**
- Fixed: MCP server crash loop — `FastMCP.run()` does not accept `host` or `port` kwargs.
  First attempted kwargs (TypeError crash), then UVICORN env vars (ignored). Final fix:
  `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)` — bypass `mcp.run()` entirely.
- Fixed: MCP info panel showed `http://172.20.0.3:8001/mcp` (Docker-internal IP, wrong
  path). Replaced `socket.gethostbyname()` with hardcoded `localhost`, `/mcp` with `/sse`.
- Fixed: MCP health check 404 — `FastMCP.sse_app()` has no `/health` route. Added
  Starlette `Route("/health")` to the SSE app before passing to uvicorn.
**Features:**
- Multi-machine Docker support — `docker-compose.yml` volume paths now use `${SOURCE_DIR}`,
  `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}` from `.env` (gitignored). Same compose file
  works on Windows workstation and MacBook VM without edits. `.env.example` template added.
- MCP settings panel: replaced generic setup instructions with connection methods for
  Claude Code, Claude Desktop, and Claude.ai (web with ngrok tunnel).
- "Generate Config for Claude Desktop" button — merges markflow MCP entry into user's
  existing `claude_desktop_config.json` non-destructively (client-side JS, no backend).
- PowerShell deployment scripts (`reset-markflow.ps1`, `refresh-markflow.ps1`) gain `-GPU`
  switch to include `docker-compose.gpu.yml` override.
- Developer Mode checkbox at top of Settings page — toggles both `log_level` and
  `auto_convert_decision_log_level` between `developer` and `normal`. Syncs bidirectionally
  with the log level dropdown.
**Default preference changes (fresh deployments):**
- `auto_convert_mode`: `off` → `immediate` (scan + convert automatically)
- `auto_convert_workers`: `auto` → `10`
- `worker_count`: `4` → `10`
- `max_concurrent_conversions`: `3` → `10`
- `ocr_confidence_threshold`: `80` → `70`
- `max_output_path_length`: `240` → `250`
- `scanner_interval_minutes`: `15` → `30`
- `collision_strategy`: `rename` (unchanged, confirmed as desired default)
- `bulk_active_files_visible`: `true` (unchanged, confirmed)
- `password_brute_force_enabled`: `false` → `true`
- `password_brute_force_max_length`: `6` → `8`
- `password_brute_force_charset`: `alphanumeric` → `all_ascii`
- Auto-conversion worker select gains "10" option in UI.

**v0.12.1** — Bugfix + Stability Patch (2026-03-29).
**Bugfixes (from log analysis):**
- Fixed: structlog double `event` argument in lifecycle_scanner (two instances)
- Fixed: SQLite "database is locked" — all direct `aiosqlite.connect()` calls now use
  `get_db()` or set `PRAGMA busy_timeout=10000`; retry wrapper on metrics INSERT
- Fixed: collect_metrics interval increased from 60s to 120s with `misfire_grace_time=60`;
  added 30s timeout wrapper via `asyncio.wait_for`
- Fixed: DB compaction always deferred — removed `scan_running` guard, compaction now runs
  concurrently with scans (safe in WAL mode)
- Fixed: MCP server unreachable — health check now uses `MCP_HOST` env var (default
  `markflow-mcp` Docker service name) instead of hardcoded `localhost`
**Stability improvements:**
- Added: Startup orphan job recovery — auto-cancels stuck bulk_jobs and interrupts
  stuck scan_runs on container start (before scheduler starts)
- Fixed: Stop banner CSS — `.stop-banner[hidden]` override prevents `display:flex`
  from overriding the HTML `hidden` attribute; JS uses `style.display` toggle
- Note: Lifecycle scanner progress tracking + ETA already existed (v0.12.8)
- Added: Mount-readiness guard — bulk scanner and lifecycle scanner verify source mount
  is populated before scanning. Empty mountpoints (SMB not connected) abort gracefully.
- Added: Static file `Cache-Control: no-cache, must-revalidate` headers via middleware
- Added: `DEFAULT_LOG_LEVEL` env var for container-start log level override
