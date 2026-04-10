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
| [`docs/security-audit.md`](docs/security-audit.md) | Findings-only security audit performed at v0.16.0. **62 findings, 3 critical + 5 high — pre-prod blocker.** Read when working on auth, input validation, JWT, role guards, or anything customer-data-sensitive. |
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

## Current Version — v0.23.5

**Search page keyboard shortcuts + migration FK fix.** Ten new
keyboard shortcuts on the Search page (`/`, `Esc`, `Alt+Shift+A` for
AI Assist, `Alt+A` select-all, `Alt+Shift+D` download zip,
`Alt+Click` direct download, `Shift+Click` range-select, and more)
plus a critical startup crash fix. Full context:
[`docs/version-history.md`](docs/version-history.md).

- **Search shortcuts** — `static/search.html` global keydown handler
  + per-row Alt-click diversion to the download endpoint + shift-click
  range selection. Discoverable via the search input `title` tooltip.
- **Help docs** — new `docs/help/whats-new.md` version page,
  rewritten `search.md` with vector + AI Assist worked examples,
  rewritten `settings-guide.md` for v0.23.4 layout, expanded
  `keyboard-shortcuts.md`, registered in `_index.json`.
- **Crash fix: migration FK** — `_run_migrations` in `core/db/schema.py`
  now commits and `PRAGMA foreign_keys=OFF` before running migrations,
  so schema rebuilds (migration 27 bulk_files) carry historical
  orphan rows through instead of aborting on FK violation. init_db
  re-enables FKs after the batch.
- **Crash fix: MCP migration race** — `mcp_server/server.py` no
  longer calls `init_db()`. MCP is a reader; the main container owns
  schema. MCP now polls for `schema_migrations` existence (2-minute
  cap) before starting.

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
- **Security audit** (62 findings in `docs/security-audit.md`) not yet addressed.

**Temporary instrumentation (deactivate when resolved):**
- **DB contention logging (v0.19.6.5):** `db-contention.log`, `db-queries.log`,
  `db-active.log` via `core/db/contention_logger.py`. High-volume during scans.
  Remove once "database is locked" is fully diagnosed.

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
