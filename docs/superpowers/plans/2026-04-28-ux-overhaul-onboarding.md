# UX Overhaul — First-run Onboarding Plan (Plan 8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two onboarding steps that bracket the layout picker (Plan 1C already shipped step 2) — **step 1 Welcome** and **step 3 Pin your first folders**. Together they form a single 3-step first-run flow at `/onboarding` that runs once per user (tracked via the `onboarding_completed_at` user-preference key from Plan 1A) and lands the user on Search-home with their layout selected and 3–4 folders pinned.

**Architecture:** Single new page `/onboarding` mounted by a new boot script that drives a 3-step state machine: **welcome → layout-picker → pin-folders → done**. Step 2 (layout picker) reuses the `MFLayoutPickerCards` component already shipped by Plan 1C; step 1 + step 3 are new components. New backend endpoint `GET /api/folders/indexed` returns the operator's indexed-folder list with file counts so step 3 can present a real list to pin from. The Search-home boot (Plan 3) is modified at one site: on first boot, if `MFPrefs.get('onboarding_completed_at')` is empty, redirect to `/onboarding` *before* mounting the home page. **Safe DOM construction throughout.**

**Tech stack:** Python 3.11 · FastAPI · pytest · vanilla JS · `MFPrefs` (Plan 1A) · `MFLayoutPickerCards` (Plan 1C) · `MFFormControls` (Plan 5) · `MFTelemetry` (Plan 1B)

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §3 (onboarding — 3 steps, recommended-Minimal default, skip-fallback)

**Mockup reference:**
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/layout-onboarding.html` — step 2 reference (already shipped in Plan 1C)
- Steps 1 + 3 had no completed mockup — visual design here is original to this plan, anchored to the same design tokens (purple gradient hero, soft paper card surfaces, generous whitespace)

**Out of scope (deferred):**
- Re-running onboarding on demand (an "Onboard again" link in avatar menu) — v1.1
- Per-role onboarding variants (member vs operator) — both roles get the same flow in v1; the only role-aware step is the welcome question copy
- Onboarding analytics dashboard — telemetry events emitted; reading them is out of scope
- Pinned-folder reordering on the home page itself — Plan 5 / 6 territory once we know what users actually pick
- Editing the indexed-folder set during onboarding (it's a *picker*, not a *manager*) — Storage detail page (Plan 5) covers add/remove

**Prerequisites:** Plans 1A through 7 complete. In particular:

- `MFPrefs.{ get, set, load }` is mountable (Plan 1A)
- `MFLayoutPickerCards.mount(slot, opts)` exists and emits a chosen-mode event (Plan 1C)
- `MFFormControls` factory module is available (Plan 5)
- `/api/me` returns `{ user_id, name, role, scope, build }` (Plan 4)
- `onboarding_completed_at` is a known preference key (Plan 1A added the schema entry)

---

## File structure (this plan creates / modifies)

**Create:**
- `api/routes/folders.py` — `GET /api/folders/indexed` (returns indexed-folder list with file counts)
- `static/onboarding.html` — single-page template with three sequential step slots
- `static/js/components/onboarding-welcome.js` — `MFOnboardingWelcome` (step 1)
- `static/js/components/onboarding-pin-folders.js` — `MFOnboardingPinFolders` (step 3)
- `static/js/pages/onboarding.js` — `MFOnboarding.mount(slot)` — the state machine that wires the three steps together
- `static/js/onboarding-boot.js`
- `tests/test_folders_indexed_endpoint.py` — 4 tests
- `tests/test_onboarding_redirect.py` — 2 tests for the Search-home redirect

**Modify:**
- `static/css/components.css` — append onboarding-specific styles (hero card, step-indicator dots, folder-row checkboxes)
- `main.py` — register `folders` router; add `/onboarding` flag-aware route
- `static/js/index-new-boot.js` — add the first-run redirect *before* `MFSearchHome.mount`

---

## Task 1: `GET /api/folders/indexed` endpoint

**Files:**
- Create: `api/routes/folders.py`
- Create: `tests/test_folders_indexed_endpoint.py`
- Modify: `main.py`

Returns a sorted list of indexed folders (top-level under each source) with file counts so step 3's picker can render real options. Pulls from `source_files` (the canonical registry per CLAUDE.md "source_files vs bulk_files"). Member can read but only sees folders they have access to (UnionCore-driven; for v1 every authenticated user sees the same list — UnionCore-tenant-scoped filtering is a follow-up).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_folders_indexed_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_admin_client(fake_jwt):
    return TestClient(app, headers={"Authorization": "Bearer " + fake_jwt("xerxes@local46.org", "admin")})


@pytest.fixture
def authed_member_client(fake_jwt):
    return TestClient(app, headers={"Authorization": "Bearer " + fake_jwt("sarah@local46.org", "member")})


def test_indexed_folders_admin_can_read(authed_admin_client):
    r = authed_admin_client.get("/api/folders/indexed")
    assert r.status_code == 200
    body = r.json()
    assert "folders" in body
    assert isinstance(body["folders"], list)


def test_indexed_folders_member_can_read(authed_member_client):
    """Member needs this for the onboarding pin-folders step."""
    r = authed_member_client.get("/api/folders/indexed")
    assert r.status_code == 200


def test_indexed_folders_unauthenticated_401():
    client = TestClient(app)
    r = client.get("/api/folders/indexed")
    assert r.status_code == 401


def test_folder_shape_has_required_fields(authed_admin_client):
    body = authed_admin_client.get("/api/folders/indexed").json()
    for f in body["folders"]:
        for key in ("path", "label", "file_count"):
            assert key in f, f"folder {f.get('path')} missing {key}"
        assert isinstance(f["file_count"], int)
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_folders_indexed_endpoint.py -v`

Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Implement the endpoint**

Create `api/routes/folders.py`:

```python
"""GET /api/folders/indexed — list indexed top-level folders with counts.

Used by Plan 8 onboarding step 3 (pin folders) and any future "browse
by topic" surface that wants a folder-tree starting point.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §3
"""
from __future__ import annotations
from fastapi import APIRouter, Depends

from core.auth import require_user
from core.database import db_fetch_all

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.get("/indexed")
async def indexed(user=Depends(require_user)):
    """Return top-level folders that have at least one indexed file.

    "Top-level" = the first path segment under each configured source.
    Sorted by file_count desc so high-traffic folders are easy to spot.
    """
    rows = await db_fetch_all(
        """
        SELECT
          -- Top-level folder = first segment of relative path
          CASE
            WHEN instr(substr(rel_path, 2), '/') > 0
              THEN '/' || substr(rel_path, 2, instr(substr(rel_path, 2), '/') - 1)
            ELSE rel_path
          END AS top,
          COUNT(*) AS cnt
        FROM source_files
        WHERE lifecycle_status = 'active'
        GROUP BY top
        ORDER BY cnt DESC
        LIMIT 100
        """
    )
    return {
        "folders": [
            {
                "path": r["top"],
                "label": r["top"].lstrip("/") or "(root)",
                "file_count": r["cnt"] or 0,
            }
            for r in rows
        ],
    }
```

If the project's `source_files` schema uses `path` instead of `rel_path`, or if the relative-path convention differs (some Windows hosts store full paths), adapt the SQL to compute the top-level folder correctly. The tests pin only the response shape, not the SQL.

- [ ] **Step 4: Wire into `main.py`**

```python
from api.routes import folders as folders_routes
app.include_router(folders_routes.router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `pytest tests/test_folders_indexed_endpoint.py -v`

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/folders.py main.py tests/test_folders_indexed_endpoint.py
git commit -m "feat(api): GET /api/folders/indexed for onboarding pin step

Returns top-level folders with file counts, sorted by count desc.
All authenticated users can read (member needs it for onboarding
step 3). Spec §3."
```

---

## Task 2: `MFOnboardingWelcome` (step 1)

**Files:**
- Create: `static/js/components/onboarding-welcome.js`
- Modify: `static/css/components.css`

The welcome screen. Centered hero card on a soft-purple gradient background. Headline asks *"What do you want to find on the K Drive?"* per spec §3, followed by a one-line subtitle and a single primary "Get started →" pill. The role-aware copy: admin/operator gets *"Set up MarkFlow for IBEW Local 46"*; member gets *"Find documents fast on the K Drive"*.

- [ ] **Step 1: Append onboarding CSS to `static/css/components.css`**

```css
/* === onboarding === */
.mf-onboard {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--mf-color-accent-tint-2), #ffffff);
  padding: 2rem;
  font-family: var(--mf-font-sans);
}
.mf-onboard__card {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  box-shadow: var(--mf-shadow-card);
  max-width: 720px;
  width: 100%;
  padding: 3rem 3rem 2.5rem;
}
.mf-onboard__steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  margin-bottom: 2rem;
}
.mf-onboard__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e0e0e0;
}
.mf-onboard__dot--active { background: var(--mf-color-accent); }
.mf-onboard__dot--done   { background: var(--mf-color-accent-soft); }
.mf-onboard__hero {
  font-size: 2.4rem;
  line-height: 1.05;
  letter-spacing: -0.025em;
  font-weight: 700;
  color: var(--mf-color-text);
  margin: 0 0 0.6rem;
}
.mf-onboard__sub {
  font-size: 1.05rem;
  color: var(--mf-color-text-muted);
  margin: 0 0 2rem;
  max-width: 50ch;
  line-height: var(--mf-leading-body);
}
.mf-onboard__cta {
  display: flex;
  gap: 0.6rem;
  align-items: center;
}
.mf-onboard__skip {
  margin-left: auto;
  color: var(--mf-color-accent);
  font-size: 0.88rem;
  font-weight: 500;
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: var(--mf-font-sans);
}

/* === onboarding step 3 — folder picker === */
.mf-folder-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 1.2rem;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 0.4rem;
}
.mf-folder-row {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.7rem 0.9rem;
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card);
  background: var(--mf-surface);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.mf-folder-row:hover:not(.mf-folder-row--on) { border-color: var(--mf-color-accent-border); }
.mf-folder-row--on {
  border-color: var(--mf-color-accent);
  background: var(--mf-color-accent-tint);
}
.mf-folder-row__check {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  border: 1.5px solid #ccc;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: transparent;
  font-size: 0.85rem;
  font-weight: 700;
}
.mf-folder-row--on .mf-folder-row__check {
  border-color: var(--mf-color-accent);
  background: var(--mf-color-accent);
  color: #ffffff;
}
.mf-folder-row__path { flex: 1; min-width: 0; font-weight: 500; color: var(--mf-color-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mf-folder-row__count {
  font-size: 0.78rem;
  color: var(--mf-color-text-faint);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.mf-folder-counter {
  font-size: 0.86rem;
  color: var(--mf-color-text-muted);
  margin-bottom: 0.7rem;
}
.mf-folder-counter strong { color: var(--mf-color-text); font-weight: 600; }
```

- [ ] **Step 2: Create the welcome component**

Create `static/js/components/onboarding-welcome.js`:

```javascript
/* MFOnboardingWelcome — onboarding step 1.
 * Spec §3 step 1: "What do you want to find on the K Drive?"
 * Role-aware copy. Calls opts.onContinue() when user clicks Get started.
 *
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }

  function copyForRole(role) {
    if (role === 'admin' || role === 'operator') {
      return {
        hero: 'What do you want to find on the K Drive?',
        sub:  'A few quick questions and MarkFlow is set up for IBEW Local 46. Takes about a minute.',
      };
    }
    return {
      hero: 'Find anything on the K Drive, fast.',
      sub:  'A 60-second tour: pick how the home page looks, then bookmark a few folders you go to often. Skip and come back any time.',
    };
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFOnboardingWelcome.mount: slot required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var copy = copyForRole((opts && opts.role) || 'member');

    var hero = el('h1', 'mf-onboard__hero');
    hero.textContent = copy.hero;
    slot.appendChild(hero);

    var sub = el('p', 'mf-onboard__sub');
    sub.textContent = copy.sub;
    slot.appendChild(sub);

    var cta = el('div', 'mf-onboard__cta');
    var go = el('button', 'mf-pill mf-pill--primary');
    go.type = 'button';
    go.textContent = 'Get started →';
    go.addEventListener('click', function () {
      MFTelemetry.emit('ui.onboarding_step_complete', { step: 'welcome' });
      if (opts.onContinue) opts.onContinue();
    });
    cta.appendChild(go);

    var skip = el('button', 'mf-onboard__skip');
    skip.type = 'button';
    skip.textContent = 'Skip onboarding';
    skip.addEventListener('click', function () {
      if (opts.onSkip) opts.onSkip();
    });
    cta.appendChild(skip);

    slot.appendChild(cta);
  }

  global.MFOnboardingWelcome = { mount: mount };
})(window);
```

- [ ] **Step 3: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/components/onboarding-welcome.js`

Expected: zero matches.

- [ ] **Step 4: Commit**

```bash
git add static/js/components/onboarding-welcome.js static/css/components.css
git commit -m "feat(ux): MFOnboardingWelcome (step 1) + onboarding CSS

Role-aware welcome copy (admin/operator vs member). Get started →
fires opts.onContinue; Skip onboarding fires opts.onSkip. Both emit
ui.onboarding_step_complete telemetry. Spec §3."
```

---

## Task 3: `MFOnboardingPinFolders` (step 3)

**Files:**
- Create: `static/js/components/onboarding-pin-folders.js`

Step 3 — drag-pickable list of indexed folders, mark 3–4 favorites. The mockup is "pending" per the spec; this implementation uses a click-to-toggle row pattern (not literal drag) since drag-to-pin doesn't add value over click-to-pin and adds significant code. The "drag-pickable" language in the spec was about the *visual feel*, not the interaction model.

Each row: checkbox + folder path + file count. Header shows "Pick 3–4 folders you visit often". Footer has a counter ("3 of 4 picked") and "Pin them" primary button (disabled until ≥1 selected).

- [ ] **Step 1: Create the component**

Create `static/js/components/onboarding-pin-folders.js`:

```javascript
/* MFOnboardingPinFolders — onboarding step 3.
 * Spec §3 step 3: drag-pickable list of indexed folders, mark 3–4 favorites.
 * Implementation uses click-to-toggle (drag-to-pin adds no value over click).
 *
 * Calls opts.onContinue(pickedPaths) when user clicks Pin them.
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }

  function fetchJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error(url + ' ' + r.status);
      return r.json();
    });
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFOnboardingPinFolders.mount: slot required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var hero = el('h1', 'mf-onboard__hero');
    hero.textContent = 'Pin a few favorites.';
    slot.appendChild(hero);

    var sub = el('p', 'mf-onboard__sub');
    sub.textContent = 'These show up at the top of your Search-home so you can jump in fast. Pick 3 or 4 for now — you can change them any time.';
    slot.appendChild(sub);

    var counter = el('div', 'mf-folder-counter');
    counter.textContent = 'No folders picked yet.';
    slot.appendChild(counter);

    var listWrap = el('div', 'mf-folder-list');
    listWrap.setAttribute('role', 'listbox');
    listWrap.setAttribute('aria-multiselectable', 'true');
    listWrap.setAttribute('aria-label', 'Indexed folders to pin');
    slot.appendChild(listWrap);

    var loading = el('p'); loading.style.cssText = 'color:#888;text-align:center;padding:2rem 0';
    loading.textContent = 'Loading folders…';
    listWrap.appendChild(loading);

    var picked = [];

    function updateCounter() {
      counter.textContent = '';
      if (!picked.length) {
        counter.textContent = 'No folders picked yet — pick at least 1 to continue.';
      } else {
        var lead = el('strong'); lead.textContent = picked.length + ' folder' + (picked.length === 1 ? '' : 's');
        counter.appendChild(lead);
        counter.appendChild(document.createTextNode(' picked' + (picked.length > 4 ? ' (you can pick more, but 3–4 is the sweet spot)' : '') + '.'));
      }
      pinBtn.disabled = picked.length === 0;
    }

    function buildRow(folder) {
      var row = el('div', 'mf-folder-row');
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', 'false');
      row.tabIndex = 0;
      var check = el('div', 'mf-folder-row__check');
      check.textContent = '✓';
      var path = el('div', 'mf-folder-row__path');
      path.textContent = folder.label || folder.path;
      var count = el('div', 'mf-folder-row__count');
      count.textContent = folder.file_count.toLocaleString() + ' files';
      row.appendChild(check); row.appendChild(path); row.appendChild(count);

      function toggle() {
        var i = picked.indexOf(folder.path);
        if (i >= 0) picked.splice(i, 1);
        else picked.push(folder.path);
        var on = picked.indexOf(folder.path) >= 0;
        row.classList.toggle('mf-folder-row--on', on);
        row.setAttribute('aria-selected', on ? 'true' : 'false');
        updateCounter();
      }
      row.addEventListener('click', toggle);
      row.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
      return row;
    }

    fetchJson('/api/folders/indexed').then(function (data) {
      while (listWrap.firstChild) listWrap.removeChild(listWrap.firstChild);
      var folders = (data && data.folders) || [];
      if (!folders.length) {
        var empty = el('p'); empty.style.cssText = 'color:#888;text-align:center;padding:2rem 0';
        empty.textContent = 'No indexed folders yet. Skip onboarding for now — once the pipeline ingests files, come back and pin a few.';
        listWrap.appendChild(empty);
        pinBtn.textContent = 'Done';
        pinBtn.disabled = false;
        return;
      }
      folders.forEach(function (f) { listWrap.appendChild(buildRow(f)); });
    }).catch(function (e) {
      console.error('mf: indexed folders load failed', e);
      while (listWrap.firstChild) listWrap.removeChild(listWrap.firstChild);
      var err = el('p'); err.style.cssText = 'color:#c92a2a;text-align:center;padding:2rem 0';
      err.textContent = 'Could not load folders. Check console — you can skip and pin later from Settings.';
      listWrap.appendChild(err);
    });

    var cta = el('div', 'mf-onboard__cta');
    var pinBtn = el('button', 'mf-pill mf-pill--primary');
    pinBtn.type = 'button';
    pinBtn.textContent = 'Pin them';
    pinBtn.disabled = true;
    pinBtn.addEventListener('click', function () {
      MFTelemetry.emit('ui.onboarding_step_complete', { step: 'pin-folders', count: picked.length });
      if (opts.onContinue) opts.onContinue(picked);
    });
    cta.appendChild(pinBtn);

    var back = el('button', 'mf-pill mf-pill--ghost');
    back.type = 'button';
    back.textContent = '← Back';
    back.addEventListener('click', function () { if (opts.onBack) opts.onBack(); });
    cta.appendChild(back);

    var skip = el('button', 'mf-onboard__skip');
    skip.type = 'button';
    skip.textContent = "I'll pin later";
    skip.addEventListener('click', function () { if (opts.onSkipStep) opts.onSkipStep(); });
    cta.appendChild(skip);

    slot.appendChild(cta);
    updateCounter();
  }

  global.MFOnboardingPinFolders = { mount: mount };
})(window);
```

- [ ] **Step 2: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/components/onboarding-pin-folders.js`

Expected: zero matches.

- [ ] **Step 3: Commit**

```bash
git add static/js/components/onboarding-pin-folders.js
git commit -m "feat(ux): MFOnboardingPinFolders (step 3)

Click-to-toggle row picker over /api/folders/indexed. Counter
('N folders picked'), keyboard accessible (Enter/Space toggles),
ARIA listbox semantics. Empty state when no folders indexed yet
('Skip for now — come back later'). Spec §3."
```

---

## Task 4: `MFOnboarding` state machine + page

**Files:**
- Create: `static/onboarding.html`
- Create: `static/js/pages/onboarding.js`
- Create: `static/js/onboarding-boot.js`
- Modify: `main.py`

The state machine wires the three components together: welcome → layout-picker → pin-folders → done. On *done*, write `MFPrefs.set('onboarding_completed_at', new Date().toISOString())` + `MFPrefs.set('pinned_folders', JSON.stringify(picked))`, then `window.location.href = '/'` (Search-home).

- [ ] **Step 1: Create the template**

Create `static/onboarding.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MarkFlow — Welcome</title>
  <link rel="stylesheet" href="/static/css/components.css">
  <style>
    body { margin: 0; min-height: 100vh; font-family: -apple-system, "SF Pro Display", Inter, system-ui, sans-serif; }
  </style>
</head>
<body data-env="dev">
  <div id="mf-onboarding" class="mf-onboard">
    <div class="mf-onboard__card">
      <div class="mf-onboard__steps" id="mf-onboarding-steps">
        <span class="mf-onboard__dot mf-onboard__dot--active"></span>
        <span class="mf-onboard__dot"></span>
        <span class="mf-onboard__dot"></span>
      </div>
      <div id="mf-onboarding-step"></div>
    </div>
  </div>

  <script src="/static/js/preferences.js"></script>
  <script src="/static/js/telemetry.js"></script>
  <script src="/static/js/components/layout-picker-cards.js"></script>
  <script src="/static/js/components/onboarding-welcome.js"></script>
  <script src="/static/js/components/onboarding-pin-folders.js"></script>
  <script src="/static/js/pages/onboarding.js"></script>
  <script src="/static/js/onboarding-boot.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create the page state machine**

Create `static/js/pages/onboarding.js`:

```javascript
/* MFOnboarding — state machine for the 3-step first-run flow.
 * Spec §3.
 *
 * Step 1: MFOnboardingWelcome
 * Step 2: MFLayoutPickerCards (Plan 1C)
 * Step 3: MFOnboardingPinFolders
 *
 * On completion (or skip): writes prefs, navigates to Search-home.
 *
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }

  function setStepDots(stepsRoot, current) {
    if (!stepsRoot) return;
    var dots = stepsRoot.querySelectorAll('.mf-onboard__dot');
    for (var i = 0; i < dots.length; i++) {
      dots[i].classList.remove('mf-onboard__dot--active', 'mf-onboard__dot--done');
      if (i < current) dots[i].classList.add('mf-onboard__dot--done');
      else if (i === current) dots[i].classList.add('mf-onboard__dot--active');
    }
  }

  function finalize(layoutMode, pickedFolders) {
    MFPrefs.set('layout', layoutMode || 'minimal');
    MFPrefs.set('pinned_folders', JSON.stringify(pickedFolders || []));
    MFPrefs.set('onboarding_completed_at', new Date().toISOString());
    MFTelemetry.emit('ui.onboarding_completed', {
      layout: layoutMode || 'minimal',
      pinned_count: (pickedFolders || []).length,
    });
    window.location.href = '/';
  }

  function skipAll() {
    // Skip = land on Minimal with no pins, but mark onboarding done so
    // we don't re-prompt. Spec §3: skip-fallback is Minimal.
    MFPrefs.set('layout', MFPrefs.get('layout') || 'minimal');
    if (!MFPrefs.get('pinned_folders')) MFPrefs.set('pinned_folders', '[]');
    MFPrefs.set('onboarding_completed_at', new Date().toISOString());
    MFTelemetry.emit('ui.onboarding_skipped', {});
    window.location.href = '/';
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFOnboarding.mount: slot required');
    var stepRoot = document.getElementById('mf-onboarding-step');
    var stepsRoot = document.getElementById('mf-onboarding-steps');
    var role = (opts && opts.role) || 'member';

    var state = {
      layout: MFPrefs.get('layout') || 'minimal',
      pinnedFolders: [],
    };

    function showWelcome() {
      setStepDots(stepsRoot, 0);
      MFOnboardingWelcome.mount(stepRoot, {
        role: role,
        onContinue: showLayoutPicker,
        onSkip: skipAll,
      });
    }

    function showLayoutPicker() {
      setStepDots(stepsRoot, 1);
      while (stepRoot.firstChild) stepRoot.removeChild(stepRoot.firstChild);

      var hero = el('h1', 'mf-onboard__hero');
      hero.textContent = 'Pick how home looks.';
      stepRoot.appendChild(hero);
      var sub = el('p', 'mf-onboard__sub');
      sub.textContent = 'You can change this any time with ⌘\\ or the layout icon next to your avatar.';
      stepRoot.appendChild(sub);

      var pickerSlot = el('div');
      stepRoot.appendChild(pickerSlot);
      MFLayoutPickerCards.mount(pickerSlot, {
        recommended: 'minimal',
        onChoose: function (mode) {
          state.layout = mode;
          MFPrefs.set('layout', mode);
          MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'onboarding' });
          showPinFolders();
        },
      });

      var cta = el('div', 'mf-onboard__cta');
      var back = el('button', 'mf-pill mf-pill--ghost');
      back.type = 'button'; back.textContent = '← Back';
      back.addEventListener('click', showWelcome);
      cta.appendChild(back);
      var skip = el('button', 'mf-onboard__skip');
      skip.type = 'button'; skip.textContent = "Skip — I'll go with Minimal";
      skip.addEventListener('click', function () {
        state.layout = 'minimal';
        MFPrefs.set('layout', 'minimal');
        showPinFolders();
      });
      cta.appendChild(skip);
      stepRoot.appendChild(cta);
    }

    function showPinFolders() {
      setStepDots(stepsRoot, 2);
      MFOnboardingPinFolders.mount(stepRoot, {
        onContinue: function (paths) {
          state.pinnedFolders = paths || [];
          finalize(state.layout, state.pinnedFolders);
        },
        onBack: showLayoutPicker,
        onSkipStep: function () { finalize(state.layout, []); },
      });
    }

    showWelcome();
  }

  global.MFOnboarding = { mount: mount };
})(window);
```

- [ ] **Step 3: Create the boot**

Create `static/js/onboarding-boot.js`:

```javascript
/* Boot for /onboarding. Fetches /api/me for role-aware copy, then
 * mounts MFOnboarding. If the user already completed onboarding,
 * redirect to / (defense-in-depth — the Search-home boot also
 * redirects in the other direction).
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var slot = document.getElementById('mf-onboarding');

  function fetchJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error(url + ' ' + r.status);
      return r.json();
    });
  }

  Promise.all([MFPrefs.load(), fetchJson('/api/me').catch(function () { return { role: 'member' }; })]).then(function (results) {
    var me = results[1];
    var done = MFPrefs.get('onboarding_completed_at');
    if (done) {
      window.location.href = '/';
      return;
    }
    MFOnboarding.mount(slot, { role: me.role });
  }).catch(function (e) {
    console.error('mf: onboarding boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Onboarding unavailable. Continue to home →';
    slot.appendChild(msg);
    setTimeout(function () { window.location.href = '/'; }, 2000);
  });
})();
```

- [ ] **Step 4: Wire `/onboarding` route in `main.py`**

```python
@app.get("/onboarding", include_in_schema=False)
async def onboarding_page():
    """First-run onboarding flow. Always served when ENABLE_NEW_UX=true;
    no legacy fallback (legacy MarkFlow had no onboarding)."""
    if not is_new_ux_enabled():
        # Flag off → no onboarding; bounce to legacy index
        return RedirectResponse(url="/", status_code=302)
    return FileResponse("static/onboarding.html")
```

- [ ] **Step 5: Smoke verify**

```bash
ENABLE_NEW_UX=true docker-compose up -d --force-recreate markflow
```

As a fresh user (clear `localStorage` + reset `onboarding_completed_at` in this user's `mf_user_prefs` row, e.g. `UPDATE mf_user_prefs SET value = json_set(value, '$.onboarding_completed_at', '') WHERE user_id = '<your sub claim>'`):

- Visit `/onboarding` → step 1 (welcome) renders with role-aware copy, dots show 1-of-3 active
- Click "Get started →" → step 2 (layout picker) renders, dots show 2-of-3 active
- Pick "Minimal" → step 3 (pin folders) renders, dots show 3-of-3 active, indexed folders load
- Click 3 folders → counter updates → "Pin them" enabled
- Click "Pin them" → redirect to `/` → Search-home renders in Minimal mode with the 3 folders pinned
- Visit `/onboarding` again → boot detects `onboarding_completed_at` is set → redirects to `/`

Skip paths:
- "Skip onboarding" on step 1 → goes straight to `/` with Minimal + no pins
- "I'll pin later" on step 3 → finalizes with chosen layout + no pins
- "Skip — I'll go with Minimal" on step 2 → step 3 still runs

- [ ] **Step 6: Commit**

```bash
git add static/onboarding.html static/js/pages/onboarding.js \
        static/js/onboarding-boot.js main.py
git commit -m "feat(ux): /onboarding — 3-step first-run flow

State machine (welcome → layout-picker → pin-folders → done) wires
MFOnboardingWelcome (Plan 8 Task 2), MFLayoutPickerCards (Plan 1C),
MFOnboardingPinFolders (Plan 8 Task 3). On completion writes layout +
pinned_folders + onboarding_completed_at prefs and redirects to /.
Boot redirects already-completed users to /. Spec §3."
```

---

## Task 5: First-run redirect from Search-home

**Files:**
- Modify: `static/js/index-new-boot.js`
- Create: `tests/test_onboarding_redirect.py` (front-end behavior tested via headless browser is overkill for v1; pin the *backend* contract that MFPrefs returns no `onboarding_completed_at` for a fresh user)

The Search-home boot (Plan 3) needs a one-line addition: before mounting the page, check `MFPrefs.get('onboarding_completed_at')`. If empty *and* `ENABLE_NEW_UX=true`, redirect to `/onboarding`.

- [ ] **Step 1: Write the test**

Create `tests/test_onboarding_redirect.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_admin_client(fake_jwt):
    return TestClient(app, headers={"Authorization": "Bearer " + fake_jwt("xerxes@local46.org", "admin")})


def test_fresh_user_has_no_completion_pref(authed_admin_client):
    """A user who has never run onboarding has an empty
    onboarding_completed_at pref. The Search-home boot uses this absence
    to trigger redirect.

    Reads from /api/user-prefs (per-user store, Plan 1A Task 8) — NOT
    /api/preferences (system-level singletons). Onboarding completion
    is intrinsically per-user and lives in mf_user_prefs."""
    r = authed_admin_client.get("/api/user-prefs")
    assert r.status_code == 200
    prefs = r.json()
    # Default for new user is empty string; absence treated identically by client.
    val = prefs.get("onboarding_completed_at", "")
    assert val == "" or val is None


def test_completion_pref_can_be_written(authed_admin_client):
    """PUT to /api/user-prefs is a partial-update with {key: value, ...}
    body shape (Plan 1A Task 8). Server merges into stored blob."""
    r = authed_admin_client.put(
        "/api/user-prefs",
        json={"onboarding_completed_at": "2026-04-28T12:00:00Z"},
    )
    assert r.status_code == 200
    body = authed_admin_client.get("/api/user-prefs").json()
    assert body["onboarding_completed_at"] == "2026-04-28T12:00:00Z"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_onboarding_redirect.py -v`

Expected: PASS — `onboarding_completed_at` is included in `DEFAULT_USER_PREFS` (Plan 1A Task 7) with default empty string.

If a test fails because the key isn't in `USER_PREF_KEYS`, add it to `core/user_prefs.py`'s `DEFAULT_USER_PREFS` (default `""`) and to the `_STRS` validator set, and re-run. Plan 1A *intended* to add it; this is the safety net if the schema additions drift between plan-as-written and what actually shipped.

- [ ] **Step 3: Modify the Search-home boot**

In `static/js/index-new-boot.js`, find the `Promise.all([MFPrefs.load(), fetchMe()]).then(...)` block (Plan 4 Task 2 modified this). At the very top of the `.then` callback, before any DOM work, add:

```javascript
  Promise.all([MFPrefs.load(), fetchMe()]).then(function (results) {
    // First-run redirect: if onboarding hasn't been completed, send the
    // user to /onboarding before rendering anything. The /onboarding
    // boot redirects back here once it writes onboarding_completed_at.
    if (!MFPrefs.get('onboarding_completed_at')) {
      window.location.href = '/onboarding';
      return;
    }

    var me = results[1];
    // ... rest of the existing block unchanged ...
```

- [ ] **Step 4: Smoke verify**

Clear `onboarding_completed_at` from your per-user prefs (via `PUT /api/user-prefs` with body `{"onboarding_completed_at": ""}`). Visit `/`. Expected: instant redirect to `/onboarding`.

Complete or skip onboarding. Expected: redirect to `/`, Search-home renders, no further redirects on subsequent visits.

- [ ] **Step 5: Commit**

```bash
git add static/js/index-new-boot.js tests/test_onboarding_redirect.py
git commit -m "feat(ux): Search-home redirects fresh users to /onboarding

One-line addition at top of index-new-boot's Promise.all callback:
if onboarding_completed_at is empty, redirect to /onboarding before
mounting anything. /onboarding redirects back once the prefs are
written. Spec §3."
```

---

## Task 6: Acceptance check + plan close

**Files:** none modified — verification only.

- [ ] `pytest tests/test_folders_indexed_endpoint.py tests/test_onboarding_redirect.py -v` — 6 PASS
- [ ] `grep -rn "innerHTML" static/js/components/onboarding-welcome.js static/js/components/onboarding-pin-folders.js static/js/pages/onboarding.js static/js/onboarding-boot.js` — zero matches
- [ ] As a fresh admin (`onboarding_completed_at` cleared, `ENABLE_NEW_UX=true`):
  - Visit `/` → redirects to `/onboarding`
  - Step 1 renders with admin copy ("Set up MarkFlow for IBEW Local 46")
  - Step indicator dots advance correctly through all three steps
  - Layout picker shows recommended ring on Minimal
  - Pin folders step loads real folders from `/api/folders/indexed`
  - Click "Pin them" with 3 folders selected → redirect to `/` → Search-home renders Minimal layout with the 3 folders pinned (visible if user picked Maximal — for Minimal, the pins are invisible until layout switch)
  - Visit `/onboarding` again → redirects back to `/`
- [ ] As a fresh member:
  - Step 1 renders with member copy ("Find anything on the K Drive, fast")
  - Rest of flow identical
- [ ] Skip paths:
  - "Skip onboarding" from step 1 → `/` with Minimal + no pins, completion pref written
  - "I'll pin later" from step 3 → `/` with chosen layout + no pins
  - "Skip — I'll go with Minimal" from step 2 → step 3 still runs
- [ ] Empty-state path:
  - Clear `source_files` in a test database → `/api/folders/indexed` returns empty list → step 3 renders "No indexed folders yet" message → "Done" button enabled (changed from "Pin them") → completes with no pins
- [ ] Telemetry events visible in `docker-compose logs -f markflow | grep ui.onboarding_`:
  - `ui.onboarding_step_complete` at each step
  - `ui.onboarding_completed` on full completion
  - `ui.onboarding_skipped` on top-level skip
  - `ui.layout_mode_selected` from the picker (source: `onboarding`)
- [ ] As admin with `ENABLE_NEW_UX=false`:
  - `/onboarding` 302 redirects to `/`
  - Legacy index renders, no onboarding visible

If any item fails, file in `docs/bug-log.md`. **Don't silently fix.**

Once all green, **Plan 8 is done**. The UX overhaul reaches its V1 milestone — all 8 plans shipped.

Recommended follow-ups (not part of this plan):
- Bump version to `v0.35.0` and write the version-history entry
- Ship the deprecation pass that removes `static/admin.html`, `providers.html`, `db-health.html`, `log-management.html`, `pipeline-files.html`, `settings.html`, `storage.html` (the legacy fallbacks each detail page route falls back to when `ENABLE_NEW_UX=false`)
- Flip `ENABLE_NEW_UX=true` in production after a one-week soak, then schedule the `/pipeline → /activity` 301 alias removal one release after that
- Run the spec §13 pre-production cutover checklist

---

## Self-review

**Spec coverage:**
- §3 step 1 (welcome — "What do you want to find on the K Drive?"): ✓ Task 2 (role-aware copy)
- §3 step 2 (layout picker — already shipped in Plan 1C): ✓ Task 4 reuses `MFLayoutPickerCards`
- §3 step 3 (pin folders — drag-pickable list with file counts): ✓ Tasks 1 + 3 (click-to-toggle in lieu of drag, justified inline)
- §3 skip-fallback to Minimal: ✓ Task 4 `skipAll` writes `layout=minimal`

**Spec gaps for this plan (deferred):**
- "Re-run onboarding from avatar menu" — v1.1 (out-of-scope at top)
- Drag-to-pin interaction — replaced with click-to-toggle (justified at top of Task 3)
- Per-tenant folder filtering on `/api/folders/indexed` — UnionCore tenant-claim driven; Plan 8 returns the same list for every authenticated user, follow-up plan once UnionCore exposes the claim

**Placeholder scan:**
- No "TODO" / "TBD" in shipped task bodies
- The "drag-pickable" → "click-to-toggle" choice is documented at the top of Task 3, not hidden as a TODO

**Type / API consistency:**
- `MFOnboardingWelcome.mount(slot, { role, onContinue, onSkip })` signature consistent with caller in Task 4
- `MFOnboardingPinFolders.mount(slot, { onContinue(paths), onBack, onSkipStep })` consistent with caller in Task 4
- `MFLayoutPickerCards.mount(slot, { recommended, onChoose })` matches Plan 1C's signature
- `MFPrefs.set('onboarding_completed_at', ...)` + `MFPrefs.set('pinned_folders', ...)` keys match Plan 1A's preferences schema
- Telemetry events follow the locked `ui.onboarding_*` namespace introduced here; `ui.layout_mode_selected` reuses Plan 1C's existing event with `source: 'onboarding'`

**Safe-DOM verification:**

```
grep -rn "innerHTML" static/js/components/onboarding-welcome.js static/js/components/onboarding-pin-folders.js static/js/pages/onboarding.js static/js/onboarding-boot.js
```

Expected: empty.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-onboarding.md`.

Sized for: 6 implementer dispatches + 6 spec reviews + 6 code-quality reviews ≈ 18 subagent calls (Task 6 is verification-only).

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session

Once Plan 8 ships, the UX overhaul reaches its V1 milestone — all 8 plans (1A · 1B · 1C · 2A · 2B · 3 · 4 · 5 · 6 · 7 · 8) complete and behind `ENABLE_NEW_UX`. Follow-ups listed at the end of Task 6.
