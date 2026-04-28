# Convert page: write-guard rejection + folder picker empty sidebar

**Status:** Plan — not implemented.
**Author:** v0.33.3 follow-up bug investigation, 2026-04-28.
**Triggers a release:** Yes — single bug-fix cut: `v0.33.4`. All four
fixes ship together because they're tangled into one operator-
visible failure.

---

## Background

Operator hit two visible failures from a single click on the Convert
page:

1. **Bulk batch rejection.** A PDF dropped on Convert produced
   `write denied — outside output dir: output/20260428_050139_99…` —
   the v0.25.0 write guard rejected the destination.
2. **Folder picker is broken.** Clicking **Browse** next to the
   Output Directory field opens a modal with the title and the
   restricted-paths hint visible, but **no drives sidebar, no
   breadcrumb, no folder list**. The operator can't navigate
   anywhere — including to a path the write guard would accept.

Investigation traced both back to four distinct root causes that
combine into one user-visible failure.

---

## Root causes

### Bug A — Picker never populates the drives sidebar on failure

`static/js/folder-picker.js:_renderDrives` is **only called from
`_render()`**, which only fires when `/api/browse` returns 200.
On a 4xx, the picker calls `_showError(detail)`, which writes to
`#fp-entries` only — `#fp-drives` stays empty.

**Effect:** if the initial navigation fails for any reason
(restricted path, missing dir, network blip), the operator is
stranded — they see the error message in the entries pane but no
drives sidebar to navigate elsewhere.

### Bug B — Output mode picker doesn't remap an out-of-allowed initialPath

`static/js/folder-picker.js:open` only remaps `initialPath` to
`/mnt/output-repo` when initialPath is **empty** or **exactly
`'/host'`**. When the convert page passes `initialPath='/app/output'`
(the broken default value sitting in the field), the picker
faithfully tries to navigate there, gets a 403 from `/api/browse`
("Browsing is restricted to mounted drives (/host/) and the output
repo (/mnt/output-repo)"), hits Bug A, and the modal renders empty.

**Effect:** Bug B is the trigger that exposes Bug A on the Convert
page specifically. Storage page doesn't hit this because it always
opens with a sane initialPath.

### Bug C — `/api/convert` accepts `output_dir` but ignores it

`api/routes/convert.py:convert_files` declares
`output_dir: str = Form(default="")` and stores it as the
`last_save_directory` preference (line 92-93)… and then **never
passes it to the orchestrator**. `convert_batch(...)` has no
`output_dir` parameter, so the user-selected destination is silently
discarded. Output always lands at `OUTPUT_BASE / <batch_id>`.

**Effect:** even if the operator manually types a valid path into
the Output Directory field (or fixes the picker via Bug A+B), the
backend ignores the value.

### Bug D — `OUTPUT_BASE` defaults to `/app/output`, which violates the v0.25.0+ write guard

`core/converter.py:65`: `OUTPUT_BASE = Path(os.getenv("OUTPUT_DIR",
"output"))`. Without an `OUTPUT_DIR` env override the relative
`output` resolves to `/app/output` inside the container — which is
outside both `/mnt/output-repo` and `/host/rw`. Every write attempt
through `is_write_allowed(...)` fails.

**Effect:** Convert page is unusable on any deployment that didn't
manually set `OUTPUT_DIR=/mnt/output-repo` in the env. v0.25.0
introduced the Universal Storage Manager but the Convert path was
never updated to consult `core.storage_manager.get_output_path()`
the way the v0.31.6 `_convert_one_pending_file` does.

---

## Best practices baked in

| Practice | How |
|---|---|
| **Trust the Storage Manager as source of truth** | Convert page resolves its destination via `core.storage_manager.get_output_path()` like every other writer added since v0.25.0. The OUTPUT_DIR env var stays as a fallback only. |
| **Defensive degradation in the picker** | Drives sidebar populates from a separate, always-runs fetch. An initial-navigation failure leaves drives clickable so the operator can recover. |
| **Honor what the user picked** | If `output_dir` is in the POST body and is allowed, use it. Don't silently fall back. If it's NOT allowed, return a clear 422 explaining why instead of writing somewhere else. |
| **Operator transparency** | When the picker remaps an out-of-allowed initialPath, log a console hint. When `/api/convert` rejects an out-of-allowed `output_dir`, the error message names the disallowed path AND the allowed roots. |
| **No silent path drift** | Never compute an output path the user can't see. The operator's typed/picked path is either honored exactly or rejected with an explanation. |
| **Backwards compatible** | Existing `OUTPUT_DIR` env continues to work; existing Convert flows on already-correctly-configured deployments aren't affected. |

---

## Fix plan — single release v0.33.4

All four fixes ship in one cut because they're entangled: fixing
just (A) leaves the picker showing drives but unable to validate
selections; fixing just (D) leaves the picker still broken so the
operator can't pick. The four changes are independently reviewable
inside the single PR.

### Fix A — Picker populates drives unconditionally

`static/js/folder-picker.js`:

- Hoist a separate `_loadDrives()` method that fetches a tiny
  drives-only payload OR derives drives from a single `/api/browse`
  call to a known-good path (`/host` is always allowed and
  exists in the container).
- Call `_loadDrives()` once at the top of `open()`, before
  `_navigate(startPath)`.
- `_renderDrives()` becomes idempotent — safe to call multiple
  times. The current `_render()` continues to call it on success
  (cheap; no-op if data unchanged).
- `_showError()` no longer leaves the sidebar blank — drives are
  already there from the early load.

Implementation choice: rather than add a new endpoint, call
`/api/browse?path=/host` first to get the `drives` array, render
it, **then** navigate to the requested path. If the user-requested
path fails, the drives are still present.

### Fix B — Output-mode picker falls back when initialPath is not browsable

`static/js/folder-picker.js:open`:

```js
// Old:
if (this.mode === 'output' && (!startPath || startPath === '/host')) {
  startPath = '/mnt/output-repo';
}

// New:
if (this.mode === 'output' && !this._isBrowsablePath(startPath)) {
  console.info('FolderPicker: initialPath',
               startPath, 'is not under an allowed browse root; remapping to /mnt/output-repo');
  startPath = '/mnt/output-repo';
}
```

`_isBrowsablePath(p)` returns true if `p` starts with `/host/` or
equals `/host` or starts with `/mnt/output-repo` or equals
`/mnt/output-repo`. Same allow-list as `api/routes/browse.py:ALLOWED_BROWSE_ROOTS`.

This means the broken `/app/output` default in the Convert page's
field no longer strands the user — the picker auto-fallbacks to
the output repo.

### Fix C — `/api/convert` propagates `output_dir` to the orchestrator

`api/routes/convert.py`:

- Validate `output_dir` early (before file uploads land). If
  non-empty AND not under an allowed root, return 422 with
  `{"detail": {"error": "output_dir_not_allowed", "message":
  "<path> is outside the allowed roots (/mnt/output-repo or
  /host/rw/...). Pick a folder under one of these via Browse."}}`
- If `output_dir` is empty, resolve via
  `core.storage_manager.get_output_path()` (the new default).
- Pass the resolved path to `_run_batch_and_cleanup` and through
  to `convert_batch(... output_dir=resolved_output)`.

`core/converter.py`:

- `convert_batch()` gains an optional `output_dir: Path | None`
  parameter (default `None` = use `self.output_base`). When
  passed, it's used as the batch destination instead of
  `self.output_base`.
- `_convert_one(...)` already receives the batch dir via closure;
  thread the override through.

### Fix D — Default destination resolves through Storage Manager

`core/converter.py`:

- `OUTPUT_BASE` constant stays for backwards compat as the fallback
  when both Storage Manager AND the env var are unset.
- New helper `_resolve_default_output_base() -> Path`:
  ```python
  def _resolve_default_output_base() -> Path:
      """Resolve the default output base, preferring the Storage Manager
      configured path, then OUTPUT_DIR env, then 'output' relative."""
      try:
          from core.storage_manager import get_output_path
          sm_path = get_output_path()
          if sm_path:
              return Path(sm_path)
      except Exception:
          pass
      return Path(os.getenv("OUTPUT_DIR", "output"))
  ```
- `ConversionOrchestrator.__init__` calls
  `_resolve_default_output_base()` at instance creation but ALSO
  re-resolves on each `convert_batch()` call so a Storage page
  reconfiguration takes effect without restart.

This mirrors v0.31.6's `_convert_one_pending_file` pattern exactly.

### Frontend: Convert page Output Directory default

`static/index.html`:

- The Output Directory `<input>` default value is rendered server-
  side from a preference. Today it shows `/app/output` because
  `last_save_directory` was never set (and the placeholder fell
  through to OUTPUT_DIR).
- Change: on Convert page load, fetch the Storage Manager output
  path via `/api/storage/output-path` (or wherever it's exposed)
  and use it as the initial value. If that's also unset, leave the
  field empty with a placeholder "Click Browse or pick a folder
  under /mnt/output-repo".
- Pass the field's current value as `initialPath` to the picker
  (Fix B handles the fallback when the value is invalid).

### Tests

- `tests/test_folder_picker_drives.py` (new, JS-doc test or a
  simple Python integration test): not feasible without a JS test
  harness — defer JS-side test to a manual smoke. Backend test:
- `tests/test_convert_output_dir.py` (new):
  - `test_convert_rejects_out_of_allowed_output_dir`: POST with
    `output_dir=/app/output` → 422 with structured error.
  - `test_convert_uses_storage_manager_default_when_unset`: with
    Storage Manager configured to `/mnt/output-repo`, POST with
    no output_dir → batch lands under `/mnt/output-repo`.
  - `test_convert_honors_user_picked_output_dir`: POST with
    `output_dir=/mnt/output-repo/my-stuff` → batch lands there.
- Existing `test_storage_api.py` regression — verify
  `is_write_allowed` semantics unchanged.

### Manual smoke checklist

1. Open Convert page → field shows `/mnt/output-repo` (not
   `/app/output`).
2. Click Browse → picker opens with **drives sidebar visible**
   (Output Repo + /host/c + /host/d shortcuts) plus the
   `/mnt/output-repo` contents in the main pane.
3. Pick a subdir, click Select → field updates to that path.
4. Drop a PDF → conversion succeeds; output lands under the
   picked path.
5. Repeat with `OUTPUT_DIR` env unset, Storage Manager unset →
   convert returns 422 with the "no output path configured" error.
6. Backwards-compat: a deployment with `OUTPUT_DIR=/mnt/output-repo`
   set in env continues to work without Storage Manager.

---

## Files to modify

| File | Why |
|------|-----|
| `static/js/folder-picker.js` | Fixes A + B (always-load drives, output-mode fallback) |
| `static/index.html` | Convert page: seed Output Directory from Storage Manager |
| `api/routes/convert.py` | Fix C (validate + propagate `output_dir`) |
| `core/converter.py` | Fix D (`_resolve_default_output_base` + `convert_batch(output_dir=...)`) |
| `tests/test_convert_output_dir.py` | New backend tests |
| `core/version.py` | Bump to 0.33.4 |
| `CLAUDE.md`, `docs/version-history.md`, `docs/help/whats-new.md`, `docs/gotchas.md` | Doc updates |

Estimated: ~3 hours including manual smoke + container rebuild +
docs.

---

## Cross-cutting concerns

### Edge cases

| Edge case | Handling |
|---|---|
| Storage Manager configured but the path doesn't exist | Convert returns 422 with the message "Storage output path /mnt/output-repo doesn't exist on disk; check Storage page". Don't auto-create. |
| Operator passes `output_dir` outside allowed roots via API (no UI) | Same 422 with the structured error. External integrators get a clear message. |
| Operator passes `output_dir` at exactly an allowed root (e.g. `/mnt/output-repo`) | Allowed; batch lands at `/mnt/output-repo/<batch_id>/...`. |
| `output_dir` contains `..` traversal | Caught by existing path validation logic. |
| Picker user right-clicks → "Open in new tab" on the Browse button | Out of scope — the button is `<button>` not `<a>`. |
| User has dev mode `DEV_BYPASS_AUTH=true` AND no Storage Manager configured AND OUTPUT_DIR env unset | Convert returns 422; dev gets a clear error to configure Storage. (Today: silently writes to `/app/output` and bulk works fine, single-file silently breaks. After fix: both paths produce the same clear error.) |

### Security

- All four fixes preserve the existing write-guard semantics; none
  loosen any allow-list.
- `/api/convert` validation reuses the same allow-list logic as
  the Storage page so behavior is consistent across surfaces.
- The browse endpoint is unchanged.

### Backwards compatibility

- Deployments with `OUTPUT_DIR=/mnt/output-repo` (or another
  allowed root) in env continue to work — the resolver still falls
  back to env when Storage Manager isn't configured.
- API consumers calling `/api/convert` without `output_dir` get
  Storage-Manager-resolved behavior (an improvement, not a break).
- API consumers calling `/api/convert` with a previously-accepted-
  but-now-rejected `output_dir` start getting 422s. This is a
  behavior change, but: the previous behavior was to silently
  write to a path the user didn't pick, which is worse. Document
  in the version-history.md as a deliberate non-breaking-but-
  behavior-changing fix.

### Rollback story

Single revert restores prior behavior. No migrations, no schema
changes, no env-var contract changes.

### Logged events for the audit trail

| Event | When |
|-------|------|
| `convert.output_dir_resolved` | Every `/api/convert` call. Fields: requested, resolved, source (`user`, `storage_manager`, `env`, `fallback`). |
| `convert.output_dir_rejected` | A user-supplied `output_dir` was rejected. Fields: requested, allowed_roots. |
| `folder_picker.initial_path_remapped` | (Frontend console.info, not server-side log.) Picker auto-fell-back from a non-browsable initialPath. |

All searchable in Log Viewer with `?q=convert.output_dir` /
`?q=folder_picker`.

---

## Open questions

1. Is there an existing API to read the Storage Manager output
   path from the frontend? If so, use it. If not, add a tiny
   `GET /api/storage/output-path` (already provided by
   `/api/storage/config`?) and consume it from the Convert page.
2. Should the Convert page also surface a "currently allowed
   roots" hint near the Output Directory field when the Storage
   Manager is unconfigured? Probably yes — small UX win.
3. Does Bulk Convert have the same Bug C (accepting `output_dir`
   but not propagating it)? Spot-checked: no `output_dir` Form
   params elsewhere in `api/routes/`. ✅ This bug is Convert-only.

---

## Foresight: blast radius beyond the Convert page

Each bug has a different reach. (3) is single-page, (1) and (2)
are latent across all picker callers, and **(4) is the dangerous
one — it silently corrupts every read path that thinks it knows
where bulk-pipeline output lives.**

### Bug A — Picker drives sidebar empty on failure

**Latent across 5 picker call sites** (`storage.html` x2 via
`storage.js`, `index.html` Convert, `locations.html` x3 — auto-
open, location-add, exclusion-add). Today only the Convert page
hits it because every other caller passes a known-good
initialPath (`/host` or a previously-Storage-validated value).
But the bug itself lives in the shared module, so any future
caller that passes an out-of-allowed initialPath hits the same
empty-sidebar dead end. **Fixing once in the shared module fixes
all 5.**

### Bug B — Output-mode picker doesn't remap a bad initialPath

**Affects all output-mode callers**, but the practical hit list
is just two: Convert page (broken now) + Storage page output
picker (could break if its input field ever holds a stale
`/app/output` value, e.g. before the user has saved a Storage
config). Locations page doesn't use output mode. **Fix in the
shared module, both surfaces protected.**

### Bug C — `output_dir` Form param accepted but ignored

**Confirmed isolated to `api/routes/convert.py`.** Grep across
`api/routes/` finds zero other endpoints with the same
`output_dir`-as-Form-param anti-pattern. Bulk endpoints route
through `core/bulk_worker.py` which has its own (correct, since
v0.31.6) Storage-Manager-resolved output handling.

### Bug D — `OUTPUT_BASE` defaults to `/app/output` — **the dangerous one**

**This bug silently misroutes 6 different consumers across the
codebase**, because `OUTPUT_BASE` (and its sibling
`OUTPUT_REPO_ROOT` in `lifecycle_manager.py`) are
module-level constants imported widely:

| Consumer | What it does | What goes wrong |
|---|---|---|
| `api/routes/convert.py` (via `_orchestrator`) | Single-file conversion writes | Write guard rejects (the visible bug) |
| `api/routes/batch.py:31` (`get_batch_output_dir`) | `/api/batch/{batch_id}/download` looks in `OUTPUT_BASE / batch_id` | After Storage-Manager-routed bulk writes elsewhere, the **Download Batch button silently 404s** |
| `api/routes/history.py:269` | History page download links | Same: history page download silently 404s after bulk routes elsewhere |
| `core/lifecycle_manager.py:40` (`OUTPUT_REPO_ROOT`) | Lifecycle scanner walks this tree for soft-delete + trash management | If actual writes go to a different (Storage-Manager-resolved) path, **lifecycle never sees them → no soft-delete tracking → no trash entries → files stay live forever after source removal** |
| `mcp_server/tools.py:15` | MCP tool path resolution for AI clients | MCP returns wrong/missing paths to Claude or other AI consumers |
| `main.py:507` | `/ocr-images` static mount | OCR debug images served from `/app/output` while real OCR-pass output sits elsewhere → broken thumbnails on Review page |

**Why this hasn't visibly broken everything yet**: any deployment
with `OUTPUT_DIR=/mnt/output-repo` set in env "accidentally"
keeps all six in sync. Drop the env var (or rely on Storage
Manager to be the source of truth, which is the v0.25.0+ design
intent) and all six start drifting silently. The Convert page is
just the **first** place this failure becomes loud, because it
runs through `is_write_allowed()`. The other five fail silently —
no error, just wrong behavior.

### Recommendation: expand v0.33.4 scope

Originally I planned to patch just Convert + the picker. But Bug D
is too dangerous to leave half-fixed. Two options:

**Option 1 (narrow, what I planned)**: Fix Convert + picker only.
Leave the 5 silent-failure consumers as a known issue for a
follow-up. Risk: someone clicks "Download Batch" on a freshly-
processed bulk and gets 404; we have to ship v0.33.5 the next day.

**Option 2 (recommended)**: Expand v0.33.4 to also migrate the 5
silent consumers to a single shared helper
`core.storage_paths.get_output_root()` that consults Storage
Manager → BULK_OUTPUT_PATH env → OUTPUT_DIR env → fallback. All
6 consumers (the 5 silent + the 1 visible) use the same resolver.
v0.33.5 then doesn't need to exist.

Going with Option 2 keeps the release coherent: "v0.33.4 — every
output-path consumer now agrees on where output lives" instead of
"v0.33.4 + v0.33.5 — patches drift across the codebase." Adds
~30 minutes to the implementation, no new endpoints, no new
tests beyond what's already planned.

### Other surfaces to verify before shipping (cheap regressions to dodge)

- **Search index**: does Meilisearch indexing read from `OUTPUT_BASE`?
  If yes, post-fix indexing might miss files that landed under
  the new resolved path. (Likely no — search indexes from the
  bulk-files DB rows, not the filesystem walk. Verify.)
- **Vector search reindex**: same question.
- **Preview page**: when it reads converted Markdown to render in
  viewer.html, where does it get the path from? If from the DB's
  `output_path` field, safe. If from `OUTPUT_BASE / batch_id`,
  needs the same fix.
- **`/api/preview/markdown-output` endpoint** (v0.32.0): verify
  it reads from DB-stored path, not a recomputed `OUTPUT_BASE`
  expression.

These are 30-second grep checks. I'll include them in the v0.33.4
PR's smoke checklist.
