# UX Overhaul — Stateful Chrome Implementation Plan (Plan 1C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the stateful pieces of the chrome — preferences client (localStorage cache + debounced server sync), telemetry helper, avatar menu popover (role-gated content), layout-mode popover (three options with `⌘\` cycle), and wire them into the static chrome's `onClick` stubs from Plan 1B. End state: `static/dev-chrome.html` is a fully-functional preview of every chrome interaction.

**Architecture:** Same vanilla-JS-with-globals pattern as Plan 1B — `MFPrefs`, `MFTelemetry`, `MFAvatarMenu`, `MFLayoutPopover`. Popovers append to `document.body` (not the nav) so they aren't clipped by `overflow:hidden`. Click-outside and Escape close. `MFPrefs` debounces PUT requests at 500ms, mirrors all writes through `localStorage`. Telemetry events fire-and-forget via `fetch` (failures swallowed — instrumentation must never break the UI). **Safe DOM construction throughout — zero `innerHTML` with template literals.**

**Tech stack:** Vanilla HTML/CSS/JS · Python/FastAPI for telemetry endpoint · pytest for backend tests

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` — covers §3 (layout modes), §6 (avatar menu content + role gating), §10 (preferences persistence), §13 (telemetry events).

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/avatar-menu.html`, `layout-onboarding.html`

**Out of scope (deferred):**
- Mounting chrome on actual pages (Plan 4 — IA shift)
- Search page rendering / layout mode switching at the page level (Plan 3)
- Document card component (Plan 2)
- Settings detail pages (Plans 5–7)

**Prerequisites:** Plan 1A (foundation setup) and Plan 1B (static chrome) must both be complete. Run `git log --oneline | head -20` and confirm both plan commits are present.

---

## Model + effort

| Role | Model | Effort |
|------|-------|--------|
| Implementer | Sonnet | med (4-8h) |
| Reviewer | Sonnet | low (2-3h) |

**Reasoning:** Prefs client (localStorage cache + 500ms debounced PUT), telemetry helper (fire-and-forget), avatar/layout popovers with click-outside + Escape. Subtle async + event-lifecycle but well-bounded. Reviewer needs to follow the popover state machine + debounce semantics, hence small-but-not-trivial review effort.

**Execution mode:** Dispatch this plan via `superpowers:subagent-driven-development`. Each role is a separate `Agent` call — `Agent({model: "sonnet", ...})` for implementation, `Agent({model: "sonnet", ...})` for review. A single-session `executing-plans` read will *not* switch models on its own; this metadata is routing input for the orchestrator.

**Source:** [`docs/spreadsheet/phase_model_plan.xlsx`](../../spreadsheet/phase_model_plan.xlsx)

---

## File structure (this plan creates / modifies)

**Create:**
- `static/js/preferences.js`
- `static/js/telemetry.js`
- `static/js/components/avatar-menu.js`
- `static/js/components/layout-popover.js`
- `static/js/keybinds.js` — global keyboard shortcuts (just `⌘\` for now)
- `api/routes/telemetry.py`
- `tests/test_telemetry_endpoint.py`

**Modify:**
- `static/css/components.css` — append avatar-menu and layout-popover styles
- `static/dev-chrome.html` — load the new scripts
- `static/dev-chrome.js` — wire static chrome's onClick stubs to the popovers; demonstrate preferences subscribe
- `main.py` — register telemetry router

---

## Task 1: Preferences client module

**Files:**
- Create: `static/js/preferences.js`

Manual smoke verification (no JS test runner). The module exposes load / get / set / setMany / subscribe and handles localStorage caching and debounced server sync.

- [ ] **Step 1: Create the module**

Create `static/js/preferences.js`:

```javascript
/* Client per-user preferences. localStorage-backed cache + debounced server sync.
 * Spec §10. Server endpoints: GET/PUT /api/user-prefs (Plan 1A Task 8).
 * NOTE: /api/user-prefs is the per-user store (UnionCore sub-keyed). Distinct
 * from /api/preferences which is system-level singleton prefs — do not conflate.
 *
 * Usage:
 *   await MFPrefs.load();                      // hydrates from server, falls back to LS
 *   MFPrefs.get('layout');                      // sync after load()
 *   await MFPrefs.set('layout', 'recent');      // local + queued PUT
 *   await MFPrefs.setMany({layout:'recent', density:'compact'});
 *   var unsub = MFPrefs.subscribe('layout', function(v) { ... });
 *
 * Safe DOM: this module touches no DOM.
 */
(function (global) {
  'use strict';

  var LS_KEY = 'mf:preferences:v1';
  var ENDPOINT = '/api/user-prefs';
  var DEBOUNCE_MS = 500;

  var prefs = {};
  var pending = null;
  var saveTimer = null;
  var subs = {};   // key -> array of callbacks

  function readLocal() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); }
    catch (e) { return {}; }
  }
  function writeLocal() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(prefs)); } catch (e) {}
  }

  function fire(key) {
    var arr = subs[key];
    if (!arr) return;
    for (var i = 0; i < arr.length; i++) {
      try { arr[i](prefs[key]); } catch (e) { console.error(e); }
    }
  }
  function fireAll() {
    for (var k in subs) if (Object.prototype.hasOwnProperty.call(subs, k)) fire(k);
  }

  function schedulePut(updates) {
    pending = Object.assign(pending || {}, updates);
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, DEBOUNCE_MS);
  }

  function flush() {
    if (!pending) return;
    var body = pending;
    pending = null;
    saveTimer = null;
    fetch(ENDPOINT, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) {
        console.warn('mf-prefs: PUT failed', r.status);
        // re-queue for next set() to retry
        pending = Object.assign(body, pending || {});
        return null;
      }
      return r.json();
    }).then(function (fresh) {
      if (fresh) { prefs = fresh; writeLocal(); fireAll(); }
    }).catch(function (e) {
      console.warn('mf-prefs: PUT error', e);
      pending = Object.assign(body, pending || {});
    });
  }

  function load() {
    // Optimistic: localStorage first so first paint is fast.
    prefs = readLocal();
    fireAll();
    return fetch(ENDPOINT, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('preferences load failed: ' + r.status);
        return r.json();
      })
      .then(function (server) {
        prefs = server;     // server wins on conflict
        writeLocal();
        fireAll();
      })
      .catch(function (e) {
        console.warn('mf-prefs: server load failed, using localStorage', e);
      });
  }

  function get(key) { return prefs[key]; }

  function set(key, value) {
    if (prefs[key] === value) return Promise.resolve();
    prefs[key] = value;
    writeLocal();
    fire(key);
    schedulePut(makeOne(key, value));
    return Promise.resolve();
  }
  function makeOne(k, v) { var o = {}; o[k] = v; return o; }

  function setMany(updates) {
    var changed = false;
    var keys = Object.keys(updates);
    for (var i = 0; i < keys.length; i++) {
      if (prefs[keys[i]] !== updates[keys[i]]) {
        prefs[keys[i]] = updates[keys[i]];
        changed = true;
      }
    }
    if (!changed) return Promise.resolve();
    writeLocal();
    for (var j = 0; j < keys.length; j++) fire(keys[j]);
    schedulePut(updates);
    return Promise.resolve();
  }

  function subscribe(key, cb) {
    if (!subs[key]) subs[key] = [];
    subs[key].push(cb);
    return function unsubscribe() {
      var arr = subs[key];
      if (!arr) return;
      var i = arr.indexOf(cb);
      if (i >= 0) arr.splice(i, 1);
    };
  }

  global.MFPrefs = {
    load: load, get: get, set: set, setMany: setMany, subscribe: subscribe
  };
})(window);
```

- [ ] **Step 2: Smoke verify in dev-chrome**

This will be wired into `dev-chrome.js` in Task 7. For now, manually load the script and exercise it:

```bash
docker-compose up -d
```

Visit `http://localhost:8000/static/dev-chrome.html`. Open DevTools Console:

```javascript
await MFPrefs.load();
console.log('layout:', MFPrefs.get('layout'));
MFPrefs.subscribe('layout', function(v) { console.log('layout changed ->', v); });
await MFPrefs.set('layout', 'recent');
// Wait 500ms, check Network tab -> PUT /api/user-prefs with {"layout":"recent"}
```

If unauthenticated GET 401s, the localStorage fallback should still work and the console shouldn't throw — just a warning.

- [ ] **Step 3: Commit**

```bash
git add static/js/preferences.js static/dev-chrome.html
git commit -m "feat(prefs): client preferences module — LS cache + debounced PUT

500ms debounce on server PUTs. localStorage write-through for instant
first paint. Server-wins on conflict (re-fetched after PUT). Subscribe
API for reactive UI. Failed PUTs re-queue for the next set() to retry.
No DOM touches. Spec §10."
```

---

## Task 2: Telemetry helper (client + server endpoint)

**Files:**
- Create: `static/js/telemetry.js`
- Create: `api/routes/telemetry.py`
- Create: `tests/test_telemetry_endpoint.py`
- Modify: `main.py` to register the router

Spec §13 lists at minimum these events: `ui.layout_mode_selected`, `ui.density_toggle`, `ui.advanced_toggle`, `ui.hover_preview_shown`, `ui.context_menu_action`. This task ships the helper and endpoint; consumers (avatar-menu, layout-popover, document card later) emit events via `MFTelemetry.emit('event', {...})`.

- [ ] **Step 1: Write the failing endpoint test**

Create `tests/test_telemetry_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_telemetry_post_accepts_event(client):
    r = client.post(
        "/api/telemetry",
        json={"event": "ui.layout_mode_selected", "props": {"mode": "minimal"}},
    )
    assert r.status_code == 204


def test_telemetry_post_rejects_missing_event(client):
    r = client.post("/api/telemetry", json={"props": {"mode": "minimal"}})
    assert r.status_code == 422


def test_telemetry_post_rejects_non_ui_event(client):
    """Defensive: only ui.* events accepted (prevent accidental log floods)."""
    r = client.post(
        "/api/telemetry",
        json={"event": "system.boot", "props": {}},
    )
    assert r.status_code == 400


def test_telemetry_post_no_auth_required(client):
    """Telemetry endpoint is unauthenticated — instrumentation must work
    even on the login page."""
    r = client.post(
        "/api/telemetry",
        json={"event": "ui.density_toggle", "props": {"to": "list"}},
    )
    assert r.status_code == 204
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telemetry_endpoint.py -v`

Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Implement the endpoint**

Create `api/routes/telemetry.py`:

```python
"""Telemetry endpoint — UI event sink.

Events are logged via structlog to a dedicated subsystem so they can be
filtered easily. Unauthenticated by design (instrumentation should work
on the login page too). Only ui.* events accepted to prevent accidental
log floods if the wrong helper is called.

Spec §13 — preflight checklist: telemetry event taxonomy.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
import structlog

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])
log = structlog.get_logger("ui_telemetry")


class TelemetryEvent(BaseModel):
    event: str = Field(..., min_length=1, max_length=64)
    props: dict = Field(default_factory=dict)


@router.post("", status_code=204)
async def emit(payload: TelemetryEvent, request: Request) -> Response:
    if not payload.event.startswith("ui."):
        raise HTTPException(
            status_code=400,
            detail="telemetry events must start with 'ui.'",
        )
    log.info(
        payload.event,
        ua=request.headers.get("user-agent", "")[:200],
        **payload.props,
    )
    return Response(status_code=204)
```

- [ ] **Step 4: Wire into `main.py`**

Add to `main.py`:

```python
from api.routes import telemetry as telemetry_routes
app.include_router(telemetry_routes.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_telemetry_endpoint.py -v`

Expected: 4 PASS.

- [ ] **Step 6: Create the client helper**

Create `static/js/telemetry.js`:

```javascript
/* UI telemetry — fire-and-forget POST /api/telemetry.
 * Spec §13. Failures are logged but never block UI.
 *
 * Usage:
 *   MFTelemetry.emit('ui.layout_mode_selected', { mode: 'minimal' });
 *
 * Safe DOM: this module touches no DOM.
 */
(function (global) {
  'use strict';

  var ENDPOINT = '/api/telemetry';

  function emit(event, props) {
    if (typeof event !== 'string' || event.indexOf('ui.') !== 0) {
      console.warn('mf-telemetry: ignored non-ui event:', event);
      return;
    }
    var body = JSON.stringify({ event: event, props: props || {} });
    try {
      // sendBeacon is best-effort and survives page unload.
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon(ENDPOINT, blob);
        return;
      }
    } catch (e) { /* fall through to fetch */ }
    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
      credentials: 'same-origin',
      keepalive: true
    }).catch(function (e) {
      console.warn('mf-telemetry: emit failed', e);
    });
  }

  global.MFTelemetry = { emit: emit };
})(window);
```

- [ ] **Step 7: Smoke check the client**

Open DevTools console at `/static/dev-chrome.html`:

```javascript
MFTelemetry.emit('ui.density_toggle', { to: 'compact' });
// Network tab -> POST /api/telemetry with that body, 204 response
// Check docker-compose logs app | grep ui_telemetry -> structlog line
```

- [ ] **Step 8: Commit**

```bash
git add static/js/telemetry.js api/routes/telemetry.py main.py tests/test_telemetry_endpoint.py
git commit -m "feat(ux): telemetry helper + /api/telemetry sink endpoint

Client uses sendBeacon when available, fetch with keepalive otherwise.
Server logs events via structlog to ui_telemetry subsystem. Only ui.*
events accepted (prevents accidental log floods). Unauthenticated by
design — instrumentation must work on login pages too. Spec §13."
```

---

## Task 3: Avatar menu popover component

**Files:**
- Create: `static/js/components/avatar-menu.js`

The big one. Builds the role-gated dropdown menu. **All construction via createElement / textContent / appendChild — no innerHTML anywhere.** Safe DOM is non-negotiable here because some content (user name, role, build sha) is dynamic.

The menu is a single popover instance per page, attached to `document.body` to escape any `overflow:hidden` ancestors. It re-anchors to the trigger button on each open.

- [ ] **Step 1: Create the component scaffold (header + render functions)**

Create `static/js/components/avatar-menu.js`:

```javascript
/* Avatar dropdown menu. Role-gated content. Spec §6.
 *
 * Usage:
 *   var menu = MFAvatarMenu.create({
 *     user: { name: 'Xerxes', role: 'admin', scope: 'IBEW Local 46' },
 *     build: { version: 'v0.34.2-dev', branch: 'main', sha: 'd15ddb3', date: '2026-04-28' },
 *     onSelectItem: function(id) { ... },
 *     onSignOut: function() { ... }
 *   });
 *   menu.openAt(avatarButton);
 *   menu.close();
 *
 * Safe DOM throughout — every text via textContent.
 */
(function (global) {
  'use strict';

  // Personal items shown to all roles. API keys gated to operator+.
  var PERSONAL_ITEMS = [
    { id: 'profile',       label: 'Profile',                 minRole: 'member'   },
    { id: 'display',       label: 'Display preferences',     minRole: 'member'   },
    { id: 'pinned',        label: 'Pinned folders & topics', minRole: 'member'   },
    { id: 'notifications', label: 'Notifications',           minRole: 'member'   },
    { id: 'api-keys',      label: 'API keys',                minRole: 'operator' }
  ];

  // System items only for operator+ (rendered with Admin only gate badge).
  var SYSTEM_ITEMS = [
    { id: 'storage',  label: 'Storage & mounts' },
    { id: 'pipeline', label: 'Pipeline & lifecycle' },
    { id: 'ai',       label: 'AI providers' },
    { id: 'auth',     label: 'Account & auth' },
    { id: 'db',       label: 'Database health' },
    { id: 'logs',     label: 'Log management' }
  ];

  var ROLE_RANK = { member: 0, operator: 1, admin: 2 };

  function meetsRole(item, userRole) {
    return ROLE_RANK[userRole] >= ROLE_RANK[item.minRole || 'member'];
  }

  function el(tag, className) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    return n;
  }

  function buildHeader(user) {
    var head = el('div', 'mf-av-menu__who');
    head.appendChild(el('div', 'mf-av-menu__avatar'));

    var text = el('div', 'mf-av-menu__who-text');
    var name = el('div', 'mf-av-menu__who-name');
    name.textContent = user.name || '';
    text.appendChild(name);

    var role = el('div', 'mf-av-menu__who-role');
    var rolePill = el('span', 'mf-role-pill mf-role-pill--' + (user.role || 'member'));
    rolePill.textContent = user.role || 'member';
    role.appendChild(rolePill);
    if (user.scope) {
      role.appendChild(document.createTextNode(' ' + user.scope));
    }
    text.appendChild(role);

    head.appendChild(text);
    return head;
  }

  function buildSectionLabel(text, opts) {
    var lab = el('div', 'mf-av-menu__sec-label');
    var span = el('span');
    span.textContent = text;
    lab.appendChild(span);
    if (opts && opts.adminOnly) {
      var gate = el('span', 'mf-av-menu__gate');
      gate.textContent = 'Admin only';
      lab.appendChild(gate);
    }
    return lab;
  }

  function buildItem(item, opts) {
    var a = el('a', 'mf-av-menu__item');
    if (opts && opts.danger) a.className += ' mf-av-menu__item--danger';
    a.setAttribute('role', 'menuitem');
    a.setAttribute('data-mf-item', item.id);
    a.appendChild(el('span', 'mf-av-menu__ico'));
    var label = el('span', 'mf-av-menu__grow');
    label.textContent = item.label;
    a.appendChild(label);
    if (opts && opts.kbd) {
      var kbd = el('span', 'mf-av-menu__kbd');
      kbd.textContent = opts.kbd;
      a.appendChild(kbd);
    }
    return a;
  }

  function buildSep() { return el('div', 'mf-av-menu__sep'); }

  function buildCta(label, id) {
    var cta = el('div', 'mf-av-menu__cta');
    cta.setAttribute('data-mf-item', id);
    var l = el('span'); l.textContent = label; cta.appendChild(l);
    var r = el('span'); r.textContent = '→'; cta.appendChild(r);
    return cta;
  }

  function buildBuild(build) {
    var b = el('div', 'mf-av-menu__build');
    var v = el('span', 'mf-av-menu__build-v');
    v.textContent = (build && build.version) || 'dev';
    b.appendChild(v);
    b.appendChild(document.createTextNode(' · '));
    var branch = el('span', 'mf-av-menu__build-b');
    branch.textContent = (build && build.branch) || '';
    b.appendChild(branch);
    b.appendChild(document.createElement('br'));
    b.appendChild(document.createTextNode('build '));
    var sha = el('span'); sha.style.color = 'var(--mf-color-text)';
    sha.textContent = (build && build.sha) || '';
    b.appendChild(sha);
    if (build && build.date) {
      b.appendChild(document.createTextNode(' · ' + build.date));
    }
    return b;
  }

  function create(opts) {
    var user = (opts && opts.user) || { name: '', role: 'member' };
    var build = (opts && opts.build) || null;
    var onSelectItem = (opts && opts.onSelectItem) || function () {};
    var onSignOut = (opts && opts.onSignOut) || function () {};

    var root = el('div', 'mf-av-menu');
    root.setAttribute('role', 'menu');
    root.style.display = 'none';

    // Header
    root.appendChild(buildHeader(user));

    // Personal section
    root.appendChild(buildSectionLabel('Personal'));
    PERSONAL_ITEMS.forEach(function (item) {
      if (meetsRole(item, user.role)) root.appendChild(buildItem(item));
    });

    // System section (admin/operator only)
    if (user.role === 'admin' || user.role === 'operator') {
      root.appendChild(buildSectionLabel('System', { adminOnly: true }));
      SYSTEM_ITEMS.forEach(function (item) {
        root.appendChild(buildItem(item));
      });
    }

    root.appendChild(buildSep());
    root.appendChild(buildCta('All settings', 'all-settings'));
    root.appendChild(buildSep());

    // Help section
    root.appendChild(buildSectionLabel('Help'));
    root.appendChild(buildItem({ id: 'help',      label: 'Help & docs' }));
    root.appendChild(buildItem({ id: 'shortcuts', label: 'Keyboard shortcuts' }, { kbd: '?' }));
    root.appendChild(buildItem({ id: 'bug',       label: 'Report a bug' }));

    root.appendChild(buildSep());
    root.appendChild(buildItem({ id: 'signout', label: 'Sign out' }, { danger: true }));

    if (build) root.appendChild(buildBuild(build));

    // Click handling — single delegate.
    root.addEventListener('click', function (ev) {
      var t = ev.target;
      while (t && t !== root && !t.getAttribute('data-mf-item')) t = t.parentNode;
      if (!t || t === root) return;
      var id = t.getAttribute('data-mf-item');
      if (id === 'signout') onSignOut();
      else onSelectItem(id);
      close();
    });

    var anchor = null;
    var onOutside = null;
    var onEsc = null;

    function openAt(triggerBtn) {
      anchor = triggerBtn;
      anchor.setAttribute('aria-expanded', 'true');
      var r = anchor.getBoundingClientRect();
      root.style.position = 'absolute';
      root.style.top = (window.scrollY + r.bottom + 8) + 'px';
      root.style.right = (document.documentElement.clientWidth - (window.scrollX + r.right)) + 'px';
      root.style.display = 'block';
      document.body.appendChild(root);
      requestAnimationFrame(function () {
        onOutside = function (ev) {
          if (!root.contains(ev.target) && ev.target !== anchor) close();
        };
        onEsc = function (ev) { if (ev.key === 'Escape') close(); };
        document.addEventListener('click', onOutside);
        document.addEventListener('keydown', onEsc);
      });
    }

    function close() {
      if (!anchor) return;
      anchor.setAttribute('aria-expanded', 'false');
      root.style.display = 'none';
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener('click', onOutside);
      document.removeEventListener('keydown', onEsc);
      anchor = null;
    }

    return { openAt: openAt, close: close, el: root };
  }

  global.MFAvatarMenu = { create: create };
})(window);
```

- [ ] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === avatar menu popover === */
.mf-av-menu {
  position: absolute;
  width: 300px;
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card);
  box-shadow: var(--mf-shadow-popover);
  padding: 0.4rem;
  z-index: 30;
  font-family: var(--mf-font-sans);
}
.mf-av-menu__who {
  padding: 0.85rem 0.85rem 0.7rem;
  border-bottom: 1px solid var(--mf-border-soft);
  margin-bottom: 0.45rem;
  display: flex; gap: 0.7rem; align-items: center;
}
.mf-av-menu__avatar {
  width: 38px; height: 38px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--mf-color-accent), var(--mf-color-accent-soft));
  flex-shrink: 0;
}
.mf-av-menu__who-text { flex: 1; min-width: 0; }
.mf-av-menu__who-name { font-size: 0.95rem; font-weight: 600; color: var(--mf-color-text); }
.mf-av-menu__who-role {
  font-size: 0.74rem;
  color: var(--mf-color-text-faint);
  margin-top: 0.12rem;
  display: flex; align-items: center; gap: 0.4rem;
}
.mf-av-menu__sec-label {
  font-size: 0.62rem; font-weight: 700;
  color: var(--mf-color-text-fainter);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  padding: 0.55rem 0.7rem 0.25rem;
  display: flex; justify-content: space-between; align-items: center;
}
.mf-av-menu__gate {
  font-size: 0.5rem;
  background: var(--mf-color-warn-bg);
  color: var(--mf-color-warn);
  padding: 0.12rem 0.4rem;
  border-radius: var(--mf-radius-pill);
  font-weight: 700; letter-spacing: 0.05em;
}
.mf-av-menu__item {
  display: flex; align-items: center; gap: 0.65rem;
  padding: 0.5rem 0.7rem;
  border-radius: var(--mf-radius-thumb);
  color: var(--mf-color-text-soft);
  text-decoration: none;
  cursor: pointer;
  font-size: 0.86rem;
}
.mf-av-menu__item:hover { background: var(--mf-color-accent-tint); color: var(--mf-color-accent); }
.mf-av-menu__item--danger { color: var(--mf-color-error); }
.mf-av-menu__item--danger:hover { background: var(--mf-color-error-bg); color: var(--mf-color-error); }
.mf-av-menu__ico {
  width: 18px; flex-shrink: 0;
  color: var(--mf-color-text-faint);
}
.mf-av-menu__grow { flex: 1; min-width: 0; }
.mf-av-menu__kbd {
  font-size: 0.7rem;
  color: var(--mf-color-text-fainter);
  font-family: var(--mf-font-mono);
}
.mf-av-menu__sep { height: 1px; background: var(--mf-border-soft); margin: 0.4rem 0.4rem; }
.mf-av-menu__cta {
  padding: 0.55rem 0.7rem;
  display: flex; align-items: center; justify-content: space-between;
  color: var(--mf-color-accent);
  font-size: 0.84rem; font-weight: 500;
  cursor: pointer;
  border-radius: var(--mf-radius-thumb);
}
.mf-av-menu__cta:hover { background: var(--mf-color-accent-tint); }
.mf-av-menu__build {
  padding: 0.6rem 0.7rem;
  font-size: 0.7rem;
  color: var(--mf-color-text-faint);
  line-height: 1.55;
  font-family: var(--mf-font-mono);
  border-top: 1px solid var(--mf-border-soft);
  margin-top: 0.35rem;
}
.mf-av-menu__build-v { color: var(--mf-color-text); font-weight: 600; }
.mf-av-menu__build-b { color: var(--mf-color-accent); }
```

- [ ] **Step 3: Verify safe DOM — no innerHTML**

Run: `grep -n "innerHTML" static/js/components/avatar-menu.js`

Expected: zero matches. If any appear, replace with createElement / textContent / appendChild equivalents.

- [ ] **Step 4: Commit**

```bash
git add static/js/components/avatar-menu.js static/css/components.css
git commit -m "feat(ux): avatar menu popover (role-gated content)

Personal items shown to all roles (API keys gated to operator+). System
section only renders for operator/admin with Admin only gate badge. All
settings link, Help section, sign out (danger), build info footer.
Click-outside and Esc close. Body-mounted popover escapes overflow:hidden.
Safe DOM throughout — verified zero innerHTML usages. Spec §6."
```

---

## Task 4: Layout-mode popover component

**Files:**
- Create: `static/js/components/layout-popover.js`

The three-mode chooser (Maximal / Recent / Minimal) with checkmark on the current mode.

- [ ] **Step 1: Create the component**

Create `static/js/components/layout-popover.js`:

```javascript
/* Layout-mode popover. Three options + current-mode checkmark.
 * Spec §3, §6.
 *
 * Usage:
 *   var pop = MFLayoutPopover.create({
 *     current: 'minimal',
 *     onChoose: function(mode) { ... }   // mode in {'maximal','recent','minimal'}
 *   });
 *   pop.openAt(layoutIconButton);
 *   pop.setCurrent('recent');             // re-renders checkmark + footer
 *   pop.close();
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var MODES = [
    { id: 'maximal', label: 'Maximal', desc: 'Search + browse rows' },
    { id: 'recent',  label: 'Recent',  desc: 'Search + history only' },
    { id: 'minimal', label: 'Minimal', desc: 'Just the search box' }
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }
  function findMode(id) {
    for (var i = 0; i < MODES.length; i++) if (MODES[i].id === id) return MODES[i];
    return MODES[2];
  }

  function create(opts) {
    var current = (opts && opts.current) || 'minimal';
    var onChoose = (opts && opts.onChoose) || function () {};

    var root = el('div', 'mf-layout-pop');
    root.setAttribute('role', 'menu');
    root.style.display = 'none';

    function buildHead() {
      var h = el('div', 'mf-layout-pop__head');
      var title = el('div', 'mf-layout-pop__title');
      title.textContent = 'Home layout';
      h.appendChild(title);
      var kbd = el('div', 'mf-layout-pop__kbd');
      var k = el('kbd');
      k.textContent = '⌘\\';   // ⌘\
      kbd.appendChild(k);
      kbd.appendChild(document.createTextNode(' to cycle'));
      h.appendChild(kbd);
      return h;
    }

    function buildOpt(mode) {
      var o = el('div', 'mf-layout-pop__opt' + (mode.id === current ? ' mf-layout-pop__opt--on' : ''));
      o.setAttribute('role', 'menuitem');
      o.setAttribute('data-mode', mode.id);
      var name = el('div', 'mf-layout-pop__name');
      name.textContent = mode.label;
      var desc = el('div', 'mf-layout-pop__desc');
      desc.textContent = mode.desc;
      var check = el('span', 'mf-layout-pop__check');
      if (mode.id === current) check.textContent = '✓';   // ✓
      o.appendChild(name);
      o.appendChild(desc);
      o.appendChild(check);
      return o;
    }

    function buildFoot() {
      var f = el('div', 'mf-layout-pop__foot');
      f.appendChild(document.createTextNode('Layout: '));
      var b = el('strong');
      b.textContent = findMode(current).label;
      f.appendChild(b);
      return f;
    }

    function rerender() {
      while (root.firstChild) root.removeChild(root.firstChild);
      root.appendChild(buildHead());
      MODES.forEach(function (m) { root.appendChild(buildOpt(m)); });
      root.appendChild(buildFoot());
    }

    rerender();

    root.addEventListener('click', function (ev) {
      var t = ev.target;
      while (t && t !== root && !t.getAttribute('data-mode')) t = t.parentNode;
      if (!t || t === root) return;
      var mode = t.getAttribute('data-mode');
      if (mode !== current) {
        current = mode;
        onChoose(mode);
      }
      close();
    });

    var anchor = null;
    var onOutside = null;
    var onEsc = null;

    function openAt(triggerBtn) {
      anchor = triggerBtn;
      anchor.setAttribute('aria-expanded', 'true');
      var r = anchor.getBoundingClientRect();
      root.style.position = 'absolute';
      root.style.top = (window.scrollY + r.bottom + 8) + 'px';
      root.style.right = (document.documentElement.clientWidth - (window.scrollX + r.right)) + 'px';
      root.style.display = 'block';
      document.body.appendChild(root);
      requestAnimationFrame(function () {
        onOutside = function (ev) {
          if (!root.contains(ev.target) && ev.target !== anchor) close();
        };
        onEsc = function (ev) { if (ev.key === 'Escape') close(); };
        document.addEventListener('click', onOutside);
        document.addEventListener('keydown', onEsc);
      });
    }
    function close() {
      if (!anchor) return;
      anchor.setAttribute('aria-expanded', 'false');
      root.style.display = 'none';
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener('click', onOutside);
      document.removeEventListener('keydown', onEsc);
      anchor = null;
    }
    function setCurrent(mode) { current = mode; rerender(); }

    return { openAt: openAt, close: close, setCurrent: setCurrent, getCurrent: function () { return current; } };
  }

  global.MFLayoutPopover = { create: create, MODES: MODES };
})(window);
```

- [ ] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === layout popover === */
.mf-layout-pop {
  position: absolute;
  width: 300px;
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card);
  box-shadow: var(--mf-shadow-popover);
  padding: 0.6rem;
  z-index: 30;
  font-family: var(--mf-font-sans);
}
.mf-layout-pop__head {
  padding: 0.4rem 0.55rem 0.55rem;
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid var(--mf-border-soft);
  margin-bottom: 0.35rem;
}
.mf-layout-pop__title { font-size: 0.86rem; font-weight: 600; color: var(--mf-color-text); }
.mf-layout-pop__kbd { font-size: 0.74rem; color: var(--mf-color-text-faint); }
.mf-layout-pop__opt {
  display: flex; align-items: center; gap: 0.7rem;
  padding: 0.55rem;
  border-radius: var(--mf-radius-thumb);
  cursor: pointer;
}
.mf-layout-pop__opt:hover { background: var(--mf-surface-soft); }
.mf-layout-pop__opt--on { background: var(--mf-color-accent-tint-2); }
.mf-layout-pop__name { font-size: 0.86rem; font-weight: 600; color: var(--mf-color-text); flex: 1; }
.mf-layout-pop__desc { font-size: 0.74rem; color: var(--mf-color-text-faint); margin-left: 0.6rem; }
.mf-layout-pop__check { color: var(--mf-color-accent); font-size: 0.95rem; margin-left: auto; }
.mf-layout-pop__foot {
  padding: 0.55rem;
  border-top: 1px solid var(--mf-border-soft);
  margin-top: 0.35rem;
  font-size: 0.78rem;
  color: var(--mf-color-text-faint);
}
.mf-layout-pop__foot strong { color: var(--mf-color-text); }
```

- [ ] **Step 3: Commit**

```bash
git add static/js/components/layout-popover.js static/css/components.css
git commit -m "feat(ux): layout-mode popover with three options

Maximal / Recent / Minimal with checkmark on current. Header has Cmd+\
keyboard hint. Footer shows current mode in strong text. Body-mounted
popover with click-outside / Esc close. setCurrent() re-renders.
Safe DOM throughout. Spec §3."
```

---

## Task 5: Global keybinds (`⌘\` for layout cycle)

**Files:**
- Create: `static/js/keybinds.js`

Single global keyboard handler. For now just registers `⌘\` for layout cycling; future plans append more shortcuts.

- [ ] **Step 1: Create the module**

Create `static/js/keybinds.js`:

```javascript
/* Global keyboard shortcuts. Register handlers via MFKeybinds.on(combo, handler).
 * Spec §3 (Cmd+\ cycles layout modes).
 *
 * Combo strings: 'mod+x' where mod = Cmd on mac, Ctrl elsewhere.
 *
 * Usage:
 *   MFKeybinds.on('mod+\\', function(ev) { ... });
 */
(function (global) {
  'use strict';

  var handlers = {};   // combo -> array of fn

  function isMac() {
    return navigator.platform.toUpperCase().indexOf('MAC') >= 0;
  }

  function eventCombo(ev) {
    var parts = [];
    if (ev.metaKey || (!isMac() && ev.ctrlKey)) parts.push('mod');
    if (ev.shiftKey) parts.push('shift');
    if (ev.altKey) parts.push('alt');
    parts.push(ev.key.toLowerCase());
    return parts.join('+');
  }

  document.addEventListener('keydown', function (ev) {
    var combo = eventCombo(ev);
    var arr = handlers[combo];
    if (!arr) return;
    var prevent = false;
    for (var i = 0; i < arr.length; i++) {
      try { if (arr[i](ev) === true) prevent = true; }
      catch (e) { console.error('mf-keybinds: handler error', e); }
    }
    if (prevent) ev.preventDefault();
  });

  function on(combo, fn) {
    if (!handlers[combo]) handlers[combo] = [];
    handlers[combo].push(fn);
    return function off() {
      var arr = handlers[combo];
      if (!arr) return;
      var i = arr.indexOf(fn);
      if (i >= 0) arr.splice(i, 1);
    };
  }

  global.MFKeybinds = { on: on };
})(window);
```

- [ ] **Step 2: Commit**

```bash
git add static/js/keybinds.js
git commit -m "feat(ux): global keybinds dispatcher

Single document-level keydown listener. Combos like 'mod+\\' (Cmd on mac,
Ctrl elsewhere). Handler returning true preventDefault()s. Returns
unsubscribe. Plan 1C uses this for layout cycle; future plans append
more shortcuts."
```

---

## Task 6: Wire static chrome's onClick stubs to popovers + ⌘\ cycle

**Files:**
- Modify: `static/dev-chrome.html` to load the new scripts
- Modify: `static/dev-chrome.js` to wire avatar/layout-icon onClick to popovers + register keybind

- [ ] **Step 1: Update dev-chrome.html script tags**

In `static/dev-chrome.html`, add the new script tags before `dev-chrome.js`:

```html
  <script src="/static/js/preferences.js"></script>
  <script src="/static/js/telemetry.js"></script>
  <script src="/static/js/keybinds.js"></script>
  <script src="/static/js/components/top-nav.js"></script>
  <script src="/static/js/components/version-chip.js"></script>
  <script src="/static/js/components/avatar.js"></script>
  <script src="/static/js/components/avatar-menu.js"></script>
  <script src="/static/js/components/layout-icon.js"></script>
  <script src="/static/js/components/layout-popover.js"></script>
  <script src="/static/dev-chrome.js"></script>
```

- [ ] **Step 2: Replace dev-chrome.js wiring**

Replace `static/dev-chrome.js` with:

```javascript
/* Dev-chrome wiring. Mounts all chrome components and demonstrates the
 * full stateful flow:
 *   - Avatar click opens role-gated menu
 *   - Layout-icon click opens 3-mode popover
 *   - Cmd+\ cycles modes
 *   - Mode change persists via MFPrefs
 *   - All clicks emit telemetry events
 */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');

  // Demo identity (Plan 4 replaces with real session identity).
  var demoUser = {
    member:   { name: 'Sarah Mitchell',  role: 'member',   scope: 'IBEW Local 46' },
    operator: { name: 'Aaron Patel',     role: 'operator', scope: 'IBEW Local 46' },
    admin:    { name: 'Xerxes Shelley',  role: 'admin',    scope: 'IBEW Local 46' }
  };
  var build = {
    version: 'v0.34.2-dev', branch: 'main',
    sha: 'd15ddb3', date: '2026-04-28'
  };

  var avatarMenu = null;
  var layoutPop = null;

  function rebuildMenus(role) {
    avatarMenu = MFAvatarMenu.create({
      user: demoUser[role],
      build: build,
      onSelectItem: function (id) {
        console.log('avatar menu selected:', id);
        MFTelemetry.emit('ui.context_menu_action', { source: 'avatar', id: id });
      },
      onSignOut: function () {
        console.log('sign out');
        MFTelemetry.emit('ui.context_menu_action', { source: 'avatar', id: 'signout' });
      }
    });

    var current = MFPrefs.get('layout') || 'minimal';
    layoutPop = MFLayoutPopover.create({
      current: current,
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
      }
    });
  }

  function render(role) {
    MFTopNav.mount(navRoot, { role: role, activePage: 'search' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: build.version }
    );
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { onClick: function (btn) { avatarMenu.openAt(btn); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );
    rebuildMenus(role);
  }

  // Cmd+\ cycles modes.
  var MODES = ['maximal', 'recent', 'minimal'];
  MFKeybinds.on('mod+\\', function () {
    var current = MFPrefs.get('layout') || 'minimal';
    var next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
    MFPrefs.set('layout', next);
    layoutPop.setCurrent(next);
    MFTelemetry.emit('ui.layout_mode_selected', { mode: next, source: 'kbd' });
    return true;  // preventDefault
  });

  // Subscribe so layout popover stays in sync if changed elsewhere.
  MFPrefs.subscribe('layout', function (mode) {
    if (layoutPop && mode) layoutPop.setCurrent(mode);
  });

  // Role switcher.
  var buttons = document.querySelectorAll('.role-switcher [data-role]');
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener('click', function (ev) {
      var role = ev.currentTarget.getAttribute('data-role');
      for (var j = 0; j < buttons.length; j++) buttons[j].classList.remove('on');
      ev.currentTarget.classList.add('on');
      render(role);
    });
  }

  // Hydrate prefs, then initial render.
  MFPrefs.load().then(function () { render('admin'); });
})();
```

- [ ] **Step 3: Smoke verify the full chrome flow**

```bash
docker-compose up -d
```

Visit `http://localhost:8000/static/dev-chrome.html`. Expected:

1. Top nav renders with `MarkFlow [v0.34.2-dev]` + `Search · Activity · Convert` + layout-icon + avatar
2. Click avatar → role-gated menu opens. Switch role to `member` first; verify Personal section shows Profile/Display/Pinned/Notifications (no API keys, no System); switch to `admin`; verify API keys appears + System section appears with `Admin only` gate
3. Click layout-icon → 3-mode popover; the current mode has a checkmark
4. Click a different mode → popover closes, network tab shows `PUT /api/user-prefs` 500ms later
5. Press `⌘\` (or `Ctrl+\` on Linux/Windows) → mode cycles
6. Open dev-tools console; verify telemetry events emitted on each interaction (Network tab: POST /api/telemetry → 204)
7. Press `Esc` while menu is open → closes
8. Click outside while menu is open → closes
9. Reload page → previously-chosen layout is preserved (localStorage + server roundtrip)

If any of those fail, fix before committing.

- [ ] **Step 4: Commit**

```bash
git add static/dev-chrome.html static/dev-chrome.js
git commit -m "feat(ux): wire static chrome stubs to stateful popovers

dev-chrome.html now loads preferences.js, telemetry.js, keybinds.js,
avatar-menu.js, layout-popover.js. dev-chrome.js wires:
- avatar.onClick -> avatarMenu.openAt
- layout-icon.onClick -> layoutPop.openAt
- MFPrefs.subscribe('layout', ...) keeps popover in sync
- Cmd+\\ cycles modes
- Telemetry events on every interaction
- Role switcher rebuilds the menu

End-to-end smoke target for Plans 1A+1B+1C foundation. Plan 4
removes this scaffold once the chrome mounts on real pages."
```

---

## Acceptance check (run before declaring this plan complete)

- [ ] `pytest tests/test_telemetry_endpoint.py -v` — 4 PASS
- [ ] `grep -rn "innerHTML" static/js/` — zero matches in any of our component files
- [ ] `docker-compose up -d` — app starts, `docker-compose logs app | grep ui_telemetry` shows events arriving
- [ ] Visit `/static/dev-chrome.html` and walk through all 9 smoke checks from Task 6 Step 3
- [ ] `git log --oneline | head -10` — 6 task commits, in order

Once all green, **Plan 1C is done** — all chrome (static + stateful + persistence + telemetry) is implemented and demonstrated on the dev page. Next plan: `2026-04-28-ux-overhaul-document-card.md` (Plan 2 — document card component family).

---

## Self-review

**Spec coverage:**
- §3 (layout modes — Maximal/Recent/Minimal): ✓ Task 4 (popover renders all three)
- §6 (avatar menu — Personal / System sections, role gating): ✓ Task 3
- §10 (preferences persistence): ✓ Task 1 (client) — server side already in Plan 1A
- §13 (telemetry events `ui.layout_mode_selected`, `ui.context_menu_action`): ✓ Task 2 + Task 6 wiring

**Spec gaps for this plan (deferred to later plans):**
- §4 (document card with hover preview, right-click): Plan 2
- §5 (Activity dashboard rendering): Plan 4
- §7 (settings detail pages): Plans 5–7
- §8 (cost cap drill-down): Plan 7
- §9 (power-user gate UI consumption): Plan 2 (cards) + Plan 4 (settings)

**Placeholder scan:** No TODOs. Every code block is complete and runnable.

**Type / API consistency:** All popovers use `create({...}).openAt(triggerBtn)` / `.close()` shape. Both popovers and avatar menu append to body for consistent z-index behavior. `MFPrefs.subscribe(key, fn)` returns unsubscribe consistently. Telemetry event names start with `ui.` consistently.

**Safe DOM verification (mandatory final scan):**

```
grep -rn "innerHTML" static/js/preferences.js static/js/telemetry.js \
  static/js/keybinds.js static/js/components/avatar-menu.js \
  static/js/components/layout-popover.js static/dev-chrome.js
```

Expected output: empty. If any line appears, replace with createElement / textContent / appendChild equivalents before committing.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-stateful-chrome.md`.

Sized for: 6 implementer dispatches + 6 spec reviews + 6 code quality reviews ≈ 18 subagent calls.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
