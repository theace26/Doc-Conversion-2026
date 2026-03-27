# MarkFlow — Status Page & Nav Redesign Prompt

> Target version: **v0.9.4**
> Scope: UI-only. No new API endpoints, no backend changes, no new tests required
> (existing tests for stop_controller and active-jobs remain valid — nothing is removed from the API).

---

## Context

Read `CLAUDE.md` before starting. Current relevant files:

| File | What it does today |
|------|--------------------|
| `static/js/global-status-bar.js` | Floating bar injected into every page — polls `/api/admin/active-jobs`, shows job count and STOP ALL button |
| `static/js/active-jobs-panel.js` | Slide-in panel triggered from the floating bar — per-job detail, progress bars, per-dir stats, individual stop buttons |
| `static/app.js` | Shared JS — `buildNav()` builds the top nav dynamically from role |
| `static/markflow.css` | Design system — CSS variables, card styles, dark mode |

All HTML pages include both JS files via `<script>` tags and render the floating bar + panel.

---

## What to Build

### 1. New page — `static/status.html`

A dedicated status page. This becomes the permanent home for everything that currently lives in the floating bar and slide-in panel.

**Layout (top → bottom):**

```
┌─────────────────────────────────────────────────────┐
│  Page header: "Active Jobs"                         │
│  Subtitle: "N jobs running" (live count)            │
│  [ STOP ALL ] button  (right-aligned, danger style) │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  JOB CARD — one per active/recent job               │
│  ┌─ job name / source path (truncated)              │
│  │  Status badge (running / paused / done / failed) │
│  │  ████████░░░░  68%  — X files done / Y total     │
│  │  ✓ converted  ✗ failed  ⟳ skipped  ? unrecognized│
│  │  Active workers (if running):                    │
│  │    Worker 1 → current-filename.docx              │
│  │    Worker 2 → another-file.pdf                   │
│  │  [ ⏸ Pause ]  [ ⏹ Stop ]  (right-aligned)       │
│  └──────────────────────────────────────────────────┘
│  (next card stacks below with gap)                  │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  LIFECYCLE SCANNER CARD                             │
│  Last scan: 3 min ago  |  Status: idle / running    │
│  (progress bar if scan in flight)                   │
└─────────────────────────────────────────────────────┘
```

**Behavior:**
- Polls `GET /api/admin/active-jobs` every **3 seconds** while page is visible (`document.visibilityState`)
- Pauses polling when tab is hidden, resumes on `visibilitychange`
- Cards are rebuilt from API response on each poll (simple full re-render — no diffing needed)
- If no active jobs: show an empty-state card — "No active jobs. Everything is quiet."
- **STOP ALL** button: calls `POST /api/admin/stop-all`, shows a confirmation toast, disables itself for 3s to prevent double-click
- **Individual Pause/Resume**: calls existing `POST /api/bulk/jobs/{id}/pause` and `POST /api/bulk/jobs/{id}/resume`
- **Individual Stop**: calls `POST /api/bulk/jobs/{id}/cancel` with a brief confirm (inline "Are you sure?" row replaces the buttons for 3s)
- Lifecycle scanner card polls `GET /api/scanner/progress` every 3s. If `running: true`, show an indeterminate progress bar (or % if `pct` is non-null). If idle, show last-scan time.
- Page uses `markflow.css` design system. Cards use the existing `.card` class pattern.
- Dark mode inherits automatically (CSS variables already handle it).

**Card CSS spec** (implement in `markflow.css` — add to the design system):
```css
/* Job status card */
.job-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem 1.5rem;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.job-card + .job-card { margin-top: 1rem; }
.job-card__header { display: flex; justify-content: space-between; align-items: flex-start; }
.job-card__title { font-weight: 600; font-size: 1rem; }
.job-card__path { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.15rem; word-break: break-all; }
.job-card__progress { height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; }
.job-card__progress-fill { height: 100%; background: var(--accent); transition: width 0.4s ease; }
.job-card__counts { display: flex; gap: 1rem; font-size: 0.8rem; flex-wrap: wrap; }
.job-card__workers { font-size: 0.8rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem; }
.job-card__worker-row { display: flex; gap: 0.5rem; align-items: center; }
.job-card__worker-id { color: var(--accent); font-variant-numeric: tabular-nums; min-width: 4.5rem; }
.job-card__actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
```

---

### 2. Redesign `static/js/global-status-bar.js` — Nav badge only

**Remove** all floating-bar DOM injection. The bar is gone. Replace with a single exported function that updates a badge in the nav:

```javascript
// global-status-bar.js — v2
// No longer injects a floating bar.
// Exports: initStatusBadge() — call once per page after nav is built.

export function initStatusBadge() {
  // Find the "Status" nav link injected by buildNav()
  // Poll /api/admin/active-jobs every 5s
  // Update the badge count on the nav link
  // If count > 0: badge visible, pulsing dot indicator
  // If count === 0: badge hidden
}
```

Implementation details:
- `initStatusBadge()` is called from `app.js` **after** `buildNav()` completes
- The badge is a `<span class="nav-badge">N</span>` injected inside the Status `<a>` tag
- CSS: small filled pill, accent color, positioned top-right of the nav link
- If the stop flag is set (check `stop_requested` field on the active-jobs response), add class `nav-badge--stopped` (red color) to the badge
- Polling uses `setInterval` — pauses when `document.hidden`, resumes on `visibilitychange`

**Remove from every HTML page:** the `<script src="/js/active-jobs-panel.js">` and `<script src="/js/global-status-bar.js">` inline includes. These will be loaded only via `app.js` module import.

---

### 3. Retire `static/js/active-jobs-panel.js`

The slide-in panel is replaced by `status.html`. You have two choices — pick the cleaner one:

**Option A (preferred):** Delete the file. Remove all references across all HTML pages. The functionality fully lives in `status.html` now.

**Option B:** Gut the panel to a stub that simply redirects to `status.html` if somehow called. Only use this if deleting the file would break something unexpected.

---

### 4. Update `static/app.js` — `buildNav()` adds Status link

Add a "Status" entry to the nav. It should:
- Always be visible (every role can view job status — it's read-only info for non-admins)
- Have `href="/status.html"`
- Include an empty `<span class="nav-badge" style="display:none"></span>` inside the `<a>` tag — this is the target for `initStatusBadge()`
- Appear between the last functional nav item and the right-side items (or wherever it fits cleanly in your existing nav order)

After `buildNav()` resolves, call `initStatusBadge()`:
```javascript
import { initStatusBadge } from '/js/global-status-bar.js';

async function buildNav() {
  // ... existing nav build logic ...
  initStatusBadge(); // wire up badge polling after nav exists in DOM
}
```

Nav badge CSS (add to `markflow.css`):
```css
.nav-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.1rem;
  height: 1.1rem;
  padding: 0 0.3rem;
  border-radius: 999px;
  background: var(--accent);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 1;
  margin-left: 0.35rem;
  vertical-align: middle;
}
.nav-badge--stopped {
  background: var(--danger);
  animation: pulse 1s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
```

---

### 5. Update all HTML pages — remove old script includes

Every `static/*.html` page currently has something like:
```html
<script src="/js/global-status-bar.js"></script>
<script src="/js/active-jobs-panel.js"></script>
```

Remove both script tags from **every** page. The badge polling is now initiated by `app.js` (which all pages already load), so no per-page wiring is needed.

Pages to audit and clean up:
- `index.html`, `progress.html`, `history.html`, `settings.html`, `search.html`
- `bulk.html`, `bulk-review.html`, `locations.html`, `review.html`
- `debug.html`, `admin.html`, `trash.html`, `db-health.html`, `unrecognized.html`
- `providers.html`

Also remove any DOM containers that the old scripts injected (e.g. `<div id="global-status-bar">`, `<div id="active-jobs-panel">`) if they were hardcoded into the HTML.

---

### 6. Register `status.html` — add to FastAPI static mount

`status.html` is served from `static/` via the existing `StaticFiles` mount — no new route needed. Verify the mount in `main.py`:
```python
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```
This already serves any `.html` file in `static/` at its name. No changes needed unless your mount is different.

---

## Files to Create

| File | Action |
|------|--------|
| `static/status.html` | **Create** — new status page |
| `static/js/global-status-bar.js` | **Rewrite** — strip floating bar, keep only badge init |
| `static/js/active-jobs-panel.js` | **Delete** (or stub) |

## Files to Modify

| File | Change |
|------|--------|
| `static/app.js` | Add Status nav entry, call `initStatusBadge()` after `buildNav()` |
| `static/markflow.css` | Add `.job-card` styles + `.nav-badge` styles |
| All `static/*.html` pages | Remove old `<script>` tags for the two retired JS files |

## Files NOT to touch

Everything in `api/`, `core/`, `tests/`, `mcp_server/`. This is a pure frontend change.

---

## Done Criteria

- [ ] `GET /status.html` loads cleanly, no 404
- [ ] Status page shows one card per active bulk job, auto-refreshes every 3s
- [ ] STOP ALL button on status page calls `/api/admin/stop-all` and shows toast
- [ ] Individual Pause / Stop buttons work from status page cards
- [ ] Lifecycle scanner card shows on status page, shows progress bar when scan is running
- [ ] Empty state renders when no jobs are running
- [ ] Every page's top nav shows a "Status" link
- [ ] Nav badge shows active job count when > 0
- [ ] Nav badge pulses red when stop has been requested
- [ ] Nav badge hides when count is 0
- [ ] No floating bar appears on any page
- [ ] No slide-in panel appears on any page
- [ ] Old script tags (`global-status-bar.js`, `active-jobs-panel.js`) are gone from all HTML pages
- [ ] Dark mode works correctly on status page (inherits CSS variables)
- [ ] Tab-hidden polling pause works (no wasted requests on background tabs)
- [ ] All existing tests still pass (no backend was changed)

---

## Version Tag

After completing all done criteria, update `CLAUDE.md`:

```
**v0.9.4** — Status page & nav redesign. Floating global-status-bar and
  slide-in active-jobs-panel replaced by dedicated /status.html with
  stacked per-job cards. STOP ALL button and individual job controls
  live on status page. Nav gains "Status" link with active-job count
  badge (pulses red when stop requested). global-status-bar.js rewritten
  to badge-only; active-jobs-panel.js retired.
```

Tag: `git tag v0.9.4`
