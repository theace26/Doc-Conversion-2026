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

1. **`docs/bug-log.md`** — move shipped rows to Shipped section (set `status: shipped-vX.Y.Z`). Add new `BUG-NNN` rows for any newly discovered bugs.
2. **`docs/version-history.md`** — append the per-release narrative entry; cite `BUG-NNN` IDs.
3. **`docs/help/whats-new.md`** — operator-facing summary for any user-visible bug fix.
4. **`docs/gotchas.md`** — if the fix exposed a class of bug worth not recreating, add a row in the relevant subsystem section (cite `BUG-NNN`).
5. **`CLAUDE.md`** — update the Current Version block.

For a feature-only release, step 1 is skipped but the bug-log is still
re-checked for items the release might affect (apply the
`checking-blast-radius` skill before shipping).

### Rule of thumb

If a task touches **bulk / lifecycle / auth / password / GPU / OCR /
search / vector**, read the relevant `gotchas.md` section first. For
"what changed and why", jump to `version-history.md`. For "where does X
live", `key-files.md`. For "is this bug already known", `bug-log.md`.

---

## Current Version — v0.34.5

**Verification milestone. v0.34.3 (BUG-011) + v0.34.4 (BUG-012)
confirmed working end-to-end on the production K-drive workload via
live-log evidence. No new code; this is a docs-only bump that captures
the one-shot manual cleanup performed during investigation and the
proof-of-fix evidence so future debugging has a clear reference.**

### What was verified in production

After v0.34.4 deployed, run-now triggered a fresh auto-conversion
cycle. The `bulk_disk_precheck` log event fired with the new
`multiplier=0.5`, the pre-check passed (250 GB × 0.5 = 125 GB needed
vs 158 GB free), and a bulk_job entered `running` status. Live
scan_progress events captured the worker enumerating files at
130–360 files/sec:

```
23:34:53 scan_coordinator.run_now_paused reason=bulk_job_started:8a472712...
23:34:57 scan_progress completed=608   files_per_second=360
23:35:02 scan_progress completed=1408  files_per_second=215
23:35:07 scan_progress completed=2008  files_per_second=163
23:35:33 scan_progress completed=5408  files_per_second=142
```

This is the first successful auto-triggered bulk_job since 2026-04-07
on the affected machine — proof both fixes hold under real load.

### One-shot manual cleanup performed during investigation

To unblock the verification (the v0.34.4 startup reaper hadn't yet
been deployed when investigation began), 38 stale `auto_conversion_runs`
rows accumulated since 2026-04-07 were cleaned manually via SQL:

```sql
UPDATE auto_conversion_runs SET status='failed', completed_at=now()
WHERE status='running' AND completed_at IS NULL;
```

Plus zero stale `bulk_jobs` (the existing reaper had already cleaned
those at the v0.34.3 container restart). Going forward, the v0.34.4
startup reaper handles this on every container start — no operator
intervention needed for future occurrences.

### Loose ends captured for follow-up

These were discovered during the investigation but are NOT shipping
in this release. They're tracked as part of the upcoming UX overhaul
spec (`docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md`):

1. **No operator-facing alert** when auto-conversion fails N cycles
   in a row. Currently logged at `info` level only. UX overhaul §13
   (Notifications) covers the trigger-rule infrastructure that will
   power this alert.
2. **No "scanned vs indexed delta" surface** — the gap between
   `source_files` count and Meilisearch index count is the leading
   indicator that conversion is wedged. Plan 4 (UX IA shift) will
   surface this on the Activity dashboard.
3. **Failure-path explicit `completed_at` writes** — the bulk_job
   pre-flight failure handler should write `auto_conversion_runs.completed_at`
   directly rather than relying on the startup orphan reaper as a
   backstop. Tracked as a future hardening pass; not urgent now that
   the reaper exists.

Full per-version detail (v0.34.2 and every prior release back to v0.13.x)
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
- **Per-user preferences are portable** — `core/user_prefs.py` stores per-user prefs (layout, density, etc.) in the `mf_user_prefs` table keyed by UnionCore subject claim. **Distinct from** the existing `core/db/preferences.py` + `user_preferences` table (system-level singletons; do not conflate). Client mirror in `localStorage` via `static/js/preferences.js` (Plan 1B) with debounced server sync to `/api/user-prefs`. Spec: `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §10.
- **Role hierarchy from JWT** — `core.auth.Role` IntEnum (MEMBER=0 < OPERATOR=1 < ADMIN=2). Use `extract_role(claims)` and `role >= Role.OPERATOR` for visibility gates. Spec §11.
- **`ENABLE_NEW_UX` feature flag** — gates new UX rendering across Plans 1B and beyond. Default off in prod until phase 4 ships. Read via `core.feature_flags.is_new_ux_enabled()`.
- **Design tokens are CSS variables** — `static/css/design-tokens.css` is the single source of truth for colors, type, spacing, shadows. Never hardcode hex outside that file. Component CSS in `static/css/components.css` consumes tokens via `var(--mf-*)`.

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
| `core/user_prefs.py` | Server-side **per-user** preferences (portable, JSON value, schema versioned). Distinct from `core/db/preferences.py` (system singletons). |
| `core/feature_flags.py` | Feature flag accessors (e.g. `is_new_ux_enabled()`) |
| `static/css/design-tokens.css` | Visual system as CSS variables — single source of truth |
| `static/css/components.css` | Shared component classes (pills, toggles, segmented, pulse, role pill, version chip) |

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
