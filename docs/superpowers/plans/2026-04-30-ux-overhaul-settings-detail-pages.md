# UX Overhaul — Remaining Settings Detail Pages (Plan 6)

**Goal:** Land the six remaining settings detail pages so every card on the Settings overview navigates to a real page. Each page follows the established Storage detail pattern: 220px sidebar + content panel, same chrome boot, `mf-xxx__*` CSS namespace. No new backend endpoints needed — all APIs already exist.

**Architecture:** One HTML template + JS component + boot script + CSS block per page. Each page registers its own specific route in `main.py` **before** the `{section}` catch-all (line 550). Boot scripts follow `settings-storage-boot.js` exactly; members redirect to `/`.

**Mockup references:**
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-detail-family.html` — Pipeline detail (full) + all other section taxonomies
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/settings-three-details.html` — AI providers, Notifications, Account & auth

**Out of scope (deferred to Plans 7–8):**
- Cost cap & alerts deep-dive (`/settings/ai-providers/cost`) → Plan 7
- First-run onboarding flow → Plan 8
- Full form saves for every field (read + display is enough for v1 where noted)
- Notification delivery (Slack/email plumbing) — UI only

**Prerequisites:** Plan 5 complete. `settings-storage-boot.js` pattern confirmed working.

---

## Agent dispatch guide

Each task carries its own dispatch line. General rules:

| Complexity | Impl agent | Impl model | Review agent | Review model |
|---|---|---|---|---|
| Real API integration + stateful controls | `mf-impl-high` | sonnet | `mf-rev-high` | sonnet |
| Established pattern + some judgment | `mf-impl-high` | sonnet | `mf-rev-medium` | haiku |
| Mechanical template / CSS / boot copy | `mf-impl-medium` | sonnet | `mf-rev-medium` | haiku |
| Trivial boilerplate (HTML only) | `mf-impl-medium` | haiku | `mf-rev-medium` | haiku |

Override upward (to opus) only if: auth-gating logic added, new DB schema touched, or a task repeatedly fails review.

---

## File structure (this plan creates / modifies)

**Create (6 × 4 files):**
- `static/settings-pipeline.html` + `static/js/pages/settings-pipeline.js` + `static/js/settings-pipeline-boot.js`
- `static/settings-ai-providers.html` + `static/js/pages/settings-ai-providers.js` + `static/js/settings-ai-providers-boot.js`
- `static/settings-auth.html` + `static/js/pages/settings-auth.js` + `static/js/settings-auth-boot.js`
- `static/settings-notifications.html` + `static/js/pages/settings-notifications.js` + `static/js/settings-notifications-boot.js`
- `static/settings-db-health.html` + `static/js/pages/settings-db-health.js` + `static/js/settings-db-health-boot.js`
- `static/settings-log-mgmt.html` + `static/js/pages/settings-log-mgmt.js` + `static/js/settings-log-mgmt-boot.js`

**Modify:**
- `static/css/components.css` — append `mf-pip__*`, `mf-ai__*`, `mf-auth__*`, `mf-notif__*`, `mf-dbh__*`, `mf-log__*` blocks
- `main.py` — add 6 specific routes before the `{section}` catch-all (currently line 550)

---

## Task 1: Pipeline & lifecycle detail

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-high` (model: **sonnet**)
*Rationale: live pause/resume toggle calls real API endpoints; scan schedule day-pills + time inputs need state; preference writes via `PUT /api/preferences/{key}`.*

**APIs consumed:**
- `GET /api/pipeline/status` → `{ enabled, paused, last_scan, next_scan, ... }`
- `GET /api/preferences` → scan_window_start, scan_window_end, scan_days_of_week, lifecycle_grace_days, lifecycle_retention_days, trash_auto_delete, stale_check_enabled, watchdog_enabled, watchdog_timeout_minutes
- `POST /api/pipeline/pause` · `POST /api/pipeline/resume`
- `PUT /api/preferences/{key}` — save field changes (operators only)

**Sidebar sections (6):** Scan schedule · Lifecycle & retention · Trash & cleanup · Stale data check · Pipeline watchdog · Pause & resume *(LIVE badge)*

**Component: `MFPipelineDetail.mount(slot, { status, prefs })`**

- **Scan schedule** — enabled toggle, start/end time inputs (HH:MM), day-of-week pills (Mon–Sun, multi-select), save bar
- **Lifecycle & retention** — grace period (days numeric input), retention period (days numeric input), save bar
- **Trash & cleanup** — auto-delete toggle, retention days input, save bar
- **Stale data check** — enabled toggle, threshold-days input, save bar
- **Pipeline watchdog** — enabled toggle, timeout-minutes input, save bar
- **Pause & resume** — large toggle labeled "Pipeline running"; badge shows LIVE (green) or PAUSED (amber). Clicking the toggle calls pause/resume immediately (no save bar needed); status refreshes from response

Day-pills are rendered as `<button>` elements (not `<a>`) with `aria-pressed`. All save bars: "Save changes" (primary) + "Discard" (ghost); discard resets to last-fetched values.

**Boot:** Fetches `/api/me` + `/api/pipeline/status` + `/api/preferences` in parallel. Members → `/`. Operators+.

- [ ] **Step 1:** Create `static/settings-pipeline.html` — same chrome stack, slot `#mf-pipeline`
- [ ] **Step 2:** Create `static/js/pages/settings-pipeline.js` — `MFPipelineDetail`
- [ ] **Step 3:** Create `static/js/settings-pipeline-boot.js`
- [ ] **Step 4:** Append `mf-pip__*` CSS to `components.css` — day-pill styles, live badge, save bar, toggle-row; reuse `mf-stg__` field/label tokens where possible
- [ ] **Step 5:** Insert route in `main.py` before the `{section}` catch-all:
  ```python
  @app.get("/settings/pipeline", include_in_schema=False)
  async def settings_pipeline_page():
      return FileResponse("static/settings-pipeline.html")
  ```
- [ ] **Step 6:** Commit `feat(ux): Pipeline & lifecycle settings detail (Plan 6 Task 1)`

---

## Task 2: AI providers detail

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-high` (model: **sonnet**)
*Rationale: provider list is dynamic (0–N providers); verify/activate are real POST calls; cost cap sub-section links to Plan 7 page.*

**APIs consumed:**
- `GET /api/llm-providers` → `[{ id, name, provider_type, is_active, is_ai_assist, api_key_masked, model, ... }]`
- `GET /api/llm-providers/registry` → available provider types + display names
- `POST /api/llm-providers/{id}/verify` → `{ ok, latency_ms, error? }`
- `POST /api/llm-providers/{id}/activate` → `{ ok }`
- `POST /api/llm-providers/{id}/use-for-ai-assist` → `{ ok }`

**Sidebar sections (6):** Active provider chain · Anthropic · OpenAI · Image analysis routing · Vector indexing · Cost cap & alerts

**Component: `MFAIProvidersDetail.mount(slot, { providers, registry })`**

- **Active provider chain** — table listing all configured providers: name, type badge, active badge (green), AI assist badge, verify button. "Add provider" link → coming soon stub for v1.
- **Anthropic / OpenAI** — each shows as a sidebar entry only if that provider type is present in `providers`. Content: masked API key field (read-only `****`), model name (read-only), verify button, "Set active" button (disabled if already active). If no provider of that type, show a "Not configured — add via the Storage page" stub pointing to legacy settings.
- **Image analysis routing** — read-only display of which provider handles image analysis; "Configure in AI Assist settings" link for v1.
- **Vector indexing** — Qdrant URL (read-only from preferences), index status (from health if available or "unknown").
- **Cost cap & alerts** — sidebar link navigates to `/settings/ai-providers/cost` (Plan 7). Content panel shows a simple "Configure cost caps and rate tables →" card with arrow.

Sidebar entries for Anthropic/OpenAI are hidden if no provider of that type is configured (dynamic sidebar based on `providers`).

**Boot:** Fetches `/api/me` + `/api/llm-providers` + `/api/llm-providers/registry`. Members → `/`. Operators+.

- [ ] **Step 1:** Create `static/settings-ai-providers.html` — slot `#mf-ai-providers`
- [ ] **Step 2:** Create `static/js/pages/settings-ai-providers.js` — `MFAIProvidersDetail`
- [ ] **Step 3:** Create `static/js/settings-ai-providers-boot.js`
- [ ] **Step 4:** Append `mf-ai__*` CSS — provider badge, active/verify button states, dynamic sidebar
- [ ] **Step 5:** Insert route in `main.py`:
  ```python
  @app.get("/settings/ai-providers", include_in_schema=False)
  async def settings_ai_providers_page():
      return FileResponse("static/settings-ai-providers.html")
  ```
- [ ] **Step 6:** Commit `feat(ux): AI providers settings detail (Plan 6 Task 2)`

---

## Task 3: Account & auth detail

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-medium` (model: **haiku**)
*Rationale: displays identity from `/api/me` + JWT/session prefs; mostly read-only; auth-adjacent but no write logic beyond preference toggles.*

**APIs consumed:**
- `GET /api/me` → identity, role, build
- `GET /api/preferences` → jwt_issuer, jwt_audience, session_timeout_minutes, reauth_for_system_settings

**Sidebar sections (5):** Identity · JWT validation · Role mapping · Sessions & timeout · Audit log

**Component: `MFAuthDetail.mount(slot, { me, prefs })`**

- **Identity** — sub claim (monospace, read-only), email (read-only), role pill (member/operator/admin), scope ("IBEW Local 46"), "Managed by UnionCore" note.
- **JWT validation** — issuer (read-only), audience (read-only), JWKS URL (read-only or "derived from issuer"). All fields use `.mf-stg__field-input` read-only styling. Note: "Managed by UnionCore deployment — contact your admin to change."
- **Role mapping** — static table showing the 4-tier → 3-tier mapping: SEARCH_USER→member, OPERATOR→operator, MANAGER→operator, ADMIN→admin. Read-only for v1.
- **Sessions & timeout** — session_timeout_minutes input (numeric, operators only), re-auth gate toggle. Save bar.
- **Audit log** — "View in Log management →" link to `/settings/log-management`; no inline table for v1.

**Boot:** Fetches `/api/me` + `/api/preferences`. Members → `/`. Operators+.

- [ ] **Step 1:** Create `static/settings-auth.html` — slot `#mf-auth`
- [ ] **Step 2:** Create `static/js/pages/settings-auth.js` — `MFAuthDetail`
- [ ] **Step 3:** Create `static/js/settings-auth-boot.js`
- [ ] **Step 4:** Append `mf-auth__*` CSS — role pill in content area, mapping table, read-only note style
- [ ] **Step 5:** Insert route in `main.py`:
  ```python
  @app.get("/settings/auth", include_in_schema=False)
  async def settings_auth_page():
      return FileResponse("static/settings-auth.html")
  ```
- [ ] **Step 6:** Commit `feat(ux): Account & auth settings detail (Plan 6 Task 3)`

---

## Task 4: Notifications detail

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-medium` (model: **haiku**)
*Rationale: toggles + text inputs writing to preferences; channel config (Slack webhook URL) needs save logic; otherwise a pattern repeat.*

**APIs consumed:**
- `GET /api/preferences` → slack_webhook_url, email_smtp_host, email_smtp_port, email_to, notifications_enabled, quiet_hours_start, quiet_hours_end, notification_triggers_json

**Sidebar sections (4):** Channels · Trigger rules · Quiet hours · Test send

**Component: `MFNotificationsDetail.mount(slot, { prefs })`**

- **Channels** — Slack: enabled toggle + webhook URL text input. Email: enabled toggle + SMTP host + port + to-address. Save bar per channel.
- **Trigger rules** — list of toggleable trigger events (from `notification_triggers_json`): "Bulk job failed", "Pipeline auto-aborted", "Consecutive scan errors", "Disk space warning", "Mount health degraded". Each is a toggle row. Save bar at bottom.
- **Quiet hours** — enabled toggle, start time input (HH:MM), end time input (HH:MM). Save bar.
- **Test send** — "Send test notification" primary button. On click: POST to `/api/preferences` is not sufficient here — show "Test send not yet implemented" stub for v1. Plan 7 (Notifications backend) will wire this.

Members may access Notifications (it's not `adminOnly` per the overview card). Adjust boot to allow members.

**Boot:** Fetches `/api/me` + `/api/preferences`. Members allowed. Role check: members see read-only view, operators can save.

- [ ] **Step 1:** Create `static/settings-notifications.html` — slot `#mf-notifications`
- [ ] **Step 2:** Create `static/js/pages/settings-notifications.js` — `MFNotificationsDetail`
- [ ] **Step 3:** Create `static/js/settings-notifications-boot.js` (no member redirect)
- [ ] **Step 4:** Append `mf-notif__*` CSS — trigger-rule list, channel card, quiet-hours row
- [ ] **Step 5:** Insert route in `main.py`:
  ```python
  @app.get("/settings/notifications", include_in_schema=False)
  async def settings_notifications_page():
      return FileResponse("static/settings-notifications.html")
  ```
- [ ] **Step 6:** Commit `feat(ux): Notifications settings detail (Plan 6 Task 4)`

---

## Task 5: Database health detail

**Agent dispatch:** `mf-impl-medium` (model: **sonnet**) · review: `mf-rev-medium` (model: **haiku**)
*Rationale: mostly read-only stats display + three action buttons; plan supplies the full structure; no complex state.*

**APIs consumed:**
- `GET /api/db/health` → `{ db_path, db_size_bytes, pool_size, write_queue_depth, last_compaction, last_integrity_check, integrity_ok, ... }`
- `GET /api/db/maintenance-log` → `[{ timestamp, action, result }]` (last N entries)
- `POST /api/db/compact` → `{ ok, duration_ms }`
- `POST /api/db/integrity-check` → `{ ok, issues }` (runs in background; poll or handle synchronously)

**Sidebar sections (5):** Connection pool · Backups · Maintenance window · Migrations · Integrity check

**Component: `MFDBHealthDetail.mount(slot, { health, log })`**

- **Connection pool** — pool_size, write_queue_depth, db_size (human-readable), db_path (monospace read-only). All read-only.
- **Backups** — last_backup timestamp or "never", backup path pref (read-only for v1). "Configure in docker-compose.yml" note.
- **Maintenance window** — last_compaction timestamp, "Run compaction now" button. On click: POST `/api/db/compact`; show inline spinner then result pill.
- **Migrations** — "All migrations applied" status pill or count of pending. Read-only for v1.
- **Integrity check** — last check timestamp + result (OK pill or warning). "Run now" button → POST `/api/db/integrity-check`; show result inline.

Action buttons: disable after click until response returns. Show result as a status pill (green OK / red error) inline below the button. No save bar (all actions are immediate).

**Boot:** Fetches `/api/me` + `/api/db/health` + `/api/db/maintenance-log` (handle 403 gracefully). Members → `/`. Operators+.

- [ ] **Step 1:** Create `static/settings-db-health.html` — slot `#mf-db-health`
- [ ] **Step 2:** Create `static/js/pages/settings-db-health.js` — `MFDBHealthDetail`
- [ ] **Step 3:** Create `static/js/settings-db-health-boot.js`
- [ ] **Step 4:** Append `mf-dbh__*` CSS — stat grid, action-result pill, spinner (CSS keyframe)
- [ ] **Step 5:** Insert route in `main.py`:
  ```python
  @app.get("/settings/db-health", include_in_schema=False)
  async def settings_db_health_page():
      return FileResponse("static/settings-db-health.html")
  ```
- [ ] **Step 6:** Commit `feat(ux): Database health settings detail (Plan 6 Task 5)`

---

## Task 6: Log management detail

**Agent dispatch:** `mf-impl-medium` (model: **sonnet**) · review: `mf-rev-medium` (model: **haiku**)
*Rationale: log level dropdowns + retention inputs writing to `/api/logs/settings`; file list table is read-only; pattern is fully established.*

**APIs consumed:**
- `GET /api/logs` → `[{ name, size_bytes, modified, compressed }]`
- `GET /api/logs/settings` → `{ max_size_mb, keep_days, compress_on_rotate, subsystem_levels: { ... } }`
- `PUT /api/logs/settings` → update compression/retention/levels

**Sidebar sections (4):** Levels per subsystem · Retention & rotation · Live viewer · Export & archive

**Component: `MFLogMgmtDetail.mount(slot, { files, settings })`**

- **Levels per subsystem** — table of subsystem name → `<select>` (DEBUG / INFO / WARNING / ERROR / CRITICAL) pre-filled from `subsystem_levels`. Save bar. Admins only for saves.
- **Retention & rotation** — max_size_mb numeric input, keep_days numeric input, compress_on_rotate toggle. Save bar.
- **Live viewer** — "Open live log viewer" primary pill button; links to existing `/logs` route (the legacy live viewer page). For v1 this is a navigation link, not an inline viewer.
- **Export & archive** — file inventory table: name, size (human-readable), modified date, compressed badge. "Download" button per row links to `/api/logs/download/{name}`. "Download bundle" button at top triggers `POST /api/logs/download-bundle` with all file names.

**Boot:** Fetches `/api/me` + `/api/logs` + `/api/logs/settings` (handle 403 gracefully). Members → `/`. Admins only (log management is admin-gated).

- [ ] **Step 1:** Create `static/settings-log-mgmt.html` — slot `#mf-log-mgmt`
- [ ] **Step 2:** Create `static/js/pages/settings-log-mgmt.js` — `MFLogMgmtDetail`
- [ ] **Step 3:** Create `static/js/settings-log-mgmt-boot.js`
- [ ] **Step 4:** Append `mf-log__*` CSS — level-select row, file-inventory table, download button
- [ ] **Step 5:** Insert route in `main.py`:
  ```python
  @app.get("/settings/log-management", include_in_schema=False)
  async def settings_log_management_page():
      return FileResponse("static/settings-log-mgmt.html")
  ```
- [ ] **Step 6:** Commit `feat(ux): Log management settings detail (Plan 6 Task 6)`

---

## Acceptance checks

- [ ] `grep -rn "innerHTML" static/js/pages/settings-pipeline.js static/js/pages/settings-ai-providers.js static/js/pages/settings-auth.js static/js/pages/settings-notifications.js static/js/pages/settings-db-health.js static/js/pages/settings-log-mgmt.js` — zero matches
- [ ] All 6 new routes return 200 (not 302) in curl/browser
- [ ] `GET /settings/pipeline` → `GET /settings/ai-providers` → `GET /settings/auth` → `GET /settings/notifications` → `GET /settings/db-health` → `GET /settings/log-management` all 200
- [ ] `GET /settings/unknown-section` still → 302 to `/settings` (catch-all still fires)
- [ ] Settings overview Storage card now has 5 siblings all rendering detail pages
- [ ] Pipeline Pause & resume toggle calls correct API and reflects state
- [ ] AI providers sidebar hides provider entries for unconfigured provider types
- [ ] Notifications boot does NOT redirect members (notifications card is member-accessible)
- [ ] Database health action buttons disable while request in-flight
- [ ] Log management Download bundle triggers the correct POST
- [ ] `git log --oneline | head -8` shows 6 task commits (one per page)
