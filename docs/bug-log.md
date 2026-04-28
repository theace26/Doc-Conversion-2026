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

(BUG-001 through BUG-010 closed in v0.34.1 / v0.34.2 — see Shipped section.)

### Security audit findings (long-running)

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| SEC-* | open (54 of 62) | mixed | Outstanding security-audit findings | 8 of 62 addressed in v0.29.0. Remaining 54: 10 critical + 18 high + 22 medium + 12 low/info — see `docs/security-audit.md` for the full enumerated list with severity, files, and remediation guidance. **Pre-prod blocker** until critical + high tier is closed. |

---

## Shipped (history)

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
