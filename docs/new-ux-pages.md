# MarkFlow Page Inventory — New-UX Status

> **Last updated:** 2026-05-03 (v0.39.0)
>
> Single source of truth for every page in the app, its UX status, and what
> is needed to build a new-UX equivalent.

---

## How dispatch works

Per-user UX dispatch is handled server-side in `core/ux_dispatch.py`.

1. When the user toggles Display Preferences, `static/js/preferences.js` calls
   `syncUxCookie()` which sets a `mf_use_new_ux=1` (or `=0`) cookie with
   `path=/; Max-Age=31536000`.

2. On every page request, `is_new_ux_for_request(request)` in `core/ux_dispatch.py`
   reads that cookie:
   - Cookie `"1"` → new UX
   - Cookie `"0"` → original UX
   - Cookie absent → falls back to the system-wide `ENABLE_NEW_UX` env flag.

3. `serve_ux_page(request, new_path, orig_path)` returns a `FileResponse` for
   the chosen file.

4. Original-only pages (no new-UX twin yet) include `ux-fallback.js` which
   auto-flips `use_new_ux` to false when the user arrives, so the toggle
   never lies.

## How to build a new-UX equivalent

See `docs/templates/README.md` for the 5-step guide and copy-paste template.
The shortest path: copy `docs/templates/new-ux-page.html` + `new-ux-page-boot.js`
+ `new-ux-page-component.js`, replace all `{{PLACEHOLDER}}` markers, add a
`serve_ux_page()` route in `main.py`, and wire the URL in `avatar-menu-wiring.js`.

---

## Status key

| Value | Meaning |
|---|---|
| `both` | Served from a dispatched route; new-UX and original-UX files both exist |
| `new-only` | No original-UX equivalent (settings sub-pages, etc.) |
| `original-only` | No new-UX equivalent yet; ux-fallback.js auto-flips the toggle |
| `redirect` | Route is a redirect alias (no HTML file served) |

---

## Home / Search

| Page (URL) | Status | New-UX file | Original-UX file | Key API endpoints | Notes |
|---|---|---|---|---|---|
| `/` | `both` | `index-new.html` | `index.html` | `/api/search/*`, `/api/me`, `/api/search/index/status` | Server-dispatched |
| `/convert` | `both` | `convert-new.html` | `index.html` | `/api/convert`, `/api/me` | Server-dispatched; original UX reuses index.html |
| `/search.html` | `original-only` | — | `search.html` | `/api/search/*`, `/api/history` | Catch-all; ux-fallback injected |

---

## Activity / Jobs

| Page (URL) | Status | New-UX file | Original-UX file | Key API endpoints | Notes |
|---|---|---|---|---|---|
| `/activity` | `original-only` | — | `activity.html` | `/api/activity/*`, `/api/me` | No new-UX yet; route in main.py; ux-fallback injected |
| `/status.html` | `original-only` | — | `status.html` | `/api/admin/active-jobs`, `/api/pipeline/stats`, `/api/health` | Catch-all; ux-fallback injected |
| `/history.html` | `original-only` | — | `history.html` | `/api/history` | Catch-all; ux-fallback injected |
| `/bulk` | `both` | `bulk-new.html` | `bulk.html` | `/api/bulk/jobs` | Server-dispatched; new-UX overview list with filter/sort/pagination |
| `/bulk/{id}` | `both` | `bulk-detail-new.html` | `job-detail.html` | `/api/bulk/jobs/{id}`, `/api/bulk/jobs/{id}/files`, `/api/bulk/jobs/{id}/errors`, `/api/bulk/jobs/{id}/stream` | Server-dispatched; new-UX tabbed detail (Overview + Files + Errors + Log); consolidates job-detail + bulk-review |
| `/bulk.html` | `original-only` | — | `bulk.html` | `/api/bulk/jobs/*` | Catch-all; ux-fallback injected; backwards-compat kept |
| `/bulk-review.html` | `original-only` | — | `bulk-review.html` | `/api/bulk/*` | Catch-all; ux-fallback injected; consolidated into `/bulk/{id}` Files tab in new UX (original-only kept for backwards compat) |
| `/job-detail.html` | `original-only` | — | `job-detail.html` | `/api/bulk/jobs/*` | Catch-all; ux-fallback injected; consolidated into `/bulk/{id}` in new UX (original-only kept for backwards compat) |
| `/batch-management.html` | `original-only` | — | `batch-management.html` | `/api/batch/*` | Catch-all; ux-fallback injected |
| `/progress.html` | `original-only` | — | `progress.html` | `/api/convert/progress/*` | Catch-all; ux-fallback injected |

---

## Search results / Document viewer

| Page (URL) | Status | New-UX file | Original-UX file | Key API endpoints | Notes |
|---|---|---|---|---|---|
| `/results.html` | `original-only` | — | `results.html` | redirect → `/history.html` | Catch-all; auto-redirect page; ux-fallback injected |
| `/review.html` | `original-only` | — | `review.html` | `/api/review/*` | Catch-all; ux-fallback injected |
| `/viewer.html` | `original-only` | — | `viewer.html` | `/api/convert/result/*` | Catch-all; ux-fallback injected |
| `/preview.html` | `original-only` | — | `preview.html` | `/api/convert/preview/*` | Catch-all; ux-fallback injected |
| `/flagged.html` | `original-only` | — | `flagged.html` | `/api/review/flagged` | Catch-all; ux-fallback injected |

---

## Pipeline / Files

| Page (URL) | Status | New-UX file | Original-UX file | Key API endpoints | Notes |
|---|---|---|---|---|---|
| `/pipeline` | `redirect` | — | — | — | 301 → `/activity` |
| `/pipeline-files.html` | `original-only` | — | `pipeline-files.html` | `/api/pipeline/files`, `/api/pipeline/stats` | Catch-all; ux-fallback injected |
| `/locations.html` | `original-only` | — | `locations.html` | `/api/locations/*` | Catch-all; ux-fallback injected |
| `/resources.html` | `original-only` | — | `resources.html` | `/api/resources/*` | Catch-all; ux-fallback injected |
| `/unrecognized.html` | `original-only` | — | `unrecognized.html` | `/api/pipeline/unrecognized` | Catch-all; ux-fallback injected |
| `/trash.html` | `original-only` | — | `trash.html` | `/api/lifecycle/trash` | Catch-all; ux-fallback injected |

---

## Settings

| Page (URL) | Status | New-UX file | Original-UX file | Key API endpoints | Notes |
|---|---|---|---|---|---|
| `/settings` | `both` | `settings-new.html` | `settings.html` | `/api/preferences`, `/api/me` | Server-dispatched |
| `/settings/storage` | `new-only` | `settings-storage.html` | — | `/api/mounts/*`, `/api/storage/*` | No original-UX equivalent |
| `/settings/pipeline` | `new-only` | `settings-pipeline.html` | — | `/api/preferences` | No original-UX equivalent |
| `/settings/ai-providers` | `new-only` | `settings-ai-providers.html` | — | `/api/llm-providers/*` | No original-UX equivalent |
| `/settings/ai-providers/cost` | `new-only` | `settings-cost-cap.html` | — | `/api/admin/llm-costs/*` | No original-UX equivalent |
| `/settings/auth` | `new-only` | `settings-auth.html` | — | `/api/auth/*` | No original-UX equivalent |
| `/settings/notifications` | `new-only` | `settings-notifications.html` | — | `/api/preferences` | No original-UX equivalent |
| `/settings/db-health` | `new-only` | `settings-db-health.html` | — | `/api/health`, `/api/admin/db/*` | No original-UX equivalent |
| `/settings/log-management` | `new-only` | `settings-log-mgmt.html` | — | `/api/admin/logs/*` | No original-UX equivalent |
| `/settings/appearance` | `new-only` | `settings-appearance.html` | — | `/api/user-prefs` | No original-UX equivalent |
| `/storage.html` | `original-only` | — | `storage.html` | `/api/mounts/*`, `/api/storage/*` | Catch-all; use `/settings/storage` in new UX; ux-fallback injected |
| `/providers.html` | `original-only` | — | `providers.html` | `/api/llm-providers/*` | Catch-all; use `/settings/ai-providers` in new UX; ux-fallback injected |
| `/db-health.html` | `original-only` | — | `db-health.html` | `/api/health`, `/api/admin/db/*` | Catch-all; use `/settings/db-health` in new UX; ux-fallback injected |
| `/admin.html` | `original-only` | — | `admin.html` | `/api/admin/*` | Catch-all; ux-fallback injected |

---

## Help / Logs

| Page (URL) | Status | New-UX file | Original-UX file | Key API endpoints | Notes |
|---|---|---|---|---|---|
| `/help` | `both` | `help-new.html` | `help.html` | `/api/help/*` | Server-dispatched; aliases: `/help-new`, `/help-new.html` |
| `/log-viewer` | `both` | `log-viewer-new.html` | `log-viewer.html` | `/api/admin/logs/stream` | Server-dispatched; aliases: `/log-viewer-new`, `/log-viewer-new.html` |
| `/log-mgmt` | `both` | `log-mgmt-new.html` | `log-management.html` | `/api/admin/logs/*` | Server-dispatched; aliases: `/log-mgmt-new`, `/log-mgmt-new.html` |
| `/log-levels` | `both` | `log-levels-new.html` | `log-viewer.html` | `/api/admin/log-levels/*` | Server-dispatched; aliases: `/log-levels-new`, `/log-levels-new.html` |
| `/log-management.html` | `original-only` | — | `log-management.html` | `/api/admin/logs/*` | Catch-all (direct .html); ux-fallback injected |
| `/log-viewer.html` | `original-only` | — | `log-viewer.html` | `/api/admin/logs/stream` | Catch-all (direct .html); ux-fallback injected |

---

## Debug / Internal

| Page (URL) | Status | New-UX file | Original-UX file | Key API endpoints | Notes |
|---|---|---|---|---|---|
| `/debug.html` | `original-only` | — | `debug.html` | `/api/debug/*` | Catch-all; no ux-fallback (debug page, not user-facing) |

---

## Pages remaining to build in new UX (priority order)

Based on operator usage patterns:

1. **`/status` (Active Jobs)** — high-value for operators; polls 4 endpoints
2. **`/history`** — primary post-conversion landing page for members
3. **`/pipeline-files`** — operator drill-down from status page
4. **`/locations`** — location management; links to settings
5. **`/bulk`** — bulk job detail view
6. **`/search` (results page)** — new search already has results inline; this is the legacy standalone page
7. **`/viewer`** — document viewer; significant complexity
8. **`/activity`** — operator activity aggregator (has partial new-UX wiring)

Use the template in `docs/templates/` to build each one in ~30 minutes.
