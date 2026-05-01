# UX Overhaul — Settings Overview + Storage Detail Plan (Plan 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the Settings detail-page pattern by shipping the `/settings` overview card grid + the first detail page (`/settings/storage`). The pattern set here — reusable form atoms, a scoped-sidebar detail shell, and a per-section page component — is what Plan 6 drops six more sections into.

**Architecture:** New backend route `GET /api/settings/sections` returns the role-gated card list for the overview. Two new reusable front-end pieces: `MFFormControls` (toggle / segmented / text-input / day-pill / mini-table factories) and `MFSettingsDetail` (scoped-sidebar + breadcrumb + save-bar shell). The Storage detail page composes those atoms into 6 sub-sections that call **existing** `/api/storage/*` endpoints — no new storage backend. Both new pages ship behind `ENABLE_NEW_UX=true`; the legacy `static/settings.html` and `static/storage.html` stay live for the flag-off path until the deprecation pass after Plan 7. **Safe DOM construction throughout.**

**Tech stack:** Python 3.11 · FastAPI · pytest · vanilla JS · existing `core/auth` `Role` enum (Plan 1A) · existing `/api/storage/*` (v0.28+ Universal Storage Manager) · existing `core/feature_flags.is_new_ux_enabled()` (Plan 1A)

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §7 (Settings detail pattern + form components + sub-section sidebars), §11 (role gates: Settings overview cards, system rows visible to ≥ operator), §13 (phase-5 specifically — preferences sync verified, re-auth gate; re-auth gate enforcement deferred to Plan 6 Account & auth)

**Mockup reference:**
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-hybrid.html` — overview-cards-then-scoped-detail (the locked pattern)
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-detail-family.html` — Pipeline detail + form atoms (representative; same atoms power Storage)
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-three-details.html` — additional form patterns referenced by Plan 6

**Out of scope (deferred):**
- Settings detail pages for Pipeline · AI providers · Account & auth · Notifications · Database health · Log management → Plan 6
- Cost cap & alerts deep-dive sub-page + CSV import → Plan 7
- Re-auth-required-to-change-System-settings enforcement (the freshness check) → Plan 6 (lives under Account & auth, since that's where the toggle and JWT-freshness logic land); Plan 5's Storage save calls still succeed without a freshness gate, identical to today's `static/settings.html` behavior
- First-run onboarding (welcome + pin folders) → Plan 8
- Removing legacy `static/settings.html` + `static/storage.html` → deferred to a deprecation pass after Plan 7 ships, when `ENABLE_NEW_UX` is ready to flip globally
- Per-user "remember last sub-section" preference → v1.1 (default to first sub-section on each visit for v1)
- Member-visible Settings cards (Display preferences, Pinned folders, Profile, Notifications opt-in) — backend gating shipped here; Plan 6 builds the actual member-facing detail pages

**Prerequisites:** Plans 1A + 1B + 1C + 2A + 2B + 3 + 4 must all be complete. Run `git log --oneline | head -25` and confirm: `f37e633` (1A), `50e552e` (1B), `3d5b1e9` (1C), `6228373` (2A), `1dc467c` (2B), `806c72f` (3), `cc65c22` (4). In particular this plan assumes:

- `core/auth.py` exposes `Role` enum (`MEMBER` / `OPERATOR` / `ADMIN`) and `extract_role(claims)` helper (Plan 1A Task 4)
- `core/feature_flags.is_new_ux_enabled()` returns the `ENABLE_NEW_UX` env-flag value (Plan 1A Task 1)
- `static/css/design-tokens.css` declares the `--mf-*` custom properties used by all CSS in this plan (Plan 1A Task 2)
- `static/css/components.css` already has `.mf-pill`, `.mf-toggle`, `.mf-seg`, `.mf-card`, `.mf-pulse` (Plan 1A Task 3)
- `MFTopNav`, `MFAvatar`, `MFAvatarMenu`, `MFLayoutIcon`, `MFLayoutPopover`, `MFVersionChip`, `MFPrefs`, `MFTelemetry`, `MFKeybinds` are mountable globals (Plans 1B + 1C)
- `GET /api/me` returns `{ user_id, name, role, scope, build }` (Plan 4 Task 1)

---

## File structure (this plan creates / modifies)

**Create:**
- `api/routes/settings_sections.py` — `GET /api/settings/sections` (role-gated card list)
- `static/settings-new.html` — Settings overview template (card grid)
- `static/settings-storage.html` — Storage detail page template
- `static/js/components/form-controls.js` — `MFFormControls` factory module (toggle / segmented / text input / day-pills / mini-table)
- `static/js/components/settings-detail.js` — `MFSettingsDetail` reusable shell (scoped sidebar + form area + breadcrumb + save bar)
- `static/js/pages/settings-overview.js` — `MFSettingsOverview` card-grid page mount
- `static/js/pages/settings-storage.js` — `MFStorageSettings` page (six sub-sections wired to `/api/storage/*`)
- `static/js/settings-overview-boot.js` — boot for `/settings`
- `static/js/settings-storage-boot.js` — boot for `/settings/storage`
- `tests/test_settings_sections_endpoint.py` — 5 tests

**Modify:**
- `static/css/components.css` — append form-control + settings-detail + settings-overview styles
- `main.py` — register `settings_sections` router; add `/settings` and `/settings/storage` routes (flag-aware: serves new templates when `ENABLE_NEW_UX=true`, falls back to legacy `static/settings.html` / `static/storage.html` otherwise)

**Not removed (yet):**
- `static/settings.html`, `static/storage.html`, `static/js/storage.js` — legacy fallback while flag is off; deprecation pass after Plan 7

---

## Task 1: `/api/settings/sections` — role-gated card list

**Files:**
- Create: `api/routes/settings_sections.py`
- Create: `tests/test_settings_sections_endpoint.py`
- Modify: `main.py`

The Settings overview page asks the backend "which cards should I render for this user?" rather than encoding visibility client-side. Keeps the role gate single-source-of-truth alongside `Role` from `core/auth.py`. Member sees Display + Pinned folders + Profile + Notifications-preferences. Operator + Admin add the seven System cards. Output is ordered the way the overview should render it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_sections_endpoint.py`:

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
def authed_operator_client(fake_jwt):
    return TestClient(app, headers={
        "Authorization": "Bearer " + fake_jwt("op@local46.org", "operator"),
    })


@pytest.fixture
def authed_member_client(fake_jwt):
    return TestClient(app, headers={
        "Authorization": "Bearer " + fake_jwt("sarah@local46.org", "member"),
    })


# These ids are the locked spec §7 card ids; if a test fails because the
# backend returned a different id, fix the backend (the IDs are part of
# the front-end <-> back-end contract — boots use them to pick templates).
SYSTEM_IDS = {
    "storage", "pipeline", "ai-providers", "account-auth",
    "database-health", "log-management", "notifications-system",
}
PERSONAL_IDS = {
    "display", "pinned-folders", "profile", "notifications-prefs",
}


def test_admin_sees_all_cards(authed_admin_client):
    r = authed_admin_client.get("/api/settings/sections")
    assert r.status_code == 200
    body = r.json()
    ids = {c["id"] for c in body["cards"]}
    for sid in SYSTEM_IDS | PERSONAL_IDS:
        assert sid in ids, f"admin missing card: {sid}"


def test_operator_sees_all_cards_same_as_admin(authed_operator_client):
    r = authed_operator_client.get("/api/settings/sections")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()["cards"]}
    for sid in SYSTEM_IDS | PERSONAL_IDS:
        assert sid in ids


def test_member_sees_personal_cards_only(authed_member_client):
    r = authed_member_client.get("/api/settings/sections")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()["cards"]}
    assert ids == PERSONAL_IDS, (
        f"member should see exactly {PERSONAL_IDS} but saw {ids}"
    )


def test_unauthenticated_returns_401():
    client = TestClient(app)
    r = client.get("/api/settings/sections")
    assert r.status_code == 401


def test_card_shape_has_required_fields(authed_admin_client):
    body = authed_admin_client.get("/api/settings/sections").json()
    for card in body["cards"]:
        # Every card must have id, label, blurb, icon, group, role_min — the
        # MFSettingsOverview component uses all six fields.
        for key in ("id", "label", "blurb", "icon", "group", "role_min"):
            assert key in card, f"card {card.get('id')} missing {key}"
        assert card["group"] in ("personal", "system")
        assert card["role_min"] in ("member", "operator", "admin")
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_settings_sections_endpoint.py -v`

Expected: FAIL — endpoint doesn't exist (404).

- [ ] **Step 3: Implement the endpoint**

Create `api/routes/settings_sections.py`:

```python
"""GET /api/settings/sections — role-gated card list for the
Settings overview page.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md
      §7 (overview cards), §11 (role gates)
"""
from __future__ import annotations
from fastapi import APIRouter, Depends

from core.auth import require_user, extract_role, Role

router = APIRouter(prefix="/api/settings/sections", tags=["settings"])


# Single source of truth for which cards exist + their visibility floor.
# Front-end never invents card IDs — boots map id -> page url here.
_CARDS = [
    # Personal — visible to every authenticated user
    {
        "id": "display",
        "label": "Display",
        "blurb": "Layout, density, snippet length, power-user actions.",
        "icon": "view",
        "group": "personal",
        "role_min": "member",
    },
    {
        "id": "pinned-folders",
        "label": "Pinned folders",
        "blurb": "Folders + topics that show up at the top of Search-home.",
        "icon": "pin",
        "group": "personal",
        "role_min": "member",
    },
    {
        "id": "notifications-prefs",
        "label": "Notifications",
        "blurb": "What you want to hear about. Channels, quiet hours.",
        "icon": "bell",
        "group": "personal",
        "role_min": "member",
    },
    {
        "id": "profile",
        "label": "Profile",
        "blurb": "Your name, scope, and identity (read-only — owned by UnionCore).",
        "icon": "user",
        "group": "personal",
        "role_min": "member",
    },
    # System — operator/admin only
    {
        "id": "storage",
        "label": "Storage",
        "blurb": "Where files come from and go to. SMB / NFS mounts, output paths, cloud prefetch, credentials.",
        "icon": "storage",
        "group": "system",
        "role_min": "operator",
    },
    {
        "id": "pipeline",
        "label": "Pipeline & lifecycle",
        "blurb": "Scan windows, lifecycle timing, scheduler behavior, write guard.",
        "icon": "gear",
        "group": "system",
        "role_min": "operator",
    },
    {
        "id": "ai-providers",
        "label": "AI providers",
        "blurb": "Anthropic key, image-analysis routing, cost cap, vector indexing.",
        "icon": "sparkle",
        "group": "system",
        "role_min": "operator",
    },
    {
        "id": "account-auth",
        "label": "Account & auth",
        "blurb": "JWT, sign-in, role hierarchy, API keys, re-auth gate.",
        "icon": "lock",
        "group": "system",
        "role_min": "operator",
    },
    {
        "id": "notifications-system",
        "label": "Notifications (system)",
        "blurb": "Operator alerts: trigger rules, channels, quiet hours, test send.",
        "icon": "bell-system",
        "group": "system",
        "role_min": "operator",
    },
    {
        "id": "database-health",
        "label": "Database health",
        "blurb": "Connection pool, backups, maintenance window, integrity check.",
        "icon": "db",
        "group": "system",
        "role_min": "operator",
    },
    {
        "id": "log-management",
        "label": "Log management",
        "blurb": "Levels per subsystem, retention, live viewer, export.",
        "icon": "logs",
        "group": "system",
        "role_min": "operator",
    },
]


_ROLE_RANK = {Role.MEMBER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}
_ROLE_FROM_NAME = {"member": Role.MEMBER, "operator": Role.OPERATOR, "admin": Role.ADMIN}


def _role_meets(actual: Role, floor_name: str) -> bool:
    return _ROLE_RANK[actual] >= _ROLE_RANK[_ROLE_FROM_NAME[floor_name]]


@router.get("")
async def list_sections(user=Depends(require_user)):
    """Return the cards visible to the authenticated user, in render order."""
    claims = user.claims if hasattr(user, "claims") else {"role": getattr(user, "role", "member")}
    role = extract_role(claims)
    visible = [c for c in _CARDS if _role_meets(role, c["role_min"])]
    return {"cards": visible}
```

If `require_user` returns a different shape, adapt the field accesses; keep the cards list verbatim — its IDs are part of the contract.

- [ ] **Step 4: Wire into `main.py`**

Add to `main.py`:

```python
from api.routes import settings_sections as settings_sections_routes
app.include_router(settings_sections_routes.router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `pytest tests/test_settings_sections_endpoint.py -v`

Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/settings_sections.py main.py tests/test_settings_sections_endpoint.py
git commit -m "feat(api): GET /api/settings/sections — role-gated card list

Single source of truth for which Settings overview cards a user sees.
Member sees the 4 personal cards (Display, Pinned folders, Notifications,
Profile). Operator/Admin add the 7 system cards (Storage, Pipeline,
AI providers, Account & auth, Notifications-system, Database health,
Log management). Card IDs are part of the front-end <-> back-end
contract — boots map id -> page url. Spec §7, §11."
```

---

## Task 2: Form-control atoms (`MFFormControls` + CSS)

**Files:**
- Create: `static/js/components/form-controls.js`
- Modify: `static/css/components.css`

Reusable atoms that every Settings detail page needs. Defined here so Plan 5 (Storage) and Plan 6 (six more sections) consume the same factories. Each factory returns a built `<div>` that the page mounts directly — no `innerHTML`, no template strings to escape.

Existing atoms from Plan 1A: `.mf-pill`, `.mf-toggle`, `.mf-toggle__knob`, `.mf-seg`, `.mf-seg__opt`. This task adds higher-level field-row + table + day-pill + sidebar + breadcrumb + save-bar styles.

- [ ] **Step 1: Append CSS to `static/css/components.css`**

Append (to the bottom of the file):

```css
/* === settings detail — shared form atoms === */
.mf-field-row { display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.95rem; }
.mf-field-row--inline { flex-direction: row; align-items: center; gap: 0.6rem; }
.mf-field-label {
  font-size: var(--mf-text-xs);
  font-weight: 700;
  color: var(--mf-color-text-muted);
  text-transform: uppercase;
  letter-spacing: var(--mf-tracking-wide);
}
.mf-field-input {
  padding: 0.62rem 0.85rem;
  border: 1px solid #e0e0e0;
  border-radius: var(--mf-radius-input);
  font-size: var(--mf-text-body);
  background: var(--mf-surface-soft);
  color: var(--mf-color-text-soft);
  box-sizing: border-box;
  font-family: var(--mf-font-sans);
  width: 100%;
}
.mf-field-input--tight { max-width: 160px; }
.mf-field-input[readonly] { background: #f0f0f0; color: var(--mf-color-text-muted); }
.mf-field-input:focus {
  outline: none;
  border-color: var(--mf-color-accent-border);
  box-shadow: 0 0 0 3px rgba(91, 61, 245, 0.12);
}
.mf-field-help {
  font-size: var(--mf-text-xs);
  color: var(--mf-color-text-faint);
  line-height: var(--mf-leading-body);
  margin: 0.35rem 0 0;
}

/* === day-of-week pill row === */
.mf-day-pills { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.mf-day-pill {
  padding: 0.4rem 0.75rem;
  border-radius: var(--mf-radius-pill);
  font-size: var(--mf-text-xs);
  font-weight: 500;
  cursor: pointer;
  border: 1px solid #e0e0e0;
  background: var(--mf-surface);
  color: var(--mf-color-text-muted);
  font-family: var(--mf-font-sans);
}
.mf-day-pill--on {
  background: var(--mf-color-accent);
  color: #ffffff;
  border-color: var(--mf-color-accent);
}

/* === mini-table (5-7 row preview, used by recent-activity blocks) === */
.mf-mini-table {
  background: var(--mf-surface-soft);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-input);
  padding: 0.85rem 0;
  font-size: var(--mf-text-sm);
}
.mf-mini-row {
  display: grid;
  gap: 0.7rem;
  padding: 0.45rem 1.05rem;
  border-bottom: 1px solid var(--mf-border-soft);
  align-items: center;
}
.mf-mini-row:last-child { border-bottom: none; }
.mf-mini-row--head {
  color: var(--mf-color-text-faint);
  font-size: var(--mf-text-micro);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.mf-mini-row--ok > .mf-mini-cell--status { color: var(--mf-color-success); font-weight: 600; }
.mf-mini-row--err > .mf-mini-cell--status { color: var(--mf-color-error); font-weight: 600; }

/* === settings overview === */
.mf-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
.mf-settings-group {
  margin-bottom: 1.6rem;
}
.mf-settings-group__head {
  font-size: var(--mf-text-xs);
  font-weight: 700;
  color: var(--mf-color-text-faint);
  text-transform: uppercase;
  letter-spacing: var(--mf-tracking-wide);
  margin: 0 0 0.7rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mf-settings-group__gate {
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--mf-color-warn);
  background: var(--mf-color-warn-bg);
  padding: 0.18rem 0.5rem;
  border-radius: var(--mf-radius-pill);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.mf-settings-card {
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 1.4rem 1.3rem;
  background: var(--mf-surface);
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
  position: relative;
  font-family: var(--mf-font-sans);
}
.mf-settings-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px -12px rgba(91, 61, 245, 0.18);
  border-color: var(--mf-color-accent-border);
}
.mf-settings-card:focus-visible {
  outline: 2px solid var(--mf-color-accent);
  outline-offset: 2px;
}
.mf-settings-card__icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--mf-color-accent-tint), var(--mf-color-accent-tint-2));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--mf-color-accent);
  font-size: 1.05rem;
  font-weight: 700;
  margin-bottom: 0.85rem;
}
.mf-settings-card__title { margin: 0 0 0.3rem; font-size: 1rem; color: var(--mf-color-text); font-weight: 600; }
.mf-settings-card__blurb { margin: 0; font-size: var(--mf-text-sm); color: var(--mf-color-text-muted); line-height: var(--mf-leading-body); }
.mf-settings-card__arrow {
  position: absolute;
  top: 1.4rem;
  right: 1.3rem;
  color: var(--mf-color-text-fainter);
  font-size: 1.1rem;
  opacity: 0;
  transition: opacity 0.15s, transform 0.15s;
}
.mf-settings-card:hover .mf-settings-card__arrow { opacity: 1; transform: translateX(2px); }

/* === settings detail shell === */
.mf-settings-detail { padding: 1.8rem var(--mf-page-pad-x) 2.2rem; max-width: var(--mf-content-max); margin: 0 auto; font-family: var(--mf-font-sans); }
.mf-crumb {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--mf-color-accent);
  font-size: var(--mf-text-sm);
  font-weight: 500;
  margin-bottom: 0.7rem;
  background: transparent;
  border: none;
  cursor: pointer;
  text-decoration: none;
  font-family: var(--mf-font-sans);
}
.mf-crumb:hover { text-decoration: underline; }
.mf-crumb__sep { color: var(--mf-color-text-fainter); font-weight: 400; }
.mf-crumb__here { color: var(--mf-color-text); }
.mf-detail-headline {
  font-size: var(--mf-text-h1);
  line-height: var(--mf-leading-tight);
  letter-spacing: var(--mf-tracking-tight);
  font-weight: 700;
  color: var(--mf-color-text);
  margin: 0 0 0.4rem;
  display: flex;
  align-items: center;
  gap: 0.65rem;
}
.mf-detail-headline__icon {
  width: 36px;
  height: 36px;
  border-radius: var(--mf-radius-input);
  background: linear-gradient(135deg, var(--mf-color-accent-tint), var(--mf-color-accent-tint-2));
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--mf-color-accent);
  font-size: 0.95rem;
  font-weight: 700;
}
.mf-detail-subtitle {
  color: var(--mf-color-text-muted);
  font-size: 0.96rem;
  margin: 0 0 1.6rem;
  max-width: 60ch;
}
.mf-detail-flex {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 2rem;
  margin-top: 0.4rem;
}
.mf-detail-side { font-size: 0.88rem; }
.mf-detail-side__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  color: var(--mf-color-text-soft);
  text-decoration: none;
  font-weight: 500;
  margin-bottom: 0.15rem;
  cursor: pointer;
  background: transparent;
  border: none;
  width: 100%;
  text-align: left;
  font-family: var(--mf-font-sans);
  font-size: 0.88rem;
}
.mf-detail-side__item:hover:not(.mf-detail-side__item--on) { background: var(--mf-surface-soft); }
.mf-detail-side__item--on { background: var(--mf-color-accent-tint); color: var(--mf-color-accent); }
.mf-detail-side__badge {
  font-size: 0.62rem;
  font-weight: 700;
  padding: 0.1rem 0.45rem;
  border-radius: var(--mf-radius-pill);
  letter-spacing: 0.05em;
}
.mf-detail-side__badge--warn { background: var(--mf-color-warn-bg); color: var(--mf-color-warn); }
.mf-detail-side__badge--good { background: var(--mf-color-success-bg); color: var(--mf-color-success); }

.mf-form-section { margin-bottom: 1.4rem; }
.mf-form-section__h {
  font-size: var(--mf-text-h3);
  font-weight: 600;
  color: var(--mf-color-text);
  margin: 0 0 0.15rem;
}
.mf-form-section__desc {
  color: var(--mf-color-text-muted);
  font-size: var(--mf-text-sm);
  line-height: var(--mf-leading-body);
  margin: 0 0 0.85rem;
  max-width: 54ch;
}

.mf-save-bar {
  display: flex;
  gap: 0.5rem;
  margin-top: 1.6rem;
  padding-top: 1.4rem;
  border-top: 1px solid var(--mf-border-soft);
  align-items: center;
}
.mf-save-bar__status {
  margin-left: auto;
  font-size: var(--mf-text-sm);
  color: var(--mf-color-text-faint);
}
.mf-save-bar__status--dirty  { color: var(--mf-color-warn); }
.mf-save-bar__status--saving { color: var(--mf-color-accent); }
.mf-save-bar__status--saved  { color: var(--mf-color-success); }
.mf-save-bar__status--error  { color: var(--mf-color-error); }
```

- [ ] **Step 2: Create the JS factory module**

Create `static/js/components/form-controls.js`:

```javascript
/* MFFormControls — factory functions that build common form atoms.
 * Each returns a real DOM node ready for appendChild. Safe DOM throughout
 * (no innerHTML, no template strings interpolated into HTML).
 *
 * Spec §7 (form components: text input, segmented, toggle, day-of-week pills,
 * mini-tables) — same atoms power Plan 5 Storage and Plan 6's six other
 * detail pages.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  /**
   * fieldRow({ label, help, control })
   *   label  — uppercase micro-label (string)
   *   help   — optional one-line help (string)
   *   control — DOM node (built by one of the factories below)
   */
  function fieldRow(opts) {
    var row = el('div', 'mf-field-row');
    if (opts.label) {
      var lab = el('span', 'mf-field-label');
      lab.textContent = opts.label;
      row.appendChild(lab);
    }
    if (opts.control) row.appendChild(opts.control);
    if (opts.help) {
      var help = el('p', 'mf-field-help');
      help.textContent = opts.help;
      row.appendChild(help);
    }
    return row;
  }

  /**
   * textInput({ value, readonly, tight, onInput, type })
   * type defaults to 'text'; pass 'number' for numerics.
   */
  function textInput(opts) {
    var input = document.createElement('input');
    input.type = opts.type || 'text';
    input.className = 'mf-field-input' + (opts.tight ? ' mf-field-input--tight' : '');
    if (opts.value !== undefined && opts.value !== null) input.value = String(opts.value);
    if (opts.readonly) input.readOnly = true;
    if (opts.placeholder) input.placeholder = opts.placeholder;
    if (typeof opts.onInput === 'function') {
      input.addEventListener('input', function (e) { opts.onInput(e.target.value, input); });
    }
    return input;
  }

  /**
   * toggle({ on, label, onChange })
   * Returns a flex row: <button.mf-toggle> + label text. Clicking the button
   * fires onChange(newOn) — caller mutates state and re-renders or calls
   * setOn(true/false) on the returned control.
   */
  function toggle(opts) {
    var on = !!opts.on;
    var wrap = el('div', 'mf-field-row mf-field-row--inline');
    var btn = el('button', 'mf-toggle ' + (on ? 'mf-toggle--on' : 'mf-toggle--off'));
    btn.type = 'button';
    btn.setAttribute('role', 'switch');
    btn.setAttribute('aria-checked', on ? 'true' : 'false');
    var knob = el('span', 'mf-toggle__knob');
    btn.appendChild(knob);
    wrap.appendChild(btn);
    if (opts.label) {
      var lab = el('span');
      lab.style.cssText = 'font-size:0.86rem;color:#333';
      lab.textContent = opts.label;
      wrap.appendChild(lab);
    }
    function setOn(next) {
      on = !!next;
      btn.classList.toggle('mf-toggle--on', on);
      btn.classList.toggle('mf-toggle--off', !on);
      btn.setAttribute('aria-checked', on ? 'true' : 'false');
    }
    btn.addEventListener('click', function () {
      setOn(!on);
      if (typeof opts.onChange === 'function') opts.onChange(on);
    });
    wrap.setOn = setOn;
    wrap.isOn = function () { return on; };
    return wrap;
  }

  /**
   * segmented({ options: [{ id, label }], selected, onSelect })
   * Pill-shaped selector. Returns a div; .setSelected(id) updates visually.
   */
  function segmented(opts) {
    var seg = el('div', 'mf-seg');
    var current = opts.selected;
    var buttons = {};
    (opts.options || []).forEach(function (o) {
      var b = el('button', 'mf-seg__opt' + (o.id === current ? ' mf-seg__opt--on' : ''));
      b.type = 'button';
      b.textContent = o.label;
      b.setAttribute('aria-pressed', o.id === current ? 'true' : 'false');
      b.addEventListener('click', function () {
        if (current === o.id) return;
        current = o.id;
        Object.keys(buttons).forEach(function (id) {
          buttons[id].classList.toggle('mf-seg__opt--on', id === current);
          buttons[id].setAttribute('aria-pressed', id === current ? 'true' : 'false');
        });
        if (typeof opts.onSelect === 'function') opts.onSelect(current);
      });
      buttons[o.id] = b;
      seg.appendChild(b);
    });
    seg.setSelected = function (id) {
      current = id;
      Object.keys(buttons).forEach(function (k) {
        buttons[k].classList.toggle('mf-seg__opt--on', k === current);
      });
    };
    seg.getSelected = function () { return current; };
    return seg;
  }

  /**
   * dayPills({ selected: ['Mon','Tue',...], onChange })
   * Returns a div with 7 pills. selected is the array of selected day codes
   * (3-letter, capitalized). onChange fires with the next selected array.
   */
  function dayPills(opts) {
    var DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    var selected = (opts.selected || []).slice();
    var wrap = el('div', 'mf-day-pills');
    DAYS.forEach(function (d) {
      var p = el('button', 'mf-day-pill' + (selected.indexOf(d) >= 0 ? ' mf-day-pill--on' : ''));
      p.type = 'button';
      p.textContent = d;
      p.setAttribute('aria-pressed', selected.indexOf(d) >= 0 ? 'true' : 'false');
      p.addEventListener('click', function () {
        var i = selected.indexOf(d);
        if (i >= 0) selected.splice(i, 1); else selected.push(d);
        p.classList.toggle('mf-day-pill--on');
        p.setAttribute('aria-pressed', selected.indexOf(d) >= 0 ? 'true' : 'false');
        if (typeof opts.onChange === 'function') opts.onChange(selected.slice());
      });
      wrap.appendChild(p);
    });
    wrap.getSelected = function () { return selected.slice(); };
    return wrap;
  }

  /**
   * miniTable({ columns, rows })
   *   columns — [{ id, label, fr }] (fr = grid-template-columns fraction)
   *   rows    — array of objects keyed by column.id; optional `_tone` =
   *             'ok' | 'err' to color the row's status cell.
   * The cell whose column id is 'status' gets a status class for tone.
   */
  function miniTable(opts) {
    var cols = opts.columns || [];
    var rows = opts.rows || [];
    var wrap = el('div', 'mf-mini-table');
    var template = cols.map(function (c) { return (c.fr || 1) + 'fr'; }).join(' ');

    var head = el('div', 'mf-mini-row mf-mini-row--head');
    head.style.gridTemplateColumns = template;
    cols.forEach(function (c) {
      var cell = el('span', 'mf-mini-cell mf-mini-cell--' + c.id);
      cell.textContent = c.label;
      head.appendChild(cell);
    });
    wrap.appendChild(head);

    rows.forEach(function (row) {
      var r = el('div', 'mf-mini-row' + (row._tone ? ' mf-mini-row--' + row._tone : ''));
      r.style.gridTemplateColumns = template;
      cols.forEach(function (c) {
        var cell = el('span', 'mf-mini-cell mf-mini-cell--' + c.id);
        var v = row[c.id];
        cell.textContent = v == null ? '' : String(v);
        r.appendChild(cell);
      });
      wrap.appendChild(r);
    });
    return wrap;
  }

  /**
   * formSection({ title, desc, body })
   * Section wrapper used inside MFSettingsDetail's form area.
   */
  function formSection(opts) {
    var sec = el('div', 'mf-form-section');
    if (opts.title) {
      var h = el('h3', 'mf-form-section__h');
      h.textContent = opts.title;
      sec.appendChild(h);
    }
    if (opts.desc) {
      var d = el('p', 'mf-form-section__desc');
      d.textContent = opts.desc;
      sec.appendChild(d);
    }
    if (opts.body) sec.appendChild(opts.body);
    return sec;
  }

  global.MFFormControls = {
    fieldRow: fieldRow,
    textInput: textInput,
    toggle: toggle,
    segmented: segmented,
    dayPills: dayPills,
    miniTable: miniTable,
    formSection: formSection,
  };
})(window);
```

- [ ] **Step 3: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/components/form-controls.js`

Expected: zero matches.

- [ ] **Step 4: Commit**

```bash
git add static/js/components/form-controls.js static/css/components.css
git commit -m "feat(ux): MFFormControls factories + settings-detail CSS atoms

Field rows, text input (text/number/readonly/tight), toggle, segmented
control, day-of-week pills, mini-table, form-section wrapper. Each
factory returns a real DOM node — no innerHTML, no template strings
interpolated into HTML.

CSS additions: field-row + day-pills + mini-table + settings-overview
card grid + settings-detail shell (breadcrumb, scoped sidebar,
form-section, save bar with status text). All consume Plan 1A's
--mf-* tokens. Plan 5 Storage and Plan 6's six detail pages share
these atoms. Spec §7."
```

---

## Task 3: `MFSettingsDetail` reusable shell

**Files:**
- Create: `static/js/components/settings-detail.js`

The scoped-sidebar + form-area + save-bar shell every detail page mounts inside. Caller passes a sub-section list and a render-function-per-active-sub-section. The shell handles sidebar highlighting, breadcrumb, save-bar status text, and dirty-tracking. Plan 6 mounts six pages inside this same shell unchanged.

- [ ] **Step 1: Create the component**

Create `static/js/components/settings-detail.js`:

```javascript
/* MFSettingsDetail — reusable scoped-sidebar + form-area shell for
 * Settings detail pages. Caller wires the actual fields per sub-section.
 *
 * Usage:
 *   MFSettingsDetail.mount(slot, {
 *     icon: '⏚',                    // single character or short string
 *     title: 'Storage.',
 *     subtitle: 'Where files come from and go to.',
 *     subsections: [
 *       { id: 'mounts',       label: 'Mounts',              icon: '⏚' },
 *       { id: 'output-paths', label: 'Output paths',        icon: '⚙' },
 *       ...
 *     ],
 *     activeId: 'mounts',
 *     onSubsectionChange: function(id) { ... },
 *     renderForm: function(activeId, formArea, ctx) { ... },
 *     // ctx.markDirty(), ctx.setStatus(state, msg), ctx.onSave(handler),
 *     // ctx.actions = [{ id, label, variant, onClick }]
 *   });
 *
 * Spec §7: detail page = breadcrumb + headline + scoped sidebar + form +
 * save bar (Save changes | contextual actions | Discard | status).
 *
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildBreadcrumb(title) {
    var crumb = el('button', 'mf-crumb');
    crumb.type = 'button';
    crumb.setAttribute('aria-label', 'Back to all settings');
    var arrow = document.createTextNode('← ');
    crumb.appendChild(arrow);
    var allText = el('span');
    allText.textContent = 'All settings';
    crumb.appendChild(allText);
    var sep = el('span', 'mf-crumb__sep');
    sep.textContent = ' / ';
    crumb.appendChild(sep);
    var here = el('span', 'mf-crumb__here');
    here.textContent = title.replace(/\.$/, '');
    crumb.appendChild(here);
    crumb.addEventListener('click', function () {
      window.location.href = '/settings';
    });
    return crumb;
  }

  function buildHeader(opts) {
    var head = el('h1', 'mf-detail-headline');
    if (opts.icon) {
      var ico = el('span', 'mf-detail-headline__icon');
      ico.textContent = opts.icon;
      head.appendChild(ico);
    }
    head.appendChild(document.createTextNode(opts.title));
    var sub = el('p', 'mf-detail-subtitle');
    sub.textContent = opts.subtitle || '';
    var wrap = document.createDocumentFragment();
    wrap.appendChild(head);
    wrap.appendChild(sub);
    return wrap;
  }

  function buildSidebar(subsections, activeId, onChange) {
    var side = el('div', 'mf-detail-side');
    side.setAttribute('role', 'tablist');
    var buttons = {};
    subsections.forEach(function (s) {
      var item = el('button', 'mf-detail-side__item' + (s.id === activeId ? ' mf-detail-side__item--on' : ''));
      item.type = 'button';
      item.setAttribute('role', 'tab');
      item.setAttribute('aria-selected', s.id === activeId ? 'true' : 'false');
      if (s.icon) {
        var ico = el('span');
        ico.style.cssText = 'color:#aaa;margin-right:0.5rem;flex-shrink:0';
        ico.textContent = s.icon;
        item.appendChild(ico);
      }
      var lab = el('span');
      lab.style.cssText = 'flex:1;min-width:0';
      lab.textContent = s.label;
      item.appendChild(lab);
      if (s.badge) {
        var b = el('span', 'mf-detail-side__badge mf-detail-side__badge--' + (s.badgeTone || 'warn'));
        b.textContent = s.badge;
        item.appendChild(b);
      }
      item.addEventListener('click', function () { onChange(s.id); });
      buttons[s.id] = item;
      side.appendChild(item);
    });
    side.setActive = function (id) {
      Object.keys(buttons).forEach(function (k) {
        buttons[k].classList.toggle('mf-detail-side__item--on', k === id);
        buttons[k].setAttribute('aria-selected', k === id ? 'true' : 'false');
      });
    };
    return side;
  }

  function buildSaveBar(ctx) {
    var bar = el('div', 'mf-save-bar');
    var save = el('button', 'mf-pill mf-pill--primary mf-pill--sm');
    save.type = 'button';
    save.textContent = 'Save changes';
    save.disabled = true;
    save.addEventListener('click', function () { ctx._fireSave(); });
    bar.appendChild(save);

    var actionsWrap = el('span');
    actionsWrap.style.cssText = 'display:inline-flex;gap:0.5rem';
    bar.appendChild(actionsWrap);

    var discard = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    discard.type = 'button';
    discard.textContent = 'Discard';
    discard.disabled = true;
    discard.addEventListener('click', function () { ctx._fireDiscard(); });
    bar.appendChild(discard);

    var status = el('span', 'mf-save-bar__status');
    status.textContent = '';
    bar.appendChild(status);

    bar._setSave = function (enabled) {
      save.disabled = !enabled;
      discard.disabled = !enabled;
    };
    bar._setStatus = function (state, msg) {
      status.className = 'mf-save-bar__status' + (state ? ' mf-save-bar__status--' + state : '');
      status.textContent = msg || '';
    };
    bar._setActions = function (actions) {
      while (actionsWrap.firstChild) actionsWrap.removeChild(actionsWrap.firstChild);
      (actions || []).forEach(function (a) {
        var btn = el('button', 'mf-pill mf-pill--' + (a.variant || 'outline') + ' mf-pill--sm');
        btn.type = 'button';
        btn.textContent = a.label;
        btn.addEventListener('click', function () { if (a.onClick) a.onClick(); });
        actionsWrap.appendChild(btn);
      });
    };
    return bar;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSettingsDetail.mount: slot required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var wrap = el('div', 'mf-settings-detail');
    wrap.appendChild(buildBreadcrumb(opts.title || ''));
    wrap.appendChild(buildHeader({ icon: opts.icon, title: opts.title, subtitle: opts.subtitle }));

    var flex = el('div', 'mf-detail-flex');
    var formArea = el('div');

    var saveHandlers = [];
    var discardHandlers = [];
    var dirty = false;

    var bar = buildSaveBar({
      _fireSave: function () { saveHandlers.forEach(function (h) { try { h(); } catch (e) { console.error(e); } }); },
      _fireDiscard: function () { discardHandlers.forEach(function (h) { try { h(); } catch (e) { console.error(e); } }); },
    });

    var ctx = {
      markDirty: function () {
        dirty = true;
        bar._setSave(true);
        bar._setStatus('dirty', 'Unsaved changes');
      },
      markClean: function () {
        dirty = false;
        bar._setSave(false);
        bar._setStatus('saved', 'All changes saved');
      },
      setStatus: function (state, msg) { bar._setStatus(state, msg); },
      onSave: function (handler) { saveHandlers.push(handler); },
      onDiscard: function (handler) { discardHandlers.push(handler); },
      setActions: function (actions) { bar._setActions(actions); },
      isDirty: function () { return dirty; },
    };

    var activeId = opts.activeId || (opts.subsections[0] && opts.subsections[0].id);
    var side = buildSidebar(opts.subsections || [], activeId, function (nextId) {
      if (dirty) {
        var ok = window.confirm('Discard unsaved changes and switch sub-section?');
        if (!ok) return;
        // Treat confirm-discard as discard.
        try { discardHandlers.forEach(function (h) { h(); }); } catch (e) { console.error(e); }
      }
      activeId = nextId;
      side.setActive(nextId);
      // Reset save handlers; the new sub-section installs its own.
      saveHandlers.length = 0;
      discardHandlers.length = 0;
      dirty = false;
      bar._setSave(false);
      bar._setStatus('', '');
      bar._setActions([]);
      while (formArea.firstChild) formArea.removeChild(formArea.firstChild);
      if (typeof opts.renderForm === 'function') opts.renderForm(nextId, formArea, ctx);
      if (typeof opts.onSubsectionChange === 'function') opts.onSubsectionChange(nextId);
    });

    flex.appendChild(side);
    flex.appendChild(formArea);
    wrap.appendChild(flex);
    wrap.appendChild(bar);
    slot.appendChild(wrap);

    if (typeof opts.renderForm === 'function') opts.renderForm(activeId, formArea, ctx);

    return {
      setActiveSubsection: function (id) {
        if (id !== activeId) {
          activeId = id;
          side.setActive(id);
          // Force re-render path through the same flow as click
          var click = new MouseEvent('click');
          // Re-use sidebar click logic instead.
          // (Caller is expected to use side.setActive + opts.renderForm directly
          //  if wanting to bypass dirty-confirm — keep this method simple.)
          while (formArea.firstChild) formArea.removeChild(formArea.firstChild);
          if (typeof opts.renderForm === 'function') opts.renderForm(id, formArea, ctx);
        }
      },
      getActiveSubsection: function () { return activeId; },
    };
  }

  global.MFSettingsDetail = { mount: mount };
})(window);
```

- [ ] **Step 2: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/components/settings-detail.js`

Expected: zero matches.

- [ ] **Step 3: Commit**

```bash
git add static/js/components/settings-detail.js
git commit -m "feat(ux): MFSettingsDetail reusable shell

Scoped sidebar + form area + save bar pattern that every Settings
detail page uses. Caller passes subsections + a renderForm(activeId,
formArea, ctx) callback. ctx exposes markDirty / markClean /
setStatus / onSave / onDiscard / setActions so per-section code
manages its own form lifecycle without re-implementing the chrome.

Sidebar switching prompts on dirty state and resets save handlers.
Spec §7."
```

---

## Task 4: Settings overview page (`/settings`)

**Files:**
- Create: `static/settings-new.html`
- Create: `static/js/pages/settings-overview.js`
- Create: `static/js/settings-overview-boot.js`
- Modify: `main.py`

The card-grid front door. Fetches `/api/me` + `/api/settings/sections` and renders cards grouped by `personal` / `system`. Clicking a card navigates to that section's detail page (only Storage exists in Plan 5; the others return 404 until Plan 6 ships their pages — boot logs `console.warn` for cards whose detail page isn't built yet).

- [ ] **Step 1: Create the template**

Create `static/settings-new.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MarkFlow — Settings</title>
  <link rel="stylesheet" href="/static/css/components.css">
  <style>
    body { margin: 0; background: #f7f7f9; font-family: -apple-system, "SF Pro Display", Inter, system-ui, sans-serif; min-height: 100vh; }
    .mf-settings-page { padding: 2.2rem 2rem 2.6rem; max-width: 1280px; margin: 0 auto; }
    .mf-settings-page h1 { font-size: 2.3rem; line-height: 1.05; letter-spacing: -0.025em; font-weight: 700; color: #0a0a0a; margin: 0 0 0.55rem; }
    .mf-settings-page > p.subtitle { color: #5a5a5a; font-size: 1rem; margin: 0 0 2rem; max-width: 60ch; }
  </style>
</head>
<body data-env="dev">
  <div id="mf-top-nav"></div>
  <div id="mf-settings-overview" class="mf-settings-page"></div>

  <script src="/static/js/preferences.js"></script>
  <script src="/static/js/telemetry.js"></script>
  <script src="/static/js/keybinds.js"></script>
  <script src="/static/js/components/top-nav.js"></script>
  <script src="/static/js/components/version-chip.js"></script>
  <script src="/static/js/components/avatar.js"></script>
  <script src="/static/js/components/avatar-menu.js"></script>
  <script src="/static/js/components/layout-icon.js"></script>
  <script src="/static/js/components/layout-popover.js"></script>
  <script src="/static/js/pages/settings-overview.js"></script>
  <script src="/static/js/settings-overview-boot.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create the page component**

Create `static/js/pages/settings-overview.js`:

```javascript
/* MFSettingsOverview — card grid for /settings.
 * Spec §7. Grouped: Personal (always) + System (operator/admin only).
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  // Map card.id -> detail page url. Plan 5 only ships /settings/storage;
  // unknown ids log a console.warn from the boot before navigating.
  var DETAIL_URLS = {
    'storage':              '/settings/storage',
    'pipeline':             '/settings/pipeline',
    'ai-providers':         '/settings/ai-providers',
    'account-auth':         '/settings/account-auth',
    'notifications-system': '/settings/notifications-system',
    'database-health':      '/settings/database-health',
    'log-management':       '/settings/log-management',
    'display':              '/settings/display',
    'pinned-folders':       '/settings/pinned-folders',
    'notifications-prefs':  '/settings/notifications',
    'profile':              '/settings/profile',
  };

  // Single-character / short-glyph icon for each card. The CSS gradient
  // background does the visual work; the glyph is a quick read.
  var ICON_GLYPH = {
    storage: '⏚',          // earth ground
    pipeline: '⚙',         // gear
    'ai-providers': '❇',   // sparkle
    'account-auth': '⧉',   // two squares
    'notifications-system': '␇',  // bell
    'database-health': '⧇', // squared database
    'log-management': '☰', // trigram
    display: '◪',
    'pinned-folders': '★',
    'notifications-prefs': '␇',
    profile: '⦿',
  };

  function buildCard(card) {
    var c = el('button', 'mf-settings-card');
    c.type = 'button';
    c.setAttribute('data-id', card.id);
    var arrow = el('span', 'mf-settings-card__arrow');
    arrow.textContent = '→';
    c.appendChild(arrow);

    var icon = el('div', 'mf-settings-card__icon');
    icon.textContent = ICON_GLYPH[card.id] || '⋯';
    c.appendChild(icon);

    var title = el('h4', 'mf-settings-card__title');
    title.textContent = card.label;
    c.appendChild(title);

    var blurb = el('p', 'mf-settings-card__blurb');
    blurb.textContent = card.blurb;
    c.appendChild(blurb);

    c.addEventListener('click', function () {
      var url = DETAIL_URLS[card.id];
      if (!url) {
        console.warn('mf: no detail page wired for card:', card.id);
        return;
      }
      MFTelemetry.emit('ui.settings_card_click', { card_id: card.id });
      window.location.href = url;
    });
    return c;
  }

  function buildGroup(label, cards, gateLabel) {
    var grp = el('div', 'mf-settings-group');
    var head = el('div', 'mf-settings-group__head');
    var lab = el('span'); lab.textContent = label;
    head.appendChild(lab);
    if (gateLabel) {
      var gate = el('span', 'mf-settings-group__gate');
      gate.textContent = gateLabel;
      head.appendChild(gate);
    }
    grp.appendChild(head);
    var grid = el('div', 'mf-settings-grid');
    cards.forEach(function (c) { grid.appendChild(buildCard(c)); });
    grp.appendChild(grid);
    return grp;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSettingsOverview.mount: slot required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var h1 = el('h1');
    h1.textContent = 'Settings.';
    slot.appendChild(h1);

    var sub = el('p', 'subtitle');
    sub.textContent = 'Configure the things that matter. The rest is sensible defaults.';
    slot.appendChild(sub);

    var cards = (opts && opts.cards) || [];
    var personal = cards.filter(function (c) { return c.group === 'personal'; });
    var system = cards.filter(function (c) { return c.group === 'system'; });

    if (personal.length) slot.appendChild(buildGroup('Personal', personal));
    if (system.length) slot.appendChild(buildGroup('System', system, 'Admin / operator'));

    if (!personal.length && !system.length) {
      var empty = el('p');
      empty.style.cssText = 'color:#888;font-size:0.9rem;text-align:center;padding:3rem 0';
      empty.textContent = 'No settings sections available for your role.';
      slot.appendChild(empty);
    }
  }

  global.MFSettingsOverview = { mount: mount };
})(window);
```

- [ ] **Step 3: Create the boot script**

Create `static/js/settings-overview-boot.js`:

```javascript
/* Boot for /settings (overview).
 * Fetches /api/me + /api/settings/sections in parallel; mounts chrome
 * (Settings is *not* in the top nav per spec §1, but the avatar/layout
 * still appear), then mounts the card grid.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var overviewRoot = document.getElementById('mf-settings-overview');

  function fetchJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error(url + ' failed: ' + r.status);
      return r.json();
    });
  }

  Promise.all([
    MFPrefs.load(),
    fetchJson('/api/me'),
    fetchJson('/api/settings/sections'),
  ]).then(function (results) {
    var me = results[1];
    var sections = results[2];
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

    // activePage: 'settings' is not a top-nav slot; pass the
    // member-or-not page so the nav doesn't highlight anything.
    MFTopNav.mount(navRoot, { role: me.role, activePage: 'none' });
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

    MFSettingsOverview.mount(overviewRoot, { cards: sections.cards });
  }).catch(function (e) {
    console.error('mf: settings overview boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Settings unavailable. Check console.';
    overviewRoot.appendChild(msg);
  });
})();
```

- [ ] **Step 4: Wire `/settings` route in `main.py` (flag-aware)**

In `main.py`, find the existing `/settings` route (it currently serves `static/settings.html`). Replace its body so it serves the new template when `ENABLE_NEW_UX` is on, falls back otherwise:

```python
from core.feature_flags import is_new_ux_enabled

@app.get("/settings", include_in_schema=False)
async def settings_page():
    """Settings overview. Flag-aware: serves the new card grid when
    ENABLE_NEW_UX=true, falls back to legacy settings.html otherwise.
    """
    if is_new_ux_enabled():
        return FileResponse("static/settings-new.html")
    return FileResponse("static/settings.html")
```

Add the import at the top with other route helpers if not already present.

- [ ] **Step 5: Smoke verify**

```bash
ENABLE_NEW_UX=true docker-compose up -d --force-recreate markflow
```

As an admin user, visit `http://localhost:8000/settings`. Expected:
- "Settings." headline + subtitle
- "Personal" group with 4 cards
- "System" group with `Admin / operator` gate badge + 7 cards
- Hovering a card lifts it; clicking the Storage card navigates to `/settings/storage` (which 404s until Task 5 ships)
- Clicking any other system card logs a `console.warn` ("no detail page wired for card") and stays on the overview

As a member user, expected: only the Personal group with 4 cards renders; no System group.

With `ENABLE_NEW_UX=false`, expected: legacy `static/settings.html` renders unchanged.

- [ ] **Step 6: Commit**

```bash
git add static/settings-new.html static/js/pages/settings-overview.js \
        static/js/settings-overview-boot.js main.py
git commit -m "feat(ux): /settings overview card grid (flag-aware)

MFSettingsOverview groups cards into Personal + System, gates the
System group with an 'Admin / operator' badge, and navigates to the
mapped detail URL on click. Plan 5 only wires Storage; other cards
console.warn until Plan 6 ships them.

main.py /settings flag-aware: serves static/settings-new.html when
ENABLE_NEW_UX=true, falls back to static/settings.html otherwise.

ui.settings_card_click telemetry emitted on every navigation. Spec §7."
```

---

## Task 5: Storage detail page template + boot + `/settings/storage` route

**Files:**
- Create: `static/settings-storage.html`
- Create: `static/js/settings-storage-boot.js`
- Modify: `main.py`

The HTML shell + boot for the first detail page. Component logic ships in Task 6. Boot redirects member-role users to `/settings` (defense-in-depth alongside the endpoint's existing `UserRole.MANAGER` gate).

- [ ] **Step 1: Create the template**

Create `static/settings-storage.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MarkFlow — Settings · Storage</title>
  <link rel="stylesheet" href="/static/css/components.css">
  <style>
    body { margin: 0; background: #f7f7f9; font-family: -apple-system, "SF Pro Display", Inter, system-ui, sans-serif; min-height: 100vh; }
  </style>
</head>
<body data-env="dev">
  <div id="mf-top-nav"></div>
  <div id="mf-settings-storage"></div>

  <script src="/static/js/preferences.js"></script>
  <script src="/static/js/telemetry.js"></script>
  <script src="/static/js/keybinds.js"></script>
  <script src="/static/js/components/top-nav.js"></script>
  <script src="/static/js/components/version-chip.js"></script>
  <script src="/static/js/components/avatar.js"></script>
  <script src="/static/js/components/avatar-menu.js"></script>
  <script src="/static/js/components/layout-icon.js"></script>
  <script src="/static/js/components/layout-popover.js"></script>
  <script src="/static/js/components/form-controls.js"></script>
  <script src="/static/js/components/settings-detail.js"></script>
  <script src="/static/js/pages/settings-storage.js"></script>
  <script src="/static/js/settings-storage-boot.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create the boot**

Create `static/js/settings-storage-boot.js`:

```javascript
/* Boot for /settings/storage. Fetches /api/me, mounts chrome,
 * mounts MFStorageSettings into the detail shell. Member role
 * → redirect to /settings (defense-in-depth alongside backend
 * UserRole.MANAGER gate on /api/storage/*).
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var pageRoot = document.getElementById('mf-settings-storage');

  function fetchJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error(url + ' failed: ' + r.status);
      return r.json();
    });
  }

  Promise.all([MFPrefs.load(), fetchJson('/api/me')]).then(function (results) {
    var me = results[1];
    if (me.role === 'member') {
      window.location.href = '/settings';
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

    MFTopNav.mount(navRoot, { role: me.role, activePage: 'none' });
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

    MFStorageSettings.mount(pageRoot);
  }).catch(function (e) {
    console.error('mf: storage settings boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Storage settings unavailable. Check console.';
    pageRoot.appendChild(msg);
  });
})();
```

- [ ] **Step 3: Wire `/settings/storage` route in `main.py` (flag-aware)**

In `main.py`, add the new route. Place it next to the `/settings` route added in Task 4:

```python
@app.get("/settings/storage", include_in_schema=False)
async def settings_storage_page():
    """Storage detail page. Flag-aware: serves the new shell when
    ENABLE_NEW_UX=true, falls back to legacy storage.html otherwise.
    """
    if is_new_ux_enabled():
        return FileResponse("static/settings-storage.html")
    return FileResponse("static/storage.html")
```

- [ ] **Step 4: Smoke verify (page boots, sub-section list visible — form is empty until Task 6)**

```bash
docker-compose up -d --force-recreate markflow
```

As an admin user with `ENABLE_NEW_UX=true`, visit `http://localhost:8000/settings/storage`. Expected at this point (Task 6 fills the form area):
- Top nav renders
- Breadcrumb "← All settings / Storage" appears
- "Storage." headline with icon glyph
- Empty form area to the right of an empty sidebar (sidebar gets populated in Task 6)

Acceptable: page may look skeletal; no console errors.

As a member, expected: redirect to `/settings`.

- [ ] **Step 5: Commit**

```bash
git add static/settings-storage.html static/js/settings-storage-boot.js main.py
git commit -m "feat(ux): /settings/storage shell — template, boot, route

Flag-aware route falls back to legacy storage.html when
ENABLE_NEW_UX=false. Boot fetches /api/me, mounts chrome, redirects
member role to /settings (defense-in-depth alongside the
UserRole.MANAGER gate on /api/storage/*). Component logic lands
in Task 6."
```

---

## Task 6: `MFStorageSettings` — six sub-sections wired to `/api/storage/*`

**Files:**
- Create: `static/js/pages/settings-storage.js`

The page component. Mounts the `MFSettingsDetail` shell with six sub-sections per spec §7 (Mounts · Output paths · Cloud prefetch · Credentials · Write guard · Sync & verification) and renders one form per active sub-section, calling existing `/api/storage/*` endpoints. No backend changes — this consumes what the v0.28+ Universal Storage Manager already exposes.

The forms are deliberately minimum-viable so the *pattern* is what reviewers verify. Field choices match the locked endpoints; richer per-share editing (add/remove/discover) is left to v1.1 or to the legacy storage.html, which still works behind the flag.

- [ ] **Step 1: Create the component**

Create `static/js/pages/settings-storage.js`:

```javascript
/* MFStorageSettings — Settings → Storage detail page.
 * Six sub-sections per spec §7, wired to existing /api/storage/* endpoints.
 *
 *   Mounts          → /api/storage/sources, /api/storage/shares
 *   Output paths    → /api/storage/output
 *   Cloud prefetch  → /api/preferences (cloud_prefetch_* keys)
 *   Credentials    → /api/storage/shares (list, masked) + /api/storage/shares/{name}/credentials (admin reveal)
 *   Write guard     → /api/storage/output (read-only summary; guard is auto-enforced)
 *   Sync & verification → /api/storage/health, /api/storage/exclusions
 *
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  var FC = null; // assigned in mount() so the module loads even if form-controls failed
  var SUBSECTIONS = [
    { id: 'mounts',          label: 'Mounts',              icon: '⏚' },
    { id: 'output-paths',    label: 'Output paths',        icon: '➟' },
    { id: 'cloud-prefetch',  label: 'Cloud prefetch',      icon: '☁' },
    { id: 'credentials',     label: 'Credentials',         icon: '⧉' },
    { id: 'write-guard',     label: 'Write guard',         icon: '⛂' },
    { id: 'sync-verify',     label: 'Sync & verification', icon: '⧇' },
  ];

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }

  function fetchJson(url, init) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, init || {}))
      .then(function (r) {
        if (!r.ok) throw new Error(url + ' ' + r.status);
        if (r.status === 204) return null;
        return r.json();
      });
  }

  // --- Sub-section renderers ------------------------------------------------

  function renderMounts(formArea, ctx) {
    var loading = el('p', 'mf-form-section__desc');
    loading.textContent = 'Loading…';
    formArea.appendChild(loading);

    Promise.all([
      fetchJson('/api/storage/sources'),
      fetchJson('/api/storage/shares').catch(function () { return { shares: [] }; }),
    ]).then(function (results) {
      formArea.removeChild(loading);
      var sources = (results[0] && results[0].sources) || [];
      var shares = (results[1] && results[1].shares) || [];

      formArea.appendChild(FC.formSection({
        title: 'Source mounts',
        desc: 'Folders on the K Drive that MarkFlow scans. Read-only at this layer; add or remove via legacy storage page until v1.1.',
        body: FC.miniTable({
          columns: [
            { id: 'label', label: 'Label', fr: 1.4 },
            { id: 'path',  label: 'Path',  fr: 2.6 },
          ],
          rows: sources.map(function (s) {
            return { label: s.label || s.id, path: s.path };
          }),
        }),
      }));

      formArea.appendChild(FC.formSection({
        title: 'Network shares (SMB / NFS)',
        desc: 'Shares mounted by Universal Storage Manager. Per-share add / remove still lives on the legacy storage page; this view is read-only summary.',
        body: FC.miniTable({
          columns: [
            { id: 'name',     label: 'Name',     fr: 1 },
            { id: 'protocol', label: 'Protocol', fr: 0.7 },
            { id: 'server',   label: 'Server',   fr: 1.6 },
            { id: 'share',    label: 'Share',    fr: 1.6 },
          ],
          rows: shares.map(function (sh) {
            return { name: sh.name, protocol: sh.protocol, server: sh.server, share: sh.share || '' };
          }),
        }),
      }));

      ctx.setActions([
        { id: 'legacy', label: 'Open legacy storage page', variant: 'outline',
          onClick: function () { window.location.href = '/storage'; } },
      ]);
    }).catch(function (e) {
      console.error(e);
      ctx.setStatus('error', 'Failed to load mounts: ' + e.message);
    });
  }

  function renderOutputPaths(formArea, ctx) {
    fetchJson('/api/storage/output').then(function (data) {
      var current = (data && data.path) || '';
      var nextValue = current;

      var input = FC.textInput({
        value: current,
        onInput: function (v) {
          nextValue = v;
          if (v !== current) ctx.markDirty();
        },
      });

      formArea.appendChild(FC.formSection({
        title: 'Output root',
        desc: 'Where converted Markdown + sidecars are written. The write guard auto-denies writes outside this path.',
        body: FC.fieldRow({ label: 'Path', control: input,
          help: 'Must exist and be writable. Use forward slashes (/mnt/output) in Docker.' }),
      }));

      ctx.onSave(function () {
        if (nextValue === current) return;
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
      });
      ctx.onDiscard(function () {
        nextValue = current;
        input.value = current;
        ctx.markClean();
        ctx.setStatus('', '');
      });
      ctx.setActions([
        { id: 'validate', label: 'Validate path', variant: 'outline',
          onClick: function () {
            ctx.setStatus('saving', 'Validating…');
            fetchJson('/api/storage/validate', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: nextValue, role: 'output' }),
            }).then(function (v) {
              if (v.ok) ctx.setStatus('saved', 'Path is valid');
              else ctx.setStatus('error', 'Invalid: ' + (v.errors || []).join('; '));
            }).catch(function (e) { ctx.setStatus('error', e.message); });
          } },
      ]);
    }).catch(function (e) {
      ctx.setStatus('error', 'Failed to load output: ' + e.message);
    });
  }

  function renderCloudPrefetch(formArea, ctx) {
    // Prefetch keys live in the bulk system-preferences endpoint
    // (api/routes/preferences.py — GET /api/preferences returns
    // { preferences: { key: value, ... }, schema: {...} }; PUT
    // /api/preferences/{key} writes a single key with validation).
    var KEYS = [
      'cloud_prefetch_enabled', 'cloud_prefetch_concurrency',
      'cloud_prefetch_rate_limit', 'cloud_prefetch_timeout_seconds',
      'cloud_prefetch_min_size_bytes', 'cloud_prefetch_probe_all',
    ];
    fetchJson('/api/preferences').then(function (data) {
      var all = (data && data.preferences) || {};
      var prefs = {};
      KEYS.forEach(function (k) { prefs[k] = all[k] == null ? '' : String(all[k]); });
      var draft = Object.assign({}, prefs);

      var enabledTog = FC.toggle({
        on: prefs.cloud_prefetch_enabled === 'true',
        label: 'Cache cloud-only files locally before convert',
        onChange: function (on) { draft.cloud_prefetch_enabled = on ? 'true' : 'false'; ctx.markDirty(); },
      });
      formArea.appendChild(FC.formSection({
        title: 'Cloud prefetch',
        desc: 'Eagerly download Drive / OneDrive / Dropbox files locally so conversion does not stall. Off by default — enable on slow links.',
        body: enabledTog,
      }));

      function numField(label, key, help) {
        var input = FC.textInput({
          type: 'number', tight: true, value: prefs[key],
          onInput: function (v) { draft[key] = v; ctx.markDirty(); },
        });
        return FC.fieldRow({ label: label, control: input, help: help });
      }
      var grid = el('div');
      grid.style.cssText = 'display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:0.85rem';
      grid.appendChild(numField('Concurrency', 'cloud_prefetch_concurrency', 'Parallel downloads (default 5)'));
      grid.appendChild(numField('Rate limit (req/s)', 'cloud_prefetch_rate_limit', 'Max requests per second'));
      grid.appendChild(numField('Timeout (seconds)', 'cloud_prefetch_timeout_seconds', 'Per-file timeout'));
      grid.appendChild(numField('Min size (bytes)', 'cloud_prefetch_min_size_bytes', 'Skip files under this size; 0 = no minimum'));
      formArea.appendChild(FC.formSection({ title: 'Tuning', body: grid }));

      var probeTog = FC.toggle({
        on: prefs.cloud_prefetch_probe_all === 'true',
        label: 'Probe every file (slower scan, fewer surprises)',
        onChange: function (on) { draft.cloud_prefetch_probe_all = on ? 'true' : 'false'; ctx.markDirty(); },
      });
      formArea.appendChild(FC.formSection({ title: 'Probe behavior', body: probeTog }));

      ctx.onSave(function () {
        ctx.setStatus('saving', 'Saving…');
        var dirty = KEYS.filter(function (k) { return draft[k] !== prefs[k]; });
        if (!dirty.length) { ctx.markClean(); return; }
        Promise.all(dirty.map(function (k) {
          return fetchJson('/api/preferences/' + k, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: draft[k] }),
          });
        })).then(function () {
          dirty.forEach(function (k) { prefs[k] = draft[k]; });
          ctx.markClean();
          MFTelemetry.emit('ui.settings_save', { section: 'storage', sub: 'cloud-prefetch', keys: dirty });
        }).catch(function (e) {
          ctx.setStatus('error', 'Save failed: ' + e.message);
        });
      });
      ctx.onDiscard(function () {
        draft = Object.assign({}, prefs);
        // Cheapest path is to re-render the sub-section.
        while (formArea.firstChild) formArea.removeChild(formArea.firstChild);
        renderCloudPrefetch(formArea, ctx);
        ctx.markClean();
      });
    }).catch(function (e) {
      ctx.setStatus('error', 'Failed to load prefs: ' + e.message);
    });
  }

  function renderCredentials(formArea, ctx) {
    fetchJson('/api/storage/shares').then(function (data) {
      var shares = (data && data.shares) || [];
      var rows = shares.map(function (sh) {
        return {
          name: sh.name,
          protocol: sh.protocol,
          username: sh.username || '—',
          password: sh.password ? '••••' : '—',
          _tone: sh.password ? 'ok' : null,
        };
      });
      formArea.appendChild(FC.formSection({
        title: 'Saved share credentials',
        desc: 'Encrypted by SECRET_KEY. Reveal-in-clear is admin-only and audit-logged. Edit, add, or remove credentials on the legacy storage page until v1.1.',
        body: FC.miniTable({
          columns: [
            { id: 'name',     label: 'Share',    fr: 1 },
            { id: 'protocol', label: 'Protocol', fr: 0.7 },
            { id: 'username', label: 'Username', fr: 1.2 },
            { id: 'password', label: 'Stored',   fr: 0.7 },
          ],
          rows: rows,
        }),
      }));
      ctx.setActions([
        { id: 'legacy', label: 'Manage on legacy page', variant: 'outline',
          onClick: function () { window.location.href = '/storage'; } },
      ]);
    }).catch(function (e) {
      ctx.setStatus('error', 'Failed to load shares: ' + e.message);
    });
  }

  function renderWriteGuard(formArea, ctx) {
    fetchJson('/api/storage/output').then(function (data) {
      var path = (data && data.path) || '';
      var status = path ? 'Active' : 'Inactive';
      var tone = path ? 'good' : 'warn';

      var statusRow = el('div', 'mf-field-row mf-field-row--inline');
      var pill = el('span', 'mf-detail-side__badge mf-detail-side__badge--' + tone);
      pill.textContent = status;
      statusRow.appendChild(pill);
      var note = el('span');
      note.style.cssText = 'font-size:0.86rem;color:#333';
      note.textContent = path
        ? 'Writes are restricted to the configured output root.'
        : 'No output root configured — writes are denied. Set an output path in the Output paths sub-section.';
      statusRow.appendChild(note);

      formArea.appendChild(FC.formSection({
        title: 'Write guard',
        desc: 'Auto-enforced based on the configured output root. The guard denies writes outside this path; there is no separate toggle to disable it.',
        body: statusRow,
      }));

      formArea.appendChild(FC.formSection({
        title: 'Allowed write root',
        body: FC.textInput({ value: path, readonly: true }),
      }));
    }).catch(function (e) {
      ctx.setStatus('error', 'Failed to load output: ' + e.message);
    });
  }

  function renderSyncVerify(formArea, ctx) {
    Promise.all([
      fetchJson('/api/storage/health').catch(function () { return { mounts: [] }; }),
      fetchJson('/api/storage/exclusions').catch(function () { return { exclusions: [] }; }),
    ]).then(function (results) {
      var mounts = (results[0] && results[0].mounts) || [];
      var exclusions = (results[1] && results[1].exclusions) || [];

      formArea.appendChild(FC.formSection({
        title: 'Mount health',
        desc: 'Last verified by the 5-minute scheduler tick. Refresh by re-running the page.',
        body: FC.miniTable({
          columns: [
            { id: 'name',         label: 'Mount',         fr: 1 },
            { id: 'status',       label: 'Status',        fr: 0.7 },
            { id: 'last_checked', label: 'Last checked',  fr: 1.2 },
          ],
          rows: mounts.map(function (m) {
            return {
              name: m.name || m.label || '?',
              status: m.online ? 'online' : 'offline',
              last_checked: m.last_checked || '—',
              _tone: m.online ? 'ok' : 'err',
            };
          }),
        }),
      }));

      formArea.appendChild(FC.formSection({
        title: 'Path exclusions',
        desc: 'Sub-paths excluded from scanning. Add / remove on the legacy storage page until v1.1.',
        body: FC.miniTable({
          columns: [
            { id: 'path_prefix', label: 'Path prefix', fr: 3 },
          ],
          rows: exclusions.map(function (ex) { return { path_prefix: ex.path_prefix }; }),
        }),
      }));

      ctx.setActions([
        { id: 'recheck', label: 'Re-check now', variant: 'outline',
          onClick: function () {
            ctx.setStatus('saving', 'Re-checking…');
            // The health endpoint is read-only; "re-check" is a UX cue —
            // re-fetch and re-render. The 5-min scheduler is what actually
            // refreshes mount state.
            fetchJson('/api/storage/health').then(function (r) {
              while (formArea.firstChild) formArea.removeChild(formArea.firstChild);
              renderSyncVerify(formArea, ctx);
              ctx.setStatus('saved', 'Refreshed');
            }).catch(function (e) { ctx.setStatus('error', e.message); });
          } },
      ]);
    }).catch(function (e) {
      ctx.setStatus('error', 'Failed to load health: ' + e.message);
    });
  }

  // --- Mount ----------------------------------------------------------------

  function renderForm(activeId, formArea, ctx) {
    if (activeId === 'mounts')          return renderMounts(formArea, ctx);
    if (activeId === 'output-paths')    return renderOutputPaths(formArea, ctx);
    if (activeId === 'cloud-prefetch')  return renderCloudPrefetch(formArea, ctx);
    if (activeId === 'credentials')     return renderCredentials(formArea, ctx);
    if (activeId === 'write-guard')     return renderWriteGuard(formArea, ctx);
    if (activeId === 'sync-verify')     return renderSyncVerify(formArea, ctx);
    var unknown = el('p', 'mf-form-section__desc');
    unknown.textContent = 'Unknown sub-section: ' + activeId;
    formArea.appendChild(unknown);
  }

  function mount(slot) {
    if (!slot) throw new Error('MFStorageSettings.mount: slot required');
    if (!global.MFFormControls || !global.MFSettingsDetail) {
      throw new Error('MFStorageSettings: MFFormControls + MFSettingsDetail required');
    }
    FC = global.MFFormControls;
    MFSettingsDetail.mount(slot, {
      icon: '⏚',
      title: 'Storage.',
      subtitle: 'Where files come from and go to.',
      subsections: SUBSECTIONS,
      activeId: 'mounts',
      onSubsectionChange: function (id) {
        MFTelemetry.emit('ui.settings_subsection_change', { section: 'storage', sub: id });
      },
      renderForm: renderForm,
    });
  }

  global.MFStorageSettings = { mount: mount };
})(window);
```

- [ ] **Step 2: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/pages/settings-storage.js`

Expected: zero matches.

- [ ] **Step 3: Smoke verify each sub-section**

```bash
docker-compose up -d --force-recreate markflow
```

As an admin user with `ENABLE_NEW_UX=true`, visit `http://localhost:8000/settings/storage`. Click each sub-section in the sidebar:

- **Mounts** — read-only mini-table of sources + shares. "Open legacy storage page" action visible.
- **Output paths** — current output path in a text input. Edit → save bar shows "Unsaved changes". Click "Validate path" → shows "Path is valid" or specific error. Click "Save changes" → "All changes saved".
- **Cloud prefetch** — toggle + 4 numeric inputs + probe toggle. Edit any → save bar dirty. Save → all changed prefs PUT. Discard → re-render at original values.
- **Credentials** — read-only mini-table of saved share credentials with masked passwords.
- **Write guard** — Active/Inactive pill with explanatory text + read-only output root display.
- **Sync & verification** — mount health table + exclusions table. "Re-check now" re-fetches and re-renders.

Switching sub-sections mid-edit → confirm("Discard unsaved changes…") prompt appears.

No console errors expected.

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/settings-storage.js
git commit -m "feat(ux): MFStorageSettings — six sub-sections via /api/storage/*

Mounts (read-only sources + shares), Output paths (read+write +
validate), Cloud prefetch (preferences PUTs), Credentials (read-only
masked), Write guard (auto-enforced status), Sync & verification
(mount health + exclusions). Reuses existing v0.28+ Universal Storage
Manager endpoints — no new backend.

Per-sub-section dirty tracking via MFSettingsDetail's ctx.markDirty
/ markClean. Save / discard / contextual actions all wired.
ui.settings_save + ui.settings_subsection_change telemetry. Spec §7."
```

---

## Task 7: Acceptance check + plan close

**Files:** none modified — verification only.

Run the full plan-5 acceptance checklist before declaring this plan complete. Findings here go to follow-up issues; do not silently fix.

- [ ] `pytest tests/test_settings_sections_endpoint.py -v` — 5 PASS
- [ ] `grep -rn "innerHTML" static/js/components/form-controls.js static/js/components/settings-detail.js static/js/pages/settings-overview.js static/js/pages/settings-storage.js static/js/settings-overview-boot.js static/js/settings-storage-boot.js` — zero matches
- [ ] `docker-compose up -d --force-recreate markflow` — succeeds, no console errors on `/settings` or `/settings/storage`
- [ ] As admin (`ENABLE_NEW_UX=true`):
  - `/settings` renders Personal (4 cards) + System (7 cards, gate badge visible)
  - Clicking Storage card → `/settings/storage`
  - Clicking any other system card → `console.warn` only, stays on overview
  - All six Storage sub-sections render without errors
  - Output-paths edit → save → reload page → value persisted
  - Cloud-prefetch toggle → save → reload page → value persisted
- [ ] As member (`ENABLE_NEW_UX=true`):
  - `/settings` renders Personal only (4 cards), no System group
  - `/settings/storage` redirects to `/settings`
- [ ] As admin (`ENABLE_NEW_UX=false`):
  - `/settings` renders the legacy `static/settings.html` unchanged
  - `/settings/storage` renders the legacy `static/storage.html` unchanged
- [ ] Telemetry events visible in `docker-compose logs -f markflow | grep ui.settings_`:
  - `ui.settings_card_click` on overview card click
  - `ui.settings_subsection_change` on Storage sub-section click
  - `ui.settings_save` on output-paths or cloud-prefetch save
- [ ] `git log --oneline | head -10` shows ~6 task commits in order
- [ ] No new files outside the **Create** list in this plan's file structure

If any item fails, file the specific failure in `docs/bug-log.md` against the v0.35 / Phase 1 milestone, **don't silently fix**. Plan-execution failures are signal, not noise.

- [ ] **Final commit (no code change — just tag the plan as shipped)**

Optional: bump version chip / changelog entry once the deprecation pass merges with Plan 7. For Plan 5 alone, the per-task commits ARE the shipped artifact — no extra commit needed here.

---

## Acceptance check (run before declaring this plan complete)

Identical to Task 7 — that section IS the acceptance check, kept inline so executors don't have to scroll.

Once all green, **Plan 5 is done**. Next plan: `2026-04-28-ux-overhaul-settings-detail-pages.md` (Plan 6 — the remaining six System detail pages: Pipeline, AI providers, Account & auth, Notifications, Database health, Log management).

---

## Self-review

**Spec coverage:**
- §7 (overview card grid + detail-page pattern + Storage sub-sections): ✓ Tasks 1, 2, 3, 4, 5, 6
  - Card grid (Tasks 1 + 4)
  - Detail-page two-column layout (Task 3)
  - Form components: text input, segmented, toggle, day-pills, mini-tables (Task 2)
  - Save bar with Save / contextual / Discard (Task 3)
  - Storage sub-sections (Mounts · Output paths · Cloud prefetch · Credentials · Write guard · Sync & verification): ✓ Task 6
- §11 (role gates: Activity hidden, system cards ≥ operator, member sees personal only): ✓ Task 1 (backend gate), Task 4 (front-end groups), Task 5 (member redirect on detail)

**Spec gaps for this plan (deferred):**
- §7 sub-section sidebars for Pipeline, AI providers, Account & auth, Database health, Log management, Notifications: Plan 6
- §8 (Cost cap & alerts deep-dive): Plan 7
- §11 "Re-auth required to change System settings" enforcement: Plan 6 (Account & auth detail page is where the toggle + JWT-freshness logic land; flagged as out-of-scope above)
- §13 phase-5-specifically item "Preferences sync verified across two machines under same identity": already covered by Plan 1A's `/api/user-prefs` integration (per-user prefs keyed by UnionCore `sub`) — re-verification with two real machines is a Phase 1 ship-gate task, not a Plan 5 implementation task
- §13 phase-5-specifically item "Track-recent-searches OFF path": handled in Plan 1C / Plan 3, not Plan 5
- §13 phase-5-specifically item "localStorage mirror reconciliation tested with conflicting writes (server wins)": Plan 1A integration concern; verification belongs to the Phase 1 ship-gate

**Placeholder scan:**
- No "TODO", "TBD", "implement later" in any task body
- Every step that changes code shows the code
- Every test step has the actual test code
- Every commit step has the actual commit message
- "Add error handling" is *not* used as a placeholder — error handling is shown explicitly per fetch (`.catch` blocks, status text)

**Type / API consistency:**
- `/api/settings/sections` card shape (`{ id, label, blurb, icon, group, role_min }`) consistent across Task 1 (backend) and Task 4 (front-end consumer)
- `Role.MEMBER / OPERATOR / ADMIN` from Plan 1A used in Task 1's backend and assumed in `/api/me`'s response from Plan 4 — verified: Plan 4's `_role_name` map uses the same names
- `MFFormControls.{ fieldRow, textInput, toggle, segmented, dayPills, miniTable, formSection }` defined in Task 2 and consumed verbatim in Task 6 — name match verified
- `MFSettingsDetail.mount(slot, opts)` signature consistent across Task 3 (definition) and Task 6 (caller)
- `ctx.markDirty / markClean / setStatus / onSave / onDiscard / setActions / isDirty` exposed in Task 3 and used in Task 6 — name match verified
- `MFTelemetry.emit(name, props)` matches Plan 1B's existing API; new event names (`ui.settings_card_click`, `ui.settings_subsection_change`, `ui.settings_save`) added to the telemetry taxonomy this plan introduces
- Existing `/api/storage/*` endpoints used as documented in `api/routes/storage.py` v0.25.0 — no shape divergence

**Safe-DOM verification (mandatory final scan):**

```
grep -rn "innerHTML" \
  static/js/components/form-controls.js \
  static/js/components/settings-detail.js \
  static/js/pages/settings-overview.js \
  static/js/pages/settings-storage.js \
  static/js/settings-overview-boot.js \
  static/js/settings-storage-boot.js
```

Expected: empty.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-settings-overview-and-storage.md`.

Sized for: 6 implementer dispatches + 6 spec reviews + 6 code-quality reviews ≈ 18 subagent calls (Task 7 is verification-only, no implementer dispatch).

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
