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

## Current Version — v0.31.1

**`.7z` viewer safety controls + system-resource snapshot —
operator-tunable byte cap on `.7z` log search, host CPU/RAM/load
panel right next to the cap, and a live spinner + ticking elapsed
time on the log viewer while a search is in flight.**

The v0.31.0 release made `.7z` archives readable in the log
viewer's history search via a `7z e -so` subprocess wrapper, with
a hardcoded 200 MB per-reader byte cap as headless-safety
defense. v0.31.1 surfaces that cap to operators (so they can size
it for their hardware), shows them what hardware they're actually
running on, and gives them a visible "yes, work is happening"
signal during the multi-second searches a `.7z` archive can
produce.

### Item A — User-tunable `.7z` byte cap

New DB pref `log_seven_z_max_mb`. Default 200 MB (matches the
prior hardcoded value), warning threshold 1024 MB (UI shows
amber), hard backend max 4096 MB (`PUT /api/logs/settings` returns
400 above). The Log Management Settings card has a new "7z search
byte cap" input with inline live validation:

- Below 1024 MB → neutral hint with the cap-as-applied summary
- Above 1024 MB OR above 50% of currently-free RAM → amber warning
- Above 4096 MB → red "above hard limit" error

`get_seven_z_max_mb()` clamps reads to `[1, SEVEN_Z_HARD_MAX_MB]`
so a malformed pref can never lift the cap. `_SevenZReader`
constructor now takes an optional `max_bytes`; the legacy
`_SEVENZ_DEFAULT_MAX_BYTES` constant remains as the fall-through
default so any new call site that forgets to pass `max_bytes`
still gets a safety cap.

### Item B — Host resource snapshot

`get_system_resource_snapshot()` reads `/proc/cpuinfo` (model
name), `/proc/meminfo` (MemTotal + MemAvailable), and
`os.getloadavg()`. Best-effort — each field returns None on
read failure rather than raising, so a malformed `/proc` entry
doesn't 500 the settings page. Snapshot embeds in the
`GET /api/logs/settings` response under the `system` key.

The Log Management Settings card now renders a snapshot row right
below the controls: "Host: <CPU model> (N cores) — X GB total /
Y GB free — load 1m / 5m / 15m". One-shot read at page load (no
polling, no scheduler job). A dynamic ETA framework that uses
24-hour spec polling + a benchmark routine is its own deferred
follow-up — see v0.31.5 in the roadmap.

### Item C — Live search spinner on the log viewer

`runHistorySearch` now starts a CSS spinner + ticking elapsed
time when the request leaves the page, ticking every 200 ms.
Stops on response (or error) before the existing
`returned · scanned · …` status line takes over. The spinner is
attached to whichever tab fired the search, not whichever tab is
currently active — so switching tabs mid-search doesn't strand a
spinner against the wrong status line.

No protocol change. The search endpoint is still single-blob
JSON; for true server-pushed progress events the deferred
v0.31.5 ETA framework is the natural place.

### Files

- `core/version.py` — bump to 0.31.1
- `core/log_manager.py` — `PREF_SEVEN_Z_MAX_MB` constant +
  `get_seven_z_max_mb()` + `get_system_resource_snapshot()` +
  augmented `get_settings()` / `set_settings()`
- `api/routes/log_management.py` — `seven_z_max_mb` field on
  `SettingsUpdate`; `_SevenZReader.__init__` accepts optional
  `max_bytes`; `_do_search` reads pref + passes it through;
  truncation warning text uses the actual cap MB
- `static/log-management.html` — Settings card 7z cap input +
  inline warn/error/ok hint, system snapshot row, JS validation
- `static/log-viewer.html` — CSS spinner, in-flight elapsed-time
  ticker, spinner ownership tied to the requesting tab
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`, `docs/help/admin-tools.md`

No DB migration. No new dependencies. No new scheduler jobs.

---

## v0.31.0 — Five-item deferred-items bundle

**Five-item bundle release encompassing every deferred item from
the v0.31.x plan: multi-provider filename interleaving, log-viewer
time-range UI, bulk re-analyze with delete-and-re-insert
semantics, multi-log tabbed live view, and log subsystem
consolidation.**

### Item 1 — Multi-provider filename interleaving

`_batch_anthropic` got the filename-as-text-block treatment in
v0.29.8 so Claude could ground descriptions in recognizable
filenames (e.g. `Benaroya_Hall_Seattle.jpg` → "Benaroya Hall, a
concert venue in Seattle"). Same pattern now ported to:

- **OpenAI** (`_batch_openai`): inserts a `{"type": "text", "text":
  "Image N filename: ..."}` block before each `image_url` block,
  prompt at the end. Same shape as Anthropic.
- **Gemini** (`_batch_gemini`): inserts a `{"text": "..."}` part
  before each `inline_data` part, prompt at the end.
- **Ollama** (`_batch_ollama`): Ollama's `/api/generate` takes a
  single prompt + images array (no per-image text blocks), so the
  filename list is prepended to the prompt
  (`"Files (in order): 1. foo.jpg, 2. bar.png\n\n<prompt>"`).

### Item 2 — Time-range UI in log viewer historical search

Backend has supported `from_iso` / `to_iso` query params on
`/api/logs/search` since v0.30.1. UI now wires them. New row
below the main controls:
- `<input type="datetime-local">` for From + To, dark-themed
- Preset chips: Last hour / Last 24h / Last 7d / Clear range
- Visible only in history mode (live tail mode hides the row)
- Local-time inputs converted to UTC ISO before being sent

### Item 3 — Bulk re-analyze with delete-and-re-insert semantics

The v0.30.4 per-row endpoint did UPDATE-in-place — preserved id,
enqueued_at, and other identity fields. Per user requirement
("make sure that the files that get reanalyzed are deleted from
the database and resubmitted for entry into the database"), v0.31.0
switches BOTH the per-row and the new bulk endpoint to
**DELETE + re-INSERT via `enqueue_for_analysis`**. Result: every
re-analyzed row gets a fresh id / enqueued_at / retry_count and
all output columns NULL — no carry-over of any prior state.

- **Per-row endpoint** (`POST /api/analysis/queue/{id}/reanalyze`):
  selects identity columns, deletes the row, re-enqueues via the
  canonical path. Returns `{old_entry_id, new_entry_id}`.
- **Bulk endpoint** (`POST /api/analysis/queue/reanalyze-bulk`):
  Pydantic body with `analyzed_before_iso`, `analyzed_after_iso`,
  `provider_id`, `model`, `status` (defaults `completed`),
  `dry_run` (defaults `true`). Hard cap of 10,000 rows per call;
  400 if exceeded. Refuses empty filter sets (no "match every row").
- **Filters helper** (`GET /api/analysis/queue/reanalyze-filters`):
  returns distinct provider_id + model values to populate modal
  dropdowns from the current DB state.
- **Frontend modal** on Batch Management with date pickers,
  provider/model dropdowns pre-populated from the API,
  status dropdown, Preview button → calls `dry_run=true` to show
  matched count + sample paths, Run button confirms with explicit
  "deletes the matching rows and re-submits them as fresh entries"
  language and exact row count.
- **Per-row Re-analyze button copy** updated to mention DELETE +
  re-INSERT explicitly.

### Item 4 — Multi-log tabbed live view

Log viewer became a multi-tab inspector. Single global EventSource
+ filter state replaced with a `LogTab` class — each tab owns its
own SSE connection, history offset, body DOM, and per-tab filter
state (level chips, search query/regex, time range, mode).

- Tab strip below the main controls. Each tab shows a
  green/red/grey dot indicating SSE connection state, the file
  name, and a × close button.
- "+ Add tab" button at the end opens a popover listing all
  available logs (with size + status pill); already-open logs are
  greyed out.
- Background tabs keep their EventSource open so events aren't
  missed; their bodies are capped at 1000 lines (oldest evicted
  from the head) so memory stays bounded.
- Switching the active tab syncs the top-bar controls (mode,
  level chips, search, time range) to that tab's stored state.
- Open tab list + active tab + per-tab filter state persist to
  `localStorage` so refresh restores the layout.
- Falls back to a single auto-opened tab on the most-recent log
  when no localStorage data + no `?file=` query param.

### Item 5 — Log subsystem consolidation

`core/log_archiver.py` (v0.12.2, ~150 LOC) deleted. Its scheduler
job replaced by a thin wrapper (`_log_manage_cycle`) that calls
`core.log_manager.compress_rotated_logs()` +
`core.log_manager.apply_retention()`. Net effect: the same 6-hour
cron cadence, but the Settings page preferences (compression
format, retention days) now actually govern the automated cycle.
Previously the cron ignored those prefs and used hardcoded gz +
90-day defaults — only manual "Compress Rotated Now" / "Apply
Retention Now" admin clicks honored them, surprising operators.

- The legacy `archive/` subdir is left in place for read access
  to historical files; the inventory endpoint already discovered
  it (added in v0.30.1) and continues to.
- `get_archive_stats()` reborn in `log_manager.py` (now reads
  retention from DB pref, not env var) so the
  `/api/logs/archives/stats` endpoint keeps working.
- 18-job scheduler count unchanged.

### Files

- `core/version.py` — bump to 0.31.0
- `core/vision_adapter.py` — filename interleaving in
  `_batch_openai`, `_batch_gemini`, `_batch_ollama`
- `core/db/analysis.py` — `BULK_REANALYZE_CAP`,
  `find_rows_for_bulk_reanalyze`, `delete_rows_by_ids`,
  `list_distinct_provider_models`
- `api/routes/analysis.py` — per-row `reanalyze_queue_entry`
  switched to delete+re-insert; new `reanalyze_bulk` endpoint
  + `BulkReanalyzeRequest` Pydantic model + filters helper
- `static/log-viewer.html` — multi-tab refactor (LogTab class,
  per-tab state, +/× tab UI, localStorage); time-range row
- `static/batch-management.html` — Bulk re-analyze top-bar button
  + modal HTML/CSS/JS; per-row button copy update
- `core/scheduler.py` — `_log_manage_cycle` replaces
  `archive_rotated_logs` job
- `core/log_archiver.py` — DELETED
- `core/log_manager.py` — added `get_archive_stats()` shim;
  comment cleanup re: deleted module
- `api/routes/logs.py` — `/archives/stats` re-imports from
  `log_manager` (now async)
- `CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md`,
  `docs/key-files.md`

No DB migration. No new dependencies.

---

### v0.30.4 (carried-forward summary) — per-row Re-analyze

Re-analyze button on the analysis-result modal so operators can
refresh stale results that pre-date v0.29.8's filename-context
prompt or v0.29.9's resilience improvements. UPDATE-in-place
semantics; superseded by v0.31.0's DELETE + re-INSERT. Full
context: [`docs/version-history.md`](docs/version-history.md).

### v0.30.3 (carried-forward summary) — Operations bundle

Active Jobs displays user-facing Storage-Manager paths via
`/api/admin/active-jobs` enrichment, stuck-scanning auto-cleanup
extends `cleanup_stale_jobs` to status='scanning', `du -sb` makes
`/api/admin/disk-usage` ~100× faster (with 5-min TTL cache and
`?refresh=true` bypass), and a Force Transcribe / Convert Pending
button on the History page. Full context:
[`docs/version-history.md`](docs/version-history.md).

### v0.30.2 (carried-forward summary) — admin.html parse-error hot fix

`renderStats` used `await` without being `async`, blanking the
entire `<script>` block and leaving the admin page on a static
"Loading..." skeleton. Three-char fix: prepend `async`. Also
`await renderStats(d)` in the caller so exceptions surface.
Full context: [`docs/version-history.md`](docs/version-history.md).

### v0.30.1 (carried-forward summary) — Log Management subsystem

`/log-management.html` (admin inventory + bundle download +
manual triggers) and `/log-viewer.html` (SSE live tail +
paginated history search). New `core/log_manager.py` +
`api/routes/log_management.py` (ADMIN-gated). At v0.30.1 ship,
the legacy `core/log_archiver.py` still ran the automated
6-hour cron with hardcoded defaults — consolidated into
`log_manager` in v0.31.0. Full context:
[`docs/version-history.md`](docs/version-history.md).

---

## v0.30.0 — Pause 500 fix + pause-with-duration presets + explicit Resume

Urgent fix: `/api/analysis/pause` 500 under queue load, plus
pause-with-duration presets and an explicit Resume button.

### The 500 (primary fix)

`POST /api/analysis/pause` was reliably 500'ing with
`sqlite3.OperationalError: database is locked` whenever the
analysis worker held a write transaction. Root cause: the
underlying `core/db/preferences.set_preference()` did raw
`aiosqlite` writes without going through the single-writer retry
path that everything else in the app uses. Fixed by wrapping the
body of `set_preference` in `db_write_with_retry` — race-safe
with exponential backoff, mirroring the pattern in
`bulk_worker.py` and the migration helpers.

### Pause-with-duration + explicit Resume (UX)

The top bar on the Batch Management page now has two distinct
buttons: a **Pause ▾** dropdown (six presets) and an always-
visible **Resume** button.

Pause dropdown options:
- 1 hour / 2 hours / 6 hours / 8 hours
- Until off-hours (uses `scanner_business_hours_end` preference
  to compute the next off-hours boundary)
- Indefinite (legacy behavior)

Backend additions:
- New preference `analysis_pause_until` stores the ISO deadline
  (empty string = indefinite).
- `POST /api/analysis/pause` accepts optional body with
  `duration_hours` (float, 0 < h ≤ 168) or `until_off_hours: true`.
  Empty body keeps the legacy "pause indefinitely" behavior.
- `POST /api/analysis/resume` now also clears `pause_until` so a
  future Pause click doesn't inherit a stale deadline.
- `GET /api/analysis/status` returns `pause_until` and
  auto-resumes (clears both prefs) when the deadline has passed —
  so an expired pause self-heals even if no worker tick has
  occurred.
- The analysis worker itself also auto-resumes on expired
  `pause_until` at its next claim cycle (fail-safe if the
  status endpoint hasn't been polled recently).

UI status label now reads "Submission: Paused until 4/24/2026,
9:00:00 PM" instead of just "Paused" when a timed pause is
active.

### Files

- `core/db/preferences.py` — `set_preference` goes through
  `db_write_with_retry`
- `api/routes/analysis.py` — pause endpoint takes optional body;
  new helpers for off-hours computation + auto-resume
- `core/analysis_worker.py` — honors + auto-clears expired
  `pause_until` at claim time
- `static/batch-management.html` — new Pause dropdown + Resume
  button + CSS; JS wired to the six presets
- `core/version.py` — bump to 0.30.0
- `CLAUDE.md` / `docs/version-history.md`

No database migration needed — new preference just starts
uninitialized (treated as "indefinite" by the code). No new
Python dependency.

---

## v0.29.9 — Vision API resilience

Financial-best-practices resilience on the Anthropic vision
pipeline: 5-layer defense against wasted API spend — preflight,
backoff, bisection, circuit breaker, operator banner.

API calls are money. v0.29.9 minimizes wasted requests on known-bad
inputs and upstream flakiness, and surfaces outages to the operator
before the quota drains.

### Five layers (in order of request life-cycle)

1. **Preflight validation** (`core/vision_preflight.py` — new):
   every image is run through PIL `verify()` + dimension sanity
   (100-8000px per edge) + MIME allow-list check *before* encoding
   to base64. Failures are recorded as `[preflight] ...` errors with
   zero API cost. Catches corrupt bytes, truncated uploads,
   micro-thumbnails, and out-of-range-dimension files.
2. **Exponential backoff + Retry-After** — 429 / 500 / 502 / 503 /
   504 / 529 trigger a retry with exponential delay (1/2/4/8 s with
   ±15% jitter, cap 30 s) across up to 4 attempts. If Anthropic
   sends a `Retry-After` header (seconds or HTTP-date), it's
   honored verbatim (capped at 30 s). Idle during backoff, not
   spinning.
3. **Per-image bisection on 400** — if a sub-batch of N images
   returns 400 (payload error), the batch is split in half and each
   half retried. Recursion continues until the bad image is isolated
   in a solo sub-batch (~log2 N extra calls worst case). The other
   N-1 files complete cleanly instead of being tossed with the bad
   one. Financial impact: one malformed file in a batch of 10 no
   longer costs 10 failed requests.
4. **Circuit breaker** (`core/vision_circuit_breaker.py` — new):
   process-local state machine (closed → open → half-open). 5
   consecutive upstream failures open the circuit; short-circuit
   rejects new calls for a cooldown window (60 s → 2 min → 4 min
   → 8 min, cap 15 min). 400s don't count toward the threshold —
   those are payload issues, not upstream outages. After cooldown
   one trial call is permitted; success closes the circuit, failure
   doubles the cooldown.
5. **Operator banner** — `/api/analysis/circuit-breaker` (new
   endpoint) exposes breaker state to the Batch Management page.
   When open or half-open, a red/amber banner appears above the
   top bar with the error class, consecutive-failure count,
   countdown to next trial, and a "Reset breaker" button
   (MANAGER+ only) for operators who've fixed the upstream issue
   manually.

### What still 400s

Intentionally scoped out: 400s that preflight can't predict
(policy violations in image content, unusually-formatted JPEG
variants Anthropic sometimes rejects, rare token-count overruns).
Those feed into bisection (isolate to a single file, mark failed,
move on) rather than block the whole queue.

### Scope: Anthropic only this pass

All 5 layers apply to `_batch_anthropic`. OpenAI / Gemini / Ollama
handlers get no new resilience this release — the primary Anthropic
user traffic was the motivator. Extending the same machinery to the
other three providers is a straightforward follow-up (the backoff
helpers + circuit breaker are provider-agnostic; each handler just
needs the same try/except shape).

### Files

- `core/vision_preflight.py` — NEW, 100 lines
- `core/vision_circuit_breaker.py` — NEW, 150 lines
- `core/vision_adapter.py` — `_batch_anthropic` rewritten with
  preflight + split into `_anthropic_sub_batch` helper supporting
  backoff + bisection + circuit-breaker gate
- `api/routes/analysis.py` — GET `/circuit-breaker` +
  POST `/circuit-breaker/reset`
- `static/batch-management.html` — banner slot + CSS + poller +
  reset handler
- `core/version.py`, `CLAUDE.md`, `docs/version-history.md`

No new dependencies. No database migration. Per-image
`retry_count` cap in `analysis_queue` (max 3 per row) still applies
as the outer safety net — the 5-layer pipeline just ensures each
retry is qualitatively different from the last rather than a
pointless re-send of the same failing request.

---

## v0.29.8 — Stale-error cleanup + filename context + wider preview formats

Three-in-one follow-up: stale-error cleanup on the analysis
queue, filenames now inform Claude's image descriptions, and the
hover-preview format set is widened to every photo format PIL
recognizes (no new dependencies).

- **Stale `error` on completed rows** — `write_batch_results`
  success branch did not clear `error` or reset `retry_count`.
  Rows that failed, retried, and eventually succeeded kept the old
  error string forever, which the batch-management UI faithfully
  showed alongside a correct `description` + `extracted_text`.
  Fixed by adding `error = NULL, retry_count = 0` to the success
  UPDATE, plus a one-time migration `clear_stale_analysis_errors()`
  (gated `analysis_stale_errors_cleared_v0_29_8` preference) that
  cleans existing rows on startup.
- **Filename context for Claude** — the Anthropic vision call now
  prepends a `{"type": "text", "text": "Image N filename: foo.jpg"}`
  block before each image block. The default prompt instructs Claude
  to name recognizable subjects (buildings, landmarks, etc.) when
  the filename identifies them AND the image content agrees —
  fallback to a generic description if they disagree. Fixes the
  "Benaroya_Hall,_Seattle,_Washington,_USA.jpg → 'a large modern
  building' without ever identifying Benaroya Hall" case.
- **Wider preview format coverage** — every photo format PIL can
  decode in the current base image is now previewable, split the
  same way as v0.29.7:
  - **Browser-native** (14 total): `.jpg`, `.jpeg`, `.jfif`, `.jpe`,
    `.png`, `.apng`, `.gif`, `.bmp`, `.dib`, `.webp`, `.avif`,
    `.avifs`, `.ico`, `.cur`
  - **PIL-thumbnailed** (23 total): `.tif`, `.tiff`, `.eps`, `.ps`,
    JPEG 2000 family (`.jp2`, `.j2k`, `.jpx`, `.jpc`, `.jpf`, `.j2c`),
    Netpbm family (`.ppm`, `.pgm`, `.pbm`, `.pnm`), Targa family
    (`.tga`, `.icb`, `.vda`, `.vst`), SGI family (`.sgi`, `.rgb`,
    `.rgba`, `.bw`), plus `.pcx`, `.dds`, `.icns`, `.psd`
  - **Still deferred**: `.svg` (needs XSS sanitization), `.heic` /
    `.heif` (needs `pillow-heif` dep), RAW camera formats (need
    `rawpy` dep).

Files: `core/version.py`, `core/db/analysis.py`,
`core/db/migrations.py`, `core/vision_adapter.py`, `main.py`,
`api/routes/analysis.py`, `static/batch-management.html`,
`CLAUDE.md`, `docs/version-history.md`.

---

## v0.29.7 — Thumbnail preview for TIFF, EPS, and WebP

Hover preview now works for TIFF, EPS, and WebP — PIL thumbnail
fallback with LRU cache, no more silent `onerror` flickers.

- **Before:** hovering a `.tif`/`.tiff` row fired `/preview`, the
  endpoint served the raw bytes, and the browser's `<img>` tag
  couldn't decode TIFF (every mainstream browser except Safari/macOS
  rejects it) → `img.onerror` hid the tooltip silently. `.eps` was
  worse: the endpoint 404'd outright because `is_image_extension()`
  didn't include vector formats. Both looked like "is the preview
  broken?" to users.
- **After:** `/api/analysis/files/:id/preview` now splits its file
  types two ways:
  - **Native** (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`):
    streamed as `FileResponse`, same as before.
  - **Thumbnailed** (`.tif`, `.tiff`, `.eps`): opened with PIL,
    thumbnailed to 400px on the longest edge via `Image.LANCZOS`,
    saved as JPEG (quality 78) and returned as an
    `image/jpeg` response. PIL's `EpsImagePlugin` shells out to
    Ghostscript (`/usr/bin/gs`, 10.05 in the base image) to
    rasterize PostScript. All PIL work runs in
    `asyncio.to_thread` so it never blocks the event loop.
- **LRU cache** (64 entries, ~13 MB ceiling) keyed on
  `(source_file_id, mtime_ns, size)` so unchanged files serve from
  memory on subsequent hovers and any edit to the file invalidates
  automatically. Response carries `Cache-Control: private,
  max-age=300` so the browser also caches short-term.
- **Failure path**: thumbnail errors surface as HTTP 500 with the
  PIL/Ghostscript error class + message (easy to diagnose in the
  browser network tab) and log as `analysis.thumbnail_generation_failed`.
- **Frontend**: `_IMG_EXT` now includes `.webp` for symmetry with
  the backend's native list. `.tif/.tiff/.eps` were already there;
  they used to silently fail, now they actually work.

Files: `core/version.py`, `api/routes/analysis.py`,
`static/batch-management.html`, `CLAUDE.md`,
`docs/version-history.md`.

---

## v0.29.6 — Multi-file download on Batch Management

Multi-file download on Batch Management — "Download selected (N)"
in the context menu + a Download Selected button in the bulk bar.

- **Bulk toolbar**: the existing "Exclude Selected" bar above each
  file table now also has a "Download Selected (N)" button that
  activates once any checkboxes are checked. N counts only rows with
  a `source_file_id` (rows without one can't be downloaded —
  usually because `source_files` lost the row).
- **Context menu**: right-clicking any file row with 1+ rows
  checkbox-selected shows "Download selected (N)" at the top of the
  menu with its own separator. Matches standard file-explorer
  convention — if a selection exists, the context menu can operate
  on it.
- **Execution**: sequential synthetic-anchor clicks with a 120 ms
  stagger between each. Browsers will usually prompt once on the
  first attempt ("allow this site to download multiple files?")
  and then batch the rest. Hard cap at **100 files per trigger** —
  above that, the user is asked to select fewer and try again.
  Rationale: 100+ simultaneous downloads reliably exhaust the browser's
  download manager and rate-limits on most sites.
- **No backend change**. Reuses the existing
  `/api/analysis/files/:id/download` endpoint once per selected file.

Files: `core/version.py`, `static/batch-management.html`,
`CLAUDE.md`, `docs/version-history.md`.

---

## v0.29.5 — Right-click context menu on Batch Management file rows

Right-click context menu on Batch Management file rows — per-file
actions without hunting for the right button.

- **Right-click any file row** on `/batch-management.html` to open a
  7-item context menu: Open in new tab · Download · Save as… · Copy
  path · Copy source directory · View analysis result · Exclude from
  analysis. Escape / click-outside / scroll / resize all close the
  menu. Keyboard-accessible (Enter/Space on focused items).
- **Open in new tab** uses the existing `/api/analysis/files/:id/preview`
  (for images) or `/download` URL. The browser's back button restores
  the batch page at the same scroll position.
- **Save as…** uses `showSaveFilePicker()` where available
  (Chrome/Edge). Non-Chromium browsers fall back to the normal
  download with a toast nudging the user to enable their browser's
  "ask where to save each file" preference.
- **View analysis result** opens a modal showing the analysis
  `description` + `extracted_text` (for completed rows), the error
  message (for failed), or a status note (pending/batched/excluded).
  Modal fetches from the new `GET /api/analysis/queue/:id` endpoint.
- **Copy path / Copy source directory** use the Clipboard API with
  a `document.execCommand('copy')` fallback for non-secure contexts.
  Toast confirms the copy.
- **Exclude from analysis** matches the existing Action-column
  button but is duplicated into the menu so operators don't have to
  hunt across columns for a single action.

Files: `core/version.py`, `api/routes/analysis.py` (new
`/queue/{entry_id}` endpoint), `static/batch-management.html`
(context-menu CSS, modal CSS, ~260 lines of new JS),
`CLAUDE.md`, `docs/version-history.md`.

---

## v0.29.4 — Clickable status filters on Batch Management

Batch Management page: status counters are clickable filters, with
a pending pseudo-batch so the 4000+ unbatched files are actually
browsable.

- **Status counters** (Pending / Batched / Completed / Failed /
  Excluded) in the top bar are now buttons. Clicking one filters the
  batch list below to only batches containing files of that status.
  Per-card counts + sizes reflect the filtered rows only, so the sum
  across all cards equals the clicked counter. Click the same counter
  again (or the "Show all" pill) to clear the filter. A banner at the
  top of the filtered view calls out what's being shown.
- **Pending pseudo-batch**: `analysis_queue` rows in `status='pending'`
  have `batch_id=NULL`, so the existing `/api/analysis/batches`
  endpoint never saw them — they were effectively invisible. Added
  `GET /api/analysis/pending-files?limit=&offset=` (paginated at
  100 per page), and the Pending filter renders a single "Pending
  (not yet batched)" card that expands to show the full paginated
  list.
- **Expanded file lists are filtered too**: clicking into a batch
  while the Completed filter is active shows only that batch's
  completed files — no need to scan a wall of rows to find the ones
  relevant to the counter you clicked.
- **Backend additions**: `get_batches(status_filter)`,
  `get_batch_files(batch_id, status_filter)`, `get_pending_files()`
  in `core/db/analysis.py`; API routes validate the filter against
  the canonical `{pending, batched, completed, failed, excluded}`
  set (400 on bad input).

Files: `core/version.py`, `core/db/analysis.py`,
`api/routes/analysis.py`, `static/batch-management.html`,
`CLAUDE.md`, `docs/version-history.md`, `docs/help/whats-new.md` (if
present).

---

## v0.29.3 — Restored GPU reservation on NVIDIA hosts

`docker-compose.override.yml` un-committed + gitignored so GPU hosts
get their `deploy:` reservation back.

- **Bug:** v0.28.0 committed `docker-compose.override.yml` for Apple
  Silicon developers. Because Docker Compose auto-merges any file with
  that exact name, every GPU-equipped host that pulled `main` silently
  lost its NVIDIA `deploy.resources.reservations` block — the override's
  `deploy: !reset null` wiped it out. Result: containers started
  without a GPU even when the host had one, and `/api/health` reported
  `gpu.ok=false` / `execution_path: container_cpu`.
- **Fix:** renamed the checked-in file to
  `docker-compose.apple-silicon.yml` (NOT auto-loaded under that name —
  it's now a sample). Added `docker-compose.override.yml` to
  `.gitignore` so it's truly per-machine, per the Docker convention.
- **Apple Silicon / no-GPU dev machines**: the three macOS scripts
  (`Scripts/macos/{refresh,reset,switch-branch}.sh`) now auto-seed
  `docker-compose.override.yml` from the sample on first run. Idempotent
  — won't clobber a customized local copy.
- **GPU hosts (Linux + nvidia-container-toolkit, Windows Docker Desktop
  with WSL2 GPU support)**: nothing to do. No override file means the
  base compose's GPU reservation takes effect. A `docker-compose up -d
  --force-recreate` after pulling is required to drop the stale
  overridden deploy config from the running container.

**Prerequisite for GPU passthrough** (unchanged): NVIDIA driver on the
host and nvidia-container-toolkit visible to Docker. Verified working
on this machine via `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`
showing the GTX 1660 Ti with 6 GB VRAM.

Files: `core/version.py`, `.gitignore`,
`docker-compose.override.yml` → `docker-compose.apple-silicon.yml`
(git rename with updated header comment),
`Scripts/macos/refresh-markflow.sh`, `Scripts/macos/reset-markflow.sh`,
`Scripts/macos/switch-branch.sh`, `CLAUDE.md`, `docs/gotchas.md`,
`docs/version-history.md`.

---

## v0.29.2 — Drive mounts writable for output paths

Drive mounts made writable so a drive path can be used as the output
directory.

- **`/host/c` and `/host/d` were mounted `:ro`** in `docker-compose.yml`
  — a pre-v0.25.0 leftover. Picking `/host/d/Doc-Conv_Test` (or any
  drive-letter path) as the output directory failed the write check
  inside `validate_path`, producing "MarkFlow can't write to this
  folder — check permissions" — even though the filesystem on the host
  itself was writable.
- **Fix:** removed `:ro` from the two drive-browser lines. The
  app-level write guard in `core/storage_manager.is_write_allowed` is
  now the sole barrier — same enforcement model already used for the
  broad `/host/rw` mount (v0.25.0). Drive paths and `/host/rw` paths
  now behave consistently, and users can pick whatever destination is
  intuitive in the folder-picker without a mental translation step.
- **Requires `docker-compose up -d --force-recreate`** to take effect
  (volume flag changes are only applied on container recreate).
- **Docs updated:** `docs/drive-setup.md` drops the `:ro` from the
  walkthrough + adds a v0.29.2 note; CLAUDE.md this block; new
  gotcha in `docs/gotchas.md` → Container & Dependencies.

Files: `core/version.py`, `docker-compose.yml`, `CLAUDE.md`,
`docs/drive-setup.md`, `docs/gotchas.md`, `docs/version-history.md`.

---

## v0.29.1 — Folder-picker fix + inline path verification

Storage page polish — folder-picker output-drive regression fix +
inline path verification after Save/Add.

- **Folder-picker `output` mode hid drives** (`static/js/folder-picker.js`).
  `_renderDrives` early-returned in output mode and rendered only the
  Output Repo shortcut, making it impossible to pick C:/D: as the
  output directory. Unified the sidebar: always show Drives, append
  Output Repo for modes that write output (`any` + `output`). Mode
  still controls initial navigation (output mode still lands at
  `/mnt/output-repo` by default). Rewrote `_renderDrives` to use
  `createElement` + `textContent` instead of `innerHTML` while at it
  — aligns with the XSS-hardening guidance.
- **Inline path verification** on the Storage page. After clicking
  **Save** on Output Directory or **Add** on Sources, the UI now
  renders a verification pill right below the input showing the path
  as markflow sees it, a green ✓ (or red ✗), and the access-status
  summary: Writable/Readable, item count, free space, warnings. On
  page load, the currently-saved output path is also re-validated so
  users can confirm nothing has drifted. Backend unchanged — the
  existing `POST /api/storage/validate` endpoint serves this.
- **Docs-only change in parallel:** CLAUDE.md's "Running the App"
  section now clarifies that `Dockerfile.base` changes require a
  full base rebuild (not just "first time only"). Matching gotcha
  added to `docs/gotchas.md` → Container & Dependencies. Caught when
  v0.28.0's `cifs-utils` + `smbclient` additions didn't land until a
  base rebuild was run.

Files: `core/version.py`, `static/js/folder-picker.js`,
`static/js/storage.js`, `static/storage.html`, `static/markflow.css`,
`CLAUDE.md`, `docs/gotchas.md`, `docs/version-history.md`.

---

## v0.29.0 — Storage polish + security hardening pass

Same-day polish follow-up to v0.28.0 plus a security hardening pass.
Storage page got proper Add-Share / Discovery modal forms (replacing
the prompt() chains), a host-OS override dropdown, folder-picker
integration on source/output path inputs, and a migrated Cloud Prefetch
section. Legacy "Storage Connections" and "Cloud Prefetch" sections
deleted from `static/settings.html`. **Eight security-audit items
addressed** — most notably ZIP path-traversal (SEC-C08 Critical),
security response headers on every request (SEC-H12), the long-standing
dead guard in `password_handler.cleanup_temp_file` (SEC-H16), and a
hardened SECRET_KEY validation in lifespan (SEC-H13). **105 storage
tests + 22 integration tests pass** in Docker.

Full context: [`docs/version-history.md`](docs/version-history.md). Plan
executed autonomously from
[`docs/superpowers/plans/2026-04-22-v0.28.0-polish.md`](docs/superpowers/plans/2026-04-22-v0.28.0-polish.md).

Files changed on this release: `api/middleware.py`, `api/routes/db_health.py`,
`api/routes/scanner.py`, `api/routes/storage.py`, `core/gpu_detector.py`,
`core/libreoffice_helper.py`, `core/password_handler.py`, `core/version.py`,
`formats/archive_handler.py`, `main.py`, `static/app.js`,
`static/js/storage.js`, `static/js/storage-restart-banner.js`,
`static/markflow.css`, `static/settings.html`, `static/storage.html`,
`tests/test_storage_api.py`, `docs/version-history.md`, `CLAUDE.md`,
`docker-compose.override.yml` (new for Apple Silicon dev).

---

## v0.28.0 — Universal Storage Manager

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
