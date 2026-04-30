# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Detailed references live in `docs/`.

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — Python/FastAPI web app
that converts documents bidirectionally between their original format and
Markdown. Runs in Docker. GitHub: `github.com/theace26/Doc-Conversion-2026`.

## Project documentation map

Read on demand — none of these are auto-loaded.

### Core engineering references (read first when working on code)

| File | Read it when... |
|------|-----------------|
| [`docs/bug-log.md`](docs/bug-log.md) | **Forward-looking register of open / planned bugs.** Triage a new bug here FIRST — it may already be tracked. MUST be updated on every release that fixes a bug (move row to Shipped + set `shipped-vX.Y.Z`) AND when a new bug is discovered. Cross-references plans, gotchas, security-audit by ID. |
| [`docs/gotchas.md`](docs/gotchas.md) | Hard-won subsystem-specific lessons (~100 items). **Always check the relevant section before modifying or debugging code in that area.** |
| [`docs/key-files.md`](docs/key-files.md) | 189-row file reference table mapping every important file to its purpose. |
| [`docs/version-history.md`](docs/version-history.md) | Detailed per-version changelog (one entry per release, full context). Append a new entry on every release. |

### Pre-production / hardening

| File | Read it when... |
|------|-----------------|
| [`docs/security-audit.md`](docs/security-audit.md) | 62 findings (10 critical + 18 high + 22 medium + 12 low/info). **Pre-prod blocker.** Read when working on auth, JWT, role guards, input validation, or anything customer-data-sensitive. |
| [`docs/streamlining-audit.md`](docs/streamlining-audit.md) | Code-quality / DRY audit, all 24 items resolved across v0.16.1–v0.16.2. History only. |

### Integration / contracts

| File | Read it when... |
|------|-----------------|
| [`docs/unioncore-integration-contract.md`](docs/unioncore-integration-contract.md) | API contract between MarkFlow and UnionCore (Phase 10 auth integration). Touch when changing `/api/search/*` shape, JWT validation, or anything UnionCore consumes. |
| [`docs/MarkFlow-Search-Capabilities.md`](docs/MarkFlow-Search-Capabilities.md) | Stakeholder-facing capability brief (last updated v0.22.0). |

### Operations & user docs

- [`docs/drive-setup.md`](docs/drive-setup.md) — end-user host-drive sharing for Docker (Win/Mac/Linux).
- [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md) — original Phase 1 design spec. Historical only.
- `docs/help/*.md` — 24 user-facing help articles rendered in the in-app help drawer. Update when shipping user-visible features.
- `docs/superpowers/plans/*.md` and `docs/superpowers/specs/*.md` — written plans and design specs for major features. Historical / context-only once shipped.

### Documentation discipline (per release)

On every release that fixes a bug or introduces a known one, all of these
update together — `bug-log.md` is the canonical ledger that ties them:

1. **`core/version.py`** — bump `__version__` to the new release. This is the single source of truth queried by `/api/version` and the `/api/health` payload. Forgetting this step makes every release after the miss appear stale to clients (caught during v0.34.5 deploy: v0.34.2–v0.34.5 all shipped with the constant still reading `0.34.1`).
2. **`docs/bug-log.md`** — move shipped rows to Shipped section (set `status: shipped-vX.Y.Z`). Add new `BUG-NNN` rows for any newly discovered bugs.
3. **`docs/version-history.md`** — append the per-release narrative entry; cite `BUG-NNN` IDs.
4. **`docs/help/whats-new.md`** — operator-facing summary for any user-visible bug fix.
5. **`docs/gotchas.md`** — if the fix exposed a class of bug worth not recreating, add a row in the relevant subsystem section (cite `BUG-NNN`).
6. **`CLAUDE.md`** — update the Current Version block.

For a feature-only release, step 2 (bug-log Shipped migration) is
skipped but the bug-log is still re-checked for items the release
might affect (apply the `checking-blast-radius` skill before shipping).

### Rule of thumb

If a task touches **bulk / lifecycle / auth / password / GPU / OCR /
search / vector**, read the relevant `gotchas.md` section first. For
"what changed and why", jump to `version-history.md`. For "where does X
live", `key-files.md`. For "is this bug already known", `bug-log.md`.

---

## Current Version — v0.34.7

**Auto-conversion is now actually converting files for the first time
since the v0.34.x sequence began. v0.34.3+v0.34.4 unblocked the
*scheduling* layer; v0.34.5 verified the scheduling held; v0.34.6
fixed a misleading disk metric. But every worker attempt was still
failing for two reasons that only surfaced under a post-v0.34.6 log
audit. Both shipped here.**

- **BUG-014 (critical): write guard was denying every write.**
  `core/storage_manager.is_write_allowed()` consulted only the
  Storage-Manager-populated `_cached_output_path` sentinel. On
  this VM that pref had never been set (no operator visit to the
  Storage page) so the cache stayed `None` and every call returned
  `False` — including against paths clearly inside
  `BULK_OUTPUT_PATH=/mnt/output-repo`. The bulk_files table had
  accumulated dozens of `write denied — outside output dir:
  /mnt/output-repo/...` rows on paths that were clearly under
  `/mnt/output-repo`. Fix: route the guard through the v0.34.1
  `core.storage_paths.resolve_output_root_or_raise()` priority chain
  (Storage Manager > BULK_OUTPUT_PATH > OUTPUT_DIR), preserving the
  v0.25.0 "absent configuration → deny" intent (resolver raises;
  guard treats as deny).
- **BUG-015 (high): Excel handler crashed on Chartsheets.** openpyxl
  returns `Chartsheet` objects for sheets containing only an
  embedded chart. Both `formats/xlsx_handler.py:ingest()` and
  `_extract_styles_impl()` accessed `.merged_cells` unconditionally,
  AttributeError-ing on those sheets. 11 files affected. Fix: duck-
  typed `hasattr(ws, "merged_cells")` guard; chartsheets are skipped
  with a `xlsx_chartsheet_skipped` log line.

Together these two were responsible for the auto-converter tripping
its 20-error abort threshold in the first 20 attempts of every cycle
since at least 2026-04-29 16:33 — `error_rate=1.0` despite the
scheduling layer being healthy. Zero files converted across at least
5 consecutive auto-runs. With both fixed the abort threshold should
now only fire on genuine errors (corrupt PDFs, LibreOffice flakes),
which exist in the long tail but should be a small minority of
attempts.

### What operators should see

- The Activity / Pipeline page's **indexed** counter starts climbing
  for the first time in days as the auto-converter actually
  succeeds. Expected throughput at observed scan rates is
  ~250 files/min when actively working.
- `bulk_files` rows with status `failed` and `error_msg` starting
  `write denied — outside output dir:` stop accumulating. Existing
  pre-v0.34.7 rows still reflect the bug; that's expected.
- `/api/version` and `/api/health` report `0.34.7`.

### Loose ends still tracked from prior releases

Carried forward; not re-implemented here:

1. **No operator-facing alert** when auto-conversion fails N cycles
   in a row. UX overhaul §13 (Notifications) covers the trigger-rule
   infrastructure.
2. **No "scanned vs indexed delta" surface** — Plan 4 (UX IA shift)
   will surface this on the Activity dashboard.
3. **Failure-path explicit `completed_at` writes** — the bulk_job
   pre-flight failure handler should write
   `auto_conversion_runs.completed_at` directly rather than relying
   on the startup orphan reaper as a backstop.
4. **LibreOffice headless flakes** on `.xls` files (`exited 0 but
   produced no output file`). Likely parallel-worker contention on
   `~/.config/libreoffice` profile dir. Tracked for a future
   hardening pass; not blocking now that the dominant failures
   above are fixed.
5. **Log spam:** `bulk_worker_error_rate_abort` fires once per
   worker per pull *after* abort is signaled, producing thousands
   of duplicate lines for one job. A "log once per abort" guard
   would be cheap; not blocking.

Full per-version detail (v0.34.6 and every prior release back to v0.13.x)
lives in [`docs/version-history.md`](docs/version-history.md). **Do not
duplicate that changelog here.** On each release, the outgoing Current
Version block above moves into `version-history.md` and is replaced with
the new release notes.

---

## Pre-production checklist

- ~~**Lifecycle timers**~~ — DONE (v0.23.3). Production values: grace=36h, retention=60d.
- **Security audit** — 62 findings (10 critical + 18 high + 22 medium + 12 low/info) in `docs/security-audit.md`. ~54 outstanding.

No temporary instrumentation currently active.

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
- **Output paths** — always go through `core/storage_paths.get_output_root()` (v0.34.1). Never capture as a module-level constant.
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
| `core/storage_paths.py` | Output-root resolver — single source of truth (v0.34.1) |
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

Full category-by-category list: [`docs/formats.md`](docs/formats.md).
~100 extensions across Office, OpenDocument, Rich Text, Web, Email, Adobe
Creative, archives, audio, video, images, fonts, code, config, and binary
metadata.

---

## Running the App

```bash
# First time — or whenever Dockerfile.base changes (apt packages,
# torch version, etc.) — rebuild the base (~25 min HDD / ~5 min SSD):
docker build -f Dockerfile.base -t markflow-base:latest .

# Normal operation:
docker-compose up -d           # start
docker-compose logs -f         # watch logs
curl localhost:8000/api/health # verify
docker-compose down            # stop
```

After code changes: `docker-compose build && docker-compose up -d`
(Only rebuilds pip + code layer — base image is cached.)

**When does the base need rebuilding?** Anytime `Dockerfile.base` changes
— new apt packages, a torch version bump, etc. To check after pulling
a branch:

```bash
git diff <last-known-good-sha>..HEAD -- Dockerfile.base requirements.txt
```

If non-empty and touching apt packages, do the full sequence: base build
→ `docker-compose build` → `docker-compose up -d`.
