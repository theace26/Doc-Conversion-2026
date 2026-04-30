---
name: Active-ops Phase 3 bookmark — paused after Task 21
description: feat/active-ops-registry @ 8a2788c (v0.35.0); Tasks 14-21 shipped (8/9 of Phase 3); 2 tasks remain (22 db.restore, 23 bulk.job). Dev container has stale base, pytest passes via docker cp pattern. To resume say "continue task 22".
type: project
originSessionId: dc09b8a6-926f-413f-9abc-6a2002d0fc24
---
User is transferring to workstation; bookmarking again.  Resume by
saying "continue task 22".

## Where things stand on `feat/active-ops-registry`

- HEAD: `8a2788c` — `feat(active_ops): retrofit db.backup (Task 21)`
- All commits pushed to `origin/feat/active-ops-registry`
- 8/8 integration tests pass alone and together (13.71s)
- Working tree: clean except for the pre-existing
  `docs/MarkFlow_Program_Summary_v2.docx` modification (not mine, not
  to be committed) and untracked junk (`.claude/settings.json`,
  `hashcat-queue/worker.log`, `docs/spreadsheet/~$phase_model_plan.xlsx`)

## Phase 3 commits in chronological order

1. `8aaa9ff` — Task 15 retrofit pipeline.convert_selected
2. `d8ea8fe` — Task 16 retrofit pipeline.scan
3. `a44bb26` — Task 17 retrofit trash.empty + facade
4. `777a121` — docs: active-ops plan drift punch-list
5. `c7fb809` — Task 18 retrofit trash.restore_all + facade
6. `95ecb47` — Task 19 retrofit search.rebuild_index
7. `79e20c7` — docs: role-based UI gating punch-list
8. `ac95043` — Task 20 retrofit analysis.rebuild + cancel hook
9. `a9f1def` — docs: Phase 3 session bookmark (now superseded by this one)
10. `8a2788c` — Task 21 retrofit db.backup

## Phase 3 progress: 8/9 done

| Task | Op type | Status |
|---|---|---|
| 14 | pipeline.run_now | ✅ shipped (yesterday) |
| 15 | pipeline.convert_selected | ✅ shipped |
| 16 | pipeline.scan | ✅ shipped |
| 17 | trash.empty | ✅ shipped |
| 18 | trash.restore_all | ✅ shipped |
| 19 | search.rebuild_index | ✅ shipped |
| 20 | analysis.rebuild | ✅ shipped |
| 21 | db.backup | ✅ shipped |
| **22** | **db.restore** | **⏳ next — same shape as 21, reuse `authed_admin_real` fixture from conftest, signature differs (multipart upload OR backup_path form)** |
| 23 | bulk.job (BulkJob thin mirror) | ⏳ |

After Phase 3: Phase 4 frontend (Tasks 24-34, 11 tasks) + Phase 5 cleanup
(Tasks 35-46, 12 tasks).

## Patterns established (carry forward into Tasks 21-23)

Every retrofit follows this recipe — see today's commits for working
examples:

1. **Always ground the actual code first** before quoting plan templates;
   line numbers, helper names, and request shapes have all drifted.  See
   `docs/superpowers/plans/2026-04-30-active-ops-plan-drift.md` for the
   pattern-level drift items.
2. **Test fixture first**: `sample_*_id` patterns in `tests/conftest.py`
   use sync sqlite3 (not the async pool — cross-loop pool deadlock when
   combined with `real_server`).
3. **`register_op` has no `total` kwarg** — set total via
   `update_op(op_id, total=N)` immediately after registration.  If total
   is discovered mid-run (Task 19's adobe_entries case), update_op again
   when known.
4. **`cancellable=True` requires both** a real cancel hook (or no-op if
   workers poll `is_cancelled` directly) AND a stub seed in
   `tests/conftest.py`'s `_set_hydration_event` setdefault block.
   `cancellable=False` (Task 19) needs neither.
5. **`finish_op` in `try/finally`** so a shutdown that propagates
   `asyncio.CancelledError` (or any other exception) cannot leak a
   'running' row to `hydrate_on_startup`.
6. **Two-flag bypass when the underlying cancel primitive has a
   "running" guard** (Tasks 14 + 16): direct-set the worker's polled
   flag in addition to calling the existing cancel function.  Doesn't
   apply to Tasks 17/18/20 because those introduced cancel cooperatively
   (registry's flag IS the only signal).
7. **For sync handlers** (Task 20): register_op AFTER the dry_run /
   short-circuit fast paths so previews don't clutter the registry.
8. **For BackgroundTasks/asyncio.create_task handlers** (Tasks 14-19):
   use `authed_operator_real` / `authed_manager_real` fixtures — under
   ASGITransport, BackgroundTasks running in the test loop stalls
   pytest teardown.

## Dev environment state

- Stack: `markflow`, `markflow-mcp`, `meilisearch`, `qdrant` all up on
  the host's running Docker (was paused for battery once today; user
  is suspending Docker again now while moving).
- The running container's `markflow` image was last rebuilt today
  before Task 15 ran.  All Tasks 15-21 production code is in the host
  filesystem, copied into the container via `docker cp` per-iteration.
- For the production `/api/health` UI, the running uvicorn is still
  several commits behind (it boots with the v0.34.9 code from the
  rebuild).  When the user wants the production stack to actually run
  the new code, do `docker-compose build markflow markflow-mcp &&
  docker-compose up -d`.
- **On the workstation pickup**: the user is transferring; the
  workstation needs to pull (`git pull origin feat/active-ops-registry`)
  to get to `8a2788c`.  Then Task 22 can start from a fresh repo state
  (no `docker cp` hack history to reconcile — fresh build picks up
  everything).

## Outstanding non-Phase-3 work (deferred)

- **Pre-existing test flake**: `test_pipeline_run_now_registers_op`
  fails when `tests/test_active_ops_endpoint.py` runs first
  (alphabetical pytest order).  Endpoint test's autouse clears
  `_cancel_hooks`; the conftest re-stubs `pipeline.run_now` with a
  no-op via setdefault, but the real run_now hook isn't a no-op (sets
  `_lifecycle_cancel`).  Documented in the drift punch-list
  (`docs/superpowers/plans/2026-04-30-active-ops-plan-drift.md`),
  out of scope for individual task commits.
- **Role-based UI gating punch-list**: commit `79e20c7`,
  `docs/superpowers/plans/2026-04-30-role-based-ui-gating.md`.  User
  flagged that UI elements served by role-gated endpoints should be
  hidden for users who lack the role; existing infrastructure
  (`/api/auth/me`, `static/app.js:188 roleGte`) just needs consistent
  application across pages.

## Why this bookmark
User is transferring to workstation at desk.  Resume by saying
"continue task 22".  Task 22 is db.restore at
`api/routes/db_health.py:150` (NOT a separate `db_backup.py` — the
plan called for that location but the actual code is all in
`db_health.py`).  Same shape as Task 21 (synchronous, cancellable=False,
no cancel hook needed) — just different request signature (multipart
upload OR backup_path form field, exactly one of the two).

## How to apply when resuming on workstation
1. **First: `git fetch && git pull origin feat/active-ops-registry`**
   — get the workstation's repo to `8a2788c`.
2. Verify state: `git log -1` should show `8a2788c` (Task 21).
3. Verify stack health: `docker-compose ps` + curl
   `localhost:8000/api/health`.  If the workstation hasn't rebuilt the
   markflow image since v0.34.9, the running container is missing
   tasks 15-21 production code.  Either:
   - Rebuild the app layer once before starting Task 22:
     `docker-compose build markflow markflow-mcp && docker-compose up -d`
   - Or continue the docker cp pattern (faster per-iteration but the
     production UI doesn't reflect new behaviour).
4. Read Task 22 from
   `docs/superpowers/plans/2026-04-28-active-operations-registry.md`
   (around line 3652).  Apply the corrections from
   `docs/superpowers/plans/2026-04-30-active-ops-plan-drift.md` and
   the patterns from this file.
5. The `authed_admin_real` fixture (added in Task 21) is already in
   conftest.py.  Re-use it directly.
