# Active Operations Registry — Design Spec

**Date:** 2026-04-28
**Target release:** v0.35.0 (after v0.34.2 OUTPUT_BASE hotfix)
**Status:** Approved (brainstorming complete; pending writing-plans)

---

## 1. Overview

A unified system for tracking, surfacing, and cancelling every long-running
file-related operation in MarkFlow. Replaces the current ad-hoc per-endpoint
status dicts with a single in-memory + DB-backed registry. Status page
becomes a single-pane-of-glass hub for "what is MarkFlow doing right now",
with each card click-through to the originating page where the operation
was started.

### Why this matters

Today, operators trigger long-running actions (Force Transcribe, Convert
Selected, DB Backup, Search Rebuild, Bulk Re-analyze, …) that return a
toast and then disappear into the void. Two of them (trash empty / restore-
all) have backend progress dicts and a sticky banner; everything else is
fire-and-forget. The Status page shows BulkJobs and pipeline scan state
but nothing else. The result: operators don't know whether their click
took, whether it's still running, or how long it has left.

This spec generalizes the v0.32.6 server-authoritative trash-progress
pattern into a registry that every long-running op routes through.

### Goals

- **One pattern** for any new long-running op — register, update, finish.
- **Two visible surfaces** — sticky banner across all pages, inline widget
  on the originating page, hub index card on Status.
- **Click-through navigation** — Status hub card → originating page with
  `?op_id=<id>` deep-link → in-page widget highlighted on arrival.
- **Server-authoritative timers** — frontend never computes elapsed time;
  backend writes `started_at_epoch` and `last_progress_at_epoch`.
- **Restart-survival** — DB-persisted; ops in flight at container death
  are marked terminated-by-restart on next startup, surfaced in the grace
  window so the operator sees what was lost.
- **Cancel propagation** — every cancellable op_type registers a hook
  bridging the registry's cancel signal to the subsystem's native cancel
  primitive.
- **Consistency** — registry replaces the current per-endpoint pattern
  (trash dicts) so the codebase has one way to do progress.

### Non-goals

- **Replace BulkJob's rich SSE per-file state.** BulkJob keeps its existing
  Active Jobs detail view; the registry holds a thin summary index entry
  only.
- **Replace pipeline-card.** Pipeline scheduling state (next-scan, mode,
  scanner_interval_minutes) stays in pipeline-card. Registry holds an
  index entry for an in-flight scan but doesn't duplicate the scheduling
  metadata.
- **Idempotency keys** (deferred to v2). v1: each click creates a new op.
  Existing `is_any_bulk_active()` and `register_run_now_scan()` mechanisms
  prevent concurrent execution; the second op surfaces with `error_msg`
  set immediately and is visible to the operator.
- **External monitoring / Prometheus metrics export.** Logs only in v1.
- **Cross-process registry** (single FastAPI worker process; no
  multi-worker setup yet).

---

## 2. Architecture

### Module layout

```
core/active_ops.py           — registry: register / update / finish / cancel /
                                list / get; in-memory dict + DB write-through
api/routes/active_ops.py     — GET /api/active-ops; POST /api/active-ops/{id}/cancel
core/db/migrations.py        — migration v29: active_operations table
static/js/active-op-widget.js — inline progress widget (mounted per origin page)
static/js/active-ops-hub.js  — Status page index section
static/js/live-banner.js     — modified: drops endpoint list; consumes /api/active-ops
```

### Component responsibilities

```
┌──────────────────────────────────────────────────────────────────────┐
│  Worker (e.g. _run_convert_selected_batch)                           │
│    op_id = active_ops.register_op(op_type='pipeline.convert_selected',│
│                                    label=..., origin_url='/history…',│
│                                    cancellable=True)                 │
│    for f in files:                                                   │
│      if active_ops.is_cancelled(op_id): break                        │
│      ... do work ...                                                 │
│      active_ops.update_op(op_id, done=processed, errors=failed)      │
│    active_ops.finish_op(op_id, error_msg=None)                       │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  core/active_ops.py registry                                         │
│    - in-memory dict[op_id, ActiveOperation]                          │
│    - asyncio.Lock for cross-task safety                              │
│    - per-op write-through coalescer (1.5s debounce; flush on         │
│      finish, error, cancel, terminal state)                          │
│    - hydrate_on_startup() runs in lifespan                           │
│    - cancel hook registry: op_type → cancel_callback                 │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  active_operations table (SQLite, WAL)                               │
│    - source of truth for restart-survival                            │
│    - in-memory dict is write-through cache for performance           │
│    - reads come from DB (so /api/active-ops gives fresh data even    │
│      across worker process boundaries)                               │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  api/routes/active_ops.py                                            │
│    GET  /api/active-ops          — running + finished-within-30s     │
│    POST /api/active-ops/{id}/cancel                                  │
└──────────────────────────────────────────────────────────────────────┘
                       │
              ┌────────┴─────────┬───────────────┐
              ▼                  ▼               ▼
   ┌──────────────────┐  ┌────────────────┐  ┌─────────────────┐
   │  live-banner.js  │  │ active-op-     │  │ active-ops-     │
   │  (sticky, all    │  │   widget.js    │  │   hub.js        │
   │   pages)         │  │ (inline, per-  │  │ (Status page    │
   │                  │  │   origin-page) │  │   index)        │
   └──────────────────┘  └────────────────┘  └─────────────────┘
```

### Single source of truth

- **In-memory dict** — fastest read path; canonical during a process
  lifetime.
- **`active_operations` DB table** — source of truth across restarts;
  in-memory state is hydrated from DB at startup.
- **`bulk_jobs` and `scan_runs`** — source of truth for their own rich
  state. Active_operations rows for those op_types are *derived state*;
  drift resolution rule: bulk_jobs / scan_runs win.

---

## 3. Data shape

### Migration v29

```sql
CREATE TABLE IF NOT EXISTS active_operations (
    op_id TEXT PRIMARY KEY,
    op_type TEXT NOT NULL,
    label TEXT NOT NULL,
    icon TEXT NOT NULL,
    origin_url TEXT NOT NULL,
    started_by TEXT NOT NULL,
    started_at_epoch REAL NOT NULL,
    last_progress_at_epoch REAL NOT NULL,
    finished_at_epoch REAL,
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    error_msg TEXT,
    cancelled INTEGER NOT NULL DEFAULT 0,   -- bool: cancel was requested
    cancellable INTEGER NOT NULL DEFAULT 0, -- bool: op_type supports cancel
    cancel_url TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_active_ops_running
    ON active_operations (finished_at_epoch)
    WHERE finished_at_epoch IS NULL;
CREATE INDEX IF NOT EXISTS idx_active_ops_finished_at
    ON active_operations (finished_at_epoch DESC)
    WHERE finished_at_epoch IS NOT NULL;
```

Idempotent (`IF NOT EXISTS`); no destructive changes; rollback by
dropping the table.

### Python dataclass

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ActiveOperation:
    op_id: str                           # uuid4
    op_type: str                         # whitelisted (see §4)
    label: str
    icon: str                            # emoji
    origin_url: str
    started_by: str
    started_at_epoch: float
    last_progress_at_epoch: float
    finished_at_epoch: float | None = None
    total: int = 0
    done: int = 0
    errors: int = 0
    error_msg: str | None = None
    cancelled: bool = False
    cancellable: bool = False
    cancel_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
```

JSON serialization for the API: `extra_json` ↔ `extra` (dict) round-trip
via `json.dumps` / `json.loads`. Keys allowed in `extra` are op_type-
specific (see §4 mapping).

---

## 4. v1 op set

### Op type registry

| op_type | Originating page | extra fields | cancellable | Source of progress |
|---|---|---|---|---|
| `pipeline.run_now` | `/history.html` | `{scan_run_id}` | yes | `run_lifecycle_scan(force=True)` ticks |
| `pipeline.convert_selected` | `/history.html` | `{file_count}` | yes | `_run_convert_selected_batch` per-file |
| `pipeline.scan` | `/status.html` | `{scan_run_id, trigger}` | yes | lifecycle_scanner ticks |
| `trash.empty` | `/trash.html` | — | yes | retrofitted from `_empty_trash_status` |
| `trash.restore_all` | `/trash.html` | — | yes | retrofitted from `_restore_all_status` |
| `search.rebuild_index` | `/settings.html` | `{indexes:[...]}` | no | new — Meili rebuild |
| `analysis.rebuild` | `/batch-management.html` | `{batch_id}` | yes | bulk re-analyze worker |
| `db.backup` | `/settings.html` | `{path}` | no | existing backup hook |
| `db.restore` | `/settings.html` | `{path}` | no | existing restore hook |
| `bulk.job` | `/bulk.html?job_id={id}` | `{bulk_job_id, kind}` | yes | thin mirror from BulkJob.tick |

**Total: 10 op_types in v1.** Whitelist enforced at `register_op()` —
unknown op_type raises `ValueError` (caught at import in tests).

Each op_type is paired with a **cancel hook callback** registered at
module import time (see §9). Op_types with `cancellable=True` MUST have a
hook registered, validated by tests.

---

## 5. Backend API

### Public surface (`core/active_ops.py`)

```python
async def register_op(
    *,
    op_type: str,                   # whitelisted
    label: str,                     # human-readable
    icon: str,                      # emoji
    origin_url: str,                # where status card click navigates
    started_by: str,                # user.email
    cancellable: bool = False,
    cancel_url: str | None = None,
    extra: dict | None = None,
) -> str:                            # returns op_id

async def update_op(
    op_id: str,
    *,
    total: int | None = None,
    done: int | None = None,
    errors: int | None = None,
) -> None:                           # no-op on already-finished rows

async def finish_op(
    op_id: str,
    *,
    error_msg: str | None = None,
) -> None:                           # synchronous final flush

async def cancel_op(op_id: str) -> bool:
    """Operator-triggered cancel. Sets cancelled=True, invokes the
    op_type's cancel hook. Returns True if hook fired, False if op
    already finished."""

def is_cancelled(op_id: str) -> bool:
    """Workers call this to observe cancel. Synchronous read against
    in-memory dict — no DB round-trip in worker hot loops."""

async def list_ops(include_finished: bool = True) -> list[ActiveOperation]:
    """Returns running ops + ops finished within last 30s grace window.
    Rows older than 30s after finish are filtered out (UI auto-purge
    cosmetic) but stay in DB until the daily 03:50 purge job."""

async def get_op(op_id: str) -> ActiveOperation | None:
    ...

async def hydrate_on_startup() -> None:
    """Called from FastAPI lifespan BEFORE workers start.
    See §10 for semantics."""
```

### HTTP endpoints (`api/routes/active_ops.py`)

```
GET  /api/active-ops                         (OPERATOR+)
  Returns: {"ops": [ActiveOperation as dict, ...]}
  Includes running ops + ops finished within last 30s
  Cache: no-cache (always fresh)

POST /api/active-ops/{op_id}/cancel          (MANAGER+)
  Returns: {"cancelled": bool, "message": str}
  400 if op already finished or op_type uncancellable
  404 if op_id not found
```

Both endpoints follow project convention — `Depends(require_role(...))`,
`structlog.get_logger(__name__)`, no `innerHTML`-style risks (JSON only).

### Frontend consumption

```
live-banner.js:    GET /api/active-ops every 2s; pick most-recent running op
active-op-widget:  GET /api/active-ops every 2s; filter by per-page predicate
active-ops-hub:    GET /api/active-ops every 2s; show all
```

All three poll the same endpoint. Total: 1 HTTP request every 2s per
page (not 3 — the polling is shared via a tiny `static/js/active-ops-poller.js`
helper that fans out the response).

---

## 6. Frontend integration

### `static/js/active-ops-poller.js` (new, ~80 LOC)

Single shared poller. Pages register subscribers; one HTTP request per
tick fans out to all subscribers. Visibility-aware (pauses when tab
hidden, matches `auto-refresh.js` convention). Public surface:

```js
window.ActiveOpsPoller.subscribe(handler);    // handler(ops_array)
window.ActiveOpsPoller.unsubscribe(handler);
window.ActiveOpsPoller.refresh();              // force tick
```

### `static/js/active-op-widget.js` (new, ~200 LOC)

Inline progress widget. Per-page mount target:

```js
window.mountActiveOpWidget(containerEl, {
  filter: (op) => op.op_type.startsWith('pipeline.'),
  highlightOpId: '<from URL ?op_id=...>',
});
```

DOM contract:
- `<div class="card active-op-row" data-op-id="...">` per matching op
- All styling via CSS variables (`var(--surface)`, `var(--border)`, etc.)
- No hardcoded colors — UX redesign can re-skin without touching JS
- XSS-safe: `createElement` + `textContent`; same convention as
  live-banner.js + pipeline-card.js
- Highlight-on-arrival: 1.8s amber pulse + scroll-into-view when
  `highlightOpId` matches, then drops to default style

### `static/js/active-ops-hub.js` (new, ~150 LOC)

Status page hub index section. Header:
```
┌─ Active Operations (3) ──────────────────────────────┐
│ ⚙ Force Transcribe        45/1,200  ETA 7m  →        │
│ 🗑 Emptying trash          300/500   ETA 47s →        │
│ 💾 DB backup              256/612   ETA 20s →        │
└──────────────────────────────────────────────────────┘
```

Each row is `<a href="${op.origin_url}?op_id=${op.op_id}">`. If the
operator is already on `op.origin_url`, the row hides (deduplicates with
the inline widget per §6.1 below).

If terminated-by-restart count exceeds 20 (see §10), expandable card:
```
┌─ Operations terminated by restart (47) ──────────────┐
│ Showing 20 most recent · [Show all 47] ▾             │
│ ⚙ Force Transcribe        45/1,200  Mar 27 14:23    │
│ ...                                                   │
└──────────────────────────────────────────────────────┘
```

### Per-page widget mounts

| Page | Mount anchor | Filter |
|---|---|---|
| `/history.html` | `<div id="active-op-widget-mount-pipeline">` above Pending Files | `op_type.startsWith('pipeline.')` |
| `/trash.html` | above the file table | `op_type.startsWith('trash.')` |
| `/bulk.html` | above existing Active Jobs section, compact mode | `!op_type.startsWith('bulk.')` |
| `/settings.html` | in Database & Search section | `op_type.startsWith('db.') \|\| op_type === 'search.rebuild_index'` |
| `/batch-management.html` | above batch list | `op_type === 'analysis.rebuild'` |
| `/status.html` | (uses `active-ops-hub.js` instead of widget) | all |

**Dedup rule (§6.1):** the `active-ops-hub.js` on `/status.html` hides
rows whose `origin_url` matches `window.location.pathname` to avoid
duplicating the inline widget. **Caveat:** `/status.html` is no
operation's origin page, so this never hides rows on Status itself.

### `live-banner.js` retrofit

Drops the `endpoints` list and per-endpoint poll loop; subscribes to
`ActiveOpsPoller` instead. Picks the most-recent running op for the
single banner slot. `LiveBanner.register()` becomes a no-op stub with a
deprecation `console.warn`.

---

## 7. Status page reorganization

```
┌─ Status — Active Operations Hub ──────────────────────┐
│ [Active Operations] (NEW INDEX)                       │
│ ┌─ Active Operations (n) ────────────────────────┐    │
│ │ each op as a clickable row                     │    │
│ └─────────────────────────────────────────────────┘    │
│ ┌─ Operations terminated by restart (n) ────────┐    │
│ │ collapsed by default; expand to see full list │    │
│ └─────────────────────────────────────────────────┘    │
│                                                        │
│ [Active Jobs] (existing rich BulkJob view, kept)       │
│ [Pipeline] (existing pipeline-card, kept)              │
│ [Auto-Conversion override] (existing, kept)            │
│ [System Health] (existing, kept)                       │
└────────────────────────────────────────────────────────┘
```

The index is the entry point; existing rich cards are detail views.
Same pattern as a file manager (list + detail pane).

---

## 8. Click-through navigation

Every Status hub card row is `<a href="{op.origin_url}?op_id={op.op_id}">`.

The originating page reads `op_id` from URL and passes to
`mountActiveOpWidget({highlightOpId})`. Widget renders that op with a
1.8s amber pulse animation and scrolls it into view. Same UX pattern as
the v0.32.9 click-through-to-bulk feature.

If the op finishes between Status hub render and the operator clicking
the link, the widget still shows it for the 30s grace window with a
"Done" green pill — operator sees the final state.

---

## 9. Cancel propagation

### The bridge problem (F8, F9, F10)

The registry only knows that cancel was requested (`cancel_op()` flips
`cancelled=True`). Each op_type has its own native cancel mechanism:

| op_type | Native cancel mechanism |
|---|---|
| `pipeline.run_now` | `core.scan_coordinator.notify_run_now_cancelled()` |
| `pipeline.convert_selected` | per-file `is_cancelled(op_id)` check |
| `pipeline.scan` | `lifecycle_scanner` cooperative check |
| `trash.empty` / `trash.restore_all` | existing `_*_cancel_event.set()` patterns |
| `analysis.rebuild` | per-file check |
| `bulk.job` | `BulkJob.cancel(job_id)` |
| `search.rebuild_index` | uncancellable (Meili rebuild is atomic-ish) |
| `db.backup` / `db.restore` | uncancellable (data integrity) |

### Cancel hook registry

```python
# core/active_ops.py
_cancel_hooks: dict[str, Callable[[str], Awaitable[None]]] = {}

def register_cancel_hook(op_type: str, hook: Callable[[str], Awaitable[None]]):
    """Module-level registration. Each subsystem calls this at import time
    if its op_type is cancellable."""
    _cancel_hooks[op_type] = hook

# At active_ops module load: validate that every op_type with
# cancellable=True in the op_type whitelist has a hook registered.
```

Each subsystem that hosts a cancellable op_type registers its hook on
import. Example:

```python
# core/scan_coordinator.py (additions)
from core.active_ops import register_cancel_hook

async def _cancel_run_now_op(op_id: str) -> None:
    notify_run_now_cancelled()

register_cancel_hook('pipeline.run_now', _cancel_run_now_op)
```

### Cancel flow

```
1. operator clicks Cancel on widget
2. POST /api/active-ops/{op_id}/cancel
3. handler calls cancel_op(op_id)
4. cancel_op flips cancelled=True (in-memory + DB write)
5. cancel_op invokes _cancel_hooks[op.op_type](op_id)
6. hook translates to subsystem's native cancel
7. worker observes (either via is_cancelled(op_id) or via the
   subsystem's own coordinator) and bails out
8. worker calls finish_op(op_id, error_msg='Cancelled by operator')
```

If hook itself raises: caught + logged + op marked
`error_msg='Cancel requested but cleanup failed: {err}'` and finished.
Better to over-finalize than leave dangling.

---

## 10. DB persistence + restart hydration

### Write-through pattern

```python
class _OpWriteCoalescer:
    """Per-op debouncer. In-memory dict is always fresh; DB write
    happens at most every 1.5s, with three flush triggers:

    1. Time-based: 1.5s since last flush
    2. Final state: finish_op() forces synchronous flush
    3. First-error: errors went from 0 → >0 (operator alerting)
    """
    WRITE_THROTTLE_MS = 1500
```

All DB writes use `db_write_with_retry` — single-writer queue, no new
locking.

### Hydration on startup

```python
async def hydrate_on_startup() -> None:
    """Run from main.py lifespan, BEFORE scheduler starts and BEFORE
    routers accept requests.

    Any row with finished_at_epoch IS NULL was running when the previous
    process died. The worker is gone, so:
    - Mark up to N=20 most recent as terminated-by-restart (visible to
      operator in 30s grace window)
    - Older ones get finished_at_epoch=now()-31s so they fall outside
      the grace window (still visible via 'Show all N' on Status hub)
    """
    rows_running = await db_fetch_all(
        "SELECT op_id, started_at_epoch FROM active_operations "
        "WHERE finished_at_epoch IS NULL "
        "ORDER BY started_at_epoch DESC"
    )
    if not rows_running:
        log.info("active_ops.hydrate_complete", terminated_count=0)
        _hydration_complete.set()
        return

    now = time.time()
    for i, row in enumerate(rows_running):
        # Top 20: visible in 30s grace window
        # Older: finalized in past so they show only via 'show all' card
        finished_at = now if i < 20 else now - 31
        await db_write_with_retry(lambda r=row, fa=finished_at: _execute(
            "UPDATE active_operations SET finished_at_epoch=?, "
            "error_msg='Container restarted; operation state lost' "
            "WHERE op_id=?",
            (fa, r['op_id']),
        ))
    log.warning(
        "active_ops.terminated_by_restart",
        total=len(rows_running),
        surfaced_in_grace=min(20, len(rows_running)),
    )
    _hydration_complete.set()

# Called from register_op:
async def register_op(...):
    await _hydration_complete.wait()
    ...
```

### Auto-purge

Daily scheduler job at 03:50 (10 min after the existing 03:30 DB
backup, to avoid contention):

```python
# core/scheduler.py
async def _purge_old_active_ops():
    cutoff = time.time() - (7 * 24 * 3600)
    deleted = await db_write_with_retry(lambda: _execute(
        "DELETE FROM active_operations "
        "WHERE finished_at_epoch IS NOT NULL AND finished_at_epoch < ?",
        (cutoff,),
    ))
    log.info("active_ops.purged", count=deleted, cutoff_epoch=cutoff)
```

Scheduler job count: 19 → 20.

---

## 11. Error handling

| Failure mode | Behavior |
|---|---|
| `register_op()` DB write fails | Log error; in-memory entry created; op shows in registry but won't survive restart. Worker continues. |
| `update_op()` DB write fails | Logged + skipped (debouncer retries on next tick). In-memory state stays fresh; UI never sees stale. |
| `finish_op()` DB write fails | Retried via `db_write_with_retry`. If still fails, log critical + leave row open (terminated-by-restart on next startup). |
| Worker crashes mid-op | No `finish_op()` call → row stays unfinished → terminated-by-restart on next lifespan boot. |
| Cancel hook itself raises | Caught + logged; op marked `error_msg='Cancel cleanup failed: {err}'`, `finished_at_epoch=now()`. |
| `update_op()` on already-finished row | No-op + WARN log. Don't reopen. |
| Two workers update same op_id concurrently | `asyncio.Lock` serializes; last-writer-wins on counters (intentional). |
| `cancel_op()` on already-finished op | Returns False; HTTP 400 to caller. |
| `cancel_op()` on uncancellable op | HTTP 400; never invokes hook. |
| Hydration query fails | Log critical; set `_hydration_failed=True`; allow startup; skip auto-mark. Old crashed rows remain `finished_at_epoch IS NULL`, cosmetic — they show as "still running" for 30s on first page load. |
| `active_ops.json` extra_json malformed | Log + treat as `{}`; continue. |
| Frontend poll fails | Existing pattern: log silently, retry next tick. Never blocks UI. |

---

## 12. Concurrency model

- **In-memory dict guarded by single `asyncio.Lock`** for cross-task
  safety.
- **DB writes serialized through `db_write_with_retry`** — same
  single-writer pattern as v0.23.0; no new locking.
- **No second-level "skip when bulk active" QoS tier** — best-practice
  decision: always write, trust the queue, don't add hidden behavior.
  Revisit only if measured contention shows up post-deployment.
- **`is_cancelled(op_id)` is synchronous** — workers call it from hot
  loops without awaiting; reads in-memory dict only.

---

## 13. Testing strategy

### `tests/test_active_ops.py` (~30 tests)

```
TestRegistryHappyPath:
  test_register_returns_unique_op_id
  test_update_modifies_in_memory
  test_finish_marks_finished_at_epoch
  test_finish_synchronously_flushes_to_db

TestConcurrency:
  test_two_workers_same_op_id_last_writer_wins
  test_lock_serializes_overlapping_updates
  test_is_cancelled_synchronous_no_db_round_trip

TestDebouncing:
  test_100_updates_within_1500ms_produces_1_db_write_plus_final
  test_finish_op_forces_synchronous_flush
  test_first_error_forces_immediate_flush

TestRestartHydration:
  test_hydration_marks_running_rows_as_terminated_by_restart
  test_hydration_caps_visible_at_20
  test_hydration_blocking_until_complete
  test_hydration_failure_does_not_crash_app

TestAutoPurge:
  test_purge_deletes_rows_older_than_7d
  test_purge_skips_running_rows
  test_purge_logs_count

TestCancel:
  test_cancel_op_flips_flag
  test_cancel_invokes_registered_hook
  test_cancel_on_finished_op_returns_false
  test_cancel_on_uncancellable_op_raises
  test_hook_registration_required_for_cancellable_op_type

TestSchemaValidation:
  test_unknown_op_type_raises
  test_extra_json_round_trips

TestErrorPaths:
  test_update_on_finished_row_is_noop
  test_db_write_failure_does_not_block_in_memory
```

### `tests/test_active_ops_endpoint.py` (~10 tests)

```
test_get_active_ops_requires_operator_role
test_get_active_ops_returns_running
test_get_active_ops_includes_finished_within_30s
test_get_active_ops_excludes_finished_older_than_30s
test_post_cancel_requires_manager_role
test_post_cancel_404_on_unknown_op_id
test_post_cancel_400_on_uncancellable
test_post_cancel_400_on_already_finished
test_post_cancel_invokes_hook
test_endpoint_returns_no_cache_header
```

### `tests/test_active_ops_integration.py` (~5 tests)

```
test_run_now_registers_op
test_convert_selected_registers_op_per_call
test_trash_empty_registers_op_replacing_old_dict
test_bulk_job_registers_thin_summary
test_cancel_pipeline_run_now_propagates_to_scan_coordinator
```

Frontend tests stay minimal (existing convention) — manual smoke test
on the 5 origin pages + Status hub.

### Smoke test checklist

1. Trigger Force Transcribe → widget appears on history.html
2. Navigate to Status → card visible, click → return to history.html
   with op highlighted
3. Empty trash → both surfaces (banner + status card) update in sync
4. Cancel a running pipeline.convert_selected → worker stops within 1
   tick
5. Restart container with op in flight → Status shows
   "terminated by restart" card on first load
6. Run 25 ops simultaneously, restart → Status shows 20 in grace
   window + "Show all 25" expandable card

---

## 14. Rollout plan

### Version order

1. **v0.34.2 (hotfix, ~1 day)** — close BUG-010 (5 OUTPUT_BASE misses
   from audit) + cache-bust convention drift cleanup. Independent;
   ships first.
2. **v0.35.0 (feature, ~3-4 days)** — this spec.

### v0.35.0 phases

**Phase 1 (registry + DB):**
- `core/active_ops.py`
- migration v29
- hydration in lifespan
- Unit + integration tests
- No retrofits yet; existing endpoints still use old patterns

**Phase 2 (HTTP API):**
- `api/routes/active_ops.py`
- `GET /api/active-ops` + `POST /api/active-ops/{id}/cancel`
- Endpoint tests

**Phase 3 (worker retrofit):**
- `pipeline.run_now`, `pipeline.convert_selected`, `pipeline.scan`
- `trash.empty`, `trash.restore_all` (replaces old dicts)
- `search.rebuild_index`, `analysis.rebuild`
- `db.backup`, `db.restore`
- `bulk.job` (thin mirror from BulkJob)
- All cancel hooks registered

**Phase 4 (frontend):**
- `static/js/active-ops-poller.js`
- `static/js/active-op-widget.js`
- `static/js/active-ops-hub.js`
- `static/js/live-banner.js` retrofit
- Mount widgets on 5 origin pages
- Mount hub on Status

**Phase 5 (deprecation + cleanup):**
- Old `/api/trash/empty/status` etc. become facades pulling from
  registry; OpenAPI marks `deprecated: true`; removed in v0.36.x
- Cache-bust pass on every modified page (`?v=0.35.0`)
- Delete orphaned `static/js/deletion-banner.js`
- Update stale `log_archiver` comments in
  `core/scheduler.py:780`, `api/routes/logs.py:124`,
  `docs/gotchas.md:276`

### Backwards compatibility

- `LiveBanner.register()` becomes deprecation-warning no-op (no crash on
  existing call sites in trash.html, status.html, pipeline-files.html).
- Old `/api/trash/empty/status` and `/api/trash/restore-all/status` kept
  one release as deprecated facades, removed in v0.36.x. Bug-log row
  pre-filed for removal.
- No DB migration is destructive (idempotent CREATE TABLE).

---

## 15. Documentation discipline

Per CLAUDE.md, every release that fixes a bug or introduces a known
bug updates 5 docs together. v0.35.0 is a feature release — bug-log
update step is skipped for shipped fixes, but new BUG-NNN rows added
for the deprecated-endpoint removal scheduled for v0.36.x:

1. `docs/bug-log.md` — new rows (all `status: planned`, target
   v0.36.x):
   - `BUG-011: remove deprecated /api/trash/empty/status and
     /api/trash/restore-all/status after one-release facade window`
   - `BUG-012: apply P1 no-op-on-terminal hardening to BulkJob.tick
     + lifecycle_scanner` (see §17)
   - `BUG-014: drift detection for source-of-truth ↔ thin-mirror
     pairs (P3)`
   - `BUG-015: boot-time self-check for scheduler time-slot
     collisions (P7)`
   - `BUG-016: audit deprecated public surfaces + apply console.warn
     / Sunset (P9)`
2. `docs/version-history.md` — full v0.35.0 entry with this spec's
   structure summarized; cross-reference §1 (why) and §14 (rollout).
3. `docs/help/whats-new.md` — operator-friendly: "Force Transcribe (and
   every other long-running action) now shows a progress bar where you
   started it and on the Status page. Click any active operation card
   on Status to jump to where you started it."
4. `docs/gotchas.md` — TWO new top-level sections:
   - **"Active Operations Registry"** — op-specific gotchas:
     - Every long-running op MUST call `register_op()` at start and
       `finish_op()` at end. Otherwise restart hydration marks it as
       `terminated_by_restart`.
     - `is_cancelled(op_id)` is synchronous — call it from worker hot
       loops without awaiting.
     - bulk_jobs / scan_runs are source of truth for their op_types;
       active_operations is derived state. On drift, source wins.
     - Cancel hook MUST be registered for any op_type with
       `cancellable=True` — validated at import.
   - **"Long-running operations & shared state"** — the 10 P1–P10
     codebase-wide patterns from §17. This is the canonical reference
     for new code touching scheduled jobs, shared mutable state,
     subsystem cancel signals, lifespan ordering, source-of-truth
     drift, deprecation signals, or DB write paths.
5. `CLAUDE.md` — Current Version block + Architecture Reminders gain
   a "Long-running operations" subsection summarizing the 10 patterns:
   - Active Operations Registry — every long-running op routes through
     `core.active_ops`; never roll your own progress dict.
   - Shared mutable state needs `asyncio.Lock`.
   - Source-of-truth + drift rule for any thin-mirror pair (bulk_jobs
     / scan_runs / source_files are sources; mirrors are derived).
   - Subsystem cancel signals bridged via `register_cancel_hook()` —
     never silent.
   - Lifespan-event gating for any subsystem-ready dependency.
   - Predicate-gated scheduler cleanup; never wall-clock-only.
   - Scheduler time slots declared in `docs/scheduler-time-slots.md`.
   - Frontend: CSS variables only; named-anchor mounts; silent
     degradation.
   - Deprecation: `console.warn` (JS) + `Sunset` header (HTTP).
   - DB writes always through `db_write_with_retry`.
6. `docs/key-files.md` — add:
   - `core/active_ops.py` — Active operations registry (v0.35.0)
   - `api/routes/active_ops.py` — Active ops HTTP API (v0.35.0)
   - `static/js/active-op-widget.js` — Inline progress widget (v0.35.0)
   - `static/js/active-ops-hub.js` — Status page index (v0.35.0)
   - `static/js/active-ops-poller.js` — Shared frontend poller (v0.35.0)

---

## 16. Files touched

### New (~9 files)

```
core/active_ops.py                    ~300 LOC
api/routes/active_ops.py              ~80  LOC
static/js/active-op-widget.js         ~200 LOC
static/js/active-ops-hub.js           ~150 LOC
static/js/active-ops-poller.js        ~80  LOC
tests/test_active_ops.py              ~280 LOC
tests/test_active_ops_endpoint.py     ~80  LOC
tests/test_active_ops_integration.py  ~100 LOC
docs/scheduler-time-slots.md          ~80  lines (P7)
```

### Modified (~17 files)

```
main.py                               + lifespan hydrate call, router register
core/db/migrations.py                 + migration v29
core/version.py                       bump to 0.35.0
api/routes/pipeline.py                + register_op around run-now &
                                        convert-selected; cancel hook
api/routes/trash.py                   retrofit empty/restore-all to registry;
                                        keep facades for one release
api/routes/admin.py                   + register_op for db.backup/db.restore
api/routes/analysis.py                + register_op for analysis.rebuild
api/routes/search.py (or wherever)    + register_op for search.rebuild_index
core/bulk_worker.py                   + BulkJob registers thin summary
core/lifecycle_scanner.py             + scan registers + cancel hook
core/scan_coordinator.py              + register_cancel_hook('pipeline.run_now')
core/scheduler.py                     + new daily auto-purge job;
                                        time slot 03:50
static/js/live-banner.js              + consume /api/active-ops via poller;
                                        deprecate register()
static/history.html                   mount widget; cache-bust ?v=0.35.0
static/trash.html                     mount widget; cache-bust ?v=0.35.0
static/bulk.html                      mount compact widget; cache-bust
static/settings.html                  mount widget; cache-bust
static/batch-management.html          mount widget; cache-bust
static/status.html                    mount hub; cache-bust
static/pipeline-files.html            cache-bust ?v=0.35.0
static/preview.html                   cache-bust ?v=0.35.0 (audit cleanup)
docs/bug-log.md                       5 new rows: BUG-011, 012, 014,
                                       015, 016 (all planned)
docs/version-history.md               v0.35.0 entry
docs/help/whats-new.md                operator-friendly summary
docs/gotchas.md                       2 new top-level sections (Active
                                       Ops Registry; Long-running ops &
                                       shared state — P1–P10) + stale
                                       log_archiver fix
docs/key-files.md                     6 new file rows
docs/help/admin-tools.md              new "Active Operations Hub" section
CLAUDE.md                             Current Version block + new
                                       "Long-running operations"
                                       subsection in Architecture
                                       Reminders (10 P1-P10 bullets)
```

### Deleted (~1 file)

```
static/js/deletion-banner.js          orphaned (audit MEDIUM #6)
```

### Modified by P-pattern retrofits (additional)

```
core/scheduler.py                     + module docstring references
                                       scheduler-time-slots.md (P7)
core/lifecycle_manager.py             + retire OUTPUT_REPO_ROOT alias
                                       OR convert to lazy proxy (relates
                                       to BUG-010 hotfix; carry forward
                                       check)
static/js/live-banner.js              + RGBA colors → CSS vars (P8
                                       retrofit; on top of registry
                                       consumption changes)
```

**Total: ~9 new + ~20 modified + 1 deleted. Roughly 1,400 LOC new,
~500 LOC modified.**

---

## 17. Codebase-wide patterns established by this work

The foresight pass uncovered patterns that apply far beyond `active_ops`.
This section elevates each into a **project-wide convention**, identifies
where it applies in existing code, captures the v0.35.0 retrofit work,
and queues anything too large for this release as a planned bug.

The intent: **every mitigation lands as a permanent codebase rule**,
not a one-off active_ops detail. New code MUST follow. Existing code
gets retrofitted in v0.35.0 where cheap, queued as `BUG-NNN: planned`
where larger.

These patterns are added to:
- `docs/gotchas.md` — new top-level subsystem section "Long-running
  operations & shared state"
- `CLAUDE.md` — Architecture Reminders bullets

### P1 — No-op on already-terminal state (from F1)

**Principle:** Any function that mutates a "running" entity (counter,
state-machine row, in-flight op) MUST no-op + WARN log on terminal-
state inputs. Don't reopen finished work, don't double-finalize.

**Today (auditable):**
- `core/bulk_worker.py` `BulkJob` — partial: some defensive checks; not
  uniform across tick / cancel / finalize.
- `api/routes/trash.py` `_empty_trash_status` — no defensive check.
- `core/lifecycle_scanner.py` `_scan_state` — no defensive check.

**v0.35.0 retrofits:**
- `active_ops.update_op()` enforces (spec §11).
- Trash empty / restore-all retrofitted to registry — picks this up
  for free.
- BulkJob thin-mirror enforces.

**Queued — `BUG-012: planned`:** Audit `BulkJob.tick()` for the same
hardening. Audit `lifecycle_scanner` _scan_state mutations. v0.36.x.

### P2 — `asyncio.Lock` for shared in-process mutable state (from F2)

**Principle:** Any in-process dict / list mutated by multiple async
tasks needs an `asyncio.Lock`. Counters can be intentional last-writer-
wins (the lock just serializes the read-modify-write); structural state
(lists of objects, nested dicts) MUST serialize.

**Today:**
- `core/db/pool.py` — single-writer pattern for DB writes (good).
- `_empty_trash_status`, `_restore_all_status` — NO lock; works today
  because only one worker mutates each. Fragile.
- BulkJob internal dicts — class-internal locks (good).
- `core/preferences_cache.py` — has its own lock (good).

**v0.35.0 retrofits:**
- `active_ops` uses `asyncio.Lock` from day 1.
- Trash dicts retired entirely (subsumed by registry).

**No follow-on** — registry retirement of trash dicts closes the only
known violation.

### P3 — Single source of truth + drift rule (from F11, F12, F13)

**Principle:** When the same entity has both a "rich" representation
(e.g., `bulk_jobs` table with per-file SSE state) and a "thin" mirror
(e.g., `active_operations` row showing aggregate progress), name the
SOURCE explicitly and document the drift-resolution rule. **Drift
detection is mandatory; silent drift is the bug.**

**Today:**
- `bulk_jobs` ↔ `active_operations` (NEW in v0.35.0): bulk_jobs wins.
- `scan_runs` ↔ `active_operations` (NEW in v0.35.0): scan_runs wins.
- `source_files` ↔ `bulk_files` (existing): source_files is the
  single source of truth for file-intrinsic data, per CLAUDE.md
  Architecture Reminders.

**v0.35.0 retrofits:**
- New thin mirrors (active_ops summaries) explicitly document their
  source. Module docstrings carry the rule.
- `core/active_ops.py` docstring includes a Mermaid diagram of all
  source-of-truth relationships in the codebase that involve thin
  mirrors.

**Queued:** `BUG-014: planned` — write a periodic drift-detection job
(scheduler 03:55 slot) that compares bulk_jobs.processed vs
active_operations.done for the same op_id; logs `active_ops.drift_
detected` on mismatch. v0.36.x.

### P4 — Lifespan ordering with `asyncio.Event` gates (from F5, F6)

**Principle:** Any subsystem that needs to "be ready" before workers
can use it MUST expose an `asyncio.Event` that gates dependent
operations. Workers `await event.wait()` before first use. Lifespan
sets the event AFTER the subsystem is hydrated. Failure to hydrate
sets the event anyway (graceful degradation) but logs critical.

**Today:**
- `core/preferences_cache.py` — has a `_cache_loaded` event.
- `core/scan_coordinator.py` — has implicit ordering (good).
- `core/vector_indexer.py` `get_vector_indexer()` — returns `None`
  when unreachable; degraded mode (good pattern, formalized in
  CLAUDE.md gotchas).

**v0.35.0 retrofits:**
- `active_ops._hydration_complete` event in lifespan (spec §10).
- Documented in gotchas.md as the canonical pattern for "subsystem
  hydration before first use".

**No follow-on** — pattern is already widely followed; v0.35.0
formalizes the convention.

### P5 — Cancel-hook bridge for cross-subsystem cancellation (from F8, F9, F10)

**Principle:** When a generic surface (registry, API, UI) accepts a
cancel signal but the actual cancel mechanism lives in a different
subsystem, an explicit hook registry bridges them. Hook absence on a
"cancellable" entity is a registration-time error, not a runtime
silent failure.

**Today:**
- `core/scan_coordinator.py` — `notify_run_now_cancelled()` etc.
  Each subsystem invents its own.
- `core/bulk_worker.py` — `BulkJob.cancel(job_id)`.
- `_empty_trash_cancel_event` — local module signal.
- These do NOT bridge to a common surface today.

**v0.35.0 retrofits:**
- `active_ops.register_cancel_hook(op_type, hook)` introduced (spec §9).
- 5 subsystems register hooks: scan_coordinator, lifecycle_scanner,
  trash, bulk_worker, analysis.
- Validation: `cancellable=True` op_type without a hook raises
  `RuntimeError` at registry construction. Caught by tests.

**No follow-on** — every cancellable op_type in v1 has a hook; pattern
is enforced by registry construction.

### P6 — Predicate-gated cleanup (from F3, F18)

**Principle:** Any scheduled cleanup job (purge, compact, archive,
truncate) MUST gate on a predicate that excludes running entities. Time
windows alone are not enough — wall-clock age does NOT prove the row
is no longer needed.

**Today:**
- `core/scheduler.py` lifecycle scan — yields to active bulk via
  `is_any_bulk_active()` (good).
- `core/scheduler.py` trash expiry — yields to active bulk (good).
- `core/scheduler.py` DB compaction — yields to active bulk (good).
- `core/scheduler.py` integrity check — yields to active bulk (good).
- `core/scheduler.py` stale data check — yields to active bulk (good).
- `core/scheduler.py` log archival — does NOT check (intentional —
  logs are not user-data; safe to compact during a job).

**v0.35.0 retrofits:**
- New auto-purge job (active_ops 03:50) follows the pattern: predicate
  `WHERE finished_at_epoch IS NOT NULL` excludes running rows.

**No follow-on** — pattern is already universal in scheduler; v0.35.0's
new job conforms.

### P7 — Scheduler time-slot allocation table (from F18)

**Principle:** Scheduled jobs MUST declare their time slots in a single
canonical table to prevent collisions. Any job that runs daily at HH:MM
gets a row. Adding a new job requires checking the table for
conflicts.

**Today:** No table. Job times are scattered across `core/scheduler.py`.
The audit found that v0.35.0's planned 03:45 job nearly collided with
the existing 03:30 DB backup job. Without a canonical table, future
additions will hit similar conflicts.

**v0.35.0 retrofits:**
- New file: `docs/scheduler-time-slots.md` — canonical allocation
  table. Format: `| slot | job | duration estimate | yields-to |`.
  Lists all 20 scheduled jobs (19 existing + new auto-purge).
- `core/scheduler.py` module docstring references the table.
- New gotchas.md entry: "When adding a scheduled job, update
  `docs/scheduler-time-slots.md` first; check for conflicts in the
  ±15 minute window."

**Queued:** `BUG-015: planned` — write a startup self-check that walks
the scheduler job table at boot and logs `scheduler.time_slot_
collision` if two jobs are within 5 min of each other (and neither
yields to the other). v0.36.x.

### P8 — Frontend: CSS variables only, named anchor mounts (from F14, F15)

**Principle:** Any new or modified `static/js/*.js` module MUST style
exclusively via CSS custom properties (`var(--surface)`,
`var(--text)`, etc.) — no hardcoded hex colors, no new class names that
don't already exist in `markflow.css`. Any element a JS module mounts
into MUST be addressed by a stable ID anchor; deleting/moving the
anchor degrades silently (`if (!container) return;`).

**Today (auditable):**
- `static/js/live-banner.js` — uses some hardcoded RGBA colors
  (`rgba(99,102,241,0.18)`, `rgba(96,165,250,0.18)`). Violates.
- `static/js/pipeline-card.js` — uses CSS vars (good).
- `static/js/cost-estimator.js` — uses CSS vars (good).
- Mount anchors: most pages already use stable IDs (good).

**v0.35.0 retrofits:**
- New widgets (`active-op-widget.js`, `active-ops-hub.js`,
  `active-ops-poller.js`) follow the rule.
- `live-banner.js` is being modified anyway — at the same time, its
  hardcoded RGBA colors are migrated to CSS variables.
- Named-anchor convention documented in gotchas.md.

**No follow-on** — UX redesign (parallel session) will catch any
remaining violations.

### P9 — Deprecation with `console.warn` (from F17)

**Principle:** When a public API (HTTP endpoint, JS function,
preference key, …) is deprecated but kept for one release as a facade,
emit a deprecation signal at every call site:
- JS functions: `console.warn('X is deprecated since vY; use Z')` on
  invocation.
- HTTP endpoints: response header `Deprecation: true` + `Sunset`
  header per RFC 8594; OpenAPI tag `deprecated: true`.
- Preferences: log warning on read; flagged in Settings UI as "deprecated".

**Today:** Inconsistent. Some deprecated paths exist (e.g., legacy
`/app/output` placeholder retired in v0.34.1) but no console-warn or
HTTP header signal.

**v0.35.0 retrofits:**
- `LiveBanner.register()` no-op stub emits `console.warn`.
- Deprecated trash status endpoints emit `Deprecation: true` +
  `Sunset: <date>` header.
- Pattern documented in gotchas.md.

**Queued:** `BUG-016: planned` — audit other deprecated public surfaces
in the codebase and apply the convention. v0.36.x.

### P10 — DB writes always go through `db_write_with_retry` (from F19)

**Principle:** Every DB write — preferences, scheduler state, registry,
backup metadata — uses the single-writer queue (`db_write_with_retry`
since v0.23.0). NO subsystem implements its own retry / serialization
logic. Trust the queue.

**Today:** Universal in `core/db/`, `api/routes/`, `core/bulk_worker.py`.
The audit found this is consistently honored.

**v0.35.0 retrofits:**
- `active_ops` uses the queue (no special-casing for "low priority"
  writes — best-practice decision in spec §12).
- Pattern reaffirmed in gotchas.md.

**No follow-on** — pattern is already universal.

### Summary table

| Pattern | Status today | v0.35.0 action | Queued |
|---|---|---|---|
| P1 No-op on terminal | partial | enforced in active_ops + trash retrofit | BUG-012 |
| P2 asyncio.Lock for shared dicts | mixed | enforced; trash dicts retired | none |
| P3 Source of truth + drift rule | implicit | explicit docstrings + drift detection planned | BUG-014 |
| P4 Lifespan event gates | partial | active_ops uses; gotcha doc | none |
| P5 Cancel-hook bridge | absent | introduced; 5 subsystems register | none |
| P6 Predicate-gated cleanup | universal | new job conforms | none |
| P7 Scheduler time-slot table | absent | new doc + boot self-check | BUG-015 |
| P8 CSS vars + named anchors | mixed | enforced for new + retrofit live-banner | none |
| P9 Deprecation console.warn / Sunset | absent | introduced | BUG-016 |
| P10 DB writes through queue | universal | reaffirmed | none |

### New BUG rows added to bug-log.md

```
BUG-011 (planned, v0.36.x) — Remove deprecated trash status endpoints
                              after one-release facade window.
BUG-012 (planned, v0.36.x) — Apply P1 no-op-on-terminal hardening to
                              BulkJob.tick + lifecycle_scanner.
BUG-014 (planned, v0.36.x) — Drift detection job for source-of-truth
                              ↔ thin-mirror pairs (P3).
BUG-015 (planned, v0.36.x) — Boot-time self-check for scheduler
                              time-slot collisions (P7).
BUG-016 (planned, v0.36.x) — Audit deprecated public surfaces +
                              apply console.warn / Sunset (P9).
```

(BUG-010 lives outside this spec — it's the v0.34.2 OUTPUT_BASE
hotfix.)

---

## 18. Audit cleanup folded into v0.35.0

Picks up these audit findings (separate from the BUG-010 OUTPUT_BASE
hotfix in v0.34.2):

- **Cache-bust convention drift** (audit HIGH #7) — single pass:
  `?v=0.35.0` on every script tag in modified pages.
- **Orphaned `deletion-banner.js`** (audit MEDIUM #6) — deleted.
- **Stale `log_archiver` references** (audit MEDIUM #10, #11) — comment
  cleanup in `core/scheduler.py:780`, `api/routes/logs.py:124`,
  `docs/gotchas.md:276`.

These are low-risk drive-bys that the consistency philosophy demands.

---

## 19. Foresight findings table (for traceability)

The spec internalizes the foresight pass; this is the lookup table for
implementation review:

| ID | Risk | Where addressed |
|---|---|---|
| F1 | update_op after finish | §11 (no-op + warn) |
| F2 | concurrent worker updates | §12 (asyncio.Lock + last-writer-wins) |
| F3 | purge during update | §10 (predicate excludes running rows) |
| F4 | cancel hook fires after finish | §9 (check `if op.finished_at_epoch is None`) |
| F5 | register before hydration | §10 (`_hydration_complete` Event) |
| F6 | hydration query fails | §11 (graceful degradation) |
| F7 | 50 terminated-by-restart noise | §6, §10 (cap 20 + show-all expand) |
| F8 | cancel doesn't reach worker | §9 (cancel hook bridge) |
| F9 | cancellable op_type without hook | §9 (registration validation) |
| F10 | cancel hook itself raises | §11 (over-finalize on raise) |
| F11 | BulkJob double-bookkeeping | §2 (thin summary + drift rule) |
| F12 | bulk_jobs ↔ active_ops drift | §2 (bulk_jobs wins) |
| F13 | scan_runs ↔ active_ops drift | §2 (scan_runs wins) |
| F14 | UX redesign restyle cost | §6 (CSS variables only) |
| F15 | UX redesign moves mount target | §6 (named anchor; silent fail) |
| F16 | duplicate ops from two tabs | §1 non-goals (deferred to v2) |
| F17 | LiveBanner.register() rot risk | §6 (deprecation console.warn) |
| F18 | scheduler time collision | §10 (03:50 slot, 10min after backup) |
| F19 | DB write traffic / QoS | §12 (best practice: always write) |

---

## 20. Known limitations / future work

- **No idempotency keys.** Operator clicks Force Transcribe twice → two
  ops registered (the second visibly errors out via existing
  `is_any_bulk_active()` check). v2: client supplies `Idempotency-Key`
  header; existing op_id returned if dedup match found.
- **Single-process registry.** Multi-worker FastAPI deployment (e.g.,
  multiple uvicorn workers) would have each worker holding its own
  in-memory dict. Today's deployment is single-process so this is fine,
  but if multi-worker becomes a thing, registry needs Redis or a
  pub/sub.
- **No metrics export.** Logs only. Prometheus / Grafana export is a v2
  consideration aligned with the planned external log shipping work
  (see CLAUDE.md "Planned: external log shipping to Grafana Loki").
- **Cancel for `db.backup` / `db.restore` is uncancellable.** A long
  restore could block the operator's UI for minutes. Future work: chunked
  restore with cancel checkpoints.
- **Operator can dismiss a terminated-by-restart card but it stays in
  DB.** v2: dismiss action triggers row deletion.
- **30s grace window is fixed.** v2: settings preference for
  per-operator length.

---

## 21. Appendix: cancel hook contract per op_type

For implementation-time reference. Each subsystem MUST register its
hook at module-import time via `register_cancel_hook(op_type, hook)`.

```python
# pipeline.run_now — core/scan_coordinator.py
async def _cancel_run_now_op(op_id: str) -> None:
    notify_run_now_cancelled()

# pipeline.convert_selected — api/routes/pipeline.py
# Worker checks active_ops.is_cancelled(op_id) per file; no extra hook.

# pipeline.scan — core/lifecycle_scanner.py
async def _cancel_scan_op(op_id: str) -> None:
    # Scanner checks active_ops.is_cancelled(op_id) at the top of each
    # batch. No extra subsystem signal needed.
    pass

# trash.empty — api/routes/trash.py
async def _cancel_empty_trash_op(op_id: str) -> None:
    _empty_trash_cancel_event.set()

# trash.restore_all — api/routes/trash.py
async def _cancel_restore_all_op(op_id: str) -> None:
    _restore_all_cancel_event.set()

# analysis.rebuild — api/routes/analysis.py
# Worker checks active_ops.is_cancelled(op_id) per file.

# bulk.job — core/bulk_worker.py
async def _cancel_bulk_job_op(op_id: str) -> None:
    bulk_job_id = active_ops.get_op(op_id).extra.get('bulk_job_id')
    if bulk_job_id:
        BulkJob.cancel(bulk_job_id)

# search.rebuild_index — uncancellable; no hook.
# db.backup — uncancellable; no hook.
# db.restore — uncancellable; no hook.
```

---

**End of spec.**
