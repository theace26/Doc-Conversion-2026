# UX Overhaul — Settings Overview + Storage Detail (Plan 5)

**Goal:** Land the Settings overview card grid (`/settings` when `ENABLE_NEW_UX=true`) and the Storage detail page (`/settings/storage`). The overview is the front door to all settings sections; Storage is the first detail page because its data is already available via existing `/api/storage/*` endpoints.

**Architecture:** `static/settings-new.html` + `MFSettingsOverview` component for the overview. `static/settings-storage.html` + `MFStorageDetail` component for the detail. Both use the same chrome boot pattern (fetch `/api/me`, mount TopNav). Storage detail reads `/api/storage/shares`, `/api/storage/output`, `/api/storage/health`. No new backend endpoints.

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-hybrid.html` (overview → detail pattern), `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-detail-family.html` (sidebar form pattern).

**Out of scope (deferred to Plans 6–7):**
- Full form management (create/edit mount, set output path via UI)
- Pipeline, AI Providers, Account & Auth, Notifications, Advanced detail pages
- Cost cap drill-down

**Prerequisites:** Plans 1A + 1B + 1C + 2A + 2B + 3 + 4 complete.

---

## File structure (this plan creates / modifies)

**Create:**
- `static/settings-new.html` — Settings overview template
- `static/js/pages/settings-overview.js` — `MFSettingsOverview` card grid component
- `static/js/settings-new-boot.js` — boot: fetches `/api/me`, mounts chrome + overview
- `static/settings-storage.html` — Storage detail template
- `static/js/pages/settings-storage.js` — `MFStorageDetail` sidebar + content component
- `static/js/settings-storage-boot.js` — boot: fetches `/api/me` + storage data, mounts page

**Modify:**
- `static/css/components.css` — append settings + storage CSS
- `main.py` — add `/settings` and `/settings/storage` routes

---

## Task 1: Settings overview page

**Files:**
- Create: `static/settings-new.html`
- Create: `static/js/pages/settings-overview.js`
- Create: `static/js/settings-new-boot.js`
- Modify: `static/css/components.css` (append)
- Modify: `main.py`

- [x] **Step 1: Create template**

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
    body { margin: 0; background: var(--mf-bg-page); font-family: -apple-system, "SF Pro Display", Inter, system-ui, sans-serif; min-height: 100vh; }
  </style>
</head>
<body data-env="dev">
  <div id="mf-top-nav"></div>
  <div id="mf-settings"></div>

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
  <script src="/static/js/settings-new-boot.js"></script>
</body>
</html>
```

- [x] **Step 2: Create MFSettingsOverview component**

Create `static/js/pages/settings-overview.js`. Safe DOM throughout.

Cards: Storage, Pipeline, AI Providers, Account & Auth, Notifications, Advanced.
Admin-only cards shown only when `opts.role !== 'member'`.

- [x] **Step 3: Create settings-new-boot.js**

Boot pattern identical to `activity-boot.js`: fetch `/api/me`, mount chrome with `activePage: 'settings'`, mount `MFSettingsOverview`.

Members are allowed on this page (Display + Pinned folders are member-facing).

- [x] **Step 4: Append settings CSS to components.css**

Append `mf-settings__*` classes for: body, headline, subtitle, grid (2-col), card, card-icon, card-arrow, card-title, card-desc. Matches `settings-hybrid.html` mockup.

- [x] **Step 5: Wire /settings route in main.py**

```python
@app.get("/settings", include_in_schema=False)
async def settings_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-new.html")
    return FileResponse("static/settings.html")
```

- [x] **Step 6: Commit**

```bash
git commit -m "feat(ux): Settings overview card grid (Plan 5 Task 1)"
```

---

## Task 2: Storage detail page

**Files:**
- Create: `static/settings-storage.html`
- Create: `static/js/pages/settings-storage.js`
- Create: `static/js/settings-storage-boot.js`
- Modify: `static/css/components.css` (append)
- Modify: `main.py`

- [x] **Step 1: Create template**

Create `static/settings-storage.html` — same chrome stack, mounts `MFStorageDetail` in `#mf-storage`.

- [x] **Step 2: Create MFStorageDetail component**

Create `static/js/pages/settings-storage.js`.

`MFStorageDetail.mount(slot, { shares, output, health, activeSection })` — two-column layout:
- **Left sidebar** (200px): Mounts · Output paths · Cloud prefetch · Credentials · Write guard · Sync & verification. Click a row sets the active section.
- **Right content**: renders based on `activeSection`:
  - `mounts`: table of shares (name, path, type, status pill) + "Manage in Storage page" link
  - `output`: current output path (read-only field) + sources list
  - Others: "Coming soon — configure in [legacy link]" stub

Breadcrumb: `← All settings` links to `/settings`.

- [x] **Step 3: Create settings-storage-boot.js**

Fetches `/api/me` + `/api/storage/shares` + `/api/storage/output` + `/api/storage/health` in parallel. Mounts chrome + `MFStorageDetail`. Members redirected to `/`.

- [x] **Step 4: Append storage-detail CSS to components.css**

Append `mf-stg__*` classes: detail-flex (220px + 1fr grid), sidebar, sidebar link (active + hover), breadcrumb, form-section, field-label, field-input (read-only), share-table, status pills, save-bar.

- [x] **Step 5: Wire /settings/storage route in main.py**

```python
@app.get("/settings/storage", include_in_schema=False)
async def settings_storage_page():
    return FileResponse("static/settings-storage.html")
```

Also add a catch-all for other settings sections to redirect gracefully:

```python
@app.get("/settings/{section}", include_in_schema=False)
async def settings_section_page(section: str):
    # Future plans implement each section. For now redirect to overview.
    return RedirectResponse("/settings", status_code=302)
```

- [x] **Step 6: Commit**

```bash
git commit -m "feat(ux): Storage detail page — sidebar + mounts/output view (Plan 5 Task 2)"
```

---

## Acceptance check

- [x] `grep -rn "innerHTML" static/js/pages/settings-overview.js static/js/pages/settings-storage.js` — zero matches
- [x] `GET /settings` (flag on) → serves settings-new.html (200, not redirect)
- [x] `GET /settings` (flag off) → serves settings.html (200)
- [x] `GET /settings/storage` → serves settings-storage.html
- [x] `GET /settings/pipeline` → 302 to `/settings`
- [x] Settings overview cards render; Storage card navigates to `/settings/storage`
- [x] Storage detail: sidebar renders 6 sections, Mounts sub-section shows shares table
- [x] Breadcrumb `← All settings` on Storage detail navigates to `/settings`
- [x] `git log --oneline | head -5` shows 2 task commits
