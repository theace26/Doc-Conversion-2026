# MarkFlow Patch: Active File Display in Bulk Progress
# Version: patch-0.7.4c
# Scope: Frontend only — static/bulk.html and static/app.js only.
# No Python changes, no database changes, no API changes.
# Run AFTER patch-0.7.4b (path safety) is complete.

---

## 0. Read First

Load `CLAUDE.md` before writing anything. Confirm the following before starting:
- `bulk_worker_count` preference exists in `_PREFERENCE_SCHEMA`
- `file_start` SSE event is already emitted by `bulk_worker.py` with `filename`
  and `worker_id` fields
- `file_converted` / `file_failed` / `file_skipped` SSE events are already emitted

This patch is **frontend only**. The SSE events needed already exist.
The `worker_count` value is already in the job record from
`GET /api/bulk/jobs/{job_id}`.

If any of the above are missing, fix the backend gap first before proceeding
with this patch.

---

## 1. What This Patch Adds

A collapsible "Currently Converting" panel below the progress bar on `bulk.html`.
It shows one row per active worker — up to N rows, where N equals the worker count
configured in Settings. Each row shows the filename currently being processed by
that worker.

```
████████████████░░░░░░  21,450 / 56,450  (38%)

▼ Currently converting  (click to collapse)
  ⟳  dept/finance/Q4_Report.pdf          worker 1
  ⟳  dept/hr/policies/handbook.docx      worker 2
  ⟳  dept/legal/contracts/NDA_2026.pdf   worker 3
  ⟳  dept/it/infrastructure_plan.pptx    worker 4
```

The panel is expanded by default and can be collapsed. The collapsed state
is remembered in `localStorage` across page refreshes.

---

## 2. Preference — `bulk_active_files_visible`

### `api/routes/preferences.py` (modify)

Add one new preference to `_PREFERENCE_SCHEMA`:

| Key | Type | Default | Label |
|-----|------|---------|-------|
| `bulk_active_files_visible` | toggle | `true` | Show active files during bulk conversion |

This controls whether the "Currently converting" panel is shown at all.
When `false`, the panel is hidden entirely (not just collapsed).

This preference is already exposed via the existing preferences API — no new
endpoint needed. Add it to the Settings UI in the Bulk section.

### `static/settings.html` (modify)

In the **Bulk** settings section, add the toggle after the worker count setting:

```
Show active files during conversion   [ ON ]
  Display which files each worker is currently processing.
```

---

## 3. Frontend — `static/bulk.html` (modify)

### 3.1 Active files state

Add a module-level state object to track what each worker is currently doing:

```javascript
// Keyed by worker_id (integer 1..N)
// Value: { filename, relativePath, startedAt } or null if worker is idle
const activeWorkers = {};
let workerCount = 4; // updated from job record on load
```

### 3.2 Wire up SSE events

In the existing SSE event handler, add handling for `file_start`,
`file_converted`, `file_failed`, `file_skipped`, and `file_skipped_for_review`:

```javascript
// file_start: a worker has picked up a new file
source.addEventListener("file_start", (e) => {
    const data = JSON.parse(e.data);
    // data shape: { file_id, filename, relative_path, worker_id, index, total }
    activeWorkers[data.worker_id] = {
        filename: data.filename,
        relativePath: data.relative_path,
        startedAt: Date.now()
    };
    renderActiveWorkers();
    updateProgressBar(data.index, data.total);
});

// file_converted / file_failed / file_skipped / file_skipped_for_review:
// worker finished — clear its slot
["file_converted", "file_failed", "file_skipped",
 "file_skipped_for_review"].forEach(eventName => {
    source.addEventListener(eventName, (e) => {
        const data = JSON.parse(e.data);
        if (data.worker_id !== undefined) {
            activeWorkers[data.worker_id] = null;
        }
        renderActiveWorkers();
        updateCounters(data);
    });
});
```

**Note on `worker_id` in existing SSE events**: Check whether the existing
`file_converted` / `file_failed` events already include `worker_id`. If they do
not, add it to the SSE event data in `core/bulk_worker.py`. This is the only
backend change allowed in this patch — adding `worker_id` to existing events
that are missing it. Do not add new event types.

### 3.3 Render function

```javascript
function renderActiveWorkers() {
    const container = document.getElementById("active-workers-list");
    if (!container) return;

    // Check preference — if hidden, don't render
    if (!getPreference("bulk_active_files_visible", true)) {
        document.getElementById("active-workers-panel").style.display = "none";
        return;
    }

    // Build rows — one per worker slot (1..workerCount)
    // Show all slots, idle slots show as "—"
    const rows = [];
    for (let i = 1; i <= workerCount; i++) {
        const worker = activeWorkers[i];
        if (worker) {
            rows.push(`
                <div class="active-worker-row active-worker-row--busy">
                    <span class="spinner" aria-hidden="true"></span>
                    <span class="active-worker-path"
                          title="${escapeHtml(worker.relativePath)}">
                        ${escapeHtml(truncatePath(worker.relativePath, 60))}
                    </span>
                    <span class="active-worker-label">worker ${i}</span>
                </div>
            `);
        } else {
            rows.push(`
                <div class="active-worker-row active-worker-row--idle">
                    <span class="active-worker-idle-dot" aria-hidden="true">·</span>
                    <span class="active-worker-path active-worker-path--idle">idle</span>
                    <span class="active-worker-label">worker ${i}</span>
                </div>
            `);
        }
    }

    container.innerHTML = rows.join("");
}
```

**`truncatePath(path, maxChars)`** — helper that truncates long paths from the
left, keeping the filename always visible:

```javascript
function truncatePath(path, maxChars) {
    if (path.length <= maxChars) return path;
    // Keep last maxChars chars, prefix with "…/"
    const truncated = path.slice(-(maxChars - 2));
    // Find first "/" in truncated string to avoid cutting mid-folder-name
    const slashIdx = truncated.indexOf("/");
    return "…/" + (slashIdx >= 0 ? truncated.slice(slashIdx + 1) : truncated);
}
```

Example:
```
dept/finance/Q4_Report.pdf                    → dept/finance/Q4_Report.pdf  (fits)
very/long/nested/path/to/some/document.pdf   → …/path/to/some/document.pdf (truncated)
```

**`getPreference(key, defaultValue)`** — check the preference from the already-loaded
preferences object (fetched on page load). Fall back to `defaultValue` if not set.

### 3.4 HTML structure to add

Add this block immediately below the progress bar in `bulk.html`, inside the active
job section. It is only rendered when a job is running or scanning:

```html
<!-- Active workers panel -->
<div id="active-workers-panel" class="active-workers-panel" style="display:none">
    <button class="active-workers-toggle" id="active-workers-toggle"
            aria-expanded="true" aria-controls="active-workers-list">
        <span class="active-workers-toggle-icon">▼</span>
        Currently converting
    </button>
    <div id="active-workers-list" class="active-workers-list">
        <!-- Populated by renderActiveWorkers() -->
    </div>
</div>
```

Show the panel (`style="display:block"`) when the first `file_start` event is received.
Hide it again when `job_complete` is received and all workers are idle.

### 3.5 Collapse toggle

```javascript
const toggle = document.getElementById("active-workers-toggle");
const list   = document.getElementById("active-workers-list");

// Restore collapsed state from localStorage
const collapsed = localStorage.getItem("bulk-workers-collapsed") === "true";
if (collapsed) {
    list.style.display = "none";
    toggle.setAttribute("aria-expanded", "false");
    toggle.querySelector(".active-workers-toggle-icon").textContent = "▶";
}

toggle.addEventListener("click", () => {
    const isExpanded = toggle.getAttribute("aria-expanded") === "true";
    const nowExpanded = !isExpanded;
    list.style.display = nowExpanded ? "block" : "none";
    toggle.setAttribute("aria-expanded", String(nowExpanded));
    toggle.querySelector(".active-workers-toggle-icon")
          .textContent = nowExpanded ? "▼" : "▶";
    localStorage.setItem("bulk-workers-collapsed", String(!nowExpanded));
});
```

### 3.6 Worker count from job record

When a bulk job is started or the page loads with an active job, fetch the job record
to get `worker_count`:

```javascript
async function loadJobAndSetWorkerCount(jobId) {
    const job = await apiFetch(`/api/bulk/jobs/${jobId}`);
    workerCount = job.worker_count || 4;
    // Pre-populate activeWorkers with null slots
    for (let i = 1; i <= workerCount; i++) {
        activeWorkers[i] = activeWorkers[i] ?? null;
    }
    renderActiveWorkers();
}
```

Call this after receiving the job_id from `POST /api/bulk/jobs` and also on page
load if a job_id is present in the URL.

---

## 4. CSS — `static/markflow.css` (modify)

Add styles for the active workers panel. Use existing CSS variables — no new colors.

```css
/* Active workers panel */
.active-workers-panel {
    margin-top: var(--space-sm, 8px);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    overflow: hidden;
}

.active-workers-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 8px 12px;
    background: none;
    border: none;
    cursor: pointer;
    font: inherit;
    font-size: 0.85rem;
    color: var(--text-muted);
    text-align: left;
}

.active-workers-toggle:hover {
    background: var(--surface-alt);
}

.active-workers-toggle-icon {
    font-size: 0.7rem;
    transition: transform var(--transition);
}

.active-workers-list {
    padding: 4px 0 8px 0;
}

.active-worker-row {
    display: grid;
    grid-template-columns: 20px 1fr auto;
    align-items: center;
    gap: 8px;
    padding: 4px 12px;
    font-family: var(--font-mono);
    font-size: 0.8rem;
}

.active-worker-row--busy {
    color: var(--text);
}

.active-worker-row--idle {
    color: var(--text-muted);
    opacity: 0.5;
}

.active-worker-path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;         /* required for text-overflow in grid */
}

.active-worker-path--idle {
    font-style: italic;
}

.active-worker-label {
    font-size: 0.75rem;
    color: var(--text-muted);
    white-space: nowrap;
}

.active-worker-idle-dot {
    text-align: center;
    color: var(--text-muted);
}
```

---

## 5. Scan Phase Behavior

During the scan phase (before `scan_complete` is received), `file_start` events
are not emitted yet. The active workers panel should not be shown during scanning.

Show the panel only after `scan_complete` is received AND the first `file_start`
event arrives. During scan, the progress area shows:

```
⟳ Scanning...   84,231 files found so far
[indeterminate progress bar animation]
```

This behavior should already exist — confirm it does and do not change it.

---

## 6. After Job Completes

When `job_complete` SSE event is received:
- Clear all `activeWorkers` slots to null
- Call `renderActiveWorkers()` one final time (all rows show "idle")
- After 2 seconds, hide the panel entirely with a CSS fade-out

```javascript
source.addEventListener("job_complete", (e) => {
    // ... existing handler code ...
    Object.keys(activeWorkers).forEach(k => activeWorkers[k] = null);
    renderActiveWorkers();
    setTimeout(() => {
        const panel = document.getElementById("active-workers-panel");
        if (panel) {
            panel.style.transition = "opacity 0.5s";
            panel.style.opacity = "0";
            setTimeout(() => panel.style.display = "none", 500);
        }
    }, 2000);
});
```

---

## 7. Done Criteria

- [ ] Active workers panel appears below progress bar when job starts
- [ ] One row per worker (matches `worker_count` from job record)
- [ ] Busy rows show spinner + truncated path + "worker N" label
- [ ] Idle rows show "·  idle  worker N" in muted style
- [ ] Long paths truncated from left, filename always visible
- [ ] Full path shown in `title` tooltip on hover
- [ ] Collapse toggle works, state persists in localStorage across refresh
- [ ] Panel is hidden when `bulk_active_files_visible` preference is false
- [ ] Settings page has "Show active files" toggle in Bulk section
- [ ] Panel fades out 2 seconds after job completes
- [ ] Panel does not appear during scan phase (only after first `file_start`)
- [ ] Worker count matches the value set in Settings
- [ ] No console errors during normal operation
- [ ] All prior tests still passing (no Python changes to break anything)

---

## 8. CLAUDE.md Update

Add to Current Status:

```markdown
**patch-0.7.4c** — Active file display in bulk progress. Collapsible panel shows
  one row per worker with current filename. Worker count matches Settings value.
  Collapse state persists. Hidden when preference is off.
```

Add to Gotchas:

```markdown
- **worker_id in SSE events**: `file_start` events must include `worker_id` (int 1..N)
  for the active file display to work. If `file_converted`/`file_failed` events were
  missing worker_id, they were patched in this changeset. Check bulk_worker.py if
  worker slots don't clear correctly after a file finishes.

- **truncatePath() trims from left**: Long paths are trimmed from the directory
  portion, not the filename. The filename is always fully visible. The prefix "…/"
  indicates truncation occurred.

- **active-workers-panel display:none by default**: The panel starts hidden in HTML
  and is shown by JS after the first file_start event. This prevents a flash of
  empty worker rows during page load and during the scan phase.
```

No version tag needed — this is a UI-only patch.

---

## 9. Output Cap Note

Single turn. All changes are in:
- `static/bulk.html` (HTML structure + JS)
- `static/markflow.css` (styles)
- `static/settings.html` (one toggle in Bulk section)
- `api/routes/preferences.py` (one preference added to schema)
- `core/bulk_worker.py` (add `worker_id` to SSE events if missing — check first)
