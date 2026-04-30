# Active-ops registry plan drift — punch-list (2026-04-30)

**Sibling doc to:** [`2026-04-28-active-operations-registry.md`](2026-04-28-active-operations-registry.md)

**Status:** punch-list, to be addressed from workstation. Tasks 15/16/17 already shipped against the corrected patterns described below; remaining tasks (18-23) will encode further fixes inline as they ship.

---

While shipping Tasks 15 (`pipeline.convert_selected`), 16 (`pipeline.scan`),
and 17 (`trash.empty`) on `feat/active-ops-registry` on 2026-04-30, the
plan repeatedly disagreed with the actual codebase.  Each task's grounding
step caught the drift before any wasted edits, but **the plan still
encodes the old understanding for Tasks 18-23** and will mislead a future
reader (or a non-Opus implementer) unless updated.

## Pattern-level drift (affects most/all remaining Phase 3 tasks)

### 1. Plan's draft tests use the wrong fixture
Plan templates use `authed_manager` / `authed_operator` (in-process via
ASGITransport).  This breaks for any endpoint that spawns work via
`BackgroundTasks` or `asyncio.create_task` — the spawned work runs in the
**test's** event loop, and pytest teardown stalls when the work doesn't
honour cancel promptly.  This is the exact problem `real_server` (commit
`4dc1d61`) was created to solve.

**Fix**: Tasks 18-23 plan templates should specify `authed_manager_real`
or `authed_operator_real` for any endpoint that backgrounds work, plus
a docstring note explaining why.  Today's commits 8aaa9ff / d8ea8fe /
a44bb26 all have working examples of the corrected pattern.

### 2. Plan's draft tests call active_ops module directly
Plan templates do `await active_ops.list_ops()` / `await
active_ops.cancel_op(op_id)` directly from the test body.  This causes a
cross-loop pool deadlock when the test also depends on `real_server` —
the connection pool's single-writer task is bound to whichever loop
called `init_db()` first (the `client` fixture's loop), and writes from
the test's function-scoped loop into that pool deadlock.

**Fix**: all Phase 3 integration tests should poll via HTTP
(`/api/active-ops` GET, `/api/active-ops/{id}/cancel` POST).  Test 14's
existing `test_pipeline_run_now_registers_op` is the canonical pattern.

### 3. register_op() has no `total` kwarg
Plan template (Task 16, line ~3000-ish) writes
`await active_ops.register_op(... total=pre_walk_total, ...)`.  The
actual API (`core/active_ops.py:150-159`) is **keyword-only** with
`op_type, label, icon, origin_url, started_by, cancellable, cancel_url,
extra` — no `total`/`done`/`errors`.  Total is set via a separate
`update_op(op_id, total=N)` call after registration.

**Fix**: scan the plan for any `register_op(... total=` / `done=` /
`errors=` and replace with a `register_op` followed by `update_op`.

### 4. Line numbers in plan are stale (v0.34.x line shifts)
Plan was written from a recon of older codebase state.  Across Phase 3,
real line numbers had drifted by tens to hundreds:
- `_flush_counters_to_db`: plan said line 1099, actual line 1128 in
  pre-Task-16 code.
- Walker call sites: plan said 766 / 989, actual 795 / 1018.
- Skip-tick targets: plan said `_update_scan_progress` at lines 980 /
  1067 (shifted similarly).
- run_lifecycle_scan return paths: plan said "4 distinct paths at
  205, 227, 531, 550", actual 6 paths at 192, 212, 234, 295, 560, 579.
- The `bulk_worker.py` +73 line shift from BUG-018 was already fixed
  in the recon refresh (commit `dae1949`); the rest of the recon was
  not similarly refreshed.

**Fix**: do a full re-grounding pass on the recon doc
(`docs/superpowers/plans/2026-04-28-active-operations-registry-recon.md`)
against current code before Tasks 18-23 are quoted from it.

### 5. Helper / function names in plan are placeholders
Plan template for Task 17 used `_list_trash_files()` and
`_delete_trash_file()` as placeholders.  The actual `purge_all_trash`
inlines the list-and-delete logic (`source_files` SQL fetch, in-line
unlinking via `asyncio.to_thread(p.unlink)`, batch UPDATEs).  Reading
the plan template literally would have produced code that didn't exist
in the codebase.

**Fix**: scan plan templates for placeholder helper names (anything in
backticks that isn't already a defined helper) and either replace with
real names or annotate as "placeholder; see actual code".

### 6. Conftest stub-seed is plan-invisible
`tests/test_active_ops_endpoint.py:21,25` clears `_cancel_hooks` before
+ after every test in that file.  When integration tests run after,
the **real** hooks (registered at module import) are gone, and
`register_op(... cancellable=True)` raises `RuntimeError` unless the
op_type is also `setdefault`-ed in the conftest's `_set_hydration_event`
fixture.  Each Phase 3 task that adds a new op_type with
`cancellable=True` needs to add a line to that block.

**Fix**: plan templates for Tasks 18-23 should include a "Step Nb: add
to conftest stub-hook setdefault block" line.  Already done in today's
commits for `pipeline.convert_selected`, `pipeline.scan`, `trash.empty`;
remaining op_types are `trash.restore_all`, `search.rebuild_index`,
`analysis.rebuild`, `db.backup`, `db.restore`, `bulk.job`.

## Task-specific drift caught (already handled in shipped commits)

### Task 15 (`pipeline.convert_selected`, commit `8aaa9ff`)
- Plan's fixture imported `_async_execute` from `core.database` — this
  function doesn't exist there; the real codebase uses
  `db_execute` + `db_write_with_retry`.
- Plan's fixture INSERTed into `bulk_files` without `job_id` — that
  column is `NOT NULL REFERENCES bulk_jobs(id)`, so the FK requires a
  parent `bulk_jobs` row first.

### Task 16 (`pipeline.scan`, commit `d8ea8fe`)
- Plan's "indent the entire 400-line function in try/finally" approach
  produced a massive churn diff.  Body extraction
  (`run_lifecycle_scan` -> `_run_lifecycle_scan_body` thin wrapper)
  achieved the same goal in +93 lines.  Plan templates for similar
  long-function retrofits in Tasks 18-23 should consider this pattern.
- Plan's cancel hook didn't include the **two-flag bypass** that Task
  14's `_cancel_run_now_via_active_ops` applied for the same reason.
  `cancel_lifecycle_scan()` has an `if _lifecycle_running:` guard that
  drops the cancel signal in the window between `register_op()` and
  `register_lifecycle_scan()` (path resolution, root validation,
  pre-walk count).  Direct `_lifecycle_cancel.set()` is the bypass.
  This applies to **any** Phase 3 task whose underlying cancel
  primitive has a "running" guard.

### Task 17 (`trash.empty`, commit `a44bb26`)
- Plan put `_empty_trash_op_id` module-level state in
  `api/routes/trash.py`, but the legacy `_empty_trash_status` dict was
  in `core/lifecycle_manager.py`.  Kept state in `lifecycle_manager.py`
  for consistency with where the worker is.
- Plan said `get_empty_trash_status()` stays sync; needed to make it
  async to use `active_ops.get_op()` cleanly.  Two callers were already
  in async route handlers, so the change was trivial.
- Plan's draft test had no fixture to seed a trashed file.  POST
  `/api/trash/empty` short-circuits with `{"status": "done"}` when
  `count_source_files_by_lifecycle_status('in_trash')` returns 0,
  bypassing the worker entirely so no op ever registers.  Added a
  `sample_in_trash_source_file_id` fixture that Task 18 will reuse
  (recon §D.2 says trash.restore_all has identical shape).

## Pre-existing flake (separate, not plan drift)

`test_pipeline_run_now_registers_op` fails when `test_active_ops_endpoint.py`
runs first (alphabetical pytest order).  Endpoint test's autouse fixture
clears `_cancel_hooks`; conftest's autouse re-seeds with a **no-op stub**
via `setdefault`, but the real `pipeline.run_now` hook isn't a no-op
(it sets `_lifecycle_cancel`).  When the integration test sends cancel,
the stub does nothing, the lifecycle scan keeps running, the 20s deadline
expires.

This affects only the run_now test; convert_selected / scan / trash.empty
are unaffected because their real hooks are no-ops too.

**Suggested fix** (out of scope for individual task commits, file as a
follow-up):
- Reshape `_reset_active_ops` in `tests/test_active_ops_endpoint.py` to
  scope its `_cancel_hooks.clear()` more carefully (e.g., snapshot +
  restore in finally, or only clear test-specific entries).
- OR register the **real** hooks in the conftest stub fixture instead
  of stubs (would require importing `core.scan_coordinator` from
  conftest, which establishes the right dependency chain).

## Why
The plan was written before the active_ops API was finalised and before
v0.34.x's line shifts.  The recon doc was selectively refreshed for
BUG-018 but not for the rest of Phase 3.  Each Phase 3 task's grounding
step caught the drift, but the plan itself still encodes the old
understanding and will mislead a future reader.

## How to apply
When at workstation, do these in order:
1. Read this file + skim today's three commits (8aaa9ff, d8ea8fe, a44bb26)
   to see the corrected patterns in context.
2. Re-ground the recon doc against current code (line numbers, helper
   names, return paths).  Treat as a separate "recon refresh" commit.
3. Update Tasks 18-23 plan templates to use `*_real` fixtures + HTTP
   polling, drop placeholder helper names, add the conftest stub-seed
   step, and fix any `register_op(... total=)` calls.
4. Optionally fix the pre-existing run_now flake under
   `test_active_ops_endpoint.py` (out of scope for individual tasks
   but easy follow-up).
