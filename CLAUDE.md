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

## Current Version — v0.32.8

**Storage page: every configured source path is verified on
page load (was: only the output path was). Each source row
now shows a momentary "⟳ Verifying…" state then resolves to
✓ Readable · N items / ✗ Unreachable. Plus a small ↻ Re-verify
button per section for manual on-demand re-check, and an
auto-re-verify when the tab regains focus after being hidden
>30 s (catches USB plug/unplug + network share drops).**

### Why this matters

User reported on v0.32.7: "we should have the green check mark
show up everytime markflow starts up and the user navigates
to the page... a verification everytime the page is refreshed".

The Output Directory section already verified on page load
(v0.29.1 shipped that). But `loadSources()` only rendered the
table rows with label / path / Remove button — no verification
widget. The green ✓ that was sometimes visible at the top of
the Sources section was a leftover from a recent **Add**
action (the `#source-add-verify` widget) and didn't survive a
page refresh.

This release closes the gap: every source gets verified on
every page load.

### What changed

**Per-source inline verification** — `loadSources()` now
renders each row with a multi-line "Path & Status" cell:
- Line 1: the path (monospace)
- Line 2: a `.storage-verify-inline` widget that starts in the
  pending `⟳ Verifying…` state and async-resolves to
  ✓ Readable · N items / ✗ Unreachable

Verifications run **in parallel** across all sources; the table
renders synchronously and each row resolves at its own pace.
Slow-network sources don't block fast-local ones.

**Per-section ↻ Re-verify buttons** — small button next to each
section's content header. One click → all that section's
widgets flip back to pending and re-resolve. Buttons disable
themselves while in flight to prevent click-storm.

**Auto-re-verify on tab focus** — `visibilitychange` listener
tracks how long the tab was hidden. Returning to the tab after
**>30 s** triggers `reverifyAll()` (sources + output). Catches:
- USB drives plugged or unplugged while you were away
- SMB / NFS shares that dropped due to a network blip
- Any path that became inaccessible (permission change, etc.)

The 30-second threshold avoids hammering `/api/storage/validate`
on every micro-tab-switch.

### Files

- `core/version.py` — bump to 0.32.8
- `static/storage.html` — section content headers gain
  Re-verify buttons; sources table column renamed
  `Path` → `Path & Status`; `?v=0.32.8` cache-bust on
  `storage.js`
- `static/js/storage.js` — `_sourceVerifyWidgets` Map for
  per-row widget tracking, `renderPendingVerify` helper for
  the ⟳ pending state, `reverifyAll` / `reverifySources` /
  `reverifyOutput` drivers, Page Visibility listener in
  `init()`
- `static/markflow.css` — `.sv-pending` style with
  `sv-pending-spin` keyframe + `.storage-verify-inline`
  compact variant + `.storage-reverify-btn` button styling
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No backend changes —
the existing `/api/storage/validate` endpoint already does
all the heavy lifting; this release just calls it more often.

---

## v0.32.7 — Status page Enumerating UI now actually renders during scans

**One-line frontend fix: the Status page's "Enumerating
source files…" UI from v0.32.1 now actually renders during
the bulk-scanner phase instead of silently falling through
to the misleading `0 / ? files — ?%` legacy display.**

### The bug

v0.32.1 added an "Enumerating source files… Xs elapsed" UI
for jobs in the scanning phase, with a stuck-warning if the
scan hangs >2 min. The intent was to replace the broken
`0 / ? files — ?%` placeholder during enumeration. The
condition was:

```js
var enumerating = (job.status === 'scanning' && job.total_files == null);
```

But `job.total_files` is **never null** during scanning — it's
always **0**. Looking at `core/bulk_worker.py:get_all_active_jobs`,
the field is sourced from `job._total_pending` which is
initialized to 0 and only set to the real count AFTER the
scanner returns. So during the entire scanning phase
`total_files == 0` (not null), the enumerating condition is
False, and the UI falls through to the legacy display.

A user reported the symptom on a 20-minute slow-HDD scan: the
job was genuinely making progress in `BulkScanner.scan()`,
but the Status page showed `0 / ? files — ?%` the whole
time, making the operator think the job was stuck.

### The fix

```js
var enumerating = (job.status === 'scanning');
```

The backend's `_scanning` flag is True for the entire
scanner call and flipped False right before `update_bulk_job_status(...,
'running', total_files=...)`. So `status === 'scanning'`
alone is the authoritative signal — no need to also check
total_files.

After the fix:
- **0–120 s into scanning**: spinner + "Enumerating source
  files… 1m 30s elapsed"
- **120 s+**: the existing v0.32.1 stuck warning fires —
  `⚠ Enumerating — stuck? No progress for X. Stop the job and
  retry, or check the log viewer.` (the heartbeat field
  `job.last_heartbeat` isn't surfaced for scanner-phase jobs,
  so the `(!job.last_heartbeat)` check in the stuck condition
  is always true during scanning — which means after 2min any
  scan correctly gets the warning. Honest signal.)

### Backend not changed

The original v0.32.7 plan included a backend "auto-complete
scan when total_files=0" fix. Re-reading `bulk_worker.py`
confirmed it's not actually broken: the worker DOES transition
`scanning → running → completed` on a zero-file scan via the
existing path (line 474 sets `_scanning=False`, then 476
calls `update_bulk_job_status(..., 'running', total_files=0)`,
then the empty file queue is drained at line 528, then 542
transitions to `'completed'`). The user's stuck-at-scanning
case was a slow HDD walk, not a missing transition. Withdrawn.

### Cache-bust

`?v=0.32.6 → ?v=0.32.7` on `live-banner.js` for all 3 pages
that load it. Same convention as before.

### Files

- `core/version.py` — bump to 0.32.7
- `static/status.html` — `enumerating` condition simplified
  + extended comment explaining why
- `static/trash.html`, `static/status.html`,
  `static/pipeline-files.html` — `?v=0.32.7` cache-bust
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No backend changes.

---

## v0.32.6 — Server-authoritative timers on Trash progress card

**Trash progress timers are now server-authoritative.
`/api/trash/empty/status` and `/api/trash/restore-all/status`
return `started_at_epoch` and `last_progress_at_epoch` (set
by the worker when it enters and bumped on every total/done
change). The Trash-page progress card reads these on every
poll and renders elapsed time + "last update" against the
true op clock — so navigating away and back no longer resets
either timer.**

### Why this matters

Reported by the operator after upgrading to v0.32.4: clicked
Empty Trash, watched the card, navigated away to Status, came
back to Trash. Card showed "Starting…" with "elapsed 12s" —
implying the op had only been running 12 seconds, when in
reality the worker had been chewing through the 51,684-row
pile for several minutes already. Confusing and undermines
trust in the progress card.

Root cause: the v0.32.4 frontend computed elapsed-time as
`Date.now() - opStartTs`, where `opStartTs` was set to
`Date.now()` whenever the card was shown. Returning to the
page meant `checkInFlightOps` re-instantiated the card with
a fresh `opStartTs`, so the timer reset.

The fix is server-side timestamps. The backend already had
authoritative knowledge of when the worker started; we just
weren't surfacing it.

### Implementation

**Backend (`core/lifecycle_manager.py`):**

- Both `_empty_trash_status` and `_restore_all_status` dicts
  now carry `started_at_epoch` and `last_progress_at_epoch`
  fields.
- Workers set both fields on entry (`time.time()`).
- `_bump_empty_progress()` / `_bump_restore_progress()`
  helpers stamp `last_progress_at_epoch = time.time()`
  whenever total or done changes (Phase 1 enumeration
  finishing, Phase 2 batch updates, Phase 3 source_files
  updates, per-row restore increments).
- `finally` block does NOT reset the timestamps — the
  post-finish "Done" frame should still reflect the true
  elapsed time the operation took.

**Backend (`api/routes/trash.py`):**

- POST `/empty` and POST `/restore-all` flatten
  `started_at_epoch`, `last_progress_at_epoch`, `total`,
  `done` into the top-level `already_running` response so
  the frontend can adopt them immediately (no need to wait
  for the first GET poll).

**Frontend (`static/trash.html`):**

- `opStartTs` and `lastProgressTs` module-level state
  variables now refer to server-authoritative values
  (server `*_epoch * 1000` to align with `Date.now()`
  millisecond units).
- New `adoptServerTimestamps(s)` helper called on every poll
  + on the initial mid-op recovery fetch + on the
  `already_running` POST response.
- `showCard()` no longer resets `opStartTs` /
  `lastProgressTs` — `checkInFlightOps` may have pre-seeded
  them with server values.
- `updateTimers()` (the 250 ms ticker) renders elapsed +
  last-update directly from server-anchored timestamps.

### Cache-bust

Bumped `?v=0.32.5` → `?v=0.32.6` on the `live-banner.js`
script tag in all 3 pages that load it. The trash.html JS
itself doesn't need a bust (the inline script is part of
trash.html which is freshly fetched with the page), but
keeping the convention is cheap.

### Files

- `core/version.py` — bump to 0.32.6
- `core/lifecycle_manager.py` — `time` import +
  `started_at_epoch` / `last_progress_at_epoch` fields +
  `_bump_empty_progress` / `_bump_restore_progress` helpers
  + non-reset on `finally`
- `api/routes/trash.py` — flatten timestamps into
  `already_running` POST responses
- `static/trash.html` — `adoptServerTimestamps` helper,
  `opStartTs` / `lastProgressTs` semantic shift,
  `showCard` no longer resets, `checkInFlightOps`
  pre-seeds, cache-bust to `?v=0.32.6`
- `static/status.html`, `static/pipeline-files.html` —
  cache-bust live-banner to `?v=0.32.6` (consistency)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

---

## v0.32.5 — Cache-bust on live-banner.js

**Cache-bust on `live-banner.js` so returning operators get the
latest banner code without a manual hard-refresh. The script
tag on each of the three pages that load the banner
(`trash.html`, `status.html`, `pipeline-files.html`) now
carries a `?v=0.32.5` query string. Bump the `?v=` on every
release that touches `live-banner.js`.**

### Why this matters

The v0.32.4 ship surfaced a real-world problem: even after a
clean container rebuild, returning operators didn't see the
v0.32.3 Live Banner because their browser had cached
`live-banner.js` from an earlier deploy. FastAPI's
`StaticFiles` doesn't add `Cache-Control: no-cache`, so
browsers used heuristic freshness based on `Last-Modified` and
held the old bytes.

The fix is a one-line change to each page's script tag — add
a `?v=<release>` query string. Browsers treat URLs with
different query strings as different resources, so a version
bump forces a fresh fetch on the next page load. No
infrastructure change, no headers, no service worker.

### The convention going forward

Every release that touches `static/js/live-banner.js` (or any
other cached JS in `static/js/`) should bump the `?v=` query
string in the loading `<script>` tag(s). The convention:

```html
<!-- Bump the ?v= when live-banner.js changes. -->
<script src="/static/js/live-banner.js?v=0.32.5"></script>
```

Three files to update: `trash.html`, `status.html`,
`pipeline-files.html` (grep `live-banner\.js` to find them).
A future release could automate this — read `__version__` at
import time, inject into a base template — but the manual
convention is fine for now: each release already touches
`core/version.py` + multiple docs files, so a 3-file
find-and-replace fits the existing rhythm.

### Files

- `core/version.py` — bump to 0.32.5
- `static/trash.html` — `?v=0.32.5` on the live-banner tag
- `static/status.html` — same
- `static/pipeline-files.html` — same
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No backend changes.

---

## v0.32.4 — Inline progress card on Trash page

**Inline progress card on the Trash page. Empty Trash and
Restore All now show a prominent in-page progress card right
between the action buttons and the file table — impossible to
miss, with progress bar, X / Y counter, EWMA rate, ETA,
elapsed-time ticker, last-poll-age indicator, and a
"backend may still be enumerating" hint when the worker
silently chews through a 50K+ row pile during its initial
SQL COUNT.**

### Why this matters

The user reported: clicked Empty Trash on the production
instance (51,684 rows). The button went disabled and showed
"Purging 0 / 51684...", but stayed at 0 for tens of seconds.
The global Live Banner from v0.32.1 didn't appear in the
viewport. Operator couldn't tell whether MarkFlow was actually
processing the command or was hung.

The fix is in-page. The new `.trash-progress` card lives right
under the action buttons. It appears immediately on click,
runs an indeterminate animated bar during the worker's
enumeration window (SQL COUNT over 50K+ rows takes 30-60s
before the first done count comes back), then transitions to
a real progress bar once `done` starts moving. The card is
self-contained — the card works even when the global Live
Banner has a positioning / z-index / cache issue.

### Card surfaces

- **Pulse dot + icon + label** ("🗑 Emptying trash" /
  "♻ Restoring all from trash" / "Done" / "Failed")
- **Progress bar** — animated indeterminate during
  enumeration, deterministic once total > 0
- **Counter** — "12,047 / 51,684 files (23%)"
- **Rate** — EWMA-smoothed, "437 files/s"
- **ETA** — derived from rate; "ETA 1m 30s"
- **Elapsed timer** — "elapsed 0s" → "elapsed 2m 15s",
  ticks every 250 ms client-side
- **Last-poll-age** — "last update just now" /
  "last update 12s ago" — operator sees whether polling
  is alive
- **Sticky hint** — appears after 30s if `done` is still 0:
  "Backend may still be enumerating the trash pile — large
  counts (50K+) can take 30-60s before progress numbers
  appear. The worker is alive as long as 'last update' is
  recent."
- **Dismiss button** — appears when finished or errored

### Other improvements bundled in

- **Poll cadence sped up** from 2 s to 1 s. Operator sees
  movement faster.
- **Mid-op recovery** — on page load, the trash page now
  checks `/api/trash/empty/status` and `/api/trash/restore-all/status`;
  if either is running, the inline card appears with the
  current progress (so an operator who refreshes the page
  mid-op doesn't lose feedback).
- **Network blip resilience** — transient poll failures no
  longer abort the operation tracking; the card just stops
  updating, the "last update" timer grows, and polling
  resumes on the next tick.

### Files

- `core/version.py` — bump to 0.32.4
- `static/trash.html` — new `.trash-progress` card CSS
  block + HTML element + unified `runTrashOp` driver +
  `checkInFlightOps` recovery path
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.
No backend changes — the existing `/api/trash/empty` +
`/api/trash/restore-all` endpoints (and their `/status`
companions) are unchanged.

---

## v0.32.3 — Trash 500-row cap removed, banner positioned below nav, banner UX polish

**Three bug fixes that surfaced from v0.32.1's Empty Trash +
Live Banner deploy. Trash list 500-row cap removed (was
showing "500 files in trash" indefinitely on a 60K-row pile);
single Empty Trash click now clears the whole pile in one
shot (was capped at 500 per click); banner positioned below
the nav bar instead of on top of it; banner shows "Starting…"
during the 100–500 ms enumeration window instead of
confusing "0 / 0 files".**

### What was broken

The v0.32.1 Empty Trash workflow + Live Banner combo had three
issues that confused operators using them end-to-end:

1. **Trash list capped at 500 rows.**
   `core/db/lifecycle.py:get_source_files_by_lifecycle_status`
   silently defaulted `limit=500`. Every caller that didn't pass
   an explicit limit got the first 500 rows. `/api/trash` then
   ran `total = len(files)` and reported `total: 500` — operators
   saw "500 files in trash" indefinitely on instances with much
   bigger trash piles. `purge_all_trash()` had the same bug, so
   one Empty Trash click only ever cleared the first 500 rows.
2. **Banner covered the nav bar.** `position: fixed; top: 0;
   z-index: 9999` painted over the sticky nav (`top: 0; z-index:
   100; height: 56px`). Operators couldn't navigate while a
   purge was in flight.
3. **Banner showed "0 / 0 files" during the kickoff window.**
   The empty-trash worker flips `running=true` before the SQL
   count completes — there's a 100–500 ms window where the
   banner sees `running=true AND total=0`, and it rendered "0 /
   0 files · — files/s · ETA —" which looked broken.

### Fixes

**Bug 1 — Trash 500-cap removed:**
- `get_source_files_by_lifecycle_status` accepts `limit=None`
  to fetch all matching rows in a single query (default still
  500 for legacy callers that paginate by hand).
- New helper `count_source_files_by_lifecycle_status(status)`
  runs a dedicated `SELECT COUNT(*)` for true totals.
- `/api/trash` (list) — uses count helper for `total`,
  paginated `LIMIT/OFFSET` for the `files` array.
- `/api/trash/empty` and `/api/trash/restore-all` (POST) —
  report true total via count helper.
- `core/lifecycle_manager.purge_all_trash` and
  `restore_all_trash` — pass `limit=None` so one click clears
  everything.

**Bug 2 — Banner below nav:**
- `position: fixed; top: 56px; z-index: 90` (nav is z-index
  100). Banner pins directly below the nav; both stay
  anchored as the page scrolls.
- Body gains `padding-top: 44px` when the banner is visible
  (via inline-injected `<style>` rule) so page content isn't
  hidden under the banner.

**Bug 3 — Banner "Starting…" UX:**
- When `running=true && total<=0 && !finished`, render
  "Starting…" instead of the zero-counter line. Rate / ETA
  lines collapse during this window. Once `total` populates
  on the next 2 s tick, normal counter format takes over.

### Files

- `core/version.py` — bump to 0.32.3
- `core/db/lifecycle.py` — `limit=None` support + count
  helper
- `core/lifecycle_manager.py` — purge/restore use
  `limit=None`
- `api/routes/trash.py` — three endpoints use count helper +
  LIMIT/OFFSET on the SQL side
- `static/js/live-banner.js` — top:56px, z-index:90,
  body padding, "Starting…" UX
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

### Operator-visible API change

```bash
# /api/trash now returns the TRUE total
curl -s 'http://localhost:8000/api/trash?per_page=25&page=1'
# was: {"total": 500, ...}; now: {"total": 51684, ...}

# /api/trash/empty reports true total in kickoff
curl -sX POST 'http://localhost:8000/api/trash/empty'
# was: {"status":"started","total":500}; now: {"total": 51684}

# A single click now clears the entire pile (~30 s for 50K rows)
```

---

## v0.32.2 — Unrecognized-file recovery: `.tmk` handler + browser-download suffix shim

**Unrecognized-file recovery: `.tmk` handler + browser-download
suffix shim. Files that were stranded in the Unrecognized
bucket because they had a `.download` / `.crdownload` /
`.part` / `.partial` suffix (browser save-page-as / interrupted-
download artifacts) or a `.tmk` extension (small markers next
to `.mp3` recordings) now flow through the existing
`SniffHandler` delegation chain.**

The fix is small and surgical:

- `formats/sniff_handler.py` registers for the new extensions.
  A new `_strip_browser_suffix(path)` helper strips the
  trailing suffix and checks the inner extension; if it has
  a registered handler, the file is routed there directly
  (e.g. `add-to-cart.min.js.download` → `.js` → text/code
  handler). No content-sniffing round-trip required.
- For `.tmk` (and other unfamiliar extensions reaching
  SniffHandler), the existing 3-layer recovery — MIME-byte
  detection via libmagic, UTF-8 text-content heuristic →
  TxtHandler, metadata-only stub last-resort — is unchanged.
- The metadata-only stub now records the **actual originating
  extension** in `DocumentMetadata.source_format` (e.g.
  `"tmk"`, `"download"`) rather than always `"tmp"` so
  operators triaging the converted output can see what they're
  looking at without back-tracing the source path.

This is **Phase 1c + Phase 3** of
[`docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md`](docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md).
Phase 0 (operator places a fresh `.tmk` sample for byte-level
discovery) and Phase 2 (general format-sniff fallback for any
unrecognized extension, with `bulk_files.sniffed_*` columns +
search/preview UI surfacing) are deferred. The shipped pieces
already recover the operator's actual stuck files; Phase 2
adds breadth at the cost of a DB migration + Meili re-index.

### Files

- `formats/sniff_handler.py` — `EXTENSIONS` expanded to
  `["tmp", "tmk", "download", "crdownload", "part", "partial"]`;
  `_strip_browser_suffix` helper; Step 0 in `ingest`;
  metadata-only stub records the originating extension.
- `core/version.py` — bump to 0.32.2
- `docs/help/unrecognized-files.md`,
  `docs/version-history.md`, `docs/help/whats-new.md` —
  user + engineering docs

No DB migration. No new dependencies. No new scheduler jobs.
No frontend changes.

---

## v0.32.1 — Pipeline-files filter + AutoRefresh + Live Banner + clickable status pills

**Pipeline Files include-trashed filter, AutoRefresh shared
helper across stale-data pages, Live Status Banner that mirrors
long-running operation progress across pages, clickable
SCANNING / PENDING / LIFECYCLE pills on Status, log-viewer
deep-link via `?q=`, scanning-card UX fix
("Enumerating source files…" instead of "0 / ? files — ?%"),
trash purge-on-demand reducing 60K+ in_trash rows by ~95%,
and a written plan for `.tmk` handler + `.download`
format-sniff recovery.**

### Why this matters

Operators triaging files from the v0.32.0 preview page were
running into three classes of confusion:

1. **Stale lists** — Pipeline Files / Batch Management /
   Flagged / Unrecognized never auto-refreshed. Trigger a
   force-action, switch tabs, come back: the file still showed
   `pending` until manually reloading.
2. **Lifecycle bloat** — `bulk_files` had 113K rows of which
   only ~2K reflected files actually on disk. Pipeline Files
   showed every one of them, mixing trashed-but-not-purged
   rows in with active files.
3. **Opaque jobs** — the SCANNING and PENDING pills on the
   Status page were dead labels, with no way to drill into
   what was happening. A stuck scan looked the same as a
   running one ("0 / ? files — ?%"), with no path to the log
   that would explain why.

v0.32.1 addresses all three plus follow-on UX polish.

### Pipeline Files include-trashed filter

`bulk_files.lifecycle_status` is independent of `bulk_files.status`
— a file can be `status='pending'` (never converted) AND
`lifecycle_status='in_trash'` (lifecycle scanner saw it
disappear from disk). The Pipeline Files page ignored
lifecycle, so 60K+ trashed-but-not-purged rows showed up as
pending forever.

Backend: `core/db/bulk.py:get_pipeline_files()` and
`api/routes/pipeline.py:pipeline_stats()` gain an
`include_trashed: bool = False` parameter. When False, both
endpoints add a JOIN on `source_files` and filter
`sf.lifecycle_status = 'active' OR sf.lifecycle_status IS NULL`
(the IS NULL preserves orphaned rows from older datasets).
Stats cache now keyed only for the default-active case;
trashed-included results are computed fresh.

Frontend: new "Include trashed / marked-for-deletion files"
checkbox below the search bar. When checked, both
`/api/pipeline/stats` and `/api/pipeline/files` receive
`include_trashed=true`; counters and list refresh together.

Default behavior change: list dropped from ~113K rows to ~2K
on this instance. The toggle stays for power users who want
to see what the registry knows even after disk-state
divergence.

### Trash purge-on-demand

The 60K+ `in_trash` rows weren't going to age out for ~42 days
under the default 60-day retention. We triggered the existing
`POST /api/trash/empty` endpoint in a 15-call loop (the
endpoint caps each call at 500 source_files via the underlying
`get_source_files_by_lifecycle_status` query). Cleared
~7,500 rows immediately; the rest age out on the existing
schedule. **Note**: a future change should let `purge_all_trash`
process all rows in one call — capping at 500 was originally
defensive against memory blow-up but on the current schema
the row weight is small enough to handle 60K in one pass.

### AutoRefresh shared helper

New `static/js/auto-refresh.js` (~120 LOC) — tiny opt-in
polling helper:

```js
AutoRefresh.start({
  refresh: () => { loadStats(); loadFiles(); },
  intervalMs: 30000,
});
```

Behavior: polls every `intervalMs` while tab is visible.
Pauses on `visibilitychange === 'hidden'` so backgrounded
tabs don't burn API calls. On focus, fires one immediate
refresh and resumes the interval. Concurrency guard prevents
two refreshes from overlapping on slow networks.

Wired this release:
- `pipeline-files.html` (30 s) — file list + status chips
- `batch-management.html` (60 s) — batch list (existing 5 s
  pollTick still handles status counters)
- `flagged.html` (30 s) — flagged-file queue + counts
- `unrecognized.html` (60 s) — unrecognized-file list

Pages with their own polling / SSE (status, history, bulk,
resources, db-health, debug, log-viewer, trash, preview)
are left alone — they have correct refresh already.

### Live Status Banner

New `static/js/live-banner.js` (~270 LOC) — sticky banner at
top of any page that includes the script. Polls a configurable
list of long-running operation endpoints (currently
`/api/trash/empty/status` and `/api/trash/restore-all/status`)
and shows progress when any is in flight:

```
🗑 Emptying trash · [bar 25%] · 127/500 files · 2.4 files/s · ETA 2m 35s · ×
```

Architecture:
- Single banner DOM, position:fixed, z-index 9999.
- 2 s poll cadence; pauses while tab hidden.
- ETA computed client-side via EWMA-smoothed throughput so
  status endpoints don't need ETA fields.
- Auto-collapses 4 s after operation finishes (so operator
  sees the green "Done" state).
- Built entirely via `createElement` / `textContent` — no
  innerHTML, XSS-safe even if an endpoint were ever to return
  operator-controlled text.
- Public hook `window.LiveBanner.register({key, url, label,
  icon, noun})` for pages to add their own long-running ops.

Wired to: `trash.html`, `status.html`, `pipeline-files.html`.

### Clickable status pills + log-viewer deep-link

Status pills on the Status page are now hyperlinks:

| Pill | Click destination |
|------|-------------------|
| **SCANNING `<id>…`** | `/log-viewer.html?q=<job_id_prefix>&mode=history` |
| **PENDING** (header card) | `/pipeline-files.html?status=pending` |
| **LIFECYCLE SCAN** (running) | `/log-viewer.html?q=lifecycle_scan&mode=history` |
| **LIFECYCLE SCANNER** (idle) | `/log-viewer.html?q=lifecycle_scan&mode=history` |

Log viewer (`static/log-viewer.html`) gained `?q=<text>` and
`?mode=history` URL parameters. On load, if `q` is present
the search input is pre-filled and dispatched; `mode=history`
flips to history search mode and runs immediately. Lets
operators jump straight from "what's the scanner doing right
now?" to the line-by-line log without typing the job ID.

CSS: new `.status-pill--link` class with the existing
`.stat-pill--link` hover pattern (opacity + scale) plus a
small ↗ glyph to signal external destination.

### Scanning-card UX fix

Active scanning jobs in their first ~10 s of life show
`total_files = NULL` because the bulk_scanner is still
walking the source tree. The status card was rendering
"0 / ? files — ?%" which looked broken. New rendering:

- While `status='scanning' AND total_files IS NULL`: show
  spinner + *"Enumerating source files… 12s elapsed"*.
- If elapsed > 2 min AND `last_heartbeat IS NULL`: switch to
  warning tone — *"⚠ Enumerating — stuck? No progress for
  3m 24s. Stop the job and retry, or check the log viewer."*
- After `total_files` is set: revert to the normal
  "N / M files — pct%" line.

Diagnoses the exact symptom the user reported — gives them a
clear action (Stop + retry) when a job is genuinely stuck
rather than burying it in a meaningless progress label.

### Plan: `.tmk` handler + `.download` format-sniff

Written plan at
[`docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md`](docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md).
Three phases:

- **Phase 0** — discovery: get a fresh `.tmk` sample (all
  on-disk samples have already aged into `in_trash`); decide
  the handler shape based on actual content.
- **Phase 1** — `.tmk` handler. 3 variants per discovery
  results (text-extension, audio-sidecar, or unknown-format
  stub).
- **Phase 2** — general format-sniff fallback for
  unrecognized files. Magic-byte test → text heuristics →
  `python-magic` cascade. Stores `sniffed_format /
  sniffed_method / sniffed_confidence` on `bulk_files`;
  surfaces in search results + file detail page.
- **Phase 3** — browser-suffix shim (`.download` /
  `.crdownload` / `.part` / `.partial`) — strip the suffix
  and re-classify on the real extension. Cheap special case
  that handles the bulk of the user's `.download` files in
  one go.

Implementation deferred — operator can ship incrementally
when ready.

### Files this release

- `core/version.py` — bump to 0.32.1
- `core/db/bulk.py` — `get_pipeline_files()` lifecycle filter
- `api/routes/pipeline.py` — endpoints honor `include_trashed`
- `static/js/auto-refresh.js` (new)
- `static/js/live-banner.js` (new)
- `static/pipeline-files.html` — include-trashed toggle +
  AutoRefresh wire-up + live banner script
- `static/batch-management.html`, `flagged.html`,
  `unrecognized.html` — AutoRefresh wire-up
- `static/trash.html`, `status.html` — live banner wire-up
- `static/status.html` — clickable pills, scanning-card fix
- `static/log-viewer.html` — `?q=` / `?mode=history` URL
  params
- `static/markflow.css` — `.status-pill--link` hover styles
- `docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md`
  (new plan)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`, `docs/help/preview-page.md`,
  `docs/help/keyboard-shortcuts.md`,
  `docs/help/_index.json`, `docs/key-files.md`

No DB migration. No new dependencies. No new scheduler jobs.

---

## v0.32.0 — File preview page + force-process + related-files

**File preview page (`static/preview.html`) — full-fledged
file-detail viewer replacing the long-standing 19-line stub.
Click the folder icon on a Pipeline Files row and a real page
opens with inline content preview, metadata sidebar, conversion +
analysis status, sibling navigation, and operator actions. Plus
side polish on Batch Management (page-size selector, collapse/
expand-all toggle).**

The preview page is the source-file inspection surface — a peer
of the converted-Markdown viewer at `static/viewer.html`. Where
viewer.html renders the Markdown OUTPUT, preview.html shows the
INPUT: the original file, its metadata, where it sits in the
pipeline, and what neighbors live next to it.

### What clicking the folder icon now produces

A page with a sticky toolbar (breadcrumb · title · status pill ·
flag pill · action buttons) and a two-pane layout:

- **Left**: per-format viewer — image, audio player, video
  player, PDF iframe, text excerpt, rendered Markdown (for
  converted Office docs), archive listing, or "no inline
  preview" metadata-only fallback.
- **Right**: metadata cards — file stats, source_files
  registry row, latest bulk_files conversion, latest
  analysis_queue row, active file_flags, sibling listing with
  ← Prev / Next → buttons + clickable file list.

Action buttons:
- **Download** — direct file download via Content-Disposition
- **Open in new tab** — same content URL, new tab
- **Copy path** — `navigator.clipboard.writeText` (with a
  document.execCommand fallback for non-secure contexts)
- **Show in folder** — jumps to Pipeline Files filtered to
  the parent directory (uses the new `?folder=` query param)
- **View converted →** — only when a successful conversion
  exists; opens viewer.html for the full Markdown experience
- **Re-analyze** — only when an analysis row exists; uses
  the v0.31.0 delete-and-re-insert endpoint

Keyboard shortcuts: `←` / `→` navigate to prev / next sibling
file; `Esc` jumps back to Pipeline Files filtered to the
parent folder.

### Backend — new `/api/preview/*` router

Six endpoints, all `OPERATOR+`-gated and path-keyed (verified
by `core.path_utils.is_path_under_allowed_root`):

- `GET /api/preview/info` — composite metadata + status +
  sibling listing (cap 200 entries, 10 s wall-clock)
- `GET /api/preview/content` — raw bytes via `FileResponse`
  with HTTP range support (so video/audio seek)
- `GET /api/preview/thumbnail` — server-rendered JPEG via
  the shared `core.preview_thumbnails` cache
- `GET /api/preview/text-excerpt` — first N bytes UTF-8
  decoded (`errors='replace'`, hard cap 512 KB)
- `GET /api/preview/archive-listing` — zip / tar (auto-detect
  gz/bz2/xz) / 7z entries (cap 500)
- `GET /api/preview/markdown-output` — converted Markdown if
  a successful `bulk_files` row exists, else 404

### Refactor: thumbnail machinery in `core/preview_thumbnails.py`

Extracted the thumbnail cache + dispatch logic out of
`api/routes/analysis.py` into a shared module. Cache key is
now path-based (resolved + mtime + size), so a thumbnail
rendered via the source_file_id-keyed analysis endpoint AND
the path-keyed preview endpoint share the same cache hit.
The existing `/api/analysis/files/:id/preview` endpoint stays
externally identical — it just delegates to the shared
module.

### Helpers: `core/preview_helpers.py`

Pure functions for `classify_viewer_kind(path)`,
`get_mime_type(path)`, `get_file_category(path)`. Used by the
info endpoint to compute the dispatch hint server-side so the
frontend doesn't repeat extension classification logic.

### Side polish: Batch Management

The Batch Management page now has:

- **Page-size dropdown** (10 / 30 / 50 / 100 / All — default
  30, persists to localStorage)
- **Expand all / Collapse all** toggle that uses the existing
  card-header click handler so lazy-loading of file lists
  fires on expand
- **Pagination footer** with `← Prev` / `Next →` and
  "Showing 1-30 of 247 batches" indicator

The page sometimes lists hundreds of batches; the previous
"render every card on page load" behavior was unwieldy.
Client-side pagination is good enough — the API already
returns the full list, we just slice it for display.

### Pipeline Files `?folder=` filter

Small addition (~30 LOC). The "Show in folder" button on the
preview page sends users to Pipeline Files filtered to a
specific directory; this required teaching pipeline-files.html
to honor a `?folder=<path>` query parameter that pre-fills
the search box.

### Side fix: quiet shutdown for the lifecycle scan

`core/scheduler.py:run_lifecycle_scan()` wrapped its body in
`try / except Exception`. When the container received SIGTERM
mid-scan, the asyncio task got cancelled while awaiting
`aiosqlite.connect.__aexit__()` inside
`mark_file_for_deletion → update_source_file → get_db()`, and
the resulting `CancelledError` slipped past the broad
`except Exception` (it's a `BaseException` in Python 3.8+),
surfacing inside apscheduler as a job-raised-exception
traceback in `markflow.log` on every clean restart.

Fix: explicit `except asyncio.CancelledError` clause that logs
`scheduler.scan_cancelled_on_shutdown` at info level and
returns. Cancellation has already done its job — the next
scheduled interval picks up the work. Other apscheduler-facing
job functions in `scheduler.py` use the same broad-except
pattern but haven't been observed crashing on shutdown; left
alone for now.

### Side cleanup: stale `db-*.log` files removed

`core/db/contention_logger.py` was retired in v0.24.2 but its
three temp files (`db-contention.log` 375 MB,
`db-queries.log` 272 MB, `db-active.log` 15 MB — last write
2026-04-23) sat untouched on disk. Removed during this release.
No code path writes to those filenames anymore.

### Force-process button + real-time progress (file-aware)

A new "🎙 Transcribe" / "⚙ Process" / "🔍 Analyze" button on
the preview page kicks off the full pipeline for a single file:
removes it from `pending` / `failed` / `batched` state, runs the
appropriate engine (Whisper / converter / LLM vision), writes
the output to the configured directory, and reindexes — without
forcing the operator to wait for the next pipeline tick.

- **File-aware label** — picked from `info.action` returned by
  `/api/preview/info`. Backed by a single-line dispatcher
  `core.preview_helpers.pick_action_for_path(p)`:
    - audio/video → `transcribe`
    - office/pdf/text/archive → `convert`
    - image (any preview-eligible extension) → `analyze`
    - everything else → `none` (button hidden)
- **Backend** — `POST /api/preview/force-action {path}` schedules
  a `BackgroundTask`. Two paths:
    - `transcribe` / `convert` → upserts a `bulk_files` row, then
      reuses `_convert_one_pending_file` from v0.31.6 (so the
      same routing / output-mapping / write-guard / index logic
      applies).
    - `analyze` → calls `enqueue_for_analysis`, then forces a
      `run_analysis_drain()` so the LLM call goes out within the
      current request rather than waiting up to 5 minutes for
      the scheduled tick.
- **Real-time progress** — in-memory dict
  (`_FORCE_ACTION_STATE`) keyed on resolved source path,
  exposed via `GET /api/preview/force-action-status?path=…`.
  Frontend polls every 2 s; each phase
  (`queued → preparing → running → success/failed`) renders an
  inline card under the action buttons with a live elapsed-time
  ticker. The poll loop quits on success/failed and re-fetches
  `/info`, which re-runs the dispatch — sidebar Conversion /
  Analysis cards repopulate, and the audio viewer adds a new
  transcript pane below its `<audio>` element.
- **Re-entrancy guard** — a second click while a prior run is
  still in-flight returns 409. Works across browser refreshes
  (state is process-local, not session-local).

### Related-Files sidebar + selection-driven search

The preview page now has two new sidebar cards plus a global
text-selection chip — operators can find context-similar files
without leaving the file detail.

- **Auto-populated "Related Files" card** — fires
  `/api/preview/related` on every page load with `mode=semantic`
  by default. Toggle to `keyword` (Meilisearch) via tabs.
  Backend derives the query in this order: converted Markdown
  excerpt (first 1000 chars) → analysis description →
  filename + parent directory tokens.
- **Sidebar search panel** — typed-query `<input>` + mode
  dropdown (semantic / keyword) + "🤖 AI Assist ↗" deep-link
  to `/search.html?q=…&ai=1` in a new tab. AI Assist intentionally
  does NOT auto-fire — preview-page opens shouldn't burn LLM
  tokens, so the synthesize action is operator-initiated.
- **Highlight-to-search chip** — `mouseup` inside the viewer,
  transcript pane, analysis description, or any related-file
  list pops a floating chip with [🧠 Semantic | 🔎 Keyword |
  🤖 AI ↗] options. Position is computed from the selection's
  `getBoundingClientRect()` and flips below if the selection
  is too close to the viewport top.
- **`Find related ↗` action button** — opens `/search.html` in
  a new tab seeded with the file's content as the query, so the
  operator gets the full search page without losing the preview
  context.

Backend endpoint `GET /api/preview/related` accepts:
`path`, `mode` (`keyword`|`semantic`), optional `q` override,
`limit` (1–25 default 10). Returns hits filtered to exclude the
current file, with `path / name / score / source_format /
size_bytes / doc_id / snippet`. Vector hits use
`source_path` from the Qdrant payload directly — no Meili
roundtrip.

### Staleness banner (don't lose the view)

When the user is away from a preview tab and a force-action /
pipeline tick changes the underlying state, the page detects it
on `visibilitychange`:

- `/info` now returns `info_version` — a 16-char SHA256 prefix
  of `(size, mtime, viewer_kind, conv.status, conv.converted_at,
  conv.output_path, analysis.status, analysis.analyzed_at,
  analysis.description[:64], len(flags))`.
- Frontend stores it on load. On tab-focus it re-fetches `/info`
  and compares; if the version changed, it re-renders + shows a
  blue banner: *"This file changed while you were away — page
  refreshed with the latest data."* Auto-dismisses after 12 s.
- Suppressed during force-action polling so we don't show the
  banner for our own work-in-progress.

### Better error UX on missing files

Click "Open in new tab" / "Download" on a file the registry
remembers but disk has lost? Two fixes:

- **Frontend** — when `info.exists=false`, the buttons render
  as `<button disabled>` with tooltip *"File not found on
  disk — cannot serve content"* instead of linking to a
  404-returning endpoint.
- **Backend** — `/api/preview/content` sniffs `Accept: text/html`.
  Browser navigations get a styled error page (path + reason +
  back-to-preview link); media-element / fetch consumers still
  get the JSON 404 so `<img onerror>` fallback paths keep
  working.

### Files

- `core/version.py` — bump to 0.32.0
- `core/preview_thumbnails.py` (new) — shared thumbnail cache
- `core/preview_helpers.py` (new) — classification helpers
- `api/routes/preview.py` (new) — six endpoints
- `api/routes/analysis.py` — thumbnail helpers replaced by
  imports from `core.preview_thumbnails`; preview endpoint
  unchanged externally
- `core/scheduler.py` — `import asyncio` + new
  `except asyncio.CancelledError` clause in
  `run_lifecycle_scan` (side fix)
- `core/preview_helpers.py` — added
  `pick_action_for_path()` + ACTION_* constants for the
  force-action dispatcher
- `api/routes/preview.py` — added force-action endpoints
  + state tracker, `/related` endpoint with keyword/semantic
  modes, `info_version` etag, friendly HTML 404 for browser
  hits on missing-file content
- `main.py` — register the new preview router
- `static/preview.html` — full rewrite + force-action button +
  progress card + Related/Search sidebar cards + selection
  chip + staleness banner + audio transcript pane
  (~1500 LOC after this release)
- `static/pipeline-files.html` — `?folder=` query param honored
- `static/batch-management.html` — page-size selector +
  Expand/Collapse-all toggle + pagination footer
- removed: `/app/logs/db-{contention,queries,active}.log` (662
  MB stale instrumentation, side cleanup)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

---

## v0.31.6 — Selective conversion of pending files

**Selective conversion on the History page's Pending Files
section — checkboxes per row + select-all + a "Convert Selected
(N)" / "Retry Selected (N)" bulk-action bar that lets operators
test a hand-picked subset of pending files instead of committing
to the full pipeline run.**

### Why this matters

The Pending Files card on the History page shows a paginated
view of every `bulk_files` row with `status='pending'` /
`'failed'` (113,354 entries on this instance). The existing
**Force Transcribe / Convert Pending** button kicks off
`/api/pipeline/run-now` which processes ALL of them in one
sweep. Operators wanted to **test a few specific files** (a
handful of MP3s, one problematic PDF) without committing to
the full sweep — especially given audio/video files take
minutes each via Whisper.

### Frontend (`static/history.html`)

- Checkbox column on the pending table (header has select-all,
  rows have per-file checkboxes bound to `bulk_files.id`).
- Bulk-action bar appears when ≥1 row is checked:
  - "N selected" count + summary "3× .mp3, 1× .pdf · 287.5 MB"
  - Cap warning if N > 100 (matches backend cap)
  - **Convert Selected (N)** / **Retry Selected (N)** button —
    verb switches based on status-filter dropdown
  - Clear selection button
- Selection persists across pagination via in-memory Set keyed
  on `bulk_files.id`. Switching the status filter
  (pending↔failed) clears selection (different eligibility
  sets). Select-all toggles current-page rows only — not all
  113k.
- Indeterminate state on select-all when partial selection.

### Backend (`api/routes/pipeline.py`)

`POST /api/pipeline/convert-selected` (OPERATOR+):

- `ConvertSelectedRequest` Pydantic body: `file_ids` (1–100).
- Validates each id has eligible status (`pending` / `failed`
  / `adobe_failed`). Returns 400 with structured
  `{not_found, ineligible, eligible_statuses}` if no eligible
  rows.
- Schedules a background batch with `asyncio.Semaphore(4)`
  concurrency (matches `BULK_WORKER_COUNT` default).
- Each file routes through `_convert_one_pending_file()`:
  - Resolves output dir from
    `core.storage_manager.get_output_path()` (Universal Storage
    Manager since v0.25.0); falls back to `/mnt/output-repo`.
  - Reconstructs source root by walking up the path until one
    of the mount roots matches (`/mnt/source`, `/host/c`,
    `/host/d`, `/host/rw`, `/host/root`); falls back to
    `source_path.parent`.
  - Uses `_map_output_path` to compute destination, mirroring
    `BulkJob._process_convertible`.
  - Honors `is_write_allowed()` write guard.
  - Calls `_convert_file_sync` in a worker thread; updates
    `bulk_files` via `db_write_with_retry`.
- Per-file exceptions never abort the batch — logged and
  recorded on the row.
- Returns immediately with `{queued, not_found, ineligible,
  message}`. Frontend's existing 30s pending-list refresh
  reflects status changes.

### Files

- `core/version.py` — bump to 0.31.6
- `api/routes/pipeline.py` — `ConvertSelectedRequest`,
  `convert_selected_files`, `_convert_one_pending_file`,
  `_run_convert_selected_batch` (~210 LOC)
- `static/history.html` — checkbox column, bulk-action bar,
  selection state Set, all handlers (~150 LOC)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

---

### v0.31.5 (carried-forward summary) — Preview format expansion + dynamic ETA framework

Hover preview now covers HEIC / HEIF (modern phone photos), ~30
RAW camera formats (Canon / Nikon / Sony / Fuji / Olympus /
Panasonic / etc), and SVG (rasterized server-side via cairosvg,
no XSS surface). Plus a dynamic ETA framework: log searches
now show "estimated 1.4s (12 prior obs)" hints based on EWMA
throughput observed on the host's actual hardware. Daily
scheduler job (count 18→19) captures CPU / RAM / load history.
Full context: [`docs/version-history.md`](docs/version-history.md).

---

### v0.31.4 (carried-forward summary) — Server-side ZIP bulk download

Multi-file download on Batch Management now produces a single
streaming ZIP via `POST /api/analysis/files/download-bundle`
instead of the v0.29.6 sequential synthetic-anchor loop. Cap
raised from 100 to 500 files; server enforces 500 files OR
~2 GiB uncompressed (whichever first). Smart compression
(`ZIP_STORED` for already-compressed extensions). Single-file
fast path skips the bundle endpoint entirely. Full context:
[`docs/version-history.md`](docs/version-history.md).

### v0.31.2 (carried-forward summary) — Multi-provider 5-layer vision resilience

OpenAI, Gemini, and Ollama vision batch paths now get the same
v0.29.9 Anthropic resilience pipeline: preflight validation,
exponential backoff with `Retry-After`, per-image bisection on
400, circuit breaker, operator banner. The breaker module is
process-wide so a 429 storm on one provider pauses any other
provider's calls — by design (one active provider at a time;
fail-fast on storms). Full context:
[`docs/version-history.md`](docs/version-history.md).

### v0.31.1 (carried-forward summary) — `.7z` viewer safety controls + system snapshot

Three polish items on top of v0.31.0's `.7z` viewability:
operator-tunable `.7z` byte cap (DB pref, 200 MB default, warn
above 1024 MB / above 50% free RAM, hard max 4096 MB), Log
Management Settings card host snapshot row (CPU model + cores,
RAM total/free, load 1m/5m/15m), and a live spinner + ticking
elapsed time on the log viewer while a search is in flight.
Full context: [`docs/version-history.md`](docs/version-history.md).

### v0.31.0 (carried-forward summary) — Five-item deferred-items bundle


Five-item bundle release: multi-provider filename interleaving
in vision_adapter.py (OpenAI/Gemini/Ollama, mirroring v0.29.8
Anthropic), time-range UI on the log viewer history search,
bulk re-analyze with DELETE + re-INSERT semantics, multi-log
tabbed live view (LogTab class refactor), and log subsystem
consolidation (deleted core/log_archiver.py; scheduler now
calls core/log_manager). Plus .7z archives readable in-place
via _SevenZReader subprocess wrapper with three-layer headless
safety (500k-line / 60s wall-clock / 200 MB byte caps). Full
context: [`docs/version-history.md`](docs/version-history.md).

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
