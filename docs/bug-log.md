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

(BUG-001 through BUG-015 closed in v0.34.1 / v0.34.2 / v0.34.3 / v0.34.4 / v0.34.6 / v0.34.7 — see Shipped section.)

### Security audit findings (long-running)

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| SEC-* | open (54 of 62) | mixed | Outstanding security-audit findings | 8 of 62 addressed in v0.29.0. Remaining 54: 10 critical + 18 high + 22 medium + 12 low/info — see `docs/security-audit.md` for the full enumerated list with severity, files, and remediation guidance. **Pre-prod blocker** until critical + high tier is closed. |

---

## Shipped (history)

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
