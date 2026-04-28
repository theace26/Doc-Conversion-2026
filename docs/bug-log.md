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

### v0.33.4 — Convert page write-guard + folder picker (planned)

Plan: [`docs/superpowers/plans/2026-04-28-convert-page-write-guard-fix.md`](superpowers/plans/2026-04-28-convert-page-write-guard-fix.md)

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| BUG-001 | planned (v0.33.4) | high | Folder picker leaves drives sidebar empty when initial navigation fails | `static/js/folder-picker.js:_renderDrives` only fires from `_render()` on `/api/browse` 200; on a 4xx the sidebar stays blank and the operator can't navigate anywhere. Latent across all 5 picker call sites; today only Convert page hits it. Plan §"Fix A". |
| BUG-002 | planned (v0.33.4) | high | Folder picker output-mode doesn't remap out-of-allowed initialPath | Picker's `open()` only remaps to `/mnt/output-repo` when `initialPath` is empty or exactly `'/host'`. Convert page passes `'/app/output'` which the picker faithfully tries to navigate to, gets 403, hits BUG-001. Plan §"Fix B". |
| BUG-003 | planned (v0.33.4) | high | `/api/convert` accepts `output_dir` Form param but ignores it | `api/routes/convert.py:40` declares `output_dir` and stores it as `last_save_directory` preference but never passes it to the orchestrator. User-picked destination silently discarded. Plan §"Fix C". |
| BUG-004 | planned (v0.33.4) | critical | `OUTPUT_BASE = /app/output` violates v0.25.0+ write guard | `core/converter.py:65` defaults to relative `output` → `/app/output` in container, outside Storage Manager allowed roots. Single-file convert always rejected unless operator manually set `OUTPUT_DIR=/mnt/output-repo` in env. Umbrella for BUG-005..009 (silent failure consumers). Plan §"Fix D". |
| BUG-005 | planned (v0.33.4) | high | Download Batch button silently 404s when bulk wrote elsewhere | Silent consumer of BUG-004. `api/routes/batch.py:31` looks in `OUTPUT_BASE / batch_id`; if bulk pipeline (which uses Storage Manager since v0.31.6) wrote to `/mnt/output-repo` instead, the download endpoint silently 404s. |
| BUG-006 | planned (v0.33.4) | high | History download links silently 404s | Silent consumer of BUG-004. `api/routes/history.py:269` same pattern as BUG-005. |
| BUG-007 | planned (v0.33.4) | critical | Lifecycle scanner walks wrong tree → no soft-delete tracking | Silent consumer of BUG-004. `core/lifecycle_manager.py:40` (`OUTPUT_REPO_ROOT`) walks the env-resolved path; if writes go to a Storage-Manager-resolved different path, lifecycle never sees them → no soft-delete entries → files never enter trash after source removal. **Data-management invariant violated.** |
| BUG-008 | planned (v0.33.4) | medium | MCP returns wrong paths to AI clients | Silent consumer of BUG-004. `mcp_server/tools.py:15` resolves paths via `OUTPUT_DIR` env. AI clients (Claude, etc.) get path drift when Storage Manager and env disagree. |
| BUG-009 | planned (v0.33.4) | low | `/ocr-images` static mount serves from wrong dir | Silent consumer of BUG-004. `main.py:507` mount points at `OUTPUT_DIR` env path. OCR debug thumbnails on Review page broken when actual OCR output goes elsewhere. |

**Note on BUG-005..009**: today these "appear fine" only because most
deployments set `OUTPUT_DIR=/mnt/output-repo` in env, which keeps
`OUTPUT_BASE` and the Storage Manager output path in sync. Drop the
env var (the v0.25.0+ design intent) and 5 silent failures appear.
v0.33.4 plan recommends fixing all 6 consumers in one cut via a
shared `core.storage_paths.get_output_root()` resolver rather than
shipping 5 follow-up patches.

### Security audit findings (long-running)

| ID | Status | Sev | Summary | Details |
|----|--------|-----|---------|---------|
| SEC-* | open (54 of 62) | mixed | Outstanding security-audit findings | 8 of 62 addressed in v0.29.0. Remaining 54: 10 critical + 18 high + 22 medium + 12 low/info — see `docs/security-audit.md` for the full enumerated list with severity, files, and remediation guidance. **Pre-prod blocker** until critical + high tier is closed. |

---

## Shipped (history)

(No closed rows yet — this section accumulates as bugs ship. New
closed entries go at the top of this section with their `shipped-vX.Y.Z`
status field.)

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
