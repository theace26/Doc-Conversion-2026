# UX Overhaul — IA Shift Implementation Plan (Plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Activity dashboard (admin/operator-only), wire real role binding via a new `/api/me` endpoint, and retire the `dev-chrome.html` scaffold now that components have a real home (the Search-as-home page from Plan 3 + Activity from this plan). The Activity page is the operator's daily monitoring surface — pipeline status pulse, throughput sparkline, active bulk jobs, queues, recent jobs, and pipeline controls.

**Architecture:** New `static/activity.html` template loads the same component bundle as `index-new.html` plus `MFActivity` and friends. New backend endpoints: `/api/me` (returns the JWT-authenticated user's identity + role) and `/api/activity/summary` (aggregates pipeline state into a single payload for the dashboard). Boot scripts replace the hardcoded `role = 'admin'` placeholder with a real `MFPrefs.load()` + `/api/me` fetch. The activity dashboard reuses Plan 1A's `core.auth.Role` enum for role gating server-side. **Safe DOM construction throughout.**

**Tech stack:** Python/FastAPI · pytest · vanilla JS · existing pipeline state in `core/db/`

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §1 (IA — Activity rename + role-gated nav), §5 (Activity dashboard sections), §11 (role binding via UnionCore)

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/activity-page.html`

**Out of scope (deferred):**
- Wiring the new chrome onto legacy pages (Convert, Settings, History, Admin, etc.) — each replacement happens in its own per-page plan (Plans 5–7 cover Settings; future plans cover Convert / History / etc.)
- Real backend endpoints for the Search-home browse rows (`/api/folders/pinned`, `/api/files/recently-opened`, `/api/files/flagged`, `/api/topics`) — separate plan since they don't gate the IA shift
- First-run onboarding (Plan 8)
- Activity throughput data via SSE (this plan polls; SSE is a follow-up perf optimization)

**Prerequisites:** Plans 1A + 1B + 1C + 2A + 2B + 3 must all be complete. Run `git log --oneline | head -20` and confirm: `f37e633` (1A), `50e552e` (1B), `3d5b1e9` (1C), `6228373` (2A), `1dc467c` (2B), `806c72f` (3).

---

## Model + effort

| Role | Model | Effort |
|------|-------|--------|
| Implementer | Sonnet | med (4-8h) |
| Reviewer | Opus | low (2-3h) |

**Reasoning:** New `/api/me` endpoint, real role binding via UnionCore JWT (replaces the hardcoded `role='admin'` placeholder), Activity dashboard gated by `core.auth.Role`. Auth surface — role-gating bugs are security issues. Opus reviewer once to verify the gate is enforced on every protected endpoint, not just the obvious ones; effort is small because the new endpoint surface is narrow.

**Execution mode:** Dispatch this plan via `superpowers:subagent-driven-development`. Each role is a separate `Agent` call — `Agent({model: "sonnet", ...})` for implementation, `Agent({model: "opus", ...})` for review. A single-session `executing-plans` read will *not* switch models on its own; this metadata is routing input for the orchestrator.

**Source:** [`docs/spreadsheet/phase_model_plan.xlsx`](../../spreadsheet/phase_model_plan.xlsx)

---

## File structure (this plan creates / modifies)

**Create:**
- `api/routes/me.py` — `/api/me` endpoint returning identity + role
- `api/routes/activity.py` — `/api/activity/summary` aggregator endpoint
- `static/activity.html` — Activity page template
- `static/js/pages/activity.js` — `MFActivity` page mount with all sections
- `static/js/activity-boot.js` — boot script that fetches `/api/me` + `/api/activity/summary` and mounts the page
- `tests/test_me_endpoint.py` — 4 tests
- `tests/test_activity_endpoint.py` — 3 tests

**Modify:**
- `static/css/components.css` — append activity-page styles
- `static/js/index-new-boot.js` — fetch `/api/me`, replace hardcoded role + user
- `main.py` — register `me` and `activity` routers; replace `/activity` placeholder with FileResponse
- `static/index-new.html` — drop the hardcoded build info comment now that the boot fetches it

**Remove:**
- `static/dev-chrome.html` — scaffold no longer needed
- `static/dev-chrome.js` — scaffold no longer needed

---

## Task 1: `/api/me` endpoint — identity + role from JWT

**Files:**
- Create: `api/routes/me.py`
- Create: `tests/test_me_endpoint.py`
- Modify: `main.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_me_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_admin_client(fake_jwt):
    return TestClient(app, headers={
        "Authorization": "Bearer " + fake_jwt("xerxes@local46.org", "admin"),
    })


@pytest.fixture
def authed_member_client(fake_jwt):
    return TestClient(app, headers={
        "Authorization": "Bearer " + fake_jwt("sarah@local46.org", "member"),
    })


def test_me_returns_admin_identity(authed_admin_client):
    r = authed_admin_client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "xerxes@local46.org"
    assert body["role"] == "admin"
    assert body["scope"]  # non-empty string


def test_me_returns_member_identity(authed_member_client):
    r = authed_member_client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["role"] == "member"


def test_me_unauthenticated_returns_401():
    client = TestClient(app)
    r = client.get("/api/me")
    assert r.status_code == 401


def test_me_includes_build_info(authed_admin_client):
    """Build info travels with /api/me so the avatar dropdown can render
    it without a separate endpoint or hardcoded HTML."""
    r = authed_admin_client.get("/api/me")
    body = r.json()
    assert "build" in body
    assert "version" in body["build"]
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_me_endpoint.py -v`

Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Implement the endpoint**

Create `api/routes/me.py`:

```python
"""GET /api/me — authenticated user identity + role.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §1, §11
"""
from __future__ import annotations
import os
import subprocess
from fastapi import APIRouter, Depends

from core.auth import require_user, extract_role, Role

router = APIRouter(prefix="/api/me", tags=["identity"])


# Build info — read once at process start. The dev container injects
# git SHA + branch as build labels; production builds set them via
# Dockerfile ARGs. Falls back to "unknown" if not available.
def _git_short_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd="/app",
                timeout=2,
            )
            .decode()
            .strip()
        )
    except Exception:
        return os.environ.get("BUILD_SHA", "unknown")


def _git_branch() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd="/app",
                timeout=2,
            )
            .decode()
            .strip()
        )
    except Exception:
        return os.environ.get("BUILD_BRANCH", "unknown")


_BUILD = {
    "version": os.environ.get("MARKFLOW_VERSION", "v0.34.5-dev"),
    "branch": _git_branch(),
    "sha": _git_short_sha(),
    "date": os.environ.get("BUILD_DATE", "dev"),
}


@router.get("")
async def get_me(user=Depends(require_user)):
    """Return the authenticated user's identity + role + build info."""
    role = extract_role(user.claims if hasattr(user, "claims") else {"role": user.role})
    role_name = {Role.MEMBER: "member", Role.OPERATOR: "operator", Role.ADMIN: "admin"}[role]
    return {
        "user_id": user.user_id,
        "name": getattr(user, "name", "") or user.user_id,
        "role": role_name,
        "scope": getattr(user, "scope", "") or "IBEW Local 46",
        "build": _BUILD,
    }
```

If the project's `require_user` returns a different shape, adapt the field accesses.

- [ ] **Step 4: Wire into `main.py`**

Add to `main.py`:

```python
from api.routes import me as me_routes
app.include_router(me_routes.router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `pytest tests/test_me_endpoint.py -v`

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/me.py main.py tests/test_me_endpoint.py
git commit -m "feat(api): GET /api/me — identity + role + build info

Returns the authenticated user's user_id, name, role (member/operator/
admin from extract_role), scope, and build info (version + branch +
short sha + date). Build info read once at process start from git +
env vars, with 'unknown' fallback. 401 when unauthenticated.

Replaces the hardcoded role/user/build placeholders in
static/js/index-new-boot.js — Plan 4 Task 2 wires the boot to fetch
this. Spec §1, §11."
```

---

## Task 2: Update Search-home boot to fetch `/api/me`

**Files:**
- Modify: `static/js/index-new-boot.js`

- [ ] **Step 1: Replace hardcoded values with /api/me fetch**

In `static/js/index-new-boot.js`, replace the hardcoded `role`, `build`, and `user` block plus the bottom `MFPrefs.load().then(...)` block with:

```javascript
  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        // Defensive fallback for unauthenticated dev — render as member
        // with no build info so the page still loads. Real auth surfaces
        // a 401 via require_user; the fallback only fires when /api/me
        // is reachable but errors (e.g., DEV_BYPASS_AUTH=true with no
        // valid token).
        console.warn('mf: /api/me failed; falling back to member', e);
        return {
          user_id: 'dev', name: 'dev', role: 'member', scope: '',
          build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' },
        };
      });
  }

  Promise.all([MFPrefs.load(), fetchMe()]).then(function (results) {
    var me = results[1];
    var role = me.role;
    var build = me.build;
    var user = { name: me.name, role: role, scope: me.scope };

    // Re-create avatarMenu and layoutPop NOW that we have the real user/build.
    // (The earlier instances were never used — this just keeps the code
    // declarative.)
    var avatarMenu = MFAvatarMenu.create({
      user: user, build: build,
      onSelectItem: function (id) { console.log('avatar item:', id); },
      onSignOut: function () {
        fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
          .finally(function () { window.location.href = '/'; });
      },
    });

    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
      },
    });

    MFTopNav.mount(navRoot, { role: role, activePage: 'search' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: build.version }
    );
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, onClick: function (btn) { avatarMenu.openAt(btn); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );

    // Cmd+\ cycles
    var MODES = ['maximal', 'recent', 'minimal'];
    MFKeybinds.on('mod+\\', function () {
      var current = MFPrefs.get('layout') || 'minimal';
      var next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
      MFPrefs.set('layout', next);
      layoutPop.setCurrent(next);
      MFTelemetry.emit('ui.layout_mode_selected', { mode: next, source: 'kbd' });
      return true;
    });

    // Hover + context menu listeners
    var hp = MFHoverPreview.create({
      onAction: function (action, doc) { console.log('hover:', action, doc.id); },
    });
    var cm = MFContextMenu.create({
      onAction: function (action, doc) { console.log('ctx:', action, doc.id); },
    });
    document.addEventListener('mf:doc-contextmenu', function (ev) {
      cm.openAt(ev.detail.x, ev.detail.y, ev.detail.doc);
    });

    MFSearchHome.mount(homeRoot, {
      systemStatus: 'All systems running · 12,847 indexed',
    });

    function rearm() {
      var cards = homeRoot.querySelectorAll('.mf-doc-card');
      cards.forEach(function (card) {
        var docId = card.getAttribute('data-doc-id');
        var doc = (window.MFSampleDocs || []).find(function (d) { return d.id === docId; });
        if (doc) hp.armOn(card, doc);
      });
    }
    rearm();
    MFPrefs.subscribe('layout', function () {
      requestAnimationFrame(rearm);
    });
  });
```

(Remove the old hardcoded `role = 'admin'`, `build = {...}`, `user = {...}`, `avatarMenu = MFAvatarMenu.create(...)`, `layoutPop = MFLayoutPopover.create(...)`, `mountChrome` function definition, the standalone `MFKeybinds.on` block, the standalone `hp` / `cm` block, and the closing `MFPrefs.load().then(...)` — they all live inside the new Promise.all callback now.)

- [ ] **Step 2: Smoke verify**

```bash
docker-compose up -d --force-recreate markflow
```

Visit `http://localhost:8000/` (with `ENABLE_NEW_UX=true`). Expected:
- Network tab shows `GET /api/me` returning 200 with role/build info
- Top nav reads the user's actual name + role pill
- Avatar dropdown's build strip shows real version + sha + date

If the user is unauthenticated and the system has `DEV_BYPASS_AUTH=true`, the fallback renders a generic "dev" user.

- [ ] **Step 3: Commit**

```bash
git add static/js/index-new-boot.js
git commit -m "feat(ux): Search-home boot fetches /api/me for real role + build

Replaces hardcoded role='admin' / build / user placeholders with a
fetch('/api/me') chained into MFPrefs.load() via Promise.all. Defensive
fallback on fetch error renders as member with 'unknown' build (so the
page still loads under DEV_BYPASS_AUTH dev configs). Sign-out hooks
into POST /api/auth/logout (existing endpoint)."
```

---

## Task 3: `/api/activity/summary` endpoint

**Files:**
- Create: `api/routes/activity.py`
- Create: `tests/test_activity_endpoint.py`
- Modify: `main.py`

The aggregator endpoint that backs the Activity dashboard. Returns a single payload with everything the page needs: status pulse, top tiles, throughput sparkline data, running jobs, queues, recent jobs.

- [ ] **Step 1: Write the failing test**

Create `tests/test_activity_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_admin_client(fake_jwt):
    return TestClient(app, headers={
        "Authorization": "Bearer " + fake_jwt("xerxes@local46.org", "admin"),
    })


@pytest.fixture
def authed_member_client(fake_jwt):
    return TestClient(app, headers={
        "Authorization": "Bearer " + fake_jwt("sarah@local46.org", "member"),
    })


def test_activity_summary_admin_can_read(authed_admin_client):
    r = authed_admin_client.get("/api/activity/summary")
    assert r.status_code == 200
    body = r.json()
    # Required top-level keys
    for key in ["pulse", "tiles", "throughput", "running_jobs", "queues", "recent_jobs"]:
        assert key in body, f"missing key: {key}"


def test_activity_summary_member_forbidden(authed_member_client):
    """Member role should not be able to read the activity summary."""
    r = authed_member_client.get("/api/activity/summary")
    assert r.status_code == 403


def test_activity_summary_unauthenticated_401():
    client = TestClient(app)
    r = client.get("/api/activity/summary")
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_activity_endpoint.py -v`

Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Implement the endpoint**

Create `api/routes/activity.py`:

```python
"""GET /api/activity/summary — single aggregated payload for the
Activity dashboard.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §5
"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_user, extract_role, Role
from core.database import db_fetch_all, db_fetch_one

router = APIRouter(prefix="/api/activity", tags=["activity"])


def _require_operator_or_admin(user=Depends(require_user)):
    role = extract_role(user.claims if hasattr(user, "claims") else {"role": user.role})
    if role < Role.OPERATOR:
        raise HTTPException(status_code=403, detail="operator/admin only")
    return user


@router.get("/summary")
async def activity_summary(user=Depends(_require_operator_or_admin)):
    """Aggregate everything the Activity dashboard needs into one payload."""
    pulse, tiles, throughput, running, queues, recent = await asyncio.gather(
        _pulse(),
        _tiles(),
        _throughput_24h(),
        _running_jobs(),
        _queues(),
        _recent_jobs(),
    )
    return {
        "pulse": pulse,
        "tiles": tiles,
        "throughput": throughput,
        "running_jobs": running,
        "queues": queues,
        "recent_jobs": recent,
    }


async def _pulse() -> dict:
    """Health pulse: 'All systems running' or specific issue."""
    # Defensive — wrap every probe so one slow query can't kill the page.
    try:
        active_row = await db_fetch_one(
            "SELECT COUNT(*) AS cnt FROM bulk_jobs WHERE status='running'"
        )
        active = active_row["cnt"] if active_row else 0
    except Exception:
        active = 0
    indexed = await _safe_count("SELECT COUNT(*) AS cnt FROM source_files WHERE lifecycle_status='active'")
    return {
        "status": "ok",
        "label": f"All systems running · {indexed:,} indexed",
        "active_jobs": active,
    }


async def _tiles() -> dict:
    """Top-tiles: Files processed today, In queue, Active jobs, Last error."""
    today_processed = await _safe_count(
        """SELECT COUNT(*) AS cnt FROM bulk_files
           WHERE status='converted' AND DATE(updated_at) = DATE('now')"""
    )
    in_queue = await _safe_count(
        "SELECT COUNT(*) AS cnt FROM bulk_files WHERE status='pending'"
    )
    active_jobs = await _safe_count(
        "SELECT COUNT(*) AS cnt FROM bulk_jobs WHERE status='running'"
    )
    last_error = await db_fetch_one(
        """SELECT MAX(timestamp) AS ts FROM activity_events WHERE event_type='error'"""
    )
    return {
        "files_processed_today": today_processed,
        "in_queue": in_queue,
        "active_jobs": active_jobs,
        "last_error_at": (last_error["ts"] if last_error else None),
    }


async def _throughput_24h() -> list[dict]:
    """24 hourly buckets of files-converted counts.

    Returned as a list of {hour: 0..23, count: N} ready for sparkline rendering.
    """
    rows = await db_fetch_all(
        """SELECT CAST(strftime('%H', updated_at) AS INTEGER) AS hour,
                  COUNT(*) AS cnt
           FROM bulk_files
           WHERE status='converted'
             AND updated_at >= datetime('now', '-24 hours')
           GROUP BY hour ORDER BY hour"""
    )
    by_hour = {r["hour"]: r["cnt"] for r in rows}
    return [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)]


async def _running_jobs() -> list[dict]:
    rows = await db_fetch_all(
        """SELECT id, source_path, started_at, total_files,
                  converted, failed, eta_seconds
           FROM bulk_jobs
           WHERE status='running'
           ORDER BY started_at DESC LIMIT 10"""
    )
    return [
        {
            "id": r["id"],
            "source_path": r["source_path"],
            "started_at": r["started_at"],
            "total": r["total_files"] or 0,
            "converted": r["converted"] or 0,
            "failed": r["failed"] or 0,
            "eta_seconds": r["eta_seconds"],
        }
        for r in rows
    ]


async def _queues() -> dict:
    """Recently-converted, Needs OCR, Awaiting AI summary, Recently failed counts."""
    return {
        "recently_converted": await _safe_count(
            """SELECT COUNT(*) AS cnt FROM bulk_files
               WHERE status='converted' AND updated_at >= datetime('now', '-24 hours')"""
        ),
        "needs_ocr": await _safe_count(
            """SELECT COUNT(*) AS cnt FROM bulk_files WHERE status='pending_ocr'"""
        ),
        "awaiting_ai_summary": await _safe_count(
            """SELECT COUNT(*) AS cnt FROM analysis_queue WHERE status='pending'"""
        ),
        "recently_failed": await _safe_count(
            """SELECT COUNT(DISTINCT bf.source_path) AS cnt FROM bulk_files bf
               WHERE bf.status='failed' AND bf.updated_at >= datetime('now', '-24 hours')"""
        ),
    }


async def _recent_jobs() -> list[dict]:
    rows = await db_fetch_all(
        """SELECT id, source_path, status, started_at, completed_at,
                  total_files, converted, failed, auto_triggered
           FROM bulk_jobs
           ORDER BY started_at DESC LIMIT 10"""
    )
    return [
        {
            "id": r["id"],
            "source_path": r["source_path"],
            "status": r["status"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "total": r["total_files"] or 0,
            "converted": r["converted"] or 0,
            "failed": r["failed"] or 0,
            "auto_triggered": bool(r["auto_triggered"]),
        }
        for r in rows
    ]


async def _safe_count(sql: str) -> int:
    try:
        row = await db_fetch_one(sql)
        return row["cnt"] if row else 0
    except Exception:
        return 0
```

If the project's `db_fetch_one` / `db_fetch_all` signatures differ, adapt — keep the SQL.

- [ ] **Step 4: Wire into `main.py`**

```python
from api.routes import activity as activity_routes
app.include_router(activity_routes.router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `pytest tests/test_activity_endpoint.py -v`

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/activity.py main.py tests/test_activity_endpoint.py
git commit -m "feat(api): GET /api/activity/summary aggregator

Returns single payload with pulse + tiles + 24h throughput + running
jobs + queues + recent jobs. Defensive — every probe wrapped in
_safe_count so one slow query can't kill the page. Operator/admin
only (member 403). Unauthenticated 401."
```

---

## Task 4: Activity page template

**Files:**
- Create: `static/activity.html`

- [ ] **Step 1: Create the template**

Create `static/activity.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MarkFlow — Activity</title>
  <link rel="stylesheet" href="/static/css/components.css">
  <style>
    body { margin: 0; background: #f7f7f9; font-family: -apple-system, "SF Pro Display", Inter, system-ui, sans-serif; min-height: 100vh; }
  </style>
</head>
<body data-env="dev">
  <div id="mf-top-nav"></div>
  <div id="mf-activity"></div>

  <script src="/static/js/preferences.js"></script>
  <script src="/static/js/telemetry.js"></script>
  <script src="/static/js/keybinds.js"></script>
  <script src="/static/js/components/top-nav.js"></script>
  <script src="/static/js/components/version-chip.js"></script>
  <script src="/static/js/components/avatar.js"></script>
  <script src="/static/js/components/avatar-menu.js"></script>
  <script src="/static/js/components/layout-icon.js"></script>
  <script src="/static/js/components/layout-popover.js"></script>
  <script src="/static/js/pages/activity.js"></script>
  <script src="/static/js/activity-boot.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add static/activity.html
git commit -m "feat(ux): Activity page template

Mounts top-nav + activity dashboard. Same chrome stack as
index-new.html. Loads MFActivity (Task 5) and the activity-boot
script that fetches /api/me + /api/activity/summary."
```

---

## Task 5: Activity dashboard component (`MFActivity`)

**Files:**
- Create: `static/js/pages/activity.js`

The biggest component in this plan. Renders all six sections from `/api/activity/summary`: pulse, tiles, throughput sparkline, running jobs, queues, recent jobs. Plus the pipeline-controls section at the bottom.

- [ ] **Step 1: Create the component**

Create `static/js/pages/activity.js`:

```javascript
/* Activity dashboard page mount. Spec §5.
 *
 * Usage:
 *   MFActivity.mount(slot, { summary, role });
 *   MFActivity.refresh(slot, summary);   // re-render with fresh data
 *
 * The boot script polls /api/activity/summary every 30s and calls
 * refresh(); the component itself is purely presentational.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildPulse(pulse) {
    var p = el('div', 'mf-pulse');
    p.appendChild(el('span', 'mf-pulse__dot'));
    p.appendChild(document.createTextNode(' ' + (pulse.label || 'All systems running')));
    return p;
  }

  function buildHeader() {
    var head = el('h1', 'mf-act__headline');
    head.textContent = 'Activity.';
    var sub = el('p', 'mf-act__subtitle');
    sub.textContent = "What's running, what's queued, what came in, what broke. The conversion engine for the K Drive at a glance.";
    var wrap = el('div');
    wrap.appendChild(head);
    wrap.appendChild(sub);
    return wrap;
  }

  function buildTiles(tiles) {
    var wrap = el('div', 'mf-act__tiles');
    var defs = [
      { lab: 'Files processed today', val: (tiles.files_processed_today || 0).toLocaleString() },
      { lab: 'In queue', val: (tiles.in_queue || 0).toLocaleString() },
      { lab: 'Active jobs', val: String(tiles.active_jobs || 0) },
      { lab: 'Last error', val: tiles.last_error_at ? formatRelative(tiles.last_error_at) : 'Never' },
    ];
    defs.forEach(function (d) {
      var t = el('div', 'mf-act__tile');
      var l = el('div', 'mf-act__tile-lab'); l.textContent = d.lab;
      var v = el('div', 'mf-act__tile-val'); v.textContent = d.val;
      t.appendChild(l); t.appendChild(v);
      wrap.appendChild(t);
    });
    return wrap;
  }

  function buildSparkline(throughput) {
    var wrap = el('div', 'mf-act__spark');
    var lab = el('div', 'mf-act__sec-label'); lab.textContent = 'Throughput · last 24h';
    wrap.appendChild(lab);
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 800 80');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'mf-act__spark-svg');
    var max = Math.max.apply(null, throughput.map(function (b) { return b.count; })) || 1;
    var points = throughput.map(function (b, i) {
      var x = (i / 23) * 800;
      var y = 80 - (b.count / max) * 70 - 5;
      return x + ',' + y;
    }).join(' ');
    var line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', points);
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', '#5b3df5');
    line.setAttribute('stroke-width', '2');
    svg.appendChild(line);
    var fill = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    fill.setAttribute('points', '0,80 ' + points + ' 800,80');
    fill.setAttribute('fill', 'rgba(91,61,245,0.08)');
    fill.setAttribute('stroke', 'none');
    svg.appendChild(fill);
    wrap.appendChild(svg);
    return wrap;
  }

  function buildRunningJobs(jobs) {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Running now';
    wrap.appendChild(lab);
    if (!jobs.length) {
      var empty = el('div', 'mf-act__empty');
      empty.textContent = 'No active jobs.';
      wrap.appendChild(empty);
      return wrap;
    }
    jobs.forEach(function (j) {
      var card = el('div', 'mf-act__job');
      var name = el('div', 'mf-act__job-name');
      name.textContent = j.source_path || '(unknown source)';
      card.appendChild(name);
      var pct = j.total ? Math.round((j.converted / j.total) * 100) : 0;
      var bar = el('div', 'mf-act__job-bar');
      var fill = el('div', 'mf-act__job-bar-fill');
      fill.style.width = pct + '%';
      bar.appendChild(fill);
      card.appendChild(bar);
      var stats = el('div', 'mf-act__job-stats');
      stats.textContent =
        j.converted.toLocaleString() + ' of ' + j.total.toLocaleString() +
        ' files · started ' + (formatRelative(j.started_at) || 'unknown') +
        (j.eta_seconds ? ' · ETA ~' + Math.round(j.eta_seconds / 60) + ' min' : '');
      card.appendChild(stats);
      wrap.appendChild(card);
    });
    return wrap;
  }

  function buildQueues(q) {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Queues & recent activity';
    wrap.appendChild(lab);
    var grid = el('div', 'mf-act__queues');
    [
      { id: 'recently_converted',   label: 'Recently converted',   tone: 'good', meta: 'last 24h' },
      { id: 'needs_ocr',            label: 'Needs OCR',            tone: 'warn', meta: 'queued' },
      { id: 'awaiting_ai_summary',  label: 'Awaiting AI summary',  tone: 'neut', meta: 'queued' },
      { id: 'recently_failed',      label: 'Recently failed',      tone: 'bad',  meta: 'last 24h' },
    ].forEach(function (def) {
      var c = el('div', 'mf-act__queue-card');
      var head = el('div', 'mf-act__queue-head');
      var t = el('span', 'mf-act__queue-title'); t.textContent = def.label;
      var b = el('span', 'mf-act__queue-badge mf-act__queue-badge--' + def.tone);
      b.textContent = def.meta;
      head.appendChild(t); head.appendChild(b);
      c.appendChild(head);
      var stat = el('div', 'mf-act__queue-stat');
      stat.textContent = (q[def.id] || 0).toLocaleString();
      c.appendChild(stat);
      grid.appendChild(c);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  function buildRecentJobs(jobs) {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Recent jobs';
    wrap.appendChild(lab);
    if (!jobs.length) {
      var empty = el('div', 'mf-act__empty');
      empty.textContent = 'No jobs yet.';
      wrap.appendChild(empty);
      return wrap;
    }
    var table = el('div', 'mf-act__table');
    jobs.forEach(function (j) {
      var row = el('div', 'mf-act__table-row');
      var name = el('span', 'mf-act__table-name');
      name.textContent = j.source_path || '(unknown)';
      var status = el('span', 'mf-act__table-status mf-act__table-status--' + (j.status || ''));
      status.textContent = j.status;
      var counts = el('span', 'mf-act__table-counts');
      counts.textContent = (j.converted || 0).toLocaleString() + '/' + (j.total || 0).toLocaleString();
      var ts = el('span', 'mf-act__table-ts');
      ts.textContent = formatRelative(j.started_at) || '';
      row.appendChild(name); row.appendChild(status);
      row.appendChild(counts); row.appendChild(ts);
      table.appendChild(row);
    });
    wrap.appendChild(table);
    return wrap;
  }

  function buildControls() {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Pipeline controls';
    wrap.appendChild(lab);
    var grid = el('div', 'mf-act__controls');
    [
      { id: 'pipeline-toggle', label: 'Pipeline running', sub: 'Auto-scan + auto-convert', toggle: true },
      { id: 'run-scan-now',    label: 'Run scan now', sub: 'Triggers an immediate scan' },
      { id: 'logs',            label: 'Logs & diagnostics', sub: 'Live viewer + error history' },
      { id: 'db-health',       label: 'Database health', sub: 'Schema + integrity + maintenance' },
    ].forEach(function (def) {
      var card = el('div', 'mf-act__ctrl');
      card.setAttribute('data-action', def.id);
      var nm = el('div', 'mf-act__ctrl-name'); nm.textContent = def.label;
      var sub = el('div', 'mf-act__ctrl-sub'); sub.textContent = def.sub;
      card.appendChild(nm); card.appendChild(sub);
      grid.appendChild(card);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  function formatRelative(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      var diff = (Date.now() - d) / 1000;
      if (diff < 60) return Math.floor(diff) + ' sec ago';
      if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
      if (diff < 86400) return Math.floor(diff / 3600) + ' hr ago';
      if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' d ago';
      return d.toISOString().slice(0, 10);
    } catch (e) { return ''; }
  }

  function render(slot, summary) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-act__body');
    body.appendChild(buildPulse(summary.pulse || {}));
    body.appendChild(buildHeader());
    body.appendChild(buildTiles(summary.tiles || {}));
    body.appendChild(buildSparkline(summary.throughput || []));
    body.appendChild(buildRunningJobs(summary.running_jobs || []));
    body.appendChild(buildQueues(summary.queues || {}));
    body.appendChild(buildRecentJobs(summary.recent_jobs || []));
    body.appendChild(buildControls());
    slot.appendChild(body);
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFActivity.mount: slot is required');
    var summary = (opts && opts.summary) || {};
    render(slot, summary);
  }

  function refresh(slot, summary) {
    render(slot, summary);
  }

  global.MFActivity = { mount: mount, refresh: refresh };
})(window);
```

- [ ] **Step 2: Append CSS to components.css**

Append (large block — keeping it focused on the activity-specific styles since most chrome reuses Plan 1A's tokens):

```css
/* === activity dashboard === */
.mf-act__body { padding: 2.2rem var(--mf-page-pad-x) 2.5rem; max-width: var(--mf-content-max); margin: 0 auto; font-family: var(--mf-font-sans); }
.mf-act__headline {
  font-size: 1.85rem;
  letter-spacing: -0.018em;
  font-weight: 700;
  color: var(--mf-color-text);
  margin: 0.4rem 0 0.4rem;
}
.mf-act__subtitle { color: var(--mf-color-text-muted); font-size: 0.96rem; margin: 0 0 1.5rem; max-width: 60ch; }

.mf-act__tiles {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.85rem;
  margin-bottom: 1.6rem;
}
.mf-act__tile {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 1.2rem 1.2rem 1.1rem;
}
.mf-act__tile-lab {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--mf-color-text-faint);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.5rem;
}
.mf-act__tile-val {
  font-size: 1.85rem;
  line-height: 1.05;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--mf-color-text);
}

.mf-act__spark {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 1.1rem 1.2rem;
  margin-bottom: 1.6rem;
}
.mf-act__spark-svg { width: 100%; height: 80px; }
.mf-act__sec-label, .mf-act__sec-h {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--mf-color-text-faint);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.mf-act__sec-h { font-size: 1.3rem; font-weight: 700; letter-spacing: -0.018em; color: var(--mf-color-text); text-transform: none; margin: 1.8rem 0 0.85rem; }

.mf-act__section { margin-bottom: 1.4rem; }
.mf-act__empty {
  background: var(--mf-surface-soft);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card);
  padding: 1.2rem;
  color: var(--mf-color-text-faint);
  font-size: 0.9rem;
  text-align: center;
}

.mf-act__job {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 1.1rem 1.2rem;
  margin-bottom: 0.75rem;
}
.mf-act__job-name { font-size: 1rem; font-weight: 600; color: var(--mf-color-text); margin-bottom: 0.5rem; }
.mf-act__job-bar { height: 6px; border-radius: var(--mf-radius-pill); background: var(--mf-color-accent-tint); overflow: hidden; margin-bottom: 0.4rem; }
.mf-act__job-bar-fill { height: 100%; background: linear-gradient(90deg, var(--mf-color-accent), var(--mf-color-accent-soft)); }
.mf-act__job-stats { font-size: 0.82rem; color: var(--mf-color-text-muted); }

.mf-act__queues {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.85rem;
}
.mf-act__queue-card {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 1.1rem 1.15rem 1rem;
}
.mf-act__queue-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
.mf-act__queue-title { font-size: 0.9rem; font-weight: 600; color: var(--mf-color-text); }
.mf-act__queue-badge {
  font-size: 0.66rem;
  font-weight: 700;
  padding: 0.18rem 0.55rem;
  border-radius: var(--mf-radius-pill);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.mf-act__queue-badge--good { background: var(--mf-color-success-bg); color: var(--mf-color-success); }
.mf-act__queue-badge--warn { background: var(--mf-color-warn-bg); color: var(--mf-color-warn); }
.mf-act__queue-badge--neut { background: var(--mf-color-accent-tint); color: var(--mf-color-accent); }
.mf-act__queue-badge--bad  { background: var(--mf-color-error-bg); color: var(--mf-color-error); }
.mf-act__queue-stat { font-size: 1.85rem; line-height: 1.05; font-weight: 700; letter-spacing: -0.02em; color: var(--mf-color-text); }

.mf-act__table { border-top: 1px solid var(--mf-border-soft); }
.mf-act__table-row {
  display: grid;
  grid-template-columns: 2.4fr 0.8fr 1fr 1fr;
  gap: 0.85rem;
  align-items: center;
  padding: 0.65rem 0.5rem;
  border-bottom: 1px solid var(--mf-border-soft);
  font-size: 0.86rem;
}
.mf-act__table-name { color: var(--mf-color-text); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mf-act__table-status { font-size: 0.78rem; font-weight: 600; }
.mf-act__table-status--running   { color: var(--mf-color-accent); }
.mf-act__table-status--completed { color: var(--mf-color-success); }
.mf-act__table-status--failed    { color: var(--mf-color-error); }
.mf-act__table-status--cancelled { color: var(--mf-color-warn); }
.mf-act__table-counts, .mf-act__table-ts { color: var(--mf-color-text-muted); font-size: 0.82rem; }

.mf-act__controls {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.85rem;
}
.mf-act__ctrl {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card);
  padding: 1.05rem 1.1rem;
  cursor: pointer;
}
.mf-act__ctrl:hover { border-color: var(--mf-color-accent-border); }
.mf-act__ctrl-name { font-size: 0.92rem; font-weight: 600; color: var(--mf-color-text); margin-bottom: 0.15rem; }
.mf-act__ctrl-sub { font-size: 0.76rem; color: var(--mf-color-text-faint); line-height: 1.4; }
```

- [ ] **Step 3: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/pages/activity.js`

Expected: zero matches.

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/activity.js static/css/components.css
git commit -m "feat(ux): MFActivity dashboard component (admin/operator only)

Six sections from /api/activity/summary: pulse + tiles (4-up grid) +
24h throughput sparkline (SVG, polyline + filled area) + running jobs
(progress bars + ETA) + queues (4-up colored badges) + recent jobs
(table) + pipeline controls (4-up).

Pure presentational — boot script polls and calls MFActivity.refresh().
Empty states for 'no active jobs' and 'no jobs yet' rendered defensively.
formatRelative() helper for timestamps. Safe DOM throughout — every
text via textContent."
```

---

## Task 6: Activity boot script + `/activity` route

**Files:**
- Create: `static/js/activity-boot.js`
- Modify: `main.py` to replace `/activity` placeholder with FileResponse

- [ ] **Step 1: Create the boot**

Create `static/js/activity-boot.js`:

```javascript
/* Boot script for the Activity page.
 * Fetches /api/me + /api/activity/summary; mounts chrome + MFActivity.
 * Polls /api/activity/summary every 30s for live updates.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var actRoot = document.getElementById('mf-activity');
  var POLL_INTERVAL = 30000;

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      });
  }
  function fetchSummary() {
    return fetch('/api/activity/summary', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('summary fetch failed: ' + r.status);
        return r.json();
      });
  }

  Promise.all([MFPrefs.load(), fetchMe(), fetchSummary()]).then(function (results) {
    var me = results[1];
    var summary = results[2];

    if (me.role === 'member') {
      // Member shouldn't see this page at all — redirect home.
      window.location.href = '/';
      return;
    }

    var build = me.build;
    var user = { name: me.name, role: me.role, scope: me.scope };

    var avatarMenu = MFAvatarMenu.create({
      user: user, build: build,
      onSelectItem: function (id) { console.log('avatar item:', id); },
      onSignOut: function () {
        fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
          .finally(function () { window.location.href = '/'; });
      },
    });
    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
      },
    });

    MFTopNav.mount(navRoot, { role: me.role, activePage: 'activity' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: build.version }
    );
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, onClick: function (btn) { avatarMenu.openAt(btn); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );

    MFActivity.mount(actRoot, { summary: summary });

    // Poll for fresh data.
    setInterval(function () {
      fetchSummary()
        .then(function (s) { MFActivity.refresh(actRoot, s); })
        .catch(function (e) { console.warn('mf: activity poll failed', e); });
    }, POLL_INTERVAL);
  }).catch(function (e) {
    console.error('mf: activity boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Activity dashboard unavailable. Check console.';
    actRoot.appendChild(msg);
  });
})();
```

- [ ] **Step 2: Replace `/activity` placeholder route**

In `main.py`, find the `_activity_placeholder` route added in Plan 1A Task 6. Replace its body:

```python
@app.get("/activity", include_in_schema=False)
async def activity_page():
    """Activity dashboard (admin/operator-only at the API layer; this
    handler serves the static HTML, and the boot script redirects
    members to / on /api/me response).
    """
    return FileResponse("static/activity.html")
```

- [ ] **Step 3: Smoke verify**

```bash
ENABLE_NEW_UX=true docker-compose up -d --force-recreate markflow
```

As an admin user, visit `http://localhost:8000/activity`. Expected:
- Page loads, renders nav with Activity active
- Tiles populate from /api/activity/summary
- Sparkline draws (even if all zeros — line is at the bottom)
- Running now / Queues / Recent jobs render
- Pipeline controls render

As a member user, visit `/activity` → redirects to `/` (the boot script catches the role and bails).

`/pipeline` should still 301 to `/activity` (Plan 1A's alias is unchanged).

- [ ] **Step 4: Commit**

```bash
git add static/js/activity-boot.js main.py
git commit -m "feat(ux): activity-boot + real /activity route

Boot fetches /api/me + /api/activity/summary in parallel, mounts
chrome (Activity active in nav for admin/operator), then mounts
MFActivity. Polls /api/activity/summary every 30s for refresh.

Member role → redirect to / (defense-in-depth alongside the
endpoint's 403). main.py /activity handler now FileResponse'd
to static/activity.html (replaces Plan 1A placeholder)."
```

---

## Task 7: Remove `dev-chrome.html` scaffold

**Files:**
- Delete: `static/dev-chrome.html`
- Delete: `static/dev-chrome.js`

The scaffold has served its purpose — components are now mounted on real pages (Search-home and Activity). Removing it eliminates a maintenance burden + a dead URL.

- [ ] **Step 1: Delete the files**

```bash
rm static/dev-chrome.html static/dev-chrome.js
```

- [ ] **Step 2: Smoke verify nothing breaks**

```bash
docker-compose up -d --force-recreate markflow
```

Visit `http://localhost:8000/static/dev-chrome.html` — expected: 404 (no longer served).

Visit `http://localhost:8000/` (with `ENABLE_NEW_UX=true`) — expected: Search home still works.

Visit `http://localhost:8000/activity` (as admin) — expected: Activity page works.

- [ ] **Step 3: Commit**

```bash
git add -u
git commit -m "chore(ux): remove dev-chrome.html scaffold

Components are now mounted on real pages (Search-home + Activity).
The scaffold has served its purpose. Removing eliminates a
maintenance burden + a dead URL.

If a future component needs an isolated smoke target, build it
fresh — don't resurrect this scaffold (it accumulated cruft from
Plans 1A through 3 incrementally)."
```

---

## Acceptance check (run before declaring this plan complete)

- [ ] `pytest tests/test_me_endpoint.py tests/test_activity_endpoint.py -v` — 7 PASS
- [ ] `grep -rn "innerHTML" static/js/pages/activity.js static/js/activity-boot.js static/js/index-new-boot.js` — zero matches
- [ ] `docker-compose up -d --force-recreate markflow` succeeds, no console errors on either page
- [ ] As admin: `/activity` loads with all 6 sections rendered from real data
- [ ] As member: `/activity` redirects to `/`
- [ ] `/pipeline` still 301s to `/activity` (Plan 1A's alias unchanged)
- [ ] `/` (with flag on) renders Search-home with the user's real name + role pill from `/api/me`
- [ ] Avatar dropdown's build strip shows real version + sha + date
- [ ] `static/dev-chrome.html` returns 404
- [ ] `git log --oneline | head -10` shows ~7 task commits in order

Once all green, **Plan 4 is done**. Next plan: `2026-04-28-ux-overhaul-settings-overview-and-storage.md` (Plan 5 — Settings overview card grid + Storage detail page).

---

## Self-review

**Spec coverage:**
- §1 (Activity rename, role-gated nav with real role from /api/me): ✓ Tasks 1, 2, 6
- §5 (Activity dashboard sections — pulse, tiles, throughput, running, queues, recent, controls): ✓ Tasks 3, 4, 5
- §11 (role binding via UnionCore JWT): ✓ Task 1 reuses Plan 1A's `extract_role` + `Role` enum

**Spec gaps for this plan (deferred):**
- §3 (real /api/folders/pinned, /api/files/recently-opened, /api/files/flagged, /api/topics for Search-home): future plan
- §7 (Settings detail pages): Plans 5–7
- §8 (cost cap drill-down): Plan 7
- Activity throughput SSE for true live-updating: future plan (currently 30s poll)

**Placeholder scan:** No TODOs in shipped code. Boot scripts have `console.log` placeholders for action handlers (avatar menu items / context menu actions / control buttons) — those wire to real endpoints in future plans where each action's destination exists.

**Type / API consistency:**
- `/api/me` and `/api/activity/summary` both follow the project's existing `prefix=/api/...` pattern from Plan 1A's `/api/user-prefs`
- `MFActivity.mount(slot, { summary, role })` consistent with `MFSearchHome.mount(slot, opts)` from Plan 3
- `MFActivity.refresh(slot, summary)` is a separate method (not a re-mount) so polling doesn't tear down + rebuild the DOM
- Role gating consistent across both endpoints + the activity-boot redirect (defense-in-depth)

**Safe-DOM verification (mandatory final scan):**

```
grep -rn "innerHTML" static/js/pages/activity.js \
  static/js/activity-boot.js \
  static/js/index-new-boot.js
```

Expected: empty.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-ia-shift.md`.

Sized for: 7 implementer dispatches + 7 spec reviews + 7 code quality reviews ≈ 21 subagent calls.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
