# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Detailed references live in `docs/`.

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — Python/FastAPI web app that converts
documents bidirectionally between their original format and Markdown. Runs in Docker.
GitHub: `github.com/theace26/Doc-Conversion-2026`

## Project documentation map

Read on demand — none of these are auto-loaded. Listed by role.

### Core engineering references (read these first when working on code)

| File | Role / read it when... |
|------|------------------------|
| [`docs/gotchas.md`](docs/gotchas.md) | Hard-won subsystem-specific lessons (~100 items, organized by subsystem). **Always check the relevant section before modifying or debugging code in that area** — most foot-guns here have already been hit. |
| [`docs/key-files.md`](docs/key-files.md) | 189-row file reference table mapping every important file to its purpose. Read when locating a file by what it does or understanding what an unfamiliar file is for. |
| [`docs/version-history.md`](docs/version-history.md) | Detailed per-version changelog (one entry per release, full context: problem, fix, modified files, why-it-matters). The canonical "why was this built" reference. Append a new entry on every release. |

### Pre-production / hardening

| File | Role / read it when... |
|------|------------------------|
| [`docs/security-audit.md`](docs/security-audit.md) | Findings-only security audit performed at v0.16.0. **62 findings: 10 critical + 18 high + 22 medium + 12 low/info — pre-prod blocker.** Read when working on auth, input validation, JWT, role guards, or anything customer-data-sensitive. |
| [`docs/streamlining-audit.md`](docs/streamlining-audit.md) | Code-quality / DRY audit performed at v0.16.0. All 24 items resolved across v0.16.1–v0.16.2. Read only when you want history of how the codebase was tightened (e.g., why `core/db/` is split into 8 modules). |

### Integration / contracts (Phase 10+)

| File | Role / read it when... |
|------|------------------------|
| [`docs/unioncore-integration-contract.md`](docs/unioncore-integration-contract.md) | The agreed-upon API contract between MarkFlow and UnionCore (Phase 10 auth integration). Two surfaces: user-facing search render + backend webhook. Read when touching `/api/search/*` shape, JWT validation, or anything UnionCore consumes. |
| [`docs/MarkFlow-Search-Capabilities.md`](docs/MarkFlow-Search-Capabilities.md) | Stakeholder-facing capability brief (last updated v0.22.0). Sales / executive tone. Read when the user asks for a feature summary suitable for non-engineers, or when updating it after major search/index changes. |

### Operations

| File | Role / read it when... |
|------|------------------------|
| [`docs/drive-setup.md`](docs/drive-setup.md) | End-user instructions for sharing host drives with the Docker container (Windows/Mac/Linux). Read when troubleshooting "MarkFlow can't see my files" or updating Docker mount setup. |
| [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md) | Original Phase 1 design spec (DocumentModel, DocxHandler, metadata, upload UI). **Historical only** — read only if revisiting the foundation architecture. |

### User-facing help wiki (`docs/help/*.md` — 18 articles)

These render in the in-app help drawer (`/help.html`). Update them when shipping
user-visible features or changing UX. Article inventory:

| Article | Covers |
|---------|--------|
| [`getting-started.md`](docs/help/getting-started.md) | First-time user walkthrough |
| [`document-conversion.md`](docs/help/document-conversion.md) | Single-file Convert page |
| [`bulk-conversion.md`](docs/help/bulk-conversion.md) | Bulk Convert page, jobs, pause/resume/cancel |
| [`auto-conversion.md`](docs/help/auto-conversion.md) | Auto-conversion pipeline (modes, workers, batch sizing, master switch) |
| [`search.md`](docs/help/search.md) | Search page, filters, batch download, hover preview |
| [`fidelity-tiers.md`](docs/help/fidelity-tiers.md) | Tier 1/2/3 round-trip explanation |
| [`ocr-pipeline.md`](docs/help/ocr-pipeline.md) | OCR detection, confidence, review queue |
| [`file-lifecycle.md`](docs/help/file-lifecycle.md) | Active → marked → trashed → purged states + timers |
| [`adobe-files.md`](docs/help/adobe-files.md) | Adobe Level-2 indexing (.psd/.ai/.indd) |
| [`database-files.md`](docs/help/database-files.md) | Database extraction (.sqlite/.mdb/.accdb/.dbf/.qbb/.qbw) |
| [`unrecognized-files.md`](docs/help/unrecognized-files.md) | Catalog page, MIME detection |
| [`llm-providers.md`](docs/help/llm-providers.md) | Provider setup, AI Assist, image analysis |
| [`hardware-specs.md`](docs/help/hardware-specs.md) | Minimum/recommended hardware, user capacity estimates |
| [`gpu-setup.md`](docs/help/gpu-setup.md) | NVIDIA Container Toolkit, host worker, hashcat |
| [`password-recovery.md`](docs/help/password-recovery.md) | PDF/Office/archive password cascade |
| [`mcp-integration.md`](docs/help/mcp-integration.md) | Port 8001 MCP server, tools, auth token |
| [`nfs-setup.md`](docs/help/nfs-setup.md) | NFS mount Settings UI |
| [`status-page.md`](docs/help/status-page.md) | System Status page, health checks |
| [`resources-monitoring.md`](docs/help/resources-monitoring.md) | Resources page, activity log |
| [`admin-tools.md`](docs/help/admin-tools.md) | Admin-only pages (flagged files, users, providers) |
| [`settings-guide.md`](docs/help/settings-guide.md) | Settings page section-by-section reference |
| [`keyboard-shortcuts.md`](docs/help/keyboard-shortcuts.md) | Page-level keyboard shortcuts |
| [`troubleshooting.md`](docs/help/troubleshooting.md) | Common problems + fixes by symptom |

### Implementation plans / specs (`docs/superpowers/`)

`docs/superpowers/plans/*.md` and `docs/superpowers/specs/*.md` contain the
written plans and design specs for major features (image-analysis-queue,
hdd-scan-optimizations, pipeline-file-explorer, nfs-mount-support, vector-search,
cloud-prefetch, file-flagging, source-files-dedup, auto-conversion-pipeline).
**Historical / context-only** — once a plan is shipped, the canonical
documentation lives in `version-history.md` and the code itself. Read a plan
only when investigating a feature's original intent or design rationale.

### Rule of thumb

If a task touches **bulk / lifecycle / auth / password / GPU / OCR / search / vector**,
read the relevant `gotchas.md` section first. Most bugs in those areas have already
been hit and documented. For "what changed and why" questions, jump to
`version-history.md`. For "where does X live" questions, jump to `key-files.md`.

---

## Current Version — v0.28.0

**Universal Storage Manager — replace manual `.env` / `docker-compose.yml`
storage config with a GUI Storage page, first-run wizard, and runtime
network-share management. Three architectural layers: Docker grants broad
host mounts (`/host/root:ro` + `/host/rw`) and `SYS_ADMIN` cap; the
application enforces write restriction through `storage_manager.is_write_allowed()`
at every file-writing site (12 sites in converter.py + bulk_worker.py,
covered by `tests/test_write_guard_coverage.py`); the new `/storage.html`
page consolidates sources, output, network shares, exclusions, and a
5-step onboarding wizard.**

- **5 new core modules**: `host_detector` (OS detection from
  `/host/root` filesystem signatures), `credential_store` (Fernet+PBKDF2
  encrypted SMB/NFS credentials), `storage_manager` (validation +
  write-guard + DB persistence), `mount_manager` extended with
  multi-mount + discovery + 5-min health probe, plus the new
  `api/routes/storage.py` consolidated API surface.
- **Scheduler grows from 17 to 18 jobs** — `mount_health` runs every 5
  minutes and yields to active bulk jobs (matches MarkFlow convention).
- **8 new DB preferences** (storage_output_path, storage_sources_json,
  storage_exclusions_json, pending_restart_*, setup_wizard_dismissed,
  host_os_override).
- **Frontend**: new `/storage.html` with collapsible sections + wizard
  modal; `static/js/storage.js` builds all DOM via createElement
  (XSS-safe per CLAUDE.md gotcha); `static/js/storage-restart-banner.js`
  is injected on every page via a dynamic script tag in `app.js` so we
  don't have to edit 20+ HTML files.
- **Settings page migration**: prominent "Open Storage Page →" link card
  at top; legacy storage sections left in place for backward
  compatibility (full removal deferred to v0.29.x once UI parity is
  proven).
- **Pragmatic deviations**: plan called for v0.25.0 (already taken — EPS
  rasterization shipped that version), bumped to v0.28.0. Plan called for
  full Settings page section removal, deferred to v0.29.x.
- **Tests**: 83 host-venv unit tests pass; 9 integration tests run inside
  the container.

Files: `core/version.py`, `core/host_detector.py`, `core/credential_store.py`,
`core/storage_manager.py`, `core/mount_manager.py`, `core/scheduler.py`,
`core/db/preferences.py`, `api/routes/storage.py`, `api/routes/browse.py`,
`main.py`, `static/storage.html`, `static/js/storage.js`,
`static/js/storage-restart-banner.js`, `static/app.js`, `static/markflow.css`,
`static/settings.html`, `tests/test_host_detector.py`,
`tests/test_credential_store.py`, `tests/test_storage_manager.py`,
`tests/test_mount_manager.py`, `tests/test_write_guard_coverage.py`,
`tests/test_storage_api.py`, `docs/help/storage.md`, `docs/help/_index.json`,
`docs/gotchas.md`, `docs/key-files.md`, `docs/version-history.md`,
`CLAUDE.md`, `docker-compose.yml`, `Dockerfile.base`.

---

## v0.24.2 — Hardening pass

**Audit-accuracy correction, DB backup
schema-version guard, PPTX pref read no longer bypasses the pool,
Whisper inference serialized so timed-out threads can't stack, and
the temporary DB contention logging instrumentation was retired.**

- **Security audit count corrected** — CLAUDE.md had "3 critical + 5
  high"; actual doc has 10 critical + 18 high + 22 medium + 12
  low/info. Still the one pre-prod blocker.
- **DB backup schema-version guard** (`core/db_backup.py`) — restore
  refuses a backup whose highest applied `schema_migrations.version`
  is newer than the current build. Prevents "passes integrity check,
  crashes on first migration-dependent query."
- **PPTX pref read** (`formats/pptx_handler.py`) — was opening a raw
  sqlite3 connection on every ingest. Now reads through the
  preferences cache (new `peek_cached_preference` sync helper in
  `core/preferences_cache.py`), with a one-time sync sqlite read on
  cold cache to warm it.
- **Whisper serialization** (`core/whisper_transcriber.py`) —
  `asyncio.wait_for` times out the awaiter but can't cancel the
  underlying inference thread. Added a `threading.Lock` inside the
  worker thread + an `asyncio.Lock` around the outer await; orphan
  threads from a prior timeout block all subsequent calls at the
  thread-level lock instead of stacking on the GPU. Honest
  `whisper_orphan_thread` warning logged on timeout.
- **DB contention logging retired** — `core/db/contention_logger.py`
  deleted, call sites in `core/db/connection.py`, `main.py`,
  `api/routes/debug.py`, `api/routes/preferences.py` removed, settings
  UI section deleted, `db_contention_logging` preference removed from
  defaults. Gotchas + key-files updated.
- **Convert-page SSE** — listed in v0.22.15 follow-ups; on static
  review in v0.24.2, `api/routes/batch.py:100-207` +
  `core/converter.py:40-53` appear functional. Leaving a watch on
  this with no code change; if a reproducible failure surfaces,
  revisit with an actual repro.
- **Corrupt-audio tensor reshape** — listed in v0.22.15 follow-ups;
  no `.reshape()` calls exist anywhere in the audio/transcription
  paths. Assumed resolved in an earlier patch. Removing from
  outstanding list.

Files: `core/version.py`, `core/db_backup.py`, `formats/pptx_handler.py`,
`core/preferences_cache.py`, `core/whisper_transcriber.py`,
`core/db/connection.py`, `core/db/preferences.py`,
`api/routes/debug.py`, `api/routes/preferences.py`, `main.py`,
`static/settings.html`, `CLAUDE.md`, `docs/gotchas.md`,
`docs/key-files.md`, `docs/version-history.md`. Module deleted:
`core/db/contention_logger.py`.

---

## v0.24.1 — AI Assist toggle feedback

Targeted UX fix on the Search page AI Assist toggle. Active state
now solid accent fill + `ON` pill; pre-search intent hint; inline
"Synthesize these results" button when toggled on after results are
already showing. Files: `static/css/ai-assist.css`,
`static/search.html`, `static/js/ai-assist.js`. Design spec at
`docs/superpowers/specs/2026-04-13-ai-assist-toggle-feedback-design.md`,
full notes in `docs/version-history.md`.

---

## v0.24.0 — Spec A (quick wins) + Spec B (batch management)

**Spec A (quick wins) + Spec B (batch management) — substantial UX
release addressing the "UX is atrocious" feedback: operators can now
drill into bulk/status counters inline, back up and restore the DB
from the UI, and manage image-analysis batches on a dedicated page.**

### Inline file lists (Spec A1 / A2)

Bulk page and Status page counter values (converted / failed /
skipped / pending) are now clickable. Clicking a count opens an
inline panel with the actual file list for that bucket, paginated
with "Load more." Status page uses event delegation so the same
handler works across per-card polls, and pagination state is
preserved across the 5s polling interval (fix in 5e6a84c) so users
don't get bounced back to page 1 mid-scroll.

### DB Backup / Restore (Spec A3-A6)

New `core/db_backup.py` module wrapping `sqlite3.Connection.backup()`
— the SQLite online backup API, which is WAL-safe and handles live
committed transactions still in `-wal` correctly. A naive
`shutil.copy2` of the `.db` file would silently miss those and
produce a corrupt/stale snapshot. Sentinel-row test proves the
backup captures the latest commit.

New endpoints in `api/routes/db_backup.py`:
`POST /api/db/backup`, `POST /api/db/restore`, `GET /api/db/backups`.
Typed error codes, audit-log entries for every backup/restore/
download, admin-only role guard.

UI on the DB Health page (`static/health.html` + `static/js/db-backup.js`):
drag-drop restore modal, download-backup button with auth cookie,
Esc-to-close, focus management. Matching "Database Maintenance"
section on `static/settings.html`.

### Hardware specs help article (A7)

`docs/help/hardware-specs.md` (already present) wired into the help
drawer TOC (`docs/help/_index.json`). Covers minimum / recommended
hardware, CPU / RAM / GPU / storage guidance, user capacity estimates.

### Batch management page (Spec B1-B6)

New `static/batch-management.html` page with full batch CRUD for
the image-analysis queue. Four new DB helpers in
`core/db/analysis.py` (`get_batches`, `get_batch_files`,
`exclude_files`, `cancel_all_batched`) — 10 unit tests.

New `analysis_submission_paused` boolean preference (default false).
The analysis worker checks this gate on each loop iteration and
skips submission when paused, so operators can drain in-flight
batches without triggering new ones.

New `/api/analysis` router with 9 endpoints (list batches, get
batch files, cancel batch, exclude files, cancel all batched,
toggle pause, etc.). Path-traversal guard on file-access endpoints,
`is_image_extension` deduplicated, audit logs for exclude / cancel
actions.

Nav entry added to the sidebar; the pipeline pill on the status
page links directly to the batch management page.

- **Files created:** `core/db_backup.py`, `core/db/analysis.py`,
  `api/routes/db_backup.py`, `api/routes/analysis.py`,
  `static/batch-management.html`, `static/js/db-backup.js`,
  `tests/test_db_backup.py`, `tests/test_analysis_batches.py`,
  `docs/help/hardware-specs.md` (content finalized)
- **Files modified:** `core/version.py`, `core/db/preferences.py`,
  `core/image_analysis_worker.py`, `main.py`,
  `static/bulk.html`, `static/status.html`,
  `static/health.html`, `static/settings.html`,
  `static/help.html` / `docs/help/_index.json`,
  navigation includes, `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`, `docs/gotchas.md`
- **Tests:** 21 new tests total (10 batch-mgmt DB + 11 DB backup).
- **New gotcha** added: SQLite online backup API is the correct
  approach for WAL databases — `shutil.copy2` of `.db` can miss
  committed transactions still in the `-wal` file.

Full context: [`docs/version-history.md`](docs/version-history.md).

---

### v0.23.8 (carried-forward summary) — Spec remediation Batch 2

Three items: content-hash sidecar collision fix (occurrence-indexed
keys `{hash}:{n}`, schema v2.0.0 with v1 auto-migrate, 4-level
cascade lookup incl. fuzzy match), PPTX chart/SmartArt extraction
(opt-in `pptx_chart_extraction_mode=libreoffice` renders charts via
LibreOffice+PyMuPDF), and C5 remaining OCR signals
(`text_layer_is_garbage` + `text_encoding_is_suspect` in
`core/ocr.py`). Full context:
[`docs/version-history.md`](docs/version-history.md).

---

### v0.23.7 (carried-forward summary) — Bulk vector indexer fix

Bulk vector indexing was 100% broken in v0.23.6 due to
`asyncio.Semaphore.acquire_nowait()` (doesn't exist — that's
`threading.Semaphore`). Fix: `async with _vector_semaphore:`.
Full context: [`docs/version-history.md`](docs/version-history.md).

---

### v0.23.6 (carried-forward summary) — Spec remediation Batch 1

Six-item hardening release: image dim hints in Markdown (M1),
pre-flight disk-space check on bulk + single-file paths (M2),
configurable trash auto-purge with a dedicated 04:00 daily job
(M4, scheduler job count 16→17), per-job force-OCR override +
default preference (C5), unified structural-hash helper with
round-trip test (S4), and an enhanced `/api/convert/preview`
endpoint with zip-bomb check + estimated duration +
`ready_to_convert` verdict (S1). Full context:
[`docs/version-history.md`](docs/version-history.md).

---

### v0.23.5 (carried-forward summary) — Search shortcuts + startup crash fix

Ten new Search page keyboard shortcuts (`/`, `Esc`, `Alt+Shift+A`,
`Alt+A`, `Alt+Shift+D`, `Alt+Click`, `Shift+Click`, and more). Plus
two critical startup crash fixes: migration FK enforcement
(`_run_migrations` now runs with `PRAGMA foreign_keys=OFF`) and MCP
server race (MCP no longer calls `init_db()`, polls for
`schema_migrations` instead). Full context:
[`docs/version-history.md`](docs/version-history.md).

---

### v0.23.4 (carried-forward summary) — Settings page reorganization

Renamed and regrouped 21 Settings sections into logical clusters:
Files and Locations (with Password Recovery, File Flagging, Info,
Storage Connections), Conversion Options (with OCR, Path Safety),
AI Options (with Vision, Claude MCP, Transcription, AI-Assisted
Search). Full context:
[`docs/version-history.md`](docs/version-history.md).

---

### v0.23.3 (carried-forward summary) — UX responsiveness + features

Migration hardening (migration 27 re-runs bulk_files rebuild, narrowed
except:pass to ALTER only), batch empty-trash with progress polling,
bulk restore, extension exclude (`scan_skip_extensions`), progress
feedback on all heavy UI actions.
Full context: [`docs/version-history.md`](docs/version-history.md).

---

### v0.23.1-v0.23.2 (carried-forward summaries)

**v0.23.2:** Critical bug fixes — bulk upsert ON CONFLICT, scheduler
coroutine, vision MIME detection.
**v0.23.1:** Database file handler — SQLite, Access, dBase, QuickBooks
schema + sample data extraction into Markdown.
Full context: [`docs/version-history.md`](docs/version-history.md).

---

### v0.23.0 (carried-forward summary) — audit remediation

20-task overhaul: DB connection pool, preferences cache, bulk_files
dedup, incremental scanning, counter batching, PyMuPDF default,
vision MIME fix, frontend polling reduction.
Full context: [`docs/version-history.md`](docs/version-history.md).

---

### v0.22.18-v0.22.19 (carried-forward summaries)

**v0.22.19:** Scan-time junk-file filter + one-time historical cleanup
(~$* Office lock files, Thumbs.db, desktop.ini, .DS_Store).
**v0.22.18:** Four production-readiness fixes from runtime-log audit
(~2,500 noisy events/24h eliminated).
Full context: [`docs/version-history.md`](docs/version-history.md).

---

### v0.22.17 (carried-forward summary) — overnight rebuild self-healing pipeline

**Six phases (0-5):** 0 Preflight (prereqs + `expectGpu` auto-detect
via `nvidia-smi.exe`) -> 1 Source sync (retry 3x) -> 1.5 Anchor
last-good (capture `:latest` IDs, tag as `:last-good`, write
`Scripts/work/overnight/last-good.json` sidecar — **runs BEFORE
build** because BuildKit GCs the old image the moment `:latest` is
reassigned) -> 2 Image build (retry 2x) -> 3 Start + 20s lifespan
pause + race override -> 4 Verify (`Test-StackHealthy` + `Test-
GpuExpectation` + `Test-McpHealth` on port 8001) -> 5 Success. On
verification failure after the `up -d` commit point, `Invoke-Rollback`
retags `:last-good` -> `:latest` and recreates with `--force-recreate`,
then re-verifies.

**Five exit codes:** 0 clean / 1 pre-commit failure (old build still
running) / 2 rollback succeeded (old build running, new build needs
investigation) / 3 rollback attempted but failed (stack DOWN) / 4
rollback refused because `docker-compose.yml`, `Dockerfile`, or
`Dockerfile.base` changed since the last-good commit (stack DOWN,
compose-old-image mismatch would silently half-work).

**No auto-remediation.** Crashed containers, disk-pressure pruning,
git reset-on-conflict were all explicitly rejected in the brainstorm
and stay rejected — they hide real bugs. The only recovery is
blue/green to a known-good image pair.

**Phase 4 catches the v0.22.15 / v0.22.16 regression class.**
`Test-GpuExpectation` parses `components.gpu.execution_path` and
`components.whisper.cuda` from `/api/health` and asserts a GPU host
actually sees its GPU end-to-end. The field name was corrected during
implementation against the live payload: CLAUDE.md v0.22.16 referenced
`cuda_available`, which is a structlog event field, NOT the HTTP
response key (which is just `cuda`).

**Portable via auto-detect.** `$expectGpu` resolves to `container` on
hosts with `nvidia-smi.exe` and `none` otherwise, so the same script
works unchanged on CPU-only friend-deploys. The design spec originally
called for `wsl.exe -e nvidia-smi` but that's wrong on the reference
host (the default WSL2 distro doesn't have nvidia-smi installed —
Docker Desktop's GPU path is independent) — see spec §11 for the
deviation rationale.

**Two new PowerShell gotchas documented** in `docs/gotchas.md` under
a new "Overnight Rebuild & PowerShell Native-Command Handling" section:
(1) `Start-Transcript` doesn't capture native-command output in PS 5.1,
and the only reliable fix is `SilentlyContinue` + variable capture
(not `ForEach-Object`); (2) `docker-compose ps --format json` cannot
be regex'd across fields because `Publishers` has nested `{}` — parse
NDJSON line-by-line with `ConvertFrom-Json`.

**Validation performed:** parser clean; dry-run end-to-end; **three
staged live runs**, the last of which went fully green (exit 0 in
1:36). The first two caught four real bugs: (A) Phase 2.5
retag-after-build was structurally impossible because BuildKit GCs
the old image on tag reassignment — fix was moving retag + sidecar
into Phase 1.5 before the build; (B) `Test-StackHealthy` leaked
`NativeCommandError` decoration on every compose-ps call because it
used `EAP=Continue` instead of `SilentlyContinue` (same class as the
v0.22.16 follow-up); (C) `Invoke-RetagImage` swallowed stderr with
`Out-Null`, hiding the Bug A error from the morning log; (D) Phase
3's race-override path probed health immediately after `up -d`,
without the 20s lifespan wait, causing a FALSE ROLLBACK of a
functionally-identical build on the second staged run — fix moved
the lifespan pause into Phase 3 (both clean-exit and race-override
branches) and added the same pause to `Invoke-Rollback`'s recreate
step. **Still deferred:** forced-rollback rehearsal with a
deliberately-broken runtime build, and compose-divergence rehearsal
(exit 4 path). Recommended before the next unattended cycle — though
the Bug D false-rollback did inadvertently exercise the rollback
path end-to-end.

v0.22.15 known follow-ups (broken Convert-page SSE, uncancellable
`asyncio.wait_for` on Whisper, corrupt-audio tensor reshape) are still
outstanding.

**All prior versions** (v0.13.x – v0.22.14) are documented per-release in
[`docs/version-history.md`](docs/version-history.md). **Do NOT duplicate that
changelog here.** On each release, the outgoing "Current Version" block above
moves into `version-history.md` and is replaced with the new release notes.

**Planned:** External log shipping to Grafana Loki / ELK. The current local
log archive system is interim.

---

## Pre-production checklist

- ~~**Lifecycle timers**~~ — **DONE** (v0.23.3). Defaults and DB both at
  production values: grace=36h, retention=60d. Adjustable via Settings UI.
- **Security audit** (62 findings: 10 critical + 18 high + 22 medium + 12
  low/info in `docs/security-audit.md`) not yet addressed.

**Temporary instrumentation:** DB contention logging was retired in
v0.24.2 (`core/db/contention_logger.py` deleted, all call sites cleaned
up). No temporary instrumentation currently active.

---

## Architecture Reminders

- **Per-machine paths via `.env`** — `docker-compose.yml` uses `${SOURCE_DIR}`, `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}`. Each machine gets its own gitignored `.env`. See `.env.example`.
- **No Pandoc** — library-level only.
- **No SPA** — vanilla HTML + fetch calls.
- **Fail gracefully** — one bad file never crashes a batch.
- **Fidelity tiers:** Tier 1 = structure (guaranteed), Tier 2 = styles (sidecar), Tier 3 = original file patch.
- **Content-hash keying** — sidecar JSON keyed by SHA-256 of normalized paragraph/table content.
- **Format registry** — handlers register by extension, converter looks up by extension.
- **Unified scanning** — all formats go through the same pipeline (no Adobe/convertible split).
- **source_files vs bulk_files** — `source_files` is the single source of truth for file-intrinsic data (path, size, hash, lifecycle); `bulk_files` links jobs to source files via `source_file_id`. Cross-job queries MUST use `source_files` to avoid duplicates.
- **Scan priority:** Bulk > Run Now > Lifecycle. Enforced by `core/scan_coordinator.py`.
- **Folder drop** — Convert page accepts whole folders via drag-and-drop.

All phases 0–11 are **Done**. Phase 1 historical spec: [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md).

---

## Critical Files (full table: [`docs/key-files.md`](docs/key-files.md))

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, router mounts |
| `core/db/` | Domain-split DB package (connection, pool, schema, bulk, lifecycle, auth, migrations, ...) |
| `core/db/pool.py` | Single-writer connection pool + async write queue (v0.23.0) |
| `core/preferences_cache.py` | In-memory TTL cache for DB preferences (v0.23.0) |
| `core/converter.py` | Pipeline orchestrator (single-file conversion) |
| `core/bulk_worker.py` | Worker pool: BulkJob, pause/resume/cancel, SSE |
| `core/scan_coordinator.py` | Scan priority coordinator (Bulk > Run Now > Lifecycle) |
| `core/scheduler.py` | APScheduler: lifecycle scan, trash expiry, DB maintenance, pipeline watchdog |
| `core/auth.py` | JWT validation, role hierarchy, API key verification |
| `Dockerfile.base` / `Dockerfile` | Base (system deps) + app (pip + code) |
| `docker-compose.yml` | Ports: 8000 app, 8001 MCP, 7700 Meilisearch |

---

## Top Gotchas (full list: [`docs/gotchas.md`](docs/gotchas.md))

The ones that bite hardest and most often — read the full file for the rest.

- **aiosqlite**: Always `async with aiosqlite.connect(path) as conn`. Never `await` then `async with`.
- **structlog**: Use `structlog.get_logger(__name__)` everywhere, never `logging.getLogger()`. `import structlog` in every file that calls it.
- **pdfminer logging**: Must set `pdfminer.*` loggers to WARNING in `configure_logging()`, or debug log grows 500+ MB per bulk job.
- **`python-jose` not `PyJWT`** — they conflict.
- **`DEV_BYPASS_AUTH=true` is the default** — production must set to `false`.
- **Source share is read-only**: `/mnt/source` mounted `:ro`.
- **Scheduled jobs yield to bulk jobs**: lifecycle scan, trash expiry, DB compaction, integrity check, stale data check all call `get_all_active_jobs()` and skip if any bulk job is scanning/running/paused. Prevents "database is locked".
- **Pipeline has two pause layers**: `pipeline_enabled` (persistent DB pref) and `_pipeline_paused` (in-memory, resets on restart). Scheduler checks both. "Run Now" bypasses both.
- **Frontend timestamps must use `parseUTC()`**: SQLite round-trips can strip the `+00:00` offset. `parseUTC()` in `app.js` appends `Z`. Never `new Date(isoString)` directly for backend timestamps.
- **Vector search is best-effort**: `get_vector_indexer()` returns `None` when Qdrant is unreachable. All call sites must handle `None`.
- **No non-ASCII in `.ps1` scripts**: Windows PowerShell 5.1 reads BOM-less UTF-8 as Windows-1252 and em-dashes become `â€"`, breaking string parsing. ASCII only.
- **`worker_capabilities.json` is per-machine**: gitignored, generated by refresh/reset scripts. Never commit.
- **MCP server binding**: `FastMCP.run()` does NOT accept `host`/`port`. Use `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)`. Endpoint is `/sse`, not `/mcp`. `/health` must be added manually as a Starlette route.

---

## Supported Formats

Full category-by-category list with every extension and its handler:
[`docs/formats.md`](docs/formats.md). Covers ~100 extensions across Office,
OpenDocument, Rich Text, Web, Email, Adobe Creative, archives, audio, video,
images, fonts, code, config, and binary metadata.

---

## Running the App

```bash
# First time only — build the base image (slow, ~25 min HDD / ~5 min SSD):
docker build -f Dockerfile.base -t markflow-base:latest .

# Normal operation:
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
(Only rebuilds pip + code layer — base image is cached.)
