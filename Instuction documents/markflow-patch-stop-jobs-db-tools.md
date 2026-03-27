# MarkFlow Patch — Global Stop Controls, Active Jobs Panel, Admin DB Tools & Locations Flag
## Claude Code Instruction — Patch against current HEAD

---

## Read First

Read `CLAUDE.md` before touching any code. This is a multi-feature patch. Implement the
four parts in order — each is independent but Part 1 and Part 2 share infrastructure.

Architecture rules still apply: no SPA, vanilla HTML + fetch, fail gracefully,
structlog for all new logging. All new UI uses `markflow.css` variables.

---

## Part 1 — Global Hard Stop Button + Persistent Scan Status Bar

### What It Is

A persistent floating bar that lives at the bottom of every page. It shows:
- Whether any job is currently running (scan, bulk conversion, lifecycle scan)
- A **STOP ALL** button that hard-stops everything
- A compact summary (e.g. "2 jobs running — 14,200 files scanned")

It follows the user across all pages. Clicking it opens the Active Jobs Panel (Part 2).

### `core/stop_controller.py` — NEW

Single module that owns the global stop state. Every worker checks this before
processing each file. Stopping is cooperative — it does not `SIGKILL`, it signals
workers to drain and exit cleanly after their current file.

```python
"""
core/stop_controller.py

Global stop controller. Workers call should_stop() before each file.
A hard stop sets the global flag, cancels all async tasks that registered,
and records the stop event in SQLite.

This is intentionally simple — one module-level flag, no locks needed because
asyncio is single-threaded. Worker tasks check the flag; they are responsible
for their own clean exit.
"""

import asyncio
import structlog
from datetime import datetime, timezone

log = structlog.get_logger(__name__)

# Module-level state — lives for the lifetime of the process
_stop_requested: bool = False
_stop_requested_at: datetime | None = None
_stop_reason: str = ""
_registered_tasks: dict[str, asyncio.Task] = {}   # job_id → asyncio.Task


def should_stop() -> bool:
    """Workers call this before processing each file. Cheap — just reads a bool."""
    return _stop_requested


def request_stop(reason: str = "admin_requested") -> dict:
    """
    Sets the global stop flag and cancels all registered tasks.
    Returns a summary of what was stopped.
    """
    global _stop_requested, _stop_requested_at, _stop_reason
    _stop_requested = True
    _stop_requested_at = datetime.now(timezone.utc)
    _stop_reason = reason

    stopped = list(_registered_tasks.keys())
    for job_id, task in list(_registered_tasks.items()):
        if not task.done():
            task.cancel()
            log.info("job_cancelled_by_stop", job_id=job_id, reason=reason)

    _registered_tasks.clear()
    log.warning("global_stop_requested", reason=reason, jobs_cancelled=stopped)
    return {"stopped_jobs": stopped, "at": _stop_requested_at.isoformat()}


def reset_stop() -> None:
    """
    Clears the stop flag. Must be called before starting any new job after a stop.
    Called automatically when a new bulk job is created via the API.
    """
    global _stop_requested, _stop_requested_at, _stop_reason
    _stop_requested = False
    _stop_requested_at = None
    _stop_reason = ""
    log.info("stop_flag_reset")


def register_task(job_id: str, task: asyncio.Task) -> None:
    """Workers register their asyncio.Task here so stop_all can cancel them."""
    _registered_tasks[job_id] = task
    log.debug("task_registered", job_id=job_id)


def unregister_task(job_id: str) -> None:
    _registered_tasks.pop(job_id, None)


def get_stop_state() -> dict:
    return {
        "stop_requested":    _stop_requested,
        "stop_requested_at": _stop_requested_at.isoformat() if _stop_requested_at else None,
        "stop_reason":       _stop_reason,
        "registered_tasks":  list(_registered_tasks.keys()),
    }
```

### Wire Stop Checks into Existing Workers

**`core/bulk_worker.py`** — In the worker loop, add at the top of each file iteration:

```python
from core.stop_controller import should_stop, register_task, unregister_task

# At the start of BulkJob.start():
register_task(self.job_id, asyncio.current_task())

# Inside worker loop, before processing each file:
if should_stop():
    log.warning("bulk_worker_stopped", job_id=self.job_id)
    await self._emit({"event": "job_stopped", "job_id": self.job_id,
                      "reason": "global_stop_requested"})
    break

# In finally block of BulkJob.start():
unregister_task(self.job_id)
```

**`core/bulk_scanner.py`** — In `scan()`, after each file upsert:

```python
from core.stop_controller import should_stop

if should_stop():
    log.warning("scan_stopped_early", job_id=job_id, scanned_so_far=files_processed)
    if on_progress:
        await on_progress({"event": "scan_stopped", "job_id": job_id,
                           "scanned": files_processed, "reason": "global_stop_requested"})
    break
```

**`core/lifecycle_scanner.py`** — In the file walk loop:

```python
from core.stop_controller import should_stop

if should_stop():
    log.warning("lifecycle_scan_stopped", scan_run_id=scan_run_id)
    _scan_state["running"] = False
    _scan_state["current_file"] = None
    break
```

**`core/bulk_worker.py` — reset on new job:** In the `POST /api/bulk/jobs` handler
(in `api/routes/bulk.py`), call `reset_stop()` before starting the job:

```python
from core.stop_controller import reset_stop
reset_stop()   # clear any previous stop before starting
```

---

### New Endpoint: `POST /api/admin/stop-all`

Add to `api/routes/admin.py`:

```python
from core.stop_controller import request_stop, get_stop_state, reset_stop

@router.post("/api/admin/stop-all")
async def stop_all_jobs(user = Depends(require_role(UserRole.ADMIN))):
    """
    Hard stop all running jobs. Sets the global stop flag and cancels all
    registered asyncio tasks. Workers will exit after their current file.
    Returns a summary of what was stopped.
    """
    result = request_stop(reason=f"admin_stop by {user.email}")
    log.warning("admin_stop_all", by=user.email, jobs=result["stopped_jobs"])
    return result


@router.post("/api/admin/reset-stop")
async def reset_stop_flag(user = Depends(require_role(UserRole.ADMIN))):
    """Clear the stop flag so new jobs can be started."""
    reset_stop()
    return {"ok": True}


@router.get("/api/admin/stop-state")
async def stop_state(user = Depends(require_role(UserRole.ADMIN))):
    return get_stop_state()
```

---

### New Endpoint: `GET /api/admin/active-jobs`

Add to `api/routes/admin.py`. This is what the persistent bar and status panel poll.

```python
from core.bulk_worker    import get_all_active_jobs      # add this function — see below
from core.lifecycle_scanner import get_scan_state
from core.stop_controller   import get_stop_state

@router.get("/api/admin/active-jobs")
async def active_jobs(user = Depends(require_role(UserRole.OPERATOR))):
    """
    Returns all currently running or recently completed jobs.
    Polled by the global status bar every 5 seconds.
    Minimum role: operator — managers and search users don't need this.
    """
    bulk_jobs = await get_all_active_jobs()   # see below
    lifecycle = get_scan_state()
    stop      = get_stop_state()

    running_count = (
        sum(1 for j in bulk_jobs if j["status"] in ("scanning", "running", "paused"))
        + (1 if lifecycle["running"] else 0)
    )

    return {
        "running_count": running_count,
        "stop_requested": stop["stop_requested"],
        "bulk_jobs": bulk_jobs,
        "lifecycle_scan": lifecycle,
    }
```

**Add `get_all_active_jobs()` to `core/bulk_worker.py`:**

The existing job registry in `bulk_worker.py` tracks active `BulkJob` instances.
Add a function that serializes them:

```python
def get_all_active_jobs() -> list[dict]:
    """Return serialized state of all jobs in the registry (active + recently finished)."""
    # _job_registry is the existing module-level dict[str, BulkJob]
    return [
        {
            "job_id":        job.job_id,
            "status":        job.status,          # scanning/running/paused/done/failed/stopped
            "source_path":   str(job.source_path),
            "output_path":   str(job.output_path),
            "total_files":   job.total_files,
            "converted":     job.converted_count,
            "failed":        job.failed_count,
            "skipped":       job.skipped_count,
            "current_files": job.current_files,   # list of {worker_id, filename} — from active workers panel
            "started_at":    job.started_at.isoformat() if job.started_at else None,
            "options": {
                "fidelity_tier":     job.options.get("fidelity_tier"),
                "ocr_enabled":       job.options.get("ocr_enabled"),
                "llm_enhance":       job.options.get("llm_enhance"),
                "worker_count":      job.options.get("worker_count"),
                "collision_strategy":job.options.get("collision_strategy"),
            }
        }
        for job in _job_registry.values()
    ]
```

Store `options` on `BulkJob` when the job is created from the API request payload.
Store `started_at` as `datetime.now(timezone.utc)` when `BulkJob.start()` is called.

---

### Persistent Global Status Bar — `static/js/global-status-bar.js` — NEW

This JS file is included in every page via a `<script>` tag at the bottom of each
HTML page (add to all existing pages). It injects its own DOM — no markup changes
needed per-page.

```javascript
/**
 * global-status-bar.js
 * Injected into every page. Polls /api/admin/active-jobs every 5s.
 * Shows a persistent bar at the bottom when jobs are running.
 * Opens the Active Jobs panel when clicked.
 */

(function () {
  // Inject bar markup into body
  const bar = document.createElement('div');
  bar.id = 'global-status-bar';
  bar.className = 'gsb hidden';
  bar.innerHTML = `
    <div class="gsb-inner" id="gsb-inner">
      <span class="gsb-indicator" id="gsb-indicator"></span>
      <span class="gsb-text"    id="gsb-text">No active jobs</span>
      <span class="gsb-detail"  id="gsb-detail"></span>
      <div class="gsb-actions">
        <button class="gsb-btn gsb-btn-view"  id="gsb-view-btn">View Jobs</button>
        <button class="gsb-btn gsb-btn-stop"  id="gsb-stop-btn">⬛ STOP ALL</button>
      </div>
    </div>
    <div class="gsb-stop-banner hidden" id="gsb-stop-banner">
      ⚠ Stop requested — jobs are winding down.
      <button class="gsb-link-btn" id="gsb-reset-btn">Reset & allow new jobs</button>
    </div>`;
  document.body.appendChild(bar);

  const elText    = document.getElementById('gsb-text');
  const elDetail  = document.getElementById('gsb-detail');
  const elInd     = document.getElementById('gsb-indicator');
  const elStop    = document.getElementById('gsb-stop-btn');
  const elView    = document.getElementById('gsb-view-btn');
  const elBanner  = document.getElementById('gsb-stop-banner');
  const elReset   = document.getElementById('gsb-reset-btn');

  let pollTimer   = null;
  let lastState   = null;

  async function poll() {
    try {
      const res  = await fetch('/api/admin/active-jobs');
      if (res.status === 401 || res.status === 403) return; // not logged in or not operator — hide bar silently
      const data = await res.json();
      lastState  = data;
      render(data);
    } catch {}
  }

  function render(data) {
    const running = data.running_count > 0;
    const stopped = data.stop_requested;

    bar.classList.toggle('hidden',   !running && !stopped);
    bar.classList.toggle('gsb-idle', !running && !stopped);
    bar.classList.toggle('gsb-running', running && !stopped);
    bar.classList.toggle('gsb-stopped', stopped);

    elBanner.classList.toggle('hidden', !stopped);
    elStop.disabled = stopped;

    if (stopped) {
      elInd.textContent  = '⬛';
      elText.textContent = 'Stop requested — finishing current files';
      elDetail.textContent = '';
      return;
    }

    if (!running) {
      bar.classList.add('hidden');
      return;
    }

    elInd.textContent = '⟳';

    const jobParts = [];
    (data.bulk_jobs || []).filter(j => ['scanning','running','paused'].includes(j.status)).forEach(j => {
      const pct = j.total_files ? Math.round(j.converted / j.total_files * 100) : null;
      jobParts.push(`Bulk: ${j.converted.toLocaleString()}${pct != null ? ` (${pct}%)` : ''} files`);
    });
    if (data.lifecycle_scan?.running) {
      const ls = data.lifecycle_scan;
      const pct = ls.pct != null ? ` (${ls.pct}%)` : '';
      jobParts.push(`Lifecycle scan: ${(ls.scanned||0).toLocaleString()} files${pct}`);
    }

    elText.textContent   = `${data.running_count} job${data.running_count !== 1 ? 's' : ''} running`;
    elDetail.textContent = jobParts.join(' · ');
  }

  // STOP ALL
  elStop.addEventListener('click', async () => {
    if (!confirm('Hard stop all running jobs? Workers will finish their current file and exit.')) return;
    elStop.disabled = true;
    await fetch('/api/admin/stop-all', { method: 'POST' });
    poll();
  });

  // Reset stop flag
  elReset.addEventListener('click', async () => {
    await fetch('/api/admin/reset-stop', { method: 'POST' });
    poll();
  });

  // View Jobs — opens the Active Jobs panel
  elView.addEventListener('click', () => {
    openActiveJobsPanel(lastState);
  });

  // Polling — 5s active, 30s when tab hidden
  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(poll, document.hidden ? 30000 : 5000);
  }
  document.addEventListener('visibilitychange', startPolling);
  poll();
  startPolling();
})();
```

Add `<script src="/js/global-status-bar.js"></script>` to the bottom of `<body>` in:
`index.html`, `bulk.html`, `history.html`, `search.html`, `settings.html`,
`locations.html`, `bulk-review.html`, `unrecognized.html`, `trash.html`,
`db-health.html`, `providers.html`, `admin.html`

Do NOT add it to `review.html`, `debug.html`, or `progress.html` — those pages
have their own focused UX.

---

## Part 2 — Active Jobs Status Panel

A slide-in side panel (not a new page) that shows all active jobs with real-time detail.
Opened by clicking "View Jobs" on the global status bar or a nav item.

### `static/js/active-jobs-panel.js` — NEW

```javascript
/**
 * active-jobs-panel.js
 * Slide-in panel showing all active jobs with real-time progress.
 * Included on all pages alongside global-status-bar.js.
 */

(function () {
  // Inject panel markup
  const panel = document.createElement('div');
  panel.id = 'ajp-panel';
  panel.className = 'ajp-panel ajp-hidden';
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('role', 'dialog');
  panel.innerHTML = `
    <div class="ajp-header">
      <h2>Active Jobs</h2>
      <div class="ajp-header-actions">
        <button class="ajp-stop-all-btn" id="ajp-stop-all">⬛ Stop All Jobs</button>
        <button class="ajp-close-btn"    id="ajp-close">✕</button>
      </div>
    </div>
    <div class="ajp-body" id="ajp-body">
      <p class="ajp-empty">No active jobs.</p>
    </div>`;

  const backdrop = document.createElement('div');
  backdrop.id = 'ajp-backdrop';
  backdrop.className = 'ajp-backdrop ajp-hidden';

  document.body.appendChild(backdrop);
  document.body.appendChild(panel);

  let refreshTimer = null;

  // ── Public API ────────────────────────────────────────────────
  window.openActiveJobsPanel = function (initialData) {
    panel.classList.remove('ajp-hidden');
    backdrop.classList.remove('ajp-hidden');
    document.body.style.overflow = 'hidden';
    if (initialData) renderPanel(initialData);
    startRefresh();
  };

  // ── Close ─────────────────────────────────────────────────────
  function closePanel() {
    panel.classList.add('ajp-hidden');
    backdrop.classList.add('ajp-hidden');
    document.body.style.overflow = '';
    clearInterval(refreshTimer);
  }

  document.getElementById('ajp-close').addEventListener('click', closePanel);
  backdrop.addEventListener('click', closePanel);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

  // ── Stop All ──────────────────────────────────────────────────
  document.getElementById('ajp-stop-all').addEventListener('click', async () => {
    if (!confirm('Stop ALL running jobs? This cannot be undone.')) return;
    await fetch('/api/admin/stop-all', { method: 'POST' });
    refresh();
  });

  // ── Refresh ───────────────────────────────────────────────────
  async function refresh() {
    try {
      const res  = await fetch('/api/admin/active-jobs');
      if (!res.ok) return;
      renderPanel(await res.json());
    } catch {}
  }

  function startRefresh() {
    clearInterval(refreshTimer);
    refreshTimer = setInterval(refresh, 2000);
    refresh();
  }

  // ── Render ────────────────────────────────────────────────────
  function renderPanel(data) {
    const body  = document.getElementById('ajp-body');
    const stop  = document.getElementById('ajp-stop-all');
    stop.disabled = data.stop_requested;

    const sections = [];

    // Bulk jobs
    (data.bulk_jobs || []).forEach(job => {
      sections.push(renderBulkJob(job, data.stop_requested));
    });

    // Lifecycle scan
    if (data.lifecycle_scan) {
      sections.push(renderLifecycleScan(data.lifecycle_scan));
    }

    if (!sections.length) {
      body.innerHTML = '<p class="ajp-empty">No active jobs.</p>';
      return;
    }

    body.innerHTML = sections.join('');

    // Wire per-job stop buttons
    body.querySelectorAll('[data-stop-job]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.stopJob;
        if (!confirm(`Stop job ${jobId.slice(0,8)}…?`)) return;
        btn.disabled = true;
        await fetch(`/api/bulk/jobs/${jobId}/cancel`, { method: 'POST' });
        refresh();
      });
    });
  }

  function renderBulkJob(job, stopRequested) {
    const isActive = ['scanning', 'running'].includes(job.status);
    const pct = job.total_files ? Math.round(job.converted / job.total_files * 100) : null;
    const pctStr = pct != null ? `${pct}%` : '?%';

    const activeWorkers = (job.current_files || []).map(w =>
      `<div class="ajp-worker-row">
        <span class="ajp-worker-id">W${w.worker_id}</span>
        <span class="ajp-worker-file" title="${escHtml(w.filename)}">${truncatePath(w.filename, 55)}</span>
       </div>`
    ).join('');

    const dirTree = buildDirSummary(job);

    return `
      <div class="ajp-job-card ${isActive ? 'ajp-job-active' : ''}">
        <div class="ajp-job-header">
          <div>
            <span class="ajp-job-status ajp-status-${job.status}">${job.status.toUpperCase()}</span>
            <span class="ajp-job-id">${job.job_id.slice(0, 8)}…</span>
          </div>
          ${isActive && !stopRequested
            ? `<button class="ajp-stop-job-btn" data-stop-job="${job.job_id}">⬛ Stop</button>`
            : ''}
        </div>

        <div class="ajp-job-paths">
          <div><span class="ajp-label">Source</span><span class="ajp-mono">${escHtml(job.source_path)}</span></div>
          <div><span class="ajp-label">Output</span><span class="ajp-mono">${escHtml(job.output_path)}</span></div>
        </div>

        <div class="ajp-progress-row">
          <div class="ajp-progress-track">
            <div class="ajp-progress-fill" style="width:${pct ?? 0}%"></div>
          </div>
          <span class="ajp-progress-label">
            ${job.converted.toLocaleString()} converted
            ${job.total_files ? `/ ${job.total_files.toLocaleString()} total` : ''}
            — ${pctStr}
          </span>
        </div>

        <div class="ajp-counters">
          <span class="ajp-counter">✓ ${job.converted.toLocaleString()} converted</span>
          <span class="ajp-counter ajp-err">✗ ${job.failed.toLocaleString()} failed</span>
          <span class="ajp-counter ajp-skip">⏭ ${job.skipped.toLocaleString()} skipped</span>
        </div>

        ${job.options ? renderOptions(job.options) : ''}

        ${activeWorkers
          ? `<details class="ajp-workers-detail" open>
               <summary>Active Workers (${job.current_files?.length ?? 0})</summary>
               <div class="ajp-workers-list">${activeWorkers}</div>
             </details>`
          : ''}

        ${dirTree
          ? `<details class="ajp-dir-detail">
               <summary>Directory Progress</summary>
               <div class="ajp-dir-tree">${dirTree}</div>
             </details>`
          : ''}
      </div>`;
  }

  function renderLifecycleScan(ls) {
    if (!ls.running && !ls.last_scan_at) return '';
    const pct = ls.pct != null ? `${ls.pct}%` : '?%';
    const eta = ls.eta_seconds != null ? ` — ~${fmtDuration(ls.eta_seconds)} remaining` : '';
    return `
      <div class="ajp-job-card ${ls.running ? 'ajp-job-active' : ''}">
        <div class="ajp-job-header">
          <span class="ajp-job-status ${ls.running ? 'ajp-status-running' : 'ajp-status-done'}">
            ${ls.running ? 'LIFECYCLE SCAN' : 'LAST LIFECYCLE SCAN'}
          </span>
        </div>
        ${ls.running ? `
          <div class="ajp-progress-row">
            <div class="ajp-progress-track">
              <div class="ajp-progress-fill" style="width:${ls.pct ?? 0}%"></div>
            </div>
            <span class="ajp-progress-label">
              ${(ls.scanned||0).toLocaleString()} files scanned${ls.total ? ` / ${ls.total.toLocaleString()} total` : ''} — ${pct}${eta}
            </span>
          </div>
          ${ls.current_file
            ? `<div class="ajp-current-file"><span class="ajp-label">Current</span>
               <span class="ajp-mono">${escHtml(truncatePath(ls.current_file, 70))}</span></div>`
            : ''}
        ` : `
          <div class="ajp-job-paths">
            <div><span class="ajp-label">Last run</span>
            <span>${ls.last_scan_at ? formatRelativeTime(ls.last_scan_at) : 'unknown'}</span></div>
          </div>
        `}
      </div>`;
  }

  function renderOptions(opts) {
    const rows = Object.entries(opts)
      .filter(([, v]) => v != null)
      .map(([k, v]) => `<span class="ajp-opt"><span class="ajp-opt-key">${k.replace(/_/g,' ')}</span>: ${v}</span>`);
    return rows.length
      ? `<div class="ajp-options">${rows.join('')}</div>`
      : '';
  }

  // ── Directory Summary ─────────────────────────────────────────
  // Build a flat list of top-level directories from source_path and
  // derive per-directory counts from converted/failed counters.
  // Full real-time directory tree would require a per-directory progress
  // event stream — that's out of scope here. Show top-level summary instead,
  // based on the scan_progress data embedded in the job state.
  // TODO: extend with per-directory counts from a future scan_dir_stats endpoint.
  function buildDirSummary(job) {
    if (!job.dir_stats || !Object.keys(job.dir_stats).length) return null;
    return Object.entries(job.dir_stats)
      .map(([dir, stats]) =>
        `<div class="ajp-dir-row">
          <span class="ajp-dir-name">${escHtml(dir)}/</span>
          <span class="ajp-dir-counts">
            <span class="ajp-ok">✓${stats.converted||0}</span>
            ${stats.failed ? `<span class="ajp-err">✗${stats.failed}</span>` : ''}
            ${stats.pending ? `<span class="ajp-muted">${stats.pending} pending</span>` : ''}
          </span>
         </div>`
      ).join('');
  }

  // ── Helpers ───────────────────────────────────────────────────
  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function fmtDuration(s) {
    if (s < 60)   return `${s}s`;
    if (s < 3600) return `${Math.round(s/60)}m`;
    const h = Math.floor(s/3600), m = Math.round((s%3600)/60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }

  // truncatePath and formatRelativeTime are expected to exist in app.js
  // If not, define them here as fallbacks
  if (!window.truncatePath) {
    window.truncatePath = (p, maxLen) => {
      if (!p || p.length <= maxLen) return p;
      const parts = p.split('/');
      const fname = parts.pop();
      while (parts.length && (parts.join('/') + '/…/' + fname).length > maxLen) parts.shift();
      return `…/${parts.join('/')  ? parts.join('/') + '/' : ''}${fname}`;
    };
  }

  if (!window.formatRelativeTime) {
    window.formatRelativeTime = (iso) => {
      if (!iso) return 'unknown';
      const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
      if (diff < 60)   return `${diff}s ago`;
      if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
      return `${Math.floor(diff/86400)}d ago`;
    };
  }
})();
```

Add `<script src="/js/active-jobs-panel.js"></script>` to the same pages as `global-status-bar.js`.
Load it BEFORE `global-status-bar.js` (it defines `window.openActiveJobsPanel` that the bar calls).

---

### Per-Directory Progress (Backend Support)

To support the directory tree view with per-directory counts, add `dir_stats` tracking
to `BulkJob` in `core/bulk_worker.py`:

```python
# On BulkJob init:
self.dir_stats: dict[str, dict] = {}   # top_dir → {converted, failed, pending}

# When a file is successfully converted:
top_dir = str(Path(file.source_path).relative_to(self.source_path).parts[0]) \
          if len(Path(file.source_path).relative_to(self.source_path).parts) > 1 \
          else "(root)"
self.dir_stats.setdefault(top_dir, {"converted": 0, "failed": 0, "pending": 0})
self.dir_stats[top_dir]["converted"] += 1

# When a file fails:
self.dir_stats[top_dir]["failed"] += 1
```

Include `dir_stats` in `get_all_active_jobs()` serialization.

Note: Only track top-level subdirectory, not the full tree. A 500k-file share with
10,000 directories would make this dict enormous. Top-level gives useful overview
without memory risk. Document this as a known scope decision in CLAUDE.md.

---

## Part 3 — Admin Page: Database Health Buttons

### Context

`api/routes/db_health.py` and `core/db_maintenance.py` already exist (Phase 9).
They have VACUUM, integrity checks, and stale data detection. They need to be
surfaced as buttons on the admin page with live feedback.

### New Endpoints (add to `api/routes/db_health.py`)

```python
@router.post("/api/db/health-check")
async def run_health_check(user = Depends(require_role(UserRole.ADMIN))):
    """
    Runs a quick DB health check:
    - PRAGMA integrity_check (quick mode — checks page structure, not full content)
    - Check DB file size and last modified time
    - Check WAL file size (large WAL = checkpoint not running)
    - Count rows in key tables
    Returns results immediately — this is fast (< 1 second on typical DB).
    """

@router.post("/api/db/integrity-check")
async def run_integrity_check(user = Depends(require_role(UserRole.ADMIN))):
    """
    Full integrity check: PRAGMA integrity_check (full, not quick).
    Slower — may take 30+ seconds on a large DB. Returns all errors found.
    If clean: {"ok": true, "errors": []}
    If errors: {"ok": false, "errors": ["row 14 in table bulk_files: ..."]}
    """

@router.post("/api/db/repair")
async def repair_database(user = Depends(require_role(UserRole.ADMIN))):
    """
    Attempts DB repair via dump-and-restore:
    1. sqlite3 markflow.db .dump > /tmp/markflow_dump.sql
    2. Create new markflow_repaired.db from dump
    3. If successful, replace markflow.db with repaired version
    4. Keep original as markflow.db.bak

    IMPORTANT: This acquires an exclusive lock. All requests will wait.
    Only runs if there is NO active scan or bulk job (check stop_controller).
    Returns error if jobs are running — user must stop all first.
    """
```

**Implement the three checks in `core/db_maintenance.py`:**

**`run_health_check()`** — async, uses aiosqlite pattern:
```python
async def run_health_check() -> dict:
    import os
    db_path = Path(os.getenv("DB_PATH", "markflow.db"))
    results = {}

    async with aiosqlite.connect(db_path) as conn:
        # Quick integrity check
        cur = await conn.execute("PRAGMA quick_check")
        rows = await cur.fetchall()
        results["quick_check"] = [r[0] for r in rows]
        results["quick_check_ok"] = results["quick_check"] == ["ok"]

        # WAL size
        wal = db_path.with_suffix(".db-wal")
        results["wal_size_mb"] = round(wal.stat().st_size / 1024 / 1024, 2) if wal.exists() else 0

        # DB file size
        results["db_size_mb"] = round(db_path.stat().st_size / 1024 / 1024, 2)

        # Row counts for key tables
        tables = ["bulk_files", "conversion_history", "ocr_flags", "llm_providers",
                  "api_keys", "scan_runs", "file_versions"]
        counts = {}
        for t in tables:
            try:
                cur = await conn.execute(f"SELECT COUNT(*) FROM {t}")
                counts[t] = (await cur.fetchone())[0]
            except Exception:
                counts[t] = None  # table may not exist yet
        results["row_counts"] = counts

    results["generated_at"] = datetime.now(timezone.utc).isoformat()
    return results
```

**`run_integrity_check()`** — may be slow, run in `asyncio.to_thread()`:
```python
async def run_integrity_check() -> dict:
    import sqlite3
    db_path = os.getenv("DB_PATH", "markflow.db")

    def _check():
        conn = sqlite3.connect(db_path)
        cur  = conn.execute("PRAGMA integrity_check")
        rows = [r[0] for r in cur.fetchall()]
        conn.close()
        return rows

    rows = await asyncio.to_thread(_check)
    ok   = rows == ["ok"]
    return {"ok": ok, "errors": [] if ok else rows,
            "generated_at": datetime.now(timezone.utc).isoformat()}
```

**`repair_database()`** — dump and restore:
```python
async def repair_database() -> dict:
    from core.stop_controller import get_stop_state
    state = get_stop_state()
    if state["registered_tasks"]:
        raise ValueError("Active jobs are running. Stop all jobs before repairing.")

    db_path   = Path(os.getenv("DB_PATH", "markflow.db"))
    bak_path  = db_path.with_suffix(".db.bak")
    new_path  = db_path.with_suffix(".db.repaired")

    def _repair():
        import sqlite3, shutil
        # Dump
        src  = sqlite3.connect(str(db_path))
        dump = "\n".join(src.iterdump())
        src.close()
        # Restore to new file
        dst = sqlite3.connect(str(new_path))
        dst.executescript(dump)
        dst.close()
        # Rotate
        shutil.copy2(str(db_path), str(bak_path))
        new_path.rename(db_path)
        return True

    try:
        await asyncio.to_thread(_repair)
        return {"ok": True, "backup": str(bak_path),
                "generated_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"ok": False, "error": str(e),
                "generated_at": datetime.now(timezone.utc).isoformat()}
```

---

### Admin Page — Database Tools Section

Add to `static/admin.html` in the Admin page (after Stats, before Task Manager):

```html
<section class="admin-section" id="db-tools">
  <h2>Database Tools</h2>
  <p class="section-desc">
    Run from <a href="/db-health.html">DB Health</a> for full details.
    These run live against the active database.
  </p>

  <div class="db-tool-row">

    <div class="db-tool-card">
      <h3>Health Check <span class="tool-badge tool-fast">fast</span></h3>
      <p>Quick structural check, WAL size, row counts. Completes in under a second.</p>
      <button class="btn-secondary" id="btn-health-check">Run Health Check</button>
      <div class="db-tool-result" id="result-health-check" hidden></div>
    </div>

    <div class="db-tool-card">
      <h3>Integrity Check <span class="tool-badge tool-slow">slow</span></h3>
      <p>Full content verification. May take 30+ seconds on large databases.</p>
      <button class="btn-secondary" id="btn-integrity-check">Run Integrity Check</button>
      <div class="db-tool-result" id="result-integrity-check" hidden></div>
    </div>

    <div class="db-tool-card db-tool-card-danger">
      <h3>Repair Database <span class="tool-badge tool-danger">destructive</span></h3>
      <p>
        Dump and restore via SQL. Original saved as <code>.db.bak</code>.
        <strong>Stop all jobs first.</strong> App will be briefly unavailable during repair.
      </p>
      <button class="btn-danger" id="btn-repair-db">Repair Database</button>
      <div class="db-tool-result" id="result-repair" hidden></div>
    </div>

  </div>
</section>
```

### DB Tools JS (add to admin.html inline script):

```javascript
// ── DB Tools ──────────────────────────────────────────────────
async function runDbTool(endpoint, resultId, btnId, confirmMsg) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  const btn    = document.getElementById(btnId);
  const result = document.getElementById(resultId);
  btn.disabled = true;
  btn.textContent = 'Running…';
  result.hidden = false;
  result.className = 'db-tool-result db-tool-running';
  result.textContent = 'Running…';

  try {
    const res  = await fetch(endpoint, { method: 'POST' });
    const data = await res.json();
    renderDbResult(result, data);
  } catch (e) {
    result.className = 'db-tool-result db-tool-error';
    result.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = btn.dataset.label;
  }
}

function renderDbResult(el, data) {
  if (data.ok === false) {
    el.className = 'db-tool-result db-tool-error';
    const errors = data.errors?.join('\n') || data.error || 'Unknown error';
    el.innerHTML = `<strong>✗ Check failed</strong><pre>${escapeHtml(errors)}</pre>`;
    return;
  }

  if (data.ok === true) {
    el.className = 'db-tool-result db-tool-ok';
    if (data.backup) {
      el.innerHTML = `<strong>✓ Repair complete</strong> — backup saved to <code>${escapeHtml(data.backup)}</code>`;
    } else {
      el.innerHTML = '<strong>✓ No errors found</strong>';
    }
    return;
  }

  // Health check — rich output
  el.className = 'db-tool-result db-tool-ok';
  const qc  = data.quick_check_ok ? '✓ Structure OK' : '✗ Structural issues detected';
  const wal = data.wal_size_mb > 50
    ? `⚠ WAL is ${data.wal_size_mb} MB — checkpoint may be stalled`
    : `✓ WAL: ${data.wal_size_mb} MB`;
  const counts = Object.entries(data.row_counts || {})
    .map(([t, c]) => `${t}: ${c != null ? c.toLocaleString() : 'n/a'}`)
    .join(' · ');
  el.innerHTML = `
    <div>${qc}</div>
    <div>${wal}</div>
    <div>DB size: ${data.db_size_mb} MB</div>
    <div class="text-muted text-sm">${counts}</div>`;
}

// Wire buttons
document.getElementById('btn-health-check')?.addEventListener('click', () => {
  runDbTool('/api/db/health-check', 'result-health-check', 'btn-health-check', null);
});
document.getElementById('btn-integrity-check')?.addEventListener('click', () => {
  runDbTool('/api/db/integrity-check', 'result-integrity-check', 'btn-integrity-check', null);
});
document.getElementById('btn-repair-db')?.addEventListener('click', () => {
  runDbTool('/api/db/repair', 'result-repair', 'btn-repair-db',
    'This will dump and restore the database. All active jobs must be stopped first. Continue?');
});

// Store original button labels for restore after run
document.querySelectorAll('.db-tool-card button').forEach(btn => {
  btn.dataset.label = btn.textContent;
});
```

---

## Part 4 — Locations: Flag as Needs Revisiting

**Do not change any Locations functionality.** Leave all code in `api/routes/locations.py`,
`static/locations.html`, and `core/bulk_scanner.py` exactly as-is.

Make two small changes only:

### 1. Add a visible banner to `static/locations.html`

At the very top of the `<body>`, before any content:

```html
<div class="flag-banner">
  ⚑ <strong>Flagged for UX Review</strong> —
  The Locations layout and workflow are marked for redesign.
  Core functionality is preserved and operational.
  <a href="https://github.com/theace26/Doc-Conversion-2026/issues" target="_blank" rel="noopener">
    Track in GitHub Issues →
  </a>
</div>
```

CSS (add to `markflow.css`):
```css
.flag-banner {
  background: #fff8e1;
  border-bottom: 2px solid #f9a825;
  color: #5d4037;
  padding: 10px 16px;
  font-size: 0.875rem;
  text-align: center;
}
@media (prefers-color-scheme: dark) {
  .flag-banner {
    background: #3e2f00;
    border-color: #f9a825;
    color: #ffe082;
  }
}
```

### 2. Add a CLAUDE.md gotcha entry

At the end of the Gotchas section in `CLAUDE.md`, add:

```
- **Locations UX flagged for redesign**: static/locations.html and api/routes/locations.py
  are functional but the layout and workflow have been flagged for UX revision.
  Do NOT refactor until a redesign spec is written. A banner is shown to users.
  Core functions (add/edit/delete location, path validation, FolderPicker) work correctly.
  Tracked: LOCATIONS_UX_REDESIGN (search this token to find all related notes).
```

That token `LOCATIONS_UX_REDESIGN` makes it easy to grep for when the time comes.

---

## CSS — Add to `markflow.css`

```css
/* ── Global Status Bar ── */
.gsb {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  font-size: 0.85rem;
  border-top: 1px solid var(--border);
  transition: transform 0.2s ease;
}

.gsb.hidden { transform: translateY(100%); pointer-events: none; }

.gsb-inner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: var(--surface);
}

.gsb-running .gsb-inner { background: var(--surface); border-top-color: var(--accent, #4a90e2); }
.gsb-stopped .gsb-inner { background: #fff3e0; border-top-color: #f9a825; }

.gsb-indicator { font-size: 1.1rem; animation: gsb-spin 1.2s linear infinite; }
.gsb-stopped .gsb-indicator { animation: none; }
@keyframes gsb-spin { to { transform: rotate(360deg); } }

.gsb-text   { font-weight: 600; }
.gsb-detail { color: var(--text-muted); flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.gsb-actions { display: flex; gap: 8px; flex-shrink: 0; }

.gsb-btn {
  padding: 4px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--surface-alt);
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
}
.gsb-btn-stop {
  background: #d32f2f;
  color: #fff;
  border-color: #b71c1c;
}
.gsb-btn-stop:hover { background: #b71c1c; }
.gsb-btn-stop:disabled { opacity: 0.5; cursor: not-allowed; }

.gsb-stop-banner {
  padding: 6px 16px;
  background: #fff3e0;
  color: #e65100;
  font-weight: 600;
  font-size: 0.82rem;
  display: flex;
  align-items: center;
  gap: 12px;
}
.gsb-link-btn {
  background: none;
  border: none;
  color: var(--accent, #4a90e2);
  cursor: pointer;
  text-decoration: underline;
  font-size: 0.82rem;
}

/* Pad page content so bar doesn't cover it */
body { padding-bottom: 56px; }

/* ── Active Jobs Panel ── */
.ajp-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  z-index: 1100;
}
.ajp-backdrop.ajp-hidden { display: none; }

.ajp-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(520px, 100vw);
  background: var(--surface);
  border-left: 1px solid var(--border);
  z-index: 1200;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ajp-panel.ajp-hidden { display: none; }

.ajp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.ajp-header h2 { margin: 0; font-size: 1.1rem; }
.ajp-header-actions { display: flex; gap: 8px; align-items: center; }

.ajp-stop-all-btn {
  background: #d32f2f; color: #fff; border: none;
  padding: 5px 12px; border-radius: var(--radius); cursor: pointer;
  font-weight: 700; font-size: 0.82rem;
}
.ajp-stop-all-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ajp-close-btn {
  background: none; border: 1px solid var(--border);
  padding: 4px 10px; border-radius: var(--radius); cursor: pointer;
  font-size: 1rem;
}

.ajp-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ajp-empty { color: var(--text-muted); text-align: center; padding: 2rem; }

.ajp-job-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px;
  background: var(--surface-alt);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ajp-job-active { border-color: var(--accent, #4a90e2); }

.ajp-job-header  { display: flex; justify-content: space-between; align-items: center; }
.ajp-job-status  { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em;
                   padding: 2px 8px; border-radius: 999px; background: var(--border); }
.ajp-status-running { background: var(--accent, #4a90e2); color: #fff; }
.ajp-status-scanning { background: #7c4dff; color: #fff; }
.ajp-status-paused  { background: #ff9800; color: #fff; }
.ajp-status-done    { background: var(--success, #4caf50); color: #fff; }
.ajp-status-stopped { background: #9e9e9e; color: #fff; }
.ajp-status-failed  { background: #f44336; color: #fff; }
.ajp-job-id { font-size: 0.75rem; color: var(--text-muted); font-family: monospace; margin-left: 8px; }

.ajp-stop-job-btn {
  background: #d32f2f; color: #fff; border: none;
  padding: 3px 10px; border-radius: var(--radius); cursor: pointer;
  font-size: 0.78rem; font-weight: 700;
}

.ajp-job-paths { display: flex; flex-direction: column; gap: 2px; font-size: 0.8rem; }
.ajp-job-paths > div { display: flex; gap: 6px; align-items: baseline; }
.ajp-label { font-weight: 600; font-size: 0.72rem; color: var(--text-muted);
             text-transform: uppercase; letter-spacing: 0.05em; flex-shrink: 0; }
.ajp-mono  { font-family: monospace; font-size: 0.78rem; word-break: break-all; }

.ajp-progress-row { display: flex; flex-direction: column; gap: 4px; }
.ajp-progress-track { height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
.ajp-progress-fill  { height: 100%; background: var(--accent, #4a90e2);
                       border-radius: 4px; transition: width 0.5s ease; }
.ajp-progress-label { font-size: 0.78rem; color: var(--text-muted); }

.ajp-counters { display: flex; gap: 12px; font-size: 0.8rem; flex-wrap: wrap; }
.ajp-counter  { font-size: 0.78rem; }
.ajp-err      { color: var(--danger, #f44336); }
.ajp-skip     { color: var(--text-muted); }
.ajp-ok       { color: var(--success, #4caf50); }
.ajp-muted    { color: var(--text-muted); }

.ajp-options  { display: flex; flex-wrap: wrap; gap: 6px; }
.ajp-opt      { font-size: 0.75rem; padding: 1px 8px; background: var(--surface);
                border: 1px solid var(--border); border-radius: 999px; }
.ajp-opt-key  { color: var(--text-muted); }

.ajp-workers-detail, .ajp-dir-detail {
  border: none; background: none;
}
.ajp-workers-detail summary, .ajp-dir-detail summary {
  font-size: 0.8rem; font-weight: 600; cursor: pointer; color: var(--text-muted);
}
.ajp-workers-list { display: flex; flex-direction: column; gap: 3px; margin-top: 6px; }
.ajp-worker-row   { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; }
.ajp-worker-id    { font-weight: 700; color: var(--accent, #4a90e2); flex-shrink: 0; width: 24px; }
.ajp-worker-file  { font-family: monospace; color: var(--text-muted);
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.ajp-dir-tree { margin-top: 6px; display: flex; flex-direction: column; gap: 2px; }
.ajp-dir-row  { display: flex; justify-content: space-between; align-items: center;
                font-size: 0.78rem; padding: 2px 0; border-bottom: 1px solid var(--border); }
.ajp-dir-name { font-family: monospace; font-size: 0.75rem; }
.ajp-dir-counts { display: flex; gap: 8px; flex-shrink: 0; }
.ajp-current-file { font-size: 0.78rem; }

/* ── DB Tool Cards ── */
.db-tool-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}
.db-tool-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem;
  background: var(--surface);
}
.db-tool-card-danger { border-color: #ef9a9a; }
.db-tool-card h3 { margin-top: 0; font-size: 0.95rem; display: flex; align-items: center; gap: 8px; }
.db-tool-card p  { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 12px; }

.tool-badge {
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.05em;
  padding: 1px 6px; border-radius: 999px;
}
.tool-fast   { background: #e8f5e9; color: #2e7d32; }
.tool-slow   { background: #fff3e0; color: #e65100; }
.tool-danger { background: #ffebee; color: #c62828; }

.db-tool-result {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: var(--radius);
  font-size: 0.82rem;
  line-height: 1.5;
}
.db-tool-result pre { margin: 4px 0 0; white-space: pre-wrap; font-size: 0.75rem; }
.db-tool-running { background: var(--surface-alt); color: var(--text-muted); }
.db-tool-ok      { background: #e8f5e9; color: #1b5e20; }
.db-tool-error   { background: #ffebee; color: #b71c1c; }
.btn-danger {
  background: #d32f2f; color: #fff; border: none;
  padding: 6px 14px; border-radius: var(--radius); cursor: pointer; font-weight: 600;
}
.btn-danger:hover { background: #b71c1c; }
```

---

## Tests

### Stop Controller — `tests/test_stop_controller.py` (NEW)

- `should_stop()` returns `False` by default
- `request_stop()` sets flag, returns stopped jobs list
- `reset_stop()` clears flag
- Registered task is cancelled when `request_stop()` called
- Unregistered task is not in registry after `unregister_task()`
- `get_stop_state()` returns correct structure

### Active Jobs — `tests/test_active_jobs.py` (NEW)

- `GET /api/admin/active-jobs` returns correct shape (admin auth)
- `POST /api/admin/stop-all` sets stop flag and returns stopped list
- `POST /api/admin/reset-stop` clears stop flag
- `GET /api/admin/stop-state` returns current flag state
- Worker respects `should_stop()` mid-scan (mock bulk_scanner with 200 files, inject stop at file 50)

### DB Tools — add to `tests/test_admin.py`

- `POST /api/db/health-check` → 200, has `quick_check_ok`, `db_size_mb`, `row_counts`
- `POST /api/db/integrity-check` → 200, `{"ok": true, "errors": []}`
- `POST /api/db/repair` with active jobs → returns error (don't repair while running)
- `POST /api/db/repair` with no active jobs → 200, `ok: true`, backup path present

---

## Done Criteria

### Stop Controls
- [ ] `POST /api/admin/stop-all` sets global flag, cancels registered tasks
- [ ] Bulk worker stops after current file when flag is set
- [ ] Bulk scanner stops file walk when flag is set
- [ ] Lifecycle scanner stops walk when flag is set
- [ ] New bulk job creation calls `reset_stop()` before starting
- [ ] `POST /api/admin/reset-stop` clears the flag

### Global Status Bar
- [ ] Bar appears at bottom of every listed page when any job is running
- [ ] Bar hidden when no jobs running and no stop requested
- [ ] Bar shows job count and summary counts
- [ ] STOP ALL button triggers confirmation then calls stop API
- [ ] "Stop requested" banner appears after stop, with Reset button
- [ ] Bar polls every 5s (active), 30s (hidden tab)
- [ ] Body has enough bottom padding that bar doesn't cover page content

### Active Jobs Panel
- [ ] Opens from "View Jobs" button on status bar
- [ ] Shows all active bulk jobs with status badge, paths, progress bar, counters
- [ ] Shows job options (fidelity tier, OCR enabled, etc.)
- [ ] Shows active workers with current filenames
- [ ] Shows per-directory progress breakdown
- [ ] "Stop" button on each active job calls cancel endpoint
- [ ] "Stop All Jobs" button at top of panel calls stop-all
- [ ] Panel closes on Escape, backdrop click, ✕ button
- [ ] Panel refreshes every 2s while open
- [ ] Lifecycle scan card shown with progress and ETA

### Admin DB Tools
- [ ] Health Check runs in < 2 seconds, shows structural OK/fail, WAL size, row counts
- [ ] Integrity Check runs (may be slow), shows "No errors found" or lists errors
- [ ] Repair Database: blocked if jobs running, confirmation required, backup path shown
- [ ] All three show loading state during run, then result

### Locations Flag
- [ ] Yellow banner visible at top of locations.html
- [ ] No functional changes to Locations
- [ ] `LOCATIONS_UX_REDESIGN` token in CLAUDE.md

### Tests
- [ ] All existing tests still pass
- [ ] Stop controller unit tests pass
- [ ] Active jobs endpoint tests pass
- [ ] DB tools tests pass

---

## CLAUDE.md Updates

After implementation:

- Add `v0.9.x` status line: "Global stop controls, active jobs panel, admin DB tools, locations flagged for UX redesign"
- Add to Key Files:
  - `core/stop_controller.py` — global stop flag, task registry, should_stop() / request_stop() / reset_stop()
  - `static/js/global-status-bar.js` — persistent floating bar, polls active-jobs, STOP ALL button
  - `static/js/active-jobs-panel.js` — slide-in panel with per-job detail, per-dir progress, individual stop
- Add gotchas:
  - **Stop is cooperative, not instant**: `request_stop()` cancels asyncio tasks and sets a flag. Workers check the flag before each file. A worker mid-conversion will finish that file before stopping. Hard kill (`SIGKILL`) is not used — it would corrupt the SQLite WAL. If a worker is hung on a single file, the only option is container restart.
  - **`dir_stats` tracks top-level directories only**: tracking the full directory tree would create an unbounded dict on deep repositories. Top-level subdirectories only. Full tree tracking is a future enhancement.
  - **`reset_stop()` must be called before starting new jobs**: If the stop flag is set and not reset, new bulk jobs will immediately stop at the first file. `POST /api/bulk/jobs` calls reset automatically. Manual reset available at `POST /api/admin/reset-stop`.
  - **DB repair acquires exclusive lock**: All in-flight requests will queue or fail during the dump-and-restore. Expected duration: 5–60 seconds depending on DB size. This is intentional — partial writes during repair would corrupt the output.
  - **`LOCATIONS_UX_REDESIGN`**: grep this token when ready to redesign the Locations page. See gotcha added in this patch for scope notes.
