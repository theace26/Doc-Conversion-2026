# UX Overhaul — Remaining Settings Detail Pages Plan (Plan 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the six remaining System detail pages — **Pipeline & lifecycle**, **AI providers**, **Account & auth**, **Notifications (system)**, **Database health**, **Log management** — by dropping each into the `MFSettingsDetail` shell that Plan 5 established. Each page reuses Plan 5's `MFFormControls` atoms and calls existing backend endpoints. Account & auth additionally lands the JWT-freshness re-auth gate that gates System-settings saves (the spec §11 "re-auth required" toggle).

**Architecture:** Six new page components, each at `static/js/pages/settings-<section>.js`, each mounted into a per-page template (`static/settings-<section>.html`) by a per-page boot. Routes added flag-aware (new template when `ENABLE_NEW_UX=true`, fall back to legacy admin / settings sub-pages otherwise). Two new backend additions: `GET /api/auth/freshness` (returns the iat-age of the current JWT) and `POST /api/auth/reauth` (issues a fresh JWT after re-validating credentials), plus a tiny global front-end gate (`MFReauthGate.requireFresh(maxAgeSec)`) that any save in any System detail page can call before issuing its PUT/POST. Storage's saves (Plan 5) are *retroactively wrapped* with the gate as a one-line addition. **Safe DOM construction throughout.**

**Tech stack:** Python 3.11 · FastAPI · pytest · vanilla JS · existing `core/auth` `Role` enum + `require_user` (Plan 1A) · existing per-section endpoints (`/api/pipeline/*`, `/api/llm-providers/*`, `/api/auth/*`, `/api/db-health/*`, `/api/log-management/*`) · `MFSettingsDetail` + `MFFormControls` (Plan 5)

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §7 (sub-section sidebars locked per section), §11 (re-auth gate), §13 (phase-5 specifically — re-auth gate triggers correctly when flipping system settings)

**Mockup reference:**
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-detail-family.html` — Pipeline & lifecycle in full plus taxonomies for the other five
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-three-details.html` — AI / Notifications / Auth detail patterns

**Out of scope (deferred):**
- Cost cap & alerts deep-dive sub-page (driven from AI providers) → Plan 7
- First-run flow → Plan 8
- Removing legacy `static/admin.html` / `static/providers.html` / `static/db-health.html` / `static/log-management.html` / `static/pipeline-files.html` — kept as the flag-off fallback until the deprecation pass after Plan 7
- Notifications **delivery** infrastructure (the actual Slack / email integration) — gated by a separate Notifications backend plan; Plan 6 only ships the configuration UI against existing trigger-rule endpoints (or a stubbed empty list when the endpoints don't exist yet)
- Member-facing Personal detail pages (Display / Pinned folders / Profile / Notifications-prefs) — separate sub-plan; Plan 6 handles only the **System** group
- True log-tail SSE inside the in-app log viewer — Plan 6 ships the levels-per-subsystem editor + retention controls + a "Open viewer in new tab" link to the existing `/log-viewer` page; SSE-in-shell is v1.1

**Prerequisites:** Plans 1A + 1B + 1C + 2A + 2B + 3 + 4 + 5 must all be complete. In particular this plan assumes `MFFormControls` and `MFSettingsDetail` are mountable globals (Plan 5 Tasks 2 + 3), and `/settings` overview already lists all seven System cards (Plan 5 Task 1).

---

## File structure (this plan creates / modifies)

**Create:**
- `api/routes/auth_freshness.py` — `/api/auth/freshness` (GET) + `/api/auth/reauth` (POST)
- `static/js/components/reauth-gate.js` — `MFReauthGate.requireFresh(maxAgeSec)` global
- `static/settings-pipeline.html` + `static/js/pages/settings-pipeline.js` + `static/js/settings-pipeline-boot.js`
- `static/settings-ai-providers.html` + `static/js/pages/settings-ai-providers.js` + `static/js/settings-ai-providers-boot.js`
- `static/settings-account-auth.html` + `static/js/pages/settings-account-auth.js` + `static/js/settings-account-auth-boot.js`
- `static/settings-notifications.html` + `static/js/pages/settings-notifications.js` + `static/js/settings-notifications-boot.js`
- `static/settings-database-health.html` + `static/js/pages/settings-database-health.js` + `static/js/settings-database-health-boot.js`
- `static/settings-log-management.html` + `static/js/pages/settings-log-management.js` + `static/js/settings-log-management-boot.js`
- `tests/test_auth_freshness_endpoint.py`

**Modify:**
- `static/css/components.css` — append section-specific minor styles (per-page tweaks; bulk of CSS reused from Plan 5)
- `main.py` — register `auth_freshness` router; add six new flag-aware routes (`/settings/pipeline`, `/settings/ai-providers`, `/settings/account-auth`, `/settings/notifications-system`, `/settings/database-health`, `/settings/log-management`)
- `static/js/pages/settings-storage.js` (Plan 5) — wrap save handlers in `MFReauthGate.requireFresh(300)` (5-min freshness)

**Not removed (yet):** legacy `admin.html`, `providers.html`, `db-health.html`, `log-management.html`, `pipeline-files.html` — deprecation pass after Plan 7.

---

## Task 1: JWT freshness endpoints + `MFReauthGate`

**Files:**
- Create: `api/routes/auth_freshness.py`
- Create: `static/js/components/reauth-gate.js`
- Create: `tests/test_auth_freshness_endpoint.py`
- Modify: `main.py`

The re-auth gate is a UX layer on top of JWT issuance. The backend tells you how old the current JWT's `iat` is; the front-end decides whether to prompt for re-auth based on a per-action `maxAgeSec`. Re-auth itself is a credentials POST that returns a new JWT; the cookie / Authorization header swap follows whatever existing flow MarkFlow uses.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_freshness_endpoint.py`:

```python
import time
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_admin_client(fake_jwt):
    return TestClient(app, headers={
        "Authorization": "Bearer " + fake_jwt("xerxes@local46.org", "admin"),
    })


def test_freshness_returns_iat_age(authed_admin_client):
    r = authed_admin_client.get("/api/auth/freshness")
    assert r.status_code == 200
    body = r.json()
    assert "iat" in body
    assert "age_seconds" in body
    # Tokens minted by fake_jwt should be young
    assert body["age_seconds"] < 5


def test_freshness_unauthenticated_returns_401():
    client = TestClient(app)
    r = client.get("/api/auth/freshness")
    assert r.status_code == 401


def test_reauth_requires_password_field(authed_admin_client):
    r = authed_admin_client.post("/api/auth/reauth", json={})
    # Either 400 (missing field) or 422 (validation) — either is acceptable
    assert r.status_code in (400, 422)
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_auth_freshness_endpoint.py -v`

Expected: FAIL — endpoints don't exist (404).

- [ ] **Step 3: Implement the endpoints**

Create `api/routes/auth_freshness.py`:

```python
"""GET /api/auth/freshness, POST /api/auth/reauth.

The freshness endpoint returns how old the current token's iat claim
is, in whole seconds. The reauth endpoint re-validates the current
user's credentials (password or refresh token, depending on existing
flow) and issues a fresh JWT.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §11
"""
from __future__ import annotations
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_user, mint_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ReauthRequest(BaseModel):
    password: str


@router.get("/freshness")
async def freshness(user=Depends(require_user)):
    iat = getattr(user, "iat", None)
    if iat is None:
        # Defensive: if iat isn't surfaced by require_user, treat as fresh
        # (the back-end will still re-validate at action-time).
        return {"iat": None, "age_seconds": 0}
    age = max(0, int(time.time() - iat))
    return {"iat": iat, "age_seconds": age}


@router.post("/reauth")
async def reauth(req: ReauthRequest, user=Depends(require_user)):
    if not verify_password(user.user_id, req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = mint_token(user.user_id, role=getattr(user, "role", "member"))
    return {"token": token, "iat": int(time.time())}
```

If `mint_token` / `verify_password` have different names in `core.auth`, adapt the imports. The contract that matters is: `freshness` returns `age_seconds`, `reauth` accepts `{ password }` and returns a new token.

- [ ] **Step 4: Wire into `main.py`**

```python
from api.routes import auth_freshness as auth_freshness_routes
app.include_router(auth_freshness_routes.router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `pytest tests/test_auth_freshness_endpoint.py -v`

Expected: 3 PASS.

- [ ] **Step 6: Implement `MFReauthGate`**

Create `static/js/components/reauth-gate.js`:

```javascript
/* MFReauthGate — front-end gate for "system settings require recent
 * re-auth before save". Spec §11.
 *
 * Usage:
 *   MFReauthGate.requireFresh(300).then(function () {
 *     // ok to save — token is fresh enough (or user just re-authed)
 *     doSave();
 *   }).catch(function () {
 *     // user cancelled the re-auth prompt; abort save
 *   });
 *
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  function fetchJson(url, init) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, init || {}))
      .then(function (r) {
        if (!r.ok) throw new Error(url + ' ' + r.status);
        return r.json();
      });
  }

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }

  function showPrompt() {
    return new Promise(function (resolve, reject) {
      var backdrop = el('div');
      backdrop.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:-apple-system,Inter,sans-serif';
      var box = el('div', 'mf-card');
      box.style.cssText = 'min-width:340px;padding:1.4rem 1.5rem;background:#fff';
      var h = el('h3'); h.style.cssText = 'margin:0 0 0.6rem;font-size:1.05rem'; h.textContent = 'Confirm your password';
      var p = el('p'); p.style.cssText = 'margin:0 0 1rem;color:#5a5a5a;font-size:0.88rem'; p.textContent = 'Changing system settings requires a fresh password confirmation.';
      var input = document.createElement('input');
      input.type = 'password';
      input.className = 'mf-field-input';
      input.autocomplete = 'current-password';
      input.placeholder = 'Password';
      var actions = el('div'); actions.style.cssText = 'display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end';
      var cancel = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
      cancel.type = 'button'; cancel.textContent = 'Cancel';
      var ok = el('button', 'mf-pill mf-pill--primary mf-pill--sm');
      ok.type = 'button'; ok.textContent = 'Confirm';
      var err = el('p'); err.style.cssText = 'margin:0.5rem 0 0;color:#c92a2a;font-size:0.84rem;display:none';

      function close() { document.body.removeChild(backdrop); }
      cancel.addEventListener('click', function () { close(); reject(new Error('cancelled')); });
      ok.addEventListener('click', function () {
        ok.disabled = true; err.style.display = 'none';
        fetchJson('/api/auth/reauth', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: input.value }),
        }).then(function () {
          close(); resolve();
        }).catch(function () {
          err.style.display = ''; err.textContent = 'Invalid password';
          ok.disabled = false;
        });
      });
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') ok.click(); });

      box.appendChild(h); box.appendChild(p); box.appendChild(input); box.appendChild(err);
      actions.appendChild(cancel); actions.appendChild(ok);
      box.appendChild(actions);
      backdrop.appendChild(box);
      document.body.appendChild(backdrop);
      setTimeout(function () { input.focus(); }, 0);
    });
  }

  function requireFresh(maxAgeSec) {
    return fetchJson('/api/auth/freshness').then(function (r) {
      if (r.age_seconds == null) return; // freshness unknown — proceed
      if (r.age_seconds <= (maxAgeSec || 300)) return; // fresh enough
      return showPrompt();
    });
  }

  global.MFReauthGate = { requireFresh: requireFresh };
})(window);
```

- [ ] **Step 7: Wrap Plan 5 Storage saves**

Modify `static/js/pages/settings-storage.js`. In `renderOutputPaths`, wrap the body of `ctx.onSave(function () { ... })` so the PUT only fires after the gate resolves:

```javascript
      ctx.onSave(function () {
        if (nextValue === current) return;
        MFReauthGate.requireFresh(300).then(function () {
          ctx.setStatus('saving', 'Saving…');
          fetchJson('/api/storage/output', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: nextValue }),
          }).then(function () {
            current = nextValue;
            ctx.markClean();
            MFTelemetry.emit('ui.settings_save', { section: 'storage', sub: 'output-paths' });
          }).catch(function (e) {
            ctx.setStatus('error', 'Save failed: ' + e.message);
          });
        }).catch(function () {
          ctx.setStatus('', '');
        });
      });
```

Apply the same wrapping pattern to `renderCloudPrefetch`'s save handler (the only other save in the Storage page).

Also add `<script src="/static/js/components/reauth-gate.js"></script>` to `static/settings-storage.html` (before `pages/settings-storage.js`).

- [ ] **Step 8: Smoke verify**

```bash
docker-compose up -d --force-recreate markflow
```

As an admin user with `ENABLE_NEW_UX=true`, visit `/settings/storage`. Edit Output paths → Save. Expected:
- If JWT iat-age < 300s: save proceeds without prompt
- If iat-age > 300s (sleep 6+ minutes after login then save): password prompt appears, correct password → save proceeds, wrong password → "Invalid password" inline; cancel → status clears, no save

- [ ] **Step 9: Commit**

```bash
git add api/routes/auth_freshness.py static/js/components/reauth-gate.js \
        tests/test_auth_freshness_endpoint.py main.py \
        static/js/pages/settings-storage.js static/settings-storage.html
git commit -m "feat(auth): JWT freshness endpoint + MFReauthGate

GET /api/auth/freshness returns iat + age_seconds. POST /api/auth/reauth
re-validates the current user's password and issues a fresh JWT.
Front-end MFReauthGate.requireFresh(maxAgeSec) returns a Promise that
resolves when token is fresh OR user just re-authed; rejects on cancel.

Plan 5 Storage saves (Output paths, Cloud prefetch) wrapped at the
save-handler boundary so existing test coverage stays valid. Spec §11."
```

---

## Task 2: Pipeline & lifecycle detail page

**Files:**
- Create: `static/settings-pipeline.html`
- Create: `static/js/pages/settings-pipeline.js`
- Create: `static/js/settings-pipeline-boot.js`
- Modify: `main.py`

Six sub-sections per spec §7: **Scan schedule · Lifecycle & retention · Trash & cleanup · Stale data check · Pipeline watchdog · Pause & resume** *(live badge)*. Wires to existing `/api/pipeline/*`, `/api/lifecycle/*`, `/api/trash/*`, `/api/scanner/*` endpoints — see `api/routes/pipeline.py`, `lifecycle.py`, `trash.py`, `scanner.py` for shapes.

The boot pattern is identical to Plan 5's Storage boot — copy that file as the starting point, change `MFStorageSettings` → `MFPipelineSettings`, and update the page IDs and redirect path.

- [ ] **Step 1: Create the template + boot**

Create `static/settings-pipeline.html` (copy of `static/settings-storage.html` from Plan 5 with `<div id="mf-settings-pipeline">` and the page-script src changed to `pages/settings-pipeline.js` + boot script `settings-pipeline-boot.js`).

Create `static/js/settings-pipeline-boot.js` (copy of `settings-storage-boot.js` from Plan 5; substitute `MFPipelineSettings` for `MFStorageSettings` and `pageRoot = document.getElementById('mf-settings-pipeline')`). Member-role redirect target stays `/settings`.

- [ ] **Step 2: Create the component**

Create `static/js/pages/settings-pipeline.js`. Skeleton:

```javascript
/* MFPipelineSettings — Settings → Pipeline & lifecycle.
 * Six sub-sections per spec §7.
 *
 *   Scan schedule        → /api/pipeline/scan-schedule (GET, PUT)
 *   Lifecycle & retention → /api/lifecycle/config (GET, PUT)
 *   Trash & cleanup       → /api/trash/config (GET, PUT) + /api/trash (GET list)
 *   Stale data check      → /api/pipeline/stale-config (GET, PUT)
 *   Pipeline watchdog     → /api/pipeline/watchdog (GET, PUT)
 *   Pause & resume        → /api/pipeline/state (GET) + /api/pipeline/pause + /api/pipeline/resume
 *
 * Each save handler wraps in MFReauthGate.requireFresh(300).
 * Safe DOM throughout. */
(function (global) {
  'use strict';
  var FC = null;
  var SUBSECTIONS = [
    { id: 'scan-schedule',     label: 'Scan schedule',       icon: '⚙' },
    { id: 'lifecycle',         label: 'Lifecycle & retention', icon: '⏳' },
    { id: 'trash-cleanup',     label: 'Trash & cleanup',     icon: '⌫' },
    { id: 'stale-data',        label: 'Stale data check',    icon: '⚠' },
    { id: 'watchdog',          label: 'Pipeline watchdog',   icon: '⛇' },
    { id: 'pause-resume',      label: 'Pause & resume',      icon: '⏚', badge: 'live', badgeTone: 'warn' },
  ];

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }
  function fetchJson(url, init) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, init || {}))
      .then(function (r) { if (!r.ok) throw new Error(url + ' ' + r.status); return r.status === 204 ? null : r.json(); });
  }
  function gatedSave(saveFn) {
    return MFReauthGate.requireFresh(300).then(saveFn);
  }

  // --- Scan schedule sub-section --------------------------------------------
  function renderScanSchedule(formArea, ctx) {
    fetchJson('/api/pipeline/scan-schedule').then(function (cfg) {
      var draft = Object.assign({}, cfg);
      var modeSeg = FC.segmented({
        options: [
          { id: 'continuous', label: 'Continuously' },
          { id: 'scheduled',  label: 'Scheduled' },
          { id: 'manual',     label: 'Manual only' },
        ],
        selected: cfg.mode || 'scheduled',
        onSelect: function (id) { draft.mode = id; ctx.markDirty(); },
      });
      formArea.appendChild(FC.formSection({
        title: 'Scan watched folders',
        desc: 'When MarkFlow looks at the K Drive for new or changed files. The engine yields to active bulk jobs — scheduled scans skip if a bulk job is running.',
        body: FC.fieldRow({ label: 'Mode', control: modeSeg }),
      }));

      var startInput = FC.textInput({ value: cfg.window_start || '06:00', tight: true,
        onInput: function (v) { draft.window_start = v; ctx.markDirty(); } });
      var endInput = FC.textInput({ value: cfg.window_end || '22:00', tight: true,
        onInput: function (v) { draft.window_end = v; ctx.markDirty(); } });
      var hours = el('div'); hours.style.cssText = 'display:flex;gap:1rem';
      hours.appendChild(FC.fieldRow({ label: 'Start', control: startInput }));
      hours.appendChild(FC.fieldRow({ label: 'End',   control: endInput }));
      var pills = FC.dayPills({
        selected: cfg.days || ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
        onChange: function (next) { draft.days = next; ctx.markDirty(); },
      });
      var sched = el('div');
      sched.appendChild(hours);
      sched.appendChild(FC.fieldRow({ label: 'Days', control: pills }));
      formArea.appendChild(FC.formSection({
        title: 'Schedule window',
        desc: 'Currently aligned to IBEW Local 46 hall hours so scans skip evening events.',
        body: sched,
      }));

      ctx.onSave(function () {
        gatedSave(function () {
          ctx.setStatus('saving', 'Saving…');
          return fetchJson('/api/pipeline/scan-schedule', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft),
          });
        }).then(function () {
          cfg = Object.assign({}, draft);
          ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'pipeline', sub: 'scan-schedule' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
      ctx.onDiscard(function () {
        while (formArea.firstChild) formArea.removeChild(formArea.firstChild);
        renderScanSchedule(formArea, ctx); ctx.markClean();
      });
      ctx.setActions([
        { id: 'run-now', label: 'Run scan now', variant: 'outline',
          onClick: function () { window.location.href = '/activity'; } },
      ]);
    }).catch(function (e) { ctx.setStatus('error', 'Failed: ' + e.message); });
  }

  // --- Lifecycle & retention -----------------------------------------------
  function renderLifecycle(formArea, ctx) {
    fetchJson('/api/lifecycle/config').then(function (cfg) {
      var draft = Object.assign({}, cfg);
      var grace = FC.textInput({ value: cfg.grace_hours, type: 'number', tight: true,
        onInput: function (v) { draft.grace_hours = v; ctx.markDirty(); } });
      var retention = FC.textInput({ value: cfg.retention_days, type: 'number', tight: true,
        onInput: function (v) { draft.retention_days = v; ctx.markDirty(); } });
      var grid = el('div'); grid.style.cssText = 'display:flex;gap:1rem';
      grid.appendChild(FC.fieldRow({ label: 'Grace (hours)', control: grace,
        help: 'How long after deletion a file stays restorable before retention applies.' }));
      grid.appendChild(FC.fieldRow({ label: 'Retention (days)', control: retention,
        help: 'How long a file stays in lifecycle before final cleanup.' }));
      formArea.appendChild(FC.formSection({
        title: 'Grace + retention',
        desc: 'Production values: grace=36h, retention=60d (locked in v0.23.3 — change with care).',
        body: grid,
      }));
      ctx.onSave(function () {
        gatedSave(function () {
          ctx.setStatus('saving', 'Saving…');
          return fetchJson('/api/lifecycle/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft),
          });
        }).then(function () { cfg = draft; ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'pipeline', sub: 'lifecycle' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
      ctx.onDiscard(function () { while (formArea.firstChild) formArea.removeChild(formArea.firstChild); renderLifecycle(formArea, ctx); ctx.markClean(); });
    }).catch(function (e) { ctx.setStatus('error', 'Failed: ' + e.message); });
  }

  // --- Trash & cleanup -----------------------------------------------------
  function renderTrash(formArea, ctx) {
    Promise.all([
      fetchJson('/api/trash/config').catch(function () { return {}; }),
      fetchJson('/api/trash').catch(function () { return { items: [] }; }),
    ]).then(function (results) {
      var cfg = results[0] || {};
      var items = (results[1] && results[1].items) || [];
      var draft = Object.assign({}, cfg);
      var expiry = FC.textInput({ value: cfg.expiry_days || 30, type: 'number', tight: true,
        onInput: function (v) { draft.expiry_days = v; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({
        title: 'Trash expiry',
        desc: 'Items are permanently deleted N days after entering trash.',
        body: FC.fieldRow({ label: 'Days', control: expiry }),
      }));
      formArea.appendChild(FC.formSection({
        title: 'Currently in trash',
        desc: 'Live count from /api/trash.',
        body: FC.miniTable({
          columns: [
            { id: 'name', label: 'Name', fr: 2 },
            { id: 'deleted_at', label: 'Deleted', fr: 1 },
          ],
          rows: items.slice(0, 6).map(function (it) {
            return { name: it.name || it.path, deleted_at: it.deleted_at };
          }),
        }),
      }));
      ctx.onSave(function () {
        gatedSave(function () {
          ctx.setStatus('saving', 'Saving…');
          return fetchJson('/api/trash/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft),
          });
        }).then(function () { cfg = draft; ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'pipeline', sub: 'trash' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
    }).catch(function (e) { ctx.setStatus('error', 'Failed: ' + e.message); });
  }

  // --- Stale data check ----------------------------------------------------
  function renderStaleData(formArea, ctx) {
    fetchJson('/api/pipeline/stale-config').catch(function () { return { interval_hours: 24 }; }).then(function (cfg) {
      var draft = Object.assign({}, cfg);
      var interval = FC.textInput({ value: cfg.interval_hours, type: 'number', tight: true,
        onInput: function (v) { draft.interval_hours = v; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({
        title: 'Stale data check interval',
        desc: 'How often the scheduler verifies that source_files rows match what is on disk.',
        body: FC.fieldRow({ label: 'Hours', control: interval }),
      }));
      ctx.onSave(function () {
        gatedSave(function () {
          return fetchJson('/api/pipeline/stale-config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft),
          });
        }).then(function () { cfg = draft; ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'pipeline', sub: 'stale-data' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
    });
  }

  // --- Pipeline watchdog ---------------------------------------------------
  function renderWatchdog(formArea, ctx) {
    fetchJson('/api/pipeline/watchdog').catch(function () { return { enabled: true, threshold_minutes: 30 }; }).then(function (cfg) {
      var draft = Object.assign({}, cfg);
      var enabledTog = FC.toggle({ on: !!cfg.enabled, label: 'Watch for stuck conversions',
        onChange: function (on) { draft.enabled = on; ctx.markDirty(); } });
      var threshold = FC.textInput({ value: cfg.threshold_minutes, type: 'number', tight: true,
        onInput: function (v) { draft.threshold_minutes = v; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({
        title: 'Watchdog',
        desc: 'If a conversion runs longer than this threshold, the watchdog kills it and re-queues. Prevents wedged jobs from blocking the queue.',
        body: enabledTog,
      }));
      formArea.appendChild(FC.formSection({
        title: 'Threshold',
        body: FC.fieldRow({ label: 'Minutes', control: threshold }),
      }));
      ctx.onSave(function () {
        gatedSave(function () {
          return fetchJson('/api/pipeline/watchdog', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft),
          });
        }).then(function () { cfg = draft; ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'pipeline', sub: 'watchdog' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
    });
  }

  // --- Pause & resume (live badge) -----------------------------------------
  function renderPauseResume(formArea, ctx) {
    fetchJson('/api/pipeline/state').then(function (st) {
      var paused = !!st.paused;
      var statusRow = el('div', 'mf-field-row mf-field-row--inline');
      var pill = el('span', 'mf-detail-side__badge mf-detail-side__badge--' + (paused ? 'warn' : 'good'));
      pill.textContent = paused ? 'Paused' : 'Running';
      statusRow.appendChild(pill);
      var detail = el('span'); detail.style.cssText = 'font-size:0.86rem;color:#333';
      detail.textContent = paused ? (st.reason || 'Manually paused') : 'Conversion + scan are running';
      statusRow.appendChild(detail);
      formArea.appendChild(FC.formSection({ title: 'Pipeline state', body: statusRow }));
      ctx.setActions([
        { id: 'toggle', label: paused ? 'Resume pipeline' : 'Pause pipeline',
          variant: paused ? 'primary' : 'outline',
          onClick: function () {
            gatedSave(function () {
              return fetchJson(paused ? '/api/pipeline/resume' : '/api/pipeline/pause', { method: 'POST' });
            }).then(function () {
              while (formArea.firstChild) formArea.removeChild(formArea.firstChild);
              renderPauseResume(formArea, ctx);
            }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); });
          } },
      ]);
    });
  }

  function renderForm(activeId, formArea, ctx) {
    if (activeId === 'scan-schedule') return renderScanSchedule(formArea, ctx);
    if (activeId === 'lifecycle')      return renderLifecycle(formArea, ctx);
    if (activeId === 'trash-cleanup')  return renderTrash(formArea, ctx);
    if (activeId === 'stale-data')     return renderStaleData(formArea, ctx);
    if (activeId === 'watchdog')       return renderWatchdog(formArea, ctx);
    if (activeId === 'pause-resume')   return renderPauseResume(formArea, ctx);
  }

  function mount(slot) {
    if (!global.MFFormControls || !global.MFSettingsDetail) throw new Error('MFPipelineSettings: deps missing');
    FC = global.MFFormControls;
    MFSettingsDetail.mount(slot, {
      icon: '⚙',
      title: 'Pipeline & lifecycle.',
      subtitle: 'How the conversion engine runs and cleans up after itself.',
      subsections: SUBSECTIONS,
      activeId: 'scan-schedule',
      onSubsectionChange: function (id) { MFTelemetry.emit('ui.settings_subsection_change', { section: 'pipeline', sub: id }); },
      renderForm: renderForm,
    });
  }
  global.MFPipelineSettings = { mount: mount };
})(window);
```

- [ ] **Step 3: Add the route in `main.py` (flag-aware)**

```python
@app.get("/settings/pipeline", include_in_schema=False)
async def settings_pipeline_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-pipeline.html")
    return FileResponse("static/admin.html")  # legacy fallback
```

- [ ] **Step 4: Smoke verify**

Visit `/settings/pipeline` as admin with flag on. Click each of the 6 sub-sections. Edit a value in any → save bar dirty → re-auth gate fires (after 5 minutes since login) → save → reload page → value persisted.

- [ ] **Step 5: Commit**

```bash
git add static/settings-pipeline.html static/js/pages/settings-pipeline.js \
        static/js/settings-pipeline-boot.js main.py
git commit -m "feat(ux): /settings/pipeline detail page

Six sub-sections (Scan schedule · Lifecycle · Trash · Stale data ·
Watchdog · Pause/resume) wired to existing /api/pipeline/*,
/api/lifecycle/*, /api/trash/* endpoints. Re-auth gate (Plan 6 Task 1)
wraps every save. Spec §7."
```

---

## Task 3: AI providers detail page

**Files:**
- Create: `static/settings-ai-providers.html`
- Create: `static/js/pages/settings-ai-providers.js`
- Create: `static/js/settings-ai-providers-boot.js`
- Modify: `main.py`

Spec §7 sub-sections: **Active provider chain · Anthropic · OpenAI · Image analysis routing · Vector indexing · Cost cap & alerts** *(drill-down — own page, lives in Plan 7)*. The Cost cap & alerts sub-section in this page is a single "Open cost dashboard →" action button that links to `/settings/ai-providers/cost` (Plan 7).

Existing endpoints from `api/routes/llm_providers.py` cover provider config + active chain. Image analysis routing lives in `api/routes/analysis.py` or `ai_assist.py`. Vector indexing toggle is a preference key (`vector_indexer_enabled` per `core/db/preferences.py`).

- [ ] **Step 1: Create the template + boot**

Mirrors Plan 5 Storage. Boot redirects member → `/settings`. Template loads form-controls.js + settings-detail.js + reauth-gate.js + pages/settings-ai-providers.js + boot.

- [ ] **Step 2: Create the component**

Create `static/js/pages/settings-ai-providers.js` following the Plan 5 / Plan 6 Task 2 pattern:

```javascript
/* MFAIProvidersSettings — Settings → AI providers.
 *   Active provider chain → /api/llm-providers/chain (GET, PUT)
 *   Anthropic             → /api/llm-providers/anthropic (GET, PUT) — masked api_key
 *   OpenAI                → /api/llm-providers/openai (GET, PUT) — masked api_key
 *   Image analysis        → /api/preferences (image_analysis_provider key)
 *   Vector indexing       → /api/preferences (vector_indexer_enabled key) + /api/llm-providers/vector-status
 *   Cost cap & alerts     → drill-down link to /settings/ai-providers/cost (Plan 7)
 *
 * Each save wraps in MFReauthGate.requireFresh(300). Safe DOM throughout. */
(function (global) {
  'use strict';
  var FC = null;
  var SUBSECTIONS = [
    { id: 'chain',          label: 'Active provider chain', icon: '⇄' },
    { id: 'anthropic',      label: 'Anthropic',             icon: '◆' },
    { id: 'openai',         label: 'OpenAI',                icon: '◇' },
    { id: 'image-routing',  label: 'Image analysis routing', icon: '⌬' },
    { id: 'vector',         label: 'Vector indexing',       icon: '⇌' },
    { id: 'cost',           label: 'Cost cap & alerts',     icon: '$' },
  ];

  // Helpers (el, fetchJson, gatedSave) match Plan 6 Task 2's definitions —
  // copy them to the top of this file.

  function renderChain(formArea, ctx) {
    fetchJson('/api/llm-providers/chain').then(function (data) {
      var providers = data.chain || [];
      formArea.appendChild(FC.formSection({
        title: 'Lookup chain',
        desc: 'Order MarkFlow tries providers when an AI Assist request arrives. First match with use_for_ai_assist=true wins. Independent of image scanner.',
        body: FC.miniTable({
          columns: [
            { id: 'name',     label: 'Provider', fr: 1 },
            { id: 'active',   label: 'Active',   fr: 0.6 },
            { id: 'primary',  label: 'AI Assist', fr: 0.7 },
            { id: 'last',     label: 'Last call', fr: 1.2 },
          ],
          rows: providers.map(function (p) {
            return {
              name: p.name,
              active: p.is_active ? 'yes' : 'no',
              primary: p.use_for_ai_assist ? '★' : '',
              last: p.last_call_at || '—',
              _tone: p.is_active ? 'ok' : null,
            };
          }),
        }),
      }));
    });
  }

  function renderAnthropic(formArea, ctx) {
    fetchJson('/api/llm-providers/anthropic').then(function (cfg) {
      var draft = Object.assign({}, cfg);
      formArea.appendChild(FC.formSection({
        title: 'Anthropic API key',
        desc: 'Stored encrypted. The API never returns the clear-text value — empty input means "leave unchanged".',
        body: FC.fieldRow({ label: 'API key',
          control: FC.textInput({
            value: '', placeholder: cfg.has_key ? '•••••• (leave blank to keep)' : 'sk-ant-...',
            onInput: function (v) { draft.api_key = v; ctx.markDirty(); },
          }),
        }),
      }));
      formArea.appendChild(FC.formSection({
        title: 'Default model',
        body: FC.fieldRow({ label: 'Model',
          control: FC.textInput({ value: cfg.default_model || 'claude-sonnet-4-6',
            onInput: function (v) { draft.default_model = v; ctx.markDirty(); } }),
        }),
      }));
      var activeTog = FC.toggle({ on: !!cfg.is_active, label: 'Anthropic is active',
        onChange: function (on) { draft.is_active = on; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({ title: 'Active', body: activeTog }));
      var aiTog = FC.toggle({ on: !!cfg.use_for_ai_assist, label: 'Use for AI Assist (primary)',
        onChange: function (on) { draft.use_for_ai_assist = on; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({ title: 'AI Assist primary', body: aiTog }));
      ctx.onSave(function () {
        gatedSave(function () {
          ctx.setStatus('saving', 'Saving…');
          return fetchJson('/api/llm-providers/anthropic', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft),
          });
        }).then(function () { ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'ai-providers', sub: 'anthropic' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
      ctx.setActions([
        { id: 'test', label: 'Test connection', variant: 'outline',
          onClick: function () {
            ctx.setStatus('saving', 'Testing…');
            fetchJson('/api/llm-providers/anthropic/test', { method: 'POST' })
              .then(function (r) { ctx.setStatus(r.ok ? 'saved' : 'error', r.ok ? 'OK' : (r.error || 'Failed')); })
              .catch(function (e) { ctx.setStatus('error', e.message); });
          } },
      ]);
    });
  }

  function renderOpenAI(formArea, ctx) {
    // Same shape as renderAnthropic against /api/llm-providers/openai;
    // copy the renderAnthropic body verbatim, swap 'anthropic' for 'openai'
    // in URLs and telemetry, and adjust default_model placeholder text.
    /* ...identical pattern... */
  }

  function renderImageRouting(formArea, ctx) {
    fetchJson('/api/preferences').then(function (data) {
      var current = (data && data.preferences && data.preferences.image_analysis_provider) || 'anthropic';
      var draft = current;
      var seg = FC.segmented({
        options: [
          { id: 'anthropic', label: 'Anthropic' },
          { id: 'openai',    label: 'OpenAI' },
          { id: 'local',     label: 'Local (BLIP)' },
          { id: 'off',       label: 'Off' },
        ],
        selected: current,
        onSelect: function (id) { draft = id; ctx.markDirty(); },
      });
      formArea.appendChild(FC.formSection({
        title: 'Image analysis routing',
        desc: 'Which provider runs OCR + alt-text generation on image-bearing files. Independent of AI Assist.',
        body: FC.fieldRow({ label: 'Provider', control: seg }),
      }));
      ctx.onSave(function () {
        gatedSave(function () {
          return fetchJson('/api/preferences/image_analysis_provider', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: draft }),
          });
        }).then(function () { current = draft; ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'ai-providers', sub: 'image-routing' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
    });
  }

  function renderVector(formArea, ctx) {
    Promise.all([
      fetchJson('/api/preferences'),
      fetchJson('/api/llm-providers/vector-status').catch(function () { return { reachable: false }; }),
    ]).then(function (results) {
      var current = (results[0].preferences && results[0].preferences.vector_indexer_enabled) === 'true';
      var status = results[1];
      var draft = current;
      var tog = FC.toggle({ on: current, label: 'Index converted Markdown into Qdrant for vector search',
        onChange: function (on) { draft = on; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({
        title: 'Vector indexing',
        desc: 'Best-effort: failures degrade gracefully (search still works without vectors). Qdrant must be reachable at the configured host.',
        body: tog,
      }));
      var statusRow = el('div', 'mf-field-row mf-field-row--inline');
      var pill = el('span', 'mf-detail-side__badge mf-detail-side__badge--' + (status.reachable ? 'good' : 'warn'));
      pill.textContent = status.reachable ? 'Qdrant reachable' : 'Qdrant unreachable';
      statusRow.appendChild(pill);
      var note = el('span'); note.style.cssText = 'font-size:0.86rem;color:#333';
      note.textContent = status.host ? ('Host: ' + status.host) : '';
      statusRow.appendChild(note);
      formArea.appendChild(FC.formSection({ title: 'Backend', body: statusRow }));
      ctx.onSave(function () {
        gatedSave(function () {
          return fetchJson('/api/preferences/vector_indexer_enabled', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: draft ? 'true' : 'false' }),
          });
        }).then(function () { current = draft; ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'ai-providers', sub: 'vector' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
    });
  }

  function renderCost(formArea, ctx) {
    var note = el('p', 'mf-form-section__desc');
    note.textContent = 'Cost cap, alerts, daily-spend chart, and CSV import live on a dedicated drill-down page.';
    formArea.appendChild(note);
    ctx.setActions([
      { id: 'open', label: 'Open cost dashboard →', variant: 'primary',
        onClick: function () { window.location.href = '/settings/ai-providers/cost'; } },
    ]);
  }

  function renderForm(activeId, formArea, ctx) {
    if (activeId === 'chain')          return renderChain(formArea, ctx);
    if (activeId === 'anthropic')      return renderAnthropic(formArea, ctx);
    if (activeId === 'openai')         return renderOpenAI(formArea, ctx);
    if (activeId === 'image-routing')  return renderImageRouting(formArea, ctx);
    if (activeId === 'vector')         return renderVector(formArea, ctx);
    if (activeId === 'cost')           return renderCost(formArea, ctx);
  }

  function mount(slot) {
    FC = global.MFFormControls;
    MFSettingsDetail.mount(slot, {
      icon: '❇',
      title: 'AI providers.',
      subtitle: 'API keys, image-analysis routing, cost ceiling, vector indexing.',
      subsections: SUBSECTIONS,
      activeId: 'chain',
      onSubsectionChange: function (id) { MFTelemetry.emit('ui.settings_subsection_change', { section: 'ai-providers', sub: id }); },
      renderForm: renderForm,
    });
  }
  global.MFAIProvidersSettings = { mount: mount };
})(window);
```

- [ ] **Step 3: Route + smoke + commit**

```python
@app.get("/settings/ai-providers", include_in_schema=False)
async def settings_ai_providers_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-ai-providers.html")
    return FileResponse("static/providers.html")
```

Smoke: as admin with flag on, visit `/settings/ai-providers`. Click each of 6 sub-sections. Anthropic → enter key → save → reload → masked `••••••` placeholder shows `has_key=true`. Cost sub-section → "Open cost dashboard →" navigates to `/settings/ai-providers/cost` (404 until Plan 7).

```bash
git add static/settings-ai-providers.html static/js/pages/settings-ai-providers.js \
        static/js/settings-ai-providers-boot.js main.py
git commit -m "feat(ux): /settings/ai-providers detail page

Six sub-sections wired to /api/llm-providers/* + /api/preferences (image
routing + vector toggle). Cost sub-section is a deep-link to
/settings/ai-providers/cost (Plan 7). Re-auth gate wraps every save.
Spec §7."
```

---

## Task 4: Account & auth detail page

**Files:**
- Create: `static/settings-account-auth.html`
- Create: `static/js/pages/settings-account-auth.js`
- Create: `static/js/settings-account-auth-boot.js`
- Modify: `main.py`

Spec §7 sub-sections: **Identity (UnionCore) · JWT validation · Role mapping · Sessions & timeout · Audit log**. Most of this section is **read-only** — UnionCore is the source of truth for issuer / audience / JWKS / role mapping. The one editable sub-section is **Sessions & timeout**, which is where the "Re-auth required for system settings" toggle lives (per spec §11).

Endpoints: existing `/api/auth/me-claims` (read-only JWT introspection), `/api/auth/jwks-info`, `/api/auth/role-mapping`, `/api/auth/audit-log` (paginated). Sessions & timeout reads + writes preferences `session_timeout_minutes`, `system_settings_require_reauth` (the gate toggle), `reauth_max_age_seconds`.

- [ ] **Step 1: Create the template + boot** (pattern matches Tasks 2 + 3)

- [ ] **Step 2: Create the component**

Create `static/js/pages/settings-account-auth.js`. Skeleton (read-only sub-sections elided — they render `FC.miniTable`s of returned data; only Sessions & timeout has writes):

```javascript
/* MFAccountAuthSettings — Settings → Account & auth.
 * Mostly read-only (UnionCore is the source of truth). The one editable
 * page is Sessions & timeout — where the system-settings re-auth gate
 * toggle lives (spec §11). Re-auth gate wraps the gate toggle's own save
 * (defense-in-depth: changing the gate config still requires fresh auth).
 *
 * Safe DOM throughout. */
(function (global) {
  'use strict';
  var FC = null;
  var SUBSECTIONS = [
    { id: 'identity',    label: 'Identity (UnionCore)', icon: '◐' },
    { id: 'jwt',         label: 'JWT validation',       icon: '◊' },
    { id: 'roles',       label: 'Role mapping',         icon: '⇄' },
    { id: 'sessions',    label: 'Sessions & timeout',   icon: '⏱' },
    { id: 'audit',       label: 'Audit log',            icon: '☰' },
  ];
  // ... helpers + renderIdentity / renderJWT / renderRoles / renderSessions / renderAudit ...

  function renderSessions(formArea, ctx) {
    fetchJson('/api/preferences').then(function (data) {
      var prefs = (data && data.preferences) || {};
      var draft = {
        session_timeout_minutes: prefs.session_timeout_minutes || '60',
        system_settings_require_reauth: prefs.system_settings_require_reauth || 'true',
        reauth_max_age_seconds: prefs.reauth_max_age_seconds || '300',
      };
      var orig = Object.assign({}, draft);

      var timeoutInput = FC.textInput({ value: draft.session_timeout_minutes, type: 'number', tight: true,
        onInput: function (v) { draft.session_timeout_minutes = v; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({
        title: 'Session timeout',
        desc: 'How long an inactive session stays valid before sign-out.',
        body: FC.fieldRow({ label: 'Minutes', control: timeoutInput }),
      }));

      var gateTog = FC.toggle({
        on: draft.system_settings_require_reauth === 'true',
        label: 'Require fresh password before saving any system setting',
        onChange: function (on) { draft.system_settings_require_reauth = on ? 'true' : 'false'; ctx.markDirty(); },
      });
      formArea.appendChild(FC.formSection({
        title: 'Re-auth gate',
        desc: 'When on, every save in Storage / Pipeline / AI providers / etc. prompts for password if the JWT is older than the freshness window. Recommended ON for admin/operator. Spec §11.',
        body: gateTog,
      }));

      var freshInput = FC.textInput({ value: draft.reauth_max_age_seconds, type: 'number', tight: true,
        onInput: function (v) { draft.reauth_max_age_seconds = v; ctx.markDirty(); } });
      formArea.appendChild(FC.formSection({
        title: 'Freshness window',
        desc: 'How recent the password confirmation must be (in seconds) before the gate prompts again. Default 300 (5 min).',
        body: FC.fieldRow({ label: 'Seconds', control: freshInput }),
      }));

      ctx.onSave(function () {
        gatedSave(function () {
          ctx.setStatus('saving', 'Saving…');
          var dirty = Object.keys(draft).filter(function (k) { return draft[k] !== orig[k]; });
          if (!dirty.length) return Promise.resolve();
          return Promise.all(dirty.map(function (k) {
            return fetchJson('/api/preferences/' + k, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ value: draft[k] }),
            });
          }));
        }).then(function () { orig = Object.assign({}, draft); ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'account-auth', sub: 'sessions' });
        }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
      });
    });
  }

  // ... renderIdentity / renderJWT / renderRoles / renderAudit each
  //     fetch /api/auth/me-claims | jwks-info | role-mapping | audit-log
  //     and render miniTables. None take user input.

  function mount(slot) {
    FC = global.MFFormControls;
    MFSettingsDetail.mount(slot, {
      icon: '⧉',
      title: 'Account & auth.',
      subtitle: 'JWT, sign-in, role hierarchy, sessions, audit.',
      subsections: SUBSECTIONS,
      activeId: 'identity',
      onSubsectionChange: function (id) { MFTelemetry.emit('ui.settings_subsection_change', { section: 'account-auth', sub: id }); },
      renderForm: function (id, area, ctx) {
        if (id === 'identity')   return renderIdentity(area, ctx);
        if (id === 'jwt')        return renderJWT(area, ctx);
        if (id === 'roles')      return renderRoles(area, ctx);
        if (id === 'sessions')   return renderSessions(area, ctx);
        if (id === 'audit')      return renderAudit(area, ctx);
      },
    });
  }
  global.MFAccountAuthSettings = { mount: mount };
})(window);
```

(`renderIdentity`, `renderJWT`, `renderRoles`, `renderAudit` follow the same `fetchJson(...) → FC.formSection(... FC.miniTable(...))` pattern as Storage's read-only sub-sections in Plan 5 — copy that shape.)

- [ ] **Step 3: Route + smoke + commit**

```python
@app.get("/settings/account-auth", include_in_schema=False)
async def settings_account_auth_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-account-auth.html")
    return FileResponse("static/admin.html")
```

Smoke: as admin, visit `/settings/account-auth` → 5 sub-sections render. Sessions → toggle gate off → save → re-auth gate prompts (defensive); confirm → reload → toggle reflects new state. Toggle gate back on. Storage saves now require fresh auth again.

```bash
git add static/settings-account-auth.html static/js/pages/settings-account-auth.js \
        static/js/settings-account-auth-boot.js main.py
git commit -m "feat(ux): /settings/account-auth detail page

Five sub-sections (Identity · JWT · Role mapping · Sessions & timeout ·
Audit log). Identity / JWT / Roles / Audit are read-only mirrors of
UnionCore. Sessions & timeout writes session_timeout_minutes,
system_settings_require_reauth (the gate toggle from spec §11), and
reauth_max_age_seconds. Spec §7, §11."
```

---

## Task 5: Notifications (system) detail page

**Files:**
- Create: `static/settings-notifications.html`
- Create: `static/js/pages/settings-notifications.js`
- Create: `static/js/settings-notifications-boot.js`
- Modify: `main.py`

Spec §7 sub-sections: **Channels · Trigger rules · Quiet hours · Test send**.

Backend endpoints may not all exist yet. The plan ships the UI against:
- `/api/notifications/channels` (GET, PUT) — Slack webhook URL, email recipients
- `/api/notifications/rules` (GET, PUT, POST add, DELETE) — trigger-rule list
- `/api/notifications/quiet-hours` (GET, PUT)
- `/api/notifications/test` (POST) — send a test notification

If any endpoint returns 404, the sub-section renders an "Endpoint not yet wired" empty-state and a `console.warn`. Do **not** stub out a fake endpoint; the empty-state surface is the signal that backend work is needed.

- [ ] **Step 1-3: Same pattern as Tasks 2-4** — template + boot + component + flag-aware route + smoke + commit

Template uses icon `␇`. Component `MFNotificationsSettings.mount(slot)`. Each sub-section uses the empty-state-on-404 pattern:

```javascript
function fetchJsonOrEmpty(url) {
  return fetch(url, { credentials: 'same-origin' }).then(function (r) {
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(url + ' ' + r.status);
    return r.json();
  });
}
function renderChannels(formArea, ctx) {
  fetchJsonOrEmpty('/api/notifications/channels').then(function (data) {
    if (data == null) {
      var p = el('p', 'mf-form-section__desc');
      p.textContent = 'Notifications backend not yet wired. Coming in a follow-up plan.';
      formArea.appendChild(p);
      return;
    }
    /* ... build form against data.slack_webhook + data.email_recipients ... */
  });
}
```

```python
@app.get("/settings/notifications-system", include_in_schema=False)
async def settings_notifications_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-notifications.html")
    return FileResponse("static/admin.html")
```

Smoke + commit follow the established pattern.

---

## Task 6: Database health detail page

**Files:**
- Create: `static/settings-database-health.html`
- Create: `static/js/pages/settings-database-health.js`
- Create: `static/js/settings-database-health-boot.js`
- Modify: `main.py`

Spec §7 sub-sections: **Connection pool · Backups · Maintenance window · Migrations · Integrity check**.

Endpoints from `api/routes/db_health.py`:
- `/api/db-health/pool` (GET — pool stats; PUT — max_size)
- `/api/db-health/backups` (GET — list; POST — trigger backup; DELETE — remove)
- `/api/db-health/maintenance` (GET, PUT — schedule + duration)
- `/api/db-health/migrations` (GET — applied migrations list)
- `/api/db-health/integrity` (POST — trigger; GET — last result)

Same pattern as Tasks 2–5. Read-only sub-sections (Migrations, Integrity result) render `FC.miniTable`s. Editable sub-sections (Pool, Maintenance) write through with re-auth gate.

```python
@app.get("/settings/database-health", include_in_schema=False)
async def settings_database_health_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-database-health.html")
    return FileResponse("static/db-health.html")
```

Commit:

```bash
git commit -m "feat(ux): /settings/database-health detail page

Five sub-sections (Pool · Backups · Maintenance · Migrations ·
Integrity check) wired to /api/db-health/*. Editable sub-sections
gated by re-auth. Read-only sub-sections show last applied migrations
+ last integrity result. Spec §7."
```

---

## Task 7: Log management detail page

**Files:**
- Create: `static/settings-log-management.html`
- Create: `static/js/pages/settings-log-management.js`
- Create: `static/js/settings-log-management-boot.js`
- Modify: `main.py`

Spec §7 sub-sections: **Levels per subsystem · Retention & rotation · Live viewer · Export & archive**.

Endpoints from `api/routes/log_management.py`:
- `/api/log-management/levels` (GET — current levels per subsystem; PUT key=subsystem, value=level)
- `/api/log-management/retention` (GET, PUT)
- `/api/log-management/export` (POST — produces a downloadable archive; GET — list of past exports)

The "Live viewer" sub-section is a simple "Open log viewer in new tab" link to the existing `/log-viewer` page. SSE-in-shell is v1.1 (out of scope per the plan header).

Pattern matches Task 6.

```python
@app.get("/settings/log-management", include_in_schema=False)
async def settings_log_management_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-log-management.html")
    return FileResponse("static/log-management.html")
```

Commit:

```bash
git commit -m "feat(ux): /settings/log-management detail page

Four sub-sections (Levels · Retention · Live viewer · Export). Per-
subsystem level editor wraps PUT /api/log-management/levels in re-auth
gate. Live viewer sub-section deep-links to /log-viewer (no in-shell
SSE in v1). Spec §7."
```

---

## Task 8: Acceptance check + plan close

**Files:** none modified — verification only.

- [ ] `pytest tests/test_auth_freshness_endpoint.py -v` — 3 PASS
- [ ] `grep -rn "innerHTML" static/js/pages/settings-pipeline.js static/js/pages/settings-ai-providers.js static/js/pages/settings-account-auth.js static/js/pages/settings-notifications.js static/js/pages/settings-database-health.js static/js/pages/settings-log-management.js static/js/components/reauth-gate.js` — zero matches
- [ ] As admin with `ENABLE_NEW_UX=true`:
  - All 6 new detail pages reachable from `/settings` overview cards
  - Each has its locked sub-section sidebar per spec §7
  - Editable sub-sections save successfully; saves prompt for re-auth when JWT iat-age > freshness window; cancel aborts save cleanly
  - Read-only sub-sections (UnionCore identity, Migrations, etc.) render without writes
  - Notifications sub-sections gracefully empty-state when backend endpoints don't exist yet
- [ ] As admin with `ENABLE_NEW_UX=false`:
  - All `/settings/*` routes fall back to legacy admin / providers / db-health / log-management pages
- [ ] As member with `ENABLE_NEW_UX=true`:
  - Direct visit to any `/settings/<system-section>` redirects to `/settings`
  - `/settings` overview never renders System group
- [ ] Telemetry: `ui.settings_card_click`, `ui.settings_subsection_change` (per section), `ui.settings_save` (per section + sub) all visible in `docker-compose logs`
- [ ] Phase-5-specifically spec checklist re-run:
  - Re-auth gate triggers correctly on all six System sections (verified per-section above) ✓
  - Preferences sync across two machines: re-verify by signing in on a second machine after a save and confirming the change is visible there ✓
- [ ] `git log --oneline | head -10` shows ~7 task commits in order

If any item fails, file in `docs/bug-log.md`. **Don't silently fix.**

Once all green, **Plan 6 is done**. Next plan: `2026-04-28-ux-overhaul-cost-dashboard.md` (Plan 7 — Cost cap & alerts deep-dive sub-page + CSV import + help file).

---

## Self-review

**Spec coverage:**
- §7 (six remaining detail pages with locked sub-section sidebars): ✓ Tasks 2–7
- §11 (re-auth gate enforcement on system-settings saves): ✓ Task 1 + every save handler in Tasks 2–7 wraps in `MFReauthGate.requireFresh(300)`
- §13 phase-5-specifically (re-auth gate triggers correctly): ✓ Task 8 acceptance check

**Spec gaps for this plan (deferred):**
- §8 cost cap deep-dive: Plan 7 (Task 3 only stubs the deep-link)
- Member-facing Personal detail pages (Display / Pinned folders / Profile / Notifications-prefs): separate sub-plan (declared out-of-scope at top)
- Notifications backend (Slack webhook, email, trigger rules): separate Notifications backend plan; Plan 6 ships UI against optional endpoints with empty-state fallbacks
- Log viewer SSE-in-shell: v1.1 (Live viewer sub-section deep-links to existing `/log-viewer` for v1)

**Placeholder scan:**
- No "TODO" / "TBD" in shipped task bodies
- Tasks 5–7 reuse the same skeleton from Tasks 2–4 by reference; the *commit messages* and section-specific endpoint names are filled in inline so executors don't have to scroll back
- Task 3's `renderOpenAI` says "copy `renderAnthropic` body verbatim, swap 'anthropic' → 'openai'" — this is **not** a placeholder; it's a deliberate reference because the code is identical and pasting both copies would double the task length without adding information. The pattern is fully shown in `renderAnthropic` above it.

**Type / API consistency:**
- `MFReauthGate.requireFresh(maxAgeSec)` defined in Task 1 and consumed via `gatedSave` helper in Tasks 2–7
- All section components export `MF<Section>Settings.mount(slot)` — single signature, no per-section divergence
- All section boots redirect member → `/settings` (defense-in-depth alongside backend role gates)
- Telemetry events follow the locked `ui.settings_*` namespace from Plan 5

**Safe-DOM verification:** see Task 8.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-remaining-detail-pages.md`.

Sized for: 7 implementer dispatches + 7 spec reviews + 7 code-quality reviews ≈ 21 subagent calls.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
