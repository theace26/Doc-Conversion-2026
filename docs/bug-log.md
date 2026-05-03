# MarkFlow Bug Log

**Forward-looking register of open / planned bugs.** This file is the
single source of truth for "what's broken right now." It complements
the other docs rather than replacing them:

| Doc | Role |
|---|---|
| **`bug-log.md`** (this file) | Open + planned bugs only. Status-tracked. Add a row when a bug is found, close it when it ships. |
| `version-history.md` | Per-release narrative changelog. Closes the loop on shipped fixes. |
| `gotchas.md` | Subsystem-organized prevention guide ("how not to recreate this bug class"). |
| `security-audit.md` | Formal audit findings inventory with severity scoring. Source of truth for security items; the bug-log only **references** them by ID. |
| `docs/superpowers/plans/*.md` | Per-feature implementation specs. Linked from bug rows when a plan exists. |

## Discipline

**Every release that fixes a bug must update this file** — close the
relevant row(s) by changing the status field and updating the "shipped
in" version. Don't delete closed rows; keep them for history (sort:
open/planned at top, shipped below).

**Every newly-discovered bug** (whether you plan to fix it now or
later) gets a row added with status `open`. If a plan is written for
it, link the plan in the row.

**Don't duplicate content** that lives elsewhere. Each bug row is a
one-line summary + cross-references to the doc(s) where the deep
context lives. The point of this file is fast triage ("what's open?"),
not narrative.

## Status field

| Status | Meaning |
|---|---|
| `open` | Found, not yet planned. Needs triage. |
| `planned` | Plan written, scheduled for an upcoming release. |
| `in-progress` | Code in flight on a branch. |
| `shipped-vX.Y.Z` | Closed. The version that contains the fix. Row stays for history. |
| `wontfix` | Deliberately not fixing. Brief rationale in the row. |

## Severity field

| Severity | Meaning |
|---|---|
| `critical` | Blocks core operator workflow OR data-loss risk. |
| `high` | Visible failure on a common path; workaround exists. |
| `medium` | Visible failure on an edge case OR silent failure that affects an important feature. |
| `low` | Cosmetic, minor inconvenience, or affects a rarely-used feature. |

---

## Open / Planned

(BUG-001 through BUG-018 closed in v0.34.1 / v0.34.2 / v0.34.3 / v0.34.4 / v0.34.6 / v0.34.7 / v0.34.8 / v0.34.9 — see Shipped section.)

### v0.35.0 follow-ups (drift bugs flagged by active-ops Phase 0 audit)

Drift bugs newly discovered during the Phase 0 pre-flight reconnaissance
for the Active Operations Registry plan (`docs/superpowers/plans/2026-04-28-active-operations-registry.md`).
Both are orthogonal to the active-ops feature itself; tracked here so
they don't get rolled into the registry commit but are not lost.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-013 | open | low | `tests/test_phase9/test_scheduler.py` imports renamed `_is_business_hours` symbol | `core/scheduler.py` renamed `_is_business_hours` (sync) to `_is_business_hours_async` (async, reads DB preferences for the window). The two test bodies (`test_business_hours_weekday_10am`, `test_business_hours_sunday_3am`) call it as if synchronous and the file is broken at import time. Fix is to either delete the two test bodies or rewrite them as async tests that mock the preference reads. Out of scope for active-ops registry plan; pick up as a separate ticket. Discovered in active-ops recon §A.4 (line 2694-2702). |
| BUG-014 | open | medium | `pipeline-card.js` POSTs to non-existent `/api/pipeline/rebuild-index` endpoint | `static/js/pipeline-card.js:285` POSTs to `/api/pipeline/rebuild-index`, but no such handler exists on the backend. The actual search-rebuild endpoint is `POST /api/search/index/rebuild` at `api/routes/search.py:703`. Pre-existing bug, orthogonal to active-ops registry. Fix is to update the frontend URL in `pipeline-card.js` (and possibly verify there are no other consumers of the bogus URL). Discovered in active-ops recon §D.5 (line 2781-2786). |

### v0.36.x planned (active-ops registry follow-ups)

Planned during the Active Operations Registry (v0.35.0) implementation. Originally reserved as BUG-015..019, but v0.34.7–v0.34.9 releases consumed those numbers; renumbered to BUG-019..023.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-019 | planned | low | Remove deprecated `/api/trash/empty/status` and `/api/trash/restore-all/status` after the v0.35.0 facade window. Endpoints currently return registry-derived data with `Deprecation: true` + `Sunset` headers. | spec §14, §17 P9 |
| BUG-020 | planned | low | Apply P1 (no-op-on-terminal) hardening to `BulkJob.tick()` and `lifecycle_scanner` `_scan_state` mutations. Currently partial. | spec §17 P1 |
| BUG-021 | planned | low | Periodic drift detection job (scheduler 03:55) that compares `bulk_jobs.processed` vs `active_operations.done` and `scan_runs` vs `active_operations` for the same `op_id`; logs `active_ops.drift_detected` on mismatch. | spec §17 P3 |
| BUG-022 | planned | low | Boot-time self-check that walks the scheduler job table and logs `scheduler.time_slot_collision` if two jobs are within 5 min of each other (and neither yields to the other). | spec §17 P7 |
| BUG-023 | planned | low | Audit deprecated public surfaces in the codebase and apply the v0.35.0 deprecation convention (`console.warn` for JS; `Deprecation` + `Sunset` headers for HTTP). | spec §17 P9 |
| BUG-024 | open | low | `tests/test_bulk_worker.py` calls `BulkJob(source_path=...)` but `BulkJob.__init__` takes `source_paths=` (plural). 5 tests fail at instantiation: `test_job_registry`, `test_bulk_job_run_empty_source`, `test_bulk_job_cancel`, `test_bulk_job_pause_resume`, `test_bulk_job_failed_file_does_not_stop_job`. Fix: update the 5 call sites in `tests/test_bulk_worker.py` to use `source_paths=`. Discovered during v0.35.0 smoke test (2026-04-30). |

### Security audit findings (long-running)

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| SEC-* | open (54 of 62) | mixed | Outstanding security-audit findings | 8 of 62 addressed in v0.29.0. Remaining 54: 10 critical + 18 high + 22 medium + 12 low/info — see `docs/security-audit.md` for the full enumerated list with severity, files, and remediation guidance. **Pre-prod blocker** until critical + high tier is closed. |

---

## Shipped (history)

### v0.38.0 — components.css theme-aware refactor

Four bugs closed in v0.38.0 (BUG-029 through BUG-032). Three were
latent regressions from v0.37.1 and v0.37.0; one was a shadow token
mismatch discovered during browser verification.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-029 | shipped-v0.38.0 | high | v0.37.1 import regression — markflow.css and 27 legacy HTML pages never loaded design-tokens.css or design-themes.css, so all 364 `var(--mf-*)` token references and every `[data-theme]` override silently no-op'd | `static/markflow.css` used `var(--mf-*)` tokens throughout but had no `@import` for `design-tokens.css` or `design-themes.css`. The 27 legacy HTML pages that link only markflow.css (not components.css) never pulled the design files in via any other route either. Result: every token resolved to nothing; page background and text colors fell back to browser defaults on those pages despite the v0.37.1 refactor. Fix: prepended `@import "./css/design-tokens.css"` and `@import "./css/design-themes.css"` to markflow.css (Phase 0, commit `8101001`). |
| BUG-030 | shipped-v0.38.0 | medium | Font picker silently no-op'd on all new-UX components — 28 components.css sites bound to `var(--mf-font-sans)` (hardcoded fallback) instead of `var(--mf-font-family)` (picker-bound token) | `design-tokens.css` defines `--mf-font-sans` as a static string (e.g., `system-ui, sans-serif`) that is never overridden. `design-themes.css` overrides `--mf-font-family` for each `[data-font="X"]` choice. `components.css` referenced `--mf-font-sans` at 28 selectors, so the font picker had no effect on new-UX components. Fix: rebound all 28 occurrences to `var(--mf-font-family)` (Phase 2, commit `fe5e803`). |
| BUG-031 | shipped-v0.38.0 | medium | Invisible card boundaries on low-contrast themes — `.card` in markflow.css used `var(--mf-shadow-press)` (pressed/interactive-state shadow) instead of `var(--mf-shadow-card)` (per-theme elevation shadow) | `--mf-shadow-press` is defined as `0 1px 3px rgba(0,0,0,0.08)` — a nearly imperceptible depth cue intended for pressed button states, not card elevation. On low-contrast themes (spring, summer, fall, winter and dark variants) where surface and background colors are close, this rendered card boundaries invisible. `--mf-shadow-card` provides the intended per-theme elevation shadow. Fix: single-token swap in `.card` rule (commit `01fc0cf`). |
| BUG-032 | shipped-v0.38.0 | high | Inline-style token rot on 19 legacy HTML pages — inline `<style>` blocks and JS `style="..."` attributes still referenced pre-v0.37.0 token names deleted by v0.37.1 | v0.37.1 deleted markflow.css's `:root` block, removing all the old short-name tokens (`--surface`, `--border`, `--text-muted`, `--accent`, `--ok`, `--error`, `--warn`, `--radius`, `--shadow`, etc.). But 19 legacy HTML pages had inline `<style>` blocks AND JS code that dynamically writes `style="color: var(--ok)"` etc. into the DOM — both reference live CSS custom properties. Neither was updated in v0.37.1. Result: ~640 inline usages resolved to nothing, causing invisible UI on resources, flagged, search, viewer, job-detail, pipeline-files, and most other original-UX pages. Fix: applied a 25-rule token-name mapping to both `<style>` and `<script>` blocks across all 19 pages (commit `617c237`). |

### v0.37.1 — v0.37.0 theme system didn't reach legacy original-UX pages

The v0.37.0 Display Preferences feature was operator-visible on the new-UX
pages but **silently no-op'd on every page that loads `static/markflow.css`**
(26 legacy HTML pages including index, resources, admin, bulk, storage, help).
Four distinct sub-bugs traced to the legacy stylesheet never being plumbed
into the v0.37.0 token system — its own parallel `--surface`/`--text`/etc.
custom-prop block + `@media (prefers-color-scheme: dark)` overrides bypassed
`[data-theme]` entirely. Resolved by a 19-commit refactor on
`refactor/markflow-css-theme-aware`: deleted markflow.css's `:root` block
and all 7 OS-media-query blocks (the main one entirely; the 6 component-
scoped ones rewritten as `html[data-theme="classic-dark"]` selector
prefixes), renamed all 302 `var(--…)` references to `--mf-*` equivalents,
substituted ~50 hardcoded color literals to `var(--mf-…)` calls, and
introduced 6 new tokens. Plus inline fixes from visual checkpoints (font
list cleanup, Display Prefs drawer button-wrap at X-Large, h1/h2/h3 +
section titles + drop-zone CTA promoted to accent color).

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-025 | shipped-v0.37.1 | high | Display Preferences drawer was a no-op on every legacy original-UX page | Drawer threw `ReferenceError: MFPrefs is not defined` at `MFPrefs.get('theme')` inside `MFDisplayPrefsDrawer.open()` because `app.js`'s `_loadAvatarMenu()` chain loaded `avatar.js → avatar-menu.js → display-prefs-drawer.js → avatar-menu-wiring.js` but never `preferences.js`. Drawer silently failed to render; user clicked Display Preferences and nothing happened. The 26 legacy HTML pages that rely on `app.js` for chrome (no static `<script src="…/preferences.js">` in their `<head>`) all hit this. Fix: added `_loadScript('/static/js/preferences.js', …)` at the head of the chain in `app.js` plus `MFPrefs.load()` invocation post-load. Shipped first as commit `bbe3753` (also extracted `MFAvatarMenuWiring` helper for BUG-026). |
| BUG-026 | shipped-v0.37.1 | medium | Avatar menu items unwired on every page (12 of 16 menu IDs went to `console.log` instead of routing) | Each `*-boot.js` (13 files) and `app.js` had its own inline `onSelectItem` handler that handled only `id === 'display'` (open drawer); every other menu ID — Profile, Pinned, Notifications, API keys, Account & auth, Storage, Pipeline, AI providers, Database, Logs, All settings, Help, Shortcuts, Bug report — fell through to `console.log('avatar item:', id)`. Fix: extracted `MFAvatarMenuWiring` helper (`static/js/components/avatar-menu-wiring.js`, 138 lines) with two ID→URL maps (one per UX mode), a coming-soon toast for unwired items, drawer lazy-load, and sign-out flow. All 13 boot files + `app.js` now call `MFAvatarMenuWiring.mount(slot, {…, pageSet})`. Removed ~250 lines of duplicated wiring. Commit `bbe3753`. |
| BUG-027 | shipped-v0.37.1 | high | Theme/font/scale switching had no visible effect on legacy original-UX pages | `static/markflow.css` (1684 lines, 0 `var(--mf-*)` references) had its own parallel CSS-custom-prop system at `:root` (lines 8–29: `--bg`, `--surface`, `--text`, `--accent`, etc.) and overrode 14 of those props in an `@media (prefers-color-scheme: dark) { :root { … } }` block. Six additional `@media (prefers-color-scheme: dark)` blocks scattered through the file (lines 270, 350, 1168, 1231, 1384, 1402) overrode component-scoped colors. None of this responded to `[data-theme="X"]` — and the OS-media-query block actively *fought* the theme system, since on a dark-OS machine it forced dark colors regardless of the user's drawer selection. Fix (Phases 1–8 of the refactor): added 5 new tokens to `design-tokens.css :root`, added classic-dark overrides for 5 tokens to `design-themes.css`, deleted markflow.css's `:root` and main `@media` blocks (lines 7–50), rewrote the 6 remaining `@media` blocks to `html[data-theme="classic-dark"]` selector prefixes, renamed all 302 `var(--name)` references to `var(--mf-name)`, and substituted ~50 remaining hardcoded literals to `var(--mf-…)` calls. Final state: 0 `@media (prefers-color-scheme)` blocks, 0 non-`mf-` var refs. |
| BUG-028 | shipped-v0.37.1 | low | X-Large text size broke Display Preferences drawer button layout | `.mf-disp-drawer__scale-row` used `display: grid; grid-template-columns: repeat(4, 1fr)` — a fixed four-column row. At X-Large scale (text-scale 1.36), the four button labels overflowed their column widths and visually broke the drawer. Fix: switched to `grid-template-columns: repeat(auto-fit, minmax(80px, 1fr))` so the buttons reflow into 2×2 (or whatever fits) when their content grows. Single-line CSS change in `components.css`. Commit `8ef45b9`. |



The post-v0.34.8 verification confirmed BUG-018's true root cause:
the abort safeguard *was* firing in memory, but the DB write that
makes the cancellation visible to operators happens only after
`asyncio.gather(*workers)` returns. A single stuck worker (the
v0.34.7 case: one stalled Whisper transcription on slow CPU)
prevents `gather` from returning, so the abort never propagates to
`bulk_jobs.cancellation_reason` even though the in-memory state is
correct. Symptom: `bulk_jobs.cancellation_reason=None` despite 31
consecutive failures with `error_rate=1.0`.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-018 | shipped-v0.34.9 | medium | Bulk-worker `error_rate_abort` decision was invisible to the DB until ALL workers exited — a single stuck worker stranded the cancellation indefinitely | `core/bulk_worker.py:713` correctly fires when `should_abort()` returns True (sets `_cancel_reason` in-memory, `_cancel_event.set()`, `_pause_event.set()`, then `continue` to drain queue). But the DB persistence of `cancellation_reason` lives at line 591, AFTER `await asyncio.gather(*workers)`. If any worker is blocked inside `_process_convertible` (long-running Whisper transcribe, frozen CIFS read, etc.), gather never returns and the cancellation is invisible. The v0.34.4 startup orphan reaper would eventually clean up on next container restart, but operators reading the live UI saw a job stuck in `running` with no abort signal. Fix: persist `status='cancelled' + cancellation_reason` immediately at the abort site via `update_bulk_job_status()`, guarded by a one-shot `_abort_persisted` flag so the per-worker re-observation doesn't keep re-writing. The post-gather write at line 591 still runs when gather *does* eventually return (idempotent overwrite + adds `completed_at`). Bonus: the per-worker log+event spam after abort fires (`bulk_worker_error_rate_abort` once per worker per pull) is also collapsed to one fire per job by the same one-shot guard. See `docs/version-history.md` v0.34.9 entry for the diagnosis chain. |

### v0.34.8 — Whisper asyncio-lock per-loop + macOS resource-fork skip

Post-v0.34.7 verification surfaced two more conversion blockers in
the bulk worker. With BUG-014 (write guard) and BUG-015 (Chartsheet)
fixed, every media file (`.mp4`/`.mov`/`.mp3`) failed instantly with
`<asyncio.locks.Lock ...> is bound to a different event loop`,
freezing the worker pool's heartbeat and producing 31 consecutive
failures with zero successful conversions before the watcher
diagnosed it.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-016 | shipped-v0.34.8 | critical | `core/whisper_transcriber.py` module-level `asyncio.Lock()` strands every Whisper call after the first (single-loop bind) | The format handlers (`formats/media_handler.py:208/211`, `formats/audio_handler.py:148/151`) call `asyncio.run(_convert())` inside a thread-pool worker so each media-file conversion runs on its own short-lived event loop. The module-level `_asyncio_lock = asyncio.Lock()` at `core/whisper_transcriber.py:43` bound to the FIRST such loop and rejected every subsequent file with `is bound to a different event loop`. Symptom: workers reported 8× immediate Whisper failures inside the first 30s of conversion phase (one per worker thread that hit a media file), the bulk_worker recorded the failures into `bulk_files.error_msg`, and the heartbeat froze the moment the lock-holder was stuck on the slow CPU transcribe call. Fix: replace the module-level lock with `_get_asyncio_lock()` — a per-loop dict keyed by `id(running_loop)` and guarded by a `threading.Lock`. Each format-handler thread still serializes Whisper inference via the existing `_thread_lock` (threading.Lock), so cross-loop GPU/CPU correctness is preserved; the asyncio.Lock just serializes coroutines within each loop. See `docs/version-history.md` v0.34.8 entry for the diagnosis chain. |
| BUG-017 | shipped-v0.34.8 | low | macOS resource-fork sidecar files (`._FILENAME.pdf`) leaked into the conversion pipeline and failed every PDF handler call with `Cannot open PDF: No /Root object!` | macOS writes a resource-fork sidecar named `._<original>` whenever the user copies a file to a non-HFS+ volume (SMB/CIFS share = the live VM's source mount). The bytes are AppleDouble-framed metadata, NOT the file format their extension claims. `core/bulk_scanner.py:_JUNK_BASENAME_PREFIXES_LOWER` already covered the `.appledouble` directory but missed the per-file `._` sibling. Fix: add `"._"` to the prefix list. Junk-filename check runs at scanner level so they never reach a handler. |

### v0.34.7 — Auto-conversion unwedged: write guard + Excel chartsheet

Two distinct conversion-blocking bugs found via post-v0.34.6 log
audit. Both had been silently failing every auto-converted file
since at least 2026-04-29 16:33, tripping the bulk-worker 20-error
abort threshold inside the first 20 attempts of every cycle (so
zero successful conversions across at least 5 consecutive auto-runs).
Combined effect: the auto-converter looked unblocked at the
scheduling layer (v0.34.3 + v0.34.4 fixes held), but no files were
actually being converted.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-014 | shipped-v0.34.7 | critical | `is_write_allowed()` returns False for every path when the Storage Manager DB pref is unset, blocking the entire bulk pipeline | `core/storage_manager.py:142` consulted only the `_cached_output_path` sentinel populated from the `storage_output_path` DB preference. On any deploy where an operator hadn't visited the Storage page (or where the DB had been reset since the last visit), the cache stayed `None`, the early-return at line 150 fired, and every write was denied — including writes that were demonstrably inside `BULK_OUTPUT_PATH`. The bulk_files table accumulated dozens of `write denied — outside output dir: /mnt/output-repo/...` rows against paths clearly under `/mnt/output-repo`. Fix: route the guard through `core.storage_paths.resolve_output_root_or_raise()`, which uses the v0.34.1 priority chain (Storage Manager > BULK_OUTPUT_PATH > OUTPUT_DIR) and refuses the legacy `output/` fallback. The v0.25.0 "absent configuration → deny everything" intent is preserved (the resolver raises if no source is configured, and the guard treats that as deny). Hardened `tests/test_storage_manager.py:test_write_denied_when_no_output_configured` to clear BULK_OUTPUT_PATH/OUTPUT_DIR via monkeypatch so the "absent configuration" branch is actually exercised even when a dev shell exports those vars. See `docs/version-history.md` v0.34.7 entry for the full diagnosis. |
| BUG-015 | shipped-v0.34.7 | high | `formats/xlsx_handler.py` crashes with `AttributeError: 'Chartsheet' object has no attribute 'merged_cells'` on .xlsx files containing chart-only sheets | openpyxl returns `Chartsheet` objects for sheets that hold only an embedded chart (no cell grid). Both the ingest loop and `_extract_styles_impl` call `ws.merged_cells.ranges` unconditionally, which AttributeErrors on chartsheets. The error propagates out of the handler and fails the whole file. 11 distinct `.xlsx` files in production hit this. Fix: duck-type guard `hasattr(ws_data, "merged_cells")` at the top of both loops; skip Chartsheets after logging `xlsx_chartsheet_skipped` for operator visibility. Chartsheets carry no Markdown-extractable content; skipping is the correct semantic. |

### v0.34.6 — Resources page disk card double-count

Resources page **Disk** card showed inflated MarkFlow disk usage
(roughly 2× actual on hosts where the conv-output walk completed).
Both the time-series snapshot writer (`core/metrics_collector.py`) and
the admin breakdown endpoint (`api/routes/admin.py`) summed the
"Conversion Output" component into the total. Post-v0.34.1 that
component walks the same root as Output Repository + Trash, so the
sum was over by the entire output-share size whenever the conv walk
returned non-zero. The bug was masked on the live VM until now
because the conv walk happened to return 0 in the most recent
snapshot; with the conv walk succeeding, the card would have jumped
from ~2 TB to ~4 TB without anything actually changing on disk.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-013 | shipped-v0.34.6 | medium | Resources page Disk card and admin disk-usage breakdown double-counted the output share post-v0.34.1 | Post-v0.34.1 `core/storage_paths.get_output_root()` returns one root for both bulk and single-file conversion. The "Output Repository" walk (excl `.trash`), the "Trash" walk, and the "Conversion Output" walk together covered the same files twice. `core/metrics_collector.py:_collect_disk_snapshot_impl` summed `repo_bytes + trash_bytes + conv_bytes + db_bytes + logs_bytes + meili_bytes` into `total_bytes` (persisted to `disk_metrics.total_bytes` and shown by `/api/resources/summary` as `disk.current_total_human`). `api/routes/admin.py:_compute_disk_usage` summed `item["bytes"] for item in breakdown` over the same redundant rows. Fix: drop `conv_bytes` from the metrics-collector sum; tag the admin breakdown's Conversion Output row with `redundant_in_total=True` and skip such rows in the sum. The "Conversion Output" row is retained in the admin UI for operator clarity (different workflow label) but no longer contributes to the displayed total. See `docs/version-history.md` v0.34.6 entry for the full narrative. |

### v0.34.4 — Orphan reaper extended to `auto_conversion_runs`

Companion fix to v0.34.3. Discovered while verifying the BUG-011 fix:
the auto-converter was refusing to start new runs because the startup
orphan-cleanup function handled `bulk_jobs` and `scan_runs` but missed
`auto_conversion_runs` entirely. **38 stale `status='running'` rows
had accumulated since 2026-04-07** — every failed-pre-flight from
BUG-011 left an unkillable orphan, and the auto-converter's
"don't start if one is already running" gate then refused all
subsequent cycles. Compound deadlock.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-012 | shipped-v0.34.4 | critical | Stale `auto_conversion_runs.status='running'` rows wedge the auto-converter forever | `core/db/schema.py:cleanup_orphaned_jobs()` handled `bulk_jobs` and `scan_runs` at startup but had no UPDATE for `auto_conversion_runs`. Any failure path that didn't write `completed_at` (failed pre-flight, container restart mid-run) left a permanent orphan. Auto-converter's "active run already exists" gate then silently skipped every subsequent cycle. Fix: third UPDATE in `cleanup_orphaned_jobs()` that marks `status='running' AND completed_at IS NULL` rows as `status='failed'`. Defensive table-existence check for older / partial-schema fixtures. Two new tests in `tests/test_bugfix_patch.py:TestOrphanCleanup`. See `docs/version-history.md` v0.34.4 entry for the compound-deadlock narrative + lessons (any table with status+completed_at gating downstream work MUST have startup orphan reaping). |

### v0.34.3 — Auto-conversion unblocked: disk-space pre-check multiplier

Hardcoded `× 3` input-size buffer in the bulk-worker pre-flight check
silently rejected every auto-conversion job once the source share grew
past ~33% of free output space. Symptom on the affected machine: 92,257
files stuck in `bulk_files.status='pending'`, `bulk_jobs` rows recording
`status='failed'` with the disk-space error, and a stale Meilisearch
count from a prior DB lifetime giving operators no visible signal that
conversion had stopped.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-011 | shipped-v0.34.3 | critical | Bulk-worker pre-flight `× 3` disk-space multiplier silently fails every auto-conversion on large shares | `core/bulk_worker.py:21` had `_DISK_SPACE_REQUIRED_MULTIPLIER = 3` (v0.23.6 M2) — assumed output ≈ input × 3 buffer. Markdown output is actually well under 50% of input. Fix: replaced constant with `_get_disk_space_multiplier()` helper reading `DISK_SPACE_MULTIPLIER` env var per-call (default `0.5`). 10 new tests in `tests/test_disk_space_multiplier.py`. Operator-facing error message now ends with "tune via DISK_SPACE_MULTIPLIER env var". See `docs/version-history.md` v0.34.3 entry for the full narrative + why no alarm fired (telemetry gap tracked in UX overhaul spec). |

### v0.34.2 — Audit follow-up: 5 missed OUTPUT_BASE consumers

Hotfix following v0.34.1's blast-radius sweep. v0.34.1's audit grep
anchored on `OUTPUT_BASE` and missed five sites that read
`BULK_OUTPUT_PATH` / `OUTPUT_DIR` directly or imported the frozen
`OUTPUT_REPO_ROOT` alias.

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-010 | shipped-v0.34.2 | high | Five OUTPUT_BASE consumers missed by v0.34.1 still read stale env / frozen alias | (1) `core/lifecycle_manager.py:53` — dropped frozen `OUTPUT_REPO_ROOT` alias entirely (only importer migrated in same release); (2) `core/db_maintenance.py:167,175` — dangling-trash health check now uses `get_output_root()` per-call; (3) `api/routes/admin.py:674,700` — disk-usage admin breakdown via resolver; (4) `core/metrics_collector.py:217,227` — 6h disk-snapshot via resolver, stops poisoning time-series; (5) `core/lifecycle_scanner.py:332,1151` — synthetic + auto-pipeline `create_bulk_job()` records resolved path. See `docs/version-history.md` v0.34.2 entry for full narrative. |

### v0.34.1 — Convert page write-guard + folder picker + 5 silent-failure consumers

Plan: [`docs/superpowers/plans/2026-04-28-convert-page-write-guard-fix.md`](superpowers/plans/2026-04-28-convert-page-write-guard-fix.md)
(executed Option 2: expanded scope — all 6 output-path consumers
unified behind `core.storage_paths.get_output_root()`).

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-001 | shipped-v0.34.1 | high | Folder picker leaves drives sidebar empty when initial navigation fails | `static/js/folder-picker.js`: hoisted `_loadDrivesSidebar()`; called once at top of `open()` BEFORE navigate. Drives sidebar always populates from a known-good `/host` fetch even when the requested startPath fails. |
| BUG-002 | shipped-v0.34.1 | high | Folder picker output-mode doesn't remap out-of-allowed initialPath | New `_isBrowsablePath(p)` allow-list helper mirrors `api/routes/browse.py:ALLOWED_BROWSE_ROOTS`. `open()` remaps non-browsable paths to `/mnt/output-repo` (output mode) or `/host` (other modes) with a `console.info` audit hint. |
| BUG-003 | shipped-v0.34.1 | high | `/api/convert` accepts `output_dir` Form param but ignores it | `api/routes/convert.py`: validate `output_dir` against `is_write_allowed()` (422 with structured error if rejected), thread to `_run_batch_and_cleanup` → `convert_batch(output_dir=...)`. New `convert.output_dir_resolved` / `convert.output_dir_rejected` log events. |
| BUG-004 | shipped-v0.34.1 | critical | `OUTPUT_BASE = /app/output` violates v0.25.0+ write guard | New `core/storage_paths.py` resolver. `ConversionOrchestrator` re-resolves on every batch (Storage Manager > BULK_OUTPUT_PATH > OUTPUT_DIR > fallback). Fix wins over BUG-005..009 once resolver is the single source of truth. |
| BUG-005 | shipped-v0.34.1 | high | Download Batch button silently 404s when bulk wrote elsewhere | `api/routes/batch.py:_batch_dir` now calls `get_output_root()` per-request. |
| BUG-006 | shipped-v0.34.1 | high | History download links silently 404s | `api/routes/history.py` same. |
| BUG-007 | shipped-v0.34.1 | critical | Lifecycle scanner walks wrong tree → no soft-delete tracking | `core/lifecycle_manager.py:OUTPUT_REPO_ROOT` replaced with `_output_root()` getter that consults the resolver. All 4 `get_trash_path` call sites updated. |
| BUG-008 | shipped-v0.34.1 | medium | MCP returns wrong paths to AI clients | `mcp_server/tools.py:OUTPUT_DIR` replaced with `_output_dir()` getter; 4 call sites updated. |
| BUG-009 | shipped-v0.34.1 | low | `/ocr-images` static mount serves from wrong dir | `main.py:507` uses `get_output_root_str()`. Note: StaticFiles binds at app-startup (before lifespan), so Storage Manager runtime changes still require a container restart for `/ocr-images` (documented in gotchas). |

(No closed rows from before v0.34.1 — this section accumulates as
bugs ship.)

---

## How to add a new bug

1. Pick the next free ID (next `BUG-NNN`).
2. Add a row to the **Open / Planned** table for the relevant release
   group (or create a new group if the bug doesn't belong to an
   existing planned release).
3. Set `Status` to `open` (no plan yet) or `planned (vX.Y.Z)` (plan
   exists / scheduled).
4. Severity per the table above.
5. **Summary**: one line, no jargon. What's broken from the operator's
   point of view.
6. **Details**: file + line where relevant, root cause in one sentence,
   link to plan if one exists. Don't duplicate the plan body — link
   to it.

When the bug ships:

1. Move the row from **Open / Planned** to **Shipped (history)**.
2. Change `Status` to `shipped-vX.Y.Z`.
3. Verify `version-history.md` has the corresponding release entry.
4. If the fix exposed a class of bug worth preventing, add a `gotchas.md`
   row in the relevant subsystem section.
