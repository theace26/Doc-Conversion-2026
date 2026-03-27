# MarkFlow Patch — "Stop Requested" Banner Never Clears

**Scope:** Two small frontend edits  
**Files touched:** `static/status.html`, `static/js/global-status-bar.js`  
**Risk:** Low — UI only, no backend changes

---

## Root Cause

The reset button on `status.html` calls the API correctly (`POST /api/admin/reset-stop`
returns `ok: true`) but the banner never disappears because:

1. `poll()` re-fetches status and re-renders the banner based on the current
   `stop_requested` value — **but the banner hide/show logic isn't reacting to the
   cleared flag correctly**, OR `poll()` runs before the flag is committed.
2. `global-status-bar.js` has **no reset handler at all** — it renders the banner
   on every page but has no way to clear it from other pages.

---

## Fix 1 — `static/status.html` (line ~292)

### What to find

```javascript
document.getElementById('reset-stop-btn').addEventListener('click', async function () {
  await fetch('/api/admin/reset-stop', { method: 'POST' });
  showToast('Stop flag cleared');
  poll();
});
```

### Replace with

```javascript
document.getElementById('reset-stop-btn').addEventListener('click', async function () {
  const res = await fetch('/api/admin/reset-stop', { method: 'POST' });
  if (res.ok) {
    showToast('Stop flag cleared');
    // Hide the banner immediately — don't wait for the next poll cycle
    const banner = document.getElementById('stop-banner');
    if (banner) banner.style.display = 'none';
    // Then let poll refresh the full page state
    poll();
  } else {
    showToast('Reset failed — check logs', 'error');
  }
});
```

> **Note:** The banner element ID may be different. Before making this edit,
> check what ID or class wraps the yellow banner div near line 19:
> ```
> grep -n "stop-banner\|winding" static/status.html | head -20
> ```
> Use whatever ID/class is on that outer `<div>` in the `style.display = 'none'` line.

---

## Fix 2 — `static/js/global-status-bar.js`

This file renders the banner on every page but has no reset handler. Find where it
renders the stop-requested banner and add a click handler on the reset button it
renders.

### Step 1 — Read the file first

```bash
cat static/js/global-status-bar.js
```

### Step 2 — Find where the banner HTML is injected

Look for where it builds the banner string or element, something like:

```javascript
if (data.stop_requested) {
    // renders banner HTML with the reset button
}
```

### Step 3 — Add a click handler after the banner is injected

The pattern to add after the banner element is inserted into the DOM:

```javascript
const globalResetBtn = document.getElementById('reset-stop-btn');
if (globalResetBtn && !globalResetBtn.dataset.bound) {
  globalResetBtn.dataset.bound = 'true'; // prevent double-binding on repeat polls
  globalResetBtn.addEventListener('click', async function () {
    const res = await fetch('/api/admin/reset-stop', { method: 'POST' });
    if (res.ok) {
      const banner = document.getElementById('stop-banner'); // adjust ID as needed
      if (banner) banner.style.display = 'none';
    }
  });
}
```

> The `dataset.bound` guard is important — `global-status-bar.js` likely runs on
> every poll tick, which would stack duplicate event listeners without it.

---

## Verify

After making both edits, test end-to-end:

1. Trigger a stop via the UI or:
   ```powershell
   Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/admin/stop-all"
   ```
2. Confirm the yellow banner appears
3. Click **Reset & allow new jobs**
4. Banner should disappear immediately without a page reload
5. Check other pages (Bulk Jobs, History) — banner should also be gone there

---

## Do NOT change

- `core/stop_controller.py` — backend logic is correct
- `api/routes/admin.py` — reset endpoint works
- Any bulk job or lifecycle scanner logic
