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
| [`docs/bug-log.md`](docs/bug-log.md) | **Forward-looking register of open / planned bugs.** Single source of truth for "what's broken right now." Status-tracked (open / planned / in-progress / shipped-vX.Y.Z / wontfix). **Read FIRST when triaging a new bug report** — it may already be tracked. **MUST be updated on every release that fixes a bug** (move row to Shipped section + set `shipped-vX.Y.Z` status) AND when any new bug is discovered (add a row with `open` status). Cross-references plans, gotchas, security-audit by ID — does NOT duplicate their content. |
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
| [`bug-log.md`](docs/help/bug-log.md) | Operator-facing explainer of the engineering bug-log + how it's used (v0.34.x) |

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
For "is this bug already known / planned?" questions, jump to `bug-log.md`.

### Documentation discipline (per release)

On **every release** that fixes a bug or introduces a known bug, the
following docs MUST be updated together — the bug-log is the canonical
ledger that ties them all together:

1. **`docs/bug-log.md`** — move the relevant row(s) from Open / Planned
   to Shipped (history); set `status: shipped-vX.Y.Z`. If the release
   discovered new bugs, add new `BUG-NNN` rows with `status: open`.
2. **`docs/version-history.md`** — append the per-release narrative
   entry; if the release closed a bug, the entry references the
   `BUG-NNN` ID(s).
3. **`docs/help/whats-new.md`** — operator-facing summary for any
   user-visible bug fix.
4. **`docs/gotchas.md`** — if the fix exposed a class of bug worth
   not recreating, add a row in the relevant subsystem section
   (cite the `BUG-NNN` for traceability).
5. **`CLAUDE.md`** — update the Current Version block.

If a release doesn't fix a bug (e.g. pure feature add), step 1 is
skipped but the bug-log is still re-checked for any open items the
release might inadvertently affect (apply the
`checking-blast-radius` skill before shipping).

---

## Current Version — v0.34.1

**Convert-page write-guard + folder-picker fix + 5 silent-failure
consumers — single-cut bug-fix release closing 9 entangled bugs
(BUG-001..009 in `docs/bug-log.md`). Tied together by `OUTPUT_BASE`
having been captured as a module-level constant at import time across
6 consumers, each silently drifting from the Storage Manager (v0.25.0+)
configured path. New `core/storage_paths.py` resolver becomes the
single source of truth; Convert page picker now always populates its
drives sidebar even on initial-navigation failure.**

### Why this matters

Operator hit two visible failures from one click on the Convert page:
(1) drop a PDF → write-guard rejection; (2) click Browse → modal
opens with empty drives sidebar. Diagnosis traced both to 4 root
causes plus 5 silent-failure consumers downstream — Download Batch
404, History download 404, **lifecycle scanner walking the wrong
tree → no soft-delete tracking**, MCP returning wrong paths to AI
clients, `/ocr-images` mount serving from wrong dir. All 9 fixed in
one cut to avoid v0.34.1 + v0.34.2 + ... patches drifting across the
codebase.

### What changed

**1. New shared resolver `core/storage_paths.py`** (~120 LOC).
`get_output_root()` consults Storage Manager > BULK_OUTPUT_PATH >
OUTPUT_DIR > fallback `output/`. Pure function, re-resolves on every
call so Storage Manager runtime reconfigs take effect without a
restart.

**2. Convert page chain** — `api/routes/convert.py` validates
`output_dir` Form param against `is_write_allowed()` early and
threads it through `_run_batch_and_cleanup` to
`convert_batch(output_dir=...)`. HTTP 422 with structured error
payload when rejected. New `convert.output_dir_resolved` /
`convert.output_dir_rejected` log events. `core/converter.py`
`ConversionOrchestrator` re-resolves default output base per-batch.

**3. 5 downstream consumers unified behind the resolver**:
`api/routes/batch.py:_batch_dir` (BUG-005), `api/routes/history.py`
download path (BUG-006), `core/lifecycle_manager.py:OUTPUT_REPO_ROOT`
→ getter w/ 4 call sites (BUG-007 — the dangerous one), `mcp_server/
tools.py:OUTPUT_DIR` → getter w/ 4 call sites (BUG-008), `main.py:507`
`/ocr-images` mount (BUG-009; caveat: mount binds at app startup and
needs container restart for runtime Storage Manager reconfigs).

**4. Folder picker fixes** (`static/js/folder-picker.js`):
`_loadDrivesSidebar()` always populates drives BEFORE attempting the
requested startPath (BUG-001 — empty sidebar on failed nav).
`_isBrowsablePath(p)` mirrors `ALLOWED_BROWSE_ROOTS`; non-browsable
initialPaths remap to `/mnt/output-repo` (output mode) or `/host`
(other modes) (BUG-002).

**5. Convert page Output Directory** (`static/index.html`) — seeds
from `/api/storage/output` before falling back to last-save-directory
preference. Picker `initialPath` no longer falls back to legacy
`/app/output`.

**6. `tests/test_convert_output_dir.py`** — 7 new tests covering
resolver priority chain + 422 paths.

**7. `docs/bug-log.md`** — BUG-001..009 moved to Shipped (history)
section, marked `shipped-v0.34.1`.

### Files

- `core/version.py` — bump to 0.34.1
- `core/storage_paths.py` — NEW (~120 LOC)
- `core/converter.py` — per-batch resolution + `output_dir` param
- `api/routes/convert.py` — validate + propagate `output_dir`
- `api/routes/batch.py`, `api/routes/history.py` — use resolver
- `core/lifecycle_manager.py` — `_output_root()` getter, 4 call sites
- `mcp_server/tools.py` — `_output_dir()` getter, 3 call sites
- `main.py` — `/ocr-images` uses resolver
- `static/js/folder-picker.js` — `_loadDrivesSidebar` +
  `_isBrowsablePath` + `open()` rewrite
- `static/index.html` — Convert page seeds output dir from Storage
  Manager + better placeholder
- `tests/test_convert_output_dir.py` — NEW (7 tests)
- `docs/bug-log.md`, `docs/version-history.md`, `docs/key-files.md`,
  `docs/help/whats-new.md`, `docs/gotchas.md`, `CLAUDE.md`

No DB migration. No new dependencies. No new endpoints.

### Operator-visible change

- Convert page → drop a PDF → conversion completes (was: write-guard
  rejection).
- Convert page → click Browse → drives sidebar visible + output-repo
  contents in main pane (was: empty modal).
- Output Directory field defaults to the Storage Manager configured
  path (was: legacy `/app/output` placeholder).
- Download Batch / History download / Lifecycle scanner / MCP all
  now agree on where output lives.

---

## v0.34.0 (carried-forward summary) — `.prproj` deep handler

`.prproj` files now go through a dedicated parser instead of
AdobeHandler's metadata-only treatment. Streams gzipped XML through
`lxml.iterparse`, harvests every clip path / sequence / bin
defensively, renders structured Markdown, and persists the media-refs
cross-reference to a new `prproj_media_refs` table. Three OPERATOR+
API endpoints (`/api/prproj/{references,…/media,stats}`); preview
page gains "Used in Premiere projects" sidebar card. New
`docs/help/developer-reference.md` covers the full API surface, DB
schema, log event taxonomy, format handler architecture, Docker /
CLI workflows, and operational runbook. Migration v28 (idempotent)
adds the cross-reference table.

---

## v0.33.2 — Token + cost estimation, Phase 2 (UI surfaces)

**Token + cost estimation subsystem — Phase 2 (UI surfaces). Adds the
per-batch Cost Estimate panel on the Batch Management page, the
Provider Spend card on the Admin page (monthly running total +
projection), the Billing & Costs Settings section with the
billing-cycle-start-day input, and a comprehensive
"Programmatic API access" section in `docs/help/admin-tools.md` with
both operator-friendly explanations and developer curl/Python/JS
samples for external integrators (IP2A, finance dashboards).**

### Why this matters

v0.33.1 shipped the backend (data file + module + 6 API endpoints)
and verified it serves real cost data on this instance ($72.10 this
cycle, projected $80.11 across 1,199 analysed files), but operators
had no UI surface. v0.33.2 makes that data visible in the places
operators are already looking — the per-batch click on Batch
Management and the Admin dashboard.

### What changed

**1. Shared module `static/js/cost-estimator.js`** (~270 LOC). Public
surface on `window.CostEstimator`:
- `formatUsd(amount)` / `formatTokens(n)` / `formatRate(rate)`
- `renderBatchCostPanel(container, summary)` — inline panel with
  TOKENS + COST columns, per-file average, rate-used, and a
  collapsible per-file breakdown table (with "estimated" pills on
  extrapolated rows)
- `renderPeriodCostCard(container, period, opts)` — Provider Spend
  card with hero total, by-provider breakdown, cycle progress, and
  end-of-cycle projection. If `opts.staleness.is_stale` is true, an
  amber warning footer reminds the operator to refresh rates.

All DOM via `createElement` + `textContent` (no `innerHTML`,
XSS-safe).

**2. Batch Management page (`static/batch-management.html`)** —
`loadBatchFiles()` now also calls `loadBatchCostPanel(batchId)` which
fetches `/api/analysis/cost/batch/{id}` and renders the panel via the
shared module. Lazy: only fires on first expand. Failure is silent
(cost is informational, not load-bearing).

**3. Admin page (`static/admin.html`)** — new "Provider Spend (LLM
costs)" card in the stats grid. Driven by a new `loadProviderSpend()`
function that fetches `/api/analysis/cost/period` +
`/api/analysis/cost/staleness` in parallel and hands off to
`CostEstimator.renderPeriodCostCard`. Auto-refreshes when the operator
clicks the page's existing **Refresh** button.

**4. Settings page (`static/settings.html`)** — new "Billing & Costs"
collapsible section with `<input type="number"
id="pref-billing_cycle_start_day" data-key="billing_cycle_start_day"
min="1" max="28">`. The page's existing generic save mechanism
(`querySelectorAll('[data-key]')`) picks the new pref up
automatically — no save-handler changes needed.

**5. Comprehensive help docs**
- `docs/help/admin-tools.md` — new "Provider Spend (LLM costs)"
  section with operator examples + worked budgeting example, plus a
  full "Programmatic API access (for external integrators)" section
  with two parallel sub-sections: a simple "for operators" version
  and a developer-technical version with curl, Python, JavaScript,
  and JSON response-shape examples covering all 6 endpoints.
- `docs/help/settings-guide.md` — new "Billing & Costs" entry
  documenting the pref + the rate-table file location + the
  hot-reload endpoint.
- `docs/help/whats-new.md` — user-friendly v0.33.2 entry with
  worked examples.

### Files

- `core/version.py` — bump to 0.33.2
- `static/js/cost-estimator.js` — NEW shared module (~270 LOC)
- `static/batch-management.html` — `loadBatchCostPanel` + script tag
- `static/admin.html` — Provider Spend card + `loadProviderSpend` +
  script tag
- `static/settings.html` — new Billing & Costs section
- `docs/help/admin-tools.md`, `docs/help/settings-guide.md`,
  `docs/help/whats-new.md`, `CLAUDE.md`, `docs/version-history.md`,
  `docs/key-files.md`

No DB migration. No new endpoints (uses v0.33.1's). No new
dependencies. Backend code unchanged from v0.33.1 — pure UI release
on top of the Phase 1 foundation.

---

## v0.33.1 — Token + cost estimation, Phase 1 (backend foundation)

**Token + cost estimation subsystem — Phase 1 (backend foundation).
Ships the rate-table data file, the loader + arithmetic module,
and six API endpoints that translate `analysis_queue.tokens_used`
counts into USD cost estimates per-row, per-batch, and per-
billing-cycle. No UI yet — that's v0.33.2. External programs
like IP2A can already hit these endpoints with the existing
JWT / X-API-Key auth.**

### Why this matters

The image-analysis queue stores `tokens_used` per row but never
translated that into dollars. Operators had no way to estimate
provider-bill exposure without manually running token counts
through a calculator with the published per-1M-token rates.
v0.33.1 closes the gap with a single source of truth
(`core/data/llm_costs.json`) and a clean API. UI surfaces and
operational hardening land in v0.33.2 + v0.33.3.

### Files

- `core/data/llm_costs.json` — NEW. Rate table for
  Anthropic / OpenAI / Gemini / Ollama. Editable; hot-reload
  via POST `/api/admin/llm-costs/reload` (no container restart).
- `core/llm_costs.py` — NEW (~470 LOC). Frozen dataclasses
  (`TokenRate`, `CostEstimate`, `BatchCostSummary`,
  `PeriodCostSummary`, `CostTable`), loader with strict schema
  validation, arithmetic helpers, billing-cycle window math,
  staleness check. Soft-fails to an empty table on disk
  errors so the app keeps starting.
- `api/routes/llm_costs.py` — NEW. Six endpoints:
  - `GET  /api/admin/llm-costs` (OPERATOR+)
  - `POST /api/admin/llm-costs/reload` (ADMIN)
  - `GET  /api/analysis/cost/file/{entry_id}` (OPERATOR+)
  - `GET  /api/analysis/cost/batch/{batch_id}` (OPERATOR+)
  - `GET  /api/analysis/cost/period[?days=N]` (OPERATOR+)
  - `GET  /api/analysis/cost/staleness` (OPERATOR+)
- `main.py` — call `load_costs()` in lifespan after init_db;
  register the new router.
- `core/db/preferences.py` — add `billing_cycle_start_day = "1"`
  default.
- `tests/test_llm_costs.py` — NEW. 17 tests covering schema
  validation, arithmetic, batch extrapolation, cycle-window
  math (start_day=31 cap, year boundary, today-before-start),
  staleness check.

### Best practices baked in

- **Single source of truth**: every caller goes through
  `core.llm_costs` — no scattered rate constants.
- **Schema validation on load**: malformed top-level shape
  raises; bad individual rate rows are skipped + logged
  rather than killing all cost reporting.
- **Defensive degradation**: missing rate → `cost_usd=null`
  + descriptive `error` string. Never blanks, never raises.
- **Operator transparency**: every estimate displays the rate
  used in `rate_used` so calculations are verifiable.
- **Observable**: every `estimate_cost` / `aggregate_*` call
  emits a `llm_cost.computed` (or `llm_cost.no_rate`) log
  line. Searchable in Log Viewer with `?q=llm_cost`.
- **Operational**: hot-reload endpoint avoids restarts.
- **No mutable global state**: `_CACHE` swaps the whole
  frozen dataclass atomically.
- **Backwards compatible**: purely additive — no DB
  migration, no existing endpoint changed.

### Operator-visible change

None yet — v0.33.1 is backend-only. Verify with curl:

```bash
curl -s http://localhost:8000/api/admin/llm-costs | jq .
curl -s 'http://localhost:8000/api/analysis/cost/period' | jq .
curl -s 'http://localhost:8000/api/analysis/cost/staleness' | jq .
```

### External integrators

The cost endpoints respect the existing JWT / `X-API-Key`
auth, so consumers like IP2A can mirror MarkFlow's
source-of-truth rate data + period totals into their own
dashboards. Full curl + Python + JS snippets land in
`docs/help/admin-tools.md` with v0.33.2.

---

## Recent release summaries

Every block below is a one-paragraph carried-forward summary. Full
context (problem, fix, modified files, why-it-matters) for each
release lives in [`docs/version-history.md`](docs/version-history.md).
On each new release the outgoing "Current Version" block is moved
into `version-history.md` and replaced here with a short summary.

### v0.33.3 (carried-forward summary) — Cost estimation Phase 3 (operational hardening)

CSV export of period cost data (`/api/analysis/cost/period.csv`) for
finance imports. Stale-rate amber warning surfaced in API + Admin
Provider Spend card. New daily 03:30 scheduler job
`check_llm_costs_staleness` (job count 18→19) emits `llm_costs.stale`
warning event when `llm_costs.json:updated_at` is older than 90 days.
Help docs gain audit-trail section pointing at
`/api/logs/search?q=llm_cost`.

### v0.33.0 (carried-forward summary) — Pipeline / Lifecycle / Pending cards merged; click-to-enlarge banner

Status page consolidates three overlapping cards (Pipeline +
Lifecycle Scanner + Pending) into a single canonical Pipeline card.
Bulk Jobs gets the same card in compact mode (one-line summary +
"view full status →"). Shared module `static/js/pipeline-card.js`
replaces the per-page copies. Background scan banner is now
click-to-enlarge with a detail modal (run-id, ETA, current file,
last-update age) plus keyboard support (Enter / Esc).

### v0.32.11 (carried-forward summary) — Lifecycle scan state hydrates from DB on startup

Status page Lifecycle Scanner card showed "Last scan: never" after
every container restart because `_scan_state` reset to None on
process boot. New `hydrate_scan_state_from_db()` runs in lifespan
startup and populates `last_scan_at` / `last_scan_run_id` from the
most recent finished `scan_runs` row.

### v0.32.10 (carried-forward summary) — Pipeline header descriptive scan info

Bulk Jobs Pipeline header gains multi-line cells with descriptive
sub-lines (Last Scan status pill + scanned/new/modified counts;
Next Scan type + cadence; Mode behavior summary; relative-time
qualifiers like "8 min ago"). Scheduler decision-reason surfaced as
hover tooltip on Mode cell. New `.pl-cell-sub` + `.pl-status-pill`
CSS rules.

### v0.32.9 (carried-forward summary) — Status card matches Bulk Jobs scan progress + click-to-jump

Status-page active-job card now mirrors the Bulk Jobs scan-progress
display (scanned-count + current-file + indeterminate animated bar).
BulkJob gains 3 state fields (`_scan_scanned`, `_scan_total`,
`_scan_current_file`); `get_all_active_jobs()` returns a new
`scan_progress` dict. Whole progress region is a click-through link
to `/bulk.html?job_id=<id>` with smooth-scroll + 1.8s highlight.

### v0.32.8 (carried-forward summary) — Storage page verifies on load + on tab focus

Every configured source path is verified on Storage page load (was:
only the output path). New per-row `.storage-verify-inline` widget
resolves async (parallel) to ✓ Readable · N items / ✗ Unreachable.
Per-section ↻ Re-verify buttons + auto-re-verify on tab focus after
>30s hidden (catches USB plug/unplug + network share drops).

### v0.32.7 (carried-forward summary) — Enumerating UI now actually renders during scans

Status page's "Enumerating source files…" UI from v0.32.1 was
silently falling through to the misleading `0 / ? files — ?%`
display because `total_files` is **0** during scanning, not null.
One-line fix: drop the `total_files == null` check; `status ===
'scanning'` alone is the authoritative signal.

### v0.32.6 (carried-forward summary) — Server-authoritative trash timers

Trash progress timers no longer reset when the operator navigates
away and back. `_empty_trash_status` and `_restore_all_status`
gain `started_at_epoch` + `last_progress_at_epoch` set by the
worker; frontend reads these on every poll instead of computing
elapsed-time client-side from the show-card moment.

### v0.32.5 (carried-forward summary) — Cache-bust convention on `live-banner.js`

Establishes the `?v=<release>` query-string convention on
`live-banner.js` script tags so returning operators get the latest
banner code without a hard-refresh. Three pages bumped
(`trash.html`, `status.html`, `pipeline-files.html`).

### v0.32.4 (carried-forward summary) — Inline progress card on Trash page

Empty Trash + Restore All now show a prominent in-page progress
card (between action buttons and file table) with bar / counter /
EWMA rate / ETA / elapsed timer / last-poll-age / sticky
"backend may still be enumerating" hint. Mid-op recovery: page
load checks `/status` endpoints and re-shows the card if either
op is in flight. No backend change.

### v0.32.3 (carried-forward summary) — Trash 500-cap removed, banner positioning, "Starting…" UX

Three v0.32.1 follow-up bugs: Trash list 500-row cap removed (new
`count_source_files_by_lifecycle_status` helper, `limit=None`
support; single Empty Trash click clears the whole pile); Live
Banner positioned below nav (`top:56px; z-index:90`) with body
padding-top adjustment; banner shows "Starting…" during the
100–500 ms enumeration window instead of "0 / 0 files".

### v0.32.2 (carried-forward summary) — `.tmk` handler + browser-download suffix shim

Files stranded in Unrecognized because of `.download` /
`.crdownload` / `.part` / `.partial` suffix or `.tmk` extension
now flow through `SniffHandler`. New `_strip_browser_suffix(path)`
strips trailing suffix and routes by inner extension.
Metadata-only stub records the actual originating extension in
`source_format` (was always `"tmp"`). Phase 2 (general format-sniff
fallback with `bulk_files.sniffed_*` columns) deferred.

### v0.32.1 (carried-forward summary) — Pipeline Files filter + AutoRefresh + Live Banner + clickable pills

Pipeline Files include-trashed toggle (default false; backend
JOIN on `source_files.lifecycle_status`). New
`static/js/auto-refresh.js` (visibility-aware polling helper) wired
to four stale-data pages. New `static/js/live-banner.js`
(long-running-op progress mirrored across pages). Status pills are
now hyperlinks (`SCANNING` → log viewer; `PENDING` → pipeline-files;
`LIFECYCLE SCAN` → log viewer). Log viewer accepts `?q=` +
`?mode=history` deep-link. Scanning-card UX fix. Written
`.tmk` recovery plan.

### v0.32.0 (carried-forward summary) — File preview page + force-process + related-files

`/preview.html` replaces the 19-line stub — full file viewer with
inline content (image / audio / video / PDF / text / Markdown /
archive / metadata-only fallback), metadata sidebar, sibling
navigation (← / →), force-process button (transcribe / convert /
analyze with real-time progress polling), Related Files sidebar
(semantic + keyword) and highlight-to-search chip, info-version
etag for staleness banner, friendly HTML 404 for missing files.
Six new `/api/preview/*` endpoints; thumbnail logic extracted to
shared `core/preview_thumbnails.py`. Plus Batch Management
page-size selector + Expand/Collapse-all + pagination footer. Side
fix: `run_lifecycle_scan` swallows `asyncio.CancelledError`
quietly on shutdown. Side cleanup: 662 MB stale `db-*.log` files
removed.

### v0.31.6 (carried-forward summary) — Selective conversion of pending files

History page Pending Files section gains checkboxes + select-all
+ "Convert Selected (N)" / "Retry Selected (N)" bulk-action bar.
New `POST /api/pipeline/convert-selected` (cap 100; routes via
new `_convert_one_pending_file` reusing Universal Storage Manager
output paths + write-guard). Lets operators test a hand-picked
subset without committing to a full pipeline sweep.

### v0.31.5 (carried-forward summary) — Preview format expansion + dynamic ETA framework

Hover preview now covers HEIC / HEIF / ~30 RAW camera formats /
SVG (rasterized server-side via cairosvg). Plus a dynamic ETA
framework: log searches show "estimated 1.4s (12 prior obs)"
hints based on EWMA throughput observed on this host's hardware.
Daily scheduler job (count 18→19) captures CPU / RAM / load
history.

### v0.31.4 (carried-forward summary) — Server-side ZIP bulk download

Multi-file download on Batch Management produces a single
streaming ZIP via `POST /api/analysis/files/download-bundle`
instead of the v0.29.6 sequential synthetic-anchor loop. Cap
raised from 100 → 500 files; server enforces 500 files OR ~2 GiB
uncompressed (whichever first). Smart compression (`ZIP_STORED`
for already-compressed extensions). Single-file fast path skips
the bundle endpoint entirely.

### v0.31.2 (carried-forward summary) — Multi-provider 5-layer vision resilience

OpenAI, Gemini, Ollama vision batch paths get the v0.29.9
Anthropic resilience pipeline (preflight, exponential backoff
with `Retry-After`, per-image bisection on 400, circuit breaker,
operator banner). Breaker module is process-wide so a 429 storm
on one provider pauses any other provider's calls — by design
(fail-fast on storms).

### v0.31.1 (carried-forward summary) — `.7z` viewer safety controls + system snapshot

Operator-tunable `.7z` byte cap (DB pref, 200 MB default, warn
above 1024 MB / above 50% free RAM, hard max 4096 MB). Log
Management Settings card host-snapshot row (CPU / RAM / load 1m
/5m/15m). Live spinner + ticking elapsed time on the log viewer
during in-flight searches.

### v0.31.0 (carried-forward summary) — Five-item deferred-items bundle

Multi-provider filename interleaving (OpenAI/Gemini/Ollama,
mirroring v0.29.8 Anthropic), time-range UI on log viewer history
search, bulk re-analyze with DELETE + re-INSERT semantics,
multi-log tabbed live view (LogTab class refactor), log subsystem
consolidation (`core/log_archiver.py` deleted; scheduler now
calls `core/log_manager`). Plus `.7z` archives readable in-place
via `_SevenZReader` subprocess wrapper with three-layer headless
safety (500k-line / 60s wall-clock / 200 MB byte caps).

### v0.30.4 (carried-forward summary) — per-row Re-analyze

Re-analyze button on the analysis-result modal so operators can
refresh stale results pre-dating v0.29.8's filename-context prompt
or v0.29.9's resilience improvements. UPDATE-in-place semantics;
superseded by v0.31.0's DELETE + re-INSERT.

### v0.30.3 (carried-forward summary) — Operations bundle

Active Jobs displays user-facing Storage-Manager paths via
`/api/admin/active-jobs` enrichment, stuck-scanning auto-cleanup
extends `cleanup_stale_jobs` to status='scanning', `du -sb` makes
`/api/admin/disk-usage` ~100× faster (with 5-min TTL cache and
`?refresh=true` bypass), Force Transcribe / Convert Pending
button on the History page.

### v0.30.2 (carried-forward summary) — admin.html parse-error hot fix

`renderStats` used `await` without being `async`, blanking the
entire `<script>` block and leaving the admin page on a static
"Loading..." skeleton. Three-char fix: prepend `async`. Also
`await renderStats(d)` in the caller so exceptions surface.

### v0.30.1 (carried-forward summary) — Log Management subsystem

`/log-management.html` (admin inventory + bundle download +
manual triggers) and `/log-viewer.html` (SSE live tail +
paginated history search). New `core/log_manager.py` +
`api/routes/log_management.py` (ADMIN-gated). Legacy
`core/log_archiver.py` consolidated into `log_manager` in
v0.31.0.

### v0.30.0 (carried-forward summary) — Pause-500 fix + pause presets + Resume

`POST /api/analysis/pause` was 500'ing under queue load because
`set_preference` did raw aiosqlite writes outside the
single-writer retry path. Wrapped in `db_write_with_retry`. Plus
pause-with-duration presets (1h / 2h / 6h / 8h / off-hours /
indefinite) + an explicit Resume button. New
`analysis_pause_until` preference; status endpoint and worker
both auto-resume on expired deadline.

### v0.29.9 (carried-forward summary) — Vision API resilience

Five-layer defense on the Anthropic vision pipeline: preflight
validation (PIL.verify + dimension/MIME), exponential backoff
honoring `Retry-After`, per-image bisection on 400 (one bad image
in a batch of 10 no longer costs 10 failed requests), process-wide
circuit breaker (open → half-open → closed), operator banner via
`/api/analysis/circuit-breaker`. New `core/vision_preflight.py` +
`core/vision_circuit_breaker.py`. OpenAI/Gemini/Ollama got the
same in v0.31.2.

### v0.29.8 (carried-forward summary) — Stale-error cleanup + filename context + wider previews

`write_batch_results` success branch now clears `error` + resets
`retry_count` (one-time `clear_stale_analysis_errors()` migration
gated by preference). Anthropic vision call prepends `Image N
filename: foo.jpg` text block before each image so Claude can
name buildings / landmarks when filename + content agree. Preview
format set widened to 14 browser-native + 23 PIL-thumbnailed
extensions.

### v0.29.7 (carried-forward summary) — Thumbnail preview for TIFF / EPS / WebP

`/api/analysis/files/:id/preview` splits into native
(FileResponse) and thumbnailed (PIL → JPEG 78 quality, 400px
longest edge) paths. EPS rasterized via PIL `EpsImagePlugin` →
Ghostscript. LRU cache (64 entries, mtime-keyed, ~13 MB
ceiling). All PIL work in `asyncio.to_thread`.

### v0.29.6 (carried-forward summary) — Multi-file download on Batch Management

"Download Selected (N)" button + context-menu item; sequential
synthetic-anchor clicks with 120 ms stagger; hard cap 100 files
per trigger. Reuses existing `/download` endpoint; no backend
change. (Superseded by v0.31.4 server-side ZIP.)

### v0.29.5 (carried-forward summary) — Right-click context menu on Batch Management

7-item menu on file rows: Open in new tab / Download / Save as…
/ Copy path / Copy source directory / View analysis result /
Exclude from analysis. Save as… uses `showSaveFilePicker()` where
available. View analysis modal fetches from new `GET
/api/analysis/queue/:id` endpoint.

### v0.29.4 (carried-forward summary) — Clickable status filters on Batch Management

Status counters (Pending / Batched / Completed / Failed /
Excluded) on Batch Management are now clickable filters. Pending
pseudo-batch surfaces 4000+ unbatched `analysis_queue` rows
(`batch_id=NULL`) that were previously invisible. New
`get_batches(status_filter)`, `get_batch_files(batch_id,
status_filter)`, `get_pending_files()` helpers; new `GET
/api/analysis/pending-files` endpoint.

### v0.29.3 (carried-forward summary) — GPU reservation restored on NVIDIA hosts

v0.28.0 committed `docker-compose.override.yml` for Apple Silicon
devs, which Docker Compose auto-merges, silently wiping NVIDIA
`deploy.resources.reservations` from every GPU host. Renamed the
checked-in file to `docker-compose.apple-silicon.yml` (no longer
auto-loaded) and gitignored the override name. macOS scripts
auto-seed the override on first run.

### v0.29.2 (carried-forward summary) — Drive mounts writable for output paths

`/host/c` and `/host/d` were mounted `:ro` (pre-v0.25.0 leftover),
so picking a drive-letter path as the output directory failed the
write check. Removed `:ro` from both lines; app-level
`is_write_allowed()` is now the sole barrier (consistent with
`/host/rw`). Requires `--force-recreate`.

### v0.29.1 (carried-forward summary) — Folder-picker fix + inline path verification

Folder-picker `output` mode early-returned in `_renderDrives`,
hiding C: / D: drives. Unified sidebar to always show drives.
Inline path verification pill on Storage page Save (Output) / Add
(Sources) shows the path as MarkFlow sees it with green ✓ /
red ✗ + access-status summary. Backend unchanged — uses existing
`POST /api/storage/validate`.

### v0.29.0 (carried-forward summary) — Storage polish + security hardening

v0.28.0 polish + 8 security-audit items addressed (notably ZIP
path-traversal SEC-C08, security response headers SEC-H12, dead
guard in `password_handler.cleanup_temp_file` SEC-H16, hardened
SECRET_KEY validation SEC-H13). Storage page got proper modal
forms (replacing prompt() chains), host-OS override dropdown,
folder-picker integration, migrated Cloud Prefetch section.
Legacy "Storage Connections" + "Cloud Prefetch" sections deleted
from `settings.html`. 105 storage tests + 22 integration tests
pass.

### v0.28.0 (carried-forward summary) — Universal Storage Manager

Storage page (`/storage.html`) replaces manual `.env` /
`docker-compose.yml` config with a GUI + first-run wizard +
runtime SMB/NFS share management. Three-layer architecture:
Docker grants broad host mounts (`/host/root:ro` + `/host/rw`)
+ `SYS_ADMIN` cap; app enforces write restriction via
`storage_manager.is_write_allowed()` at 12 sites; new
`/api/storage/*` consolidates the surface. Five new core modules
(`host_detector`, `credential_store` with Fernet+PBKDF2,
`storage_manager`, extended `mount_manager` with 5-min health
probe). Scheduler 17 → 18 jobs.

### v0.24.2 (carried-forward summary) — Hardening pass

Audit count corrected (62 findings, not "3 critical + 5 high").
DB backup schema-version guard refuses backups whose highest
applied migration is newer than the current build. PPTX pref
read goes through preferences cache (new `peek_cached_preference`
sync helper). Whisper inference serialized at thread-level so
timed-out threads can't stack on the GPU. DB contention logging
instrumentation retired (`core/db/contention_logger.py` deleted).

### v0.24.1 (carried-forward summary) — AI Assist toggle feedback

Targeted UX fix on the Search page AI Assist toggle. Active
state now solid accent fill + `ON` pill; pre-search intent hint;
inline "Synthesize these results" button when toggled on after
results are already showing.

### v0.24.0 (carried-forward summary) — Spec A (quick wins) + Spec B (batch management)

Spec A: inline file-list drill-down on Bulk + Status counters;
DB Backup/Restore via SQLite online backup API (WAL-safe) with
typed errors + audit log; hardware specs help article. Spec B:
full Batch Management page with batch CRUD; new
`analysis_submission_paused` preference (worker checks each
loop iteration so operators can drain in-flight batches without
new ones starting); 9 endpoints under `/api/analysis`. New
`core/db_backup.py` + `core/db/analysis.py`. 21 new tests.

### v0.23.x (carried-forward summary) — audit remediation + incremental polish

**v0.23.8:** content-hash sidecar collision fix (occurrence-indexed
keys `{hash}:{n}`, schema v2.0.0 with v1 auto-migrate, 4-level
cascade lookup), PPTX chart/SmartArt extraction
(`pptx_chart_extraction_mode=libreoffice`), C5 remaining OCR
signals.
**v0.23.7:** Bulk vector indexer fix
(`asyncio.Semaphore.acquire_nowait()` doesn't exist — that's
threading.Semaphore).
**v0.23.6:** Six-item hardening — image dim hints in Markdown,
pre-flight disk-space check on bulk + single-file paths,
configurable trash auto-purge (scheduler 16 → 17 jobs), per-job
force-OCR override, unified structural-hash helper, enhanced
`/api/convert/preview` endpoint.
**v0.23.5:** Ten new Search page keyboard shortcuts; two startup
crash fixes (migration FK enforcement, MCP server race).
**v0.23.4:** Settings page reorganized into Files-and-Locations /
Conversion-Options / AI-Options clusters.
**v0.23.3:** Migration hardening, batch empty-trash with progress
polling, bulk restore, extension exclude
(`scan_skip_extensions`). **Lifecycle timers landed at production
values: grace=36h, retention=60d.**
**v0.23.2:** Critical bug fixes — bulk upsert ON CONFLICT,
scheduler coroutine, vision MIME detection.
**v0.23.1:** Database file handler — SQLite, Access, dBase,
QuickBooks schema + sample data extraction into Markdown.
**v0.23.0:** 20-task overhaul — DB connection pool, preferences
cache, bulk_files dedup, incremental scanning, counter batching,
PyMuPDF default, vision MIME fix, frontend polling reduction.

### v0.22.x (carried-forward summary) — overnight rebuild + production-readiness

**v0.22.19:** Scan-time junk-file filter + one-time historical
cleanup (~$* Office locks, Thumbs.db, desktop.ini, .DS_Store).
**v0.22.18:** Four production-readiness fixes from runtime-log
audit (~2,500 noisy events/24h eliminated).
**v0.22.17:** Six-phase overnight rebuild self-healing pipeline
(preflight → source sync → anchor last-good → image build →
start + verify → success / blue-green rollback). Five exit
codes covering pre-commit failure / rollback success / rollback
failure / compose-divergence-refusal. Phase 4 catches v0.22.15-
class GPU regressions via `/api/health` `execution_path` +
`whisper.cuda` assertion. `expectGpu` auto-detect via
`nvidia-smi.exe` makes the same script work on CPU-only deploys.
Two new PowerShell gotchas documented (Start-Transcript +
docker-compose ps JSON parsing).

**All earlier versions** (v0.13.x – v0.22.16) are documented
per-release in [`docs/version-history.md`](docs/version-history.md).
**Do NOT duplicate that changelog here.** On each release the
outgoing "Current Version" block above moves into
`version-history.md` and is replaced with the new release notes.

**Planned:** External log shipping to Grafana Loki / ELK. The
current local log archive system is interim.

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
# First time — or whenever Dockerfile.base changes (apt packages,
# torch version, etc.) — rebuild the base (~25 min HDD / ~5 min SSD):
docker build -f Dockerfile.base -t markflow-base:latest .

# Normal operation:
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
(Only rebuilds pip + code layer — base image is cached.)

**When does the base need rebuilding?** Anytime `Dockerfile.base`
changes — new apt packages, a torch version bump, etc. The app-layer
build (`docker-compose build`) reuses the cached base, so system-level
additions won't land without a fresh base build. To check after
pulling a branch:
```bash
git diff <last-known-good-sha>..HEAD -- Dockerfile.base requirements.txt
```
If non-empty and touching apt packages, do the full sequence: base
build → `docker-compose build` → `docker-compose up -d`.
