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

## Current Version — v0.34.9

**Closes BUG-018 — the "the abort safeguard didn't fire on the v0.34.7
stuck run" mystery. Turns out the safeguard *was* firing in memory;
the DB persistence was just gated on `asyncio.gather(*workers)`
returning, which a single stuck worker can prevent indefinitely.
Move the persistence to the abort site itself.**

- **BUG-018 (medium):** `core/bulk_worker.py:713` correctly fires
  the abort decision when `should_abort()` returns True
  (`consecutive_errors >= 20`), but only sets `_cancel_reason` in
  memory + sets `_cancel_event`. The DB write that materialises
  `bulk_jobs.cancellation_reason` lives at line 591, AFTER
  `await asyncio.gather(*workers)`. If any worker is blocked
  inside `_process_convertible` (long Whisper, frozen CIFS read,
  etc.), `gather` never returns and the cancellation is invisible
  to the UI / startup reaper / operators. Fix: persist the abort
  to the DB at the abort site itself via `update_bulk_job_status()`,
  guarded by a one-shot `_abort_persisted` flag so the per-worker
  re-observation collapses to a single action per job (also
  eliminates the `bulk_worker_error_rate_abort` log/event spam
  that previously fired once per worker per pull after abort was
  signaled).

### What operators should see

- When the bulk worker's "too many errors, abort" safeguard fires,
  `bulk_jobs.cancellation_reason` and `bulk_jobs.status='cancelled'`
  appear within the same heartbeat tick — not "after every worker
  drains the queue" (which a stuck worker can prevent).
- `markflow.log` growth from aborted jobs drops dramatically —
  from "once per worker per pull after abort" to "once per
  aborted job".
- `/api/version` reports `0.34.9`.

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
5. **No audio-capable cloud provider configured.** Local Whisper
   on CPU works for everyday volume but is slow for hours-long
   archives. Add an OpenAI or Gemini API key on the Settings → AI
   Providers page if offload is needed; Anthropic does not
   currently support audio.
6. **Worker heartbeat freezes during multi-minute Whisper
   transcriptions.** Workers correctly hold the threading.Lock
   through CPU inference, but the heartbeat updater inside the
   worker loop doesn't tick during the blocking call. Operators
   see a job that looks "stuck" while it's actually working.
   Likely fixed by either a per-file deadline or a separate
   heartbeat coroutine. Not blocking; cosmetic.

### Audit hints from this release sequence

- **BUG-016 lesson:** module-level asyncio primitives (`asyncio.Lock`,
  `Event`, `Condition`, `Queue`, `Semaphore`) silently bind to
  whichever loop first uses them. Mixed-loop code paths
  (`asyncio.run` inside a thread pool) will then fail with
  `is bound to a different event loop`. Worth a one-time grep for
  other module-level constructions of these types if a similar
  symptom resurfaces.
- **BUG-018 lesson:** for state transitions that matter to
  operators (status flips, cancellations, abort decisions), persist
  at the *decision site*, not at the *closeout site*. Other
  `_cancel_event.set()` sites in `core/bulk_worker.py`
  (lines 905, 1301-1302, 1507, 1526) likely have the same coupling
  to the post-gather write — out of scope for this release but
  worth a similar audit if a bug like BUG-018 resurfaces in any
  of those paths.

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
