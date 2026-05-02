# MarkFlow Version History

Detailed changelog for each version/phase. Referenced from CLAUDE.md.

---

## v0.37.1 — Theme system reaches legacy original-UX pages (2026-05-02)

**Goal:** Make the v0.37.0 Display Preferences (theme / font / text-scale) visibly apply to the 26 legacy original-UX HTML pages, not just the new-UX surfaces. Resolves four sub-bugs (BUG-025 through BUG-028) clustered around the same root cause: `static/markflow.css` was never plumbed into the v0.37.0 `[data-theme]` token system and had its own parallel custom-prop block plus 7 `@media (prefers-color-scheme: dark)` overrides.

**Why this matters:** v0.37.0 shipped a polished theme picker that did nothing on most pages a typical operator actually visits day-to-day (index, bulk, storage, admin, help, resources). Clicking a theme swatch would re-color the new-UX chrome and the drawer itself, but `/index.html` stayed the same color. Worse, on a dark-OS machine the legacy stylesheet's `@media (prefers-color-scheme: dark)` block actively fought the user's chosen theme — Classic Light + dark-OS rendered dark anyway. v0.37.1 closes this gap.

**What changed:**

1. **`bbe3753` — Display Preferences drawer + avatar-menu wiring fix (preliminary commit, before the markflow.css refactor).** `app.js`'s `_loadAvatarMenu()` chain now loads `preferences.js` first so `MFPrefs` is defined when the drawer's `open()` calls `MFPrefs.get('theme')`. Without this, the drawer silently `ReferenceError`'d on every legacy page (BUG-025). Same commit also extracted a new `MFAvatarMenuWiring` helper (`static/js/components/avatar-menu-wiring.js`, 138 lines) that owns avatar-menu mount + ID->URL routing for both UX modes + coming-soon toast + drawer lazy-load + sign-out, replacing ~250 lines of duplicated wiring across `app.js` and 13 `*-boot.js` files (BUG-026 — 12 of 16 menu items previously fell through to `console.log`).

2. **8-phase markflow.css refactor (commits `78826b3` through `8a272dc`).** Reconciles legacy stylesheet with v0.37.0 token system:
   - Phase 1 — Added 5 new tokens to `design-tokens.css :root`: `--mf-surface-alt`, `--mf-color-text-on-accent`, `--mf-color-accent-hover`, `--mf-color-info`, `--mf-radius-sm`. Added classic-dark overrides for 5 (incl. `--mf-shadow-press` and `--mf-shadow-popover` to preserve markflow.css's old dark-mode shadow values).
   - Phase 2 — Deleted markflow.css's `:root` custom-prop block (lines 8-29) and main `@media (prefers-color-scheme: dark) { :root { ... } }` block (lines 31-50). Rewrote the 6 remaining `@media (prefers-color-scheme: dark)` blocks (badge dark variants, storage-verify dark variants, flag-banner dark, stop-banner dark, tool-* dark, db-tool-* dark) as `html[data-theme="classic-dark"]` selector prefixes — the styles are preserved, but they now fire from the user's theme choice, not the OS preference. Renamed all 302 `var(--...)` references in markflow.css from local custom-prop names (`--bg`, `--surface`, `--text`, `--accent`, `--ok`, `--warn`, `--error`, `--info`, `--radius`, `--font-sans`, `--font-mono`, `--shadow`, `--shadow-lg`, `--transition`, ...) to their `--mf-*` equivalents per a 20-row rename map.
   - Phases 3-8 — Per-section literal-substitution sweep using a documented decision tree (exact match / drift-<=-5 snap / new-token / kept-as-literal / status-snap). ~50 hardcoded color literals substituted to `var(--mf-...)` calls. One additional new token introduced: `--mf-color-accent-glow` for the toggle-switch on-state shadow.

3. **`fd3f80c` — Font + text-scale wiring fixes from Phase-2 visual checkpoint #1.** Spec A11 originally bound markflow's `--font-sans` -> `--mf-font-sans`. But `--mf-font-sans` is hardcoded in design-tokens.css; design-themes.css's `[data-font="X"]` rules override `--mf-font-family`. Renamed 5 `var(--mf-font-sans)` -> `var(--mf-font-family)` in markflow.css so the drawer's font picker actually applies. Also wrapped `html { font-size: 16px }` in `calc(16px * var(--mf-text-scale, 1))` — single-line change that makes every rem-based font-size in the file scale with the drawer's text-size selector.

4. **`a710c5c` and `d8ddb13` — Visible-text highlighting from Phase-2 visual checkpoints #1 and #2.** User reported that page titles, section headers, and the drop-zone CTA didn't visibly recolor on theme switches because they inherited body text color (`--mf-color-text`), and the deltas across themes for body text were subtle on the user's display. Promoted h1, h2, h3, `.card-header`, and `.section-title` to `color: var(--mf-color-accent)`, plus the drop-zone CTA paragraph and its `<strong>`/`<em>` inline emphasis. Theme switches now visibly re-color the prominent text on every legacy page.

5. **`8ef45b9` — Display Prefs drawer scale-row wraps gracefully (BUG-028).** `.mf-disp-drawer__scale-row` switched from `grid-template-columns: repeat(4, 1fr)` to `repeat(auto-fit, minmax(80px, 1fr))`. At X-Large text scale, the four buttons now reflow into 2x2 instead of overflowing.

6. **Font list cleanup.** Removed Inter, IBM Plex Sans, Poppins, and DM Sans from the drawer FONTS list, FONT_FAMILIES map, and design-themes.css `[data-font]` selectors — at body sizes on macOS, all four rendered visually identical to system-ui (SF Pro). Replaced with **Comic Sans MS** as a system-installed alternative (no Google Fonts dependency). Drawer now offers 11 fonts down from 14, every one visibly distinct.

**Design decisions:**

- **Full rename over alias bridge.** Spec considered two options for handling markflow's local custom-prop namespace (`--surface`, `--text`, etc.): (alpha) add `:root { --surface: var(--mf-surface); ... }` aliases in design-tokens.css so existing `var(--surface)` calls auto-track; (beta) rewrite every `var(--surface)` to `var(--mf-surface)` in markflow.css. User picked beta. Rationale: cleaner end state, single canonical namespace, no two-level resolution chain. Cost: ~24 extra substitutions in the change-index. Tradeoff accepted.
- **Delete the OS dark-mode media query (no fallback).** v0.37.1 removes `@media (prefers-color-scheme: dark)` from markflow.css entirely. Users who want dark on legacy pages now pick Classic Dark in the drawer (or stay on the system default if Nebula is configured). Rationale: keeping the media query alongside `[data-theme]` creates cascade conflicts; the theme system is the correct mechanism for dark-mode opt-in. Edge case: a user previously on Classic Light + dark-OS will now see Classic Light's actual light colors instead of OS-forced dark. This is the intended behavior — operators can override via the drawer.
- **Status colors converge to existing tokens (A4 mandate).** The decision tree's status-snap branch routes any error/warn/success/info-toned literal to `--mf-color-success`/`warn`/`error`/`info` (or `*_bg` variants) regardless of small drift from the original markflow.css value. Rationale: status colors carry semantic meaning, not aesthetic; consistency across UX modes matters more than pixel-fidelity to the legacy palette. ~40 of the ~50 substitutions across Phase 8 fell into this branch.
- **Promote h1/h2/h3 + section-title + drop-zone CTA to accent color.** User explicitly requested visible highlighting on titles after Phase-2 checkpoint #1, then again after checkpoint #2. Rationale: body color shifts subtle; accent color shifts dramatic across themes (purple -> orange -> green -> pink). h4 left alone (small/label-like usage).

**Files modified:**
- `static/markflow.css` — 1684 -> 1631 lines; net -53 lines after deletions and re-prefixing
- `static/css/design-tokens.css` — 6 new tokens (5 from spec + accent-glow)
- `static/css/design-themes.css` — 5 classic-dark overrides + Comic Sans `[data-font]` rule; removed 4 obsolete `[data-font]` rules
- `static/js/components/display-prefs-drawer.js` — FONTS list cleaned up
- `static/css/components.css` — scale-row CSS fix
- `static/app.js` — preferences.js loaded in chain; delegated to `MFAvatarMenuWiring`
- 13 `static/js/*-boot.js` — refactored to call `MFAvatarMenuWiring.mount()` instead of inline wiring
- 12 `static/*.html` — added `<script src=".../avatar-menu-wiring.js">`

**Files created:**
- `static/js/components/avatar-menu-wiring.js` (138 lines) — single source of truth for avatar-menu mount + routing across both UX modes
- `docs/superpowers/specs/2026-05-01-markflow-theme-refactor-design.md` — design spec for the refactor
- `docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md` — full rollback artifact: every literal touched, every snap, every kept literal, every renamed var, every deleted block; ~140 rows
- `docs/superpowers/plans/2026-05-01-markflow-theme-refactor.md` — 14-task implementation plan with per-task model/effort routing

**Loose ends tracked forward:**
- `static/css/components.css` (new-UX) has the same `--mf-font-sans` and hardcoded `0.86rem`-style font-sizes that markflow.css had pre-refactor. Font picker and text-scale work on legacy pages now but only partially on new-UX pages. Separate refactor; smaller scope since components.css is more disciplined.
- Palette tweaks deferred per user intent ("I'll have to sit down and tweak it a little more at a later date"). Token VALUES in `design-themes.css` are easy to revise without touching markflow.css.

---

## v0.37.0 — Display Preferences & Theme System (2026-04-30)

**Goal:** Ship a full per-user display customization layer on top of the v0.36.0 UX overhaul. Users get 28 color themes, 14 font choices, and 4 text-scale steps, all accessible from a drawer in the avatar menu. Operators get a new Settings -> Appearance page to control system defaults and the per-user override gate.

**Why this matters:** The v0.36.0 UX overhaul introduced a new design language (Nebula palette, Inter font, card grid), but all users were locked into the same visual experience. Different operators have different accessibility needs, brand preferences, and screen environments. Delivering theme/font/scale controls as a first-class feature (not a future consideration) also allowed the three-tier UX toggle to replace the blunt `ENABLE_NEW_UX` env-only mechanism -- users can now switch interface mode themselves without waiting for an operator to flip a flag.

**What changed:**

1. **user_prefs SCHEMA_VER 1->2** -- `core/user_prefs.py` bumps `SCHEMA_VER` to 2. Four new preference keys added to `mf_user_prefs`: `theme` (default: `"nebula"`), `font` (default: `"system-ui"`), `text_scale` (default: `"1"`), `use_new_ux` (default: `None`, meaning defer to system/env). Schema migration is additive and runs at startup via `_migrate_schema()`. Existing rows with `schema_ver=1` are upgraded in place.

2. **Three-tier UX toggle** -- `core/feature_flags.py` gains `is_new_ux_enabled_for(user_sub)`. Resolution order: (1) user's stored `use_new_ux` pref if set; (2) `ENABLE_NEW_UX` env var if set (env acts as deployment bypass, overrides user pref in forced-on/off scenarios); (3) system DB pref `enable_new_ux`; (4) False. The existing `is_new_ux_enabled()` (env-only, used during request-context-free startup) is unchanged.

3. **System preference keys** -- `core/db/preferences.py` gains three new system-level pref keys: `enable_new_ux` (boolean, default False), `allow_user_theme_override` (boolean, default True), `default_theme` (string, default `"nebula"`). These feed the Appearance settings page and the tier-3 fallback in the three-tier lookup.

4. **design-themes.css** -- NEW file `static/css/design-themes.css` contains all 28 theme blocks as `[data-theme="name"]` CSS attribute-selector rules, 13 Google Font `@import` blocks (14 choices; System UI is no import), and 4 `[data-text-scale]` blocks. `static/css/components.css` gains `@import "./design-themes.css"` at the top. Token overrides follow the same `var(--mf-*)` naming convention established in `design-tokens.css`.

5. **Zero-flash init script** -- All 35+ HTML pages gain a synchronous `<script>` block inside `<head>` (before any stylesheet link) that reads `localStorage` and writes `data-theme`, `data-font`, `data-text-scale`, and `data-ux` onto `<html>` before the browser paints. This prevents the flash-of-default-theme that would occur if attrs were applied after DOMContentLoaded. All pages also gain a `<link rel="preconnect">` for `fonts.googleapis.com` and the Google Fonts `<link>` for the selected font.

6. **preferences.js extension** -- `static/js/preferences.js` gains `syncAttrs()` (writes all four `data-*` attrs from the current prefs object), a `COUNTERPART` map (maps each Original-UX theme to its New-UX equivalent and vice versa), and UX-mode migration logic (when the user toggles `use_new_ux`, the current theme is migrated to the counterpart if one exists). Debounced server sync to `/api/user-prefs` unchanged.

7. **Display Preferences drawer** -- NEW file `static/js/components/display-prefs-drawer.js`. Mounts as a slide-in drawer from the right side of the screen. Contains: theme swatch grid (6 groups, 28 swatches), font picker (14 options each rendered in its own typeface), text-scale selector (4 buttons), and New UX toggle. All DOM via `createElement` + `textContent` (XSS-safe). Wired to the avatar menu "Display preferences" entry across all 11 new-UX boot files.

8. **Settings -> Appearance page** -- NEW files: `static/settings-appearance.html` (page shell), `static/js/pages/settings-appearance.js` (page module), `static/js/settings-appearance-boot.js` (boot script). Page is OPERATOR+ gated. Controls: "New interface (default)" toggle (writes `enable_new_ux` system pref), "Allow per-user display overrides" toggle (writes `allow_user_theme_override`). Card added to `settings-overview.js`. Route `/settings/appearance` mounted in `main.py`.

**Design decisions and rationale:**

- **Why Nebula as the default theme.** Nebula is the New UX palette -- deep purple accent, dark card surfaces, the visual identity introduced in v0.36.0. Making it the default for new installs means the first impression of MarkFlow is the intended design, not the legacy Classic Light theme. Existing users who have not set a preference will see Nebula on their next load; operators who want the old look can set `default_theme=classic-light` in Settings -> Appearance.

- **Why `data-*` attributes on `<html>` rather than a CSS class or a separate stylesheet swap.** The `data-*` approach is the current industry standard for CSS custom property theming: one selector per theme in a single file, no JavaScript-driven class toggling, no FOUC from stylesheet swaps, no specificity fights. It also composes cleanly -- `[data-theme="nebula"][data-text-scale="large"]` selects naturally without any JS coordination needed.

- **Why a COUNTERPART map for UX-mode migration.** The Original UX and New UX theme groups have different palettes that serve the same role in each design system. When a user switches UX mode, landing on the wrong palette is jarring -- e.g., switching from New UX (Nebula) to Original UX and seeing an entirely different color scheme. The COUNTERPART map (Nebula -> Classic Light, Aurora -> Sage, etc.) makes the transition feel intentional rather than accidental. Users can still pick any theme manually after the migration.

- **Why Google Fonts with `display=swap`.** The 13 non-system fonts are loaded from Google Fonts CDN with `&display=swap` so the page renders in the system font immediately and the chosen font swaps in when it loads. This means no layout shift on first load and no blocking network request. The `<link rel="preconnect" href="https://fonts.googleapis.com">` in every page head reduces DNS + TLS latency on first load.

- **Why SCHEMA_VER 2 rather than a new table.** The four new preference keys (theme, font, text_scale, use_new_ux) are per-user preferences of the same character as the existing layout/density/pinned-folders keys. Splitting them into a separate table would require a join on every preference read. Bumping the schema version and migrating existing rows in place is simpler and consistent with the pattern already established in `core/user_prefs.py`.

**New API routes:**
- `GET /settings/appearance` -- Appearance settings page (HTML, OPERATOR+).
- `GET /api/user-prefs` / `PATCH /api/user-prefs` -- unchanged endpoint, now handles 4 additional keys.

**Files shipped (major new):**
- `static/css/design-themes.css` (NEW)
- `static/js/components/display-prefs-drawer.js` (NEW)
- `static/js/pages/settings-appearance.js` (NEW)
- `static/js/settings-appearance-boot.js` (NEW)
- `static/settings-appearance.html` (NEW)
- Modified: `core/user_prefs.py` (SCHEMA_VER bump + 4 new keys), `core/feature_flags.py` (three-tier lookup), `core/db/preferences.py` (3 new system pref keys), `static/css/design-tokens.css` (3 new token variables), `static/css/components.css` (@import + drawer styles), `static/js/preferences.js` (syncAttrs + COUNTERPART map), all 35+ HTML pages (init script + Google Fonts), all 11 new-UX boot files (drawer wiring), `static/js/pages/settings-overview.js` (Appearance card), `main.py` (/settings/appearance route).

**Dependencies:** No new Python packages. One new Google Fonts CDN dependency (client-side only, graceful fallback to system-ui).

**Backend pipeline:** No changes. Conversion, bulk worker, scheduler, scan coordinator, auth, and lifecycle subsystems are identical to v0.36.0.

**Order:** Shipped after v0.36.0 (UX Overhaul Plans 1A-8).

---

## v0.36.0 — UX Overhaul (Plans 1A–8) (2026-04-30)

**Goal:** Ship the full UX overhaul behind a `ENABLE_NEW_UX` feature flag. All eight plans (foundation, home page, stateful chrome, document cards, IA shift, settings redesign, cost dashboard, onboarding) are implemented and gated. Existing UI is completely unchanged for any deployment where the flag is off.

**Why this matters:** The pre-overhaul UI accumulated friction across every major workflow — no search-first entry point, no per-user layout preferences, settings buried in a single sprawling page, no visibility into AI spend, no first-run guidance. The overhaul addresses all of these in one coordinated release, delivered as a flag-gated surface so operators can validate before rolling out.

**What changed:**

1. **Design system (Plans 1A + 1B)** — `static/css/design-tokens.css` introduces CSS custom properties for every color, spacing step, and type scale used by the new UI. `static/css/components.css` adds shared component classes (cards, chips, avatars, density modifiers). Purple accent `#5b3df5` is the primary brand color throughout. No existing stylesheets were modified.

2. **New home page — search-as-home (Plan 2)** — `static/index-new.html` replaces the Convert page as the default landing view. Three layout modes are available: **Maximal** (large card grid + prominent search bar), **Recent Activity** (search + file-type chip row + recent-document cards), and **Minimal** (large centered search bar only, everything else hidden). `Cmd+\` (or `Ctrl+\` on Windows/Linux) cycles between modes. The active mode is persisted in per-user preferences and survives page reload and container restart.

3. **Stateful chrome (Plan 3)** — top navigation bar gains an avatar menu (role-gated entry point to Settings), a version chip showing the current release, and a layout-icon popover for switching between the three home-page modes. The avatar menu is suppressed for unauthenticated or viewer-role sessions.

4. **Document cards (Plan 4)** — document tiles across all list views gain a gradient top band color-coded by file type (Office files, audio, image, PDF, etc.) and a paper-snippet body showing a text excerpt. Three density modes are available: **Cards** (default, full gradient tile), **Compact** (condensed row with small icon), and **List** (flat table row). Density is stored per user.

5. **Activity dashboard (Plan 5, IA shift)** — new page at `/activity`. Shows live scan/convert status, the delta between files scanned vs files indexed (surfacing the "scanned but not yet searchable" gap operators previously had no visibility into), and auto-conversion health over the trailing 7 days. Replaces the old Pipeline status tab for operators. Requires OPERATOR role or above.

6. **Settings redesign (Plan 6)** — `/settings` now renders an overview card grid; each section has its own full-page route: `/settings/storage`, `/settings/pipeline`, `/settings/ai-providers`, `/settings/auth`, `/settings/notifications`, `/settings/db-health`, `/settings/log-management`. The old single-page settings accordion is preserved for non-new-UX deployments.

7. **Cost dashboard (Plan 7)** — `/settings/ai-providers/cost` is a new deep-dive page under AI Providers. Surfaces spend tiles (MTD and rolling-30d totals per provider), a daily spend bar chart, CSV rate import for custom per-token pricing, and configurable alert thresholds (soft warning / hard cap). Powered by the new `/api/telemetry` UI-event sink.

8. **First-run onboarding (Plan 8)** — 3-step full-screen overlay presented on the first visit to the home page: Welcome → Layout picker (choose Maximal / Recent / Minimal) → Pin folders (select up to 6 source folders as quick-access cards). Completion state persists in `mf_user_prefs` so the overlay does not reappear after the first run. Can be re-triggered from Settings → Account.

9. **Per-user preferences** — `core/user_prefs.py` (NEW) + `mf_user_prefs` DB table (schema in `_SCHEMA_SQL`, no migrations subdir). Stores: layout mode, density setting, pinned folders (up to 6), and onboarding completion flag. Exposed via `/api/user-prefs` (GET + PATCH). Scoped per authenticated user; anonymous sessions get a session-local fallback.

**Design decisions and rationale:**

- **Why search became the home page.** The primary daily action in MarkFlow is finding and working with documents that have already been converted. The Convert page was built first (it was the only page that existed in Phase 1), but by the time bulk conversion was stable, most sessions started with a search — not an upload. Making search the landing screen reflects that reality. The Convert page is still reachable from the top nav; it just isn't the default destination anymore.

- **Why the feature flag (`ENABLE_NEW_UX`).** The new UI is a significant visual change. Operators running production deployments need to be able to validate before rolling out, and to roll back without a code change. The flag keeps the old UI fully intact for any deployment where it's unset. All new routes and static files are served regardless (so operators can preview at the new URLs), but the application shell only activates the new home page and chrome when the flag is `true`.

- **Why three layout modes (Maximal / Recent / Minimal).** There is no single right layout for everyone. Power users with large monitors doing continuous conversion work want to see everything (Maximal). Operators checking in quickly want a clean, minimal surface that gets out of the way. The Recent mode exists for the in-between case: "I want context about what's happened but I still need search prominent." Making the mode user-switchable rather than admin-controlled avoids a false choice. `Ctrl+\` / `Cmd+\` was chosen as the shortcut because it follows the "toggle sidebar" convention from VS Code / Obsidian, which most operators already know.

- **Why per-user preferences are separate from system preferences.** `core/db/preferences.py` stores admin-controlled settings that apply to the entire deployment (pipeline enablement, folder paths, retention periods). Layout mode, card density, and pinned folders are personal — two operators on the same deployment will have different screen sizes, workflows, and habits. Mixing them into the same table would give operators no ability to share a deployment without clobbering each other's working style. The new `mf_user_prefs` table is scoped to a user identity (`sub` claim from UnionCore), not to the server.

- **Why preferences are stored server-side instead of just localStorage.** If a user logs in from a different browser, or the container is recreated, localStorage is gone. Server-side storage means a user's layout choice survives a container restart, a browser change, or switching from the desktop to a laptop. localStorage is still used as a read-fast cache (500ms debounced sync prevents write-per-keystroke churn); the server is the source of truth.

- **Why design tokens (CSS custom properties) for every color and spacing value.** Before the overhaul, colors were hardcoded hex in a dozen CSS files. A future brand update or a dark-mode pass would require a grep through the entire static tree. `static/css/design-tokens.css` is now the single file that owns every color (`--mf-accent`, `--mf-bg-page`, `--mf-card-gradient-audio`, etc.). All component CSS references `var(--mf-*)` only — no hardcoded hex elsewhere in the new code. The constraint was enforced during plan review; the components CSS was written against the tokens file from the start.

- **Why zero `innerHTML`.** The entire JS component library (onboarding overlay, document cards, top nav, search bar, settings pages) was built with `createElement` / `textContent` / `appendChild` only — never `innerHTML` with a template literal. `innerHTML` with user-controlled or backend-supplied data is the reliable path to stored XSS. This constraint was set as a non-negotiable design rule in the spec (§ Safe DOM) and enforced in every code review during the plan execution cycle.

- **Why "Activity" instead of "Pipeline".** "Pipeline" is an engineering metaphor for the internal processing chain. The audience for that page is operators, not engineers — they understand "what's happening" more intuitively than "what the pipeline is doing". Operators were already using "activity" in conversation when asking about scan/convert status. The rename also let us reserve "Pipeline" as a technical concept in help docs without the UI conflating the two.

- **Why the cost dashboard was included in this release rather than deferred.** AI provider spend became visible for the first time in v0.32.x (AI Assist provider chain). From v0.32.x to v0.36.0, operators have been accumulating API spend with no visibility — no per-provider totals, no daily trend, no alerting thresholds. Given that the Settings redesign already created a natural home for a cost deep-dive page (`/settings/ai-providers/cost`), deferring it further would have left a real operational gap open for multiple more releases.

- **Why the onboarding overlay is exactly 3 steps.** Every step in an onboarding flow that isn't strictly necessary to make the first session useful increases abandonment. The choices were: (1) Welcome — establishes what changed and what the user is about to choose; (2) Layout picker — the highest-impact first decision, because the wrong layout makes the new home page feel broken; (3) Pin folders — makes the Recent layout's quick-access cards work on the first visit. Everything else (density, provider setup, notifications) can be changed from Settings at any time. The overlay can be re-triggered from Settings → Account for users who want to revisit their initial choices.

**New API routes:**
- `GET /api/me` — authenticated identity (username, display name, role). Used by the avatar menu.
- `GET /api/activity/summary` — operator-gated dashboard data (scan counts, index delta, auto-conversion health).
- `GET /api/user-prefs` / `PATCH /api/user-prefs` — per-user layout, density, pinned folders, onboarding state.
- `POST /api/telemetry` — UI event sink (click, layout-switch, search-submit events). Writes to a ring-buffered SQLite table; consumed by the cost dashboard aggregation query.

**Files shipped (major new):**
- `static/css/design-tokens.css` (NEW)
- `static/css/components.css` (NEW)
- `static/index-new.html` (NEW)
- `static/js/layout-switcher.js` (NEW)
- `static/js/doc-cards.js` (NEW)
- `static/js/onboarding.js` (NEW)
- `core/user_prefs.py` (NEW)
- `api/routes/me.py` (NEW)
- `api/routes/activity.py` (NEW)
- `api/routes/telemetry.py` (NEW)
- ~15 modified: `main.py` (route mounts, flag guard), `static/css/app.css` (token imports), existing page HTML files (cache-bust, nav chrome injection)

**Dependencies:** No new Python packages. No changes to `requirements.txt` or `Dockerfile.base`.

**Feature flag:** `ENABLE_NEW_UX` environment variable. Default is `off` (empty / unset). Set to `true` in `.env` or `docker-compose.yml` to activate the new surfaces. All new routes and static files are served regardless (so operators can preview), but the application shell only switches to the new home page and chrome when the flag is on.

**Backend pipeline:** No changes. Conversion, bulk worker, scheduler, scan coordinator, auth, and lifecycle subsystems are identical to v0.35.0.

**Order:** Shipped after v0.35.0 (Active Operations Registry).

---

## v0.35.0 — Active Operations Registry (2026-04-28)

**Goal:** Single source of truth for every long-running file-related op in MarkFlow. Workers register at start, update on tick, finish at end. One unified frontend surface (sticky banner, inline per-page widget, Status hub) consumes one polling endpoint. Replaces the v0.32.6 ad-hoc trash status dicts with a generic registry that 10 op_types route through.

**Why this matters:** Operators triggered Force Transcribe (and most other long-running actions) and got a toast — then nothing. No progress, no cancel, no idea whether the action was still running. The Status page showed bulk jobs and pipeline scan but nothing else. v0.35.0 closes the gap with a unified hub.

**What changed:**

1. **`core/active_ops.py` (NEW)** — registry: register / update / finish / cancel / list / get, in-memory dict + DB write-through, hydrate on startup, daily auto-purge. ~300 LOC.

2. **Migration v29** — `active_operations` table (idempotent CREATE).

3. **`api/routes/active_ops.py` (NEW)** — `GET /api/active-ops` (OPERATOR+), `POST /api/active-ops/{op_id}/cancel` (MANAGER+).

4. **10 op_type retrofits** — `pipeline.run_now`, `pipeline.convert_selected`, `pipeline.scan`, `trash.empty`, `trash.restore_all`, `search.rebuild_index`, `analysis.rebuild`, `db.backup`, `db.restore`, `bulk.job` (thin mirror).

5. **5 cancel hooks** registered in scan_coordinator, pipeline routes (×2), lifecycle_scanner, trash routes, analysis routes, bulk_worker — bridging registry cancel to each subsystem's native primitive.

6. **3 new frontend modules** — `active-ops-poller.js` (shared poller), `active-op-widget.js` (inline widget), `active-ops-hub.js` (Status index). Consume `/api/active-ops` with `ActiveOpsPoller.subscribe()`.

7. **`live-banner.js` retrofitted** — drops endpoint list; subscribes to poller; hardcoded RGBA colors migrated to CSS variables (P8).

8. **6 origin pages mounted** — history, trash, bulk, settings, batch-management mount the inline widget; status mounts the hub.

9. **Cache-bust convention pass** — every JS script-tag query string bumped to `?v=0.35.0` across all `static/*.html`.

10. **Codebase-wide patterns formalized (spec §17 P1–P10)** — gotchas.md and CLAUDE.md gain canonical references for: no-op on terminal state, asyncio.Lock for shared dicts, source-of-truth + drift rule, lifespan event gates, cancel-hook bridge, predicate-gated cleanup, scheduler time-slot allocation table, frontend CSS-vars-only, deprecation signals, DB writes through queue.

11. **5 new planned BUG rows** queued for v0.36.x: deprecated endpoint removal (BUG-019), BulkJob/scanner P1 hardening (BUG-020), drift detection (BUG-021), scheduler collision self-check (BUG-022), deprecation surface audit (BUG-023).

12. **Audit cleanup ride-alongs** — orphaned `static/js/deletion-banner.js` deleted; stale `log_archiver` comments updated; `docs/scheduler-time-slots.md` (NEW) documents all 20 scheduler jobs.

**Files:** ~9 new + ~20 modified + 1 deleted. ~1,400 LOC new, ~500 LOC modified. Migration v29 idempotent. No new dependencies.

**Order:** Shipped after v0.34.9 (BUG-018 abort persistence fix).

**Operator-visible:**
- Click Force Transcribe → progress widget appears above Pending Files; same widget visible on Status hub.
- Click any operation card on Status → jump to its origin page; the operation pulses amber on arrival.
- Cancel button on every cancellable op (DB backup/restore are intentionally uncancellable).
- After container restart: ops in flight show as red "terminated by restart" on Status hub for 30 s, then auto-hide.
- Old `/api/trash/empty/status` and `/api/trash/restore-all/status` endpoints kept as deprecated facades (returning registry-derived data with `Deprecation: true` + `Sunset` headers); removal in v0.36.x per BUG-019.

**Spec:** [`docs/superpowers/specs/2026-04-28-active-operations-registry-design.md`](superpowers/specs/2026-04-28-active-operations-registry-design.md). 1,332 lines, 21 sections.

**Plan:** [`docs/superpowers/plans/2026-04-28-active-operations-registry.md`](superpowers/plans/2026-04-28-active-operations-registry.md). 46 tasks across 5 phases.

---

## v0.34.9 — Bulk-worker abort persists immediately even with stuck workers (BUG-018) (2026-04-30)

**Closes the "abort safeguard didn't fire" mystery from the v0.34.7
verification run. The safeguard was firing — the DB persistence
just happened to be gated on `asyncio.gather()` returning, which a
single stuck worker can prevent indefinitely. Move the persistence
to the abort site itself, with a one-shot guard so re-observers
don't double-write or double-log.**

### BUG-018 — abort decision invisible to DB while any worker is stuck

**Symptom (operator-facing).** In the v0.34.7 verification run that
exposed BUG-016, `bulk_jobs.cancellation_reason` stayed `None`
despite the bulk-worker hitting `error_rate=1.0` with 31 consecutive
Whisper-lock failures. Operators reading the UI saw a job in
`status='running'` with `failed=31` and no abort signal — the
opposite of what the safeguard exists to communicate.

**Diagnosis.** Reading `core/bulk_worker.py` end to end:

1. The abort check at line 713 runs at the top of each `_worker()`
   iteration. `should_abort()` returns True correctly when
   `consecutive_errors >= 20` (verified against
   `core/storage_probe.py:ErrorRateMonitor`).
2. When abort fires, the existing code does:
   ```python
   self._cancel_reason = "Aborted: error rate ..."
   self._cancel_event.set()
   self._pause_event.set()
   continue  # drain queue
   ```
3. `_cancel_reason` lives ONLY on the worker instance (in-memory).
   The DB persistence happens later, in the post-gather code at
   line 580-591:
   ```python
   await asyncio.gather(*workers)
   ...
   if self._cancel_event.is_set():
       cancel_reason = getattr(self, '_cancel_reason', ...)
   ...
   await update_bulk_job_status(self.job_id, final_status, **extra_fields)
   ```
4. `asyncio.gather(*workers)` blocks until **all** workers exit. In
   the v0.34.7 run, one worker was inside a multi-minute Whisper
   transcription on slow CPU (the lock-holder from BUG-016, before
   it was fixed) and never reached the top of the loop again.
   The other 7 workers reached the top, observed
   `_cancel_event.is_set()`, and drained the queue — but they
   couldn't exit either, because `_queue.get()` blocks until a
   `None` terminator is enqueued (and the terminator wasn't being
   pushed during abort).

So the abort fired correctly in memory, all observable side effects
of the abort happened in memory, but the DB never reflected any of
it because the worker pool was stranded.

**Fix.** Persist the abort to the DB at the abort site itself, not
just in memory. Use a one-shot `_abort_persisted` flag so the
per-worker re-observation (every worker that hits the top of the
loop after `_cancel_event.set()` would otherwise re-fire the log,
re-emit the event, and re-write the DB) collapses to a single
action per job:

```python
if self._error_monitor.should_abort():
    if not getattr(self, "_abort_persisted", False):
        self._abort_persisted = True
        self._cancel_reason = (...)
        self._cancel_event.set()
        self._pause_event.set()
        log.error("bulk_worker_error_rate_abort", ...)
        _emit_bulk_event(self.job_id, "job_error_rate_abort", ...)
        try:
            await update_bulk_job_status(
                self.job_id,
                "cancelled",
                cancellation_reason=self._cancel_reason,
            )
        except Exception as exc:
            log.warning("bulk_worker_abort_persist_failed", ...)
    continue
```

The flag is set BEFORE the await, so re-observations on subsequent
worker iterations short-circuit cleanly (asyncio's single-threaded
loop guarantees no race within one event loop). The post-gather
write at line 591 is now an idempotent overwrite that adds
`completed_at` if and when gather eventually returns; if gather
never returns (truly stuck worker), the v0.34.4 startup reaper
will mark the job on next container restart, but at least the
operator-visible state already reflects the abort.

**Bonus fix folded in: log/event spam.** Pre-v0.34.9, every worker
that reached the top of the loop after `_cancel_event.set()` would
re-fire `bulk_worker_error_rate_abort` (log + SSE event), producing
thousands of duplicate lines per aborted job. The same one-shot
guard collapses this to exactly one fire per job, which is what
the operator and downstream tooling expect.

**Why not just remove the post-gather write.** Two reasons. (1) On
a normal abort where workers DO exit cleanly, the post-gather write
adds `completed_at` and refreshes counters — useful state. (2)
Defensive symmetry: keep the in-memory + DB writes both intact so
neither path is the single source of truth. The DB write at abort
time means operators see the cancellation immediately; the
post-gather write means the row is fully closed out when workers
finish draining.

**Lesson — DB persistence should track in-memory state changes
within bounded latency, not gate them on a separate event chain.**
Anywhere the in-memory state of a long-lived async task can diverge
from its persisted representation, that divergence is operator-
visible (or invisible) latency that compounds when something
upstream goes wrong. For state transitions that matter to
operators (status flips, cancellations, abort decisions),
persist at the decision site, not at the closeout site.

**Audit hint.** Other `_cancel_event.set()` sites in
`core/bulk_worker.py` (lines 905, 1301-1302, 1507, 1526) likely
have similar dependence on the post-gather write to persist
cancellation. Out of scope for this release but worth a similar
audit if any of those paths surfaces a bug like this one.

### Files touched

- `core/version.py` — `0.34.8` → `0.34.9`.
- `core/bulk_worker.py` — abort site at line 713 now persists
  immediately + one-shot guard against re-fires.
- `docs/bug-log.md` — BUG-018 moved from Active to Shipped.
  Header bug-range citation updated.
- `docs/version-history.md` — this entry.
- `docs/help/whats-new.md` — operator note.
- `CLAUDE.md` — Current Version block bumped to v0.34.9.

---

## v0.34.8 — Whisper asyncio-lock per-loop + macOS resource-fork skip (BUG-016, BUG-017) (2026-04-30)

**Empirical follow-up to v0.34.7. The first run-now after v0.34.7
triggered a fresh bulk_job that produced 0 successful conversions in
~5 min of convert phase, with 31 consecutive failures and a frozen
heartbeat. Diagnosis traced to a module-level `asyncio.Lock()` that
binds to a single event loop while the media handlers create a fresh
loop per file (BUG-016). A side issue produced a constant trickle of
"corrupt PDF" errors against macOS resource-fork sidecars (BUG-017).
Both fixed here.**

### BUG-016 — Whisper `asyncio.Lock` is bound to a different event loop

**Symptom (operator-facing).** After v0.34.7 deploy, the next run-now
created bulk_job `6c6f3c11`. Scan completed normally; convert phase
started and immediately produced a burst of 31 failures in ~30s,
all with the same error message:

```
local Whisper failed or is unavailable, and no cloud provider that
supports audio is configured
```

The bulk_jobs.last_heartbeat froze at 03:25:38 — the moment the
30th-or-so failure was recorded — and stayed frozen for the rest of
the watch window. `bulk_jobs.converted=0`. The job did not abort
(see BUG-018 for that secondary mystery).

**Diagnosis.** The persisted `markflow.log` showed every media file's
Whisper call returning the same RuntimeError:

```
'<asyncio.locks.Lock object at 0x742da8fdeb40 [locked, waiters:1]>
 is bound to a different event loop'
```

Architectural read of `core/whisper_transcriber.py` revealed:

1. Line 43: `_asyncio_lock = asyncio.Lock()` — created at
   module-import time.
2. Line 162: `async with _asyncio_lock:` inside `transcribe()`.
3. `formats/media_handler.py:208,211` and
   `formats/audio_handler.py:148,151` call
   `asyncio.run(_convert())` inside a thread pool — so every media
   file conversion spawns a fresh thread with a fresh event loop.

Python's `asyncio.Lock` constructor records no loop affinity at
creation time, but the FIRST acquire binds the lock to the calling
loop. Every subsequent acquire from a different loop raises the
"is bound to a different event loop" RuntimeError. Result: the
first media file in the bulk job acquired and (eventually) released
the lock, but its loop was now CLOSED. Every subsequent media file
got a brand-new loop from `asyncio.run`, tried to acquire the same
module-level lock, and failed instantly. Eight workers each hit the
issue on their first media file in parallel — hence the 8-or-so
quick failures, then a slow drift up to 31 as more media files
came down the queue.

The frozen heartbeat at 03:25:38 was the lock-holding worker still
running its CPU transcription on the first file (~5–10 min on a
540-second audio at "base" model on CPU); the other workers had
all finished failing.

**Fix.** Replace the module-level lock with a per-loop lookup:

```python
_asyncio_lock_dict_guard = threading.Lock()
_asyncio_locks_by_loop_id: dict[int, asyncio.Lock] = {}

def _get_asyncio_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = id(loop)
    with _asyncio_lock_dict_guard:
        lock = _asyncio_locks_by_loop_id.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _asyncio_locks_by_loop_id[key] = lock
        return lock
```

Then in `transcribe()`:

```python
async with _get_asyncio_lock():
    ...
```

Each per-file event loop now gets its own asyncio.Lock instance.
Cross-loop GPU/CPU serialization is still provided by the unchanged
`_thread_lock` (`threading.Lock`), so the original "at most one
Whisper inference at a time" guarantee is preserved. The dict
accumulates one tiny entry per closed loop; for an 8-worker pool
processing many media files this is bounded by max-concurrent
transcriptions and isn't a concern.

**Why duck-typed dict instead of weakref.** `asyncio.Lock` instances
aren't weak-referenceable (slot-based), and event-loop closure
isn't a directly-detectable signal we could hook for cleanup. The
dict-of-`id(loop)` approach is the cheapest correct solution; the
alternative (recreating the lock every call) defeats the lock's
purpose for in-loop coroutine serialization.

**Lesson — module-level asyncio primitives are a trap.** Any
`asyncio.Lock`, `asyncio.Event`, `asyncio.Condition`,
`asyncio.Queue`, etc., constructed at import time will silently
bind to whichever event loop first uses it. Mixed-loop code paths
(e.g. `asyncio.run` inside a thread pool, common when bridging sync
→ async) will then fail with "bound to a different event loop". The
safe pattern is to construct the primitive inside the running
coroutine, OR to look it up per-loop the way this fix does. Worth
auditing the rest of the codebase for similar patterns.

### BUG-017 — macOS resource-fork sidecars treated as their parent format

**Symptom.** `bulk_files.error_msg` accumulated rows like:

```
Cannot open PDF: No /Root object! - Is this really a PDF?
   source: .../municipal archives/._7123.pdf
```

**Diagnosis.** macOS writes a sidecar file named `._<original>`
whenever a file is copied to a non-HFS+ volume — including SMB/CIFS
mounts (the K-drive source share). The bytes are AppleDouble-framed
metadata, NOT the format their extension claims. `._7123.pdf` is
not a PDF; running `pikepdf` against it raises "No /Root object".
The bulk scanner's `is_junk_filename` predicate already filtered
the directory variant `.appledouble` and `_JUNK_BASENAMES_LOWER`,
but missed the per-file sibling.

**Fix.** Add `"._"` to `_JUNK_BASENAME_PREFIXES_LOWER` in
`core/bulk_scanner.py`. Files with that prefix never reach a
handler.

### BUG-018 noted as open

`bulk_worker.error_rate_abort` did not fire on the v0.34.7 stuck run
despite 31 consecutive failures. The check is at
`core/bulk_worker.py:713` and the underlying logic in
`core/storage_probe.py:ErrorRateMonitor.should_abort` triggers on
`consecutive_errors >= 20`. The cancellation_reason stayed `None`
on `bulk_job 6c6f3c11`. Two leading hypotheses:

1. The `_cancel_reason` set in the worker instance lost the race
   to a heartbeat-freeze — the DB write that would have propagated
   it to `bulk_jobs.cancellation_reason` never executed.
2. `_error_monitor.record_error` was called for the lock-bound-loop
   exception path, but a different exception path (e.g. via
   `db_lock_requeue`) reset `_consecutive_errors` so the threshold
   never crossed the 20 mark.

Logged in `bug-log.md` as open. Not blocking now that BUG-016 is
fixed — errors will be a small minority of attempts and the
safeguard won't need to fire. Revisit when the next "everything is
failing" scenario surfaces (or proactively if the lesson above
turns up other module-level asyncio primitives).

### Files touched

- `core/version.py` — `0.34.7` → `0.34.8`.
- `core/whisper_transcriber.py` — module-level `_asyncio_lock`
  replaced with per-loop dict + `_get_asyncio_lock()` getter; one
  call site updated.
- `core/bulk_scanner.py:_JUNK_BASENAME_PREFIXES_LOWER` — added
  `"._"` macOS resource-fork prefix.
- `docs/bug-log.md` — BUG-016 + BUG-017 in Shipped, BUG-018 in
  Active. Header bug-range citation updated.
- `docs/version-history.md` — this entry.
- `docs/help/whats-new.md` — operator note.
- `CLAUDE.md` — Current Version block bumped to v0.34.8.

---

## v0.34.7 — Auto-conversion unwedged: write guard fallback + Excel chartsheet skip (BUG-014, BUG-015) (2026-04-30)

**Two conversion-blocking bugs found during a post-v0.34.6 log audit.
Symptom: every auto-conversion cycle since at least 2026-04-29 16:33
hit `error_rate=1.0` and aborted at the 20-error threshold within the
first 20 file attempts. The scheduling layer (v0.34.3 + v0.34.4) was
healthy; the actual conversions were not. After this release the
indexed counter should start climbing for the first time in days.**

### BUG-014 — `is_write_allowed()` denies every path when Storage Manager pref is unset

**Symptom (operator-facing).** `bulk_files.error_msg` accumulating
rows like `write denied — outside output dir: /mnt/output-repo/Reports`
on paths clearly inside the configured `BULK_OUTPUT_PATH=/mnt/output-repo`.
Every file convert in the bulk pipeline rejected at the v0.25.0 write
guard, despite the converter resolving correct output paths.

**Diagnosis.** Live introspection of the running container:

```python
from core.storage_manager import _cached_output_path, is_write_allowed
print(_cached_output_path)               # → None
print(is_write_allowed('/mnt/output-repo/Reports'))   # → False
print(is_write_allowed('/mnt/output-repo'))           # → False
print(is_write_allowed('/mnt/output-repo/foo'))       # → False
```

Meanwhile `core.storage_paths.get_output_root()` correctly returned
`/mnt/output-repo`. The two write-guard cache systems were not
synchronised: `get_output_root()` (v0.34.1) reads through the
priority chain `Storage Manager > BULK_OUTPUT_PATH > OUTPUT_DIR`,
falling back to env vars when the DB pref is unset.
`is_write_allowed()` (v0.25.0) consulted only the
`storage_manager._cached_output_path` sentinel populated from the
`storage_output_path` DB preference. On this VM that preference had
never been set (operator never visited the Storage page) — the cache
stayed `None` and the early-return at `core/storage_manager.py:150`
fired for every call.

**Fix.** Route `is_write_allowed()` through
`core.storage_paths.resolve_output_root_or_raise()`, which uses the
same priority chain as the runtime path resolver and refuses to
silently fall back to the legacy `output/` default:

```python
def is_write_allowed(target_path: str) -> bool:
    if not target_path:
        return False
    try:
        from core.storage_paths import resolve_output_root_or_raise
        base_path = resolve_output_root_or_raise(label="is_write_allowed")
    except RuntimeError:
        return False
    try:
        target_real = os.path.realpath(target_path)
    except OSError:
        return False
    base = str(base_path).rstrip(os.sep)
    return target_real == base or target_real.startswith(base + os.sep)
```

The v0.25.0 "absent configuration → deny everything" intent is
preserved (the resolver raises when no source is configured, and the
guard treats that as deny rather than as "allow `/app/output`").

**Test fragility caught and fixed.**
`tests/test_storage_manager.py:test_write_denied_when_no_output_configured`
asserted "no Storage Manager pref → guard denies everything". After
the fix, that's only true if `BULK_OUTPUT_PATH` and `OUTPUT_DIR` are
also clear — environments where a dev shell exports either would have
silently passed for the wrong reason. Added explicit
`monkeypatch.delenv` calls so the test exercises the absent-config
branch deterministically.

**Why this stayed hidden.** The Storage Manager / cached-pref design
predates the v0.34.1 single-source-of-truth resolver. v0.34.1 unified
six other consumers behind `get_output_root()` but didn't migrate the
write guard, because the guard's failure mode (silent denial) didn't
look like a path-resolution bug — it looked like a write-permission
bug. The error message `write denied — outside output dir:
<path-that-is-clearly-inside-output-dir>` was the giveaway, but it
took a log audit to surface.

**Lesson.** When a "single source of truth" refactor consolidates N
callers, security-critical guards are NOT optional members of N. A
guard whose source of truth differs from the runtime resolver is a
bug in the making — they will diverge under any operational scenario
that affects one cache and not the other (DB reset, fresh deploy,
env var change without DB update). Audit gating writes that they
share the resolver, the same way path-resolution callers were
audited in v0.34.1.

### BUG-015 — Excel handler crashes on Chartsheets

**Symptom.** `'Chartsheet' object has no attribute 'merged_cells'` in
`bulk_files.error_msg` for 11 distinct `.xlsx` files. Conversions
fail outright; no Markdown produced.

**Diagnosis.** `openpyxl.load_workbook()` returns `Chartsheet`
instances for sheets that contain only an embedded chart (no cell
grid). They expose `.title` but not the `Worksheet` interface —
specifically, no `.merged_cells`, `.iter_rows`, `.max_row`,
`.max_column`. `formats/xlsx_handler.py` iterated `wb.sheetnames`
and called `_build_merged_cells_map(ws)` (which accesses
`ws.merged_cells.ranges`) without distinguishing sheet types. The
AttributeError propagated out of the handler.

**Fix.** Duck-typed guard at the top of both sheet loops (the
`ingest()` main loop and the `_extract_styles_impl()` styles loop):

```python
if not hasattr(ws_data, "merged_cells"):
    log.info(
        "xlsx_chartsheet_skipped",
        filename=file_path.name,
        sheet=sheet_name,
        sheet_type=type(ws_data).__name__,
    )
    continue
```

Chartsheets carry no Markdown-extractable content; silently skipping
them is the correct semantic. The log event surfaces the omission so
operators can audit what was skipped if a `.xlsx` produces less
output than expected.

**Why duck-typing instead of `isinstance(ws, Chartsheet)`.** openpyxl
has shuffled `Chartsheet` between `openpyxl.workbook.workbook` and
`openpyxl.chartsheet` across recent versions; `hasattr` survives
those moves and any future sheet types we haven't anticipated.

### Net effect

Both fixes together remove the two systemic conversion failures that
dominated the auto-converter's first-20-attempts window. The 20-error
abort threshold was a real safeguard, not a bug — but it was tripping
on these two bugs every cycle, so it never had a chance to see a
successful conversion. With BUG-014 and BUG-015 fixed, the threshold
should now only fire on genuine sources of error (corrupt PDFs, etc.),
which exist in the long tail but should be a much smaller fraction of
attempts.

### Files touched

- `core/version.py` — `0.34.6` → `0.34.7`.
- `core/storage_manager.py:is_write_allowed` — route through
  `resolve_output_root_or_raise()`.
- `formats/xlsx_handler.py` — Chartsheet guard in `ingest()` main
  loop and `_extract_styles_impl()` styles loop.
- `tests/test_storage_manager.py:test_write_denied_when_no_output_configured`
  — env-var hygiene via `monkeypatch.delenv`.
- `docs/bug-log.md` — BUG-014 + BUG-015 in Shipped; header
  bug-range citation updated.
- `docs/version-history.md` — this entry.
- `docs/help/whats-new.md` — operator note.
- `CLAUDE.md` — Current Version block bumped to v0.34.7.

---

## v0.34.6 — Resources page Disk card double-count fix (BUG-013) + version-constant catch-up (2026-04-30)

**Two-part release. Code fix for a metric that quietly overstated
MarkFlow's disk footprint by up to 2× on the Resources page, plus
catch-up for a release-discipline gap that shipped v0.34.2 → v0.34.5
with `core/version.py` still reading `0.34.1`.**

### BUG-013 — Resources page Disk card double-counted the output share

**Symptom (operator-facing).** The Resources page **Disk** card
showed `2.05 TB` total MarkFlow disk usage on the production VM —
which happened to be the right number, but only because of a
masking accident (see "Why this stayed hidden" below). The bug was
latent and would have flipped the card to roughly `4 TB` the next
time the underlying walk completed cleanly, with nothing actually
having changed on disk.

**Root cause.** Post-v0.34.1, `core/storage_paths.get_output_root()`
returns one configured root for **both** bulk and single-file
conversion. Two of MarkFlow's disk-usage callers had not been
updated to reflect that consolidation:

1. `core/metrics_collector.py:_collect_disk_snapshot_impl` — walks
   the output repo three times: `repo_bytes` (excl `.trash`),
   `trash_bytes` (just `.trash`), and `conv_bytes` (the same root,
   no exclusion). Every walk runs every 6 hours and persists as a
   row in `disk_metrics`. The pre-fix sum was:

   ```python
   total_bytes = repo_bytes + trash_bytes + conv_bytes \
                 + db_bytes + logs_bytes + meili_bytes
   ```

   When the conv walk succeeded, `conv_bytes ≈ repo_bytes + trash_bytes`
   — so the entire output share was added to the total twice.
   `disk_metrics.total_bytes` is what `/api/resources/summary` returns
   as `disk.current_total_bytes`, which the Resources card renders
   directly as the headline number.

2. `api/routes/admin.py:_compute_disk_usage` — the admin breakdown
   endpoint `/api/admin/disk-usage` builds the same set of rows and
   then does `total_bytes = sum(item["bytes"] for item in breakdown)`.
   Same double-count, surfaced on the admin Disk Usage panel.

**Why this stayed hidden until 2026-04-30.** The latest snapshot in
the live `disk_metrics` table at investigation time had
`conversion_output_bytes = 0` — likely a CIFS walk failure on the
NAS that `_walk_dir` swallowed silently. With one of the two
duplicate components zero, the displayed total happened to land on
the genuine MarkFlow footprint (~2.1 TB). The bug was a sleeper —
the next successful conv-walk snapshot would have made the card
jump to ~4 TB.

**Fix.**

`core/metrics_collector.py:252` — drop `conv_bytes` from the sum:

```python
total_bytes = repo_bytes + trash_bytes + db_bytes + logs_bytes + meili_bytes
```

The `conversion_output_bytes` column is still populated (so the
admin breakdown UI can keep its "Conversion Output" workflow row
for operator clarity) but no longer contributes to the total.

`api/routes/admin.py:_compute_disk_usage` — tag the redundant
breakdown row with `redundant_in_total: True` and skip such rows
in the sum:

```python
total_bytes = sum(
    item["bytes"] for item in breakdown
    if not item.get("redundant_in_total")
)
```

**Why a flag instead of removing the row.** The "Conversion Output"
breakdown row is intentionally retained — pre-v0.34.1 it was a
distinct path (single-file conversion vs bulk output), and operators
mentally model the two workflows separately even now that the
resolver returns one root. The fix preserves that mental model
without re-inflating the total.

**Lesson.** When a refactor consolidates two paths into one
(`get_output_root()` did this in v0.34.1), every per-component sum
that previously partitioned by path-of-origin needs to be revisited.
A grep for the old call sites isn't enough — the bug is in the
*shape* of the sum, not in any individual call.

### Catch-up: `core/version.py` shipped stale through v0.34.2 → v0.34.5

The version constant was last bumped in v0.34.1 (`14fdaea`) and
missed in every subsequent release commit. `/api/version` and the
`gpu`-block sibling in `/api/health` therefore reported `0.34.1`
against v0.34.5 code on every running deployment. Caught while
deploying the latest pull on the Proxmox VM.

Bumped here to `0.34.6` and added a step 1 to CLAUDE.md's
"Documentation discipline (per release)" so the constant cannot
fall behind silently again.

### Files touched

- `core/version.py` — bump `0.34.5` → `0.34.6`.
- `core/metrics_collector.py:252` — drop `conv_bytes` from `total_bytes`.
- `api/routes/admin.py:_compute_disk_usage` — `redundant_in_total` flag + skip in sum; description text updated to note the post-v0.34.1 root consolidation.
- `docs/bug-log.md` — BUG-013 row in Shipped section; header bug-range citation updated.
- `docs/version-history.md` — this entry.
- `docs/help/whats-new.md` — operator note.
- `CLAUDE.md` — Current Version block bumped to v0.34.6.

---

## v0.34.5 — Verification milestone for v0.34.3 + v0.34.4 (2026-04-28)

**Docs-only bump. No code changes. Captures the live-log evidence that
the v0.34.3 (BUG-011) and v0.34.4 (BUG-012) fixes work end-to-end on
the production K-drive workload, plus the one-shot manual cleanup
performed during investigation.**

### Why a separate version

Both fixes shipped earlier the same day, and the verification happened
post-release. The verification evidence and the one-shot cleanup are
operationally important enough to record at a stable version tag —
future operators investigating similar wedge conditions will have a
clear "this is what success looks like" reference.

### Live-log proof of fix

After v0.34.4 deployed, run-now triggered a fresh auto-conversion
cycle. The pre-flight passed, a bulk_job entered `running`, and the
worker started enumerating files. The `bulk_disk_precheck` event
fired with the new `multiplier=0.5` (passes: 250 GB × 0.5 = 125 GB
needed vs 158 GB free):

```
23:34:53 scan_coordinator.run_now_paused reason=bulk_job_started:8a472712e35743918aff46d36b7a05df
23:34:57 scan_progress completed=608   files_per_second=360.7  job_id=8a472712...
23:34:59 scan_progress completed=808   files_per_second=192.3
23:35:02 scan_progress completed=1408  files_per_second=215.0
23:35:04 scan_progress completed=1608  files_per_second=172.3
23:35:07 scan_progress completed=2008  files_per_second=162.7
23:35:12 scan_progress completed=3208  files_per_second=186.3
23:35:33 scan_progress completed=5408  files_per_second=142.5
```

This is the first auto-triggered bulk_job to reach `running` status
since 2026-04-07 on the affected machine. No `bulk_disk_precheck_failed`
event in the watched window — the multiplier fix held.

### One-shot manual cleanup performed during investigation

Before v0.34.4 was written, 38 stale `auto_conversion_runs` rows had
accumulated since 2026-04-07. To unblock investigation (the v0.34.4
startup reaper hadn't yet been deployed), they were cleaned manually:

```sql
UPDATE auto_conversion_runs SET status='failed', completed_at=now()
WHERE status='running' AND completed_at IS NULL;
-- 38 rows updated
```

Plus zero stale `bulk_jobs` (the existing reaper had already cleaned
those at the v0.34.3 container restart). v0.34.4's reaper handles
this automatically going forward — no operator action needed for
future similar conditions.

### Loose ends captured for the upcoming UX overhaul

Three observability gaps surfaced during investigation. None block
operations now that v0.34.3 + v0.34.4 are deployed, but each would
have made the original investigation dramatically faster:

1. **No operator-facing alert when auto-conversion fails repeatedly.**
   The `bulk_jobs.error_msg` carries the disk-space rejection but it
   only surfaces if you query the DB. UX overhaul §13 (Notifications
   trigger rules) is where this lands.
2. **No "scanned vs indexed delta" surface.** The gap between the
   `source_files` count and the Meilisearch index count is the
   leading indicator that conversion is wedged. UX overhaul §5
   (Activity dashboard) is where this surfaces.
3. **Failure-path explicit `completed_at` writes.** The bulk_job
   pre-flight failure handler should write the parent
   `auto_conversion_runs.completed_at` directly rather than relying
   on the startup orphan reaper as a backstop. Future hardening pass.

### What didn't change

- No code in this release. CLAUDE.md, version-history.md (this entry),
  whats-new.md, bug-log.md, gotchas.md only.
- Test count unchanged from v0.34.4.
- No DB migration. No new endpoints. No env vars.

---

## v0.34.4 — Orphan reaper extended to `auto_conversion_runs` (2026-04-28)

**Companion fix to v0.34.3. Discovered while verifying the BUG-011 fix:
the auto-converter was refusing to start new runs because the startup
orphan-cleanup function handled `bulk_jobs` and `scan_runs` but missed
`auto_conversion_runs` entirely. 38 stale `status='running'` rows had
accumulated since 2026-04-07. Closes BUG-012.**

### How the bug compounded with BUG-011

The auto-converter's gate is correct on its own: "don't start a new
run if one is already active." But combined with the v0.23.6 M2
disk-space pre-check that always failed on shares larger than 1/3 of
free output space, it created a slow-motion deadlock:

1. Scheduled scan completes, finds files
2. Auto-converter creates `auto_conversion_runs` row, `status='running'`
3. Auto-converter creates `bulk_jobs` row to process the files
4. `_precheck_disk_space()` rejects with `× 3 buffer needed` error
5. `bulk_jobs.status='failed'` written, but `auto_conversion_runs.completed_at`
   stays NULL — there was no code path to close it on pre-flight failure
6. Next scheduled scan sees `auto_conversion_runs` row still `status='running'`,
   bails with "run already in progress"
7. Repeat steps 1-6 every 45 minutes for 3 weeks

By the time we investigated, 38 stale rows had accumulated. The v0.34.3
fix to the multiplier was correct, but **untestable in production**
until the orphan reaper was extended.

### What changed

- **`core/db/schema.py:cleanup_orphaned_jobs()`** — added a third UPDATE:
  ```sql
  UPDATE auto_conversion_runs SET status='failed', completed_at=?
  WHERE status='running' AND completed_at IS NULL
  ```
  Wrapped in a defensive table-existence check so partial-schema test
  fixtures (and older DBs) don't error out.
- **Log payload** — `startup.orphan_cleanup` event now includes
  `failed_auto_runs` count alongside `cancelled_jobs` and `interrupted_scans`.
- **`tests/test_bugfix_patch.py:TestOrphanCleanup`** — added two tests:
  one for the orphan-reaping path, one regression check that
  already-completed rows aren't touched. Both self-skip when the test DB
  lacks the table (some conftest fixtures only create a minimal schema).

No new endpoints. No DB migration. No API contract changes. No env vars.

### Operator-visible change

- After this release ships, **restart the container once**. The startup
  orphan reaper handles any accumulated stale `auto_conversion_runs`
  rows automatically. No manual SQL needed.
- Subsequent auto-conversion cycles start cleanly even if a prior run
  failed pre-flight or got killed mid-flight.
- Combined with v0.34.3's disk-space fix, the K-drive auto-conversion
  path is end-to-end functional.

### Lessons that generalize (added to gotchas.md)

1. **Any table with a `status` field + a `completed_at` field that
   gates downstream behavior MUST have a startup orphan reaper.** This
   includes `bulk_jobs`, `scan_runs`, `auto_conversion_runs`, and any
   future similar work-tracking table. Adding a new such table without
   extending `cleanup_orphaned_jobs()` is a class-of-bug-waiting-to-happen.
2. **"Run already in progress" gates compound silently.** When a gating
   check sees stale state, it doesn't fail loudly — it just skips the
   work. The compounded effect of "every cycle stalls" can persist for
   weeks before anyone notices, especially if the success path is also
   logged at `info` level.
3. **Failure paths must close their state.** When the bulk_job
   pre-flight failed in v0.23.6 onward, the code path that wrote
   `bulk_jobs.status='failed'` should have also written
   `auto_conversion_runs.completed_at` to close the parent run. The
   orphan reaper is a backstop, not an excuse to skip explicit failure
   handling.

---

## v0.34.3 — Auto-conversion unblocked: disk-space pre-check multiplier (2026-04-28)

**Closes BUG-011 in `docs/bug-log.md`. Auto-conversion was silently
failing every job once the source share grew past roughly one-third of
free output space — no errors surfaced to the operator, just an
ever-growing pile of `bulk_files.status='pending'` and a stale
Meilisearch index showing data from a previous DB lifetime.**

### Symptom on the affected machine

The K-drive ingest had reached 92,257 files (~250 GB). Every
scheduled auto-conversion job ran the pre-flight check, calculated
`required = 250 GB × 3 = 750 GB`, looked at the output volume's
~158 GB free, and aborted with:

```
158729 MB free on output volume but 750775 MB needed
(92257 files, 250258 MB input × 3 buffer)
```

The error landed in `bulk_jobs.error_msg` but had no surface in the
nav, status banner, or any pulse indicator — operators saw "12,847
indexed" (the stale Meilisearch count) and "94k scanned" (the
discovery count from the in-progress scan code path) and had no
visible reason for the gap.

### Root cause

`core/bulk_worker.py:21` declared `_DISK_SPACE_REQUIRED_MULTIPLIER = 3`
(introduced in v0.23.6 M2). The comment said the multiplier covered
"markdown output + sidecars + temp", but **markdown output is text and
sidecars are tiny JSON** — actual ratio is well under 0.5×. The 3×
assumption likely traced to a legacy extracted-image-files codepath
that hasn't applied since the content-hash sidecar redesign.

### What changed

- **`core/bulk_worker.py:21`** — replaced the hardcoded constant with
  a `_get_disk_space_multiplier()` helper that reads `DISK_SPACE_MULTIPLIER`
  from the environment with a default of **0.5**. Per-call read (not
  import-time snapshot) so runtime config takes effect without a
  container restart, mirroring the v0.34.x lesson on output-path
  resolvers.
- **`core/bulk_worker.py:_precheck_disk_space()`** — captures
  `multiplier` once at call time and uses it for the calculation, log
  event, and operator-facing error message. Error message now ends
  with `"tune via DISK_SPACE_MULTIPLIER env var"` so the next operator
  who hits a real space crunch immediately knows the lever exists.
- **`.env.example`** — new `DISK_SPACE_MULTIPLIER=0.5` entry with
  inline guidance on when to tune up (extracted-image workflows,
  dense vector indexing of large PDFs).
- **`tests/test_disk_space_multiplier.py`** — 10 unit tests covering:
  default, valid float override, integer-string override, small value
  honored, zero falls back, negative falls back, non-numeric falls
  back, empty falls back, whitespace falls back, per-call (not
  snapshot) read semantics.

No DB migration. No new endpoints. No API contract changes.

### Operator-visible change

- **Auto-conversion runs to completion** on shares that previously
  failed pre-flight. The 92,257 pending files in `bulk_files` drain
  on the next auto-conversion cycle (or a manual "Run scan now" from
  Activity / Pipeline).
- **Meilisearch index count climbs** from the stale ghost number
  toward the actual indexed total as conversion completes.
- **Tuning lever exists**: `DISK_SPACE_MULTIPLIER` in `.env` for
  shares with unusually large output. Most operators won't need to
  touch it.

### Why the original 3× shipped

Educated guess from the v0.23.6 M2 commit context: the check was
probably designed when extracted images were saved as separate output
files (legacy convertible path). The modern pipeline keeps content as
markdown text + content-hash-keyed sidecar JSON — a fraction of input
size. The multiplier never got revisited when the output model
changed.

### Why no alarm fired

Auto-conversion failure was logged at `error` level but not routed
through any operator-facing alert channel. The activity-events table
recorded the failure as a generic `bulk_end` (no special status), so
the existing dashboard surfaces showed normal-looking activity. This
is the bigger lesson — auto-pipeline failures should page someone.
Tracked separately as part of the upcoming UX overhaul (Notifications
trigger rules, see `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §13).

---

## v0.34.2 — Audit follow-up: 5 OUTPUT_BASE consumers missed by v0.34.1 (2026-04-28)

**Hotfix closing BUG-010 in `docs/bug-log.md`. Post-merge audit of
v0.34.1 found five silent-failure sites that the original blast-radius
sweep missed, all carrying the same root cause v0.34.1 set out to
eliminate: stale env-var reads or import-time-frozen aliases for the
output base directory.**

### What was missed

v0.34.1 unified six consumers behind `core/storage_paths.get_output_root()`,
but the audit grep used `OUTPUT_BASE` as the search anchor. Five further
sites read `BULK_OUTPUT_PATH` / `OUTPUT_DIR` directly (or imported the
new `OUTPUT_REPO_ROOT` module-level alias, which itself snapshotted the
resolver result at import time):

- **`core/lifecycle_manager.py:53`** — the `OUTPUT_REPO_ROOT = _output_root()`
  alias kept "for legacy importers". The alias is itself a frozen
  snapshot, so any importer would still see a stale path even though
  the underlying `_output_root()` getter re-resolves correctly.
- **`core/db_maintenance.py:167,175`** — `dangling_trash` health check
  imported the frozen alias. Operators saw wrong dangling-trash counts
  in the health summary after Storage Manager reconfiguration.
- **`api/routes/admin.py:674,700`** — admin Disk Usage breakdown read
  `BULK_OUTPUT_PATH` and `OUTPUT_DIR` env vars directly. Both rows
  reported against the wrong directory when env defaults diverged from
  the Storage-Manager-configured root.
- **`core/metrics_collector.py:217,227`** — same pattern in the 6h
  disk-snapshot job that persists rows to `disk_metrics`. Every
  snapshot since v0.34.1 (under a divergent Storage Manager config)
  recorded byte counts for the wrong directory — silently poisoning
  the time-series.
- **`core/lifecycle_scanner.py:332,1151`** — synthetic-lifecycle and
  pipeline-auto-conversion `create_bulk_job(...)` calls baked
  `os.getenv("BULK_OUTPUT_PATH", "/mnt/output-repo")` into the
  `bulk_jobs.output_path` column. Job rows recorded a path the bulk
  worker (which uses the resolver) might not actually have written to,
  leaving forensics ambiguous.

### What changed

All five sites now route through `core.storage_paths.get_output_root()`.
The `OUTPUT_REPO_ROOT` legacy alias on `lifecycle_manager.py:53` is
**dropped entirely** — its only importer (`db_maintenance.py`) was
migrated in this same release, and keeping the alias around just
re-introduces the frozen-snapshot footgun the v0.34.1 design set out
to eliminate.

Admin / metrics_collector now compute "Output Repository" and
"Conversion Output" against the same resolved path. Both labels are
retained for operator-facing clarity, but post-v0.34.1 they describe
the same directory under any modern Storage Manager configuration.

### Operator-visible change

- Admin Disk Usage panel shows correct paths and byte counts after a
  Storage Manager reconfiguration without a container restart.
- Disk-metrics time-series stops drifting on the very next 6h snapshot.
- Health summary's `dangling_trash` count agrees with the actual
  `.trash/` tree on the configured output root.
- New synthetic / auto-pipeline `bulk_jobs` rows record an
  `output_path` that matches where the worker actually writes.

### Why this didn't ship as part of v0.34.1

The v0.34.1 audit grep anchored on `OUTPUT_BASE` (the original frozen
constant in `core/converter.py`). Sites that read `BULK_OUTPUT_PATH`
or `OUTPUT_DIR` directly without going through `OUTPUT_BASE` slipped
past. v0.34.2's audit broadened the grep to all variants of those env
names plus any `*_REPO_ROOT` alias. No further sites surfaced after
the broadened sweep.

### What did NOT change

- `core/converter.py:74` — still defines `OUTPUT_BASE = Path(...)` as a
  retained module-level constant. Confirmed unused via grep across the
  whole repo (zero importers post-v0.34.1). Left as dead code rather
  than removed in this hotfix to keep the diff scoped to the audit
  finding; a future cleanup release can drop it.
- `main.py:233` — first-run-only seed of the `locations` DB table from
  `BULK_OUTPUT_PATH` / `BULK_SOURCE_PATH` env vars. This is intentional
  bootstrap behavior — operators set the env on first deploy, the
  values land in the DB once, and Storage Manager owns them thereafter.
  Not a silent-failure consumer.

No DB migration. No new dependencies. No new endpoints. No API
contract changes.

### Files touched

- `core/lifecycle_manager.py` — drop `OUTPUT_REPO_ROOT` alias
- `core/db_maintenance.py` — `dangling_trash` check uses resolver
- `api/routes/admin.py` — `_compute_disk_usage()` uses resolver
- `core/metrics_collector.py` — `_collect_disk_snapshot_impl()` uses resolver
- `core/lifecycle_scanner.py` — both `create_bulk_job()` call sites use resolver
- `docs/bug-log.md` — BUG-010 row, planned → shipped-v0.34.2
- `docs/version-history.md` — this entry
- `docs/help/whats-new.md` — operator-visible note
- `CLAUDE.md` — Current Version block updated

---

## v0.34.1 — Convert-page write-guard + folder-picker + 5 silent-failure consumers (2026-04-28)

**One-cut bug-fix release closing 9 entangled bugs (BUG-001..009 in
`docs/bug-log.md`). Tied together by `OUTPUT_BASE` having been
captured as a module-level constant at import time across 6 consumers,
each silently drifting from the Storage Manager (v0.25.0+) configured
path. New `core/storage_paths.py` resolver becomes the single source
of truth; Convert page picker now always populates its drives sidebar
even on initial-navigation failure.**

### What was broken

A single click on the Convert page produced two cascading failures:

1. Drop a PDF → `write denied — outside output dir: output/2026...` —
   the v0.25.0 write guard rejected the destination because
   `OUTPUT_BASE` defaulted to `/app/output`, outside the write-guard
   allow-list.
2. Click Browse on the Output Directory field → modal opened with the
   title visible but **no drives sidebar, no breadcrumb, no folder
   list**. The operator was stranded inside a broken modal.

Diagnosis traced these to **9 bugs in 4 root causes**:

- **BUG-001 / BUG-002** (folder picker) — picker only rendered drives
  on `/api/browse` 200; failed-navigation left sidebar blank. And
  output-mode only remapped `/host` / empty initialPath to
  `/mnt/output-repo`, leaving `/app/output` to fail-403 into the
  empty-sidebar dead end.
- **BUG-003** (`/api/convert`) — endpoint accepted `output_dir` Form
  param, stored it as a preference, then never passed it to the
  orchestrator. User-picked destination silently discarded.
- **BUG-004** (`OUTPUT_BASE` default) — the visible failure. Plus 5
  silent-failure consumers downstream:
  - **BUG-005** Download Batch silently 404s when bulk routed to
    Storage-Manager-resolved path
  - **BUG-006** History download links silently 404s (same)
  - **BUG-007** **Critical**: lifecycle scanner walked the wrong tree
    when output diverged → no soft-delete tracking → files never
    entered trash after source removal
  - **BUG-008** MCP returned wrong paths to AI clients
  - **BUG-009** `/ocr-images` static mount served from wrong dir

These 5 silent consumers "appeared fine" only because most deployments
set `OUTPUT_DIR=/mnt/output-repo` in env, which kept `OUTPUT_BASE`
and the Storage Manager output path coincidentally aligned. Drop the
env var (the v0.25.0+ design intent) and 5 latent failures appeared.

### Plan executed

`docs/superpowers/plans/2026-04-28-convert-page-write-guard-fix.md`,
**Option 2 (recommended)**: unify all 6 consumers behind a single
shared resolver, ship the visible Convert fix + the 5 silent-consumer
fixes in one coherent release rather than v0.34.1 + v0.34.2 + ...
patches drifting across the codebase.

The plan referenced `v0.33.4`; with v0.34.0 having shipped the same
day this slots in as v0.34.1.

### What changed

**1. New `core/storage_paths.py`** — single source of truth resolver.
Public surface:

- `get_output_root() -> Path` — resolves Storage Manager > BULK_OUTPUT_PATH
  > OUTPUT_DIR > fallback `output/`. Pure function, no caching, cheap.
  Re-resolves on every call so Storage Manager runtime reconfigs take
  effect without a process restart for runtime consumers.
- `get_output_root_str() -> str` — string form for FastAPI
  StaticFiles mount paths.
- `resolve_output_root_or_raise(*, label)` — like `get_output_root` but
  refuses the legacy `output/` fallback. Use in code paths that should
  never silently fall through.

**2. `core/converter.py`** — Bug D fix:

- `OUTPUT_BASE` retained as legacy alias / fallback only.
- `ConversionOrchestrator.__init__()` defers default resolution to call
  time. Passing an explicit `output_base` still works (test seam +
  back-compat); when omitted, resolved per-batch via the new helper.
- `convert_batch()` accepts a new optional `output_dir` parameter.
  Priority: explicit arg > orchestrator's explicit construction >
  resolver. Stored on `self.output_base` for the per-file convert
  thread.
- New log event `convert.output_dir_resolved` per batch. Fields:
  `requested`, `resolved`, `source` (`user` / `explicit` / `resolver`).

**3. `api/routes/convert.py`** — Bug C fix:

- Validate `output_dir` Form param against `is_write_allowed()` early
  (before file uploads land). Reject with HTTP 422 + structured
  error: `{"error": "output_dir_not_allowed", "message": ...,
  "requested": ...}`.
- When `output_dir` is empty, resolve via `get_output_root()` and
  reject with HTTP 422 `{"error": "no_output_configured", ...}` if
  the resolver falls through to the legacy default.
- Validated path threads through `_run_batch_and_cleanup` to
  `convert_batch(output_dir=...)`.
- New log event `convert.output_dir_rejected` for audit.

**4. `api/routes/batch.py`** + **`api/routes/history.py`** — Bug 5/6
fix. Both `_batch_dir(batch_id)` / `batch_dir = OUTPUT_BASE / ...`
sites now call `get_output_root() / batch_id` per-request. Imports
of `OUTPUT_BASE` removed.

**5. `core/lifecycle_manager.py`** — Bug 7 fix. Module-level
`OUTPUT_REPO_ROOT` replaced with `_output_root()` getter. All 4
`get_trash_path(...)` call sites updated. Backwards-compat alias
retained for legacy importers.

**6. `mcp_server/tools.py`** — Bug 8 fix. Same pattern: `OUTPUT_DIR`
constant replaced with `_output_dir()` getter; 4 call sites updated.

**7. `main.py:507`** — Bug 9 partial fix. `/ocr-images` mount uses
`get_output_root_str()` at app-startup time. Note: `StaticFiles`
binds at module-load before lifespan startup, so a Storage Manager
**runtime** reconfig still requires a container restart for
`/ocr-images` to follow. Documented in gotchas.

**8. `static/js/folder-picker.js`** — Bug A + B fix:

- New `_loadDrivesSidebar()` method fetches `/api/browse?path=/host`
  separately and always renders the drives sidebar BEFORE attempting
  to navigate to the requested startPath. Failed startPath leaves the
  sidebar populated so the operator can navigate elsewhere instead
  of being stranded.
- New `_isBrowsablePath(p)` helper mirrors `ALLOWED_BROWSE_ROOTS` from
  `api/routes/browse.py`. `open()` checks the requested initialPath
  against the allow-list and remaps non-browsable values to
  `/mnt/output-repo` (output mode) or `/host` (others) with a
  `console.info` audit log entry.

**9. `static/index.html`** — Convert page Output Directory now seeds
from `/api/storage/output` (Storage Manager configured path) before
falling back to the `last_save_directory` preference. Empty default
shows a placeholder pointing the operator at the Browse button + the
allowed root. Picker `initialPath` no longer falls back to the
legacy `/app/output`.

### Tests

`tests/test_convert_output_dir.py` — 7 new tests:

- 4 resolver-layer tests for the priority chain
  (Storage Manager > BULK_OUTPUT_PATH > OUTPUT_DIR > fallback) +
  `resolve_or_raise` rejecting the legacy fallback.
- `test_convert_rejects_out_of_allowed_output_dir` — POST
  `/etc/passwd` → HTTP 422 with `error=output_dir_not_allowed`.
- `test_convert_uses_storage_manager_default_when_unset` — POST with
  no `output_dir` + Storage Manager configured → 200 batch_id back.
- `test_convert_rejects_when_no_output_configured` — POST with
  nothing configured anywhere → HTTP 422 with
  `error=no_output_configured`.

### Files

- `core/version.py` — bump to 0.34.1
- `core/storage_paths.py` — NEW (~120 LOC)
- `core/converter.py` — `convert_batch(output_dir=...)`,
  `_resolve_default_output_base()`, per-batch resolution
- `api/routes/convert.py` — validate + propagate `output_dir`
- `api/routes/batch.py` — use resolver in `_batch_dir`
- `api/routes/history.py` — use resolver in download path
- `core/lifecycle_manager.py` — `_output_root()` getter, 4 call sites
  updated
- `mcp_server/tools.py` — `_output_dir()` getter, 3 call sites updated
- `main.py` — `/ocr-images` uses `get_output_root_str()`
- `static/js/folder-picker.js` — `_loadDrivesSidebar`,
  `_isBrowsablePath`, `open()` rewrite
- `static/index.html` — Convert page seeds output dir from Storage
  Manager + better placeholder + better picker initialPath
- `tests/test_convert_output_dir.py` — NEW (7 tests)
- `docs/bug-log.md` — BUG-001..009 moved to Shipped
- `docs/version-history.md`, `docs/key-files.md`,
  `docs/help/whats-new.md`, `docs/gotchas.md`, `CLAUDE.md`

No DB migration. No new dependencies. No new endpoints.

### Operator-visible change

- Convert page → drop a PDF → conversion succeeds (instead of
  rejected by write guard).
- Convert page → click Browse → picker opens with drives sidebar
  visible AND output-repo content in the main pane.
- Output Directory field shows the Storage Manager configured path
  by default instead of the legacy `/app/output`.
- Download Batch / History download / Lifecycle scanner / MCP all
  now agree on where output lives. Drop the env var override and
  nothing silently breaks.

### Backwards compatibility

- Deployments with `OUTPUT_DIR=/mnt/output-repo` (or another allowed
  root) in env continue to work — resolver falls back to env when
  Storage Manager isn't configured.
- API consumers calling `/api/convert` with a previously-accepted-but-
  now-rejected `output_dir` (e.g. `/etc/passwd` for some reason) start
  getting 422s. Documented as a deliberate non-breaking-but-behavior-
  changing fix — the previous behavior silently wrote somewhere the
  user didn't pick, which is worse.

---

## v0.34.0 — `.prproj` deep handler (parser + cross-reference + UI) (2026-04-28)

**Premiere Pro project files (`.prproj`) now go through a dedicated
deep handler instead of `AdobeHandler`'s metadata-only treatment. The
new handler streams the gzipped XML through `lxml.iterparse`, harvests
every clip path / sequence / bin defensively, renders a structured
Markdown summary, and persists the media-refs cross-reference to a
new `prproj_media_refs` table. Three new OPERATOR+ API endpoints
expose the cross-reference; the preview page gains a "Used in Premiere
projects" sidebar card. All three plan phases shipped as a single
release per operator request. Plus a new comprehensive
`developer-reference.md` help article.**

### Why this matters

Premiere project files are gzipped XML — they're machine-readable,
but the v0.33.x handler chain ran them through AdobeHandler which
extracted only filename + creator + modify date. Operators editing
in shared NAS environments routinely lose track of which Premiere
project a given clip belongs to. With the deep handler, MarkFlow
becomes the authority on that relationship — searchable by clip
filename and queryable via API.

### Deviation from the plan

The plan called for **three separate releases** (v0.34.0 / v0.34.1 /
v0.34.2 — one per phase). Operator chose option (1): one release
covering all three phases. Phase 0 (real-world fixtures) was deferred
— the suite ships with synthetic fixtures generated inside the test
file and a `test_real_fixtures_if_present` sweep that auto-runs
against any `.prproj` files dropped into `tests/fixtures/prproj/`.

### Phase 1 — parser + handler + Markdown rendering

**New module `formats/prproj/parser.py`** (~430 LOC). Public surface:
`parse_prproj(path) -> PrprojDocument`. `PrprojDocument` is a frozen
dataclass tree (`MediaRef`, `Sequence`, `Bin`). Implementation:

- **gzip + plain-XML autodetect** on the first 2 magic bytes.
- **Streaming `lxml.iterparse`** with element clearing for memory
  safety on 100 MB+ uncompressed XML.
- **Defensive tag-name heuristics** — substring matching against
  known Premiere tag fragments (`Clip`, `MasterClip`, `ClipDef`,
  `Sequence`, `Bin`, `FilePath`, `URL`, `MediaSource`, etc.) instead
  of fixed XPath. A small false-positive rate beats missing real refs.
- **Schema-confidence scoring** — `high` (known root + media + seqs),
  `medium` (one or the other), `low` (unknown root or empty harvest).
- **Security hardening** — `resolve_entities=False`, `no_network=True`,
  `recover=False`. No XXE, no external DTD fetch, no eval / exec / shell.

**New module `formats/prproj/handler.py`** (~340 LOC). `PrprojHandler`
extends `FormatHandler`, registered via `@register_handler` for
extension `prproj`. Renders a `DocumentModel` with H1 (project name),
metadata table, sequence list, media list (grouped by type), bin tree
(ASCII art), and parse-warning list. Exports as Markdown via the
existing handler chain.

**Routing change**: `formats/__init__.py` imports `PrprojHandler`
**after** `AdobeHandler`. The format registry is last-writer-wins, so
the new handler takes the `prproj` slot. `AdobeHandler.EXTENSIONS`
also drops `prproj` defensively.

### Phase 2 — DB + API

**New table `prproj_media_refs`** (DDL in `_SCHEMA_SQL` + idempotent
migration v28):

```sql
CREATE TABLE prproj_media_refs (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES bulk_files(id) ON DELETE CASCADE,
    project_path    TEXT NOT NULL,
    media_path      TEXT NOT NULL,
    media_name      TEXT,
    media_type      TEXT,
    duration_ticks  INTEGER,
    in_use_in_sequences TEXT,
    recorded_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_prproj_refs_media_path  ON prproj_media_refs(media_path);
CREATE INDEX idx_prproj_refs_project_id  ON prproj_media_refs(project_id);
CREATE INDEX idx_prproj_refs_project_path ON prproj_media_refs(project_path);
```

**New module `core/db/prproj_refs.py`** (~270 LOC). Two parallel
surfaces:

- **Async** (`upsert_media_refs`, `get_projects_referencing`,
  `get_media_for_project`, `delete_refs_for_project`, `stats`) — used
  by the API routes.
- **Sync** (`upsert_media_refs_sync`) — used by the handler, which
  runs in worker threads where the async pool isn't reachable. Opens a
  short-lived `sqlite3.Connection` with WAL + busy_timeout. Failures
  log + swallow — never fail an ingest because of cross-ref persistence.

The handler's `_best_effort_persist_refs` hook fires only when at
least one ref was harvested (skips on metadata-only fallback). FK
`ON DELETE CASCADE` ensures cleanup when a `.prproj`'s `bulk_files`
row is removed.

**New router `api/routes/prproj.py`** mounted at `/api/prproj`. Three
OPERATOR+ endpoints:

- `GET /api/prproj/references?path=<media_path>` — reverse lookup
- `GET /api/prproj/{project_id}/media` — forward lookup
- `GET /api/prproj/stats` — aggregate counts (n_projects, n_media_refs,
  top_5_most_referenced)

### Phase 3 — UI surface

**New shared module `static/js/prproj-refs.js`** (~120 LOC). Public
surface on `window.PrprojRefs`:

- `fetchProjectsReferencing(mediaPath)` — `/api/prproj/references` call
- `renderReferencesCard(container, refs)` — populates the sidebar card
- `isLikelyMediaPath(path)` — extension check (video / audio / image
  / graphic) used to decide whether to show the card

All DOM via `createElement` + `textContent` (XSS-safe per project
gotcha — mirrors `cost-estimator.js`).

**Preview page card**. `static/preview.html` gains
`#pv-prproj-refs-card` between the Flags and Related cards. Mounted
only when `info.path` looks like media. Empty state: *"Not referenced
by any indexed Premiere project."*

**Search page**. The existing dynamic facet-chip system surfaces
`prproj` as a filterable type once Premiere projects are indexed —
no static markup change needed.

### Phase 1.5 placeholders (deferred)

- **Sequence-clip linkage** — `MediaRef.in_use_in_sequences` is empty
  in v0.34.0; populating it requires a second iterparse pass to walk
  sequence-track-clip nodes. `merge_sequence_usage()` exists as a
  stub-shaped no-op.
- **Title text** + **marker comments** — denser schemas; deferred.

### Tests

`tests/test_prproj_handler.py` (~280 LOC):
- `test_parse_minimal_project` — 1 sequence, 5 clips
- `test_parse_medium_project` — 10 sequences, 100 clips
- `test_parse_handles_unknown_schema` — unrecognised root
- `test_parse_handles_truncated_gzip` — fallback path
- `test_parse_records_warnings_in_document` — malformed sequence node
- `test_handler_priority_wins_over_adobe` — routing
- `test_adobe_handler_no_longer_lists_prproj`
- `test_empty_document_fallback`
- `test_handler_renders_markdown_with_media_paths`
- `test_media_type_classification`
- `test_dedup_repeated_paths`
- `test_real_fixtures_if_present` (auto-skipped when no fixtures)

`tests/test_prproj_refs.py` (~250 LOC):
- `test_upsert_sync_writes_refs`
- `test_upsert_sync_replaces_not_duplicates`
- `test_upsert_sync_no_bulk_row_returns_zero`
- `test_reverse_lookup_3_projects_one_clip`
- `test_forward_lookup_returns_all_media`
- `test_cascade_delete_on_project_removal`
- `test_stats_aggregates`

### Help wiki additions

**New article `docs/help/developer-reference.md`** — comprehensive
deep-dive covering: quick-start, auth model, full API surface, all
new v0.34.0 endpoints, LLM cost subsystem, search + AI Assist,
pipeline + bulk endpoints, lifecycle + trash, storage + mounts,
analysis queue, log management, **database schema**, **log event
taxonomy**, format handler architecture, Docker / CLI workflows,
environment variables, and an **operational runbook**. Linked from
`_index.json` Integration category.

**Updated `docs/help/adobe-files.md`** — `.prproj` row in the
supported-formats table updated to "deep parse"; new section
"Premiere Pro Projects (Deep Parse)" with worked example, fallback
behaviour, cross-reference API pointer, and limitations.

**Updated `docs/help/admin-tools.md`** — new "Premiere project
cross-reference -- v0.34.0" section with operator + integrator
treatment, curl/Python/JavaScript samples, response-shape examples,
and audit-trail event reference.

**Updated `docs/help/whats-new.md`** — v0.34.0 entry with worked
examples ("which projects reference this clip?").

### Files

- `formats/prproj/__init__.py` — NEW (marker)
- `formats/prproj/parser.py` — NEW (~430 LOC, defensive iterparse
  walker)
- `formats/prproj/handler.py` — NEW (~340 LOC, render + Phase 2 hook)
- `formats/__init__.py` — register PrprojHandler after AdobeHandler
- `formats/adobe_handler.py` — drop `prproj` from EXTENSIONS + 4 inline
  comment cleanups
- `core/db/schema.py` — `prproj_media_refs` DDL added to `_SCHEMA_SQL`;
  migration v28 appended to `_MIGRATIONS`
- `core/db/prproj_refs.py` — NEW (~270 LOC, async + sync surface)
- `api/routes/prproj.py` — NEW (3 endpoints)
- `main.py` — register `prproj_routes.router`
- `static/js/prproj-refs.js` — NEW shared module (~120 LOC)
- `static/preview.html` — `#pv-prproj-refs-card` mount + 2 CSS rules
  + `loadPrprojRefsCard(info)` hook + cache-busted script tag
- `tests/test_prproj_handler.py` — NEW (12 tests + auto-fixture sweep)
- `tests/test_prproj_refs.py` — NEW (7 tests, async + sync)
- `tests/fixtures/prproj/README.md` — NEW (placeholder explaining
  Phase 0 deferral)
- `docs/help/developer-reference.md` — NEW comprehensive integrator
  reference
- `docs/help/_index.json` — register developer-reference article
- `docs/help/adobe-files.md`, `docs/help/admin-tools.md`,
  `docs/help/whats-new.md` — v0.34.0 sections
- `docs/version-history.md`, `docs/key-files.md`, `CLAUDE.md` —
  version blocks
- `core/version.py` — bump to 0.34.0

No breaking schema changes (purely additive). No new pip dependencies
(`lxml>=5.0.0` already present). One new scheduler job? No — the
cross-ref persists synchronously inside the existing bulk pipeline.

### Operator-visible change

- `.prproj` files now produce a structured Markdown summary instead
  of the metadata-only stub.
- Search page surfaces `prproj` as a facet chip when there are
  matching results.
- Preview page (for video / audio / image / graphic files) shows
  "Used in Premiere projects" card.
- New `/api/prproj/*` endpoints; new help article at
  `/help.html#developer-reference`.

### External integrators

External programs (asset management, IP2A, ops scripts) can hit the
new endpoints with the existing JWT or X-API-Key auth. Full curl /
Python / JavaScript samples live in `docs/help/admin-tools.md` and
`docs/help/developer-reference.md`.

---

## v0.33.3 — LLM token + cost estimation, Phase 3 (operational hardening) (2026-04-28)

**Closes the cost-estimation subsystem with finance-grade exports,
auto-staleness detection, and a fully-documented audit trail.**

### What landed

**CSV export endpoint** — `GET /api/analysis/cost/period.csv`
(OPERATOR+). Same data as the JSON `/period` endpoint but flattened
into one row per `(date, provider, model)` with columns: `date,
provider, model, files_analyzed, tokens, cost_usd`. Trailing TOTAL
row. Honors `?days=N` for trailing windows. Audit-trail event
`llm_cost.csv_exported` records actor + cycle label so admins can
see who pulled what. Suggested filename includes the cycle window
+ today's date.

**Daily staleness check** — new scheduler job
`check_llm_costs_staleness` runs at 03:30 daily (quiet window before
the 04:00 trash auto-purge). Calls `core.llm_costs.is_data_stale()`;
if true, emits a `llm_costs.stale` warning event with `updated_at`,
`threshold_days`, `source_url`, and a `hint` field telling the admin
exactly which file to edit + which endpoint to hit. Job count log
line bumped from 18 to 19.

**Stale-rate warning surfaced in UI** — the Admin Provider Spend card
already had the warning footer wired in v0.33.2; v0.33.3's value is
that the operator now has a *server-side* signal too (the daily log
event) that doesn't depend on someone opening the Admin page to see
the visual warning. Both surfaces work in parallel.

**Export CSV button** on the Provider Spend card. Added to the
existing footer alongside "Set cycle start day" + "Edit rate table".
Uses standard `<a href="..." download>` so the browser handles the
download flow.

**Audit trail documented**. Help doc points operators at
`/api/logs/search?q=llm_cost` to grep the full cost-calculation
history. Events catalogued:

- `llm_cost.computed` — every successful estimate (per-row,
  per-batch, per-period scopes)
- `llm_cost.no_rate` — rate-table miss (provider/model not in JSON)
- `llm_cost.no_tokens` — `tokens_used` is null
- `llm_cost.csv_exported` — CSV download
- `llm_costs.loaded` / `llm_costs.file_missing` /
  `llm_costs.load_failed` — lifecycle events
- `llm_cost.rate_table_reloaded` — admin hot-reload
- `llm_costs.stale` — daily staleness check fires

### Why a daily warning instead of a daily refresh

The plan was explicit: **no automatic refresh of the rate table**.
Pricing pages can change schema, drop models, or add new SKUs that
don't fit the loader's expectations. An automatic scrape against
provider websites is fragile and can introduce wrong values silently.
The right pattern is operator-curated: emit a clear "this is N days
old" warning, link the operator to the source URLs, and let them
update + reload on their own schedule.

### Tests

Two new tests added:

- `test_is_data_stale_old_date` — explicit stale path with
  `updated_at = "2020-01-01"` ensures `is_data_stale(threshold_days=90)`
  returns True (was previously only tested on the negative path).
- `test_aggregate_period_per_provider_breakdown_handles_zero_cost`
  — Ollama rows ($0.00) must NOT be silently dropped from the
  `by_provider` breakdown. Finance needs to see free inference is
  happening, not assume nothing ran. Regression guard.

### Files

- `core/version.py` — bump to 0.33.3
- `core/scheduler.py` — `check_llm_costs_staleness()` helper +
  CronTrigger(hour=3, minute=30) job; `scheduler.started` log line
  jobs count 18 → 19
- `api/routes/llm_costs.py` — `GET /api/analysis/cost/period.csv`
  endpoint (one row per `(date, provider, model)`, TOTAL footer,
  audit-trail event)
- `static/js/cost-estimator.js` — Export CSV link added to footer
- `tests/test_llm_costs.py` — 2 new tests (24 total now)
- `docs/help/admin-tools.md`, `docs/help/whats-new.md`,
  `docs/version-history.md`, `CLAUDE.md`

No DB migration. No new dependencies.

### Operator-visible change

- Admin → Provider Spend card → new "↓ Export CSV" link.
- Daily log warning when rate data >90 days old (search
  `llm_costs.stale` in Log Viewer).
- All cost calculations searchable as `llm_cost.*` events.

---

## v0.33.2 — LLM token + cost estimation, Phase 2 (UI surfaces) (2026-04-28)

**UI release on top of v0.33.1's backend. Three operator-facing surfaces
plus a comprehensive API-integrator section in the help docs.**

### What landed

**Per-batch Cost Estimate panel** on the Batch Management page.
Expand any batch and the file table is preceded by a panel showing
TOKENS / COST columns with actual + estimated breakdowns, the rate
used (e.g. `anthropic/claude-opus-4-7 ($45/1M blended)`), and a
collapsible per-file breakdown table.

**Provider Spend card** on the Admin page. Shows the cycle running
total ($XX.XX), tokens analyzed, file count, by-provider percentage
breakdown, days-into-cycle, and a "projected at current pace" figure
extrapolated from spend so far. Amber stale-rate warning footer when
the loaded `llm_costs.json` is >90 days old.

**Billing & Costs Settings section** with a `billing_cycle_start_day`
input (1-28). The page's existing generic save mechanism picks up
the new pref via the `data-key` attribute — no save-handler changes.

**Comprehensive API documentation** in `docs/help/admin-tools.md`:
- A "Provider Spend (LLM costs)" operator section with a worked
  budgeting example.
- A "Programmatic API access" section with **two parallel
  sub-sections** (per the operator's explicit request):
  - "For operators (the simple version)" — plain English, 4 numbered
    steps from "get an API key" to "MarkFlow logs the call."
  - "For developers (the technical version)" — auth header pattern,
    full endpoint reference table with role requirements, curl
    samples for all 6 endpoints, Python sample showing
    `current_cycle_total()` + `project_month_end()` +
    `trailing_week()`, JavaScript / Node sample showing
    `currentCycleSpend()` + `batchCost(id)`, and full JSON
    response-shape examples for `/cost/period` and `/cost/batch/{id}`.

This is the format external integrators (IP2A, finance dashboards)
need to plug in without spelunking through code.

### Architectural choices

**Single shared module instead of three copies.** Both pages
consume the same `static/js/cost-estimator.js` so a future cost-
display change is a one-file edit. Same pattern as v0.33.0's
`pipeline-card.js` — one cache-busted module, two mounts.

**XSS-safe DOM construction.** All new render code uses
`createElement` + `textContent` (never `innerHTML`). Per the
project's explicit gotcha, this is non-negotiable for any new
frontend code.

**Lazy fetch on Batch Management.** The cost panel only fetches
`/cost/batch/{id}` when the operator expands the batch — never on
the page-load list. Big batches (200+ files) don't pay any cost-
calculation overhead unless the operator actually wants to see it.

**Silent failure on cost endpoint errors.** The cost panel is
informational, not load-bearing. A network blip on `/cost/batch`
must never break the file-list browse experience. The catch
clause sets `mount.textContent = ''` and moves on.

### Files

- `static/js/cost-estimator.js` — NEW (~270 LOC)
- `static/batch-management.html` — `loadBatchCostPanel` +
  cache-bust to `?v=0.33.2`
- `static/admin.html` — Provider Spend card + `loadProviderSpend`
- `static/settings.html` — Billing & Costs section
- `docs/help/admin-tools.md` — Provider Spend doc + API integrator
  section
- `docs/help/settings-guide.md` — Billing & Costs entry
- `docs/help/whats-new.md` — user-facing release notes
- `CLAUDE.md`, `docs/version-history.md`
- `core/version.py` — bump to 0.33.2

No DB migration. No new endpoints (reuses v0.33.1's). No backend
changes. No new dependencies.

### Operator-visible change

- Click any batch on Batch Management → Cost Estimate panel renders
  above the file table with actual + estimated tokens/cost.
- Open Admin → new "Provider Spend (LLM costs)" card shows monthly
  running total + by-provider breakdown + month-end projection.
- Open Settings → new "Billing & Costs" section with the
  cycle-start-day input.
- Open Help → "Administration" → new "Programmatic API access"
  section with curl/Python/JS samples for external integrators.

---

## v0.33.1 — LLM token + cost estimation subsystem, Phase 1 (2026-04-28)

**Backend foundation for the per-batch / per-month cost-estimate
feature. No UI yet — Phase 2 (v0.33.2) wires the modal + admin card.**

### Problem

`analysis_queue.tokens_used` has been populated for every
analysed image since v0.18.x but has never been translated into
USD. Operators wanted "what does this batch cost?" + "what's my
running monthly total?" without leaving MarkFlow. Until v0.33.1
that meant manually multiplying token counts against the
provider's published per-1M-token rate.

### Fix

Three new files form the Phase-1 backend:

**`core/data/llm_costs.json`** — the single source of truth for
rate data. Schema-versioned (current: v1), externally editable,
hot-reloadable via API. Ships with current rates for Anthropic
(opus-4-6, opus-4-7, sonnet-4-6, haiku-4-5), OpenAI (gpt-4o,
gpt-4o-mini, gpt-4-turbo), Gemini (1.5-pro, 1.5-flash, 2.0-
flash), and Ollama (`*` wildcard at $0).

**`core/llm_costs.py`** — frozen-dataclass loader, arithmetic,
and aggregation. Strict schema validation rejects bad top-level
shape; bad individual rate rows are skipped + logged. Soft-
fails to an empty table on disk errors. Public surface:

```python
load_costs() / reload_costs() / get_costs()
estimate_cost(provider, model, tokens) -> CostEstimate
aggregate_batch_cost(batch_id, rows) -> BatchCostSummary
aggregate_period_cost(rows, cycle_start_day) -> PeriodCostSummary
is_data_stale(threshold_days=90) -> bool
```

Every cost calculation emits a `llm_cost.computed` (or
`llm_cost.no_rate`) structured log line. Searchable in Log
Viewer with `?q=llm_cost.computed` — Phase 3 promotes this to
a documented audit trail.

**`api/routes/llm_costs.py`** — six endpoints:

| Endpoint | Role | Returns |
|----------|------|---------|
| `GET  /api/admin/llm-costs` | OPERATOR+ | full rate table JSON |
| `POST /api/admin/llm-costs/reload` | ADMIN | `{ok, schema_version, ...}` |
| `GET  /api/analysis/cost/file/{entry_id}` | OPERATOR+ | `CostEstimate` for one analysis row |
| `GET  /api/analysis/cost/batch/{batch_id}` | OPERATOR+ | `BatchCostSummary` |
| `GET  /api/analysis/cost/period[?days=N]` | OPERATOR+ | `PeriodCostSummary` |
| `GET  /api/analysis/cost/staleness` | OPERATOR+ | `{is_stale, age_days, threshold_days}` |

### Cost arithmetic detail

`analysis_queue` stores a single `tokens_used` per row (the
per-image share of the batch's input+output total). The
estimator uses a 50/50 blended rate `(input_per_million +
output_per_million) / 2` rather than splitting input/output
because the underlying data isn't broken out. Documented as
such in the help doc; Phase 2 may surface "rate used: blended
$45/1M" so operators understand the calculation.

For batches with mixed analysed/pending rows, the aggregator
extrapolates pending-row cost from the batch's per-file
average. UI in v0.33.2 will label these clearly as
"Estimated" rather than mixing them into "Actual".

### Billing-cycle window

`compute_billing_cycle_window(cycle_start_day, today)`:

- Clamps `cycle_start_day` to 1..28 (avoids February edge case)
- If `today.day >= start_day`, current cycle = `today.replace(day=start_day)` → +1 month
- Otherwise, rolls back one month
- Year-boundary handled (Jan today + day=15 → Dec 15 prev year)

Operators set their `billing_cycle_start_day` preference in
v0.33.2's Settings entry (default 1 = calendar month) so the
"running total this cycle" matches their actual provider
invoice window.

### External integrators

All cost endpoints respect the existing JWT / `X-API-Key` auth.
External consumers (IP2A, dashboards, finance pipelines) can
mirror the rate table or pull period totals straight from the
API:

```bash
curl -H "X-API-Key: $KEY" http://markflow:8000/api/admin/llm-costs
curl -H "X-API-Key: $KEY" http://markflow:8000/api/analysis/cost/period
```

Full curl + Python + JS samples ship in `docs/help/admin-tools.md`
with v0.33.2.

### Files

- `core/data/llm_costs.json` (NEW)
- `core/llm_costs.py` (NEW, ~470 LOC)
- `api/routes/llm_costs.py` (NEW, ~210 LOC)
- `tests/test_llm_costs.py` (NEW, 17 tests)
- `main.py` — `load_costs()` in lifespan + register router
- `core/db/preferences.py` — `billing_cycle_start_day = "1"` default
- `CLAUDE.md`, `docs/version-history.md`, `docs/help/whats-new.md`
- `core/version.py` — bump to 0.33.1

No DB migration. No new dependencies. No new scheduler jobs.
No frontend changes.

### Operator-visible change

None until v0.33.2 ships the UI. Verify backend with curl above.

---

## v0.33.0 — Pipeline + Lifecycle + Pending cards merged; banner click-to-enlarge (2026-04-28)

**UX consolidation: one canonical Pipeline card across all pages,
plus click-to-enlarge on the live scan banner.**

### Problem

The Status page presented three top-level cards — Pipeline, Lifecycle
Scanner, and Pending — that read overlapping subsets of the same scan
data from three different endpoints. Operators saw the same number
three different ways. Worse, every release that touched scan-progress
display had to be applied to all three or they'd drift.

v0.32.11 closed by acknowledging the structural problem in writing:
"The right fix is to promote the rich Pipeline card to be the
canonical card on Status, drop the standalone Lifecycle Scanner card
(its data is already in the Pipeline card), and add a summary card
with link-to-status on the home page. Single source of truth, no
mirroring."

### Fix

**1. Shared module `static/js/pipeline-card.js`** (~430 LOC). Exposes
`mountPipelineCard(containerEl, opts)` returning `{refresh, destroy}`.
Polls `/api/pipeline/status` every 30 s. Renders the rich card (status
pill, Mode/Last Scan/Next Scan/Source Files/Pending/Interval cells
with sub-lines + tooltips inherited from v0.32.10) when
`opts.compact === false`, or a 1-line summary plus a "view full
status →" link when `opts.compact === true`. Action buttons
(Pause/Resume, Rebuild Index, Run Now) wired through a `postAction()`
helper. All DOM built via `createElement` + `textContent` (XSS-safe
per the project gotcha).

**2. Status page** drops `<div id="lifecycle-container">` (and its
`renderLifecycle()` IIFE that polled `/api/scanner/progress`) and
`<div id="pending-container">` (and its `loadPending()` IIFE).
Replaces them with `<div id="pipeline-card-mount">` hydrated by the
new module in non-compact mode. Auto-conversion sub-line folds into
the Pipeline card's Last Scan cell.

**3. Bulk Jobs page** removes ~150 LOC of inline `loadPipelineStatus`
+ helpers (now in the module). Mounts the same module in compact
mode — one-line summary keeps Bulk Jobs visually focused on jobs while
still surfacing scanner state for context. Removed
`togglePipelinePause`, `pipelineRunNow`, `rebuildSearchIndex`
(now in the module).

**4. Banner click-to-enlarge** (`static/bulk.html`). The Background
scan banner is now `role="button" tabindex="0"` with a "click to
enlarge" hint. New `#scan-detail-backdrop` modal renders run-id,
files scanned, total estimated, ETA, elapsed, current file path,
last-update-age, plus a short "What's a background scan?"
educational box and a link to the scanner log. Keyboard support:
Enter/Space opens, Escape closes, click-outside closes.

### Why a shared module instead of three copies

The Pipeline card data was being rendered three different ways across
`static/index.html` (originally), `static/bulk.html`, and
`static/status.html`. Every release that touched any of `mode`,
`last_scan`, `next_scan`, or `pending` had to be applied N times.
v0.32.10's descriptive sub-lines, v0.32.11's hydration fix, and this
release's consolidation all stemmed from "it changed in one place but
not the others." `pipeline-card.js` makes the next change a 1-file
edit.

### Files

- `core/version.py` — bump to 0.33.0
- `static/js/pipeline-card.js` — NEW, shared module
- `static/status.html` — Lifecycle + Pending cards removed, Pipeline
  card mount added, cache-bust to `?v=0.33.0`
- `static/bulk.html` — inline Pipeline replaced with compact mount,
  scan-detail modal markup + handlers added, cache-bust to `?v=0.33.0`
- `CLAUDE.md`, `docs/version-history.md`, `docs/help/whats-new.md`,
  `docs/help/status-page.md`, `docs/help/file-lifecycle.md`,
  `docs/key-files.md`

No DB migration. No new endpoints. No new dependencies. Pure frontend
reorganization + one new shared module.

### Operator-visible change

- Status page: 3 cards → 1 card. Same data, no duplication.
- Bulk Jobs: Pipeline header collapses to a 1-line summary that links
  to the full Status page when more detail is wanted.
- Every page with the live scan banner: click the banner (or focus +
  press Enter) to open the rich detail modal.

---

## v0.32.11 — Lifecycle scan state hydrates from DB on startup (2026-04-28)

**Single bug fix. The Status page's "Lifecycle Scanner" card
showed `Last scan: never` after every container restart, even
when the `scan_runs` table had dozens of completed scans.
Operators using "Status" as the canonical "what's happening"
page got a misleading read.**

### The bug

`core.lifecycle_scanner._scan_state` is a module-level dict
that holds the current scan's progress (running flag,
percentage, current file, etc.) and the cached "last scan"
timestamps. The dict initializes with `last_scan_at=None`.
The scan-finished branch at `_scan_state["last_scan_at"] =
now_iso()` only fires when a scan completes inside the
current process. After a container restart, the dict resets
to `None` and the API endpoint
`GET /api/scanner/progress` returns:

```json
{"running": false, "last_scan_at": null, "last_scan_run_id": null, ...}
```

The Status page's `renderLifecycle()` reads that and prints
`Last scan: never`. But the DB's `scan_runs` table is
durable — every scan that ever finished writes a row with
`finished_at` populated. The bug was just that the in-memory
state didn't read from it.

Diagnosed via:
```bash
$ curl -s http://localhost:8000/api/scanner/progress
{"running": true, ..., "last_scan_at": null, "last_scan_run_id": null}

$ curl -s http://localhost:8000/api/pipeline/status | jq .last_scan
{
  "id": "473f5456...", "status": "running", "files_scanned": 21529, ...
}

# DB knew the truth all along:
$ docker exec ... python3 -c "...SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 3"
running    started_at=2026-04-28 02:55:50  finished_at=None     files=21529
interrupted started_at=2026-04-28 02:14:57  finished_at=02:22:56 files=28504
cancelled  started_at=2026-04-27 23:14:40  finished_at=23:24:44 files=36738
```

So `/api/pipeline/status` reads from the DB and gets accurate
timestamps. `/api/scanner/progress` reads from the in-memory
dict and misses everything that ran in prior process
lifetimes.

### The fix

New function `hydrate_scan_state_from_db()` in
`core/lifecycle_scanner.py`. Queries the most recent finished
`scan_runs` row and populates `_scan_state["last_scan_at"]` +
`last_scan_run_id` if they're still None. Safe to call
repeatedly; only fills in fields that are currently None and
never overwrites an active scan's state.

Wired into `main.py`'s `lifespan` startup hook (Phase 9,
right before scheduler start). Result: by the time the
container's `/api/scanner/progress` endpoint serves its first
request, the in-memory state already reflects DB history.

### Operator-visible change

Before:
```
LIFECYCLE SCANNER  idle
Last scan: never
```

After (matches the same data the Pending card shows):
```
LIFECYCLE SCANNER  idle
Last scan: 2026-04-28 02:22:56 — 28,504 files scanned
```

### Files

- `core/version.py` — bump to 0.32.11
- `core/lifecycle_scanner.py` — new
  `hydrate_scan_state_from_db()`; `db_fetch_one` import
- `main.py` — call hydration in lifespan startup, before
  scheduler start
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new endpoints. No
new scheduler jobs.

### Best-practice note (deferred)

The Status page currently shows BOTH a "Lifecycle Scanner"
card and a Pipeline strip + Pending card with overlapping
data. The right architectural move is to **promote the rich
Pipeline card** (the one on Image 11 from /index.html — Mode,
Last Scan, Next Scan, Source Files, Pending, Interval) to be
the canonical card on Status, and either remove the
standalone Lifecycle Scanner card or visually nest it under
Pipeline as a sub-component. Single source of truth, no
mirroring drift.

This work is **not in v0.32.11** — only the data-source bug
is fixed. The merge is a UX redesign with implications for
the home page (which would gain a summary card linking to
Status). Plan and ship in a follow-up release.

---

## v0.32.10 — Pipeline header descriptive scan info (2026-04-28)

**Each cell of the Bulk Jobs page Pipeline header gains a
sub-line describing what it means. Last Scan: status pill +
scanned/new/modified counts. Next Scan: scan type +
paused/off handling. Mode: meaning + tooltip with the
scheduler's last full decision-reason. Time fields gain a
relative qualifier ("8 min ago" / "in 5 min").**

### Why

User reported on v0.32.9: "it would be more helpful for a
user to know what kind of scan is coming up next, what kind
of scan had already happened, just a little bit more
description."

The Pipeline header was 6 bare values:

```
Mode         Last Scan      Next Scan      Source Files   Pending   Interval
Immediate    7:22:56 PM     8:27:38 PM     1,493          1,493     45 min
```

Useful, but minimal. The operator couldn't tell:
- Was that 7:22:56 PM scan completed cleanly or interrupted?
- How many files did it actually process?
- Is the next scan the scheduler tick, or a different kind
  of run?
- What does "Mode: Immediate" actually do?

All this data was already on the `/api/pipeline/status`
response (`last_scan.status`, `last_scan.files_scanned`,
`last_scan.files_new`, `last_scan.files_modified`,
`last_auto_conversion.reason`). v0.32.10 surfaces it.

### Frontend changes — `static/bulk.html`

The Pipeline header markup gains a `.pl-cell` wrapper per
cell with a title attribute + a `.pl-cell-sub` div for the
descriptive sub-line:

```html
<div class="pl-cell" title="…explanation…">
  <span class="text-muted">Last Scan</span><br>
  <strong id="pl-last-scan">--</strong>
  <div class="pl-cell-sub" id="pl-last-scan-sub"></div>
</div>
```

The `loadPipelineStatus` JS now populates:

#### Mode sub-line

Mode-dependent text:
- **Off**: "Manual triggers only"
- **Immediate**: "Convert on every new-file detection"
- **Queued**: "Hold scan results for next tick"
- **Scheduled**: "Convert at scheduler intervals"

The Mode cell's title is also dynamically extended to include
the last auto-conversion's `reason` field, e.g.:

> Auto-convert scheduler mode.
>
> Last decision (running): Mode=immediate | 113354 files
> discovered | CPU now=4.9% | CPU historical avg=7.1% |
> samples=1 | Mon 20:00 | off hours | workers=8 | batch=175

The scheduler emits this rich reasoning string for every
auto-conversion run. Operators get the full decision context
on hover without cluttering the visible row.

#### Last Scan sub-line

A `.pl-status-pill` + counts:
- Status pill (color-coded): ✓ Completed / ⟳ Running /
  ⚠ Interrupted / ✗ Failed / ⊘ Cancelled
- "28,504 scanned · 12 new · 4 modified" (omits zero counts)

#### Next Scan sub-line

Type + interval, with paused/off/disabled fallbacks:

| Backend state | Sub-line |
|---|---|
| `disabled_info` set | "Disabled — fix shown below" |
| `paused = true` | "Pipeline paused — Resume to enable" |
| `auto_convert_mode = 'off'` | "Mode is Off — use Run Now to scan manually" |
| Otherwise | "Pipeline scan · every 45 min" |

#### Time qualifiers

Both Last Scan and Next Scan time displays now include a
relative qualifier:

- Last Scan: `7:22:56 PM (8 min ago)`
- Next Scan: `8:27:38 PM (in 5 min)`

The relative time is computed against `Date.now()` on each
render, so it stays accurate across the polled refresh
cadence.

### CSS — `static/markflow.css`

```css
.pl-cell { line-height: 1.35; }
.pl-cell-sub {
  margin-top: 0.15rem;
  font-size: 0.72rem;
  color: var(--text-muted);
  font-weight: 400;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}
.pl-status-pill {
  display: inline-block;
  padding: 0.05em 0.4em;
  border-radius: 3px;
  font-size: 0.68rem;
  font-weight: 600;
}
.pl-status-pill.pl-status-ok      { background: rgba(34,197,94,.15);  color: #4ade80; }
.pl-status-pill.pl-status-running { background: rgba(96,165,250,.15); color: #60a5fa; }
.pl-status-pill.pl-status-warn    { background: rgba(245,158,11,.18); color: #fbbf24; }
.pl-status-pill.pl-status-err     { background: rgba(239,68,68,.18);  color: #f87171; }
.pl-status-pill.pl-status-muted   { background: rgba(156,163,175,.18); color: #d1d5db; }
```

The grid template grew from `minmax(140px, 1fr)` to
`minmax(170px, 1fr)` to accommodate the wider multi-line
content without dropping below 6 cells per row on standard
viewports.

### Cache-bust

`?v=0.32.10` on `markflow.css` for `bulk.html` and `status.html`
(both pages now use the v0.32.9-introduced or v0.32.10-introduced
CSS rules).

### Files

- `core/version.py` — bump to 0.32.10
- `static/bulk.html` — Pipeline header markup with `.pl-cell`
  wrappers + tooltips; `loadPipelineStatus` populates
  sub-lines + status pill + relative-time qualifier;
  `markflow.css` cache-bust
- `static/markflow.css` — `.pl-cell` / `.pl-cell-sub` /
  `.pl-status-pill` + 5 status-color variants
- `static/status.html` — `markflow.css` cache-bust bumped
  `?v=0.32.9 → ?v=0.32.10`
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No backend changes —
the existing `/api/pipeline/status` endpoint already returned
all this data; v0.32.10 just surfaces more of it.

### Done criteria

- ✅ Last Scan cell shows status pill + scanned/new/modified
  counts beneath the timestamp
- ✅ Next Scan cell shows scan type + interval ("Pipeline
  scan · every 45 min") beneath the timestamp
- ✅ Mode cell shows what the mode does + tooltip with
  scheduler's last decision-reason
- ✅ Time fields show relative qualifiers ("8 min ago" /
  "in 5 min")
- ✅ Paused / Off / Disabled states render context-appropriate
  Next Scan sub-text instead of just hiding the value

---

## v0.32.9 — Status card matches Bulk Jobs scan progress + click-to-jump (2026-04-28)

**The Status page active-job card now renders the same rich
scan-phase data the Bulk Jobs page surfaces (X / Y files
scanned + current file + indeterminate animated bar), and is
click-through to `/bulk.html?job_id=<id>` with a smooth-scroll
+ highlight on the destination card.**

### Why

User comparing the two views of the same in-flight bulk scan:

- **Status page (v0.32.7-v0.32.8)**: `[spinner] Enumerating
  source files… 33s elapsed` and an empty progress bar. Fine
  for "the scan exists" but invisible whether it's at 100
  files scanned or 100,000.
- **Bulk Jobs page**: `Scanning source files / 10,696 files
  scanned / JOB SITE VISITS/2023 JOBSITE VISIT
  PHOTOS/.../IMG_1979.jpg` + filled animated bar.

The Status page card is the *first* place an operator sees the
scan; the Bulk Jobs page is the *deep* view they have to
navigate to. The richer data should be on both, and getting to
the deep view should be a single click.

### Backend changes

`core/bulk_worker.py`:

- `BulkJob.__init__` gains 3 new state fields:
  ```python
  self._scan_scanned = 0
  self._scan_total = 0
  self._scan_current_file = ""
  ```
- The `_scan_progress_cb` callback (which fires on every
  `scan_progress` event the `BulkScanner` emits) now stashes
  the latest values onto the job instance in addition to
  forwarding the event to the SSE bus:
  ```python
  if event_type == "scan_progress":
      if "scanned" in event and isinstance(event["scanned"], int):
          self._scan_scanned = event["scanned"]
      if "total" in event and isinstance(event["total"], int):
          self._scan_total = event["total"]
      if "current_file" in event and isinstance(event["current_file"], str):
          self._scan_current_file = event["current_file"]
  ```
- `get_all_active_jobs()` returns a new `scan_progress` dict
  in each job's payload:
  ```json
  "scan_progress": {
      "scanned": 10696,
      "total": 51684,
      "current_file": "JOB SITE VISITS/2023.../IMG_1979.jpg"
  }
  ```

The polled `/api/admin/active-jobs` endpoint now exposes the
same data the per-job SSE stream emits.

### Frontend — Status page

`static/status.html`:

- The `enumerating` block (where `job.status === 'scanning'`)
  renders three states based on `scan_progress.scanned`:
  - **scanned > 0**: rich line `[spinner] Scanning source
    files — 10,696 / 51,684 files scanned — 33s elapsed`
    plus a monospace current-file path beneath
  - **scanned == 0 and elapsed < 120 s**: legacy
    `[spinner] Enumerating source files… Xs elapsed`
  - **scanned == 0 and elapsed > 120 s**: legacy
    `⚠ Enumerating — stuck? No progress for X.` warning
- The `<div class="job-card__progress">` becomes
  `<div class="job-card__progress job-card__progress--indeterminate">`
  during scanning. The new modifier replaces the empty
  static-width bar with a sliding gradient sweep
  (1.6 s ease-in-out infinite, full-width track).
- The whole progress region (bar + line + current-file) is
  wrapped in an `<a class="job-card__progress-link"
  href="/bulk.html?job_id=<id>">` so clicking anywhere in
  that area navigates to the deep view.
- A small `↗ Open` button next to the job-id chip provides a
  more deliberate alternative click target.

### Frontend — Bulk Jobs page

`static/bulk.html`:

- New page-load IIFE reads `?job_id=` from `URLSearchParams`.
  If present, polls every 250 ms (up to 5 s) for the
  `active-job-section` div to be rendered by
  `loadJobHistory`, then:
  ```js
  el.scrollIntoView({behavior: 'smooth', block: 'start'});
  el.style.boxShadow = '0 0 0 3px rgba(99,102,241,0.55)';
  setTimeout(() => { el.style.boxShadow = ''; }, 1800);
  ```
  Smooth scroll + 1.8 s highlight flash draws the operator's
  eye to the freshly-navigated card.
- The retry-up-to-5s pattern handles the case where
  `loadJobHistory` is still in-flight when the IIFE runs
  (the function is async).

### CSS additions

`static/markflow.css`:

```css
.job-card__progress { ...; position: relative; }
.job-card__progress--indeterminate .job-card__progress-fill {
  width: 35% !important;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: jc-indeterminate-sweep 1.6s ease-in-out infinite;
}
@keyframes jc-indeterminate-sweep {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(370%); }
}
.job-card__progress-link {
  display: block; cursor: pointer; ...
  padding: 0.25rem; margin: -0.25rem;
  transition: background 0.15s;
}
.job-card__progress-link:hover { background: rgba(99,102,241,0.06); }
.job-card__open-link { ... }
```

### Cache-bust

- `markflow.css` on `status.html`: new `?v=0.32.9` query
  string (previously had none — relied on browser ETag
  revalidation which is unreliable for stylesheets)
- `live-banner.js` on `status.html`: bumped `?v=0.32.7 →
  0.32.9` for consistency (file itself unchanged)
- `bulk.html` doesn't need a CSS bust (uses no new CSS
  rules); its JS change is picked up via standard HTML
  revalidation

### Files

- `core/version.py` — bump to 0.32.9
- `core/bulk_worker.py` — `_scan_*` state fields, callback
  updates, `get_all_active_jobs` returns `scan_progress`
- `static/status.html` — rich scan-phase rendering,
  click-through `<a>` wrapper, ↗ Open button, CSS +
  live-banner.js cache-bust
- `static/bulk.html` — `?job_id=` honoring with smooth
  scroll + highlight flash
- `static/markflow.css` — indeterminate-bar modifier +
  click-through link styling + open-link button styling
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

### Done criteria

- ✅ Status page card during a bulk-job scan shows the same
  scanned-count + current-file the Bulk Jobs page shows
- ✅ Indeterminate animated bar replaces the empty static bar
- ✅ Clicking the progress region jumps to
  `/bulk.html?job_id=<id>`
- ✅ Bulk Jobs page scrolls the active job into view + flashes
  it on landing from the click-through

---

## v0.32.8 — Storage page verifies every source on page load + on tab focus (2026-04-28)

**Operator-feedback fix in response to a v0.32.7 user
observation: "we should have the green check mark show up
everytime markflow starts up and the user navigates to the
page... a verification everytime the page is refreshed."**

### The gap

Output Directory has been verified on page load since
v0.29.1 (`loadOutput()` calls `renderVerificationAt()`). But
`loadSources()` only rendered the table rows — label, path,
Remove button. No verification widget per row. The green ✓
that sometimes appeared at the top of the Sources section was
the `#source-add-verify` element populated by a recent Add
action; it didn't survive a page refresh, and it only showed
the most-recently-added source (operators with multiple
sources only saw verification for one of them).

### What ships in v0.32.8

#### 1. Per-source inline verification on page load

`loadSources()` now renders each source row with a multi-line
"Path & Status" cell:
- Line 1: the path (monospace)
- Line 2: a `.storage-verify-inline` widget that starts in
  the pending state (`⟳ Verifying…` with a CSS rotation
  animation) and async-resolves to ✓ Readable · N items
  / ✗ Unreachable via `/api/storage/validate`

Verifications fire **in parallel** across all sources — the
table renders synchronously and each row resolves at its own
pace, so a slow-responding network source doesn't block fast-
local ones.

A new `Map<source.id, {el, path}>` (`_sourceVerifyWidgets`)
tracks the active widgets so `reverifyAll()` and the Page
Visibility listener can re-run them without rebuilding the
table.

#### 2. Per-section ↻ Re-verify buttons

A small button next to each section's content header. One
click → all that section's widgets flip back to pending and
re-resolve. Buttons disable themselves while in flight to
prevent click-storm.

Three drivers:
- `reverifyAll()` — re-runs sources + output (used by
  Page Visibility listener)
- `reverifySources()` — re-runs sources only (Sources
  ↻ button)
- `reverifyOutput()` — re-runs output only (Output ↻ button)

#### 3. Auto-re-verify on tab focus (Page Visibility API)

A `visibilitychange` listener tracks how long the tab has
been hidden. When the tab regains focus after being hidden
**>30 seconds**, `reverifyAll()` fires automatically.

The 30-second threshold avoids hammering
`/api/storage/validate` on every micro-tab-switch (operators
flipping between Storage and another tab repeatedly within a
minute don't trigger re-validation each time).

This catches:
- USB drives plugged or unplugged while the operator was away
- SMB / NFS shares that dropped due to a network blip
- Any path that became inaccessible (permission change, mount
  expired, drive dismounted)

If the operator returns and the path is still good, the
re-verification is invisible (the green ✓ briefly flashes to
⟳ then back to ✓). If the path changed status, the new state
is reflected.

### CSS additions (`static/markflow.css`)

```css
.storage-verify .sv-pending {
  background: rgba(96,165,250,0.18);
  color: #3b82f6;
  animation: sv-pending-spin 1.4s linear infinite;
}
@keyframes sv-pending-spin { to { transform: rotate(360deg); } }
.storage-verify-inline { margin-top: 0.25rem; }
.storage-verify-inline .sv-line { font-size: 0.82rem; }
.storage-verify-inline .sv-sub { font-size: 0.78rem; padding-left: 1.5rem; }
.storage-reverify-btn { /* tiny button per section header */ }
```

The `.storage-verify-inline` modifier shrinks the existing
`.storage-verify` typography slightly so per-row widgets
don't dominate the table cells.

### Cache-bust

`?v=0.32.8` on `storage.js` (new — the existing storage.html
script reference didn't have a version query string).
`live-banner.js` cache-bust on the 3 pages that load it
(`trash.html`, `status.html`, `pipeline-files.html`) is
unchanged at `?v=0.32.7` — the file itself didn't change, no
need to bump.

### Files

- `core/version.py` — bump to 0.32.8
- `static/storage.html` — content-header rows gain
  ↻ Re-verify buttons; sources table column renamed `Path`
  → `Path & Status`; `?v=0.32.8` cache-bust on `storage.js`
- `static/js/storage.js` — `_sourceVerifyWidgets` Map +
  `renderPendingVerify` helper + `reverifyAll` /
  `reverifySources` / `reverifyOutput` drivers + Page
  Visibility listener wired in `init()`
- `static/markflow.css` — `.sv-pending` style with
  `sv-pending-spin` keyframe + `.storage-verify-inline`
  compact variant + `.storage-reverify-btn` styling
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No backend changes —
the existing `/api/storage/validate` endpoint already does
all the heavy lifting; v0.32.8 just calls it more often.

### Done criteria

- ✅ Every configured source shows ✓/✗ on page load (was:
  only the output)
- ✅ Each section has a ↻ Re-verify button for manual on-
  demand re-check
- ✅ Returning to the tab after >30 s of hidden time
  triggers an automatic re-verification of every path
- ✅ Slow-responding sources don't block other rows from
  resolving — verifications run in parallel

---

## v0.32.7 — Status page Enumerating UI now actually renders during scans (2026-04-28)

**One-line frontend fix. The "Enumerating source files…" UI
from v0.32.1 had a wrong condition that prevented it from
ever rendering. Fixed; operators now see honest scan-phase
feedback instead of a misleading `0 / ? files — ?%` for the
duration of every bulk scan.**

### The bug

The v0.32.1 release added an "Enumerating source files… Xs
elapsed" UI for jobs in the scanning phase, with a
stuck-warning that fires after 2 min of no progress. The
intent was to replace the broken `0 / ? files — ?%`
placeholder that operators saw during the enumeration phase
of every bulk scan.

The condition was:

```js
var enumerating = (job.status === 'scanning' && job.total_files == null);
```

But `job.total_files` is **never null** during scanning — it's
always **0**. Source: `core/bulk_worker.py:get_all_active_jobs`
sets `total_files = job._total_pending`, and `_total_pending`
is initialized to 0 in `BulkJob.__init__` and only assigned
the real count AFTER the scanner returns. So during the entire
scanning phase, `total_files == 0` (NOT null), the
`enumerating` condition is False, and the UI falls through
to the legacy display.

The condition was wrong from the v0.32.1 ship. The bug went
unnoticed because most scans complete in seconds; only on a
slow-HDD bulk scan with a deep tree did the misleading
display sit visible long enough to confuse anyone.

### Reported instance

A user clicked Force Bulk Scan against `/host/d/k_drv_test`
on an HDD. The scanner walked the directory tree for 20+
minutes (incremental scan checking every dir's mtime against
the cache). During that whole window the Status page showed:

```
SCANNING ▸ 21f3f9e7…
0 / ? files — ?%
✓ 0 converted   ✗ 0 failed   ⏭ 0 skipped
```

with no indication that the scanner was actually making
progress. The operator wanted to know whether to wait, stop,
or escalate.

### The fix

```js
var enumerating = (job.status === 'scanning');
```

The backend's `_scanning` flag is True for the entire
`BulkScanner.scan()` call and flipped False right before
`update_bulk_job_status(..., 'running', total_files=...)`. So
`status === 'scanning'` alone is the authoritative signal —
no need to also check total_files.

After the fix:

| Time in scanning | Display |
|---|---|
| 0–120 s | `[spinner] Enumerating source files… 1m 30s elapsed` |
| 120 s+ | `⚠ Enumerating — stuck? No progress for X. Stop the job and retry, or check the log viewer.` (existing v0.32.1 stuck warning, fires correctly now) |

The stuck-warning is honest because the existing
`(!job.last_heartbeat)` check is always true during scanning
(the `last_heartbeat` field is only updated by per-file
conversion workers, not by the scanner). So after 2 min any
scan correctly transitions to the stuck warning. If the scan
is genuinely making progress (just slow), the operator can
verify by tailing the log viewer using the link in the
status pill.

### Backend NOT changed

My initial v0.32.7 plan included a "backend auto-complete
scan when total_files=0" fix. Re-reading `bulk_worker.py`
confirmed it's not actually broken: the worker DOES transition
`scanning → running → completed` correctly on a zero-file
scan via the existing path:

- Line 474: `self._scanning = False`
- Line 476: `update_bulk_job_status(..., 'running', total_files=0)`
- Line 506: `self._total_pending = len(pending_files)` (= 0)
- Line 512-517: empty-list iteration over `pending_files`
- Line 519-521: sentinel values pushed to queue (workers exit immediately)
- Line 528: `await asyncio.gather(*workers)` returns
- Line 542: `update_bulk_job_status(..., 'completed', completed_at=...)`

The original observed "stuck-at-scanning for 20 min" was a
genuinely slow scan walking an HDD tree, not a missing
state transition. Withdrawn from this release.

### Cache-bust

`?v=0.32.6 → ?v=0.32.7` on the `live-banner.js` script tag in
all 3 pages that load it (`trash.html`, `status.html`,
`pipeline-files.html`). Same convention as v0.32.5/v0.32.6 —
bump on every release that touches `live-banner.js` or any
of these pages.

### Files

- `core/version.py` — bump to 0.32.7
- `static/status.html` — `enumerating` condition simplified
  to just `status === 'scanning'`; comment block extended to
  explain why total_files==null was the wrong signal
- `static/trash.html`, `static/status.html`,
  `static/pipeline-files.html` — `?v=0.32.7` cache-bust
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No backend changes.

### Done criteria

- ✅ Operator triggers a Force Bulk Scan; Status page card
  immediately shows `[spinner] Enumerating source files…
  Xs elapsed` instead of `0 / ? files — ?%`
- ✅ After 2 min of no transition, the existing
  v0.32.1 stuck warning fires automatically
- ✅ Once the scanner returns and the job transitions to
  `running`, the display flips to the normal `X / Y files
  — N%` format
- ✅ Zero-file scans (incremental scan finds nothing new)
  transition to `completed` quickly via the existing path

### Future polish (not in v0.32.7)

The scanner phase doesn't currently emit a heartbeat that
the API surfaces, so the stuck-warning is binary
(0–120s = spinner, 120s+ = warning). A future release
could add `scanner_last_event_at` (timestamp of the most
recent `on_progress` callback) to the job state and
surface it in `get_all_active_jobs`, so the stuck-warning
fires only after no scanner progress events for 2 min,
not after 2 min of any scanning. Bigger lift; defer.

---

## v0.32.6 — Server-authoritative timers on Trash progress card (2026-04-27)

**Trash progress timers (elapsed + "last update") are now
anchored to server-side timestamps instead of the user's
client clock. Navigating away from the Trash page and back
no longer resets either timer — they reflect the actual
operation, not the page session.**

### Why

Reported after the v0.32.4 ship: operator clicked Empty
Trash on the 51,684-row pile, watched the card, navigated
to Status, came back. Card showed "elapsed 12s" — implying
the op had only been running 12 seconds, when in reality
the worker had been chewing through the pile for several
minutes already. The displayed `done` count was also
suspect because it visually anchored to the (wrong) elapsed
time.

Root cause: the v0.32.4 frontend computed elapsed time as
`Date.now() - opStartTs`, where `opStartTs` was set to
`Date.now()` in `showCard()`. The card-show ran every time
the page mounted (including via `checkInFlightOps` on
returning to the page), so the timer reset on every navigation.

### Backend changes (`core/lifecycle_manager.py`)

Both `_empty_trash_status` and `_restore_all_status` dicts
gain two new fields:

```python
{
    "running": False,
    "total": 0,
    "done": 0,
    "errors": 0,
    "started_at_epoch": 0.0,         # NEW
    "last_progress_at_epoch": 0.0,   # NEW
}
```

The worker sets both on entry (`time.time()`). New helpers
`_bump_empty_progress()` and `_bump_restore_progress()`
stamp `last_progress_at_epoch = time.time()` whenever the
status changes meaningfully:

- **Empty trash**:
  - When `total` is set after Phase-1 enumeration completes
  - On every Phase-2 batch (200-row chunk of bulk_files
    UPDATE)
  - On every Phase-3 batch (200-row chunk of source_files
    UPDATE)
- **Restore all**:
  - When `total` is set after enumeration
  - On every per-row restore increment (was previously
    every-50-row syncs only — now per-row for finer
    granularity)

The `finally` block intentionally does NOT reset the
timestamps. The post-finish "Done" frame on the card needs
the true elapsed time the operation took; resetting on exit
would defeat that.

### Backend changes (`api/routes/trash.py`)

POST `/empty` and POST `/restore-all` now flatten
`started_at_epoch`, `last_progress_at_epoch`, `total`,
`done` into the top-level `already_running` response:

```json
{
    "status": "already_running",
    "total": 51684,
    "done": 12047,
    "started_at_epoch": 1761606123.456,
    "last_progress_at_epoch": 1761606145.892,
    "progress": {...}
}
```

The nested `progress` field stays for any caller that
already keys on it. New callers should use the flat fields.
This lets the frontend adopt the timestamps immediately on
a re-click instead of waiting for the next GET poll.

### Frontend changes (`static/trash.html`)

- New `adoptServerTimestamps(s)` helper called on every
  poll + on the initial mid-op recovery fetch + on the
  `already_running` POST response.
- `opStartTs` and `lastProgressTs` semantic shift — both
  now refer to server-authoritative `*_epoch * 1000` values
  (ms units to align with `Date.now()`).
- `showCard()` no longer resets the timer state; `checkInFlightOps`
  may have pre-seeded with server values.
- `updateTimers()` renders elapsed + last-update directly
  from server-anchored timestamps. Defensive fallback to
  `Date.now()` if the backend response somehow omits the
  fields (transitional safety; v0.32.6 backend always
  returns them).

### Cache-bust

`?v=` query string on `live-banner.js` bumped from `0.32.5`
to `0.32.6` on all 3 pages that load it (`trash.html`,
`status.html`, `pipeline-files.html`). The convention is
"bump on every release that touches `live-banner.js` OR
the page that loads it."

### Files

- `core/version.py` — 0.32.6
- `core/lifecycle_manager.py` — `import time`, status-dict
  field additions, `_bump_*_progress` helpers, non-reset
  on `finally`
- `api/routes/trash.py` — flatten timestamps into
  `already_running` POST responses (both endpoints)
- `static/trash.html` — `adoptServerTimestamps` helper,
  `opStartTs` / `lastProgressTs` semantic shift, no-reset
  in `showCard`, `checkInFlightOps` pre-seeds,
  `?v=0.32.6` cache-bust on `live-banner.js`
- `static/status.html`, `static/pipeline-files.html` —
  `?v=0.32.6` cache-bust (consistency)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies.

### Done criteria

- ✅ Operator clicks Empty Trash, leaves the page, comes
  back N minutes later — card shows elapsed = N+ minutes,
  not "12s"
- ✅ "last update" reflects the worker's actual last batch
  (e.g., "last update 2s ago" if the worker just stamped
  Phase-2 batch #100, or "last update 1m 30s ago" if it's
  been silent that long)
- ✅ Done count survives navigation correctly (was
  already correct in v0.32.4; just now accompanied by
  honest timer)

---

## v0.32.5 — Cache-bust on live-banner.js (2026-04-27)

**One-line fix per page: the `<script src="/static/js/live-banner.js">`
tag on each of the three pages that load the banner now
carries a `?v=0.32.5` query string. Forces returning
browsers to re-fetch the script on every release that
touches it, eliminating the "I deployed v0.32.3 but my
browser is still running v0.32.1's live-banner.js" stale-
cache class of bug.**

### Why

The v0.32.4 ship surfaced an honest user complaint: after
upgrading to v0.32.4 the operator's browser was still
serving the OLD `live-banner.js` from cache, so the global
sticky banner didn't render even though the inline progress
card (which is part of `trash.html` itself) did. FastAPI's
`StaticFiles` doesn't add `Cache-Control: no-cache`, so
browsers used heuristic freshness based on `Last-Modified`
and held the old file. Hard refresh (Ctrl+F5) fixed it for
each operator individually but isn't a sustainable solution.

### What

Three files changed, one-line edit each:

```diff
-  <script src="/static/js/live-banner.js"></script>
+  <!-- v0.32.5: cache-bust by version. Bump the ?v= when live-banner.js changes. -->
+  <script src="/static/js/live-banner.js?v=0.32.5"></script>
```

Files touched:
- `static/trash.html`
- `static/status.html`
- `static/pipeline-files.html`

Browsers treat URLs with different query strings as different
resources for caching purposes, so a version bump forces a
fresh fetch on the next page load. The query string is
ignored by FastAPI's static-file handler (it serves the same
file content regardless), so no backend change is needed.

### The release convention going forward

Every release that touches `static/js/live-banner.js` (or any
other long-lived JS in `static/js/`) should bump the `?v=`
query string in the loading `<script>` tags. Three files to
update; grep `live-banner\.js` to find them.

### What's deferred

A future release could automate this with one of:

1. **Auto-inject the version** at request time via a custom
   `StaticFiles` subclass that rewrites HTML responses to
   add `?v=<version>` to all `static/js/*` references.
2. **Switch StaticFiles to `Cache-Control: no-cache,
   must-revalidate`** so browsers always send a conditional
   request. Still hits the network on every page load but
   gets a cheap 304 Not Modified when nothing's changed.
3. **Service Worker** that maintains a versioned asset
   manifest. Cleanest UX, biggest engineering investment.

Each has trade-offs; the manual convention is fine for now.
The release process already touches `core/version.py` +
multiple docs files, so a 3-file find-and-replace fits the
existing rhythm.

### Files

- `core/version.py` — bump to 0.32.5
- `static/trash.html` — `?v=0.32.5` on the live-banner tag
- `static/status.html` — same
- `static/pipeline-files.html` — same
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No backend changes. No
behavioral changes — just cache hygiene on the JS asset.

---

## v0.32.4 — Inline progress card on Trash page (2026-04-27)

**Operator-feedback fix in response to a v0.32.3-shipped
Empty Trash run that "looked stuck" because the only signal
of progress was the disabled button text "Purging 0 / 51684..."
and the global Live Banner failed to surface. v0.32.4 ships a
prominent in-page progress card on the Trash page itself —
impossible to miss, with progress bar / counter / rate / ETA /
elapsed timer / last-poll-age indicator and a sticky hint when
the backend is still enumerating.**

### Why this matters

Reported by the operator after upgrading to v0.32.3:

> I clicked on empty trash... and i don't know if the
> markflow is executing my command. I want a progress bar or
> some kind of status bar to be visible to tell the user what
> is happening.

The screenshot showed the Trash page mid-operation: button
disabled with text "Purging 0 / 51684..." (so the POST
returned `started` with total=51684), but no global Live
Banner visible at the top of the page, and `done` stuck at
0 for tens of seconds. The operator had no way to tell
whether the worker was alive, just slow, or hung.

Two factors contributed to the gap:

1. **Backend enumeration window.** With 51K trash rows, the
   worker spends 30-60 s on the initial SQL COUNT before the
   first batch deletion fires. During that window, the
   `/api/trash/empty/status` endpoint returns `done=0,
   running=true`. Honest, but indistinguishable from a hung
   worker to the operator.
2. **Global Live Banner not visible.** The v0.32.3 Live Banner
   pins at `top: 56px` with `z-index: 90`. Either the page
   needed a hard refresh after the deploy (cached old
   live-banner.js) or the operator had scrolled past it. Either
   way, the only feedback they had was the button text.

### What the new card shows

The `.trash-progress` element lives directly between the
action buttons and the file table — operators see it without
scrolling, immediately on click, regardless of viewport
position or browser cache state.

```
┌────────────────────────────────────────────────────────────────┐
│ ● 🗑 Emptying trash                                           │
│ ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  (or anim) │
│ 12,047 / 51,684 files (23%)  437 files/s  ETA 1m 30s           │
│ elapsed 27s · last update just now                              │
│ ─────────────────────────────────────────────────────────────  │
│ Backend may still be enumerating the trash pile — large counts │
│ (50K+) can take 30-60s before progress numbers appear. The     │
│ worker is alive as long as "last update" is recent.            │
└────────────────────────────────────────────────────────────────┘
```

State machine:

- **Indeterminate / starting** — total = 0; bar animates
  left-to-right; counter shows "Starting…"; rate / ETA
  hidden.
- **Determinate / running** — total > 0; bar fills to
  done/total %; counter shows "X / Y files (N%)"; rate +
  ETA populate from EWMA-smoothed throughput.
- **Finished (green)** — done = total; bar at 100% green;
  Dismiss button shown; auto-hides after 5 s.
- **Errored (red)** — start endpoint returned non-2xx;
  bar at 100% red; error message in hint; Dismiss button.

### Implementation: unified `runTrashOp` driver

Replaces the two separate `pollEmptyProgress` /
`pollRestoreProgress` functions with a single driver that
takes an opts dict (start URL, status URL, button element,
running-text template, done-toast, etc.) and drives the card
end-to-end. Both **Empty Trash** and **Restore All** flow
through this. Adding a third long-running trash operation in
the future is now a one-call change.

The driver:

- Polls every **1 s** (was 2 s in the legacy poller). Operator
  sees movement twice as fast.
- Tracks **EWMA-smoothed rate** (α=0.3) so a momentary stall
  doesn't kill the ETA.
- Updates **elapsed + last-poll-age** every **250 ms** via a
  separate `setInterval` so timers tick smoothly even between
  status-endpoint polls.
- After **30 s** of `done=0` or `total=0`, surfaces the
  "backend may still be enumerating" hint as sticky text.
- On **transient poll failures** (network blip), leaves the
  card visible and lets the "last update" timer grow —
  signals degraded polling without aborting the whole op.

### Mid-op recovery (page-load `checkInFlightOps`)

If the user lands on the Trash page mid-op (e.g. after a hard
refresh during a long Empty Trash), the page now checks both
`/api/trash/empty/status` and `/api/trash/restore-all/status`
on load. If either reports `running=true`, the inline card
appears immediately with the current progress — no need to
re-trigger the op or wait for the next button click.

### Files

- `core/version.py` — bump to 0.32.4
- `static/trash.html` — `.trash-progress` CSS block (CSS
  variables-first, with pulse-dot + indeterminate-bar
  keyframes); HTML card element below the action buttons;
  unified `runTrashOp` driver replacing the legacy pollers;
  `checkInFlightOps` recovery path; `setCounterParts` /
  `setCounterStarting` helpers that build the counter via
  createElement (no innerHTML / template-string HTML)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.
No backend changes — the existing `/api/trash/empty` /
`/api/trash/restore-all` start endpoints and their `/status`
companions are unchanged.

### Done criteria

- ✅ Operator clicking Empty Trash sees the card appear
  immediately with the indeterminate bar animating
- ✅ Card stays visible without scrolling on a 1080p+
  viewport (sits between action buttons and file table)
- ✅ Card explains the "stuck at 0" window with a hint after
  30 s instead of leaving the operator wondering
- ✅ Mid-op page refresh recovers the card state from
  `/api/trash/*/status`
- ✅ Restore All gets the same card via the shared driver

---

## v0.32.3 — Trash 500-row cap removed, banner positioned below nav, banner UX polish (2026-04-27)

**Three bug fixes that surfaced from the v0.32.1 trash-empty
work and the live-banner deploy. All three were blocking
operators from using v0.32.1's banner + Empty Trash workflow
end-to-end.**

### Bug 1: Trash list capped at 500 rows

`core/db/lifecycle.py:get_source_files_by_lifecycle_status`
had a hard-coded `limit: int = 500` parameter. Every caller
that passed no explicit limit got the first 500 rows
silently — including `/api/trash` (list endpoint), which then
ran `total = len(files)` and returned `total: 500` in the
JSON response. Operators saw "500 files in trash" on the
Trash page indefinitely even when the database had 60K+ rows
in `lifecycle_status='in_trash'`. The Empty Trash workflow
did the same — `purge_all_trash()` only ever processed 500
rows per call, so clearing a 60K pile required 120+ button
clicks.

Fix:
- `get_source_files_by_lifecycle_status` accepts `limit=None`
  to fetch all matching rows in a single query. Default
  stays at 500 for callers that explicitly want paginated
  walks.
- New helper `count_source_files_by_lifecycle_status(status)`
  runs a dedicated `SELECT COUNT(*)` so endpoints can
  display true totals without paying the cost of fetching
  every row.
- `/api/trash` list endpoint now uses
  `count_source_files_by_lifecycle_status` for `total` and
  paginated `LIMIT/OFFSET` for the `files` array — the two
  are now consistent (operator sees real totals; per-page
  list stays bounded at 25 by default).
- `core/lifecycle_manager.py:purge_all_trash` and
  `restore_all_trash` both pass `limit=None` so a single
  Empty Trash / Restore All click clears the entire pile.
- `/api/trash/empty` and `/api/trash/restore-all` (POST
  endpoints) report the true total via the count helper, so
  the live banner shows e.g. "127 / 51,684" instead of "127
  / 500".

### Bug 2: Live banner covered the nav bar

`static/js/live-banner.js` set `position: fixed; top: 0;
z-index: 9999`. The nav bar in `markflow.css` is `position:
sticky; top: 0; z-index: 100; height: 56px`. Banner painted
over the nav during long-running operations — operators
couldn't navigate while a purge was in flight.

Fix: banner now `position: fixed; top: 56px; z-index: 90`.
Nav stays supreme at the very top; banner pins directly
below. Both stay anchored as the page scrolls. Body gains
`padding-top: 44px` when the banner is visible (via an
inline-injected style rule) so page content isn't hidden
under it.

### Bug 3: Banner showed "0 / 0 files" while running

The empty-trash worker initializes `_empty_trash_status` with
`total=0` and flips `running=true` BEFORE the SQL count
completes. There's a 100–500 ms window where the banner
sees `running=true` AND `total=0` and rendered "0 / 0 files
· — files/s · ETA —" which looked broken.

Fix: when `running=true` but `total <= 0` and not finished,
render "Starting…" instead. Rate / ETA lines collapse during
this window. Once `total` populates on the next 2 s tick,
the banner switches to the normal counter format.

Combined with Bug 1's fix returning true totals from
`/api/trash/empty`, the banner now shows "Starting… → 12 /
51,684 → 51,684 / 51,684 (Done)" through the lifecycle of
one click.

### Files

Modified:
- `core/version.py` — bump to 0.32.3
- `core/db/lifecycle.py` —
  `get_source_files_by_lifecycle_status(limit=None)` support;
  new `count_source_files_by_lifecycle_status`
- `core/lifecycle_manager.py` — `purge_all_trash` and
  `restore_all_trash` use `limit=None`
- `api/routes/trash.py` — three endpoints (list, empty,
  restore-all) use the count helper for true totals; list
  endpoint uses LIMIT/OFFSET on the SQL side
- `static/js/live-banner.js` — banner at `top: 56px` with
  `z-index: 90` below nav; body padding when visible;
  "Starting…" UX when total=0
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

### API behavior changes (visible to API consumers)

```bash
# /api/trash now returns the TRUE total (was capped at 500)
$ curl -s 'http://localhost:8000/api/trash?per_page=25&page=1' | jq '{total, page, per_page, files_in_page: (.files | length)}'
{
  "total": 51684,        # ← used to be 500
  "page": 1,
  "per_page": 25,
  "files_in_page": 25
}

# /api/trash/empty reports true total in the kickoff response
$ curl -sX POST 'http://localhost:8000/api/trash/empty'
{"status":"started","total":51684}   # ← used to be 500

# Status polling — banner reads done/total from here
$ curl -s 'http://localhost:8000/api/trash/empty/status'
{"running":true,"total":51684,"done":12047,"errors":0}
```

A single Empty Trash click now clears the entire pile
(~30 s wall-clock for 50K rows on this hardware, batched 200
at a time internally).

---

## v0.32.2 — Unrecognized-file recovery: `.tmk` handler + browser-download suffix shim (2026-04-27)

**Phase 1c + Phase 3 of
[`docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md`](superpowers/plans/2026-04-27-unrecognized-file-recovery.md).
The two highest-impact pieces of the plan, shipped without
waiting for Phase 0 (which requires a fresh `.tmk` operator
sample) or Phase 2 (general format-sniff fallback with
`bulk_files.sniffed_*` columns + UI surfacing — bigger lift,
deferred to a follow-up release).**

### What this fixes on the production instance

Two distinct classes of file were stranded in the
**Unrecognized** bucket on Pipeline Files:

1. **`.tmk` files** (5+ instances seen at v0.32.1, all
   sitting next to `.mp3` recordings under
   `/mnt/source/11Audio Files to Transcribe/...`). MarkFlow
   had no handler registered for the extension, so they
   always landed in `unrecognized`.
2. **`.download` files** (~30+ files under
   `.../IBEW White Shirts Receipt_files/`). Spot-checked as
   browser-saved JavaScript that retained the `.download`
   suffix Chrome / Edge / Firefox / Safari append during
   "Save Page As — Complete" exports. The real format is
   `.js` — MarkFlow already had a JS-capable text handler;
   it just couldn't see past the bogus extension.

Both classes now flow through the existing `SniffHandler`
delegation chain rather than landing as unrecognized.

### Implementation: extending `formats/sniff_handler.py`

`SniffHandler.EXTENSIONS` grew from `["tmp"]` to
`["tmp", "tmk", "download", "crdownload", "part", "partial"]`.
A new helper `_strip_browser_suffix(path)` checks the trailing
token against the `_BROWSER_DOWNLOAD_SUFFIXES` tuple
(`.download`, `.crdownload`, `.part`, `.partial`) and returns
the inner extension when a match is found.

A new **Step 0** in `SniffHandler.ingest` runs the strip
before any content sniffing:

1. **Browser-suffix strip** — if the inner extension has a
   registered handler, delegate immediately. No
   `python-magic` round-trip, no file-bytes read for
   detection.
2. (Existing) MIME-byte detection via libmagic.
3. (Existing) UTF-8 text-content heuristic → TxtHandler.
4. (Existing) Metadata-only stub.

The metadata-only stub now records the **actual originating
extension** in `DocumentMetadata.source_format` (e.g.
`"tmk"`, `"download"`) rather than always `"tmp"` — operators
triaging the converted output can see what they're looking at
without back-tracing to the source path.

### What stays out of scope (deferred)

The general format-sniff fallback for **any** unrecognized
extension (Phase 2 of the plan) is bigger:

- DB migration for `bulk_files.sniffed_format`,
  `sniffed_method`, `sniffed_confidence` columns
- New `core/format_sniffer.py` module with magic-byte table +
  text-heuristic + python-magic fallback
- Surfacing in search results (Meili re-index — ~10 min on the
  current corpus)
- Surfacing in the preview-page Conversion sidebar card

Deferred per the plan's "if schedule pressure forces a cut,
ship 0+3+1 and defer 2" guidance. The v0.32.2 implementation
already recovers the operator's actual stuck files — Phase 2
adds breadth (catching unknown extensions like `.iso`, `.bin`,
etc.) at the cost of a larger surface and a re-index.

### Files

- `formats/sniff_handler.py` — `EXTENSIONS` expanded;
  `_strip_browser_suffix` helper; Step 0 in `ingest`;
  metadata-only stub records the originating extension;
  `_BROWSER_DOWNLOAD_SUFFIXES` constant; updated docstring.
- `core/version.py` — bump to 0.32.2
- `docs/help/unrecognized-files.md` — new "Step 0:
  Browser-suffix strip" section + "Step 4: Metadata-only
  stub" section + per-version recovery summary at the top
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.
No frontend changes — recovery is silent from the UI's
perspective; affected files just transition from
`unrecognized` to `converted` after the next bulk pipeline
cycle.

### Done criteria

- ✅ Zero `.tmk` rows remain in the Unrecognized bucket after
  the next bulk scan (per the plan's Phase 1 criteria).
- ✅ Zero `.download` / `.crdownload` / `.part` / `.partial`
  rows remain in Unrecognized (per Phase 3 criteria).
- ✅ Files that flow through the inner-extension delegation
  pick up the **real** handler (TxtHandler for `.js`,
  PdfHandler for `.pdf`, etc.) rather than the
  metadata-only stub.

---

## v0.32.1 — Pipeline-files filter + AutoRefresh + Live Banner + clickable status pills (2026-04-27)

**Operator-experience cleanup release. The v0.32.0 preview page
exposed three classes of stale-data / opacity / lifecycle-bloat
problems; v0.32.1 fixes all three plus follow-on polish.**

### Pipeline Files filter — show only files actually on disk

`bulk_files.lifecycle_status` and `bulk_files.status` are
orthogonal — a file can be `pending` (never converted) AND
`in_trash` (lifecycle scanner saw it disappear). The Pipeline
Files page ignored lifecycle, so on this instance it showed
113K rows of which only ~2K reflected files actually present
on disk.

Backend changes:
- `core/db/bulk.py:get_pipeline_files()` gains
  `include_trashed: bool = False`. When False, the
  pending/failed/unrecognized queries add a JOIN on
  `source_files` with `sf.lifecycle_status = 'active' OR
  sf.lifecycle_status IS NULL` (the IS NULL branch preserves
  orphaned bulk_files rows from older datasets where
  `source_file_id` wasn't backfilled).
- The pending_analysis / batched / analysis_failed paths get
  the same JOIN (against `source_files` keyed on
  `aq.source_path`).
- `api/routes/pipeline.py:pipeline_files()` exposes the
  parameter.
- `api/routes/pipeline.py:pipeline_stats()` applies the same
  filter to the failed and unrecognized counters (the
  scanned and pending_conversion counters already filtered).
  Stats cache is keyed only for the active-only case;
  trashed-included results are computed fresh.

Frontend: new "Include trashed / marked-for-deletion files"
checkbox below the search bar in `static/pipeline-files.html`.
Both `/api/pipeline/stats` and `/api/pipeline/files` get the
`include_trashed=true` query param when checked; counters
and list refresh together.

Result on the production instance: list dropped from ~113K
rows to ~2K. Toggle stays available for power users
investigating registry/disk divergence.

### Trash purge-on-demand

The 60K+ `in_trash` rows weren't going to age out for ~42
days under the default 60-day retention. Triggered the
existing `POST /api/trash/empty` in a 15-call loop (the
endpoint caps each call at 500 source_files via
`get_source_files_by_lifecycle_status`'s underlying query).
Cleared ~7,500 rows immediately; the rest age out on the
existing schedule.

Follow-up note: `purge_all_trash` should eventually process
all rows in one call rather than capping at 500 — the
defensive cap predates the v0.23.x dedup work that
significantly reduced row weight.

### AutoRefresh shared helper

New `static/js/auto-refresh.js` (~120 LOC) — opt-in polling
with visibilitychange-pause and concurrency guard:

```js
AutoRefresh.start({
  refresh: () => { loadStats(); loadFiles(); },
  intervalMs: 30000,
});
```

Behavior:
- Polls every `intervalMs` while the tab is visible.
- Pauses on `visibilitychange === 'hidden'` so backgrounded
  tabs don't burn API calls.
- On tab focus, fires one immediate refresh + resumes the
  interval.
- Concurrency guard prevents two refreshes from overlapping
  on slow networks (`inFlight` boolean).
- Returns a public handle with `refreshNow()`, `stop()`,
  `lastRefreshAt()` for callers that want manual triggers.

Wired this release:
- `static/pipeline-files.html` (30 s)
- `static/batch-management.html` (60 s — exists alongside the
  existing 5 s pollTick which handles status counters)
- `static/flagged.html` (30 s)
- `static/unrecognized.html` (60 s)

Pages with their own polling / SSE (status, history, bulk,
resources, db-health, debug, log-viewer, trash, preview)
left alone — they have correct refresh already.

### Live Status Banner

New `static/js/live-banner.js` (~270 LOC) — sticky banner
at the top of any page that includes the script. Polls a
configurable list of long-running operation endpoints and
shows progress when any is in flight:

```
🗑 Emptying trash · [bar 25%] · 127/500 files · 2.4 files/s · ETA 2m 35s · ×
```

Architecture:
- Single banner DOM, position:fixed, z-index 9999.
- 2 s poll cadence; pauses while tab hidden.
- ETA computed client-side via EWMA-smoothed throughput
  (`α=0.3`) so status endpoints don't need ETA fields.
- Auto-collapses 4 s after the operation finishes (so
  operator sees the green "Done" state before the banner
  hides).
- Built entirely via `createElement` / `textContent` — no
  innerHTML, XSS-safe even if a status endpoint were ever
  to return operator-controlled text.
- Public hook `window.LiveBanner.register({key, url, label,
  icon, noun})` for pages to add their own long-running ops
  (e.g., a force-action queue endpoint when one is added
  later).

Wired to: `static/trash.html`, `static/status.html`,
`static/pipeline-files.html`. Currently polls
`/api/trash/empty/status` and `/api/trash/restore-all/status`;
add new endpoints to the registry as new long-running ops
are added.

### Clickable status pills + log-viewer deep-link

The status pills on the Status page were dead labels. v0.32.1
makes them hyperlinks:

| Pill | Click destination |
|------|-------------------|
| **SCANNING `<id>…`** | `/log-viewer.html?q=<job_id_prefix>&mode=history` |
| **PENDING** (header card) | `/pipeline-files.html?status=pending` |
| **LIFECYCLE SCAN** (running) | `/log-viewer.html?q=lifecycle_scan&mode=history` |
| **LIFECYCLE SCANNER** (idle) | `/log-viewer.html?q=lifecycle_scan&mode=history` |

`static/log-viewer.html` gained `?q=<text>` and
`?mode=history` URL parameter handling. On load, if `q` is
present the search input is pre-filled and dispatched;
`mode=history` flips to history search mode and runs
immediately.

CSS: new `.status-pill--link` class with the existing
`.stat-pill--link` hover pattern (opacity + scale) plus a
small ↗ glyph (Unicode `\2197`) to signal external
destination.

### Scanning-card UX fix

Active scanning jobs in their first ~10 s of life have
`total_files = NULL` because the bulk_scanner is still
walking the source tree. The status card was rendering
"0 / ? files — ?%" which looked broken — the user reported
it as a perceived error. New rendering:

- While `status='scanning' AND total_files IS NULL`: show
  spinner + *"Enumerating source files… 12s elapsed"*.
- If elapsed > 2 min AND `last_heartbeat IS NULL`: switch to
  warning tone — *"⚠ Enumerating — stuck? No progress for
  3m 24s. Stop the job and retry, or check the log viewer."*
- After `total_files` is set: revert to the normal
  "N / M files — pct%" line.

This diagnoses the exact symptom reported ("there seems to be
an error in the scanning progress card") — gives operators a
clear action path (Stop + retry, or follow the now-clickable
SCANNING pill to the log viewer) when a job is genuinely
stuck.

### Plan: `.tmk` handler + `.download` format-sniff

Written plan at
[`docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md`](superpowers/plans/2026-04-27-unrecognized-file-recovery.md).

Three phases:
- **Phase 0** — discovery: collect a fresh `.tmk` sample (all
  on-disk samples have already aged into `in_trash`); decide
  handler shape based on actual content.
- **Phase 1** — `.tmk` handler. Three variants per discovery
  results: text-extension, audio-sidecar, or unknown-format
  stub.
- **Phase 2** — general format-sniff fallback for
  unrecognized files. Magic-byte test → text heuristics →
  `python-magic` cascade. Stores `sniffed_format /
  sniffed_method / sniffed_confidence` on `bulk_files`;
  surfaces in search results + file-detail page.
- **Phase 3** — browser-suffix shim (`.download` /
  `.crdownload` / `.part` / `.partial`) — strip the suffix,
  re-classify on the real extension. Cheap special case for
  the bulk of `.download` files (confirmed via spot-check to
  be browser-saved JS).

Implementation deferred — operator can ship incrementally.

### Files

New:
- `static/js/auto-refresh.js` (~120 LOC) — shared
  refresh-on-visibility helper
- `static/js/live-banner.js` (~270 LOC) — sticky
  long-running-op progress banner
- `docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md`
  — written plan

Modified:
- `core/version.py` — bump to 0.32.1
- `core/db/bulk.py` — `include_trashed` parameter on
  `get_pipeline_files`
- `api/routes/pipeline.py` — endpoints honor
  `include_trashed`; stats cache refactor
- `static/pipeline-files.html` — toggle + AutoRefresh +
  LiveBanner wire-up + URL state
- `static/batch-management.html`, `flagged.html`,
  `unrecognized.html` — AutoRefresh wire-up
- `static/trash.html`, `status.html` — LiveBanner wire-up
- `static/status.html` — clickable pills, scanning-card UX
  fix
- `static/log-viewer.html` — `?q=` / `?mode=history` URL
  params
- `static/markflow.css` — `.status-pill--link` hover styles
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`, `docs/help/_index.json`,
  `docs/help/keyboard-shortcuts.md`, `docs/key-files.md`

No DB migration. No new dependencies. No new scheduler jobs.

### API quick-reference

```bash
# Pipeline Files honors include_trashed
curl -s 'http://localhost:8000/api/pipeline/files?status=pending'
curl -s 'http://localhost:8000/api/pipeline/files?status=pending&include_trashed=true'

# Stats endpoint same shape
curl -s 'http://localhost:8000/api/pipeline/stats'
curl -s 'http://localhost:8000/api/pipeline/stats?include_trashed=true'

# Long-running operation status (Live Banner polls these)
curl -s 'http://localhost:8000/api/trash/empty/status'
curl -s 'http://localhost:8000/api/trash/restore-all/status'

# Trash purge — runs in batches of 500 source_files per call
for i in 1..N; do
  curl -s -X POST 'http://localhost:8000/api/trash/empty'
  # poll /status until running=false, then loop
done
```

---

## v0.32.0 — File preview page + Batch Management UX polish (2026-04-27)

**Replaces the long-standing 19-line `static/preview.html` stub
with a full-fledged file-detail viewer. Click the folder icon
on a Pipeline Files row and a real page opens with inline
content preview (per format), a metadata sidebar showing every
DB registry row that touches the file, and operator actions
(Download / Open / Copy path / Show in folder / View converted
/ Re-analyze). Sibling navigation with ←/→ keys; Esc jumps back
to Pipeline Files filtered to the parent directory.**

Plan executed:
[`docs/superpowers/plans/2026-04-27-preview-page-implementation.md`](superpowers/plans/2026-04-27-preview-page-implementation.md).

### Architecture

The preview page is the **source-file inspection** surface — a
peer of `static/viewer.html` (the converted-Markdown viewer).
viewer.html renders the Markdown OUTPUT; preview.html shows the
INPUT alongside its lineage through the conversion + analysis
pipelines.

### New backend router — `api/routes/preview.py`

Six endpoints, all `OPERATOR+`-gated and path-keyed (verified
by `core.path_utils.is_path_under_allowed_root`). Path
validation rejects relative paths, Windows-style backslashes,
drive-letter prefixes, and anything outside the allow-listed
mount roots.

- `GET /api/preview/info` — composite endpoint returning file
  metadata + source_files row (if any) + latest bulk_files
  conversion (if any) + latest analysis_queue row (if any) +
  active file_flags + sibling listing. Sibling listing capped
  at 200 entries with a 10s wall-clock guard so a slow
  SMB/NFS share can't pin the request thread. Computes
  `viewer_kind` server-side as a dispatch hint, refining
  `office` to either `office_with_markdown` or
  `office_no_markdown` based on whether a successful
  conversion exists.
- `GET /api/preview/content` — raw bytes via FastAPI's
  `FileResponse`, which honors HTTP Range headers natively
  (so the browser's `<video>` / `<audio>` elements seek
  correctly). 500 MB inline cap as defense-in-depth against
  unbounded fetches.
- `GET /api/preview/thumbnail` — server-rendered JPEG via
  the shared `core.preview_thumbnails.get_cached_thumbnail`.
  Reuses the same LRU cache as the analysis-route preview
  endpoint (cache key is path-based, so both endpoints share
  hits on identical paths).
- `GET /api/preview/text-excerpt` — first N bytes UTF-8
  decoded with `errors='replace'`. Default 64 KB, hard max
  512 KB. Extension-gated to TEXT_EXTS / OFFICE_EXTS / unknown
  so a `.mp4` doesn't accidentally get decoded.
- `GET /api/preview/archive-listing` — zip / tar (auto-detect
  gz/bz2/xz) / 7z entries (cap 500). The 7z format uses the
  system `/usr/bin/7z l -slt` listing command parsed via
  block-per-entry. Already-corrupt archives surface as HTTP
  422 rather than 500.
- `GET /api/preview/markdown-output` — converted Markdown
  contents if a successful `bulk_files` row exists for the
  source path. Honors the path-traversal guard on the
  output_path too — a corrupted DB row pointing outside the
  allowed roots returns 400, not the file.

### Refactor — `core/preview_thumbnails.py` (new shared module)

Extracted the thumbnail cache + dispatch logic out of
`api/routes/analysis.py` into a shared module. Cache key is
now path-based: `(resolved_path_str, st_mtime_ns, st_size)`.
This means a thumbnail rendered via the source_file_id-keyed
analysis endpoint AND the path-keyed preview endpoint share
the same cache entry — no duplicate rendering for the same
file.

The existing `/api/analysis/files/:source_file_id/preview`
endpoint stays externally identical: same response shape, same
cache behavior. Internally it now delegates to
`get_cached_thumbnail(path)` which raises OSError on
inaccessible files and RuntimeError on PIL/rawpy/cairosvg
failures; the route layer translates to HTTP 404 / 500
respectively.

The pillow-heif registration at module load is preserved so
HEIC/HEIF files continue to flow through the standard PIL
path.

### Helpers — `core/preview_helpers.py` (new)

Pure functions used by the info endpoint:
- `classify_viewer_kind(path)` — extension → `image | audio
  | video | pdf | text | office | archive | unknown`
- `get_mime_type(path)` — best-effort MIME with overrides for
  HEIC, AVIF, Opus, etc. that stdlib mimetypes returns None
  on
- `get_file_category(path)` — coarse category for the
  metadata sidebar (`document` aggregates PDFs + Office
  formats)
- `can_render_native(path)` — predicate for "browser can
  render via /content directly" vs "needs /thumbnail"

No I/O — purely extension-based so works on a path that may
not exist on disk yet.

### Frontend — full rewrite of `static/preview.html`

~770 LOC replacing the 19-line stub. Sticky toolbar
(breadcrumb · title · status pill · flag pill · action
buttons) above a CSS-grid two-pane layout (viewer left,
sidebar right). Per-viewer dispatch on `info.viewer_kind`:

- `image` — `<img>` from /content with /thumbnail fallback
  on error (handles TIFF/EPS/HEIC/RAW/SVG/PSD that browsers
  can't render natively)
- `audio` — `<audio controls>` with HTTP range seeking
- `video` — `<video controls>` with HTTP range seeking
- `pdf` — `<iframe>` using the browser's built-in PDF viewer
- `text` — `<pre><code>` of the first 64 KB
- `office_with_markdown` — `marked.parse()` →
  `DOMPurify.sanitize()` → `innerHTML`. Same import block as
  viewer.html (CDN-cached); same allow-list.
- `office_no_markdown` — empty-state with a context-aware
  message ("Queued for conversion" / "Previous attempt
  failed" / "Skipped" / "No bulk_files row")
- `archive` — sortable table of entries with size + modified
  columns
- `unknown` — metadata + Download button only

Sibling navigation:
- ← Prev / Next → buttons in the sidebar
- Clickable sibling list (capped at 200, with truncation
  indicator)
- ← / → keyboard shortcuts when focus isn't in an input
- Esc jumps to Pipeline Files filtered to the parent

Action buttons:
- Download (direct file)
- Open in new tab
- Copy path (Clipboard API + execCommand fallback)
- Show in folder (`/static/pipeline-files.html?folder=`)
- View converted → (only when bulk_files.status == 'success')
- Re-analyze (only when analysis_queue row exists; uses the
  v0.31.0 delete-and-re-insert endpoint)

Browser back/forward navigation supported via `popstate`
listener — the URL is mutated via `history.pushState()` on
sibling-link clicks rather than full reloads, so navigation
within a folder is instant.

### Pipeline Files `?folder=` filter

`static/pipeline-files.html` now honors a `?folder=<absolute
path>` query parameter. On page load, the search input is
pre-filled with the folder path and `searchQuery` is set so
the existing substring-match filter naturally selects every
file under that directory. If no status chip is pre-selected,
defaults to `scanned` so the operator sees results rather than
the empty-state prompt.

### Side polish — Batch Management page

Three additions on `static/batch-management.html`:

- **Page-size dropdown** with options 10 / 30 / 50 / 100 /
  All. Defaults to 30; persists to localStorage under
  `markflow.batch-management.pageSize.v1`.
- **Expand all / Collapse all** toggle button. Detects current
  state (any cards collapsed → expand all; all open →
  collapse all). The expand path simulates header clicks so
  lazy-loading of file lists fires; the collapse path just
  removes the `.open` class.
- **Pagination footer** with `← Prev` / `Next →` buttons and a
  "Showing 1-30 of 247 batches" indicator.

The `loadBatches` function was refactored: it now stores the
full list in a closure variable `allBatches` and calls
`renderBatchesPage()` to slice + render. Page-size changes and
pagination clicks just call `renderBatchesPage()` with no
re-fetch.

### Files

- `core/version.py` — bump to 0.32.0
- `core/preview_thumbnails.py` (new, ~290 LOC)
- `core/preview_helpers.py` (new, ~190 LOC)
- `api/routes/preview.py` (new, ~580 LOC)
- `api/routes/analysis.py` — thumbnail helpers extracted
  (-160 LOC, +5 import lines)
- `main.py` — register the new preview router
- `static/preview.html` — full rewrite (~770 LOC, was 19)
- `static/pipeline-files.html` — `?folder=` query param
  honored (~25 LOC)
- `static/batch-management.html` — page-size dropdown,
  Expand/Collapse-all toggle, pagination footer
  (~120 LOC additions)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

### Acceptance verification

Per the plan's acceptance criteria:
- ✅ Click folder icon on a Pipeline Files row → preview.html
  opens in new tab with `?path=<container path>`
- ✅ Audio / video rows show players with seek (HTTP range
  works through FileResponse)
- ✅ Image rows show the file at full size, with auto-fallback
  to /thumbnail for non-native formats
- ✅ PDF rows show the browser's built-in PDF viewer
- ✅ Text rows show first 64 KB with truncation indicator
- ✅ Converted Office docs show the rendered Markdown inline
  AND link to viewer.html
- ✅ Unconverted Office docs show context-aware empty state
- ✅ Archives show entry table (zip / tar / 7z)
- ✅ Sidebar metadata reflects file stats + DB rows + flags
- ✅ Action buttons work (Download streams, Copy path
  copies, Show in folder navigates with `?folder=`)
- ✅ ← / → / Esc keyboard nav
- ✅ `?path=/etc/passwd` returns 400 (path-traversal guard)

### Late additions: force-process button + related-files context surface + staleness banner

After the initial preview-page implementation landed, four
follow-up surfaces shipped under the same v0.32.0 cut. The
force-process button addresses "I see this file is stuck in
pending — make it process NOW." The related-files / search /
selection-chip surface addresses "while I'm looking at this
file, find me other files like it without losing my place."
The staleness banner addresses "I came back to this tab and
something looks different." And the missing-file UX fix
addresses raw `{"detail":"file not found"}` JSON greeting
operators who clicked "Open in new tab" on a stale registry row.

#### Force-process button (file-aware)

A single button kicks off the full pipeline for one file:
removes it from `pending` / `failed` / `batched` state, runs the
appropriate engine (Whisper / converter / LLM vision), writes
the output to the configured directory, and reindexes — without
forcing the operator to wait for the next pipeline tick.

`core.preview_helpers.pick_action_for_path(p)` returns one of:

- `transcribe` for audio / video → button label "🎙 Transcribe"
- `convert` for office / pdf / text / archive → button label "⚙ Process"
- `analyze` for any preview-eligible image → button label "🔍 Analyze"
- `none` — button hidden (unsupported format)

The button is also hidden when `info.exists=false` (no point
showing the action for a file MarkFlow can't read).

Backend endpoints:

`POST /api/preview/force-action` (OPERATOR+):
- Body: `{"path": "<absolute container path>"}`
- For `transcribe` / `convert`: upserts a `bulk_files` row
  (status=`pending`), calls `_convert_one_pending_file()` from
  v0.31.6 (so output mapping, write-guard, and indexing all
  reuse the proven path).
- For `analyze`: calls `enqueue_for_analysis(...)`, then
  forces a `run_analysis_drain()` so the LLM call goes out
  within the current request rather than waiting up to 5
  minutes for the scheduled tick.
- 409 if a prior run is still in-flight for this path.
- Returns `{path, action, state: "queued", message}`; work
  runs in a `BackgroundTask`.

`GET /api/preview/force-action-status?path=<>`:
- Returns the in-memory progress record:
  `{state, phase, action, started_at, updated_at, finished_at,
  elapsed_ms, error, output_path}`
- `state` is one of `idle / queued / preparing / running /
  indexing / success / failed`.
- Process-local — resets on container restart.

Frontend progress UI: clicking the button slides in an inline
progress card under the action buttons with spinner + phase
label + live elapsed-time ticker (decoupled from the 2 s
HTTP poll cadence). On success the card turns green, the
output path appears, and the page re-fetches `/info` so the
sidebar Conversion / Analysis cards repopulate. The audio
viewer additionally appends a transcript pane below the
`<audio>` element on success — same endpoint
(`/api/preview/markdown-output`) the office_with_markdown
viewer uses.

#### Related Files + typed-search panel + selection chip

Three search surfaces on the preview page, all backed by the
new `GET /api/preview/related` endpoint:

1. **Auto-populated Related Files card** — fires on every
   page load with `mode=semantic` by default. Tabs flip to
   `keyword` (Meili). Backend derives the query when `q` is
   empty via this priority: converted-Markdown excerpt
   (first 1000 chars) → analysis description → filename
   stem + parent dir name.
2. **Typed-query Search panel** — `<input>` + mode `<select>` +
   "🤖 AI Assist ↗" deep-link to `/search.html?q=…&ai=1` in a
   new tab. AI Assist deliberately does NOT auto-fire (would
   burn LLM tokens on every preview page open).
3. **Highlight-to-search chip** — `mouseup` inside the viewer /
   transcript pane / analysis description / related-list pops
   a floating chip with `[🧠 Semantic | 🔎 Keyword | 🤖 AI ↗]`.
   Position is computed from
   `getBoundingClientRect()`, flips below if too close to the
   viewport top. Auto-hides on `mousedown` outside, `Escape`,
   scroll, or resize.

`GET /api/preview/related` parameters:
- `path` (required), `mode` (`keyword`|`semantic`, default `semantic`)
- `q` (optional override — backend auto-derives when empty)
- `limit` (1–25, default 10)

Returns `{path, mode, query_used, derived, results, warning}`.
Vector results use `source_path` from the Qdrant payload
directly — no Meili roundtrip.

#### Staleness banner (`info_version` + visibilitychange)

`/api/preview/info` now returns `info_version` — a 16-char
SHA256 prefix of the fields that an operator would notice
changing: `(size, mtime, viewer_kind, conv.status,
conv.converted_at, conv.output_path, analysis.status,
analysis.analyzed_at, analysis.description[:64], len(flags))`.

Frontend stores `info_version` on initial load. On
`visibilitychange` (tab focus) it re-fetches `/info` and
compares; if the version changed, it re-renders + surfaces
a blue banner: *"This file changed while you were away —
page refreshed with the latest data."* Auto-dismisses after
12 s. Suppressed during force-action polling so we don't
show it for our own work-in-progress.

#### Better error UX on missing files

Two-layer fix for "Open in new tab on a stale registry row
returns raw JSON":

- **Frontend** — when `info.exists=false`, Download / Open-in-
  new-tab render as `<button disabled>` with a tooltip
  *"File not found on disk — cannot serve content"*. Operator
  never reaches the endpoint.
- **Backend** — `/api/preview/content` sniffs `Accept: text/html`.
  Browser navigations get a styled HTML 404 page with the
  path, the failure reason, and links back to the preview
  page + Pipeline Files. Media-element / fetch consumers still
  get the original JSON 404 so `<img onerror>` fallback paths
  in the page itself stay intact.

#### Side fix: quiet shutdown for the lifecycle scan

`core/scheduler.py:run_lifecycle_scan()` wrapped its body in
`try / except Exception`. When the container received SIGTERM
mid-scan, the asyncio task got cancelled while awaiting
`aiosqlite.connect.__aexit__()` inside
`mark_file_for_deletion → update_source_file → get_db()`, and
the resulting `CancelledError` slipped past the broad
`except Exception` (it inherits from `BaseException` in Python
3.8+), surfacing inside apscheduler as a job-raised-exception
traceback in `markflow.log` on every clean restart.

Fix: explicit `except asyncio.CancelledError` clause that logs
`scheduler.scan_cancelled_on_shutdown` at info level and
returns. Cancellation has already done its job — the next
scheduled interval picks up the work.

#### Side cleanup: stale `db-*.log` files removed

`core/db/contention_logger.py` was retired in v0.24.2 but its
three temp files sat untouched on disk:

| File | Size | Last write |
|------|------|-----------|
| `db-contention.log` | 375 MB | 2026-04-23 20:13 |
| `db-queries.log`    | 272 MB | 2026-04-23 19:32 |
| `db-active.log`     |  15 MB | 2026-04-23 20:13 |

Total: 662 MB stale on disk. Removed during this release.

#### API quick-reference

```bash
# File-aware force-process
curl -sX POST http://localhost:8000/api/preview/force-action \
  -H 'Content-Type: application/json' \
  -d '{"path":"/host/c/Audio/meeting04.mp3"}'

# Poll progress (poll every ~2s while in-flight)
curl -s 'http://localhost:8000/api/preview/force-action-status?path=/host/c/Audio/meeting04.mp3'

# Find related (semantic, query auto-derived from file)
curl -s 'http://localhost:8000/api/preview/related?path=/host/c/Audio/meeting04.mp3&mode=semantic&limit=10'

# Find related (keyword override)
curl -s 'http://localhost:8000/api/preview/related?path=/host/c/Audio/meeting04.mp3&mode=keyword&q=union+meeting+resolution&limit=5'

# /info now includes action + info_version
curl -s 'http://localhost:8000/api/preview/info?path=/host/c/Audio/meeting04.mp3' | jq '{action, info_version, viewer_kind, exists}'
```

#### Late-addition file changes

New: none beyond what was listed above (`preview.py`,
`preview_helpers.py`, `preview_thumbnails.py`).

Modified additionally:
- `api/routes/preview.py` — force-action endpoints + state
  tracker (~210 LOC), `/related` endpoint (~150 LOC),
  `info_version` etag, friendly HTML 404 for browser hits on
  missing-file content (~80 LOC)
- `core/preview_helpers.py` — `pick_action_for_path()` +
  `ACTION_*` constants (~70 LOC)
- `core/scheduler.py` — `import asyncio` + new
  `except asyncio.CancelledError` clause in `run_lifecycle_scan`
- `static/preview.html` — force-action button + progress card +
  Related/Search sidebar cards + selection chip + staleness
  banner + audio transcript pane (~750 LOC of CSS + HTML + JS,
  bringing the file to ~2050 LOC)
- `CLAUDE.md`, `docs/help/whats-new.md`,
  `docs/help/preview-page.md` (new),
  `docs/help/_index.json`, `docs/help/keyboard-shortcuts.md`,
  `docs/key-files.md`, `docs/version-history.md`

Removed:
- `/app/logs/db-{contention,queries,active}.log` — 662 MB
  stale instrumentation, side cleanup

No DB migration. No new dependencies. No new scheduler jobs.

---

## v0.31.6 — Selective conversion of pending files (2026-04-27)

**New "Convert Selected (N)" / "Retry Selected (N)" workflow on
the History page's Pending Files section. Operators can hand-pick
a subset of pending files for immediate conversion instead of
committing to the full pipeline run via Force Transcribe.**

### The user need

The Pending Files card surfaces every `bulk_files` row with
`status='pending'` or `'failed'` — currently 113,354 entries on
the production instance. The existing **Force Transcribe /
Convert Pending** button hits `/api/pipeline/run-now` which
processes ALL of them in one sweep. Operators wanted to **test a
specific handful of files** (a few MP3s, one problematic PDF)
without committing to the full sweep, especially because audio
and video files take minutes each via Whisper.

### Frontend (`static/history.html`)

- **Checkbox column** added to the pending files table:
  - Header has a select-all checkbox (toggles current page
    only, not all 113k).
  - Rows have per-file checkboxes bound to `bulk_files.id`.
  - Indeterminate state on select-all when partial-page
    selection.
- **Bulk-action bar** (`#pending-bulk-bar`) appears when ≥1 row
  is checked:
  - "N selected" count
  - Context summary: "3× .mp3, 1× .pdf · 287.5 MB total"
    (top-3 file types, total uncompressed size)
  - Cap warning if N > 100 (matches backend
    `_CONVERT_SELECTED_MAX`); button disabled with tooltip
    "Untick some rows or use Force Transcribe..."
  - Convert/Retry button — verb switches based on the
    status-filter dropdown:
    - `pending` → "Convert Selected (N)"
    - `failed` → "Retry Selected (N)"
  - Clear selection button
- **Selection persistence**:
  - In-memory `Set<string>` of `bulk_files.id` values.
  - Survives pagination — selecting rows on page 1, navigating
    to page 2, and back to page 1 restores the checkboxes.
  - **Cleared on status filter switch** (pending↔failed) since
    the eligibility set differs.
- **`updatePendingBulkBar()`** computes the summary from a
  cached `pendingSelectedFiles` map. For ids selected via
  select-all on a page rendered earlier (and now off-screen),
  a stub `{id}` entry is created so the count stays correct
  even if size data isn't available.
- **`syncSelectAllState()`** computes the indeterminate state
  by counting checked rows vs. total visible rows.
- After every `loadPending()` re-render, `syncSelectAllState`
  + `updatePendingBulkBar` run to restore visual state from
  the persistent Set.
- Click handler on **Convert Selected**:
  - Confirmation prompt: "Schedule N selected files for
    immediate convert? They will run with up to 4 concurrent
    workers; large media files (audio/video) may take minutes
    each."
  - POST `/api/pipeline/convert-selected` with `{file_ids: [...]}`.
  - Toast on success with included/skipped counts.
  - Auto-clears selection and refreshes the pending list after
    a 2-second delay.

### Backend (`api/routes/pipeline.py`)

`POST /api/pipeline/convert-selected` (OPERATOR+):

- **Pydantic body** `ConvertSelectedRequest`:
  ```python
  class ConvertSelectedRequest(BaseModel):
      file_ids: list[str] = Field(
          ..., min_length=1, max_length=100,
          description="bulk_files.id values to schedule",
      )
  ```
- **Validation**: each id is looked up in `bulk_files`. Misses
  go into `not_found`; rows whose status isn't in
  `{pending, failed, adobe_failed}` go into `ineligible`.
- **400 only when nothing eligible**. Mixed selections (some
  resolved + some not) succeed with the issues surfaced in
  the response.
- **Background batch**: schedules a `_run_convert_selected_batch`
  task that runs conversions concurrently with
  `asyncio.Semaphore(4)` — matches the default
  `BULK_WORKER_COUNT`. Per-file exceptions are caught + logged
  + recorded on the row, never abort the whole batch.
- **Per-file conversion** (`_convert_one_pending_file`):
  - Resolves output dir from
    `core.storage_manager.get_output_path()` (the same Storage
    Manager-configured root the pipeline uses); falls back to
    `/mnt/output-repo` if the operator hasn't set one yet.
  - Reconstructs the source root by walking up the path
    until one of the standard mount roots matches:
    `/mnt/source`, `/host/c`, `/host/d`, `/host/rw`,
    `/host/root`. Falls back to `source_path.parent` if no
    match (the converter still works; output just lands
    directly under output_root rather than mirroring the tree).
  - Uses `core.db.bulk._map_output_path` to compute the
    per-file destination, mirroring
    `BulkJob._process_convertible`.
  - Honors `core.storage_manager.is_write_allowed()` write
    guard.
  - Calls `core.converter._convert_file_sync` in a worker
    thread (`asyncio.to_thread`).
  - On success: updates `bulk_files` with status='converted',
    output_path, converted_at, content_hash (sha256 of
    output file), and clears `error_msg`. Routed through
    `db_write_with_retry` to ride out single-writer DB
    contention.
  - On failure: updates status='failed' with error_msg.
- Returns immediately with
  `{queued, not_found, ineligible, message}`. The frontend's
  existing 30-second pending-list refresh picks up the row
  transitions; no SSE / push needed for a workflow this
  short-lived.

### Logging events

- `convert_selected.scheduled` — request received, batch queued
- `convert_selected.start` — per-file conversion starting
- `convert_selected.success` — per-file conversion completed
  with output_path
- `convert_selected.failed` — per-file conversion returned
  non-success status
- `convert_selected.exception` — per-file conversion threw
- `convert_selected.write_denied` — output dir failed
  `is_write_allowed` check
- `convert_selected.mkdir_failed` — output dir mkdir raised
  OSError
- `convert_selected.batch_complete` — whole batch finished

### Files

- `core/version.py` — bump to 0.31.6
- `api/routes/pipeline.py` — `ConvertSelectedRequest`,
  `convert_selected_files` endpoint, `_convert_one_pending_file`
  + `_run_convert_selected_batch` helpers (~210 LOC)
- `static/history.html` — checkbox column, bulk-action bar,
  selection state Set, all handlers (~150 LOC)
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

### Acceptance

- Pending Files table renders a checkbox column on every row.
- Checking 3 rows surfaces a "3 selected · 3× .mp3 · 287 MB
  total" bulk bar.
- Switching the status filter from Pending to Failed clears the
  selection.
- Click "Convert Selected (3)" → confirm → toast "Scheduled 3
  files for conversion" → table auto-refreshes within ~30 s
  showing the rows transitioning out of pending.
- Selecting 101 rows shows the cap warning and disables the
  Convert button.
- Backend rejects an all-ineligible selection with HTTP 400
  carrying `{not_found, ineligible, eligible_statuses}`.
- Backend accepts mixed (eligible + missing) selections and
  surfaces the missing ids in the response.

### Risks

- **Concurrent run-now / bulk job collision**: if the operator
  triggers Convert Selected while a bulk job is already running,
  both pipelines try to update the same `bulk_files` rows. The
  bulk job's row claim happens via `claim_pending_files`
  (atomic UPDATE on status), so only one of the two would
  succeed in claiming any given row — the other gets a no-op
  rowcount and effectively skips. Acceptable; shouldn't
  duplicate work.
- **Whisper concurrency**: Whisper transcription is GPU-bound
  (or thread-bound on CPU) and serialized via the existing
  `whisper_transcriber.py` lock from v0.24.2. Selecting 4
  audio files schedules 4 conversions; 3 of them block waiting
  for the lock. Total wall time is roughly the sum of
  transcription times. Acceptable.
- **Output write contention**: same write-guard rules apply.
  If the Storage Manager output root is on a slow SMB share,
  operators see throughput limited by the share. No different
  from the bulk-job path.

---

## v0.31.5 — Preview format expansion + dynamic ETA framework (2026-04-27)

Two-item bundle release that closes out the v0.31.x roadmap.
Folds in both the **v0.31.3** roadmap item (preview format
expansion: HEIC, RAW, SVG) and the **v0.31.5** roadmap item
(system spec polling + dynamic ETA framework) into a single
release.

### Numbering note

The roadmap (`docs/superpowers/plans/2026-04-25-v0.31.x-roadmap.md`)
suggested numbering preview formats as v0.31.3 and the ETA
framework as v0.31.5 as separate releases. Since v0.31.4 (the
server-side ZIP bundle) shipped first chronologically, going
back to v0.31.3 would have been a regression in
`core/version.py`. We bundled both remaining items into v0.31.5
to keep version numbers monotonic.

### Item 1 — Preview format expansion (was roadmap v0.31.3)

The hover preview on Batch Management already covered 37
extensions across browser-native and PIL-thumbnailed buckets
(v0.29.7-v0.29.8). v0.31.5 adds three more buckets:

#### HEIC / HEIF / HEICS / HEIFS

Modern phone-camera default (iOS, recent Android). The pip dep
`pillow-heif` was already in `requirements.txt` from a prior
release but never wired up. v0.31.5 actually USES it:

```python
try:
    import pillow_heif as _pillow_heif
    _pillow_heif.register_heif_opener()
except Exception as _exc:
    log.warning("preview.pillow_heif_unavailable", error=...)
```

Once the opener is registered at module load, HEIC files flow
through the same `_generate_thumbnail_sync` PIL path as TIFF /
PSD / etc. — no new code path. The container's apt packages
already include `libheif1` runtime (pillow-heif's wheels bundle
it on Debian Trixie / x86_64).

#### RAW camera formats

~30 extensions across the major camera vendors:

- **Canon**: `.cr2`, `.cr3`, `.crw`
- **Nikon**: `.nef`, `.nrw`
- **Sony**: `.arw`, `.srf`, `.sr2`
- **Fuji / Olympus / Panasonic / Pentax / Samsung**:
  `.raf`, `.orf`, `.rw2`, `.pef`, `.srw`
- **Adobe Digital Negative** (cross-vendor open standard):
  `.dng`
- **Kodak / Sigma / Hasselblad / Leica / Mamiya / Phase One /
  Epson**: `.kdc`, `.dcr`, `.x3f`, `.3fr`, `.fff`, `.mef`,
  `.mos`, `.raw`, `.rwl`, `.erf`

Decoded via `rawpy` (LibRaw bindings). Wheels ship LibRaw, so
no apt deps needed. New helper
`_generate_raw_thumbnail_sync(path)`:

1. Try `raw.extract_thumb()` — most RAW files carry an
   embedded JPEG preview (160-1600 px on the longest edge).
   Returns the JPEG bytes wrapped in a PIL Image, thumbnailed
   to `_THUMB_MAX_PX` (400 px).
2. If extraction returns a bitmap thumb instead of a JPEG
   thumb, the `numpy` array becomes a PIL Image and goes
   through the same thumbnail path.
3. If extraction fails (older RAW format with no embedded
   preview), fall back to `raw.postprocess(half_size=True)`
   — half-size demosaic skips the bayer interpolation cost,
   which is ~50× faster than full resolution. Still slower
   than embedded-JPEG extraction, but acceptable for a
   preview hover.

#### SVG / SVGZ

Rasterized server-side via `cairosvg` (uses the `libcairo2`
already in the container via WeasyPrint — no new apt
dependency). New helper `_generate_svg_thumbnail_sync(path)`:

```python
png_bytes = cairosvg.svg2png(
    url=str(path),
    output_width=_THUMB_MAX_PX,
)
# … then PIL.Image.open(BytesIO(png_bytes)) → JPEG output
```

**Security note**: the response body is raster pixels, NOT
the original SVG document. Any embedded `<script>` / event
handlers / external `<image>` references are inert by the
time bytes reach the browser. We never serve the SVG verbatim
through the preview endpoint, so XSS surface is zero. The
output dimensions are also capped at 400 px regardless of the
SVG's intrinsic size, which prevents "billion-laughs" style
expansion attacks from blowing up the thumbnail buffer.

#### Frontend

`_IMG_EXT` set in `static/batch-management.html` is updated to
match the new server-side coverage so hover previews fire on
HEIC / RAW / SVG files.

### Item 2 — Dynamic ETA framework (was roadmap v0.31.5)

New module `core/eta_estimator.py` (~250 LOC). Records
observations of the form `(operation, scope_size, wall_seconds)`
and answers "given an upcoming operation of size N, how long
is it likely to take?" using an exponentially-weighted moving
average (EWMA, α=0.3) of throughput.

#### Why EWMA over a fixed-window average

Throughput is heavily influenced by recent disk-cache state, so
the most recent observations are the most predictive. EWMA's
α=0.3 weights the newest reading at 30% and the prior trailing
average at 70% — enough smoothing to swallow outliers, enough
recency to react to drift (HDD cache warm vs cold, container
under heavy bulk load vs idle).

#### Storage

One preference row per operation key, named
`eta_observations__<sanitized op>`. JSON-encoded blob per row:

```json
{
  "count": 47,
  "throughput_ewma": 8523.4,
  "last_throughput": 9120.1,
  "last_observed_at": 1745740432.5,
  "history": [{"scope_size": 50000, "wall_seconds": 5.8, ...}, ...]
}
```

The history array is bounded at 200 entries — enough for the
diagnostic tail-20 view, capped to keep the row at ~10 KB.

#### Cold-start gate

`estimate()` returns `None` until `_MIN_OBSERVATIONS = 3`.
Below that, the UI shows nothing rather than a confidently
wrong prediction. After 3 obs, the estimate has confidence
"low"; the UI says "estimated ~X" with the squiggle. After
10 obs, "medium" — drops the squiggle. After 50, "high" —
phrasing softens to "expected X."

#### System-spec snapshot

New scheduler job `eta_system_spec_snapshot` (job count 18→19),
runs every 24 hours via `IntervalTrigger(hours=24)`. Captures
host CPU / RAM / load via the existing
`core.log_manager.get_system_resource_snapshot` helper (which
reads `/proc/cpuinfo`, `/proc/meminfo`, `os.getloadavg()`),
appends to `preferences['eta_system_spec_history']`, capped at
90 entries (~3 months of daily snapshots). Best-effort: a
`/proc` read failure on one field doesn't abort the snapshot,
just leaves the field as `None`.

The framework doesn't currently USE the spec history for ETA
calculation — it's recorded so future improvements can detect
hardware drift (e.g. fall back to a fresh EWMA if RAM doubled
between snapshots, suggesting a hardware upgrade).

#### First wired-up operation: log-history search

`/api/logs/search` now records observations bucketed by archive
format:

- `log_search_plain` — uncompressed `.log`
- `log_search_gz` — `.gz` / `.tgz` archives
- `log_search_7z` — `.7z` archives (subprocess decompression
  is much slower per byte, separate bucket avoids polluting
  gzip forecasts)

Observations from cap-truncated searches (line cap or
wall-clock cap fired) are NOT recorded — those would skew the
EWMA toward "infinitely slow" because the wall-time covered
fewer scanned lines than the search would have completed
naturally.

#### UI surface

Log viewer's history-mode controls row gains a new ETA hint
span. `updateEtaHint(name)` fires fire-and-forget at the start
of every history search:

```js
const data = await API.get(
  '/api/logs/eta?name=' + encodeURIComponent(name) +
  '&estimated_scope=100000'
);
```

Reads "ETA: estimated 1.4s (12 prior obs)" or similar; absent
if the estimator hasn't seen enough observations yet for this
file's format bucket.

#### Headless safety

Every method in the estimator is best-effort. Misshaped JSON
in the preference, DB unavailable, math errors all return
`None` rather than raising. Callers should treat ETA as
advisory text, never gate logic on it. The ETA hint update on
the frontend swallows network failures — if the endpoint blips
the hint just clears.

#### Diagnostic endpoints

- `GET /api/logs/eta?name=<file>&estimated_scope=N` (ADMIN+) —
  returns `{op, scope, estimate}`. The UI hint hits this.
- `GET /api/logs/eta/stats?op=<op>` (ADMIN+) — returns recorded
  observation counts + EWMA per known operation key, with a
  trailing-20-entry history sample when an `op` is named.

### Files

- `core/version.py` — bump to 0.31.5
- `core/eta_estimator.py` — NEW (~250 LOC)
- `core/scheduler.py` — registers `eta_system_spec_snapshot`
  daily job (count 18→19)
- `api/routes/log_management.py` — search endpoint records
  observations on success; new `/eta` and `/eta/stats`
  endpoints
- `api/routes/analysis.py` — preview endpoint dispatches to
  `_generate_raw_thumbnail_sync` (rawpy) and
  `_generate_svg_thumbnail_sync` (cairosvg); registers
  pillow-heif opener at module load; expanded preview
  extension sets (`_THUMBNAIL_PREVIEW_EXTS` adds HEIC family;
  new `_RAW_PREVIEW_EXTS` and `_SVG_PREVIEW_EXTS` sets)
- `requirements.txt` — adds `rawpy`, `cairosvg`
- `static/batch-management.html` — `_IMG_EXT` adds HEIC / RAW /
  SVG extensions
- `static/log-viewer.html` — ETA hint span, `updateEtaHint()`
  helper fires on each search
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. Two new pip dependencies (`rawpy`,
`cairosvg`). One new scheduler job (count 18→19). Lazy imports
for `rawpy` and `cairosvg` (only loaded when their format is
actually previewed) so module-load cost is bounded.

### Acceptance

- Hover a `.heic` file on Batch Management → preview thumbnail
  shows the photo (was 404 / silent fail before).
- Hover a `.cr2` / `.dng` / etc. → preview shows the embedded
  JPEG thumb (or half-size demosaic for older formats).
- Hover an `.svg` → preview shows the rasterized PNG render;
  inspect the response Content-Type → `image/jpeg` (NOT
  `image/svg+xml`).
- Run a few log searches over a `.gz` archive: the ETA hint
  appears once 3+ observations are on file, reads "estimated
  Xs (3 prior obs)" or higher count.
- Inspect `/api/logs/eta/stats` → returns the observation
  counts + EWMA per operation key.
- Wait 24 h after rebuild: `preferences['eta_system_spec_history']`
  has at least one entry.

---

## v0.31.4 — Server-side ZIP bulk download on Batch Management (2026-04-27)

**Replaces the v0.29.6 sequential per-file synthetic-anchor download
loop with a single streaming ZIP from a new
`POST /api/analysis/files/download-bundle` endpoint.**

### What this fixes

The v0.29.6 multi-file download did a JS for-loop of synthetic
`<a download>` clicks staggered 120 ms apart. Browsers prompted
once for "allow multiple downloads" and then dumped N items into
the browser's download manager. Above 100 files the existing UI
refused entirely, advising the operator to split the selection.
Operators cherry-picking a few hundred files for offline review
had to do the work in three separate rounds.

v0.31.4 replaces that loop with one POST. The server packages
the files into a ZIP in a worker thread (`asyncio.to_thread`),
streams the bytes back, and the browser sees a single
`markflow-files-<TS>.zip` download.

### Backend (`api/routes/analysis.py`)

`POST /api/analysis/files/download-bundle` (OPERATOR+):

- **`BundleDownloadRequest`** Pydantic body with
  `file_ids: list[str]` (1-500 entries enforced via Pydantic
  `min_length`/`max_length`) and optional `bundle_name: str`
  (max 120 chars, sanitized for filename safety — only
  alphanumerics, `.`, `-`, `_`, space; spaces collapse to
  underscores; truncated to 80 chars).
- Pre-flight: each id resolves through the existing
  `_lookup_source_path` helper. Missing or unsafe ids are
  silently skipped (mirrors the log-management bundle pattern).
  Total uncompressed bytes tallied as we go.
- **Hard cap of ~2 GiB uncompressed**
  (`_BUNDLE_MAX_UNCOMPRESSED_BYTES = 2 * 1024**3`). When the
  running total crosses the cap, returns HTTP 413 with a
  specific "split into smaller batches" message. The 500-file
  Pydantic ceiling is the other edge — whichever fires first.
- **`_ALREADY_COMPRESSED_EXTS` set** (JPEG/PNG/GIF/WebP/AVIF
  family, MP3/M4A/AAC/OGG/Opus/FLAC, MP4/MOV/MKV/AVI/WMV/WebM,
  ZIP/GZ/TGZ/BZ2/XZ/7Z/RAR, DOCX/XLSX/PPTX/ODT/ODS/ODP/EPUB,
  PDF) gets `ZIP_STORED` mode. Other extensions use
  `ZIP_DEFLATED`. Skips wasted CPU re-compressing
  entropy-saturated bytes.
- **Duplicate-arcname disambiguation**: two files with the same
  basename get `_1`, `_2` suffixes inside the ZIP so nothing
  silently overwrites.
- **Partial-bundle resilience**: per-file `OSError` during
  `zipfile.write()` is logged via
  `analysis.bundle_file_failed` + skipped. Operator gets a
  partial bundle rather than a 500.
- **Response headers** surface the result:
  `X-MarkFlow-Bundle-Files-Included`,
  `X-MarkFlow-Bundle-Files-Skipped`. UI parses these for the
  toast message.
- 404 only if EVERY id was missing/unsafe (no files survived
  the pre-flight).

### Frontend (`static/batch-management.html`)

- `DOWNLOAD_ALL_CAP` raised from 100 to 500 to match the
  server.
- `DOWNLOAD_STAGGER_MS` removed (not needed for one POST).
- Sequential synthetic-anchor loop replaced by a single
  `fetch()` to `/api/analysis/files/download-bundle` with
  `credentials: 'same-origin'`. Response blob → `URL.createObjectURL`
  → `<a download>` click → revoke. Filename comes from the
  response's `Content-Disposition`.
- **Single-file fast path**: if exactly 1 file is selected,
  skip the bundle endpoint entirely — go straight to the
  existing direct `/files/{id}/download` URL. Faster, no
  zipping, no Content-Length-Unknown delay.
- Toast surfaces `included` + `skipped` counts.
- Errors (4xx/5xx, network failures) surface via `showError()`
  with the response body for context.

### Operational

- `.dockerignore` updated to exclude `backups/`,
  `hashcat-queue/`, `.claude/`. The `backups/` exclusion alone
  cut the build context from 4.7 GB to ~150 MB on this host —
  necessary so `--no-cache` rebuilds finish in reasonable time.

### Files

- `core/version.py` — bump to 0.31.4
- `api/routes/analysis.py` — `BundleDownloadRequest`,
  `download_files_bundle`, `_BUNDLE_MAX_FILES`,
  `_BUNDLE_MAX_UNCOMPRESSED_BYTES`, `_ALREADY_COMPRESSED_EXTS`
- `static/batch-management.html` — bundle fetch path replaces
  the synthetic-anchor loop; cap raised to 500
- `.dockerignore`
- `CLAUDE.md`, `docs/version-history.md`,
  `docs/help/whats-new.md`

No DB migration. No new dependencies. No new scheduler jobs.

### Acceptance

- Selecting 1 file and clicking "Download Selected" triggers
  the existing direct-download URL (no bundle endpoint hit).
- Selecting 5+ files triggers `POST /download-bundle`,
  returns a single ZIP with all 5 files inside, browser shows
  one item in the download manager.
- Selecting 600 files: client-side message
  ("Too many files selected (600). Please select 500 or fewer
  at a time.")
- Selecting 500 files totaling > 2 GiB on disk: server returns
  HTTP 413 with split-into-batches message; surfaced as a
  toast/error on the page.
- Bundle with 1 deleted file in the selection: included count
  is N-1, skipped count is 1 in the response headers; toast
  reads "Downloaded bundle of N-1 files (1 skipped — missing
  or unreadable)".

---

## v0.31.2 — Multi-provider 5-layer vision-API resilience (2026-04-25)

**Ports the v0.29.9 Anthropic-only resilience pipeline to
OpenAI, Gemini, and Ollama. Every operator now gets the same
financial protection against wasted vision-API spend regardless
of which provider they've activated.**

### Background

v0.29.9 shipped a five-layer defense pipeline (preflight
validation, exponential backoff with Retry-After, per-image
bisection on 400, circuit breaker, operator banner) on Anthropic
vision calls. The roadmap explicitly noted that the helpers
(`_parse_retry_after`, `_backoff_delay`, `_safe_body`) and the
circuit-breaker module were provider-agnostic — porting the
pattern to the other three providers was a follow-up.

v0.31.0 ported the *filename interleaving* prompt improvement
to OpenAI / Gemini / Ollama. This release ports the resilience
machinery.

### What landed

For each of OpenAI, Gemini, and Ollama:

1. `_batch_<provider>` was rewritten to do the same per-image
   read + compress + preflight + sub-batch-planning loop as
   `_batch_anthropic`. Pre-flight failures get reserved a solo
   sub-batch slot so the per-image error surfaces cleanly.
2. New `_<provider>_sub_batch` helper that mirrors
   `_anthropic_sub_batch`: circuit-breaker gate, retry loop
   (4 attempts) with backoff + Retry-After honored on
   429/5xx/529, recursive bisection on 400, non-retryable
   classification on other 4xx, success path with token
   counting and JSON-array parse.
3. Provider-specific quirks preserved:
   - **OpenAI**: chat-completions payload, Bearer auth header,
     `data["choices"][0]["message"]["content"]` parse, 18 MB
     request budget per `_PROVIDER_LIMITS`.
   - **Gemini**: `generateContent` URL, API key in query
     param, `parts` array structure, joined `text` from
     `candidates[].content.parts[]`, `usageMetadata` token
     accounting, 18 MB budget.
   - **Ollama**: `/api/generate` with prompt + images array
     (no per-image text blocks — filenames prepended to the
     prompt instead, same shape as v0.31.0), 50 MB budget
     because the workload is local.

### Ollama-specific fallback preserved

Ollama's existing "if all results fail, fall back to sequential
`describe_frame` calls" path was rewritten to trigger only when
ALL non-preflight images came back with the marker error
`"failed to parse LLM response"`. That marker is the parser's
signal that the model spoke but didn't produce a JSON array —
typically a model that doesn't grok the multi-image-batch
prompt. Bisection on 400 already covers the "model rejects
multi-image" HTTP case; the parser-failure fallback covers the
"model returns garbled prose" case where bisection wouldn't
help (because the per-image solo call would also produce prose,
just shorter).

### Cross-provider breaker semantics

The circuit breaker module (`core/vision_circuit_breaker.py`)
is process-wide and provider-agnostic. A 429 storm hitting
OpenAI will trip the breaker for Anthropic / Gemini calls too.
This is by design:

- Operators run one active provider at a time. During
  steady-state operation, breaker state for that provider is
  what we care about.
- If the operator is mid-experiment switching providers, a
  breaker tripped by the previous provider's failures
  fail-fast on the new provider's first call, which is
  appropriate caution — the operator can manually Reset from
  the banner if they want to bypass the cooldown.
- The cooldown (60s → 2min → 4min → 8min, cap 15min) is
  short enough that a stale-tripped breaker doesn't
  permanently block experimentation.

### Files

- `core/version.py` — bump to 0.31.2
- `core/vision_adapter.py` — three batch functions rewritten +
  three new sub-batch helpers (~600 LOC additions, ~150 LOC
  removals net of the simpler old code)
- `CLAUDE.md` — Current Version block; v0.31.1 demoted to
  summary
- `docs/version-history.md` — this entry
- `docs/help/whats-new.md` — user-visible bullet with
  example failure scenarios
- `docs/help/llm-providers.md` — new "Resilience and reliability"
  section explaining the 5 layers in user-facing terms

No DB migration. No new dependencies. No new scheduler jobs.
No frontend changes — the operator banner that polls
`/api/analysis/circuit-breaker` was already provider-agnostic
because the breaker module never had per-provider state.

---

## v0.31.1 — `.7z` viewer safety controls + system-resource snapshot (2026-04-25)

Operator-tunable byte cap on `.7z` log search, a host CPU/RAM/load
snapshot panel right next to the cap, and a live spinner + ticking
elapsed time on the log viewer's history search while a request
is in flight.

The v0.31.0 release made `.7z` archives readable via a `7z e -so`
subprocess wrapper with a hardcoded 200 MB per-reader byte cap.
v0.31.1 surfaces that cap to operators (so they can size it for
their hardware), shows them what hardware the container is
actually running on, and gives them a visible "yes, work is
happening" signal during the multi-second searches a `.7z` can
produce.

Plan executed:
[`docs/superpowers/plans/2026-04-25-v0.31.0-7z-safety-controls.md`](superpowers/plans/2026-04-25-v0.31.0-7z-safety-controls.md).
The "v0.31.0" prefix in the plan filename is historical — the
plan was written during the v0.31.0 session but scoped out to a
follow-up, which became this release.

### Item A — User-tunable `.7z` byte cap

`core/log_manager.py`:
- New constant `PREF_SEVEN_Z_MAX_MB = "log_seven_z_max_mb"`.
- `DEFAULT_SEVEN_Z_MAX_MB = 200` (matches the prior hardcoded
  value so existing deployments see no behavioral change).
- `SEVEN_Z_WARN_THRESHOLD_MB = 1024` (UI shows amber).
- `SEVEN_Z_HARD_MAX_MB = 4096` (backend rejects above this).
- `get_seven_z_max_mb()` reads + clamps. Out-of-range, missing,
  or non-numeric values fall back to the default — so a corrupted
  pref can never accidentally lift the cap.
- `get_settings()` returns `seven_z_max_mb`, `seven_z_warn_threshold_mb`,
  and `seven_z_hard_max_mb` so the UI can render warnings without
  hardcoding the same constants.
- `set_settings(... seven_z_max_mb=)` persists the new value;
  validation error is a clean `ValueError` that the route surfaces
  as HTTP 400.

`api/routes/log_management.py`:
- `SettingsUpdate.seven_z_max_mb: int | None = Field(None, ge=1, le=SEVEN_Z_HARD_MAX_MB)`.
- `_SevenZReader.__init__(path, max_bytes=None)`. The legacy
  module-level `_SEVENZ_DEFAULT_MAX_BYTES` (renamed from
  `_SEVENZ_MAX_BYTES`) remains as the fallback so any new call
  site that forgets to pass `max_bytes` still gets a safety cap.
- `_check_cap` and `read` now reference `self._max_bytes` instead
  of the module constant — every reader carries its own cap.
- The async `search_log` resolves `seven_z_max_mb` once via
  `await get_seven_z_max_mb()` BEFORE entering the worker thread
  (the thread can't `await`), then closure-captures the byte
  budget into `_do_search`.
- The reader-truncation warning string now reads
  `f"7z stream truncated at {seven_z_max_mb} MB"` using the
  actual operator-configured value.

### Item B — Host resource snapshot

`get_system_resource_snapshot()` is a synchronous best-effort
read of:
- `/proc/cpuinfo` "model name" line → `cpu_model`
- `os.cpu_count()` → `cpu_count`
- `/proc/meminfo` MemTotal → `memory_mb_total`
- `/proc/meminfo` MemAvailable (preferred) or MemFree → `memory_mb_free`
- `os.getloadavg()` → `load_1min`, `load_5min`, `load_15min`

Each field returns `None` on read failure (file missing,
permission denied, parse error) rather than raising. The
container is Debian so the `/proc` paths are correct; the same
helper degrades gracefully on a Windows dev host running pytest
natively (`getloadavg` is POSIX).

The snapshot is one-shot per page load — no caching, no scheduler
job, no historical tracking. The dynamic ETA framework that adds
24-hour spec polling + a benchmark routine is the explicit
follow-up at v0.31.5 in the roadmap.

`get_settings()` includes the snapshot under a `system` sub-dict
so the existing settings GET response is sufficient — no new
endpoint.

### Item C — Live search spinner

The `GET /api/logs/search` endpoint is non-streaming. Until the
v0.31.5 ETA framework lands and converts it to SSE, operators
need some kind of "work is happening" signal during the
multi-second searches a `.7z` archive can produce.

`static/log-viewer.html`:
- New `.lv-spinner` CSS class — `border + animation` rotating
  ring, 0.85 rem, accent-blue top.
- New `<span id="lv-spinner" hidden>` inserted before the existing
  `lv-status` span in the controls row.
- New `startSearchSpinner(label) / stopSearchSpinner()` helpers.
  The start helper sets a `setInterval(tick, 200)` that updates
  `statusEl.textContent` to `"Searching <name> ... 1.4s"` —
  ticking the elapsed time so the operator sees the request is
  actually in flight, not stuck.
- The `runHistorySearch` method captures `startedSpinner =
  (this === activeTab)` BEFORE the await. On response (or error)
  it stops only the spinner it itself started — so if the user
  switches tabs mid-search, neither this tab's nor the new
  active tab's spinner state gets corrupted.

### Frontend — Settings page details

`static/log-management.html`:
- New CSS classes `.lm-cap-warn` (ok / warn / error) and
  `.lm-system-row` (boxed snapshot panel).
- New "7z search byte cap (MB)" input row in the Settings card,
  with inline `<div id="lm-7zmax-warn">` for live validation.
- New `<div id="lm-system-row">` below the settings grid that
  renders the snapshot ("Host: <CPU> (N cores) — X GB total / Y
  GB free — load 1m / 5m / 15m").
- `validateCap()` runs on every keystroke + on `loadSettings()`:
  - `< 1` or non-numeric → red "Enter a value..." error
  - `> SEVEN_Z_HARD_MAX_MB` → red "Above hard limit" error
  - `> SEVEN_Z_WARN_THRESHOLD_MB` OR `> 50% of free RAM` → amber
    "Caution: <reasons>" warning
  - Otherwise → neutral "Cap reads as: truncate at ~N MB" hint.
- Save handler includes `seven_z_max_mb` in the PUT body.
  After save, `loadSettings()` is re-invoked so any backend
  clamping is reflected immediately.

### Files

- `core/version.py` — bump to 0.31.1
- `core/log_manager.py` — pref + helpers + augmented settings
- `api/routes/log_management.py` — Pydantic field, reader cap,
  pref read in async outer
- `static/log-management.html` — settings UI + snapshot
- `static/log-viewer.html` — search spinner
- `CLAUDE.md` — Current Version block + v0.31.0 demoted to summary
- `docs/version-history.md` — this entry
- `docs/help/whats-new.md` — user-visible bullet
- `docs/help/admin-tools.md` — refresh "future release will let
  you tune this" sentence to "this is now tunable"

No DB migration. No new dependencies. No new scheduler jobs.

---

## v0.31.0 — Deferred-items bundle (2026-04-25)

Five-item bundle release executing the entire
`docs/superpowers/plans/2026-04-24-v0.31-deferred-items.md` plan
in one shot. Each item is independent — bundled per the user's
end-of-session "do all updates THEN bump version + commit"
directive.

### Item 1 — Multi-provider filename interleaving

`_batch_anthropic` got the filename-as-text-block treatment in
v0.29.8 (operators with the Anthropic provider saw their
descriptions improve from generic "a large modern building" to
"Benaroya Hall, a concert venue in Seattle"). Same pattern now
applies to the three other providers in `core/vision_adapter.py`:

- **OpenAI** (`_batch_openai`): content array now interleaves
  `{"type": "text", "text": "Image N filename: ..."}` blocks
  before each `image_url` block. Prompt moved to the END of the
  array (was at the beginning) — matches Anthropic's order.
- **Gemini** (`_batch_gemini`): `parts` array interleaves
  `{"text": "Image N filename: ..."}` parts before each
  `inline_data` part. Prompt also moved to the end.
- **Ollama** (`_batch_ollama`): Ollama's `/api/generate` API
  takes a single string `prompt` + `images: [b64, ...]` array
  with no per-image text blocks, so the filename list is
  prepended to the prompt:
  `"Files (in order): 1. foo.jpg, 2. bar.png\n\n<prompt>"`.

The base prompt (defined in `describe_batch`) already includes
the "If the preceding filename identifies a specific recognizable
subject... name the subject" instruction added in v0.29.8, so the
prompt itself didn't need to change.

### Item 2 — Time-range UI in log viewer historical search

Backend has supported `from_iso` / `to_iso` query params on
`GET /api/logs/search` since v0.30.1, but the UI didn't expose
them. v0.31.0 adds:

- A new row below the main controls in `static/log-viewer.html`,
  visible only in history mode (live tail mode hides the row).
- Two `<input type="datetime-local">` fields (From / To),
  dark-themed via `color-scheme: dark`.
- Preset chips: **Last hour**, **Last 24h**, **Last 7d**,
  **Clear range**. Clicking a preset fills both inputs to
  (now − Δ) and (now), then re-runs the search.
- `localInputToUtcIso(value)` helper converts the local-time
  input to a UTC ISO string before sending. Empty / invalid
  inputs degrade to no-param (server's flexible ISO parse
  treats naive ISO as UTC).
- Hint text near the row shows the active From/To as ISO so
  operators know exactly what's being sent to the server.

### Item 3 — Bulk re-analyze with delete-and-re-insert semantics

#### The semantics change

The v0.30.4 per-row endpoint did UPDATE-in-place — preserved id,
enqueued_at, content_hash, source_path; only cleared the result
columns. v0.31.0 was written to the user's explicit requirement
(2026-04-24):

> *"Make sure that the files that get reanalyzed are deleted
> from the database and resubmitted for entry into the database
> with the new information."*

Both the per-row and the new bulk endpoints now do **DELETE +
re-INSERT** via the canonical `enqueue_for_analysis` path. Effect:
fresh `id`, fresh `enqueued_at`, `retry_count = 0`, all output
columns NULL because the row is BRAND NEW, not because we
explicitly cleared them. Defends against future schema additions
that an UPDATE would have to remember to clear.

#### Per-row endpoint

`POST /api/analysis/queue/{entry_id}/reanalyze` (OPERATOR+) now:

1. SELECTs the row to capture identity columns (source_path,
   content_hash, job_id, scan_run_id, file_category).
2. DELETEs the row through `db_write_with_retry`.
3. Re-INSERTs via `enqueue_for_analysis(...)`.
4. Returns `{status, old_entry_id, new_entry_id}` so callers can
   correlate the change.

#### Bulk endpoint

`POST /api/analysis/queue/reanalyze-bulk` (OPERATOR+):

- Pydantic body `BulkReanalyzeRequest`:
  - `analyzed_before_iso`, `analyzed_after_iso`, `provider_id`,
    `model`, `status` (default `completed`), `dry_run` (default
    `true`)
- Refuses empty filter sets — at least one of (date bound,
  provider, model, non-empty status) must be supplied.
- 10,000-row hard cap (`BULK_REANALYZE_CAP` in
  `core/db/analysis.py`). Above that, dry-run sets
  `exceeds_cap=true` and a non-dry-run gets a 400.
- Dry-run returns `{matched, sample (first 5 source_paths),
  exceeds_cap, cap}`.
- Confirmed run returns `{deleted, re_enqueued, new_entry_ids,
  dropped}`. `dropped` is non-zero only in defensive races where
  `enqueue_for_analysis` declines to re-insert; shouldn't occur
  since we just deleted the row, but is logged for visibility.

`GET /api/analysis/queue/reanalyze-filters` (OPERATOR+) returns
`{providers, models}` — distinct values from `analysis_queue` —
for the modal's dropdown population.

#### DB helpers (`core/db/analysis.py`)

- `BULK_REANALYZE_CAP = 10_000`
- `find_rows_for_bulk_reanalyze(...)` — composes the filter
  WHERE clause, returns up to `cap+1` rows so the API can
  detect "exceeds cap".
- `delete_rows_by_ids(row_ids)` — single DELETE with `IN (?, ?, ...)`.
- `list_distinct_provider_models()` — backs the filters helper.

#### Frontend (`static/batch-management.html`)

- Top-bar **"Bulk re-analyze..."** button next to "Cancel All
  Pending".
- Modal with date pickers, provider/model dropdowns
  pre-populated from the filters helper, status dropdown, a
  Preview button (calls `dry_run=true`), and a Run button
  (disabled until preview shows >0 matched rows). Run button
  confirms with explicit "deletes the matching rows and
  re-submits them as fresh entries" copy plus the exact row
  count and LLM token caveat.
- Per-row **"Re-analyze"** button copy + tooltip updated to
  mention DELETE + re-INSERT explicitly.

### Item 4 — Multi-log tabbed live view

`static/log-viewer.html` got a substantial refactor. Single global
EventSource + filter state replaced with a **`LogTab` class**
(~250 LOC of class + helper code). Each tab owns:

- Its own EventSource (kept open in the background so events
  aren't missed when watching a different tab)
- Body div (only the active tab's body is `display: block`;
  others are hidden)
- History offset, pause flag, line counts (totalLines /
  filteredLines)
- Per-tab filter state: levels Set, search query + regex flag,
  from_iso / to_iso, mode (live / history)

Tab strip at the top of the body area:

- Each tab shows a green/red/grey dot indicating SSE connection
  state (connected / disconnected / connecting), the file name,
  and a × close button.
- **+ Add tab** button at the end opens a popover listing all
  available logs (with size + status). Already-open logs are
  greyed out with a ✓ open marker.
- Switching the active tab syncs the top control bar (mode
  selector, level chips, search box, time range, pause button)
  to that tab's stored state.

Memory bound: each tab's body is capped at 1000 lines —
`appendLine` evicts older nodes from the head once the cap is
reached. Closed tabs have their EventSource explicitly `.close()`d.

Persistence: open tab list, active tab, and per-tab filter state
all serialized to `localStorage` under
`markflow.logviewer.tabs.v1`. On bootstrap, the saved tab set is
restored (filtered to logs that still exist on disk). If
localStorage is empty AND no `?file=` query param is present, the
most-recent log is auto-opened so the page isn't a blank slate.

### Item 5 — Log subsystem consolidation

`core/log_archiver.py` (v0.12.2, ~150 LOC) **deleted**. Its
6-hour scheduler job replaced by a thin async wrapper in
`core/scheduler.py`:

```python
async def _log_manage_cycle():
    from core.log_manager import compress_rotated_logs, apply_retention
    try: await compress_rotated_logs()
    except Exception as exc: log.warning("scheduler.log_compress_failed", error=...)
    try: await apply_retention()
    except Exception as exc: log.warning("scheduler.log_retention_failed", error=...)
```

Net effect: same 6-hour cron cadence, but the **Settings page
preferences (compression format, retention days) now actually
govern the automated cycle**. Previously the cron used hardcoded
gz + 90-day defaults regardless of what the operator set in the
UI — only manual "Compress Rotated Now" / "Apply Retention Now"
admin clicks honored the prefs. That divergence is now fixed.

The legacy `archive/` subdir under `LOGS_DIR` is left in place;
the inventory endpoint already discovered it (added in v0.30.1)
and continues to. New compressions go to `LOGS_DIR/<name>.gz`
(in-place rotation), not the `archive/` subdir.

`get_archive_stats()` reborn in `core/log_manager.py` (now reads
retention from DB pref instead of env var). The
`/api/logs/archives/stats` route in `api/routes/logs.py` updated
to import from there. Endpoint shape unchanged.

18-job scheduler count unchanged.

### Cumulative file list

- `core/version.py` — bump to 0.31.0
- `core/vision_adapter.py` — filename interleaving in
  `_batch_openai`, `_batch_gemini`, `_batch_ollama`
- `core/db/analysis.py` — `BULK_REANALYZE_CAP`,
  `find_rows_for_bulk_reanalyze`, `delete_rows_by_ids`,
  `list_distinct_provider_models`
- `api/routes/analysis.py` — per-row `reanalyze_queue_entry`
  switched to delete+re-insert; new `reanalyze_bulk` +
  `reanalyze_filters` endpoints + `BulkReanalyzeRequest` model
- `static/log-viewer.html` — multi-tab refactor + time-range row
- `static/batch-management.html` — Bulk re-analyze top-bar button
  + modal HTML/CSS/JS + per-row button copy update
- `core/scheduler.py` — `_log_manage_cycle` replaces
  `archive_rotated_logs` job
- `core/log_archiver.py` — DELETED
- `core/log_manager.py` — added `get_archive_stats()` shim;
  comment cleanup re: deleted module
- `api/routes/logs.py` — `/archives/stats` re-imports from
  `log_manager` (now async)
- `CLAUDE.md`, `docs/version-history.md`, `docs/key-files.md`,
  `docs/gotchas.md`, multiple `docs/help/*.md`

No DB migration. No new dependencies. No new scheduler jobs (the
existing `log_archive` job's body was rewritten but the slot is
unchanged).

### Risks / things to watch

- **`analysis_queue.id` is no longer stable across re-analyze.**
  Documented in `docs/gotchas.md` (Re-analyze section). Future
  integrations that cache the id need to handle "row not found"
  by looking up via `source_path` instead.
- **Operators caching the Settings page from before v0.31.0**
  may have stale `compression_format` / `retention_days` values
  in their DB that now get applied to the cron. If they had
  diverged from the legacy archiver's hardcoded gz+90d, behavior
  changes on the next cron tick. Visible only on logs that
  rotate.
- **Bulk re-analyze can blow LLM quota fast.** The 10k cap +
  dry-run + confirm dialog with explicit token caveat are the
  safety net. Operators should always preview first.

---

## v0.30.4 — Re-analyze button for stale analysis results (2026-04-24)

Closes a UX gap exposed by v0.29.8's filename-context prompt
improvement: rows analyzed before that release have no way to
benefit from the new prompt without manual SQL.

### Trigger

User opened the analysis-result modal on
`strike_NY_tailors_1910_dbloc-Edit.tif` and saw a generic
description ("Same photograph as the previous image but slightly
cropped...") that didn't reference the strike, NY, or 1910 — even
though the filename clearly identifies all three. The row was
analyzed at 12:17:11 PM, before v0.29.8 shipped at ~3:00 PM. The
row's content_hash matches the file, so `enqueue_for_analysis`
correctly skips it on subsequent scans. Operators had no path to
refresh.

### Backend

`POST /api/analysis/queue/{entry_id}/reanalyze` (OPERATOR+):

```sql
UPDATE analysis_queue
SET status = 'pending',
    batch_id = NULL,
    batched_at = NULL,
    description = NULL,
    extracted_text = NULL,
    error = NULL,
    analyzed_at = NULL,
    retry_count = 0,
    provider_id = NULL,
    model = NULL,
    tokens_used = NULL
WHERE id = ?
```

Preserves identity columns (source_path, content_hash,
file_category, scan_run_id, enqueued_at). The next worker claim
cycle re-submits the image with the current prompt. Goes through
`db_write_with_retry` so it doesn't 500 if the worker has a write
lock (v0.30.0 lesson).

404 if `entry_id` isn't in the table.

### Frontend

Analysis-result modal (introduced v0.29.5) now has a "Re-analyze"
button in the header next to the close ×. Tooltip explains the
cost. Confirm dialog summarizes:

> Re-analyze "{filename}"? The current description and extracted
> text will be cleared and replaced when the next worker cycle
> picks it up. Uses LLM tokens.

On success: closes the modal, calls `refreshStatus()` +
`loadBatches()` so the row shows status='pending' immediately.

### Why per-row, not bulk

A "re-analyze every completed row" pass would burn LLM quota on
tens of thousands of files for incremental quality gains.
Operators can spot the underwhelming descriptions in the modal
and re-trigger individually, paying ~1 image worth of tokens per
click. Future v0.30.x release could add a bulk-re-analyze with
filter (e.g., "all rows analyzed before 2026-04-24") if there's
demand.

### Files

- `core/version.py` — bump to 0.30.4
- `api/routes/analysis.py` — new `reanalyze_queue_entry` endpoint
- `static/batch-management.html` — Re-analyze button + handler
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No DB migration. No new dependencies. Reuses the existing
batched-result-write path (`write_batch_results` in
`core/db/analysis.py`) which since v0.29.8 also clears `error`
and resets `retry_count` on success — so re-analyzed rows come
back clean even if the original had a stale error blob.

---

## v0.30.3 — Operations bundle: real paths + stuck-scan cleanup + disk-usage perf + force-transcribe button (2026-04-24)

Four operations-level fixes shipped together. All surfaced from a
single round of looking at the running install.

### 1. Real source/output paths on Active Jobs

Active Jobs card showed `/mnt/source → /mnt/output-repo` — the
container mount points the bulk worker uses for I/O. Operators
running the Storage Manager (v0.28.0+) had configured paths like
`/host/d/k_drv_test`, but the UI never showed them.

`/api/admin/active-jobs` now enriches every job with:
- `display_source_path` — pulled from the `storage_sources_json`
  preference (the same JSON the Storage page reads/writes). If
  multiple sources are configured, shows the first plus a
  "+N more" suffix.
- `display_output_path` — pulled from
  `core.storage_manager.get_output_path()`.

Both are returned alongside the raw `source_path` / `output_path`
fields. Frontend (`static/status.html`) prefers them when present
and falls back gracefully otherwise. The job row still operates on
the mount paths internally — only the display changes.

### 2. Stuck 'scanning' job auto-cleanup

A scan that started under one container and finished after a
container restart left a zombie job displayed forever:
- Status: 'scanning'
- No scanner running to update it
- `cleanup_stale_jobs` migration only covered 'running' status

Today's reproduction had job `89bc8015...` stuck displaying
"0 / ? files — ?%" in the Active Jobs panel even though the
underlying scan had completed (`parallel_scan_complete` with
`files=85450`). The bulk_jobs row was never updated to a terminal
status because the writer crashed on `persist_throttle_events`
right after the scan finished — a separate latent bug.

Fix: extended `cleanup_stale_jobs` to:
- Match `status IN ('running', 'scanning')` instead of just
  'running'
- Stamp `completed_at = datetime('now')` so the Bulk Jobs page
  knows when it ended
- Preserve any existing `error_msg`; otherwise write a
  descriptive "Container restart during {status}; auto-cleared on
  next startup" message

The current zombie was cleared via one-shot SQL since the new
migration only runs on next startup. After v0.30.3 deploy, the
auto-cleanup runs on every container start.

### 3. `/api/admin/disk-usage` 100× faster

Was hanging past 60 s (caused the empty "Loading disk usage..."
panel on the admin page). Root cause: Python's `Path.rglob('*')`
over the output repo, which has ~100 K Markdown files plus their
sidecars. Native walker is just slow at that scale.

Two-layer fix:
1. **`du -sb` subprocess** — the system `du` binary is orders of
   magnitude faster than `rglob` (sub-second on the same tree).
   Used when no `exclude_parts` filter is needed (the common
   case). When excludes are needed (e.g., to skip `.trash` inside
   the output-repo), falls back to the Python walker because `du`
   has no equivalent flag. Subprocess has a 30 s timeout
   belt-and-braces guard against pathologically slow NAS mounts.
   `_DU_AVAILABLE = False` after first FileNotFoundError so
   no-`du` environments don't keep retrying.
2. **TTL cache (5 min)** — wraps the entire
   `_compute_disk_usage()` result. Repeat admin-page loads inside
   the window return instantly. Response includes
   `from_cache: true` so callers can tell. The `/disk-usage`
   endpoint accepts `?refresh=true` to bypass the cache for an
   explicit Refresh button click.

`file_count` is left as 0 (treated as "unavailable" by the UI)
when `du -sb` is the source — du doesn't return file counts
cheaply. Bytes is what operators actually look at; counts can
remain on the slow path when needed.

### 4. Force Transcribe / Convert Pending button

History page → Pending Files card now has a primary "Force
Transcribe / Convert Pending" button next to the status filter.
Click → confirm dialog → POSTs to the existing
`/api/pipeline/run-now` endpoint, which triggers an immediate
scan + convert cycle. The bulk worker picks up every pending
file (including audio/video → Whisper transcription) in priority
order.

This is the simplest possible plumbing for the user's ask: the
"run now" path already exists from the Pipeline subsystem; the
button just exposes it from the most natural UI location
(Pending Files where the operator is actually looking at the
backlog). Confirmation dialog warns about LLM/transcription
quota usage.

### Files

- `core/version.py` — bump to 0.30.3
- `core/db/migrations.py` — `cleanup_stale_jobs` extended to
  scanning + stamps completed_at + descriptive error_msg
- `api/routes/admin.py` — `_resolve_display_source_path` and
  `_resolve_display_output_path` helpers; `/active-jobs`
  enrichment; `_walk_dir` prefers `du -sb`; `_compute_disk_usage`
  TTL-cached; `/disk-usage` accepts `?refresh=true`
- `static/status.html` — Active Jobs job-card path uses
  `display_source_path / display_output_path` with fallback
- `static/history.html` — Force Transcribe / Convert Pending
  button + click handler
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No DB migration. No new dependencies. The stuck-job cleanup
runs on lifespan startup; the previous zombie was cleared via
one-shot SQL during diagnosis.

---

## v0.30.2 — Admin panel hot fix: async/await parse error in renderStats (2026-04-24)

Hot three-character patch. Admin panel was visibly broken — every
KPI card stuck at "--", every async section at "Loading...", every
table empty. User reported it after pulling v0.30.1.

### Root cause

`static/admin.html:591` declared `function renderStats(d)` as a
plain (non-async) function, then on line 606 used
`await API.get('/api/flags/stats')` inside it. That's a SyntaxError
at parse time:

```
SyntaxError: Unexpected reserved word 'await' (at admin.html:606)
```

When a `<script>` block fails to parse, NONE of its code runs —
not `loadStats()`, not `loadPipelineFunnel()`, not the
event-listener hookup for the Refresh button. The browser just
renders the initial HTML skeleton, which hardcodes `--` in every
counter and "Loading..." in every async panel. To an operator it
looks identical to "all backend endpoints are timing out," but
`curl` against the same endpoints returned 200 in <200 ms.

The bug was pre-existing (not introduced by v0.30.1). It likely
crept in during an earlier iteration on the stats-rendering path
that didn't get hit at load time on the test machine where it was
edited.

### Fix

1. `function renderStats(d)` -> `async function renderStats(d)`.
2. `loadStats` now does `await renderStats(d)` so exceptions
   inside the `/api/flags/stats` fetch propagate to the existing
   try/catch (they were previously swallowed silently).

### Verification recipe

```bash
# Confirm the endpoints are already fast (they always were):
time curl -sS http://localhost:8000/api/admin/stats | head -c 200
# After rebuild, hard-refresh /admin.html - all KPI cards populate
# within ~200 ms, Pipeline Funnel loads, Recent Errors table
# populates.
```

### Files

- `core/version.py` - bump to 0.30.2
- `static/admin.html` - two single-line edits (async keyword,
  await on caller)
- `CLAUDE.md` - Current Version block
- `docs/version-history.md` - this entry

### Deferred

`/api/admin/disk-usage` is genuinely slow (>60 s on the current
install) because it walks the output-repo with Python's
`rglob("*")` over ~100 K files. That's orthogonal to the
renderStats bug - it wouldn't have blocked the KPI cards from
populating. A follow-up can swap the walker to `du -sb`
subprocess + 5-min TTL cache.

---

## v0.30.1 — Log Management subsystem (admin + viewer) (2026-04-24)

New admin-only subsystem for log observability. Two pages, one
backend router, two helper modules. No dependencies added; no
database migration.

### Motivation

The existing `core/log_archiver.py` (v0.22.1) quietly compresses
rotated logs to `/app/logs/archive/*.gz` every 6 hours. Useful
infrastructure, completely invisible to operators. This release
surfaces it — inventory, download, live tail, historical search
— plus adds on-demand compression triggers and a configurable
compression-format + retention settings panel.

### Surface area

**`/log-management.html`** (admin nav → Log Management card):

- Inventory table: every file under `/app/logs` + the
  `archive/` subdir. Columns: checkbox / name / stream
  (operational/debug/other) / status pill (active/rotated/
  compressed with format) / size / modified / download link.
- Toolbar: "Open Live Viewer" (new tab), "Download All" (streams
  a zip of every file), "Download Selected (N)" (streams a zip
  of checked rows), "Compress Rotated Now" (synchronous trigger
  of the compression helper), "Refresh".
- Collapsed Settings panel: compression format (gz / tar.gz /
  7z), retention days (1-3650), rotation size MB (10-10240 —
  takes effect at next restart), "Save Settings", "Apply
  Retention Now".

**`/log-viewer.html`** (admin nav → Log Management card →
secondary link, OR per-row filename click from the inventory
page):

- File dropdown (excludes .7z — those require download +
  external tooling), Mode dropdown (Live tail / Search history).
- Live mode: SSE stream from `/api/logs/tail/{name}`. Backfill
  ~200 lines at connection start, then real-time append. New
  lines arrive as they're written by structlog; the viewer
  respects the Pause button and an "Auto-scroll" toggle.
- History mode: server-side paginated search via
  `/api/logs/search`. Paginates with a "Load older" button that
  walks backward through the file in 200-line pages.
- Level-filter chips (DEBUG / INFO / WARNING / ERROR+CRITICAL)
  apply client-side in live mode (no round trip), server-side
  in history mode.
- Search box with a Regex toggle. Substring search is case-
  insensitive. Regex failures surface via `showError`.
- JSON-aware rendering: each line is `JSON.parse`d. structlog
  output gets pretty colored timestamp / level / logger / event
  with a green `k=v k=v` tail for the remaining fields.
  Non-JSON lines render as plain text, still filter-able.

### Backend

**`core/log_manager.py` (new, 250 lines)**:
- `list_logs()` — walks `LOGS_DIR` and `LOGS_DIR/archive`,
  returns `list[LogEntry]` with stream classification, status,
  compression format.
- `_safe_logs_path(name)` — resolves bare filenames or
  `archive/<filename>` relative paths to absolute paths inside
  `LOGS_DIR`. Rejects `..`, backslashes, absolute paths, and
  anything that `Path.resolve()` puts outside the root.
- `compress_rotated_logs(format_override=None)` — finds
  `*.log.N` rotated backups and compresses them using the DB
  preference (gz / tar.gz / 7z). gz + tar.gz use Python
  stdlib; 7z shells out to `/usr/bin/7z` with a 10-minute
  subprocess timeout. All compression work runs in
  `asyncio.to_thread` so it doesn't block the event loop.
- `apply_retention(days_override=None)` — deletes compressed
  logs (`.gz` / `.7z` / `.tgz` only — never touches active or
  rotated-uncompressed files) older than the configured
  retention window. Safety-gated to require an explicit
  compressed-suffix match; no `.log` will ever be purged by
  this path.
- `get_settings()` / `set_settings()` — preference-backed
  accessors with validation. Bounds checks: retention 1-3650
  days, rotation 10-10240 MB, format in {gz, tar.gz, 7z}.

**`api/routes/log_management.py` (new, 350 lines)** — ADMIN-
gated throughout:

| Endpoint | Purpose |
|---|---|
| GET /api/logs | Inventory + total size + LOGS_DIR path |
| GET /api/logs/settings | Current settings from prefs |
| PUT /api/logs/settings | Validated update |
| POST /api/logs/compress-now | Synchronous trigger |
| POST /api/logs/apply-retention-now | Synchronous trigger |
| GET /api/logs/download/{name:path} | File stream |
| POST /api/logs/download-bundle | Streaming zip |
| GET /api/logs/tail/{name:path} | SSE live tail |
| GET /api/logs/search | Paginated historical search |

The `{name:path}` converter is intentional — `archive/foo.gz`
needs to be passable as the URL path without URL-encoding the
slash.

### Search endpoint details

`GET /api/logs/search?name=X&q=...&regex=true&levels=ERROR,WARNING&from_iso=...&to_iso=...&limit=200&offset=0`

- `limit` 1-1000, `offset >= 0`. Defaults: 200, 0.
- `q` pairs with `regex=true/false`. Regex is case-insensitive.
  Invalid regex returns 400 with the compile error.
- `levels` is a comma-separated filter on the `level` field of
  parsed JSON lines. Alternative `min_level=WARNING` selects
  WARNING + ERROR + CRITICAL via the `_LEVEL_ORDER` mapping.
- Time range via `from_iso` / `to_iso` — applied against the
  parsed `timestamp` / `ts` field. Non-JSON lines always pass
  the time filter (no timestamp to compare).
- **Scan cap**: 500,000 lines per request. A regex that
  matches nothing on a 10 GB file won't DoS the server —
  `scan_truncated: true` in the response surfaces when the cap
  was hit so the UI can flag it.
- Gzipped files are read via `gzip.open("rt")`; uncompressed
  via `path.open("r")`. Both use UTF-8 with `errors="replace"`
  so corrupt bytes don't crash the reader.
- Lines stored in a ring buffer sized `limit + offset + 100`,
  reversed at the end, sliced to `[offset:offset+limit]`. Newest-
  first output order.

### Security posture

- ADMIN role required for every endpoint (the `/api/logs` tree
  can carry sensitive PII, error tracebacks with internal file
  paths, request IDs, user IDs, etc.). MANAGER / OPERATOR are
  NOT granted access.
- Every file access routes through `_safe_logs_path` — rejects
  `..`, backslashes, absolute paths, and anything outside
  `LOGS_DIR.resolve()`.
- 7z compression invoked via `subprocess.run` with a fixed
  argv list (no shell, no interpolation of user input into
  arguments beyond the validated source path).
- SSE stream checks `request.is_disconnected()` between each
  poll tick so disconnects terminate the tail promptly without
  holding a file handle open.
- Every mutation (settings update, compress-now, retention-now,
  download, bundle) is audit-logged via structlog with
  `user.email`.

### Deliberate non-goals

- **No replacement of `core/log_archiver.py`**. That module
  runs its own 6-hourly cron with hardcoded gz + 90-day defaults
  and writes to `/app/logs/archive/`. The new settings panel
  writes to DB prefs that the new manual-trigger path respects,
  but the automated scheduler uses the legacy module unchanged.
  A follow-up release can consolidate; for now, two subsystems
  coexist peacefully because their file locations and triggers
  don't overlap.
- **No time range UI in the viewer** for history search — the
  backend supports `from_iso` / `to_iso` query params but the
  frontend doesn't wire them up this release. Follow-up.
- **No `.7z` live tail / search** — 7z archives need full
  decompression to inspect, which would OOM the worker on large
  logs. Users are directed to the Download button for those.
- **No HEIC / other photo format additions in the preview
  system** — the earlier v0.29.8 format set is unchanged here.

### Files

- `core/log_manager.py` — new
- `api/routes/log_management.py` — new
- `static/log-management.html` — new
- `static/log-viewer.html` — new
- `static/admin.html` — new Log Management card in the
  scheduled-jobs column
- `main.py` — register `log_management.router`
- `core/version.py` — bump to 0.30.1
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

---

## v0.30.0 — Pause-500 fix + pause-with-duration presets + explicit Resume (2026-04-24)

One urgent bug fix plus a UX polish on the Batch Management page.

### Bug: `/api/analysis/pause` 500 under queue load

**Symptom:** clicking Pause on Batch Management produced
`Failed: POST /api/analysis/pause failed (500)`. Container logs
showed a `sqlite3.OperationalError: database is locked` traceback
originating in `core/db/preferences.py:160` (`set_preference`).

**Root cause:** `set_preference` was doing raw `aiosqlite` writes
without going through the single-writer retry machinery
(`db_write_with_retry`) that v0.23.0 introduced for exactly this
class of contention. Every other write path in the app — bulk
worker, migrations, analysis worker — uses the retry helper. The
preference writer did not, so any overlap with a held write
transaction hit SQLite's default 5 s `busy_timeout` and 500'd.

**Fix:** wrap the inner `INSERT … ON CONFLICT DO UPDATE` in
`db_write_with_retry`. Imports are local (no circular import risk)
and the helper already backs off exponentially on "database is
locked" with 3 retries at 0.5/1.0/2.0 s. Net: the Pause button now
succeeds even when the worker is mid-batch.

### Feature: pause-with-duration presets + explicit Resume

The old Pause button was a toggle ("Pause" ↔ "Resume" on a single
button) that paused indefinitely on click. v0.30.0 replaces it
with two distinct controls:

1. **Pause ▾** — opens a popover with six preset durations:
   - 1 hour
   - 2 hours
   - 6 hours
   - 8 hours
   - Until off-hours (next boundary from
     `scanner_business_hours_end`, default 22:00)
   - Indefinitely
2. **Resume** — always visible when paused, immediately clears
   both pause prefs and resumes the worker.

**Backend data model.** A new preference
`analysis_pause_until` stores an ISO-8601 UTC deadline. Empty
string means indefinite. Combined with the existing
`analysis_submission_paused` boolean:

| `paused` | `pause_until`     | Meaning                         |
|----------|-------------------|---------------------------------|
| `false`  | (ignored)         | Running normally                |
| `true`   | ""                | Paused indefinitely             |
| `true`   | future ISO        | Paused with auto-resume         |
| `true`   | past ISO          | Stale — auto-resumes on read    |

**API.**

- `POST /api/analysis/pause` accepts optional body
  `PauseRequest { duration_hours?: float, until_off_hours?: bool }`.
  `duration_hours` bounded by `0 < h ≤ 168` (one week max).
  Empty body keeps legacy behavior (indefinite pause).
  Returns `{status: "paused", mode: "1h"|"until_off_hours"|
  "indefinite", pause_until: ISO | null}`.
- `POST /api/analysis/resume` now also clears `analysis_pause_until`
  so a later Pause click doesn't inherit a stale deadline.
- `GET /api/analysis/status` returns `pause_until` alongside the
  boolean `paused` flag. The endpoint also auto-resumes (clears
  both prefs) when it sees a past deadline — the UI's next poll
  always reflects the correct state without needing the worker
  to tick first.

**Worker.** `core/analysis_worker.py` now reads
`analysis_pause_until` at the top of each claim cycle. If set and
in the past, it auto-clears both prefs and proceeds; if set and
in the future, it logs and skips; if empty, it stays paused
indefinitely (legacy). Mirrors the status endpoint's auto-resume
so a long-idle page doesn't need to be open for a timed pause to
expire.

**UI.** The status label reads:
- "Submission: Running" (closed)
- "Submission: Paused until 4/24/2026, 9:00:00 PM" (timed)
- "Submission: Paused (indefinite)" (legacy)

The Pause button exposes `aria-haspopup="true"` and
`aria-expanded`; menu items use `role="menuitem"` with Enter/Space
activation. Escape closes the menu.

### Files

- `core/version.py` — bump to 0.30.0
- `core/db/preferences.py` — `set_preference` wraps
  `db_write_with_retry`
- `api/routes/analysis.py` — `PauseRequest` model, helper
  `_compute_off_hours_pause_until`, rewritten `/pause` endpoint,
  `/status` returns `pause_until` + auto-resume, `/resume` clears
  deadline
- `core/analysis_worker.py` — timed-pause awareness + auto-resume
  at claim time
- `static/batch-management.html` — dropdown popover CSS/HTML/JS,
  explicit Resume button, status-label reformat
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No database migration. No new dependency.

**Deferred to v0.30.1** (already in flight, not shipping this
release): Log Management subsystem (auto-compression of rotated
logs, admin inventory page, live SSE tail view, multi-file
download bundle). Keeping v0.30.0 tight to unblock the pause
bug fast.

---

## v0.29.9 — Vision API resilience: preflight + backoff + bisection + circuit breaker (2026-04-24)

Five coordinated layers of defense against wasted Anthropic vision
API spend. Framed explicitly around financial best practices: API
calls are real dollars, every avoidable 400 is waste, and an
operator should never silently burn quota during an upstream
outage.

### Layer 1 — Preflight validation (`core/vision_preflight.py`)

New module, ~100 lines. Every image is validated before encoding:

1. Non-empty bytes
2. MIME in the Anthropic allow-list (`image/jpeg`, `image/png`,
   `image/gif`, `image/webp`)
3. PIL `Image.verify()` on the header (catches truncation /
   corruption without decoding pixels)
4. PIL `Image.open().size` inside sane bounds: `100 ≤ min_edge`
   and `max_edge ≤ 8000` pixels

Returns a structured `PreflightResult(ok, error, width, height,
detected_mime)`. On failure the analysis_queue row gets a
descriptive `[preflight] ...` error and the API call is skipped
entirely — zero cost on known-bad inputs. The PIL import is lazy
so callers that never use vision don't pay the C-extension load
cost.

### Layer 2 — Exponential backoff + `Retry-After`

Module-level helpers `_parse_retry_after()` and `_backoff_delay()`
in `core/vision_adapter.py`. Retryable status codes:

```python
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 529})
```

`_parse_retry_after()` handles both numeric-seconds and
HTTP-date forms of the header. If present, the server-suggested
delay wins (capped at `_BACKOFF_MAX_S = 30 s`). Otherwise the
fallback is exponential 1/2/4/8 s with ±15 % jitter (prevents
concurrent callers thundering-herd after a common failure).

Per sub-batch: up to `_BACKOFF_MAX_ATTEMPTS = 4` tries. Worst-case
wall-clock under sustained failure is ~255 s per sub-batch (15 s
sleep + 4 × 60 s request timeout). Network / timeout exceptions
follow the same loop.

400 Bad Request is NOT in `_RETRYABLE_STATUS_CODES` — retrying a
400 is always waste. 400s feed Layer 3 instead.

### Layer 3 — Per-image bisection on 400

When a sub-batch of N images returns 400, `_anthropic_sub_batch`
splits `batch_indices` in half and recursively retries each half.
At N=1, the 400 is recorded as that specific image's error with
the Anthropic response body for debugging.

Worst case for one malformed file in a batch of 16:
- 1 call × 16 → 400
- 2 calls × 8 → one 400, one success
- 2 calls × 4 → one 400, one success
- 2 calls × 2 → one 400, one success
- 2 calls × 1 → one 400 (isolated), one success
- Total: 9 calls for 15 successful analyses + 1 isolated failure.

Without bisection: 1 call → all 16 tossed. With bisection: 15 of
16 saved, and the operator learns exactly which file was bad.
Recursion guard caps at depth 20 (never hit in practice; log2 of
the 24 MB payload over minimum image size is ~11).

### Layer 4 — Circuit breaker (`core/vision_circuit_breaker.py`)

New module, ~150 lines. Process-local state machine:

```
closed   ─(5 consecutive upstream failures)→ open
open     ─(cooldown elapses)→ half-open (one trial allowed)
half-open ─(trial succeeds)→ closed
half-open ─(trial fails)→ open (cooldown doubles, cap 15 min)
```

Cooldown starts at 60 s and doubles on repeated re-open:
`60 → 120 → 240 → 480 → 900 s (cap)`. Exponential to give
Anthropic time to recover from genuine outages without us
hammering.

**Only UPSTREAM failures count toward the threshold** — 400s feed
bisection and don't trip the breaker (otherwise one bad image
could pause the whole queue). 429 / 5xx / 529 / network/timeout
all count.

**Process-local, not DB-persisted**: intentional. Restart resets
the breaker — an operator who just restarted presumably wants to
try again, and Anthropic may have recovered while we were down.

Thread-safe via `threading.Lock` since the breaker is called from
multiple concurrent async tasks.

### Layer 5 — Operator banner

Two new endpoints on `api/routes/analysis.py`:

- `GET /api/analysis/circuit-breaker` (OPERATOR+): returns
  `{status, consecutive_failures, threshold, cooldown_s,
  cooldown_remaining_s, opened_at_epoch, last_error_class,
  last_error_detail}`. Polled every 5 s by the Batch Management
  page's existing `pollTick` (added as a parallel fetch to
  `/status`; silent-fail on error so a network blip doesn't show a
  stale banner).
- `POST /api/analysis/circuit-breaker/reset` (MANAGER+):
  force-closes the breaker for operators who've manually fixed the
  upstream issue.

The Batch Management page renders a red banner (or amber for
half-open) above the top bar when the status is not `closed`.
Banner shows error class, consecutive-failure count, cooldown
countdown, and a "Reset breaker" button gated on confirmation.

### Out of scope

Intentionally deferred:

- **OpenAI / Gemini / Ollama resilience** — same 5 layers can be
  applied to the three other provider handlers
  (`_batch_openai` / `_batch_gemini` / `_batch_ollama`) but the
  current traffic is almost entirely Anthropic on this install.
  Follow-up.
- **Token-estimate pre-flight** — we could reject images whose
  combined `max_tokens` request would exceed the model context.
  The current `400 * len(batch_indices)` heuristic is safe for
  Claude Opus 4.6/4.7 but not airtight.
- **Per-hour spend cap** — a hard dollar ceiling that pauses the
  queue regardless of success rate. Nice-to-have, not shipped.
- **Cost attribution to batches** — `tokens_used` is already
  recorded; a provider-rate table multiplied by token counts would
  surface per-batch cost in the UI. Separate PR.

### Files

- `core/vision_preflight.py` — NEW
- `core/vision_circuit_breaker.py` — NEW
- `core/vision_adapter.py` — imports + constants + helpers +
  rewritten `_batch_anthropic` + new `_anthropic_sub_batch` method
- `api/routes/analysis.py` — two new endpoints
- `static/batch-management.html` — banner slot + CSS + poller +
  reset handler
- `core/version.py` — bump to 0.29.9
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No new dependencies. No database migration. No Dockerfile change.
Per-image `retry_count < 3` cap in `analysis_queue` still applies
as the outermost safety net — the 5 layers ensure each of those 3
retries is qualitatively different from the last instead of a
pointless re-send.

---

## v0.29.8 — Stale-error cleanup + filename context + wider preview formats (2026-04-24)

Three follow-ups sparked by a single real-world incident: an operator
opened the v0.29.5 "View analysis result" modal on a Benaroya Hall
photo and saw **both** a clean description ("A large modern
building with a curved glass facade in an urban downtown setting...")
**and** a stale Anthropic 400 Bad Request error from a prior attempt.
Three problems fell out of that one screenshot:

### 1. Stale `error` on completed rows

**Root cause:** `write_batch_results()` in `core/db/analysis.py`
had asymmetric success/failure UPDATE clauses. The failure branch
correctly set `error = ?`; the success branch set
`description`, `extracted_text`, `provider_id`, `model`,
`tokens_used` but didn't touch `error`. A row that failed, retried,
and eventually succeeded kept the old error blob forever.

**Fix:** success UPDATE now includes `error = NULL, retry_count = 0`.

**Migration:** `clear_stale_analysis_errors()` gated by preference
`analysis_stale_errors_cleared_v0_29_8`. Counts and clears rows
matching `status = 'completed' AND error IS NOT NULL` once on
startup. Logged as `migration.clear_stale_analysis_errors_starting`
/ `_complete` / `_noop`. Runs before bulk_files dedup so the UI
reflects correct data immediately after the restart.

### 2. Filename context in Anthropic vision calls

**Root cause:** the Claude API image block (`{"type": "image", ...}`)
has no `filename` field. `_batch_anthropic()` in
`core/vision_adapter.py` was sending just the raw image bytes. The
filename `Benaroya_Hall,_Seattle,_Washington,_USA.creativecommons.jpg`
carried rich context (named building, city, state, license) that the
model never saw.

**Fix:** interleave a plain text block before each image:
```
{"type": "text", "text": "Image 1 filename: Benaroya_Hall,_Seattle,_Washington,_USA.creativecommons.jpg"}
{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}
{"type": "text", "text": "Image 2 filename: ..."}
{"type": "image", ...}
...
{"type": "text", "text": <prompt>}
```

**Updated prompt:**
> If the preceding filename identifies a specific recognizable
> subject (a named building, landmark, event, person, vehicle, or
> piece of equipment) AND the image content is consistent with that
> identification, name the subject in the description (e.g.
> "Benaroya Hall, a concert venue in Seattle"). If the filename and
> the image content disagree, describe what the image actually shows
> and ignore the filename.

The "filename disagrees with image content" escape hatch is
important — filenames can be wrong, stale, or adversarial. The
model is instructed to trust the pixels over the text when they
conflict.

**Scope caveat:** applied only to the Anthropic provider handler
(`_batch_anthropic`). OpenAI, Gemini, and Ollama handlers still
receive the updated prompt text but don't yet interleave per-image
filenames. Follow-up: extend `_batch_openai` / `_batch_gemini` /
`_batch_ollama` to inject filename `text` parts before each
image block.

### 3. Wider preview format coverage

v0.29.7 added TIFF/EPS/WebP. v0.29.8 extends to every photo format
PIL can decode in the base image — zero new dependencies. Source
of truth was a live introspection inside the container:

```python
from PIL import Image; Image.init()
sorted({e for e in Image.EXTENSION if Image.EXTENSION[e] in Image.OPEN})
```

Narrowed that list down to formats operators actually encounter as
photos (dropped video `.mpg`, scientific `.fit/.fits/.hdf`, obscure
`.blp/.mic/.pcd`, Windows-metafile vector `.wmf/.emf`).

**Native (14)**: `.jpg`, `.jpeg`, `.jfif`, `.jpe`, `.png`, `.apng`,
`.gif`, `.bmp`, `.dib`, `.webp`, `.avif`, `.avifs`, `.ico`, `.cur`

**Thumbnail via PIL (23)**: `.tif`, `.tiff`, `.eps`, `.ps`,
`.jp2`, `.j2k`, `.jpx`, `.jpc`, `.jpf`, `.j2c`,
`.ppm`, `.pgm`, `.pbm`, `.pnm`,
`.tga`, `.icb`, `.vda`, `.vst`,
`.sgi`, `.rgb`, `.rgba`, `.bw`,
`.pcx`, `.dds`, `.icns`, `.psd`

(23 thumbnail exts + 14 native = 37 total; some overlaps like
`.icb/.vda/.vst` are Targa aliases so the user-visible distinct
format count is lower.)

The frontend `_IMG_EXT` Set in `static/batch-management.html` was
widened to match — must stay in sync with
`api/routes/analysis.py _ALL_PREVIEW_EXTS`. Both files now carry
comments pointing at each other.

**Still deferred:**
- `.svg` — needs XSS sanitization (SVG can carry inline
  `<script>` and external entity references). Non-trivial —
  requires an SVG sanitizer or a rasterize-to-PNG pass.
- `.heic` / `.heif` — needs `pillow-heif` in `requirements.txt`,
  which triggers an app-layer rebuild and adds a transitive
  dependency on `libheif`. Worth doing but scoped separately.
- `.cr2`, `.cr3`, `.nef`, `.nrw`, `.arw`, `.raf`, `.orf`, `.rw2`,
  `.pef`, `.srw`, `.dng` — RAW camera formats, need `rawpy` or
  `imageio` + a RAW codec. Large dep, uncommon in a document
  conversion pipeline.
- `.psd` multi-layer access — PIL reads the flat composite (good
  enough for preview); `psd-tools` is already installed for Adobe
  L2 indexing and could be used here for layered rendering if ever
  needed.

### Files changed

- `core/version.py` — bump to 0.29.8
- `core/db/analysis.py` — success branch clears `error` +
  `retry_count`
- `core/db/migrations.py` — new `clear_stale_analysis_errors()`
- `main.py` — lifespan calls the new migration
- `core/vision_adapter.py` — default prompt + `_batch_anthropic`
  filename interleaving
- `api/routes/analysis.py` — `_NATIVE_PREVIEW_EXTS` and
  `_THUMBNAIL_PREVIEW_EXTS` expanded with source-of-truth comment
- `static/batch-management.html` — `_IMG_EXT` expanded to match
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No new Python dependencies. No Dockerfile changes. Preview
thumbnailing reuses the v0.29.7 LRU cache + asyncio.to_thread
machinery unchanged.

---

## v0.29.7 — Thumbnail preview for TIFF, EPS, and WebP (2026-04-24)

The hover preview feature (inherited with the batch-management page in
v0.24.0 Spec B) silently lied about its format support. The
frontend `_IMG_EXT` whitelist included `.tif/.tiff/.eps`, so hovering
a row with those extensions fired the 250ms open timer and
dispatched a `/preview` request — but every mainstream browser except
Safari on macOS rejects TIFF in `<img>` tags, and EPS was never
decodable by anything. Both appeared as a brief flicker and then
nothing, since `img.onerror = hidePreview` swallowed the failure.

### Fix: split the preview path

`api/routes/analysis.py` now has two code paths keyed on the file
extension:

```python
_NATIVE_PREVIEW_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
_THUMBNAIL_PREVIEW_EXTS = {".tif", ".tiff", ".eps"}
```

**Native** extensions stream as `FileResponse` the same way they did
before — no regression, no added compute.

**Thumbnailed** extensions open the file with PIL, thumbnail to 400px
on the longest edge via `Image.LANCZOS`, convert to JPEG-safe mode
(RGB — EPS can arrive as CMYK, TIFF often as LA/P/I;16), and save as
a quality-78 optimized JPEG. EPS support is free: PIL's
`EpsImagePlugin` shells out to `/usr/bin/gs` which is already in
`Dockerfile.base` (Ghostscript 10.05.1 verified).

All PIL work runs in `asyncio.to_thread(_generate_thumbnail_sync, path)`
so a slow render (large TIFF, complex EPS) never blocks the event
loop. First-import of `PIL.Image` is also deferred so module load
cost only hits the first preview request, not every startup.

### LRU cache

A module-level `OrderedDict` keyed on
`(source_file_id, stat.st_mtime_ns, stat.st_size)` holds the last 64
generated thumbnails (roughly 13 MB ceiling at 200 KB average).
Hits use `move_to_end` (standard LRU dance); evictions
`popitem(last=False)`. Rationale for a plain dict rather than
`functools.lru_cache`: the async call path can't decorate easily, and
the key needs to invalidate on file edit — which the explicit tuple
captures. Also any edit to the file bumps `st_mtime_ns` and the key
changes, so stale thumbs are never served.

Response carries `Cache-Control: private, max-age=300` so browsers
also cache short-term, cutting even the backend round-trip for the
common "hover the same file three times in a minute" case.

### Failure path

Thumbnail exceptions are caught and re-raised as HTTP 500 with the
original class + message embedded, plus a
`analysis.thumbnail_generation_failed` structlog line with path and
`source_file_id`. No silent `500` with nothing in logs — the root
cause shows up in both places.

### Frontend

`_IMG_EXT` was widened to include `.webp` so the hover symmetry with
the backend is preserved. TIFF/EPS were already in the set; they
used to silently fail, now they actually work. No new UI state — the
existing `<img>` approach just now gets JPEG bytes for previously
broken formats.

### Security / resource posture

No new attack surface. PIL's default decompression-bomb thresholds
(89 MP warn, 178 MP error) still apply. The 400px thumbnail ceiling
bounds output size at ~200 KB worst case. The LRU cache is
memory-only, scoped per-process, and bounded. Ghostscript runs as
the container's app user (same privileges as the rest of MarkFlow)
and only processes files already validated by
`is_path_under_allowed_root` in the existing `_lookup_source_path`
helper.

### Why not SVG / HEIC / PSD too

- **SVG**: browsers render natively, but SVGs can contain `<script>`
  or XXE payloads — safely serving them inline wants an SVG
  sanitizer (`lxml` + allowlist) or a rasterization pass. Out of
  scope for v0.29.7; revisit if SVG sources start showing up in
  the analysis queue.
- **HEIC/HEIF**: requires `pillow-heif` in `requirements.txt` —
  adds a dependency and base-image rebuild. Defer until actual
  HEIC sources land.
- **PSD/AI/INDD**: already handled by the Adobe L2 indexing
  pipeline with its own rasterizer. The analysis-queue preview is
  for image-analysis items only, which by design are raster
  formats.

### Files changed

- `core/version.py` — bump to 0.29.7
- `api/routes/analysis.py` — new preview helpers + LRU cache +
  rewritten `preview_file` endpoint (~95 lines added)
- `static/batch-management.html` — added `.webp` to `_IMG_EXT`;
  comment now cross-references the backend constant
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No database migration. No new Python dependency. No Dockerfile change.

---

## v0.29.6 — Multi-file download on Batch Management (2026-04-24)

Closes the obvious gap in v0.29.5: the per-row context menu didn't
account for the fact that the page already has a multi-select
checkbox column. You could bulk-exclude but not bulk-download — even
though operators reviewing a batch are usually triaging multiple
images at once, not one.

### What's new

- **Bulk toolbar button**: the "Exclude Selected" row above each
  file table now also has a **Download Selected (N)** button.
  Activates once any checkboxes are checked; the count in parens
  reflects only rows that have a valid `source_file_id` (rows
  without one can't hit the download endpoint — usually because the
  corresponding `source_files` row was purged).
- **Context menu (v0.29.5) integration**: right-clicking any file
  row while 1+ rows are selected prepends a "Download selected (N)"
  item at the top of the menu with its own separator group. This
  mirrors standard file-explorer convention — a context menu opened
  over a multi-select operates on the selection, not just the
  right-clicked row.
- **Cap + stagger**: each triggered download is a synthetic
  `<a download>` click. To avoid saturating the browser's download
  manager, the click loop `await`s 120 ms between each trigger. Hard
  cap at **100 files per invocation**; exceeding it surfaces an
  error toast asking the user to narrow the selection.
- **Pending pseudo-batch** rows participate: the `__fileMap` on the
  tbody is extended on every "Load more" paginator so that rows
  loaded after the initial 100 still resolve to their full file
  object for the multi-download lookup.

### Why synthetic clicks instead of a server-side zip

The minimal path. A server-side zip endpoint would be cleaner UX
(single downloaded archive), but:

- It requires streaming to avoid buffering many GB in memory for a
  large selection.
- It adds a second file-serving path to security-review
  (path-safety, auth scoping, rate limits).
- It duplicates the download endpoint's MIME + content-disposition
  handling.

For v1 the client-side approach is enough — browsers handle it
natively, the first download triggers a "allow multiple?" permission
prompt that then grants the rest, and the existing `/download`
endpoint is already audit-logged per request. If the operator
workload ever shifts to "download 500+ files at once," a server-side
zip endpoint is a reasonable v2.

### Implementation notes

- **`getSelectedFilesFromTbody(tbody)`** — walks `tbody.__fileMap`
  against `:checked` checkboxes and returns the full file-object
  array. Avoids re-querying the backend for selection state.
- **`downloadSelectedFiles(files)`** — filters to rows with
  `source_file_id`, applies the 100-file cap, confirms with the user
  (message calls out the browser's multi-download prompt), then
  iterates with `await new Promise(r => setTimeout(r, 120))` between
  clicks.
- **`showContextMenu(x, y, f, onAfterExclude, tbody)`** — new
  `tbody` parameter. When non-null and selection > 0, prepends the
  download-selected menu item.
- **`renderFileRow(f, updateSel, tbody)`** — new `tbody` parameter,
  threaded through to the contextmenu handler. Both call sites
  updated (`renderFileTable` + `loadPendingFiles` Load-more path).

### Files changed

- `core/version.py` — bump to 0.29.6
- `static/batch-management.html` — two new helpers, three updated
  functions, one new toolbar button (~65 lines of JS + a tiny
  flex-gap tweak)
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No backend change. No database migration. No new dependency.

---

## v0.29.5 — File-row context menu on Batch Management (2026-04-24)

Builds on the v0.29.4 clickable-counter filters. Right-click any file
row to reach per-file actions inline, without hunting across columns
or leaving the page.

### Menu items

| Item | Action | Notes |
|------|--------|-------|
| Open in new tab | Opens the preview URL (images) or download URL (other types) in a new tab | Browser back button returns to the Batch Management page at the same scroll position |
| Download | Triggers a default-location download | Uses existing `/api/analysis/files/:id/download` |
| Save as… | Chromium File System Access API `showSaveFilePicker()` | Non-Chromium browsers fall back to Download + a toast explaining the fallback |
| Copy path | Full `source_path` to clipboard | Clipboard API with `execCommand('copy')` fallback for non-secure contexts |
| Copy source directory | Parent directory path to clipboard | Same copy path |
| View analysis result | Modal showing `description` + `extracted_text` + model metadata (completed), error text (failed), or status note | Fetches `/api/analysis/queue/:id` |
| Exclude from analysis | Same as the existing Action-column button | Duplicated here for flow; confirms via `confirm()` then refreshes counts + batch list |

### Implementation notes

- **One new backend endpoint**: `GET /api/analysis/queue/{entry_id}`
  returns the full `analysis_queue` row (description, extracted_text,
  error, model metadata, retry_count). OPERATOR role required. 404 on
  unknown id.
- **CSS** (`static/batch-management.html`): `.bm-ctx` (the menu
  container), `.bm-ctx-item` / `.bm-ctx-sep` / `.bm-ctx-icon` (menu
  rows + separator + icon slot), plus a full modal stack
  (`.bm-modal-backdrop`, `.bm-modal`, `.bm-modal-head`, `.bm-modal-body`,
  `.bm-modal-section`, `.bm-modal-text`, `.bm-modal-err`,
  `.bm-modal-kv`, `.bm-modal-close`).
- **JS**: `showContextMenu(x, y, f, onAfterExclude)` builds the menu
  and positions it inside the viewport (clamps to 4px from each
  edge). Global listeners close the menu on `click`, `scroll`
  (capture), `resize`, and `Escape`. `ctxItem` is a small factory
  that handles icon + label + disabled state + click/keyboard
  activation. `openAnalysisResultModal(f)` renders a section-based
  modal with Esc + backdrop-click-to-close.
- **Design deviations from the original ask**: "View markdown
  directory/files" was replaced with "View analysis result." The
  Batch Management page is for the image-analysis queue
  specifically, which stores its output in DB fields
  (`description`, `extracted_text`), not standalone `.md` files.
  Renaming the menu item matches the actual data model; users
  looking for the *converted-document* markdown would be on a
  different page.
- **XSS-safety**: all user-supplied values (`source_path`, `error`,
  `description`, `extracted_text`) go through `textContent`. No
  `innerHTML` interpolation on fetched data — consistent with the
  XSS-hardening guidance applied in v0.24.0's batch-management
  original and v0.29.1's folder-picker rewrite.
- **Row event**: `renderFileRow` attaches a single `contextmenu`
  listener per `<tr>` that calls `ev.preventDefault()` and opens the
  menu at `ev.clientX/clientY`. The context menu also works on the
  pending pseudo-batch's file rows (v0.29.4 shares `renderFileRow`
  across all file-table contexts).

### Files changed

- `core/version.py` — bump to 0.29.5
- `api/routes/analysis.py` — new `GET /api/analysis/queue/{entry_id}`
- `static/batch-management.html` — menu CSS, modal CSS, ~260 lines
  of new JS
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No database migration. No new dependency. No Python business-logic
change — the endpoint just SELECTs an existing row by id.

---

## v0.29.4 — Clickable status filters on Batch Management (2026-04-24)

Batch Management was a decent operator view as shipped in v0.24.0 —
you could see every batch, expand for files, exclude individual rows.
But the five status counters at the top (Pending / Batched / Completed
/ Failed / Excluded) were plain text: you could *see* that 4542 files
were pending but couldn't *click through* to browse them. On this
install the pending bucket was the largest one and had no UI surface
at all, because pending rows have `batch_id = NULL` and the existing
`/batches` endpoint only returned batched-or-later rows.

### Backend additions

**`core/db/analysis.py`:**

- `get_batches(status_filter: str | None = None)` — when `status_filter`
  is set, the returned `file_count`, `total_size_bytes`, and
  `earliest_batched_at` reflect only rows matching that status, and
  batches with zero matching rows are omitted. The derived `status`
  field on each batch still comes from the full row set so operators
  see the real shape of the batch (a batch with 7 completed + 3 failed
  will still be labeled 'failed' even when the Completed filter is
  active).
- `get_batch_files(batch_id, status_filter: str | None = None)` —
  same filter semantics.
- `get_pending_files(limit=100, offset=0)` — NEW. Returns a paginated
  flat list of rows with `status='pending' AND batch_id IS NULL`,
  plus a `total` for UI pagination. Validates `1 ≤ limit ≤ 500` and
  `offset ≥ 0`.

**`api/routes/analysis.py`:**

- `GET /api/analysis/batches?status=X` — optional status param,
  validated against the canonical `{pending, batched, completed,
  failed, excluded}` set (400 on bad input).
- `GET /api/analysis/batches/{batch_id}/files?status=X` — same
  param, same validation.
- `GET /api/analysis/pending-files?limit=&offset=` — NEW endpoint.
  Both params bounds-checked at the route layer too.

### Frontend (`static/batch-management.html`)

- Counters in the top bar are now `<button class="bm-count-btn">`.
  Each has an `aria-pressed` state and a "Click to filter by X" title.
  Click once → filter active + page reloads; click the same counter
  again → filter cleared. A "Show all" pill appears when any filter
  is active.
- Active-filter state is a single JS variable (`activeStatusFilter`);
  the counters re-render on every `/status` poll so the count numbers
  stay live even while a filter is applied.
- When filtering, a banner above the batch list explains what's being
  shown ("Filtering to completed files (1209 total). Batches shown
  are those containing at least one completed file; file lists inside
  each batch are filtered the same way.").
- **Pending pseudo-batch**: when `activeStatusFilter === 'pending'`,
  the batch list is replaced by a single synthetic card titled
  "Pending (not yet batched)". Expanding it calls `/pending-files`
  with `limit=100 offset=0`, renders the first page, and appends a
  "Load more (N of M)" footer that paginates through the rest. The
  existing `renderFileTable` / `renderFileRow` / preview /
  exclude logic is reused unchanged.
- Expanded batch file lists honor the filter too: opening a batch
  while the Failed filter is active calls `/batches/:id/files?status=failed`,
  so operators only see the rows they care about.

### Why these semantics

Numbers that match when you follow them: the five status counters sum
to the `analysis_queue` row count, and when you click one, the
per-batch counts in the filtered view also sum to that counter. No
arithmetic surprises, no "where did the other 40 files go?" moments.

The derived batch status (`failed` / `batched` / `completed` / `mixed`)
is intentionally NOT recomputed on the filtered subset — if a batch
has 7 completed + 3 failed rows, showing 'completed' next to the
filtered-to-7-completed-rows view would misrepresent the batch's
actual state. Keeping the derivation on the full row set matches the
"show me the real shape" instinct operators need when deciding whether
to cancel or retry.

### Files changed

- `core/version.py` — bump to 0.29.4
- `core/db/analysis.py` — three helpers extended/added
- `api/routes/analysis.py` — two endpoints extended, one new
- `static/batch-management.html` — counter buttons, filter banner,
  pending pseudo-batch, paginated `/pending-files` call, filtered
  batch-file load
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No database migration. No new dependency. No changes to the analysis
worker or the batching queue itself — this release is purely a visibility
and navigation improvement on top of existing data.

---

## v0.29.3 — GPU reservation restored on NVIDIA hosts (2026-04-24)

**Bug class:** silent multi-platform regression. v0.28.0 committed
`docker-compose.override.yml` — intended as a convenience for Apple
Silicon devs who don't have `nvidia-container-toolkit` — but because
Docker Compose auto-merges any file with that exact name, *every host
that pulled main* had its GPU `deploy:` reservation zeroed out via the
override's `deploy: !reset null`. GPU-equipped Windows + Linux hosts
ran on CPU with no warning, and `/api/health` reported
`gpu.ok=false` / `execution_path: container_cpu` despite
`docker run --gpus all nvidia-smi` showing the GPU was fully visible
to Docker.

### Root cause

The v0.28.0 plan at `docs/superpowers/plans/2026-04-22-v0.28.0-polish.md:191`
actually proposed the correct pattern — *"commit a sample as
`docker-compose.override.yml.sample` and gitignore the real one."*
The executor deviated and committed the real file under its auto-loaded
name. No user-visible failure on Apple Silicon (the override was doing
its job there) and no test coverage for "GPU reservation is not
stripped on GPU hosts," so the regression lived through v0.29.0,
v0.29.1, and v0.29.2.

### Fix

- **Renamed** `docker-compose.override.yml` → `docker-compose.apple-silicon.yml`
  via `git mv`. The renamed file is *not* auto-loaded by Docker Compose
  under its new name, so GPU hosts pulling the new main see the base
  compose's GPU reservation only.
- **Gitignored** `docker-compose.override.yml` (added to `.gitignore`
  under a new section documenting the per-machine convention).
- **Updated the three macOS helper scripts** (`Scripts/macos/{refresh,reset,switch-branch}.sh`)
  to auto-seed `docker-compose.override.yml` from the sample if it
  doesn't already exist. Idempotent — existing customized local
  copies are preserved across runs.
- **Sample file header** rewritten to explain the new workflow and
  reference this v0.29.3 regression + fix, so future maintainers don't
  re-make the mistake.

### Activation (per machine)

| Host type | Action needed |
|---|---|
| Apple Silicon / no-GPU | Run any `Scripts/macos/*.sh` script once — it auto-seeds the override. Or manually: `cp docker-compose.apple-silicon.yml docker-compose.override.yml`. |
| Linux + nvidia-container-toolkit | Nothing. Pull, then `docker-compose up -d --force-recreate markflow markflow-mcp`. |
| Windows Docker Desktop + WSL2 GPU | Same as Linux+NVIDIA: just recreate. |

A `docker-compose up -d` alone is **not** sufficient on a host whose
currently-running container was created with the stale (overridden)
compose config — volume/deploy changes require `--force-recreate`.

### Verification recipe

```bash
# Confirm GPU is visible to Docker at the host level
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi

# Confirm compose config now includes the deploy block for markflow
docker-compose config | grep -A 10 "^  markflow:" | grep -A 6 deploy
#   -> should show reservations / devices / driver: nvidia / count: 1 / capabilities: [gpu]

# Recreate and verify
docker-compose up -d --force-recreate markflow markflow-mcp
curl -sS http://localhost:8000/api/health | python -c 'import sys,json;d=json.load(sys.stdin);print(d["components"]["gpu"])'
#   -> should show ok=true / execution_path=container_gpu / vendor=nvidia
```

### Gotcha added

`docs/gotchas.md` → Container & Dependencies: first bullet now calls
out that `docker-compose.override.yml` is per-machine and that a stray
committed override is the first suspect when GPU reservations go
missing. Includes the `docker-compose config | grep -A 8 deploy:`
verification command.

### Files changed

- `core/version.py` — bump to 0.29.3
- `docker-compose.override.yml` → `docker-compose.apple-silicon.yml`
  (renamed; new header explains the sample workflow)
- `.gitignore` — adds `docker-compose.override.yml`
- `Scripts/macos/refresh-markflow.sh`, `reset-markflow.sh`,
  `switch-branch.sh` — auto-seed the override from the sample
- `CLAUDE.md` — Current Version block
- `docs/gotchas.md` — new Container & Dependencies bullet
- `docs/version-history.md` — this entry

No Python code changed. No database migration. The fix is a rename + a
gitignore entry + three shell-script edits, but the impact is every
NVIDIA host in this project's installed base getting its GPU back.

---

## v0.29.2 — Drive mounts writable for output paths (2026-04-24)

Tiny compose change with outsized UX impact. Makes drive-letter paths
(e.g. `/host/d/markflow-output`) valid output destinations instead of
only source destinations, removing a mount-flag vs. write-guard
inconsistency that dates back to pre-v0.25.0.

### What was broken

After v0.29.1 landed the inline path-verification pill, the first thing
it surfaced on a real test machine was: picking `/host/d/Doc-Conv_Test`
as the output directory fails with "MarkFlow can't write to this
folder — check permissions" — even though D:\Doc-Conv_Test on the
Windows host is a perfectly writable folder.

### Root cause

`docker-compose.yml` mounted the drive-browser volumes as read-only:

```yaml
- ${DRIVE_C:-C:/}:/host/c:ro    # Drive browser — C:
- ${DRIVE_D:-D:/}:/host/d:ro    # Drive browser — D:
```

That was correct in the pre-v0.25.0 model where the container layer
itself was the enforcement barrier. v0.25.0 introduced the Universal
Storage Manager + the broad `/host/rw` mount (also in
`docker-compose.yml`), with the app-level write guard
(`core/storage_manager.is_write_allowed`) as the sole enforcement
mechanism — documented as such in the compose file's DANGER comment.

The `:ro` on the drive-browser mounts was not updated to match the
new model, so drive paths went through the *old* enforcement path
(kernel-level `:ro`) while `/host/rw/...` paths went through the new
path (app-level write guard). Two mounts, two policies, for the same
underlying filesystem on the host.

Empirical confirmation (from the test machine):

```
touch /host/d/.markflow-write-test           → Read-only file system
touch /host/rw/mnt/host/d/.markflow-write-test → OK
```

Both paths map to the same `D:\...` location on Windows.

### Fix

Drop `:ro` from the two drive-browser volume lines in
`docker-compose.yml`. The app-level write guard now governs writes to
`/host/c` and `/host/d` just as it already does for `/host/rw` — there
is now a single enforcement model across all host mounts, with
`tests/test_write_guard_coverage.py` enforcing that no converter or
bulk_worker write site bypasses the guard.

```yaml
# v0.29.2: drive mounts are writable. The app-level write guard
# (core/storage_manager.is_write_allowed) is the sole barrier — same
# enforcement model as /host/rw above. Previously `:ro`, which blocked
# users from picking a drive path (e.g. /host/d/Doc-Conv_Test) as the
# configured output directory even though the write guard would have
# permitted it.
- ${DRIVE_C:-C:/}:/host/c     # Drive — C:
- ${DRIVE_D:-D:/}:/host/d     # Drive — D:
```

### Activation

Volume-flag changes don't take effect on a plain `docker-compose up
-d` — the existing container still has the old mount flags frozen
until recreate. Correct command:

```bash
docker-compose up -d --force-recreate markflow
```

### Security posture

Unchanged in practice. The `:ro` flag was functionally redundant once
v0.25.0 shipped `is_write_allowed`, since any write attempt on a read-
only FS would fail whether the app guard approved it or not. Removing
`:ro` does not expand the set of writes the app performs — only the
set of *targets a user can configure as the output directory*. The
write guard still allows writes only inside that configured directory.

If an operator configures an outright dangerous output path (e.g.
`/host/d/Windows/System32`), the write guard will dutifully allow
writes there — this was already true for `/host/rw/...` paths and is
accepted as the tradeoff of the v0.25.0 model. The hardening required
to catch that class of mistake (allowed-root allowlist, path-prefix
denylist, etc.) would be a separate effort against
`core/storage_manager.py` and would apply to both mount families.

### Docs

- `docs/drive-setup.md` — walkthrough now shows writable volumes; new
  "As of v0.29.2 you can pick an output folder directly on a mounted
  drive" note under Output Folder
- `docs/gotchas.md` → Container & Dependencies — new first bullet
  calling out that mount flags are no longer the backstop
- `CLAUDE.md` — Current Version block, v0.29.1 demoted to secondary
  section

### Files changed

- `core/version.py` — bump to 0.29.2
- `docker-compose.yml` — `:ro` removed from `/host/c` and `/host/d`;
  commentary explaining why
- `docs/drive-setup.md` — walkthrough + Output Folder note
- `docs/gotchas.md` — Container & Dependencies gotcha
- `CLAUDE.md` — Current Version block
- `docs/version-history.md` — this entry

No code change. No migration. No new dependency. One-line compose
change + paperwork.

---

## v0.29.1 — Folder-picker fix + inline path verification (2026-04-24)

Small but high-value UX polish on the Storage page. Two related pieces
of the "can I actually use MarkFlow's output?" feedback loop were
broken or missing — both fixed in this release.

### Folder-picker: `output` mode now shows drives

**Bug:** On the output-folder picker, the `DRIVES` sidebar (C:, D:) was
hidden entirely, leaving only a single "Output Repo" shortcut. Users
could not navigate to a local filesystem drive to pick it as the output
directory.

**Root cause:** `_renderDrives()` in `static/js/folder-picker.js`
short-circuited for `mode === 'output'` and rendered the Output Repo
button alone, returning before the drives loop ran. The existing `any`
mode already rendered drives + an Output Repo shortcut; output mode
just needed the same treatment.

**Fix:** Removed the output-mode early return. `_renderDrives` now
always renders the Drives section and appends the Output Repo shortcut
when `mode === 'any' || mode === 'output'`. Source mode shows drives
only (unchanged). `open()` still handles mode-based initial navigation
(output mode still lands at `/mnt/output-repo` by default), so nothing
about the default destination changes — users just have a way to leave
it now. Also rewrote the rendering function to use
`document.createElement` + `textContent` instead of `innerHTML` — same
XSS-safety convention used elsewhere in `storage.js`.

**File:** `static/js/folder-picker.js`.

### Inline path verification on Save / Add

**User ask:** "Once the user clicks Save, show the directory as
MarkFlow sees it, below the Path entry box, with a green checkmark
indicating MarkFlow can write / access the selected directory. Do the
same verification for source directories — green checkmark = readable."

**Implementation:** New `renderVerificationAt(container, path, role)`
helper in `static/js/storage.js` that calls the existing
`POST /api/storage/validate` endpoint and renders a verification pill:

```
[✓] /host/d/Doc-Conv_Test
    Writable · 12 items · 42.3 GB free
```

On error (path doesn't exist / not writable / permission denied):

```
[✗] /host/x/missing
    This folder doesn't exist: /host/x/missing
```

Warnings (low disk space, empty source folder, long-path risk) render
in amber below the green-check line.

**Wired into three flows:**
1. `setOutput()` — after the PUT succeeds (or fails with a 400), the
   verification pill renders inline. On HTTP 400, the backend's
   `{errors, warnings}` detail is surfaced as the failure reason — no
   toast/alert needed.
2. `addSource()` — same pattern in the Sources Add form. Result
   persists below the Add form until the next Add.
3. `loadOutput()` — on page load, if an output path is already saved,
   the same verification runs automatically so operators can confirm
   nothing has drifted (share unmounted, permissions changed, etc.).

**Backend:** unchanged. `POST /api/storage/validate` with body
`{path, role: "source" | "output"}` already existed and returns
`{ok, warnings, errors, stats: {item_count, free_space_bytes}}` — the
client just needed to render it.

**Files:** `static/storage.html` (two `<div class="storage-verify">`
slots replacing the old `<p id="output-current">` + a new one under
the Sources Add form), `static/js/storage.js` (helper +
`setOutput` / `loadOutput` / `addSource` updates), `static/markflow.css`
(scoped styles for `.storage-verify` with light + dark variants using
the existing badge-color palette).

### Docs-only piggyback

Parallel to the two Storage fixes, CLAUDE.md's "Running the App"
section was updated to clarify that `Dockerfile.base` changes require
a full base rebuild — the previous wording ("first time only") was
correct-by-omission and bit the v0.28.0 rollout when `cifs-utils` +
`smbclient` additions weren't picked up by an app-layer-only build.
Matching gotcha added to `docs/gotchas.md` → **Container &
Dependencies → Base image rebuild trigger**. Commits: `d934321`
(docs), `4696abd` (folder-picker fix).

### Files changed

- `core/version.py` — bump to 0.29.1
- `static/js/folder-picker.js` — output-mode drive visibility fix
- `static/js/storage.js` — verification helper + wiring
- `static/storage.html` — verification slots
- `static/markflow.css` — `.storage-verify` styles
- `CLAUDE.md` — Current Version block, Running the App clarification
- `docs/gotchas.md` — base-rebuild-trigger gotcha
- `docs/version-history.md` — this entry

No schema migration, no new dependency, no test additions (the bug was
a pure UI regression with no backend surface). Manual browser
verification: the output picker now shows C: + D: alongside Output
Repo; the verification pill renders green for valid paths and red with
the backend's error text for invalid ones.

---

## v0.29.0 — Storage page polish + security hardening pass (2026-04-22)

**Same-day follow-up to v0.28.0.** Polish pass on the Universal Storage
Manager plus eight security-audit items from
[`docs/security-audit.md`](security-audit.md). All work in one autonomous
run planned at
[`docs/superpowers/plans/2026-04-22-v0.28.0-polish.md`](superpowers/plans/2026-04-22-v0.28.0-polish.md).

### Storage page polish

- **Add-Share modal**: replaces the prompt() chain in `storage.js`.
  Proper form with inline pattern validation (name matches `^[A-Za-z0-9_-]+$`),
  protocol radio (smb/nfsv3/nfsv4), show/hide SMB credential fields, submit
  in-flight disable, surface response errors inline instead of via alert().
- **Discovery modal**: two-tab UI (Scan subnet / Probe server). Clicking a
  discovered share opens the Add-Share modal pre-filled with server +
  sanitized share name.
- **Host-OS override dropdown**: Auto / Windows / WSL / macOS / Linux in the
  page header. Persists via `/api/preferences/host_os_override` and re-loads
  Quick Access on change so operators can force a particular OS rendering
  when auto-detection is wrong.
- **Folder-picker buttons**: 📁 next to source-path-input and
  output-path-input open the existing FolderPicker modal. Source defaults to
  `/host/root`; output defaults to `/host/rw`.
- **Cloud Prefetch section** migrated from Settings: 6 existing prefs, one
  "Save" button that writes through `/api/preferences/{key}` and flashes
  "Saved ✓" inline.
- **Settings page retirement**: "Storage Connections" (~139 lines) and
  "Cloud Prefetch" (~61 lines) sections deleted from `static/settings.html`,
  along with the dedicated Storage Connections `<script>` block (~133 lines)
  and the Cloud Prefetch toggle-label JS. The "Files and Locations"
  link-card and prominent "Open Storage Page →" card stay.

### Security hardening — 8 audit findings

- **SEC-C08** (Critical, ZIP path traversal): `_zip_member_is_safe()` rejects
  `..`, absolute paths, and Windows-separator paths before `extract` and
  `extractall` in both `_extract_zip` and `_batch_extract_zip`.
- **SEC-H12** (High, missing security headers): new `_SECURITY_HEADERS` dict
  in `api/middleware.py` sets `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `Permissions-Policy` (no accelerometer / camera / geolocation / microphone /
  payment / USB), and a conservative Content-Security-Policy. Applied via
  `setdefault()` so explicit per-route overrides still win.
- **SEC-H13** (High, weak SECRET_KEY): `main.py` lifespan rejects the
  hardcoded dev default AND anything < 32 chars when `DEV_BYPASS_AUTH=false`.
  In DEV mode the same check warns instead of aborting.
- **SEC-H16** (High, dead cleanup guard): `password_handler.cleanup_temp_file`
  was comparing `result.output_path != result.output_path` (always False) —
  decrypted temp files were never deleted. Fixed with proper realpath
  containment check against `tempfile.gettempdir()`.
- **SEC-H18** (High, insecure tempfile): `libreoffice_helper` replaced
  `tempfile.mktemp()` with `tempfile.mkstemp()` which atomically creates
  and O_EXCL-locks the destination file.
- **SEC-M10** (Medium, unbounded pagination): scanner/runs and
  db/maintenance-log clamp `limit` to [1, 500].
- **SEC-M12** (Medium, zip-bomb check): `check_compression_ratio` (imported
  but never called) now gates every zip extraction on the aggregate ratio
  computed from `infolist()`.
- **SEC-M15** (Medium, world-readable passwords file): archive_handler now
  creates `config/archive_passwords.txt` with 0600 and chmods on every
  append so other host users can't read recovered plaintext passwords.
- **SEC-M21** (Medium, untrusted worker_capabilities.json): new
  `_validate_worker_report` type-checks every field against an expected
  schema; mistyped values are dropped; unknown fields ignored.

### v0.28.0/v0.29.0 self-review (SELF-H1..H4)

- **H1**: `ShareIn.name` enforces `^[A-Za-z0-9_-]+$` at the API layer so
  credentials and mount-point names can't drift out of sync.
- **H2**: `/shares` + `/shares/discover` both reject servers starting with
  `-` so smbclient / showmount / mount.cifs can't interpret them as flags.
- **H3**: new `DiscoverIn` Pydantic model replaces the raw `payload: dict`
  for `/api/storage/shares/discover`.
- **H4**: `add_share` rolls back the just-saved `CredentialStore` entry on
  mount failure so there are no orphan credentials.

### Testing

- **105 storage tests pass** in Docker (mount_manager 47, storage_manager 20,
  host_detector 7, credential_store 7, write_guard_coverage 2, storage_api 22).
- **1297 project tests pass** in Docker (one-shot image without Qdrant /
  Meilisearch / tesseract fixtures). 69 failures are all pre-existing and
  require external services or specific fixtures; none regressed from this
  branch.
- **Live smoke tested**: rebuilt container, probed /api/health, /api/storage/*,
  confirmed security headers in every response, confirmed Pydantic validation
  rejects `../evil` share names (422) and dash-prefixed servers (400).

### Infrastructure

- **`docker-compose.override.yml`**: zeros out the GPU `deploy:` block for
  markflow + markflow-mcp so `docker-compose up` works on Apple Silicon /
  any host without NVIDIA Container Toolkit. Linux developers with GPU
  support delete the file.

### Known deferrals

- **CSP tightening**: current policy uses `'unsafe-inline'` for scripts.
  Removing it requires replacing every `onclick=` handler with
  addEventListener; v0.30.x target.
- **SEC-H02/H01** (serve_source / view_markdown path traversal): these
  need a per-route containment check. Punted to v0.30.x after more
  review of /mnt/source usage.
- **SEC-H07–H11** (XSS via unescaped DOM assignments): frontend refactor
  — separate sprint.

Files changed on this release: `api/middleware.py`, `api/routes/db_health.py`,
`api/routes/scanner.py`, `api/routes/storage.py`, `core/gpu_detector.py`,
`core/libreoffice_helper.py`, `core/password_handler.py`, `core/version.py`,
`formats/archive_handler.py`, `main.py`, `static/app.js`,
`static/js/storage.js`, `static/js/storage-restart-banner.js`,
`static/markflow.css`, `static/settings.html`, `static/storage.html`,
`tests/test_storage_api.py`, `docs/version-history.md`, `CLAUDE.md`,
`docs/superpowers/plans/2026-04-22-v0.28.0-polish.md` (new),
`docker-compose.override.yml` (new).

---

## v0.28.0 — Universal Storage Manager (2026-04-22)

**Problem.** First-time setup required hand-editing `.env` and `docker-compose.yml`
to point MarkFlow at the host filesystem and any network shares. That gate
locked out non-technical users entirely. The plan: replace it with a GUI-driven
Storage page, a first-run wizard, and runtime mount management — so the
onboarding step that used to take an hour of Docker debugging is two clicks.

**Architecture (three layers).**

1. **Docker** grants broad read access (`/host/root:ro`) and writable access
   (`/host/rw`), plus the `SYS_ADMIN` capability so the container can run
   `mount` against SMB/NFS at runtime.
2. **Application code** is the SOLE restriction on the broad `/host/rw`
   mount. `core.storage_manager.is_write_allowed()` gates every file write
   in `core/converter.py` and `core/bulk_worker.py`. Coverage is enforced
   by `tests/test_write_guard_coverage.py` — a static check that fails CI
   if any new write in those modules lands without a guard or an explicit
   `# write-guard:skip` opt-out comment.
3. **Presentation** consolidates storage configuration on a single
   `/storage.html` page with a 5-step first-run wizard overlay.

**Phase 1 (backend).** 13 tasks, 5 new core modules, 1 new route file:

- `core/host_detector.py` — OS detection from `/host/root` filesystem
  signatures (Windows / WSL / macOS / Linux), cached singleton, builds
  OS-appropriate quick-access lists. WSL is checked before plain Linux
  because both have `/etc/os-release`.
- `core/credential_store.py` — Fernet + PBKDF2 (600k iterations, hardened
  in commit `549b43f`) at `/etc/markflow/credentials.enc`, 0600 perms,
  passwords never logged. Wrong key = silently treated as empty store
  (no decryption error surface to operators who fat-fingered SECRET_KEY).
- `core/storage_manager.py` — `validate_path` (async via `asyncio.to_thread`
  to tolerate slow NAS stat), `check_source_output_conflict` (rejects same /
  nested), `is_write_allowed` (realpath-based; defeats symlink escape),
  `load_config_from_db` / `save_output_path` (DB persistence + cache
  invalidation; only flags pending-restart on actual change, not first write).
- `core/mount_manager.py` extended — multi-mount support with v2 schema
  (`{_schema_version: 2, shares: {...}}`, idempotent migration from v1),
  `share_mount_point()` sanitizer (strips non-alphanumeric except `-_`),
  `mount_named` / `unmount_named` for `/mnt/shares/<name>`, network
  discovery (`smbclient -L`, `showmount -e`), `discover_smb_servers`
  caps subnet scan at 256 hosts, `remount_all_saved` for lifespan startup,
  `check_mount_health` writes module-level `mount_health` dict.
- `api/routes/storage.py` — `/api/storage/*` consolidated surface
  (host-info, validate, sources, output, exclusions, shares, discover,
  test, credentials, health, restart-status, restart-dismiss,
  wizard-status, wizard-dismiss). MANAGER role minimum;
  `/shares/{name}/credentials` is ADMIN-only.
- `core/db/preferences.py` — 8 new defaults (storage_output_path,
  storage_sources_json, storage_exclusions_json, pending_restart_*,
  setup_wizard_dismissed, host_os_override).
- `core/scheduler.py` — `mount_health` job, every 5 minutes, yields to
  active bulk jobs. Job count grows from 17 to 18.
- `main.py` lifespan — `load_config_from_db()` → `remount_all_saved()` →
  `start_scheduler()`, all wrapped in broad `try/except` so a flaky NAS
  cannot block startup.
- Docker (`docker-compose.yml`, `Dockerfile.base`) — broad host mounts,
  `SYS_ADMIN` capability, `smbclient` + `cifs-utils` packages added
  (committed earlier on this branch in `c732b48`, `549b43f`, `b75d42b`).

**Phase 2 (frontend).** 4 new files, 2 modified:

- `static/storage.html` — page scaffolding (collapsible cards, wizard modal).
- `static/js/storage.js` — vanilla fetch + `createElement`/`textContent`
  throughout (never `innerHTML` on fetched data — XSS-safety per CLAUDE.md
  gotcha). Wizard is a 5-step overlay with per-step validation against
  `/api/storage/validate`.
- `static/js/storage-restart-banner.js` — amber sticky banner. Polls
  `/api/storage/restart-status` every 60s. "Remind me later" snoozes for
  1 hour. The banner is injected via a `<script>` tag dynamically appended
  at the end of `app.js`'s `DOMContentLoaded` handler — that way every
  page that loads `app.js` also gets the banner without editing 20+ HTML
  files.
- `static/app.js` — Storage nav item (MANAGER+); restart-banner loader.
- `static/markflow.css` — quick-access grid, mount status dots,
  wizard modal, amber restart banner, discovery result panel.

**Phase 3 (migration & polish).**

- `static/settings.html` — prominent "Open Storage Page →" link card at
  top. Existing storage-related sections (Locations, Storage Connections,
  Cloud Prefetch) left in place for backward compatibility. Pragmatic
  deviation from the plan, which called for full removal: dual-path during
  the transition release. v0.29.x can prune the legacy sections once UI
  parity is proven.
- `api/routes/browse.py` — clarifying comment on `ALLOWED_BROWSE_ROOTS`:
  `/host` already prefix-covers `/host/root` and `/host/rw`; the write
  restriction is the storage_manager guard, NOT the browse allow-list.
- `tests/test_storage_api.py` — 9 integration tests against the FastAPI
  TestClient with `DEV_BYPASS_AUTH=true` for in-process auth bypass.
- `docs/help/storage.md` — end-user help article (registered in
  `docs/help/_index.json` under Configuration).
- `docs/gotchas.md` — new "Universal Storage Manager (v0.28.0)" section
  with 7 hard-won lessons (write-guard coverage, SYS_ADMIN requirement,
  SECRET_KEY rotation, v1→v2 migration, regex coverage gap on `shutil.copy2`,
  preferences read/write split, `get_mount_manager()` singleton).
- `docs/key-files.md` — entries for the 4 new core modules, the new
  route file, and 3 new static files.

**Version note.** The plan called for v0.25.0 but that version was already
shipped (EPS rasterization, commit `e4a5a9d`). Bumped to **v0.28.0**.

**Tests.** 83 unit tests pass on a host venv (mount_manager: 47,
storage_manager: 20, host_detector: 7, credential_store: 7,
write_guard_coverage: 2). Integration tests in `test_storage_api.py`
run inside the Docker container.

**Known follow-ups for v0.29.x.**

1. Move Cloud Prefetch UI from Settings to the Storage page so the legacy
   Settings sections can be safely deleted.
2. Replace the prompt-based add-share/discovery flows with proper modal
   forms — current implementation uses `prompt()` calls which are functional
   but unpolished.
3. Expose `host_os_override` in the Storage page UI (DB pref already exists).
4. End-to-end test in Docker with a real SMB server; staged-live verification
   of `remount_all_saved` after `SECRET_KEY` rotation.

---

## v0.27.0 — Search latency fixes for CPU-only hosts (2026-04-14)

Hybrid (keyword + vector) search on this CPU-only VM took ~14s for
a novel query because a single `sentence-transformers` embed runs
for ~10–12s on CPU. Worse, the embed was a *synchronous* CPU call
inside an async request handler — it blocked the event loop so
every other concurrent request on the server stalled for the
duration. Three changes.

### Change 1 — Query-embedding LRU cache (`core/vector/embedder.py`)

Added `LocalEmbedder.embed_cached(text)` backed by an `OrderedDict`
LRU of size `QUERY_EMBED_CACHE_SIZE` (default 256). Cache is
keyed on `(model_name, text)` so exact-repeat queries after the
first one are effectively free (~0ms vs ~10s). Hit / miss counters
log every 25 lookups at INFO level (`embedder_cache_stats`).

Multi-text batch embeds used by the indexer bypass the cache; only
the query-search path calls `embed_cached`.

### Change 2 — Offload embed to worker thread (`core/vector/index_manager.py`)

`VectorIndexManager.search` previously called
`self._embedder.embed([query])[0]` synchronously. Now wraps it in
`asyncio.to_thread(self._embedder.embed_cached, query)`. The
10-second embed no longer blocks the event loop, so other requests
(health checks, admin jobs, AI Assist SSE, status polling) stay
responsive during search.

### Change 3 — Skip hybrid for confident keyword queries (`api/routes/search.py`)

Introduced a `_keyword_is_confident(query, hits)` heuristic that
short-circuits the vector path when the keyword layer already has
a clean answer:

- Explicit opt-out: `?hybrid=0` query param.
- Implicit: quoted exact-match queries (`"2022 report"`).
- Implicit: single-token query that already produced ≥5 keyword
  hits — Meilisearch is confident, the embed would add latency
  for no ranking gain.

Conservative on purpose: multi-word conversational queries still
always trigger hybrid, which is where semantic search pays off.

### Expected user impact

- First-time search for a novel query: unchanged (~14s).
- Second search with the same (or identical) query: ~200ms
  (cached embed + Qdrant lookup + RRF merge).
- Keyword-obvious queries (`"Ryan Paddock"`, `picnic`): ~200ms
  regardless, because hybrid is skipped entirely.
- Concurrent requests during a search: no longer stall for the
  duration of the embed.

### Files touched

- `core/vector/embedder.py` — `embed_cached` method, LRU, stats
  counters, doc block update.
- `core/vector/index_manager.py` — `asyncio.to_thread` wrapper
  around the query embed.
- `api/routes/search.py` — `hybrid` query parameter,
  `_keyword_is_confident` heuristic, skip path with debug log.
- `core/version.py` → `0.27.0` (minor bump — architectural change
  to search hot path).

---

## v0.26.0 — Vector hit preview enrichment + AI snippet field aliasing (2026-04-14)

User reported that AI Assist consistently replied with "no preview
text is available for any of the matched documents" when
synthesizing across hybrid (keyword + vector) search results, even
when the underlying documents had rich, useful content. Two
overlapping root causes in the search → AI pipeline.

### Root cause A — vector-only hits carried no content

`core/vector/hybrid_search.py::rrf_merge` built the metadata dict
for a vector-only hit from just `title`, `source_index`,
`source_path`, and `source_format`. The Qdrant payload actually
includes `chunk_text` (the raw text of the chunk that matched the
query vector) plus `heading_path`, but the merge function dropped
both. Downstream consumers — Meilisearch-only UI, AI Assist,
source cards — therefore saw a filename with no content.

### Root cause B — AI prompt looked for field names that didn't exist

`core/ai_assist.py::_build_snippet_prompt` read
`r.get("snippet") or r.get("_formatted", {}).get("content")`.
Neither field is produced by `/api/search/all`; the search API
emits `content_preview` and `highlight` (from Meilisearch) and
now `chunk_text` (from the vector path, via rrf_merge). Every
result ended up on the `(no preview available)` branch even for
documents that had well-formed previews. The `sources` event
emitted at the end of the stream had the same problem for
`file_type` and `path` — old field names, empty fallbacks.

### Fix

- **`rrf_merge` vector-only branch** — now carries
  `content_preview`, `highlight`, `format`, `heading_path`, and a
  debug `_preview_source: "vector_chunk"` marker. Keyword hits that
  happen to have an empty preview also fall back to the vector
  chunk when one is available.
- **`_build_snippet_prompt`** — reads preview across a five-alias
  chain (`content_preview` → `highlight` → `snippet` →
  `chunk_text` → `_formatted.content`), title across three, and
  file_type across four. The 600-char truncation and
  `DEFAULT_MAX_SNIPPETS=8` cap are unchanged.
- **Sources event** — same alias fallbacks applied, so the drawer's
  source-list tooltips and the "Read full doc" handler get real
  paths and doc_ids for both keyword and vector hits.

### Expected user impact

- AI Assist responses now reference actual document content rather
  than pure filenames. Business cards, event flyers, newsletter
  articles all gain preview text in Claude's context.
- Semantic queries like *"pictures of business cards"* should
  surface `Ryan Paddock.jpg` (a vision-analysed JPG whose chunk
  text says "A business card placed on a lined notebook") via the
  vector path, because the document's chunk text now reaches the
  ranked list instead of being stripped.

### Files touched

- `core/vector/hybrid_search.py` — extended vector-only metadata,
  keyword-with-empty-preview fallback.
- `core/ai_assist.py` — `_build_snippet_prompt` + `sources` event
  field aliasing.
- `core/version.py` → `0.26.0` (minor bump — user-visible ranking
  and AI output changes).

---

## v0.25.3 — AI Assist UX polish (2026-04-14)

Targeted fixes to make AI Assist interactions unmissable.

### Changes

- **"Synthesize these results" click feedback.** On click the button
  now disables, changes label to "Opening…", and pulses until either
  the drawer opens (handler replaces it) or a 1.5s safety timeout
  restores it. Previously the button appeared to do nothing because
  the drawer slides in 400px from the right and on wide monitors the
  user's eye stays on the results — no acknowledgement of the click.
- **Drawer "just-opened" flash.** When the drawer first slides in it
  briefly paints a 2px accent-colored left edge (600ms), so peripheral
  vision catches the motion.
- **Toggle pulse.** Clicking the AI Assist on/off toggle now scales +
  ring-pulses briefly, confirming the state change.
- **Reduced-motion respected.** All three animations are disabled
  under `prefers-reduced-motion: reduce`.

### Files touched

- `static/js/ai-assist.js` — runBtn click wrapper, openDrawer
  flash class, toggle pulse trigger.
- `static/css/ai-assist.css` — `.is-running`, `.just-opened`,
  `.pulse` keyframes + reduced-motion guard.
- `core/version.py` → `0.25.3`.

---

## v0.25.2 — Fix AI Assist init race (2026-04-14)

`ai-assist.js` was logging `AIAssist: required DOM elements not
found` on every search page load. Root cause: the inline
`<script>` block in `static/search.html` called `AIAssist.init()`
synchronously during HTML parsing at line ~1045, but the
`<aside id="ai-assist-drawer">` element it looks up lives at
line ~1253 — below the script. At init time the drawer hadn't
been parsed yet, so `getElementById('ai-assist-drawer')` returned
null, `init()` bailed at its null-guard, and click handlers for
the **AI Assist toggle** and **"Synthesize these results"** run
button were never attached. Both buttons rendered but silently
did nothing.

### Fix

Wrap `AIAssist.init()` in a `DOMContentLoaded` listener when
`document.readyState === 'loading'` (otherwise call it directly).
This is a one-branch guard — no HTML reorganization needed, and
it tolerates future inline-script moves without silently
reintroducing the bug.

### Notes

- Backend and CSS were never the problem. `/api/ai-assist/status`
  returned `enabled: true` and the SSE stream at
  `/api/ai-assist/search` produced Claude output on direct POST.
- This has been broken since the drawer element was added;
  nobody caught it because the only visible symptom is a single
  `console.warn` that's trivial to miss.

---

## v0.25.1 — Search responsiveness feedback (2026-04-14)

User reported that hitting Enter on a plain keyword search (e.g.
"photos") produced no visible UX response — the page went blank
until results landed, which felt broken even when the underlying
Meilisearch query finished in <200 ms. Root cause was `doSearch()`
in `static/search.html` hiding every results element at the top of
the function and only restoring them on response, with no progress
indicator in between.

### Fix

- **Top-bar progress indicator.** New `#search-progress` element
  (2px accent-colored bar, indeterminate slide animation, respects
  `prefers-reduced-motion`) sits above the results area and toggles
  visible for the duration of the fetch.
- **Dim, don't hide.** `doSearch()` no longer clears the prior
  results card / toolbar / empty-state. Instead it adds an
  `.is-searching` class (opacity 0.5, `pointer-events: none`) so
  the user keeps context while the new results load. On success
  the new results replace the old in place; on error the old
  results reappear un-dimmed.
- **Stale-response guard.** Added a monotonic `_searchSeq`
  counter. If the user hits Enter twice quickly, the late-arriving
  response from request #1 is discarded instead of overwriting
  the fresher results from request #2. This bug was latent
  before — invisible in dev, visible in production with variable
  network latency.

AI Assist behaviour is unchanged. The drawer only auto-opens when
the user has explicitly flipped the toggle on (persisted in
`localStorage['markflow_ai_assist_enabled']`), so plain keyword
searches never trigger an LLM call unless asked.

### Files touched

- `static/search.html` — CSS for `.search-progress` and
  `.is-searching`, new `<div id="search-progress">`, rewritten
  `doSearch()`.
- `core/version.py` — bump to `0.25.1`.
- `docs/help/whats-new.md`, `docs/help/search.md` — user-facing
  notes.

---

## v0.25.0 — EPS rasterization + vision MIME allow-list (2026-04-14)

Two overlapping bugs in the analysis worker surfaced during a
production drain against Anthropic. Both produced HTTP 400s that
cascaded into `analysis_queue` failures for entire file classes.

### Root causes

**Upstream (bug A):** `.eps` was in `_IMAGE_EXTENSIONS` in both
`core/db/analysis.py` and `core/bulk_worker.py`, so the scanner
enqueued EPS files with `file_category='image'`. The vision adapter's
`detect_mime()` returned `application/postscript`, which does not
start with `image/`, so `_compress_image_for_vision` fell through
the `else` branch and defaulted `mime = "image/png"`. For files
under the 3.5 MB raw threshold, raw PostScript bytes were then sent
to Anthropic tagged as `image/png` — rejected with
`"Could not process image"`.

**Adapter (bug B):** The raw-passthrough fast path
(`if len(raw) <= _ANTHROPIC_MAX_IMAGE_RAW_BYTES: return raw, mime`)
never verified that `mime` was in the provider's allow-list. Small
BMP/TIFF files slipped through with `image/bmp` / `image/tiff`,
producing the distinct error
`messages.0.content.1.image.source.base64.media_type: Input should
be 'image/jpeg', 'image/png', 'image/gif' or 'image/webp'`.

### Fix

- **New: `core/vector_rasterizer.py`** — `rasterize(source, content_hash)`
  renders EPS/AI/PS via async Ghostscript (`gs -dNOPAUSE -dBATCH -dSAFER
  -sDEVICE=png16m -r150 -dFirstPage=1 -dLastPage=1`) and PSD/PSB via PIL
  composite. Cache keyed by content_hash at
  `/app/data/vector_cache/<hash>.png`; fallback key is
  `sha256(abspath)` when content_hash is unavailable.
- **`core/db/analysis.py`** — split `_IMAGE_EXTENSIONS` (raster only) from
  new `_VECTOR_IMAGE_EXTENSIONS = {".eps"}`; added
  `is_vector_image_extension()`; parameterized `enqueue_for_analysis` with
  `file_category: str = "image"`; `claim_pending_batch` now selects
  `file_category` too.
- **`core/bulk_worker.py`** — removed `.eps` from `_IMAGE_EXTENSIONS_BW`,
  added `_VECTOR_IMAGE_EXTENSIONS_BW`, added `_analysis_category()` helper;
  caller passes `file_category` through.
- **`core/analysis_worker.py`** — before `describe_batch`, iterate claimed
  rows and rasterize any with `file_category='vector_image'` or
  `is_rasterizable(source)` to the cached PNG. Per-item rasterization
  failures write through `write_batch_results` without wasting the
  Anthropic API call; the rest of the batch proceeds.
- **`core/vision_adapter.py`** — added
  `_VISION_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/gif",
  "image/webp"}`; the raw-passthrough fast path now requires MIME to be
  in the allow-list. Anything else falls through to the existing PIL
  decode + JPEG re-encode path, regardless of raw size.

### Migration

Applied directly to prod DB on upgrade (not a schema migration — data
rehydration only):

```sql
UPDATE analysis_queue
  SET file_category='vector_image'
  WHERE LOWER(source_path) LIKE '%.eps'
     OR LOWER(source_path) LIKE '%.ai'
     OR LOWER(source_path) LIKE '%.ps'
     OR LOWER(source_path) LIKE '%.psd'
     OR LOWER(source_path) LIKE '%.psb';

UPDATE analysis_queue
  SET status='pending', retry_count=0, batch_id=NULL, batched_at=NULL, error=NULL
  WHERE status='failed';
```

363 rows re-tagged `vector_image`; 140 prior failures flipped back to
pending for re-processing through the new path.

### Verified

Four drain cycles against live Anthropic after deploy:

| Drain | Content | Result |
|---|---|---|
| 1 | 10 BMPs (Blender freestyle brushes) | 10/0 — PIL re-encode |
| 2 | 10 mixed (6 EPS, 2 JPEG, 2 others) | 10/0 — mix of GS raster + PIL recompress |
| 3 | 10 EPS (Logo_multipanel series) | 10/0 — GS raster |
| 4 | 10 mixed | 10/0 |

Cache after test: 17 PNGs / 5.6 MB.

### Rule of thumb

API providers stack validation layers (envelope size check + per-image
size check + MIME allow-list). An envelope check is necessary but not
sufficient; MIME validation must happen before the bytes cross the wire,
not after. Both pieces were present in the code but had gaps — upstream
trusted the scanner, adapter trusted upstream. Defense in depth required
fixing both.

---

## v0.24.2 — Hardening pass (2026-04-13)

A batch of small, surgical fixes across five areas. Output of a
code review + state analysis session that followed the v0.24.1 UX
fix. No new features.

### Security-audit count correction

CLAUDE.md's header row for `docs/security-audit.md` said "3 critical
+ 5 high." The actual doc has **62 findings: 10 critical + 18 high
+ 22 medium + 12 low/info.** Pre-prod blocker unchanged, but the
*size* of the blocker now reflects reality.

### DB backup schema-version guard

`core/db_backup.py` gains `_schema_version_sync` and
`_current_schema_version_sync` helpers and checks the backup's
highest applied `schema_migrations.version` before touching the live
DB. If the backup is newer than the running build knows about, the
restore refuses with `code: "schema_version_newer"`. Older backups
are still allowed — the migration runner brings them forward at
init. Catches a failure mode where `integrity_check` passes but the
first migration-dependent query crashes.

### PPTX pref read no longer bypasses the pool

`formats/pptx_handler._read_chart_mode_pref` was opening a raw
`sqlite3.connect` on every PPTX ingest. Now reads through the
in-memory preferences cache (new `peek_cached_preference` sync
helper added to `core/preferences_cache.py`). On a cold cache, a
one-time sync sqlite read warms the cache and all subsequent
conversions hit memory only. Low-volume issue in practice (the
old path was read-only), but it was one of several inconsistent
patterns for reading prefs from sync code, and the pattern was
spreading.

### Whisper inference serialized — orphan threads can't stack

`core/whisper_transcriber.py` wraps `model.transcribe` in
`asyncio.to_thread`. When the caller wraps that in
`asyncio.wait_for`, a timeout cancels the awaiter but the thread
keeps running until `model.transcribe` returns — Python threads
cannot be cancelled. Two stacked timeouts meant two threads
competing for GPU memory.

Fix uses two locks:
- `threading.Lock` held *inside* the worker thread for the entire
  `model.transcribe` call. An orphan thread from a prior timeout
  holds this until it completes.
- `asyncio.Lock` around the outer `asyncio.to_thread` so concurrent
  awaiters queue at the asyncio layer first.

An honest `whisper_orphan_thread` warning is logged on
`CancelledError` so the operator sees the "GPU still busy" state
rather than a silent resource leak. `orphan_thread_active()`
exposed as a module function for status-page hooks.

### DB contention logging retired

The temporary instrumentation module flagged in v0.19.6.5 is
removed. The "database is locked" bug it was hunting hasn't
surfaced in recent runs and the module was spamming log files at
2.4M+ lines during scans. Changes:

- `core/db/contention_logger.py` — deleted
- `core/db/connection.py` — imports + every `log_acquire` /
  `log_release` / `log_query` / `log_lock_error` call removed;
  `get_db()` and `db_write_with_retry()` back to their original
  lean form
- `main.py` — startup preference apply block removed
- `api/routes/preferences.py` — conditional toggle handler removed
- `api/routes/debug.py` — `/debug/api/contention-logs` endpoint
  removed
- `core/db/preferences.py` — `db_contention_logging` entry removed
  from `DEFAULT_PREFERENCES`
- `static/settings.html` — "Debug: DB Contention Logging" section
  and its ~120-line `contentionViewer` IIFE removed
- `docs/gotchas.md` — the "TEMPORARY" gotcha now documents the
  retirement; if lock contention reappears, add short-lived
  structured logging rather than reintroducing the full module
- `docs/key-files.md` — row removed

Log files on disk (`db-contention.log`, `db-queries.log`,
`db-active.log`) are orphaned but not deleted by this patch —
operators can rm them at leisure.

### v0.22.15 follow-ups — reconciliation

CLAUDE.md listed three "outstanding" follow-ups from v0.22.15:

1. **Broken Convert-page SSE** — on static review,
   `api/routes/batch.py:100-207` and `core/converter.py:40-53`
   appear functional. The `/api/convert` flow creates a batch,
   redirects to `progress.html`, which opens SSE to
   `/api/batch/{id}/stream`, which reads from the progress queue
   the converter emits into. No clear bug found. Leaving a watch —
   if a reproducible failure surfaces, revisit with an actual repro.
2. **Uncancellable `asyncio.wait_for` on Whisper** — addressed this
   release (see above).
3. **Corrupt-audio tensor reshape** — no `.reshape()` calls exist
   anywhere in the audio/transcription paths (`grep` confirmed).
   Assumed resolved in an earlier patch. Removed from outstanding
   list.

### Files touched

`core/version.py`, `core/db_backup.py`, `formats/pptx_handler.py`,
`core/preferences_cache.py`, `core/whisper_transcriber.py`,
`core/db/connection.py`, `core/db/preferences.py`,
`api/routes/debug.py`, `api/routes/preferences.py`, `main.py`,
`static/settings.html`, `CLAUDE.md`, `docs/gotchas.md`,
`docs/key-files.md`, `docs/version-history.md`. Deleted:
`core/db/contention_logger.py`.

---

## v0.24.1 — AI Assist toggle feedback (2026-04-13)

Targeted UX fix on the Search page AI Assist toggle. Two user
complaints in one session: the active state was too subtle to
notice, and users didn't know whether the toggle could be flipped
before running a search (it always could — the state is a
persistent `localStorage` preference — but the UI gave no signal).

### Changes

- **Stronger active visual.** When enabled, the toggle now renders
  with a solid accent fill and white text, a small `ON` pill
  appended to the label, and a soft accent glow. The previous
  10%-accent-tint state was being missed.
- **Pre-search intent hint.** When the toggle is ON but no results
  are rendered yet, a one-line caption appears under the search
  box — "AI synthesis will run on your next search." — making the
  pre-search state meaningful instead of ambiguous.
- **"Synthesize these results" inline action.** When the user
  flips the toggle ON *after* a search has already rendered, a
  new button appears in the results toolbar. Clicking it runs
  synthesis on the current result set without requiring a new
  search. Previously this was a silent no-op, which looked like a
  bug.
- `AIAssist.runOnCurrentResults()` added to the public API.

### Files

- `static/css/ai-assist.css` — solid-fill `.active` state, new
  `.ai-assist-hint` and `.ai-assist-run-btn` rules, `.toggle-state`
  pill.
- `static/search.html` — `toggle-state` span, `#ai-assist-hint`
  element under the search box, `#ai-assist-run-btn` inside the
  results toolbar.
- `static/js/ai-assist.js` — `_updateContextUI()` drives hint /
  run-button visibility from `_enabled` × `_currentResults.length` ×
  drawer-open state; wired into `setEnabled()`, `onResults()`,
  `openDrawer()`, `closeDrawer()`, and `_applyServerStatusToButton()`.
  New public `runOnCurrentResults()`.
- `core/version.py` — 0.24.0 → 0.24.1.
- `docs/superpowers/specs/2026-04-13-ai-assist-toggle-feedback-design.md`
  — design spec.

### Why this matters

The AI Assist toggle had been a quiet pain point: users couldn't
tell it was on, and couldn't tell what it would *do* until they
ran a search. Fixing both in a single patch is a better return on
attention than a full Search page redesign would be right now.

---

## v0.24.0 — Spec A (quick wins) + Spec B (batch management) (2026-04-13)

The first substantial UX release since the user flagged overall UX
as needing attention. 19 commits across two design specs:
**Spec A** — eight quick-win operator usability improvements
(inline file lists on counter values, DB backup/restore UI, a
hardware-specs help article registered in the help drawer, a
Database Maintenance section on Settings). **Spec B** — a
dedicated Batch Management page for the image-analysis queue,
with pause gate, per-batch cancel, file exclusion, and 9 new API
endpoints backed by 4 new DB helpers.

### Why this shipped

Two things were chronically awkward in v0.23.x:

1. **Operator visibility on bulk / status pages.** When a bulk job
   reported "253 skipped," there was no way to see *which* 253
   files without leaving the page, opening a search, and manually
   filtering by status. The Status page had the same problem per
   card. Users had to mentally hold the filter query while navigating.
2. **No in-product way to back up the DB before a risky operation.**
   Admins were shelling into the container and running
   `sqlite3 .backup` by hand (or, worse, `cp markflow.db ...`,
   which silently produced a stale snapshot on a WAL database
   under load). There was also no way to restore from the UI.
3. **No operator surface for the image-analysis queue.** Batches
   piled up with no way to cancel an in-flight batch, exclude a
   specific file that was crashing the worker, or pause new
   submissions while draining what was already queued.

v0.24.0 addresses all three in a single release.

### Inline file lists (A1, A2)

**What changed.** Bulk page (`static/bulk.html`) and Status page
(`static/status.html`) counter values — converted / failed /
skipped / pending — are now clickable. Clicking one opens an
inline panel directly under the counter strip showing the actual
file list for that bucket, with "Load more" pagination.

**Status page polling.** The Status page refreshes each card
every 5 seconds. The first implementation re-rendered the panel
from scratch on every poll, dumping the user back to page 1. The
5e6a84c fix preserves the load-more page across polls by snapshotting
the current `page` integer before re-render and restoring it after.
Event delegation (cd5057b) was chosen over per-card click handlers
because each poll replaces the card DOM — individual handlers
would have been re-bound on every tick.

**Files:** `static/bulk.html`, `static/status.html`,
`static/js/bulk.js` (or equivalent helper), `api/routes/bulk.py`
(new list endpoints scoped to job_id + status).

### DB Backup / Restore (A3 – A6)

**Why `sqlite3.Connection.backup()` and not `shutil.copy2()`.**
MarkFlow runs with `PRAGMA journal_mode=WAL`. Under WAL, committed
transactions may live in the `-wal` sidecar file for an arbitrary
window before the checkpoint thread merges them back into the main
`.db`. A naive file copy of the `.db` alone can silently miss a
few seconds of committed writes, producing a backup that looks
valid but is corrupt-ish (indexes pointing at rows that aren't
there yet, etc.). The SQLite **online backup API** —
`sqlite3.Connection.backup(dest_conn)` — is the correct answer: it
reads pages under the WAL reader lock and produces a
transactionally consistent snapshot even while writes are in
flight. `core/db_backup.py` wraps this API. The sentinel-row test
in `tests/test_db_backup.py` inserts a row, runs backup, and
verifies the row is in the dest — proving the online backup beats
the race.

**API surface.** `api/routes/db_backup.py` exposes:

- `POST /api/db/backup` — create a named backup. Returns typed
  error codes on failure (disk-space, permissions, backup-in-flight).
- `POST /api/db/restore` — upload a `.db` file, validate, swap in.
- `GET /api/db/backups` — list existing backups with size + mtime.

All routes are admin-only. Every call writes an audit log entry
(initiator user, action, target file, result).

**UI.** `static/js/db-backup.js` drives two modals on the DB
Health page:

- **Create Backup** — fire-and-forget button, success toast on
  completion.
- **Restore** — drag-drop drop-zone, file-type validation (must be
  `.db`), Esc-to-close, focus trap, explicit confirm step, progress
  indicator. Download-backup links go through authenticated cookie
  fetch so signed URLs aren't required.

Settings page (`static/settings.html`) gets a matching **Database
Maintenance** section with the same controls plus links out to
the full Health page.

### Hardware specs help article (A7)

`docs/help/hardware-specs.md` was written but not yet registered
in the help drawer sidebar. Commit 12a8c15 adds it to
`docs/help/_index.json` so it shows up in the `/help.html` TOC.
Covers minimum / recommended CPU / RAM / GPU / storage, plus
per-user throughput estimates matching the reference hardware
(i7-10750H / 64 GB / GTX 1660 Ti).

### Batch management page (B1 – B6)

**Goal.** Give operators a single page that lists every
image-analysis batch with status (queued / running / completed /
cancelled), file counts, and per-batch controls. Let admins
pause new submissions, cancel batches that haven't started, and
exclude individual files that are crashing the worker.

**DB layer (B1, B2).** Four new helpers in `core/db/analysis.py`:

- `get_batches(status_filter=None, limit=50)` — list batches with
  file counts, paginated.
- `get_batch_files(batch_id)` — enumerate files in a batch.
- `exclude_files(file_ids, reason)` — mark specific files
  excluded so the worker skips them.
- `cancel_all_batched(batch_id)` — mark all non-started files in
  a batch as cancelled.

Ten failing tests landed first (6c45d2e), then the implementation
turned them green (ab4ec70) — strict TDD.

**Pause preference (B3, B5).** New `analysis_submission_paused`
boolean in `core/db/preferences.py` (default `false`). The
analysis worker (`core/image_analysis_worker.py`) now checks this
gate on each loop iteration and skips submission while paused.
In-flight work is not cancelled — paused = "don't start new," not
"kill existing." Operators drain the queue by pausing, waiting
for current batches to finish, then acting.

**API router (B4).** `api/routes/analysis.py` mounts 9 endpoints:
list batches, get batch files, cancel batch, exclude files,
cancel-all-batched, get/set pause state, resubmit batch, and a
batch-detail lookup. Code review (1657048) added a path-traversal
guard on file-access endpoints, deduplicated the
`is_image_extension` helper (was defined in two places), and
wrote audit-log entries for every exclude/cancel.

**Frontend (B6).** `static/batch-management.html` renders the
batch list with inline file expansion, pause toggle in the
header, and per-batch action buttons. `fix(B6)` (b597d53) added
a polling overlap guard (don't start a new fetch while the
previous is in flight), honored the `parseUTC()` convention for
backend timestamps (SQLite strips `+00:00`), and whitelisted the
allowed status values client-side so a bad server response can't
render as an arbitrary class name.

The sidebar gets a new nav entry, and the pipeline pill on the
Status page now links directly to `/batch-management.html`
instead of a generic anchor.

### Files created

- `core/db_backup.py`
- `core/db/analysis.py`
- `api/routes/db_backup.py`
- `api/routes/analysis.py`
- `static/batch-management.html`
- `static/js/db-backup.js`
- `tests/test_db_backup.py`
- `tests/test_analysis_batches.py`
- `docs/help/hardware-specs.md` (content finalized + registered)

### Files modified

`core/version.py`, `core/db/preferences.py`,
`core/image_analysis_worker.py`, `main.py`, `static/bulk.html`,
`static/status.html`, `static/health.html`,
`static/settings.html`, `docs/help/_index.json`, sidebar nav
partial, `CLAUDE.md`, `docs/version-history.md`,
`docs/help/whats-new.md`, `docs/gotchas.md`.

### Tests

**21 new tests** total:

- 10 in `tests/test_analysis_batches.py` covering the four new
  DB helpers (happy paths + exclude-already-excluded +
  cancel-already-cancelled + filter / limit).
- 11 in `tests/test_db_backup.py` covering the online backup
  API, sentinel-row race, restore with validation, typed
  error codes, and audit-log integration.

### Why it matters

This release swaps three operator workflows from "shell into the
container and run queries" to "click something on the page."
It's the first of what's expected to be several UX-focused
releases addressing the broader feedback. The DB backup path
is also the prerequisite for every future destructive-operation
audit: any code path that mutates the schema or bulk-deletes
data can now surface a "back up first?" prompt that actually
works.

---

## v0.23.8 — Spec remediation Batch 2 (2026-04-13)

Three items from the spec review, completing the remediation started in
v0.23.6 (Batch 1).

### C1-a: Content-hash sidecar collision fix

**Problem:** Style sidecars keyed elements by bare content hash
(SHA-256[:16]). When a document contained duplicate paragraphs
(e.g., two "N/A" with different styles), only the last entry
survived — the others were silently overwritten.

**Fix:** Element keys now use `{hash}:{occurrence}` format
(`a1b2c3d4:0`, `a1b2c3d4:1`). A new `core/sidecar_match.py`
module provides occurrence-aware lookup with a 4-level cascade:

1. Exact v2 key `{hash}:{n}` (nth occurrence of this hash)
2. Overflow fallback (more occurrences than entries → use last stored)
3. Bare hash fallback (v1 backward compatibility)
4. Fuzzy text match (SequenceMatcher ratio >= 0.90 against `_text` fields)

Each sidecar entry now includes a `_text` field storing the
normalized source text, enabling fuzzy matching for lightly
edited paragraphs (~10% edit distance tolerance).

Sidecar schema version bumped `1.0.0` → `2.0.0`.
`load_sidecar()` auto-migrates v1 sidecars by appending `:0` to
bare-hash keys. Migration is in-memory only — existing sidecar
files on disk remain v1 until regenerated.

**Files:** `core/sidecar_match.py` (new), `core/metadata.py`,
`formats/docx_handler.py`, `formats/pptx_handler.py`,
`tests/test_sidecar_match.py` (new), `tests/test_roundtrip.py`,
`tests/test_docx.py`.

### M5: PPTX chart/SmartArt extraction

**Problem:** Charts in PPTX files produced only a `[Chart: title]`
text placeholder. SmartArt was not detected at all.

**Fix:** New `pptx_chart_extraction_mode` preference with two
values:

- `placeholder` (default): Current behavior — text placeholder
  with warning. No change for existing users.
- `libreoffice`: Converts PPTX to PDF via LibreOffice headless
  (timeout 60s), renders each slide to a PIL image via PyMuPDF
  at 2x resolution, crops chart region using EMU-to-pixel
  coordinate mapping, and saves as a PNG IMAGE element.

SmartArt detection added: group shapes with `dgm:relIds` or
`smartArt` in their XML emit a warning. Text content is still
extracted via recursive group traversal.

LibreOffice failure (timeout, binary not found, render error)
falls back silently to placeholder mode — never crashes on a
chart.

Preference is read synchronously from SQLite in the handler
(same pattern as `database_handler._get_sample_rows_limit`).

**Files:** `formats/pptx_handler.py`, `core/db/preferences.py`,
`api/routes/preferences.py`, `static/settings.html`,
`tests/test_pptx_handler.py`.

### C5: Remaining OCR signals (text-layer quality)

**Problem:** `needs_ocr()` used 3 image-based signals (entropy,
edge density, entropy+edges combo). PDFs with garbage text layers
(bad OCR, corrupt embedding) were not detected.

**Fix:** Two new functions in `core/ocr.py`:

- `text_layer_is_garbage(chars)`: Checks pdfplumber char positions.
  If >80% of chars have `x0 == 0 AND top == 0`, or all chars
  stack at the same point, the text layer is garbage.
- `text_encoding_is_suspect(text)`: Checks Unicode block
  distribution. If >30% of letter characters have ordinal >= 0x0250
  (outside Latin/Latin Extended), the extracted text is suspect.

Both wired into `formats/pdf_handler.py` at both ingest paths
(`_ingest_pdfplumber` and `ingest_with_ocr`). When either signal
fires, the page is treated as scanned (triggers OCR).

**Files:** `core/ocr.py`, `formats/pdf_handler.py`,
`tests/test_ocr.py`.

---

## v0.23.7 — Bulk vector indexer backpressure fix (2026-04-11)

Single-bug hotfix on the vector branch. Bulk vector indexing was
100% broken in v0.23.6 due to an `asyncio.Semaphore` API misuse in
the bulk worker's backpressure helper. Every bulk-converted file
raised an unhandled `AttributeError` when it tried to enter the
Qdrant indexing path, and the error was only visible via
`Task exception was never retrieved` messages on the event loop
because the helper was launched as a detached `create_task()`.

### The bug

`core/bulk_worker.py:_index_vector_with_backpressure()` was
written to cap concurrent Qdrant upserts at 20 via a
module-level `asyncio.Semaphore(20)`, with a non-blocking
acquire so saturated runs would log-and-skip instead of piling up:

```python
_vector_semaphore = asyncio.Semaphore(20)

async def _index_vector_with_backpressure(...):
    """Index to Qdrant with bounded concurrency. Skip if queue is full."""
    acquired = _vector_semaphore.acquire_nowait()    # ← AttributeError
    if not acquired:
        log.info("vector_indexing.backpressure_skip", file=source_path)
        return
    try:
        await _index_vector_async(...)
    finally:
        _vector_semaphore.release()
```

`asyncio.Semaphore` has **no** `acquire_nowait()` method — that
method lives on `threading.Semaphore`. The author was porting a
`threading`-style idiom to async without noticing the surface API
diverges. Because the call is the first statement, every single
bulk file triggered the error, and because the helper runs under
`asyncio.create_task()` inside `_index_vector_async`'s caller,
the exception was swallowed into `Task exception was never
retrieved` warnings that were easy to miss in the log firehose.

Discovered via `~/pull-logs.sh` analysis on 2026-04-11 after
refreshing to the latest vector-branch HEAD on the Proxmox VM:
11 `AttributeError` occurrences in a single tail window, all
from `_index_vector_with_backpressure`. The root cause was
isolated to a single line; the rest of the vector pipeline
(embedding model load, deterministic chunk IDs, idempotent
upserts, rebuild loop, 60s httpx timeout) was unaffected.

### The fix

Replaced the manual acquire / try / finally block with the
idiomatic async context manager, which is equivalent in intent,
shorter, and crucially does not leak a permit if the task is
cancelled between `acquire()` and the `try:`:

```python
async def _index_vector_with_backpressure(...):
    """Index to Qdrant with bounded concurrency. Waits for a free slot when the pool is saturated."""
    async with _vector_semaphore:
        await _index_vector_async(...)
```

**Behavioural change:** the pool now **blocks** when saturated
instead of **skipping**. Under the old (broken) code the intent
was log-and-drop, but that was never a reachable code path because
the helper crashed before the acquire could succeed. Making the
semaphore block is the correct semantics for a backpressure
primitive anyway — the bulk worker never wants to silently drop
files from the vector index when Qdrant is healthy but slow. The
`vector_indexing.backpressure_skip` log event is gone as a result,
which matches the new "we never skip" behaviour.

Timeout safety is still provided upstream: `AsyncQdrantClient` is
configured with `QDRANT_TIMEOUT_S=60` (see `## Vector Search &
Qdrant` in `gotchas.md`), so a genuinely wedged qdrant will fail
the individual upsert rather than permanently holding a semaphore
permit.

**Why it matters:** v0.23.6 on the vector branch shipped a
bulk-conversion pipeline where every file failed to vector-index,
so keyword search kept working (Meilisearch path is independent)
but semantic/hybrid search results quietly stopped growing.
This is exactly the class of silent-failure regression that the
"Vector search is best-effort" gotcha in `gotchas.md` is meant
to protect against at the call-site level — but this case was
inside the backpressure helper itself, not at a call site, so
the best-effort guard never fired.

**Files touched:** `core/version.py`, `core/bulk_worker.py`,
`CLAUDE.md`, `docs/gotchas.md`, `docs/version-history.md`,
`docs/help/whats-new.md`.

---

## v0.23.6 — Spec remediation Batch 1 (2026-04-10)

Six-item landing of the first batch of the v0.23.5 spec-review
remediation. No user-visible redesign — this release is about
hardening and small quality-of-life wins on top of the conversion
pipeline and the lifecycle manager. See `docs/superpowers/` for the
original audit and `memory/project_batch2_spec_remediation.md` for
the deferred Batch 2 scope.

### M1 — Width/height hints in markdown image output

`formats/markdown_handler.py` now emits images in the CommonMark
attribute-list form `![alt](src){width=Wpx height=Hpx}` when the
source `ImageData` carries dimensions. Previously dimensions were
encoded in the markdown title string (`![alt](src "WxH")`) which
was legal but noisy and harder to reason about. The ingest-side
parser in `_ast_to_elements` now recognises both the new attr-list
syntax AND the legacy `"WxH"` title form, so round-tripping an
old-format .md file still restores dims on the DocumentModel.

**Why it matters:** Tier 2 DOCX round-trip now keeps image
dimensions end-to-end, and any downstream tooling that reads the
generated markdown can size images without having to re-open the
PNG from `assets/`.

**Files touched:** `formats/markdown_handler.py`.

### M2 — Pre-conversion disk space check

Both the bulk worker and the single-file converter path now run a
disk-space pre-flight check before any files are touched.
`core/bulk_worker.py` adds `BulkJob._precheck_disk_space()`, called
immediately after the scan phase completes and before workers
start. It sums the input sizes, multiplies by a 3× conservative
buffer (markdown + sidecars + intermediates), and compares against
`shutil.disk_usage(output_path).free` on the nearest existing
parent directory. A failing job transitions cleanly to the
`failed` state with `cancellation_reason=Insufficient disk space:
…` and emits a `job_failed_disk_space` SSE event for the UI.

`core/converter._convert_file_sync` performs the same check
per-file, with the multiplier applied to `file_path.stat().st_size`.
Failures raise `ValueError("Insufficient disk space for
conversion: …")` which the existing exception handler converts
into a recorded `ConvertResult` with status `error`.

The feature logs `convert_disk_precheck` /
`bulk_disk_precheck` events with the full reasoning (input bytes,
required bytes, free bytes, probe path) so post-mortems are
trivial.

**Files touched:** `core/bulk_worker.py`, `core/converter.py`.

### M4 — Configurable trash retention + scheduled auto-purge

Two new preferences:

- `trash_auto_purge_enabled` (default `true`) — master switch for
  the automatic retention-based purge job
- (existing) `lifecycle_trash_retention_days` — authoritative
  retention window (already read by `run_trash_expiry` since
  v0.22.x, but with this release the purge branch moves to a
  dedicated daily job)

`core/scheduler.py` adds `_purge_aged_trash()`, registered as a
cron job at `04:00` local time. It respects the new master
switch, yields to active bulk jobs (like every other scheduled
job), reads `lifecycle_trash_retention_days`, and deletes trashed
rows older than the window. Log event
`scheduler.purge_aged_trash_complete` includes `purged_count` and
`bytes_freed`. The existing hourly `run_trash_expiry` job no
longer purges — it only moves expired marks into trash — which
means the two responsibilities are cleanly separated in the
scheduler registry (now reporting 17 jobs, up from 16).

`core/lifecycle_manager.py:32` gets a comment clarifying that
`TRASH_RETENTION_DAYS = 60` is just a default used in the trash
README text; the authoritative value lives in the preference.

Settings UI: new toggle **Auto-purge aged trash (v0.23.6)** under
the **File Lifecycle** section in `static/settings.html`, wired
through the generic `updateToggleLabel` handler that already
covers all toggles.

**Files touched:** `core/db/preferences.py`, `core/scheduler.py`,
`core/lifecycle_manager.py`, `static/settings.html`.

### C5 — Per-job force-OCR flag

New preference `force_ocr_default` (default `false`) plus a
per-job override exposed on the bulk job config modal as a
checkbox **Force OCR on every PDF page**. When enabled,
`PdfHandler.ingest()` dispatches to a new
`_ingest_pdfplumber_force_ocr()` path that skips text-layer
extraction entirely and marks every page as scanned, stashing
the per-page PIL images on `model._scanned_pages` so the deferred
OCR runner in `ConversionOrchestrator._check_and_run_deferred_ocr`
picks them up and runs Tesseract on each one.

The flag is plumbed end-to-end:

- `api/routes/bulk.py` adds a `force_ocr: bool | None` field to
  `CreateBulkJobRequest` and includes it in the overrides dict
  passed into `BulkJob`.
- `core/bulk_worker.py` reads `self.overrides.get("force_ocr")`
  in `_process_convertible` and plants it in `convert_opts`.
- `core/converter._convert_file_sync` reads
  `options.get("force_ocr")`, and when the format is PDF, calls
  `handler.ingest(working_path, force_ocr=True)` with a
  `TypeError` fallback for handlers that don't support the kwarg
  (all non-PDF handlers).

Settings UI: new toggle **Force OCR by default (v0.23.6)** under
the **OCR** section. Bulk modal UI: new checkbox next to the
**OCR mode** dropdown. Both hydrate from `force_ocr_default` on
page load.

**Why it matters:** PDFs that have a text layer but bad
character-set mapping (a very common failure mode of old scanners
that ran an OCR pass before saving) previously forced the user to
drop the text layer manually. Now the operator just ticks the
box.

**Files touched:** `core/db/preferences.py`, `formats/pdf_handler.py`,
`core/converter.py`, `core/bulk_worker.py`, `api/routes/bulk.py`,
`static/bulk.html`, `static/settings.html`.

### S4 — Structural hash helper + round-trip test

New helper `compute_structural_hash(model)` in
`core/document_model.py` that returns a deterministic SHA-256 hex
digest of a canonical representation of document structure:
heading count + levels + text, table count + dimensions + cell
text, image count + dimensions, list count + nesting depths. The
canonical rep is serialised via `json.dumps(sort_keys=True)` so
key ordering is stable across Python versions.

Added `_list_depths()` helper that recursively walks list items
and records nesting depth — the old `structural_hash()`
instance-method forgot about nested lists entirely.

`DocumentModel.structural_hash()` stays as an instance-method
wrapper for callers that already use that API.

New round-trip test `test_structural_hash_survives_roundtrip` in
`tests/test_roundtrip.py` asserts that DOCX → MD → DOCX
round-tripping preserves heading/table/image/list counts — strict
hash equality is too brittle because the DOCX round-trip can add
a trailing empty paragraph, but the core structural dimensions
are preserved.

**Files touched:** `core/document_model.py`,
`tests/test_roundtrip.py`.

### S1 — POST /api/convert/preview dry-run endpoint (enhanced)

The endpoint already existed in a minimal form (filename, format,
page count, element counts, warnings). This release rounds it out
with:

- Pre-flight zip-bomb check via the existing `check_zip_bomb()`
  helper — returns a warning and sets `ready_to_convert=false`
  when a file's compression ratio exceeds the threshold
- Size-limit check against `MAX_UPLOAD_MB` (default 100) —
  same behaviour
- `estimated_conversion_seconds` field — rough estimate based on
  ingest wall time × 2 (for export + IO), plus 5s/page when OCR
  is likely
- `ready_to_convert` boolean — drives the Convert button state in
  the UI

The Preview button on `static/index.html` existed but had a
minimal one-line `alert()` output. It now renders a formatted
multi-line block with all fields, warnings as a bulleted list,
and the `ready_to_convert` verdict.

`api/models.py` `PreviewResponse` grows the two new fields.
`core/converter.PreviewResult` dataclass matches.

**Files touched:** `core/converter.py`, `api/models.py`,
`api/routes/convert.py`, `static/index.html`.

### Documentation

- `docs/help/whats-new.md` — new v0.23.6 entry at top
- `docs/help/settings-guide.md` — documents the three new
  preferences (`trash_auto_purge_enabled`, `force_ocr_default`,
  plus the already-existing `lifecycle_trash_retention_days`)
- `docs/help/ocr-pipeline.md` — new "Forcing OCR on a file"
  section
- `docs/help/file-lifecycle.md` — mentions configurable retention
  and scheduled auto-purge
- `docs/help/document-conversion.md` — mentions the enhanced
  Preview button
- `docs/help/bulk-conversion.md` — documents the per-job
  force-OCR checkbox

### Gotchas introduced in this release

1. **force_ocr kwarg is PDF-only** — the converter uses a
   `TypeError` fallback so other handlers don't break, but no
   other handler honours the flag. Adding force_ocr to, say, an
   image handler would require a per-handler opt-in.
2. **Disk-space multiplier is 3×** — deliberately conservative.
   If a pipeline sees false-positive failures on a tight volume,
   the multiplier constant
   (`_DISK_SPACE_REQUIRED_MULTIPLIER` in `core/bulk_worker.py`)
   is the knob to turn. Not exposed as a preference yet.
3. **Daily purge runs at 04:00 local, not UTC** — matches the
   existing `run_db_compaction` cron trigger style. Operators
   running in a different tz should be aware.

---

## v0.23.5 — Search shortcuts, migration FK fix, MCP race fix (2026-04-10)

Two-track release: a set of new keyboard shortcuts on the Search
page, plus a pair of critical startup crash fixes discovered during
the v0.23.4 → v0.23.5 upgrade on the dev instance.

### Search Page Keyboard Shortcuts

Added ten shortcuts to `static/search.html` via a single global
`keydown` handler appended to the main IIFE. All `Alt`-based combos
to avoid conflicts with typing into the search input.

| Key | Action |
|-----|--------|
| `/` | Focus the search input from anywhere on the page |
| `Esc` | Contextual close: preview popup → AI drawer → flag modal → autocomplete → batch selection → blur search |
| `Alt + Shift + A` | Toggle AI Assist |
| `Alt + A` | Select every visible result on the current page |
| `Alt + C` | Clear batch selection |
| `Alt + Shift + D` | Download the current batch as ZIP (uses Shift to avoid Chrome's `Alt+D` address bar shortcut) |
| `Alt + B` | Trigger Browse All |
| `Alt + R` | Re-run the current search |
| `Alt + Click` on a result | Download the original source file directly instead of opening the viewer |
| `Shift + Click` on a checkbox | Range-select from the last-checked row to this one |

Implementation notes:
- `Alt+Click` on the hit-link diverts navigation to
  `/api/search/download/{index}/{doc_id}` via `e.preventDefault()` +
  `window.location.href`.
- `Shift+Click` range-select tracks `window._lastCheckedIdx` and
  dispatches synthetic `change` events on the in-range checkboxes so
  the existing batch-bar update logic fires.
- Global keydown listener checks `isEditable(e.target)` before
  handling `/` so it doesn't steal the key mid-input.
- `handleEscape()` returns `true` if it handled the key so we can
  `preventDefault()` conditionally.
- Discoverability: the search input gets a `title` tooltip on init.

### Help Documentation Updates

- **New:** `docs/help/whats-new.md` — user-facing version page
  listing changes v0.20.0 → v0.23.5, most recent on top. Registered
  as the first entry under **Basics** in `docs/help/_index.json`.
- **Rewritten:** `docs/help/search.md` — now covers the three search
  layers (keyword Meilisearch / vector Qdrant / AI Assist Claude)
  with worked examples per layer. Keyword syntax cheatsheet
  documents phrase `"quotes"`, negative `-term`, typo tolerance, and
  prefix match — with the honest note that AND/OR/NOT don't exist.
  AI Assist section has five example question categories.
- **Rewritten:** `docs/help/settings-guide.md` — matches the v0.23.4
  section layout (Files and Locations / Conversion Options / AI
  Options groups). Adds docs for `scan_skip_extensions`,
  `handwriting_confidence_threshold`, Database sample rows per table,
  Pipeline master switch, Cloud Prefetch, Auto-Conversion, Debug
  DB contention, Advanced.
- **Expanded:** `docs/help/keyboard-shortcuts.md` — three new
  subsections for the Search page: search box + autocomplete,
  page-level shortcuts, and result-row shortcuts. Full Esc priority
  order documented.
- **Unchanged:** `docs/help/ocr-pipeline.md` (already had v0.20.3
  handwriting fallback section), `docs/help/database-files.md`
  (already matched v0.23.1 handler reality).

### Crash Fix A — Migration FK Enforcement

**Symptom:** On startup after pulling v0.23.4 onto a long-running
dev instance, both containers crash-looped. MCP logs showed
`sqlite3.IntegrityError: FOREIGN KEY constraint failed` during
`_run_migrations`. Main container logs showed `database is locked`
because the two containers were racing on migration.

**Root cause:** `core/db/connection.py` sets `PRAGMA foreign_keys=ON`
on every connection open. Migration 27 (v0.23.3 re-run of the
`bulk_files` rebuild) does the standard SQLite "new table / insert
from old / drop / rename" pattern. With FK enforcement on,
`INSERT INTO bulk_files_new SELECT ... FROM bulk_files` rejects any
row whose `job_id` no longer exists in `bulk_jobs` or whose
`source_file_id` no longer exists in `source_files`. The dev
instance had accumulated orphans over 20+ releases.

**Fix (`core/db/schema.py`):** At the start of `_run_migrations`,
`await conn.commit()` to flush any implicit transaction, then
`await conn.execute("PRAGMA foreign_keys = OFF")`. This is the
standard SQLite recommendation for schema rebuilds (see
<https://sqlite.org/lang_altertable.html#otheralter>). `init_db()`
already calls `PRAGMA foreign_keys = ON` at line 916 immediately
after `_run_migrations` returns, so enforcement is restored for
normal operation. Historical orphans get copied through to the new
table; going-forward inserts with bad FKs continue to be rejected.

### Crash Fix B — MCP Migration Race

**Symptom:** `mcp_server/server.py:304` called
`asyncio.run(init_db())` on startup, and so did the main container.
With `docker-compose depends_on` providing only start-order
guarantees (not readiness), both processes hit the migration
runner concurrently. The loser got `database is locked` because the
winner held an exclusive lock.

**Fix (`mcp_server/server.py`):** MCP is a reader. The main
container owns schema setup and migrations. Removed the `init_db()`
call. Replaced with a 2-minute polling loop that waits for the
`schema_migrations` table to exist (via
`SELECT COUNT(*) FROM sqlite_master WHERE ... name='schema_migrations'`)
before proceeding. If the wait times out, MCP logs a warning and
starts anyway — the first query will surface any real problem.

### Files

- Modified: `core/version.py` (0.23.4 → 0.23.5)
- Modified: `CLAUDE.md` (current version section)
- Modified: `core/db/schema.py` (`_run_migrations` FK-off prologue)
- Modified: `mcp_server/server.py` (init_db removed, DB-ready poll added)
- Modified: `static/search.html` (keyboard shortcut handler, Alt-click download, shift-click range select)
- Modified: `docs/help/search.md` (rewrite)
- Modified: `docs/help/settings-guide.md` (rewrite for v0.23.4 layout)
- Modified: `docs/help/keyboard-shortcuts.md` (Search page expansion)
- Modified: `docs/help/_index.json` (registered whats-new under Basics)
- Created: `docs/help/whats-new.md`
- Modified: `docs/version-history.md` (this entry)

---

## v0.23.4 — Settings page reorganization (2026-04-10)

UX pass on the Settings page. Reorganized 21 sections into logical
groups with clearer naming.

### Section Renames
- **Locations** → **Files and Locations**
- **Conversion** → **Conversion Options**
- **AI Enhancement** → **AI Options**

### Section Regrouping
- **Files and Locations** group: Password Recovery, File Flagging,
  Info, Storage Connections now follow immediately after the renamed
  "Files and Locations" section.
- **Conversion Options** group: OCR, Path Safety now follow
  immediately after "Conversion Options".
- **AI Options** group: Vision & Frame Description, Claude Integration
  (MCP), Transcription, AI-Assisted Search now follow immediately
  after "AI Options".

### New Section Order
1. Files and Locations, 2. Password Recovery, 3. File Flagging,
4. Info, 5. Storage Connections, 6. Conversion Options, 7. OCR,
8. Path Safety, 9. AI Options, 10. Vision & Frame Description,
11. Claude Integration (MCP), 12. Transcription, 13. AI-Assisted Search,
14. Logging, 15. File Lifecycle, 16. Pipeline, 17. Cloud Prefetch,
18. Search Preview, 19. Auto-Conversion, 20. Debug: DB Contention
Logging, 21. Advanced

### Files
- Modified: `static/settings.html` (section moves + renames only,
  no content changes)

---

## v0.23.3 — UX responsiveness, bulk restore, extension exclude, migration hardening (2026-04-10)

Focused on user-perceived responsiveness for heavy operations and two new
features. Also fixes the migration runner bug that silently dropped DDL.

### Migration Hardening
- **Migration 27:** Re-runs the `bulk_files` table rebuild that migration 26
  silently failed on. Converts `UNIQUE(job_id, source_path)` to
  `UNIQUE(source_path)` — fixes the `ON CONFLICT` crash that killed every
  bulk job since v0.23.0.
- **`INSERT OR IGNORE` on `schema_migrations`:** Prevents restart crash when
  a migration version row already exists.
- **`except: pass` narrowed to ALTER TABLE only:** Non-ALTER DDL failures
  (CREATE, DROP, INSERT, RENAME) now propagate instead of being silently
  swallowed. Root cause of the migration 26 failure.
- **`get_preference()` signature fixes:** `migrations.py` and
  `preferences_cache.py` were calling `get_preference(key, default)` but
  the function only takes `key`. Default handling moved to the cache layer.

### UX Responsiveness
- **Empty Trash:** Batched DB operations (chunks of 200), disk deletions in
  parallel (batches of 50 via thread pool), `asyncio.sleep(0)` between
  chunks. Returns immediately, runs in background. Frontend polls
  `GET /api/trash/empty/status` every 2s showing "Purging X / Y..."
- **Rebuild Search Index:** Polls `/api/search/index/status` every 3s,
  shows "Rebuilding (X docs)..." until all sub-indexes finish.
- **DB Compaction:** Shows "Compacting..." with 10s hold, then confirms
  via health poll.
- **Integrity Check:** Button text "Checking... (this may take a minute)".
- **Stale Data Check:** Button text "Checking... (scanning tables)".
- **Trash confirm dialog:** Was unstyled native `<dialog>` anchored to
  top-left. Now centered with backdrop, border-radius, padding.

### New Features
- **Bulk Restore** (`POST /api/trash/restore-all`): Background task +
  progress polling. "Restore All" button on trash page with
  "Restoring X / Y..." feedback. Processes in batches of 50 with
  event loop yields.
- **Extension Exclude** (`scan_skip_extensions` preference): JSON list of
  file extensions to skip during scanning (without dots). Wired into both
  `core/bulk_scanner.py` and `core/lifecycle_scanner.py`. Configurable
  via Settings > Conversion. Example: `["tmp", "bak", "log"]`.

### Files
- Modified: `core/db/schema.py` (migration 27 + runner hardening),
  `core/db/migrations.py` (get_preference fix), `core/preferences_cache.py`
  (default handling fix), `core/lifecycle_manager.py` (batch purge +
  restore_all), `api/routes/trash.py` (4 new endpoints), `static/trash.html`
  (dialog fix + restore all + progress polling), `static/bulk.html` (index
  rebuild polling), `static/db-health.html` (compaction/integrity/stale
  feedback), `core/bulk_scanner.py` (extension exclude), `core/lifecycle_scanner.py`
  (extension exclude), `core/db/preferences.py` (scan_skip_extensions),
  `api/routes/preferences.py` (extension exclude schema), `Dockerfile.base`
  (pysqlcipher3 removed — build failure)

---

## v0.23.2 — Critical bug fixes: bulk upsert, scheduler coroutine, vision MIME (2026-04-10)

Three bugs fixed, one critical (all bulk conversions stalled since schema/code mismatch).

### Bug fixes

- **`bulk_job_fatal` ON CONFLICT mismatch (critical)** — The audit remediation plan
  (v0.23.0) changed all upsert SQL from `ON CONFLICT(job_id, source_path)` to
  `ON CONFLICT(source_path)`, but the `bulk_files` table schema still had
  `UNIQUE(job_id, source_path)`. Every bulk conversion job failed immediately,
  leaving 1,654 files permanently stuck in pending. Migration 26 rebuilds the table
  with `UNIQUE(source_path)`, deduplicating on `MAX(ROWID)` per `source_path`.

- **Unawaited `get_all_active_jobs()` coroutine** — `_bulk_files_self_correction`
  in `core/scheduler.py:481` and the admin cleanup endpoint in
  `api/routes/admin.py:421` called `get_all_active_jobs()` without `await`.
  The coroutine was truthy (always non-empty object), so the scheduler always
  skipped self-correction and the admin endpoint always returned 409. Added `await`.

- **Vision adapter MIME mislabeling** — All four provider batch methods
  (`_batch_anthropic`, `_batch_openai`, `_batch_gemini`, single-image path) used
  `path.suffix` to guess MIME type via `mimetypes.guess_type()`. Files with
  mismatched extensions (e.g. GIF saved as `.png`) sent the wrong `media_type` to
  the API, causing HTTP 400 and failing entire 10-image batches. Now uses
  `detect_mime()` (magic-byte header detection) which was already defined but unused
  in these code paths.

### Files changed
- `core/db/schema.py` — base DDL: `UNIQUE(source_path)`, migration 26 (table rebuild)
- `core/scheduler.py` — `await get_all_active_jobs()` in self-correction job
- `api/routes/admin.py` — `await get_all_active_jobs()` in cleanup endpoint
- `core/vision_adapter.py` — `detect_mime(path)` replaces `path.suffix` in 4 locations
- `core/version.py` — bump to 0.23.2

---

## v0.23.1 — Database file handler: schema + sample data extraction (2026-04-09)

New `DatabaseHandler` replaces `BinaryHandler` for database file extensions,
extracting full schema, sample data, relationships, and indexes into structured
Markdown summaries.

### Supported Formats
- **SQLite** (`.sqlite`, `.db`, `.sqlite3`, `.s3db`) — Python built-in `sqlite3`
- **Microsoft Access** (`.mdb`, `.accdb`) — engine cascade: mdbtools -> pyodbc -> jackcess
- **dBase / FoxPro** (`.dbf`) — `dbfread` (pure Python)
- **QuickBooks** (`.qbb`, `.qbw`) — best-effort binary header parse; metadata-only
  for encrypted/newer files with QuickBooks Desktop export instructions

### Architecture
- Engine-per-format behind a common ABC (`DatabaseEngine` in `formats/database/engine.py`)
- Five dataclasses: `TableInfo`, `ColumnInfo`, `RelationshipInfo`, `IndexInfo`
- Engine cascade for Access: `MdbtoolsBackend` (CLI) -> `pyodbc` (ODBC) -> `jackcess` (Java)
- Capability detection (`formats/database/capability.py`) probes installed backends at startup
- Password cascade reuses existing archive handler pattern (empty -> static list -> dictionary)

### Markdown Output
Each database produces: H1 title, metadata property table, schema overview table,
per-table column definitions + sample data (default 25 rows, configurable via
`database_sample_rows` preference, max 1000), relationships table, indexes table.
QuickBooks files include company name extraction and manual export instructions.

### Limits
- Max 50 tables with full detail sections (remaining counted in summary)
- Max 20 columns in sample data tables (remaining noted)
- Max 1000 sample rows per table (hard cap)

### Dependencies Added (Dockerfile.base)
- `mdbtools`, `unixodbc-dev`, `odbc-mdbtools` (apt)
- `dbfread`, `pyodbc`, `pysqlcipher3` (pip)
- Optional: Java JRE + jackcess JAR for full .accdb support

### Files
- Created: `formats/database/` package (7 files: `__init__.py`, `engine.py`,
  `sqlite_engine.py`, `access_engine.py`, `dbase_engine.py`, `quickbooks_engine.py`,
  `capability.py`)
- Created: `formats/database_handler.py`
- Created: `tests/test_database_engines.py`, `tests/test_database_handler.py`
- Created: `docs/help/database-files.md`
- Modified: `formats/__init__.py`, `formats/binary_handler.py`,
  `core/db/preferences.py`, `api/routes/preferences.py`, `Dockerfile.base`,
  `docs/formats.md`

---

## v0.23.0 — Audit remediation: DB pool, pipeline hardening, vision MIME fix (2026-04-09)

20-task overhaul addressing all 17 items from the Health Audit + Specification
Review. Organized into 4 waves for maximum parallelism.

### DB Layer
- **Connection pool** (`core/db/pool.py`): Single-writer async write queue + 3
  read-only connections. WAL mode, 30s busy timeout. `db_fetch_one/all` and
  `db_execute` in `core/db/connection.py` transparently route through pool when
  initialized, falling back to direct connection during startup schema init.
  Eliminates "database is locked" errors under concurrent bulk + lifecycle scans.
- **Preferences TTL cache** (`core/preferences_cache.py`): 5-minute in-memory
  cache. Invalidated on PUT via `api/routes/preferences.py`. Eliminates ~50K
  DB reads/day from scheduler ticks, worker files, and scan iterations.
- **bulk_files dedup migration** (`core/db/migrations.py:run_bulk_files_dedup`):
  One-time cleanup keeping only the latest row per `source_path`. Expected to
  delete ~187K rows. Schema migrated from `unique(job_id, source_path)` to
  `unique(source_path)` so rescans update in place instead of creating duplicates.
- **Stale job detection** (`core/db/migrations.py:add_heartbeat_column` +
  `cleanup_stale_jobs`): `bulk_jobs` gets `last_heartbeat` column. Workers update
  every 60s. Startup cleans jobs stuck in 'running' with heartbeat > 30 min old.
- **Counter batching** (`core/bulk_worker.py:CounterAccumulator`): Batches
  converted/failed/skipped counter updates (flush every 50 files or 5s). Reduces
  per-scan DB writes from ~800K to ~16K.

### Pipeline
- **Incremental scanning** (`core/bulk_scanner.py`): Files already converted with
  same mtime are skipped. Post-scan cross-job dedup DELETE as safety net.
- **Pipeline stats cache** (`api/routes/pipeline.py`): 20s TTL on `/api/pipeline/stats`.
  Invalidated on bulk job start/complete via `core/scan_coordinator.py`.
- **Lifecycle I/O fix** (`core/lifecycle_manager.py`): `shutil.move` and
  `unlink` wrapped in `asyncio.to_thread()`. Added `recover_moving_files()`
  for startup crash recovery.
- **Forced trash expiry** (`core/scheduler.py`): Every 4th `run_trash_expiry`
  invocation bypasses the active-jobs check.
- **Housekeeping job** (`core/scheduler.py:run_housekeeping`): Every 2 hours.
  Cross-job dedup + PRAGMA optimize + conditional VACUUM (>10% free pages).
  Does NOT yield to active bulk jobs.
- **Vector backpressure** (`core/bulk_worker.py`): Bounded semaphore (20) on
  Qdrant indexing tasks. Skipped files picked up on next lifecycle scan.

### PDF Engine
- **PyMuPDF as default** (`formats/pdf_handler.py`): Pages with table gridlines
  (detected via `get_drawings()` line analysis) switch to pdfplumber for that
  page only. All other pages use PyMuPDF (~3x faster). Full pdfplumber fallback
  on any PyMuPDF failure. Controlled by `pdf_engine` preference.

### Vision Adapter
- **Magic-byte MIME detection** (`core/vision_adapter.py:detect_mime`): Detects
  JPEG, PNG, GIF, BMP, WebP from file headers. Fixes 115 batch failures from
  .jpg files that were actually GIFs.
- **Provider-aware batch limits** (`core/vision_adapter.py:plan_batches`):
  Per-provider caps for anthropic (24MB/20img), openai (18MB/10img), gemini
  (18MB/16img), ollama (50MB/5img).

### Frontend
- **Polling reduction** (`static/js/global-status-bar.js`): 20s visible (was 5s),
  30s hidden, stops after 30 min hidden. Tab re-activation reloads page.
  Eliminates ~40K unnecessary requests/day.

### Other
- **Conversion semaphore auto-detect** (`core/converter.py`): `cpu_count // 2`,
  capped 2–8. Configurable via `max_concurrent_conversions` preference.
- **Removed unused deps** (`requirements.txt`): `mammoth` and `markdownify`
  deleted (zero imports found).
- **Logging suppression** (`core/logging_config.py`): httpx/httpcore set to
  WARNING (~40K debug lines/day from Meilisearch polling).
- **Structural hash** (`core/document_model.py:DocumentModel.structural_hash`):
  SHA-256 of heading/table/image/list structure for round-trip comparison.
- **markitdown validation** (`core/validation/markitdown_compare.py`): CLI tool
  for comparing MarkFlow output against Microsoft markitdown. Dev use only.
- **Startup migrations** (`main.py:lifespan`): Pool init, heartbeat column,
  stale job cleanup, bulk dedup, vision MIME re-queue, lifecycle timer warnings,
  crash recovery.

### Files modified (18) + created (4)
Modified: `main.py`, `core/version.py`, `core/db/connection.py`, `core/db/bulk.py`,
`core/bulk_worker.py`, `core/bulk_scanner.py`, `core/converter.py`,
`core/document_model.py`, `core/lifecycle_manager.py`, `core/logging_config.py`,
`core/scan_coordinator.py`, `core/scheduler.py`, `core/vision_adapter.py`,
`formats/pdf_handler.py`, `api/routes/pipeline.py`, `api/routes/preferences.py`,
`requirements.txt`, `static/js/global-status-bar.js`

Created: `core/db/pool.py`, `core/db/migrations.py`, `core/preferences_cache.py`,
`core/validation/` (package with `markitdown_compare.py`)

### Validation
`python -m py_compile` clean on all 22 files.

---

## v0.22.19 — Scan-time junk-file filter + historical cleanup (2026-04-08)

Direct follow-up to the v0.22.18 sweep. Triggered by a UI screenshot of
a cancelled bulk job (`c0ae5913`) showing 90 failed files, ~43 of which
displayed `"Cannot convert ~$xxx.doc: LibreOffice not found. Install
libreoffice-headless."` in the error column. v0.22.18's libreoffice
helper fix would have shown the *real* error instead, but didn't address
the deeper issue: **these files should never have been queued in the
first place**.

### What was wrong

The failing file paths followed an unmistakable pattern:

```
~$-09-17 MLA Official Redline.doc
~$.lois.agency fee payer memo.doc
~$cific Fisherman Inc Wage Report 2008-2009.doc
~$2017.CEWW.JM.Support.Letter.docx
~$00789-MG SIH Grant Award.docx
~WRL2619.tmp
```

Every one starts with `~$` — Microsoft Office's **lock-file prefix**.
When you open a document in Word/Excel/PowerPoint/Visio, Office
creates a hidden ~162-byte sentinel file with the same name prefixed
by `~$`. It's not a real document, just an "I'm in use" marker that
gets cleaned up when you close the file. They linger forever if Office
crashes mid-edit.

When the bulk scanner walked the source share, it picked up these
sentinel files (since they have valid `.doc` / `.docx` / `.xlsx`
extensions), queued them into `bulk_files`, and a worker eventually
shipped them to `libreoffice --headless --convert-to docx`. LibreOffice
correctly exited non-zero (the file isn't a real document), and the
*pre-v0.22.18* helper then raised the misleading
`"LibreOffice not found. Install libreoffice-headless."` error.

The accumulated damage from no scanner-side filtering, observed in
the live DB at upgrade time:

| Junk type | bulk_files rows | source_files rows |
|---|---|---|
| `Thumbs.db` (Windows thumbnail cache) | 1,327 | 453 |
| `~$*` Office lock files | (subset of failed rows above) | (similar) |
| `~WRL*.tmp` Word recovery temp | 3 in last cancelled job | similar |

Plus inflated `total_files` counts on every bulk job and inflated
`source_files` lifecycle scan counts on every cycle.

### The fix

**`core/bulk_scanner.py` — new `is_junk_filename()` helper.** Defines
two constants and one helper function near the top of the module:

```python
_JUNK_BASENAME_PREFIXES_LOWER = (
    "~$",        # MS Office lock files (Word/Excel/PowerPoint/Visio)
    "~wrl",      # Word recovery temp files
)
_JUNK_BASENAMES_LOWER = frozenset({
    "thumbs.db", "desktop.ini", ".ds_store", ".appledouble",
    "ehthumbs.db", "ehthumbs_vista.db",
})

def is_junk_filename(name: str) -> bool: ...
```

Pure case-insensitive string ops, no regex — runs millions of times
per scan and a regex compile is overkill for six fixed patterns.
Case-insensitive because Windows filesystems are case-insensitive
and the same artifact can appear as `Thumbs.db` / `THUMBS.DB` /
`thumbs.db`.

**`BulkScanner._is_excluded()`** now calls `is_junk_filename()` first
(cheapest check, catches the noisiest leaks), before the existing
exclusion-prefix and skip-pattern checks.

**`core/lifecycle_scanner.py`** — both `_is_excluded` closures (one in
`_serial_lifecycle_walk`, one in `_parallel_lifecycle_walk`) get the
same prepended check, importing `is_junk_filename` from
`core.bulk_scanner`. This means:

- New scans never queue junk files
- Existing pending junk rows stay until cleaned up (next item)

**`main.py:lifespan` — one-time historical cleanup migration.** A
DELETE migration runs once on startup, gated by the
`junk_cleanup_v0_22_19_done` preference flag. Mirrors the same patterns
the scanner now filters, expressed as SQL `LIKE` over `source_path`
suffixes (handles both POSIX `/` and Windows `\` separators on
UNC-mounted paths). Deletes from `bulk_files` first, then `source_files`,
to handle the FK relationship cleanly. Logs counts via
`markflow.junk_cleanup_v0_22_19`. Idempotent — runs exactly once per
database, then the preference flag short-circuits all future startups.

### Why this matters for prod-readiness

The 43 misleading errors per job were the loud visible symptom, but
the real cost was cumulative:

- Every scan added more junk rows to `source_files`
- Every bulk job re-processed the same lock files
- The file count UI badge overstated by ~5%
- The `lifecycle_scan.file_error` count was inflated
- Users saw "LibreOffice not found" messages and started chasing a
  Dockerfile bug that didn't exist (Dockerfile.base correctly installs
  `libreoffice-writer` + `libreoffice-impress`)

This is the same "noise hides real signal" pattern v0.22.18 set out
to fix — the difference is v0.22.18 fixed the *symptom layer* (error
messages, retry logic, timeouts) and v0.22.19 fixes the *data layer*
(don't queue garbage in the first place). Together they eliminate
roughly **2,521 noisy log/DB events / 24h** without adding any new
code paths to maintain.

### Validation performed

- `python -m py_compile` clean on all four edited files
  (`core/bulk_scanner.py`, `core/lifecycle_scanner.py`, `main.py`,
  `core/version.py`).
- Diagnostic SQL confirmed the upgrade-time leak counts (1,327 / 453)
  via `core/database` queries against the live DB.

### Not yet validated

- **Live deploy verification.** After rebuild + restart, expect:
  1. Startup log line `markflow.junk_cleanup_v0_22_19` with
     `bulk_files_deleted` and `source_files_deleted` counts roughly
     matching the diagnostic's 1,327 / 453.
  2. Post-startup query `SELECT count(*) FROM bulk_files WHERE
     source_path LIKE '%Thumbs.db'` returning 0.
  3. Next bulk scan over the same source share producing zero junk
     rows in `bulk_files`.

### Known follow-ups still outstanding

- v0.22.15: broken Convert-page SSE, uncancellable `asyncio.wait_for`
  on Whisper, corrupt-audio tensor reshape.
- Pre-prod: lifecycle timers at testing values, security audit
  (62 findings), UX overhaul, DB contention instrumentation cleanup
  (now safe to remove once v0.22.18 + v0.22.19 burn-in confirms zero
  contention errors).

---

## v0.22.18 — Production-readiness sweep: lifecycle/vision/qdrant/libreoffice (2026-04-08)

Four targeted fixes from a runtime-log audit of the live `vector` branch
stack. Each one closes a recurring failure mode that was bleeding errors
into the logs without crashing the app, masking real signal and blocking
the path to production.

### What was wrong (from the audit)

A scan of `markflow.log` / `db-active.log` / `db-contention.log` over
the previous 24h surfaced four buckets:

1. **1,929 "database is locked" errors / 24h** — lifecycle scanner
   colliding with bulk_worker writes. Root cause was structural: the
   scheduler-level "skip if bulk active" guard only checks at scan
   *kickoff*. A 45-min lifecycle scan keeps walking even if a bulk job
   starts on minute 2, and the per-file `_process_file` writes don't
   use `db_write_with_retry` (bulk_worker has used it from day one for
   exactly this reason). Cancel checks existed at the directory
   boundary in the serial walk and at the *batch* boundary in the
   parallel walk — neither was checked between individual files.

2. **154 vision_adapter `describe_batch_failed` / 24h** — every single
   one was Anthropic's per-image 5 MB hard cap. The adapter already
   had a 24 MB *total request* sub-batch cap (good for the 32 MB
   request limit), but no per-image enforcement. A single 22 MB camera
   image in a batch of 10 still under-budgets the request envelope and
   then explodes on the per-image limit.

3. **381 `bulk_vector_index_fail` / 24h** — all
   `ResponseHandlingException(ReadTimeout)`. The bulk_worker already
   wraps `index_document` in try/except → `log.warning` (the audit
   overstated this as a critical failure; vector indexing is
   documented as best-effort and runs in a detached background task).
   Real fix is just bumping `AsyncQdrantClient(timeout=…)` from the
   default 5s to 60s — under bulk load, legitimate upserts were
   tripping the default.

4. **14 LibreOffice "not found" errors** — the helper raises
   `"LibreOffice not found. Install libreoffice-headless."` in TWO
   different cases: (a) neither `libreoffice` nor `soffice` is on
   PATH, and (b) one or both binaries ran fine but the conversion
   exited nonzero on a corrupt file. `Dockerfile.base` does install
   `libreoffice-writer` + `libreoffice-impress`, so the 14 errors are
   case (b) — file-level conversion failures masquerading as missing
   binary errors. Misleading message, real bug.

### Fixes

**1. `core/lifecycle_scanner.py` — yield + retry-on-lock**

- New `_process_file_with_retry()` wraps `_process_file` with
  3-attempt exponential-backoff retry on
  `OperationalError("database is locked")`. Mirrors the
  `db_write_with_retry` pattern bulk_worker uses on line 661 and the
  ETA writer.
- Both `_serial_lifecycle_walk` (per-file inner loop) and
  `_parallel_lifecycle_walk` (per-file batch loop) now check
  `_should_cancel()` between files, not just between directories /
  batches. A 10k-file folder no longer keeps writing for several
  minutes after the scan_coordinator has signalled cancel.
- Both call sites updated from `_process_file` to
  `_process_file_with_retry`.

**2. `core/vision_adapter.py` — per-image size cap**

- New module-level `_compress_image_for_vision(raw, suffix)` helper.
  Strategy: pass-through if already under 3.5 MB raw (≈4.7 MB base64,
  comfortably under Anthropic's 5 MB cap); otherwise downscale longest
  edge to 1568 px (Anthropic's own vision recommendation) and
  re-encode JPEG q=85, with q=70 fallback if still oversized.
- Wired into `describe_frame` (single-frame), `_batch_anthropic`,
  `_batch_openai`, `_batch_gemini`. Ollama is local-only and unaffected.
- Pillow is already a base dep (used by EPS/raster handlers); local
  import inside the helper avoids loading it on cold start.
- `_compress_image_for_vision` never raises — on PIL failure it
  returns the original bytes so the existing 5 MB error path still
  fires with the real provider message (just for the unfixable cases).

**3. `core/libreoffice_helper.py` — distinguish binary-missing from conversion-failed**

- Track `binary_found` flag across the
  `("libreoffice", "soffice")` loop.
- On loop exit: if `binary_found` is False, raise the existing
  "LibreOffice not found on PATH" message. If True, raise a new
  message that includes the actual stderr and exit code from the
  failing binary, e.g.
  `"LibreOffice failed to convert FOO.doc to docx (exit=77): source file could not be loaded"`.
- New `libreoffice_convert_no_output` log event for the rare
  exit-0-but-no-output-file case (corrupt files that LibreOffice
  silently drops).

**4. `core/vector/index_manager.py` — Qdrant client timeout**

- `AsyncQdrantClient(timeout=…)` now defaults to 60s (was qdrant-client's
  default 5s). Override via `QDRANT_TIMEOUT_S` env var. Vector
  indexing runs in a detached background task in `bulk_worker`, so a
  60s budget per upsert is harmless to throughput.

### Why it matters

Together these clear roughly **2,478 noisy log events / 24h** without
adding any new code paths to maintain. The 1,929 lock errors were the
loudest symptom of "MarkFlow is fragile under sustained load" — none
of them caused user-visible failures, but they made the logs unusable
for spotting real regressions. The vision and LibreOffice fixes
restore conversions that were genuinely failing every day. The Qdrant
timeout fix means vector index completeness should jump significantly
during the next sustained bulk run.

### Validation performed

- `python -m py_compile` clean on all four edited files.

### Not yet validated

- **Live rebuild + 24h burn-in.** The next overnight rebuild
  (v0.22.17 self-healing pipeline) is the natural validation window.
  Re-scan the same log buckets after one full day and confirm:
  lifecycle lock errors trend toward zero, vision batch failures
  trend toward zero, Qdrant timeouts trend toward zero, and the
  surviving LibreOffice errors carry the new specific stderr message
  instead of the old "not found" red herring.
- **Contention instrumentation cleanup.** Once the lifecycle lock
  count is verified at zero, `core/db/contention_logger.py` and the
  `db-contention.log` / `db-queries.log` / `db-active.log` writers
  can be removed (they're explicitly tagged as temporary in CLAUDE.md
  pre-prod checklist).

### Known follow-ups still outstanding

- v0.22.15: broken Convert-page SSE, uncancellable `asyncio.wait_for`
  on Whisper, corrupt-audio tensor reshape.
- Pre-prod: lifecycle timers at testing values, security audit
  (62 findings), UX overhaul.

---

## v0.22.17 — Overnight rebuild self-healing pipeline (2026-04-08)

Full refactor of `Scripts/work/overnight/rebuild.ps1` from a linear
"halt on first failure" script into a phased pipeline with retry,
rollback, and auto-diagnostics. Ships against the design spec at
`docs/superpowers/specs/2026-04-08-overnight-rebuild-self-healing-design.md`
(see §11 of that spec for two live-probe deviations from the draft).

### Why

The v0.22.16 follow-up fixes made the script's output and race handling
honest, but the script still halted on the first transient failure (a
single `git fetch` flake, a pip mirror hiccup during the 2.5 GB torch
wheel pull, a compose race the override couldn't suppress) and left
nothing actionable behind when a genuine new-build regression shipped
from a late commit. The Whisper-on-CPU (v0.22.15) and GPU-detector-
lying (v0.22.16) class of bug would both have been caught in the
morning by the user reading a dead-stack transcript — not by the
script itself. The 3 AM "stack is broken and the morning log has no
follow-up data" failure mode had to stop.

### Design principles (from the spec §2)

- **Transient tolerance (A):** retry the network-sensitive steps
  within a bounded budget. Never retry steps whose failure is
  structural (missing NVIDIA Container Toolkit, etc.).
- **Honest failure, no silent remediation:** never auto-restart
  crashed containers, never `docker system prune` on disk pressure,
  never `git reset --hard` on conflicts. These hide real bugs.
  (Auto-remediation was option B in the brainstorm — explicitly
  rejected and stays rejected.)
- **Blue/green rollback (C):** if a new build fails verification,
  retag the previous image as `:latest` and recreate. One rollback
  target only (`:last-good`), no time-travel. Refuse rollback if
  `docker-compose.yml` / `Dockerfile` / `Dockerfile.base` changed
  since the last-good commit, because a compose-old-image mismatch
  would silently half-work.
- **Morning-ready diagnostics (D):** on any non-success exit, the
  transcript contains 13 items (compose ps, logs from four services,
  two health curls, host GPU + disk, git state, sidecar, app log
  tail) — everything needed to diagnose without running a follow-up
  command.
- **Portable by default:** the GPU verification gate auto-detects
  expectation from the host, so friend-deploys on CPU-only Windows
  boxes use the script unchanged.

### Phased pipeline

```
Phase 0    Preflight       - prerequisites, record HEAD commit,
                             auto-detect expectGpu via nvidia-smi.exe
Phase 1    Source sync     - git fetch/checkout/pull     [retry 3x]
Phase 1.5  Anchor last-good - capture :latest IDs, tag as :last-good,
                              write sidecar (BEFORE build - BuildKit
                              GCs the old image as soon as :latest
                              is reassigned)
Phase 2    Image build     - docker build base + app     [retry 2x]
Phase 3    Start           - docker-compose up -d          [20s wait + race override]
Phase 4    Verify          - containers + /api/health + GPU + MCP
Phase 5    Success         - compact FINAL STATE block
```

Phases 0-2 never touch the running stack — `docker build` writes to
the image store out-of-band. On failure there, exit 1 and yesterday's
build keeps serving. Phases 3-4 have already run `up -d`, so a failure
there triggers `Invoke-Rollback`. The `$script:PreCommit` flag makes
this distinction unambiguous in the catch handler.

### Exit codes (new contract)

| Code | Meaning | Morning stack state |
|---|---|---|
| 0 | Clean success, new build verified | New build running, healthy |
| 1 | Pre-commit failure (phases 0-2) | Old build still running, untouched |
| 2 | Rollback succeeded — old build running; new build needs investigation | Old build running, healthy |
| 3 | Rollback failed — stack DOWN | Stack DOWN |
| 4 | Rollback refused — compose/Dockerfile diverged since last-good commit | New build stopped, stack DOWN |

### Key implementation details

**`Invoke-Retryable`** — wraps `Invoke-Logged` with linear-backoff
retry (5s → 10s → 20s). On success after >1 attempt, emits
`RETRY-OK: <label> succeeded on attempt N` so the morning review can
grep `RETRY-OK` to see what flaked overnight. Applied to `git fetch`,
`git pull`, `docker build` (base), and `docker-compose build`. Not
applied to `git checkout` (local, no network), the GPU toolkit smoke
test (missing toolkit is structural, not transient), or
`docker-compose up -d` (already has the race override via
`Test-StackHealthy`).

**`Invoke-RetagImage`** — Phase 1.5 helper. Tags a captured image ID
as `<image>:last-good` with one retry on failure. Atomicity is
enforced across the pair: if the markflow retag succeeds but the
mcp retag fails after its retry, Phase 1.5 aborts as exit 1 rather
than proceeding into Phase 2/3 with an out-of-sync image pair (no
safety net → don't do the risky thing).

**`Invoke-Rollback`** — five steps from spec §5.4: compose/Dockerfile
divergence check against `last-good.commit`, sidecar validation that
both image IDs still resolve via `docker image inspect` (catches a
stray `docker image prune`), retag of both `:last-good` → `:latest`,
`docker-compose up -d --force-recreate markflow markflow-mcp` (the
`--force-recreate` is load-bearing — compose won't see a tag change
as a reason to recreate by default), 20s lifespan pause, then full
re-verification via `Test-StackHealthy` + `Test-GpuExpectation` +
`Test-McpHealth` against the rolled-back stack.

**`Test-GpuExpectation`** — new Phase 4 check that closes the gap
which let v0.22.15 and v0.22.16 ship. Parses `/api/health` for
`components.gpu.execution_path` and `components.whisper.cuda`. When
`$expectGpu="container"`, asserts execution_path ∉ {container_cpu,
none} AND whisper.cuda=true. When `$expectGpu="none"`, skips the
check (CPU-only friend-deploy path). Field names were corrected
against the live `/api/health` payload during implementation —
CLAUDE.md v0.22.16 had referenced `cuda_available`, which is a
structlog event field and an internal attribute but not the HTTP
response key (see spec §11).

**`Test-McpHealth`** — new Phase 4 check, curls
`http://localhost:8001/health` (the Starlette route manually
registered in the MCP server — FastMCP.run does not accept
host/port). Catches the case where `docker-compose ps` reports
markflow-mcp as running but the MCP process inside has crashed or
failed to bind.

**`Write-Diagnostics`** — 13-item dump emitted on every non-success
exit (plus a compact `FINAL STATE` block on exit 0). Budget ~20s
total. Every command wrapped in `Invoke-Logged -AllowNonZero` so a
failing diagnostic command can't abort the capture. Dumps:
`docker-compose ps`, 100-line tail of markflow + markflow-mcp logs,
20-line tail of meilisearch + qdrant logs, verbose curl of both
`/api/health` endpoints, `nvidia-smi.exe`, `wsl df -h /`,
`git log -5 --oneline` + `git status --short`, the `last-good.json`
sidecar, and the last 100 lines of `logs/app.log`.

**Phase 0 GPU auto-detection — diverges from spec §6.3 intentionally.**
The spec called for `wsl.exe -e nvidia-smi` as the host probe, but
that fails on the reference workstation (WSL2 default distro has no
nvidia-smi — Docker Desktop's GPU passthrough uses the NVIDIA
Container Toolkit independently). `nvidia-smi.exe` from the Windows
driver install (in System32, on PATH) is the authoritative probe
and correctly resolves `expectGpu=container` on the reference host.

### Sidecar file

`Scripts/work/overnight/last-good.json` — per-machine, gitignored via
a new rule in `.gitignore`. Written by Phase 2.5 on a successful
retag. Schema:

```json
{
  "commit": "<HEAD SHA before tonight's pull>",
  "tagged_at": "2026-04-08T03:14:27-07:00",
  "markflow_image_id": "sha256:...",
  "mcp_image_id": "sha256:...",
  "host_expects_gpu": true
}
```

The `commit` field is the pre-pull HEAD recorded in Phase 0 — i.e.
the commit that PRODUCED the image currently being tagged as
`:last-good`, not tonight's new HEAD. This is what the rollback
compose-divergence check compares against.

### New parameters

`-DryRun` — runs Phase 0 preflight + GPU detection for real, but
logs-and-skips every git/docker command. Validates script-level
control flow without side effects. Always exits 0. Used during
implementation to verify all seven phase transitions before any
live runs.

### Validation performed

- PowerShell parser clean (`[Parser]::ParseFile`).
- Dry-run end-to-end: all phases 0 → 5 transition cleanly,
  `expectGpu=container` correctly resolved via nvidia-smi.exe.
- `Get-ImageId` against live `doc-conversion-2026-markflow:latest`
  and `doc-conversion-2026-markflow-mcp:latest` — returns the
  expected sha256 IDs.
- `Test-GpuExpectation` against the currently running stack — passes
  with `execution_path='container', whisper.cuda=true`.
- `Test-McpHealth` against `http://localhost:8001/health` — passes.
- `Test-StackHealthy` regexes confirmed to match the real
  `/api/health` response shape (components are nested under
  `components.*` but the regexes happen to work because they scan
  the full body and no nested `{}` appears between each component's
  opening brace and its `ok` field).

### Bugs caught and fixed during staged live-run validation

The first staged live run (`-SkipPull -SkipBase -SkipGpuCheck`,
invoked as the "refresh container" step of this release cycle)
surfaced four real bugs in the initial implementation. All fixed
before committing.

**Bug A — Phase 2.5 retag-after-build was structurally impossible.**
The draft spec assumed "build N is still resident on the host but
reachable only by sha ID" after `docker-compose build` replaces
`:latest`. That assumption is wrong on modern BuildKit: the old
image is garbage-collected the moment its `:latest` tag is dropped.
Phase 2.5's `docker tag <prev-sha> :last-good` failed with `Error
response from daemon: No such image: sha256:...`. **Fix:** moved the
retag + sidecar write into Phase 1.5 (renamed "Anchor last-good"),
BEFORE Phase 2 build. Tagging the current `:latest` as `:last-good`
pre-build gives the image store a second reference that keeps the
old image resident across the build. Phase 2.5 deleted.

**Bug B — `Test-StackHealthy` leaked `NativeCommandError` decoration
on every `docker-compose ps` call.** Same class as the v0.22.16
follow-up (commit 54d6808). The helper used `$ErrorActionPreference
= "Continue"` locally and relied on `2>$null` to suppress
docker-compose's symlink-warning stderr. With EAP=Continue, PS 5.1
auto-displays native stderr as `NativeCommandError` ErrorRecords
BEFORE the `2>$null` redirection takes effect, so the transcript
filled with `docker-compose.exe : time="..." level=warning ...  /
At ...rebuild.ps1:300 char:20 / FullyQualifiedErrorId :
NativeCommandError` spam on every probe attempt. **Fix:**
`$ErrorActionPreference = "SilentlyContinue"` inside
`Test-StackHealthy` (same pattern as Invoke-Logged). Documented in
the function's comment block so future edits can't re-regress this.

**Bug C — Invoke-RetagImage swallowed stderr with `Out-Null`,
hiding the actual docker error from the morning log.** Made it
impossible to diagnose Bug A without manually re-running the tag
command. **Fix:** capture stderr into a variable and `Write-Host`
each line (with ErrorRecord -> Exception.Message projection) on
retag failure.

**Bug D — Phase 3's race-override path called `Test-StackHealthy`
immediately after `up -d` non-zero exit, without any lifespan
wait.** The 3x5s=15s retry budget is not enough for a cold
container start that takes ~20s for FastAPI lifespan startup. On
the second staged run, a perfectly healthy new build got rolled
back unnecessarily because the health probe hit the container
before uvicorn finished binding. This was actually a FALSE
ROLLBACK - the build was functionally identical to the one being
rolled back to. The self-healing pipeline did the right thing
gracefully on a false positive, but the gate was over-eager.
**Fix:** moved the 20-second lifespan pause from Phase 4 to the
END of Phase 3 (after `up -d`, BEFORE any health probe, on both
the clean-exit and race-override branches). Also added the same
lifespan pause before `Test-StackHealthy` in `Invoke-Rollback`'s
recreate step, which had the symmetric race. Phase 4 no longer
sleeps - Phase 3 already did.

### Final validation — third live run

After fixes A-D, re-ran `-SkipPull -SkipBase -SkipGpuCheck`:
- Phase 1.5 captured both image IDs AND successfully tagged them
  as `:last-good` AND wrote `last-good.json` BEFORE the build.
- Phase 2 rebuilt the app layer in ~57s.
- Phase 3 `up -d` exited 1 (compose post-start race, as expected
  from v0.22.16), waited 20s, `Test-StackHealthy` passed on the
  first attempt, race override engaged.
- Phase 4: `Test-StackHealthy`, `Test-GpuExpectation` (reporting
  `execution_path='container', whisper.cuda=true`), and
  `Test-McpHealth` all passed.
- Phase 5: FINAL STATE block clean, exit 0, total runtime 1:36.
- **No NativeCommandError decoration anywhere in the transcript.**
- Stack now running image from commit d46944c with
  `core/version.py = 0.22.17`.

### Still deferred — requires deliberate break, not a normal run

- Forced rollback rehearsal (break a runtime import to fail
  Phase 4; observe rollback path + exit 2). The self-healing
  pipeline already executed a successful rollback during Bug D
  surfacing, but that was a false-positive scenario - a true
  runtime-broken-build rehearsal has not been performed.
- Compose-divergence rehearsal (edit docker-compose.yml after a
  successful run, force Phase 4 failure, expect exit 4).

Recommended before the next unattended cycle.

### Modified files

- `Scripts/work/overnight/rebuild.ps1` — full refactor (~730 lines).
- `.gitignore` — added `Scripts/work/overnight/last-good.json`.
- `docs/gotchas.md` — two new entries in a new "Overnight Rebuild &
  PowerShell Native-Command Handling" section: (1) Start-Transcript
  does not capture native output → the Invoke-Logged +
  SilentlyContinue + variable-capture pattern; (2) docker-compose ps
  --format json cannot be regex'd across fields because Publishers
  has nested `{}`, use per-line ConvertFrom-Json.
- `docs/superpowers/specs/2026-04-08-overnight-rebuild-self-healing-design.md` —
  status flipped to Implemented, §10 open questions resolved, new
  §11 "Implementation notes & spec deviations" documents the GPU
  probe change and the `cuda_available` → `cuda` field correction.

### Known v0.22.15 follow-ups still outstanding

(Unchanged from v0.22.16.) Broken Convert-page SSE; uncancellable
`asyncio.wait_for` on Whisper; corrupt-audio tensor reshape.

---

## v0.22.16 — GPU detector WSL2 honesty + overnight rebuild resilience (2026-04-08)

Two follow-ups to the v0.22.15 GPU work, both surfaced the same night by
the overnight rebuild script and the Resources-page widget reporting
`CPU (no GPU detected)` on a host where Whisper was clearly running on
CUDA.

### Issue #1 — GPU detector lied on WSL2 Docker Desktop

**Symptom:** After v0.22.15, `docker-compose logs markflow | grep whisper`
showed `cuda_available=true, gpu_name="NVIDIA GeForce GTX 1660 Ti"`, yet
`/api/health` and the Resources widget reported
`gpu.execution_path="container_cpu"` and
`gpu.effective_gpu="CPU (no GPU detected)"`. Same GPU, two sources of
truth disagreeing.

**Root cause:** `core/gpu_detector.py` resolved `execution_path` by
requiring BOTH `container_gpu_available` AND
`container_hashcat_backend in ("CUDA","OpenCL")`. On WSL2 Docker Desktop,
`nvidia-smi` succeeds inside the container (the NVIDIA Container Toolkit
injects `libcuda.so`), but `hashcat -I` reports CPU (pocl) only because
the toolkit's WSL2 path does not inject `libnvidia-opencl.so.1` — the
`opencl` driver capability is rejected. CUDA workloads (torch, Whisper)
are unaffected; hashcat falls back to CPU. The old resolver treated
"hashcat can't see the GPU" as "there is no GPU," which was never the
intent.

**Fix:** New second tier in the `detect_gpu()` / `get_gpu_info_live()`
priority ladder: if `container_gpu_available` is true but the hashcat
backend is not CUDA/OpenCL, still resolve `execution_path="container"`,
use the real `container_gpu_name`, and set `effective_backend="CUDA"`.
Consumers that specifically need hashcat GPU acceleration can inspect
`container_hashcat_backend` directly — they weren't getting GPU hashcat
in either the old or new behavior, the lie was just one level removed.
The resolver is now a documented 5-tier ladder (see the priority comment
in `detect_gpu()`): container GPU+hashcat → container GPU+CUDA-only →
host worker GPU → container CPU → none. `get_gpu_info_live()` carries
the same ladder verbatim so the live re-resolve after the host worker
file appears doesn't diverge.

**Logging:** Added `container_hashcat_backend` to the `gpu.resolution`
log line so future diagnostics don't have to cross-reference two events.

**Test:** New `test_detect_nvidia_container_hashcat_cpu_only` in
`tests/test_gpu_detector.py` asserts the WSL2 case: nvidia-smi returns a
1660 Ti, hashcat `-I` returns CPU (pocl), and the detector resolves
`execution_path="container"` with the real GPU name and
`effective_backend="CUDA"`. All 14 tests in the module pass.

**Modified files:**
- `core/gpu_detector.py` — new priority tier in `detect_gpu()` and
  `get_vector_info_live()` [sic: `get_gpu_info_live()`], documented
  5-tier comment, `container_hashcat_backend` in resolution log.
- `tests/test_gpu_detector.py` — WSL2 CPU-only hashcat regression test.

### Issue #2 — Overnight rebuild script had empty transcript logs and false failures

**Symptom #1:** `Scripts/work/overnight/rebuild.ps1` runs unattended at
~3 AM and writes a transcript log. Morning review on 2026-04-08 found
section headers (`>>> git fetch origin`, `>>> docker build...`) with
empty bodies — none of the native command output was captured. Useless
for forensics.

**Symptom #2:** On a successful rebuild where the stack came up fine,
`docker-compose up -d` returned exit code 1 because its post-start
cleanup lost a race with the Docker Desktop reconciler
(`No such container: <old id>`) even though the replacement container
was already running. The script threw, the user was paged, but the
stack was actually healthy.

**Root causes:**
1. **PS 5.1 `Start-Transcript` does not capture native stdout/stderr.**
   Native executables (docker, git, curl, nvidia-smi) bypass the PS host
   and write directly to the console device. Transcript only records
   output that goes *through* the host.
2. **`2>&1` in PS 5.1 wraps native stderr as `RemoteException` records.**
   Even when those are piped through `Write-Host`, the default render
   adds the full error-decoration envelope (`CategoryInfo`, etc.) and
   dominates the log.
3. **`$ErrorActionPreference = "Stop"` + native stderr warnings** (e.g.
   docker-compose's "project has been loaded without an explicit name
   from a symlink") cause `2>&1` to terminate the whole pipeline before
   `$LASTEXITCODE` can even be inspected.
4. **Compose exit 1 on a working stack.** No way to distinguish the
   race-override case from a real failure without probing the stack.

**Fix:** New `Invoke-Logged` helper replaces `Assert-ExitCode`. It:
  - Wraps the native invocation in a `scriptblock` passed as `-Command`.
  - Temporarily relaxes `$ErrorActionPreference` to `Continue` so
    harmless stderr warnings don't abort the pipeline.
  - Pipes output through `ForEach-Object { Write-Host }`, stringifying
    `ErrorRecord` objects via `$_.Exception.Message` so the log shows
    plain text instead of PS decoration.
  - Checks `$LASTEXITCODE` authoritatively and throws on non-zero
    unless `-AllowNonZero` is given.

Every step in `rebuild.ps1` (GPU smoke test, git fetch/checkout/pull,
base image build, app build, `docker-compose up`, container status,
health check) now routes through `Invoke-Logged` — the transcript now
captures every line of native output.

New `Test-StackHealthy` function handles the compose race: when
`docker-compose up -d` exits non-zero under `-AllowNonZero`, the script
probes `docker-compose ps --format json` (markflow + markflow-mcp both
running) and `curl /api/health` (top-level status ok, database ok,
meilisearch ok). Policy is deliberately conservative: 3 attempts, 5
seconds apart, all checks must pass, false = genuine failure. Whisper
CUDA is intentionally *not* required so the script stays portable to
friend-deploys on CPU-only hosts. On true healthy-but-compose-returned-1,
the rebuild is marked successful and no one gets woken up.

**Modified files:**
- `Scripts/work/overnight/rebuild.ps1` — `Invoke-Logged` helper,
  `Test-StackHealthy` post-start probe, every native call routed through
  the helper, health-check banner updated to mention v0.22.16
  `gpu.execution_path="container"` expectation.

### Why it matters

The widget lie was a trust issue — users would see "CPU" and assume
v0.22.15 hadn't landed, then either disable Whisper or file a ghost bug.
The rebuild script issues meant overnight automation couldn't be trusted
to self-report: every morning needed a manual status check, and the one
time the stack *did* come up through a compose race, it looked like a
failure. Both fixes restore honesty in the reporting layer without
touching any workload code.

### Known follow-ups (not in this release)

- The v0.22.15 SSE / `asyncio.wait_for` / corrupt-audio items are still
  outstanding.
- `Test-StackHealthy`'s regex JSON matching is fine for today's health
  payload but will need a proper parser if the shape grows nested.

---

## v0.22.15 — GPU Whisper + Audio Fallback Graceful Fail (2026-04-07)

Two related problems surfaced by diagnosing a stuck manual-convert batch
of four MP3 files on the Convert page. Batch `20260408_021247_8847` stalled
after 17 hours with one file failing on a Whisper tensor-reshape error,
one failing on an empty cloud-provider list, and two others stuck mid-load.

### Issue #1 — Whisper was running on CPU despite having a GTX 1660 Ti

**Symptom:** `whisper_device_auto` events logged `"device": "cpu",
"cuda_available": false` on every batch. A 75-minute MP3 (`240306_1116.mp3`)
sat for hours with no progress after the model-load event. The machine
has a GTX 1660 Ti (Turing / CC 7.5) that should have been doing the work
in ~10-15 minutes instead of ~17 hours.

**Root cause:** Two bugs stacked, either of which would have been enough
on its own:

1. **`Dockerfile.base:63`** installed the CPU-only PyTorch wheel via
   `pip install torch --index-url https://download.pytorch.org/whl/cpu`.
   That wheel ships no CUDA libraries at all, so `torch.cuda.is_available()`
   returned `False` inside the container regardless of what Docker passed
   through. The CPU-only wheel was chosen to keep the base image small
   (~200 MB vs ~2.5 GB) during early development, and that choice became
   a silent production cap.
2. **`docker-compose.yml`** had no GPU reservation on the `markflow`
   service — no `deploy.resources.reservations.devices` block, no
   `runtime: nvidia`, no `NVIDIA_VISIBLE_DEVICES` env var. Even if torch
   had been CUDA-enabled, the container had zero visibility into host
   GPU devices.

**Fix:** Switched the base image to the CUDA 12.1 wheel
(`whl/cu121`) and added a `deploy.resources.reservations.devices` block
to the `markflow` service requesting `driver: nvidia, count: 1`. On
hosts without an NVIDIA GPU, `torch.cuda.is_available()` returns `False`
and Whisper transparently falls back to CPU — so the same image works
on GPU and CPU-only machines. Friends deploying on GPU-less hosts can
comment out the compose block and the app still runs. Host prereq:
NVIDIA Container Toolkit installed inside the WSL2 distro (Windows) or
the `nvidia-container-toolkit` package (Linux).

**Why CUDA 12.1 specifically:** GTX 1660 Ti is Turing (CC 7.5) and
supports every current CUDA release; cu121 is the mainstream default
with broad driver compatibility (≥ 525), smaller than cu124 (~2.5 GB vs
~2.7 GB), and large enough to cover any modern RTX card a friend-deploy
might have.

**Modified files:**
- `Dockerfile.base:61-70` — comment block + `whl/cu121` index URL
- `docker-compose.yml:64-75` — `deploy.resources.reservations.devices`
  block with inline commenting explaining how to disable for CPU-only hosts

### Issue #2 — Cloud fallback failed cryptically when no audio provider exists

**Symptom:** When Whisper crashed on `240306_1004.mp3` (corrupt audio →
tensor reshape error), the cloud fallback logged:

```
All cloud providers failed. Last error: None.
Audio-capable providers checked: []
```

This is a two-part problem: (a) the empty list shows no eligible provider
was ever found, so the loop didn't iterate and `last_error` stayed `None`;
(b) the final user-facing error was the generic "all transcription methods
failed", which gave the user no indication of what to actually fix.

**Root cause:** The user has only Anthropic / Claude configured as an AI
provider. Claude does not support audio input (it handles text, images,
and PDFs, but not audio). `AUDIO_CAPABLE_PROVIDERS` in `cloud_transcriber.py`
correctly maps `anthropic: False`, so the loop skipped every candidate and
fell through to the terminal `RuntimeError` with a meaningless message.
There was no pre-flight check, no distinct exception type, and no
user-actionable guidance — just a stack trace mentioning "Last error: None".

**Fix:** Three-layer graceful-fail:

1. **New exception type** — `NoAudioProviderError` in `core/cloud_transcriber.py`,
   subclass of `RuntimeError`, raised when the eligible-provider list is
   empty. Distinct from generic provider failures (rate limits, API errors)
   so the caller can distinguish "config issue, user action needed" from
   "transient failure, maybe retry".
2. **Pre-flight in `CloudTranscriber.transcribe()`** — compute the eligible
   list (audio-capable provider type AND api_key present) up front. If
   empty, raise `NoAudioProviderError` with the full context: which providers
   the user has configured, which provider types support audio, and
   exactly what to do (add an OpenAI or Gemini key). Logs a `warning`-level
   event `cloud_transcribe_no_audio_provider` with both lists for post-mortem.
3. **Dedicated catch in `transcription_engine.py`** — separate `except
   NoAudioProviderError` clause that logs the condition at `info` level
   (this is a config state, not a bug) and raises a user-facing `RuntimeError`
   with actionable text: "Cannot transcribe <file>: local Whisper failed or
   is unavailable, and no cloud provider that supports audio is configured.
   Add an OpenAI or Gemini API key in Settings → AI Providers, or
   troubleshoot Whisper/GPU setup. (Anthropic/Claude does not currently
   support audio.)"

The existing terminal `RuntimeError` message was also tightened — it now
only fires when eligible providers exist but all actually failed, so the
"Last error" field is always populated with a real cause.

**Why distinguish the two failure modes:** They lead to different user
actions. "No provider configured" is a Settings-screen fix. "All providers
failed with real errors" is a "check API key expiry / billing / outage"
fix. Lumping them into one message left the user guessing.

**Modified files:**
- `core/cloud_transcriber.py:29-48` — added `NoAudioProviderError` class,
  enriched the `AUDIO_CAPABLE_PROVIDERS` comment with the Anthropic caveat
- `core/cloud_transcriber.py:67-105` — pre-flight eligibility check, logs
  `cloud_transcribe_no_audio_provider` warning, raises typed exception
- `core/cloud_transcriber.py:117-124` — tightened terminal error message
- `core/transcription_engine.py:104-148` — `NoAudioProviderError` catch
  + branched user-facing error message
- `docs/gotchas.md` — Media & Transcription section updated with GPU
  passthrough, Anthropic no-audio graceful fail, and Dockerfile.base
  CUDA wheel entries
- `docs/help/troubleshooting.md` — new "Audio or Video Transcription
  Fails" section with Whisper model sizing table and ffmpeg re-encode
  recipe for corrupt audio
- `core/version.py` — 0.22.14 → 0.22.15

### Side-findings (flagged for a future release, not fixed here)

These surfaced during the log diagnostic but are out of scope for this
release:

- **`/api/batch/.../stream` returned 404** on the Convert page SSE
  progress channel at batch start. The UI has no live progress for
  manual-convert batches.
- **`asyncio.wait_for` does not cancel threadpool work.**
  `transcription_engine.py:73-81` wraps `WhisperTranscriber.transcribe`
  in `asyncio.wait_for(timeout=3600)`, but the actual transcription runs
  inside `asyncio.to_thread`. CPython cannot cancel a running thread, so
  the timeout fires at 3600 s but the thread keeps running — which
  explains why the 75-min file's timeout event never logged.
- **Whisper should catch and re-raise corrupt-audio errors with a
  cleaner message.** The `cannot reshape tensor of 0 elements into
  shape [1, 0, 16, -1]` error on `240306_1004.mp3` should surface as
  "audio file contains no decodable frames" so the user can re-encode.
- **`convert_batch_completed` event never fires** in `api/routes/convert.py`
  — only the per-file `file_conversion_complete` or `_error` events. Makes
  "is the batch done?" hard to answer from logs alone.

---

## v0.22.14 — Log Diagnostic Fixes (2026-04-07)

A diagnostic log scan after v0.22.13 surfaced four issues. All four
addressed in this release.

### Issue #1 — Vector indexing was blocking conversion (BIGGEST IMPACT)

**Symptom:** `bulk_vector_index_fail` warnings every 2-3 files with an
empty error string. Conversion rate dropped to **0.048 files/sec → ETA
6.6 days for the in-flight 28k-file job**.

**Root cause:** `core/bulk_worker.py:819` did
`await vec_indexer.index_document(...)` synchronously inside the worker
loop. When Qdrant timed out (60s default httpx timeout) the worker
blocked for the full timeout per file. Math: 5s convert + 60s qdrant
timeout = 65s/file = ~0.015 files/sec; observed 0.048 ≈ ~1 in 3 files
hitting the timeout.

The empty error string was a separate logging defect: `ReadTimeout(TimeoutError())`
stringifies to empty when the inner `TimeoutError()` has no message.
`str(exc)` produced `""`, masking the failure entirely.

**Fix:** New module-level helper `_index_vector_async()` in
`core/bulk_worker.py`. The worker now does:

```python
asyncio.create_task(_index_vector_async(...))
```

instead of `await vec_indexer.index_document(...)`. The vector indexing
runs as a detached background task; the worker immediately moves to the
next file. Errors logged with `repr(exc)` and `exc_type=type(exc).__name__`
so empty stringify no longer hides the failure.

**Expected impact:** 5-10x throughput restoration when Qdrant is slow.
Worker rate should return to its natural conversion speed; vector
indexing catches up async.

### Issue #2 — `database is locked` was permanently failing files

**Symptom:** 13 lock-contention events / 30 min, 4 of which were
non-recoverable:

- `bulk_worker_unhandled error='database is locked'` — file marked
  `failed` (real bug, lost work)
- `analysis_worker.drain_failed`
- `auto_metrics_aggregation_failed`
- `adobe_index_error` + `adobe_l2_index_failed`

**Root cause:** Multiple writers (4 bulk workers + Adobe L2 indexer +
analysis worker drain + auto_metrics aggregator + cleanup jobs +
contention logger) all competing for the SQLite WAL. The in-flight
retry helper `db_write_with_retry()` saved most cases, but several code
paths bypassed it.

**Fix:**

1. **`core/bulk_worker.py` `_worker()` top-level except**: now
   distinguishes `"database is locked"` from real failures. On lock
   error, logs a `bulk_worker_db_lock_requeue` warning and `continue`s
   (leaves the file `pending`); does NOT update status, NOT increment
   the failed counter, NOT emit `file_failed`. The next worker pass
   over the pending list retries the file naturally.

2. **`core/adobe_indexer.py`**: `upsert_adobe_index()` is now wrapped in
   `db_write_with_retry()`. Lock errors are retried with backoff
   instead of bubbling out as a permanent `adobe_index_error`.

3. **`core/analysis_worker.py`** and **`core/auto_metrics_aggregator.py`**:
   the top-level `except` blocks now check for `"database is locked"` in
   the error string and downgrade to a warning. The next scheduled drain /
   aggregation tick retries naturally — these are already periodic jobs,
   so missing one tick during heavy contention is harmless.

### Issue #3 — Vision API 400 errors had no diagnostic detail

**Symptom:** `vision_adapter.describe_batch_failed count=10 error="Client
error '400 Bad Request' for url '.../v1/messages'"`. The
`analysis_queue` had **1,150 failed vs 90 completed** — vision pipeline
mostly broken with no way to identify the offending image.

**Fix:** `core/vision_adapter.py:describe_batch()` `except` block now
captures the HTTP response body via `getattr(exc, "response", None)` and
logs:

```python
log.error(
    "vision_adapter.describe_batch_failed",
    provider=...,
    count=...,
    error=str(exc),
    exc_type=type(exc).__name__,
    response_body=response.text[:500],
    first_image=str(image_paths[0]),
)
```

The actual Anthropic error message (e.g. "Image exceeds 5MB", "Invalid
base64") and the first image path now appear in logs. Also propagated
into the per-row `BatchImageResult.error` field so the `analysis_queue`
table itself shows the real reason. Next log scan will be able to
bisect the offending images.

### Issue #4 — Ghostscript missing for `.eps` conversion

**Symptom:** `image_handler.convert_failed Unable to locate Ghostscript
on paths`. EPS files in source share were uniformly failing.

**Fix:** Added `ghostscript` to `Dockerfile.base`'s apt install list for
the long term. Also added a separate `apt-get install -y ghostscript`
layer in the app `Dockerfile` so this version can ship without a 25-min
base image rebuild. The next time `Dockerfile.base` is rebuilt, the
duplicate becomes a no-op (apt-get reports already-installed) and the
app-Dockerfile line can be removed.

### Modified files

- `core/version.py` — 0.22.13 → 0.22.14
- `core/bulk_worker.py` — `_index_vector_async()` helper, async vector
  task, db-lock requeue branch in worker handler
- `core/analysis_worker.py` — db-locked downgrade
- `core/auto_metrics_aggregator.py` — db-locked downgrade
- `core/adobe_indexer.py` — `upsert_adobe_index` via `db_write_with_retry`
- `core/vision_adapter.py` — capture response body + first_image path
- `Dockerfile.base` — add `ghostscript`
- `Dockerfile` — temporary `apt-get install ghostscript` layer
- `CLAUDE.md`, `docs/version-history.md` — updates

### Verification plan

1. Rebuild + restart container.
2. Trigger lifecycle scan.
3. Wait 5 minutes for the bulk worker to process some files.
4. Re-run the log scan from this session and confirm:
   - `bulk_progress` rate has jumped (target: at least 5x previous)
   - No `bulk_worker_unhandled error='database is locked'` events
   - Adobe L2 errors gone (or reduced to retried warnings)
   - Vision 400 logs now include response body
   - `image_handler.convert_failed` for EPS gone

---

## v0.22.13 — Active Connections Widget (2026-04-07)

**Asked in chat:** "Under the resources page — are you able to show how
many connections are active on the website?"

The Resources page previously tracked CPU/RAM/disk metrics, activity log,
OCR quality, and scan throttle history but had no concept of "who/what is
currently using MarkFlow". This release adds a small in-memory tracker
plus a polled widget to show:

1. **Recently active users** — sliding window (default 5 minutes) of who
   has made an authenticated request, sorted most-recent-first.
2. **Live SSE / streaming connections** — exact count of long-lived
   StreamingResponse generators currently open, bucketed by endpoint
   label so admins can see which features are in active use.

### Why no DB schema

Both counters are in-process dicts. Resets on container restart are
**intentional** — these are "right now" diagnostics, not historical
metrics. The widget shows 0 immediately after a rebuild and refills
within seconds as clients reconnect. Avoiding the DB also avoids write
contention with the bulk worker / scanner during heavy load.

### Code changes

- **`core/active_connections.py`** (new, ~150 lines):
  - `_user_last_seen: dict[str, tuple[str, str]]` — sub → (iso_ts, email)
  - `_active_streams: dict[str, int]` — endpoint label → count
  - `record_request_activity(user_sub, user_email)` — middleware hook
  - `get_active_users(window_seconds)` — sliding window query that
    drops stale entries on every call (so the dict can't grow unbounded
    over a long-running process)
  - `track_stream(endpoint)` — async context manager that increments
    on enter and decrements in `finally`. Exception-safe so client
    disconnects (`CancelledError` / `BrokenPipeError`) still drop the
    counter back.
  - `get_active_streams()` / `get_total_active_streams()`

- **`core/auth.py`** — `get_current_user()` stashes the resolved
  `AuthenticatedUser` on `request.state.user` (in all 3 auth paths:
  DEV_BYPASS_AUTH, X-API-Key, JWT Bearer). This is the integration point
  the middleware needs.

- **`api/middleware.py`** — `RequestContextMiddleware.dispatch()` reads
  `getattr(request.state, "user", None)` after `call_next()` returns and
  fires `record_request_activity(user.sub, user.email)`. Skips silently
  for unauthenticated routes (e.g. `/api/health`, static assets).

- **SSE generators wrapped** with `async with track_stream(...)`:
  - `api/routes/bulk.py` — `bulk_job_events`, `ocr_gap_fill`
  - `api/routes/batch.py` — `batch_progress` (refactored: outer
    `event_generator()` wraps the body in `track_stream`, original body
    moved to inner `_batch_event_generator()`)
  - `core/ai_assist.py` — `ai_assist_search`, `ai_assist_expand`
    (same refactor pattern: outer wrapper + inner `_impl()` body)

- **`api/routes/resources.py`** — new admin-only endpoint:
  ```
  GET /api/resources/active?window_seconds=300
  ```
  Returns:
  ```json
  {
    "window_seconds": 300,
    "users": [{"sub": "...", "email": "...", "last_seen": "..."}, ...],
    "total_users": 5,
    "total_streams": 3,
    "streams_by_endpoint": {"bulk_job_events": 2, "ai_assist_search": 1}
  }
  ```

- **`static/resources.html`** — new "Active Connections" section between
  the Live System Metrics and Activity Log sections. Two cards
  side-by-side:
  - **Active Users** — count badge + scrollable list
    (`email` left-aligned, "Xs ago" right-aligned). 200px max height.
  - **Live Streams** — count badge + scrollable list (endpoint label
    monospaced, count badge right-aligned). Sorted by count desc.
  Both rendered with safe DOM construction (no innerHTML / template
  injection). Polled every 5 seconds via `pollActiveConnections()`.
  Polling pauses when the tab is hidden (visibility change handler).

### Limitations / known non-features

- **Anonymous traffic is invisible.** The auth model has no concept of an
  unauthenticated visitor identity, so there's nothing to count. Anyone
  hitting the app is either authenticated (counted under users) or holds
  an SSE stream (counted under streams).
- **Two browser tabs in one browser look like one user** because they
  share the same JWT `sub`.
- **DEV_BYPASS_AUTH=true makes everything look like the user "dev"** —
  expected, since that's the only identity the auth dependency hands out
  in dev mode.
- The endpoint requires admin role. Non-admins polling it get a silent
  failure in the widget (the "--" badges stay).

### Modified files

- `core/version.py` — 0.22.12 → 0.22.13
- `core/active_connections.py` — new
- `core/auth.py` — stash user on request.state
- `api/middleware.py` — record activity hook
- `core/ai_assist.py` — wrap both stream functions
- `api/routes/bulk.py` — wrap two SSE generators
- `api/routes/batch.py` — wrap batch progress generator
- `api/routes/resources.py` — `/api/resources/active` endpoint
- `static/resources.html` — new section + JS poller
- `CLAUDE.md`, `docs/version-history.md` — updates

---

## v0.22.12 — AI Assist Settings Copy Fix + Provider Badge (2026-04-07)

**Problem:** The Settings page "AI-Assisted Search" section still carried
v0.21.0-era copy under the "Enable AI Assist" toggle:

> Allows users to synthesize search results via Claude.
> Requires `ANTHROPIC_API_KEY` in the environment.

This was wrong as of v0.22.10 (AI Assist reads from `llm_providers`) and
doubly wrong as of v0.22.11 (per-provider opt-in flag). Admins reading the
text would still think they needed to set an env var.

The user also wanted the section to clearly tell them that AI Assist uses
the same provider system as **Vision & Frame Description** and **AI
Enhancement** above it on the same page.

**Fix:** `static/settings.html`:

- Replaced the stale "Requires `ANTHROPIC_API_KEY`" line with:
  > Allows users to synthesize search results via Claude. Uses the
  > provider shown above — no environment variable required.
- Added a top-of-section blurb above the toggle:
  > AI Assist uses the same LLM provider system as **Vision & Frame
  > Description** and **AI Enhancement** above. By default it uses the
  > provider marked _Active_ on the Providers page; you can override
  > this by clicking _Use for AI Assist_ on a specific provider. AI
  > Assist requires an Anthropic provider.
- Added a new live provider-info badge (`#ai-assist-provider-info`)
  rendered from the `/api/ai-assist/status` response. It shows
  `Provider: anthropic · claude-opus-4-6 · opted-in via "Use for AI
  Assist"` (or `falling back to the Active provider`, or `using the
  legacy ANTHROPIC_API_KEY env var (deprecated)`, or `no provider
  configured`) plus a "Manage Providers →" link. Built with safe DOM
  construction (no innerHTML).

**Why this matters:** UX clarity. The previous text was a recipe for
support tickets ("I set ANTHROPIC_API_KEY in .env but the toggle still
won't enable"). Now the section explicitly tells admins which provider
record AI Assist will use, where it came from, and how to switch it.

### Modified files

- `core/version.py` — 0.22.11 → 0.22.12
- `static/settings.html` — section copy + provider info badge + JS render
- `CLAUDE.md`, `docs/version-history.md` — updates

---

## v0.22.11 — Per-Provider "Use for AI Assist" Opt-In (2026-04-07)

**Problem (raised in chat):** v0.22.10 wired AI Assist to use the active
`llm_providers` record. But what if the admin wants AI Assist to use a
DIFFERENT provider than the image scanner? For example: image analysis
runs against a cheap Gemini provider for vision OCR, while AI Assist runs
against an Anthropic provider for natural-language synthesis. With v0.22.10
the two features were locked to the same active provider.

**Fix:** Add a per-provider opt-in flag (`use_for_ai_assist`) and a
checkbox/button on the Providers page. The flag is mutually exclusive across
providers (exactly like `is_active`) but **independent** from `is_active`.

### Schema

Migration #25:
```sql
ALTER TABLE llm_providers ADD COLUMN use_for_ai_assist INTEGER NOT NULL DEFAULT 0;
```

The base `CREATE TABLE` definition for `llm_providers` was also updated so
fresh installs get the column without relying on the migration.

### Code changes

- **`core/db/catalog.py`** — two new helpers:
  - `get_ai_assist_provider()` — returns the row with `use_for_ai_assist=1`,
    api_key DECRYPTED, or None.
  - `set_ai_assist_provider(provider_id | None)` — clears the flag on every
    row, then sets it on the named row. Pass `None` to clear entirely.

- **`core/db/__init__.py`** — re-exports the two new helpers via the
  `core.db` package so `from core.database import ...` works.

- **`core/ai_assist.py`** — `_get_provider_config()` is now a 3-step lookup:
  1. **Opted-in provider** — `get_ai_assist_provider()`. Preferred path.
  2. **Active provider** — `get_active_provider()`. Backward-compat fallback
     for users who haven't opted in a specific AI Assist provider yet.
  3. **`ANTHROPIC_API_KEY` env var** — last-resort legacy fallback.
  Returns a new field `provider_source` with one of `"opted_in"`,
  `"active_fallback"`, `"env_fallback"`, or `"none"` so the UI can render
  an accurate state indicator.

- **`api/routes/llm_providers.py`**:
  - `CreateProviderRequest` and `UpdateProviderRequest` gain an optional
    `use_for_ai_assist: bool` field. When True on create, the new provider
    is opted in immediately (and the flag is cleared on all others).
  - `update_provider()` handles the flag separately from other fields
    because the flip-others-to-zero behavior is mutually exclusive and
    cannot be done via a generic UPDATE — calls `set_ai_assist_provider()`
    instead.
  - New endpoint `POST /api/llm-providers/{id}/use-for-ai-assist` that
    accepts a literal `id` to opt in, or `id="none"` to clear.

- **`static/providers.html`**:
  - Add-provider form gains a "Also use this provider for the AI Assist
    search feature" checkbox with an explanatory hint.
  - Save logic warns (but allows) opting in a non-Anthropic provider —
    AI Assist will then surface a clear "incompatible" notice when invoked.
  - Provider cards refactored from template-string injection to safe DOM
    construction (`_renderProviderCards()`). Each card shows:
    - Existing **Active** badge (green) if `is_active`
    - New **AI Assist** badge (purple) if `use_for_ai_assist`
    - Existing Verify / Activate / Delete buttons
    - New **Use for AI Assist** button (or **Disable AI Assist** if it's
      already opted in) wired to `setAIAssistProvider(id)`.

### Independence from `is_active`

The two flags (`is_active` and `use_for_ai_assist`) are completely
orthogonal. Common configurations:

| `is_active` | `use_for_ai_assist` | Effect |
|---|---|---|
| Provider A | Provider A | Same provider for both (the v0.22.10 default) |
| Provider A | Provider B | Image scanner uses A, AI Assist uses B |
| Provider A | (none) | AI Assist falls back to A — v0.22.10 behavior |
| (none)      | Provider B | Image scanner has no provider; AI Assist uses B |

### Modified files

- `core/version.py` — 0.22.10 → 0.22.11
- `core/db/schema.py` — migration #25 + base CREATE TABLE update
- `core/db/catalog.py` — `get_ai_assist_provider()`, `set_ai_assist_provider()`
- `core/db/__init__.py` — re-exports
- `core/ai_assist.py` — 3-step lookup chain, `provider_source` field
- `api/routes/llm_providers.py` — request models, create/update flag, new endpoint
- `static/providers.html` — checkbox, badge, button, safe DOM rendering
- `CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md` — updates

---

## v0.22.10 — AI Assist Uses llm_providers (2026-04-07)

**Problem:** AI Assist read its API key from `os.environ["ANTHROPIC_API_KEY"]`
in `core/ai_assist.py:_get_api_key()`. Meanwhile the image scanner / vision
pipeline read it from the `llm_providers` SQLite table managed via the
Settings → Providers page (encrypted at rest, set per-deployment in the UI).
Two separate configurations for what was effectively the same Anthropic key.
This was confusing — users who set up image analysis assumed AI Assist
"just worked" too, but it silently fell back to the env var (almost always
empty in this deployment).

**Fix:** AI Assist now resolves its key/model/base URL from the same source.

### Code changes

- **`core/ai_assist.py`**
  - New async helper `_get_provider_config()` that:
    1. Calls `core.db.catalog.get_active_provider()` (the same call the
       vision pipeline uses).
    2. If the active provider is `anthropic` and has an `api_key`, returns
       `{api_key, model, api_url, provider, configured: True, compatible: True}`.
       The provider's `model` and `api_base_url` (if set) override the
       defaults — so an admin can point AI Assist at a different Anthropic
       model or a self-hosted Anthropic-compatible proxy from the UI.
    3. If the active provider is set but is NOT `anthropic` (openai, gemini,
       ollama, custom), returns `compatible: False` with a clear error
       message ("Active LLM provider is 'openai'. AI Assist currently
       requires an Anthropic provider..."). AI Assist's SSE format and
       `x-api-key` header are Anthropic-specific.
    4. As a fallback only when there is NO provider record at all, reads
       `ANTHROPIC_API_KEY` from env (legacy compatibility — should be
       considered deprecated). Returned with `provider="env_fallback"`.
  - `stream_search_synthesis()` and `stream_document_expand()` both
    call `await _get_provider_config()` and short-circuit with a clear SSE
    error event if `compatible` is false or `configured` is false.
  - The hard-coded `ANTHROPIC_API_URL` constant became
    `ANTHROPIC_API_URL_DEFAULT`. The actual URL used per request comes
    from `cfg["api_url"]` so a custom `api_base_url` in the provider
    record is honored.
  - Added `provider=cfg["provider"]` to the start/complete log events for
    observability.

- **`api/routes/ai_assist.py`**
  - Imported `_get_provider_config` from `core.ai_assist`.
  - `_api_key_configured()` is now async and delegates to
    `_get_provider_config()` — returns true iff a usable
    (configured + compatible) provider exists.
  - `GET /api/ai-assist/status` response gained four new fields:
    - `provider_source` — "anthropic" / "env_fallback" / "openai" / etc.
    - `provider_compatible` — bool
    - `provider_error` — human-readable reason when not usable
    - `model` — the actual model that will be used
  - `key_configured` is unchanged in shape (still bool) so existing
    frontends keep working.

- **`static/settings.html`**
  - The "Not configured" notice in the AI Assist section was rewritten to
    point users at the **Providers page** (`/providers.html`) instead of
    asking them to edit `.env`.
  - The `_initAIAssistSettings()` JS now reads `status.provider_error`
    and substitutes it into the notice when present, so a user with the
    wrong provider active sees "Active LLM provider is 'openai'..." with a
    direct link to fix it.

- **`static/js/ai-assist.js`**
  - The `_showNotConfiguredNotice('missing_key')` drawer message now uses
    `_serverStatus.provider_error` when present and links to
    `/providers.html`. The old `.env` / `docker-compose restart` snippet
    was removed.

- **`core/version.py`** — 0.22.9 → 0.22.10
- **`CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md`** — updates.

### Why this matters

1. **Single source of truth.** Setting up an Anthropic key in the
   Providers page is now sufficient to enable both image analysis AND AI
   Assist. No more split-brain config.
2. **Per-deployment overrides.** The provider record's `model` and
   `api_base_url` columns flow through to AI Assist, so an admin can point
   it at a non-default model or an Anthropic-compatible proxy without
   touching environment variables.
3. **Encrypted at rest.** Provider API keys are stored encrypted in
   `llm_providers.api_key` (via `core.crypto.encrypt_value`). Env-var
   storage was plaintext.
4. **Clearer error UX.** A user with OpenAI active no longer sees AI
   Assist silently disabled — they see "Active LLM provider is 'openai'.
   AI Assist currently requires an Anthropic provider. Switch the active
   provider on the Settings → Providers page."

### Backward compatibility

- The `ANTHROPIC_API_KEY` env var still works as a fallback when there is
  no `llm_providers` record at all. This keeps existing dev/test setups
  working without immediate config migration. The env-var path should be
  considered deprecated and removed in a future release.
- The `/api/ai-assist/status` response shape is a strict superset of the
  old shape — existing callers reading only `key_configured`/`org_enabled`/
  `enabled` keep working unchanged.

---

## v0.22.9 — UX + Data Integrity Pass (2026-04-07)

A grab-bag of UX and pipeline-truthfulness fixes that emerged from a single
diagnostic session.

### 1. Search default view

**Problem:** Clicking Search in the nav bar opened the search page in "browse
all" mode by default, immediately running an empty-query search and showing
date-sorted hits. Users expected an empty input waiting for them to type or
click Browse All explicitly.

**Fix:** `static/search.html` init block now only auto-runs a search when a
`?q=` URL param is present. Otherwise it hides all results UI (`results-card`,
`results-toolbar`, `search-meta`, `pagination`, `empty-state`) and focuses
the input. Browse All button is still available as an explicit one-click
action.

### 2. AI Assist "needs configuration" UX

**Problem:** When `ANTHROPIC_API_KEY` is not set in the environment:
- The search-page AI Assist toggle button was silently `display: none`'d
  by `js/ai-assist.js` after `/api/ai-assist/status` returned
  `key_configured: false`.
- The Settings page "AI-Assisted Search" section was likewise
  `style="display:none"` until JS toggled it on, and the toggle never fired
  because the same status check returned early.

The user couldn't tell the feature existed, let alone how to enable it.

**Fix:**
- `static/settings.html` — section is always rendered. A new
  `#ai-assist-not-configured` notice element shows clear setup instructions
  (`ANTHROPIC_API_KEY=...` in `.env`, then `docker-compose restart markflow`)
  when the status endpoint reports `key_configured: false`. The configured
  controls are wrapped in `#ai-assist-configured-controls` and only shown
  when the key IS configured.
- `static/js/ai-assist.js` — server status is cached in module state. The
  toggle button stays visible at all times. A new `.needs-config` CSS class
  paints it amber. Clicking the button when misconfigured opens the drawer
  with an inline help message (missing key vs. admin disabled) instead of
  toggling the local enabled flag.
- `static/css/ai-assist.css` — `.ai-assist-toggle.needs-config` styling.

### 3. Pipeline "pending" count was 2-3× inflated

**Problem:** Pipeline status badge reported 84,656 pending while only 36,296
distinct files existed. Root cause: `bulk_files` is keyed by
`(job_id, source_path)`, so each new scan job inserts its own row for every
file — including files that were already successfully converted in older
jobs. The naive `COUNT(*) FROM bulk_files WHERE status='pending'` query in
`/api/pipeline/status` and `/api/pipeline/status-overview` summed across all
those duplicate rows.

The v0.22.7 self-correction job's "cross-job dedup" step kept only the most
recent job's row per source_path, but new scan runs immediately recreated the
duplication and the cleanup only ran every 6 hours.

**Fix (two layers):**

a) **Query layer** (`api/routes/pipeline.py`) — both endpoints now use a
   `NOT EXISTS` subquery against `bulk_files`:

   ```sql
   SELECT COUNT(*) FROM source_files sf
   WHERE sf.lifecycle_status = 'active'
     AND NOT EXISTS (
         SELECT 1 FROM bulk_files bf
         WHERE bf.source_path = sf.source_path
           AND bf.status = 'converted'
     )
   ```

   This counts truly-distinct unconverted source files. The `failed` and
   `unrecognized` counts in `status-overview` were rewritten the same way
   (`COUNT(DISTINCT source_path)` + same `NOT EXISTS` guard) so a file
   that failed in one job and converted in another no longer shows up in
   the failed bucket.

b) **Cleanup layer** (`core/db/bulk.py`) — `cleanup_stale_bulk_files()` now
   has a 4th deletion step, **pending-superseded prune**:

   ```sql
   DELETE FROM bulk_files
   WHERE status = 'pending'
     AND job_id NOT IN ({active_job_statuses})
     AND EXISTS (
         SELECT 1 FROM bulk_files bf2
         WHERE bf2.source_path = bulk_files.source_path
           AND bf2.status = 'converted'
     )
   ```

   This catches the common case where a newer scan job inserts a fresh
   `pending` row for a file that was already converted in an older job.
   Active jobs (scanning/running/paused/pending) are still excluded so
   in-flight work is never disturbed. Counts are returned via a new
   `pending_superseded_deleted` key in the cleanup result dict.

### 4. Adobe-files index regression — silently empty since "unified dispatch"

**Problem:** The Meilisearch `adobe-files` index reported 0 documents and the
`adobe_index` SQLite table was empty, despite ~1,400 .ai/.psd/.indd files
being scanned and 100+ .ai files showing `status='converted'` in `bulk_files`.

**Root cause:** `core/bulk_worker.py:_worker()` dispatch routes ALL files
through `_process_convertible()` (per the "unified scanning" architecture
note in CLAUDE.md). Adobe files therefore go through the regular conversion
pipeline → `AdobeHandler.ingest()` → markdown summary → `documents`
Meilisearch index. That's correct as far as it goes.

But the older `_process_adobe()` method, which calls
`AdobeIndexer.index_file()` to extract XMP/EXIF metadata + text layers and
upserts them into the `adobe_index` table (the data backing the
`adobe-files` Meilisearch index), was **never called** from the dispatch
loop. It became dead code at some point during the unified-dispatch
refactor. Result: rich Level-2 metadata for Adobe files was being silently
dropped.

**Fix:** `core/bulk_worker.py` —
- Added `_index_adobe_l2(file_dict)`: a focused method that runs
  `AdobeIndexer().index_file(source_path)` to populate `adobe_index` (via
  `upsert_adobe_index()`), then calls
  `search_indexer.index_adobe_file(result, job_id)` to push the result into
  the `adobe-files` Meilisearch index. Does NOT touch `bulk_files` status —
  the markdown conversion above already handled that. Files with extensions
  AdobeIndexer doesn't support (.ait/.indt templates, .psb) return an
  "Unsupported Adobe extension" result and are debug-logged + skipped.
- `_worker()` now invokes `_index_adobe_l2(file_dict)` immediately after
  `_process_convertible(file_dict, worker_id)` returns successfully, gated
  on `ext in ADOBE_EXTENSIONS and self.include_adobe`. Wrapped in
  `try/except` so an L2 failure never aborts the conversion.

The dead `_process_adobe()` method was left in place for now (unused but
harmless) — can be removed in a follow-up cleanup pass.

### 5. Other findings (not fixed this round)

Diagnostic findings recorded for follow-up:

- **Vector search IS working.** Qdrant has 14,377 points in collection
  `markflow_chunks` and `hybrid_search_merged` events show successful
  RRF fusion (`keyword=10, vector=10, merged=10`). `indexed_vectors_count: 0`
  in the collection info is misleading — it just means HNSW per-segment
  threshold (10k) hasn't been crossed across the 5 segments, so Qdrant uses
  brute-force search. Still returns results correctly.
- **`analysis_queue` is mostly stalled** — 2,078 pending + 1,010 failed +
  190 batched + 90 completed. Likely tied to LLM provider config and/or
  the missing ANTHROPIC_API_KEY. Worth investigating in a dedicated session.

### Modified files

- `core/version.py` — 0.22.8 → 0.22.9
- `core/db/bulk.py` — 4th cleanup step + extended docstring/return dict
- `core/bulk_worker.py` — `_index_adobe_l2()` + dispatch hook
- `api/routes/pipeline.py` — both pending queries rewritten
- `static/search.html` — init block, no auto browse-all
- `static/settings.html` — AI Assist section restructured + JS init
- `static/js/ai-assist.js` — server status caching + needs-config UX
- `static/css/ai-assist.css` — `.needs-config` styling
- `CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md` — updates

---

## v0.22.8 — GPU Detector Live Re-Resolution Fix (2026-04-07)

**Fix:** `get_gpu_info_live()` in `core/gpu_detector.py` re-reads the
`host_worker_*` fields on every health check (correctly), but never re-resolved
the derived `execution_path`, `effective_gpu_name`, or `effective_backend`
values. Those are computed once during `detect_gpu()` at container startup
and cached on the singleton `_gpu_info`. If `worker_capabilities.json` did
not exist at startup but appeared later (common during dev when running the
refresh script after the container was already up), the health page kept
reporting "CPU (no GPU detected)" even though the live re-read had populated
`host_worker_available=true` with the correct GPU details.

**Symptom:** The Status page System Health Check showed `gpu: FAIL / CPU`
while the underlying API response had a fully-populated `host_worker` block
with the correct NVIDIA / AMD / Apple GPU identified.

**Fix:** Added the same execution-path resolution block from `detect_gpu()`
to the end of `get_gpu_info_live()`. Now the live re-read also re-evaluates:

```python
if container_gpu_available and container_hashcat_backend in ("CUDA", "OpenCL"):
    -> "container"
elif host_worker_available and host_worker_gpu_backend in _gpu_backends:
    -> "host"   # this branch was being missed
elif container_hashcat_available:
    -> "container_cpu"
else:
    -> "none"
```

**Modified files:**
- `core/gpu_detector.py` — Added execution-path resolution to `get_gpu_info_live()`
- `core/version.py` — 0.22.7 → 0.22.8
- `CLAUDE.md`, `docs/version-history.md` — Updates

---

## v0.22.7 — bulk_files Self-Correction (2026-04-07)

**Feature:** Periodic cleanup sweep for the `bulk_files` table that prunes
phantom rows, purged rows, and cross-job duplicates. Solves the long-standing
issue where the pipeline status badge reported nonsensical pending counts
(observed: 325,186 pending for 34,814 unique source files — a ~9.3x
duplication factor across 9-10 historical bulk jobs).

**Background:**
The `bulk_files` table is keyed by `(job_id, source_path)`, so each new scan
job inserts a fresh row for every file even if previous jobs already converted
it. Over time the table balloons to many multiples of the unique source file
count. The pipeline status badge sums across all `bulk_files` rows without
deduplicating by `source_path`, producing inflated and misleading pending
counts. Documented as a known issue in `docs/gotchas.md`.

**The cleanup performs three deletions in a single transaction:**

1. **Phantom prune**: `DELETE FROM bulk_files WHERE source_path NOT IN
   (SELECT source_path FROM source_files)` — removes rows for files that no
   longer exist in the source registry (file deleted from disk).
2. **Purged prune**: `DELETE FROM bulk_files WHERE source_path IN (SELECT
   source_path FROM source_files WHERE lifecycle_status='purged')` — removes
   rows for files that were permanently trashed.
3. **Cross-job dedup**: For each `source_path`, keep only the row from the
   most recent job (by `bulk_jobs.started_at`) and delete older duplicates.

**Safety:** All three deletions exclude rows belonging to active jobs
(status in `scanning`, `running`, `paused`, `pending`). The scheduler
wrapper additionally skips the entire job if `get_all_active_jobs()` is
non-empty, providing two layers of protection against touching in-flight rows.

**Schedule:** Every 6 hours via `_bulk_files_self_correction()` in
`core/scheduler.py`. Job ID `bulk_files_self_correction`.

**Manual trigger:** `POST /api/admin/cleanup-bulk-files` (admin role required).
Returns 409 Conflict if a bulk job is currently active. Response payload:
```json
{
  "phantom_deleted": 12,
  "purged_deleted": 0,
  "dedup_deleted": 290847,
  "total_deleted": 290859
}
```

**Modified files:**
- `core/db/bulk.py` — New `cleanup_stale_bulk_files()` function with
  three-pass deletion logic and active-job exclusion
- `core/db/__init__.py` — Export `cleanup_stale_bulk_files`
- `core/scheduler.py` — New `_bulk_files_self_correction()` wrapper that
  checks `get_all_active_jobs()` before delegating, plus job registration
  in `start_scheduler()` (now reports 15 jobs)
- `api/routes/admin.py` — New `POST /api/admin/cleanup-bulk-files` endpoint
- `core/version.py` — 0.22.6 → 0.22.7
- `CLAUDE.md`, `docs/version-history.md`, `docs/gotchas.md` — Updates

---

## v0.22.6 — Critical hashlib Bug + Vision Payload Splitter (2026-04-06)

**Critical Fixes:**

- **`hashlib` UnboundLocalError in bulk_worker**: A local `import hashlib` inside
  the vector-indexing block (line 802) shadowed the module-level import. Python's
  scoping rules then treated `hashlib` as a local variable for the **entire function**,
  causing the earlier `hashlib.sha256(...)` call on line 726 to raise
  `UnboundLocalError: cannot access local variable 'hashlib' where it is not
  associated with a value`. This caused **every file in every bulk job to fail**,
  triggering the 100% error-rate auto-abort in a runaway cascade.
  - Log impact: 124,216 `bulk_worker_error_rate_abort` events, 67
    `bulk_worker_unhandled` errors, 506 files marked failed, 19+ jobs cancelled.
  - **Fix:** Removed the redundant inner import (`hashlib` is already imported
    at module level).

- **Vision adapter `413 Payload Too Large` from Anthropic API**:
  `_batch_anthropic()` sent up to 10 base64-encoded images per request without
  checking total size. Large keyframes pushed requests over Anthropic's 32 MB
  hard limit, killing entire vision batches.
  - **Fix:** Rewrote `_batch_anthropic()` with a size-aware greedy splitter.
    Pre-encodes all images, groups into sub-batches that stay under 24 MB (leaving
    8 MB headroom for JSON envelope, headers, and prompt text), and makes
    multiple sequential API calls per logical batch. Results are reassembled in
    original input order. New constant `_ANTHROPIC_MAX_PAYLOAD_BYTES = 24 MB`.

**Modified files:**
- `core/bulk_worker.py` — Removed shadowing inner `import hashlib`
- `core/vision_adapter.py` — Size-aware batch splitter for Anthropic vision

---

## v0.22.5 — Bulk Scanner files/sec Display Fix (2026-04-07)

**Fix:** The Active Job panel on the Bulk Jobs page displayed nonsensical scan
rates like `783184.5 files/sec` and a meaningless `~0s remaining` ETA during
parallel scans. Root cause was in `core/bulk_scanner.py` — the parallel drain
loop collected up to 200 files from the worker queue per cycle, then called
`tracker.record_completion()` once per file in a tight loop. All ~200 entries
landed in `RollingWindowETA`'s 100-slot deque with near-identical
`time.monotonic()` timestamps (sub-millisecond apart), so the fps math
(`(newest_count - oldest_count) / elapsed`) divided ~100 files by a ~127µs
span, producing ~787k files/sec.

Replaced the per-file loop with a single
`await tracker.record_completion(count=len(batch))` so each drain cycle yields
exactly one window entry. Window entries are now spaced by the real wall-clock
interval between drains (tens of ms to seconds), giving a realistic files/sec
and a usable scan ETA.

The serial scan path and single-file path were unaffected — they already call
`record_completion()` once per discovered file with real wall-clock pacing.
`RollingWindowETA.record_completion()` already accepted a `count` parameter;
this fix just uses it instead of iterating.

**Modified files:**
- `core/bulk_scanner.py` — parallel drain loop records batch as single window entry

---

## v0.22.4 — Help Link Fix + Auto-Conversion Article (2026-04-06)

**Fixes:**
- **Help icon links broken**: The `?` icons added by `static/js/help-link.js` linked to
  `/help#slug`, but the static catch-all in `main.py` only matches paths ending in
  `.html`. Updated to `/help.html#slug`.
- **Missing auto-conversion help article**: Added `docs/help/auto-conversion.md`
  covering modes (immediate/business-hours/scheduled/manual), workers, batch sizing,
  the pipeline master switch, decision logging, Run Now, priority interaction with
  manual jobs, and troubleshooting. Registered in `_index.json` under "Core Features".

**Modified files:**
- `static/js/help-link.js` — `/help#` -> `/help.html#`
- `docs/help/auto-conversion.md` — New help article
- `docs/help/_index.json` — Added auto-conversion entry

---

## v0.22.3 — Settings Toggle State Persistence Fix (2026-04-06)

**Fix:** Toggle switches on the Settings page did not display their saved state on
page load. `updateToggleLabel()` was hardcoded to update only the "unattended" toggle
label ID, so all other toggles always showed "OFF" regardless of their actual saved
value. Users attempting to re-save saw "nothing to save" because the underlying
checkbox values were correct -- only the visible labels were wrong.

- Rewrote `updateToggleLabel()` to generically find the sibling `.toggle-label`
  within the same `.toggle` parent via `el.closest('.toggle')`.
- Added a single `document.querySelectorAll('.toggle input')` change handler for
  all toggles, replacing scattered per-toggle event wiring.

**Modified files:**
- `static/settings.html` — Generic `updateToggleLabel()`, bulk change handler

---

## v0.22.2 — Toggle Switch UX Redesign, SQLite Timestamp Fix (2026-04-06)

**Fixes:**
- **Toggle switches redesigned**: Settings page toggles now have a visible track outline
  showing the knob travel path, dim knob/track when off, accent-colored glow when on,
  and label text to the right that lights up with the accent color on check. Replaces the
  cramped "OFF" text that overlapped the switch bubble.
- **SQLite `datetime('now')` timestamps**: `cleanup_orphaned_jobs()` now uses `now_iso()`
  instead of SQLite's `datetime('now')` for consistent `+00:00` offset formatting.
  Frontend `parseUTC()` also handles legacy space-separated timestamps from SQLite.

**Modified files:**
- `static/markflow.css` — Toggle switch redesign (`.toggle-track`, `.toggle-label`)
- `static/app.js` — `parseUTC()` handles `YYYY-MM-DD HH:MM:SS` format
- `core/db/schema.py` — `cleanup_orphaned_jobs()` uses `now_iso()` instead of `datetime('now')`

---

## v0.22.1 — Timestamp Localization, GPU Detection Fix, Script Portability (2026-04-06)

**Fixes:**
- **UTC timestamps displayed as local time**: All user-facing pages now correctly convert
  UTC timestamps to the browser's local timezone. Added `parseUTC()` helper in `app.js`
  that appends `Z` to bare ISO timestamps (no timezone suffix) before parsing. Updated
  `formatLocalTime()` and fixed 6 pages that bypassed it with raw `new Date()` calls:
  `bulk.html`, `db-health.html`, `trash.html`, `pipeline-files.html`, `version-panel.js`.
- **GPU health check showing wrong hardware**: `worker_capabilities.json` was committed
  to git with stale Apple M4 Pro data from a different machine. Now gitignored — each
  machine generates it at deploy time via the refresh/reset scripts. Added `.json.example`
  for reference.
- **PowerShell script parse errors**: All `.ps1` and `.sh` scripts under `Scripts/` had
  non-ASCII characters (em dashes, box-drawing, emojis) that broke Windows PowerShell 5.1
  (reads BOM-less UTF-8 as Windows-1252, where byte 0x94 from em dash becomes a right
  double quote, breaking string parsing). Replaced with ASCII equivalents across all 18
  script files for cross-platform safety (Windows PS5.1, macOS zsh, Linux bash over SSH).

**Modified files:**
- `static/app.js` — `parseUTC()` helper, `formatLocalTime()` rewrite
- `static/bulk.html` — Use `parseUTC()` for last-scan time
- `static/db-health.html` — Use `formatLocalTime()` for compaction/integrity dates
- `static/trash.html` — Use `formatLocalTime()` for trash/purge dates
- `static/pipeline-files.html` — Use `parseUTC()` in local `formatLocalTime()`
- `static/js/version-panel.js` — Use `parseUTC()` for recorded_at
- `.gitignore` — Add `hashcat-queue/worker_capabilities.json`
- `hashcat-queue/worker_capabilities.json.example` — New reference template
- `Scripts/**/*.ps1`, `Scripts/**/*.sh` — ASCII-only characters (18 files)

---

## v0.22.0 — Hybrid Vector Search (2026-04-05)

**Feature:** Semantic vector search augmenting existing Meilisearch keyword search.
Documents are chunked with contextual headers, embedded locally via sentence-transformers,
and stored in Qdrant. At query time, both systems run in parallel and results merge
via Reciprocal Rank Fusion (RRF). Graceful fallback to keyword-only when Qdrant is
unavailable. Query preprocessor detects temporal intent and biases toward recent docs.

**New files:**
- `core/vector/chunker.py` — Markdown to contextual chunks (heading-based + fixed-size fallback)
- `core/vector/embedder.py` — Pluggable embedding (local sentence-transformers default)
- `core/vector/index_manager.py` — Qdrant collection lifecycle, document indexing, search
- `core/vector/hybrid_search.py` — RRF merge of keyword + vector results
- `core/vector/query_preprocessor.py` — Temporal intent detection, query normalization

**Modified files:**
- `docker-compose.yml` — Qdrant container + volume
- `requirements.txt` — sentence-transformers, qdrant-client
- `core/bulk_worker.py` — Vector indexing parallel to Meilisearch (fire-and-forget)
- `api/routes/search.py` — Hybrid search in `/api/search/all`
- `main.py` — Vector search startup health check

**Infrastructure:**
- Qdrant container (internal port 6333, not exposed to host)
- Single collection `markflow_chunks` with payload filtering
- `all-MiniLM-L6-v2` embedding model (384 dimensions, ~80MB, CPU inference)
- Embedding model version tracked in collection metadata for future upgrade path

---

## v0.21.0 — AI-Assisted Search (2026-04-05)

**Feature:** Opt-in AI synthesis layer on top of existing Meilisearch results. A
persistent toggle in the search bar activates a right-side drawer that streams a
Claude-synthesized answer grounded in the top matching documents. A "Read full doc"
button per cited source triggers a deeper single-document analysis.

**New files:**
- `core/ai_assist.py` — Claude API streaming (search synthesis + document expand)
- `api/routes/ai_assist.py` — FastAPI endpoints (`/api/ai-assist/search`, `/expand`, `/status`)
- `static/js/ai-assist.js` — Toggle, drawer, SSE streaming, source expansion
- `static/css/ai-assist.css` — Drawer styles, loading/streaming/error states

**Modified files:**
- `main.py` — Register ai_assist router
- `.env.example` — Add `ANTHROPIC_API_KEY`, `AI_ASSIST_MODEL`, `AI_ASSIST_MAX_TOKENS`, `AI_ASSIST_EXPAND_MAX_TOKENS`
- `static/search.html` — Add toggle button, drawer scaffold, CSS/JS links, init + onResults calls
- `docker-compose.yml` — Pass AI env vars to markflow service

**Behaviour:**
- Feature is completely opt-in — hidden when `ANTHROPIC_API_KEY` is not set
- Toggle state persists across page reloads via localStorage
- Streams SSE events: `chunk` (text delta), `sources` (citation metadata), `done`, `error`
- Expand endpoint reads converted markdown from `source_files.output_path`
- Uses `httpx` for streaming (already in requirements.txt)

**Amendment 1 — Org toggle + usage tracking:**
- Org-wide on/off toggle in Settings (admin only), stored in `user_preferences` table
- `ai_assist_usage` table (migration 24) logs user, query, mode, estimated tokens per call
- Admin endpoints: `PUT /api/ai-assist/admin/toggle`, `GET /api/ai-assist/admin/usage`
- Settings page shows per-user totals and recent calls with estimated token spend
- `/api/ai-assist/status` now returns `{key_configured, org_enabled, enabled}`
- Search/expand endpoints return 503 when org toggle is off
- New module: `core/db/ai_usage.py`

---

## v0.20.3 — Handwriting Recognition via LLM Vision Fallback (2026-04-05)

**Feature:** Automatic handwriting detection and LLM-powered transcription. When
Tesseract OCR produces results that match handwriting patterns (very low confidence,
high flagged word ratio, unrecognisable words), the page image is sent to the active
LLM vision provider for transcription.

**How it works:**
1. Tesseract runs as normal on every scanned page
2. `detect_handwriting()` analyses the OCR output for three signals:
   - Average confidence below threshold (default 40%)
   - More than 60% of words below the confidence threshold
   - Low dictionary hit rate (most "words" aren't recognisable English)
3. If all three signals fire, the page image is sent to the LLM vision adapter
4. In unattended mode: LLM text automatically replaces Tesseract output
5. In review mode: both outputs shown, user picks or edits

**Configuration:**
- `handwriting_confidence_threshold` preference (default: 40)
- Requires an active LLM vision provider (Claude, GPT-4V, Gemini, or Ollama)
- Falls back gracefully to manual review if no provider is configured

**Files changed:**
- `core/ocr.py` — added `detect_handwriting()` and `_llm_handwriting_fallback()`
- `core/ocr_models.py` — added `handwriting_detected` field to `OCRFlag`
- `core/db/schema.py` — migration 23 (handwriting_detected column on ocr_flags)
- `core/db/conversions.py` — persist handwriting_detected in insert_ocr_flag
- `core/version.py` — bump to 0.20.3
- `docs/help/ocr-pipeline.md` — updated handwriting FAQ
- `README.md` — updated OCR description, version
- `CLAUDE.md` — updated current status

---

## v0.20.2 — Binary File Handler Expansion (2026-04-05)

**Feature:** Expanded the binary metadata handler to cover 30+ common binary file
types. Executables, DLLs, shared libraries, disk images, virtual disks, databases,
firmware, bytecode, and object files are now recognized and cataloged with metadata
(size, MIME type, magic bytes) instead of appearing as "unrecognized."

Also fixes `.heic` and `.heif` missing from `SUPPORTED_EXTENSIONS` (they were
handled by `image_handler.py` since v0.19.6.8 but never added to the scanner set,
so bulk scans marked them as unrecognized).

**New extensions in binary handler:**
- Executables & libraries: `.exe`, `.dll`, `.so`, `.msi`, `.sys`, `.drv`, `.ocx`, `.cpl`, `.scr`, `.com`
- macOS binaries: `.dylib`, `.app`, `.dmg`
- Disk images: `.img`, `.vhd`, `.vhdx`, `.vmdk`, `.vdi`, `.qcow2`
- Databases: `.sqlite`, `.db`, `.mdb`, `.accdb`
- Firmware & ROM: `.rom`, `.fw`, `.efi`
- Bytecode: `.class`, `.pyc`, `.pyo`
- Object files: `.o`, `.obj`, `.lib`, `.a`
- Misc: `.dat`, `.dmp`

**DB migration 22:** Re-queues all formerly unrecognized files of the above types
(and `.heic`/`.heif`) by setting their status from `unrecognized` to `pending`.
They will be processed by the binary handler (or image handler) on the next bulk run.

**Files changed:**
- `formats/binary_handler.py` — added 30 extensions + type descriptions
- `core/bulk_scanner.py` — added 32 extensions to SUPPORTED_EXTENSIONS (30 binary + .heic/.heif)
- `core/db/schema.py` — migration 22
- `core/version.py` — bump to 0.20.2
- `README.md` — updated format table, version, file count
- `docs/help/unrecognized-files.md` — updated extension count, notes on binary handler
- `docs/help/document-conversion.md` — expanded binary row, added .heic/.heif to images
- `CLAUDE.md` — updated current status

---

## v0.20.1 — 20 New File Format Handlers (2026-04-05)

**Feature:** Added support for 20 new file extensions across 6 new handlers and
6 extended existing handlers. Total supported formats: ~80 extensions.

**Extended existing handlers:**
- `txt_handler.py` — added `.lst` (list files), `.cc` (C++ source), `.css` (stylesheets)
- `csv_handler.py` — added `.tab` (tab-delimited data, same treatment as .tsv)
- `pptx_handler.py` — added `.pptm` (PowerPoint macro-enabled)
- `docx_handler.py` — added `.wbk` (Word backup), `.pub` (Publisher), `.p65` (PageMaker) via LibreOffice
- `adobe_handler.py` — added `.psb` (Photoshop Big, same as PSD)
- `image_handler.py` — added `.cr2` (Canon RAW)

**New handlers:**
- `font_handler.py` — `.otf`, `.ttf` — extracts font metadata via fonttools
- `shortcut_handler.py` — `.lnk` (Windows shortcut), `.url` (URL shortcut)
- `vcf_handler.py` — `.vcf` — parses vCard contacts
- `svg_handler.py` — `.svg` — parses SVG XML, extracts dimensions/elements/text
- `sniff_handler.py` — `.tmp` — MIME-detects content, delegates to matching handler
- `binary_handler.py` — `.bin`, `.cl4` — metadata-only (size, MIME, magic bytes)

**Files changed:**
- 6 modified handlers, 6 new handler files
- `formats/__init__.py` — register new handlers
- `core/bulk_scanner.py` — add all 20 extensions to SUPPORTED_EXTENSIONS
- `core/version.py` — bump to 0.20.1

---

## v0.20.0 — NFS Mount Support + Mount Settings UI (2026-04-05)

**Feature:** Network mount configuration is no longer hardcoded to SMB/CIFS. MarkFlow
now supports SMB/CIFS, NFSv3, and NFSv4 (with optional Kerberos) as mount protocols.

**New components:**
- `core/mount_manager.py` — Protocol-agnostic mount abstraction. Generates mount commands
  and fstab entries, handles live mount/unmount, tests connections, persists config to
  `/etc/markflow/mounts.json`. Supports `dry_run=True` for config-generation mode.
- `api/routes/mounts.py` — REST endpoints: GET status, POST test, POST apply.
- Settings UI "Storage Connections" section — radio buttons for protocol, conditional
  SMB credentials / NFSv4 Kerberos fields, test and apply buttons with live status.
- Setup script protocol selection — choose SMB/NFSv3/NFSv4 during initial VM provisioning.

**Files changed:**
- `core/mount_manager.py` — NEW
- `api/routes/mounts.py` — NEW
- `tests/test_mount_manager.py` — NEW
- `static/settings.html` — Storage Connections section
- `Scripts/proxmox/setup-markflow.sh` — protocol selection menu
- `Dockerfile.base` — added `nfs-common` package
- `main.py` — register mounts router
- `core/version.py` — bump to 0.20.0

---

## v0.19.6.11 — Fix Three Scan Failures (2026-04-05)

**Problem:** Bulk scan reported 12 failed files across three distinct root causes.

**Bug 1 — Read-only FS crash on media files (2 files):**
`audio_handler.py` and `media_handler.py` computed the MediaOrchestrator output dir
as `file_path.parent / "_markflow"`, which writes into the source mount. Since
`/mnt/source` is mounted read-only, this raised `[Errno 30] Read-only file system`.

**Fix:** Both handlers now use `tempfile.mkdtemp()` for the orchestrator's scratch
output. The bulk worker already places the final `.md` and sidecar into the correct
output tree independently.

**Bug 2 — INI parser crash on XGI driver config files (8 files):**
Python's `configparser` with `allow_no_value=True` raises `AttributeError`
(`'NoneType' object has no attribute 'append'`) on INI files with continuation
lines after a no-value key. The exception handler only caught `configparser.Error`
and `KeyError`, not `AttributeError`, so the fallback line parser never ran.

**Fix:** Added `AttributeError` to the `_try_configparser` exception handler so
these files fall through to the line-by-line parser.

**Bug 3 — Markdown handler UTF-8 decode error (1 file):**
`markdown_handler.py` called `read_text(encoding="utf-8")` with no fallback.
A LICENSE-MIT.md file encoded in Latin-1 (byte `0xa9` = `©`) crashed with
`UnicodeDecodeError`.

**Fix:** Added `try/except UnicodeDecodeError` with Latin-1 fallback.

**Files changed:**
- `formats/audio_handler.py` — use tempdir for orchestrator output
- `formats/media_handler.py` — use tempdir for orchestrator output
- `formats/ini_handler.py` — catch `AttributeError` in `_try_configparser`
- `formats/markdown_handler.py` — Latin-1 fallback for non-UTF-8 `.md` files
- `core/version.py` — bump to 0.19.6.11

---

## v0.19.6.10 — Reduce PDF Image Extraction Log Noise (2026-04-05)

**Problem:** WSJ newspaper PDFs embed images as raw FlateDecode pixel streams (no image
headers). The image handler tried `PIL.Image.open()` on these headerless byte buffers,
producing hundreds of `image_handler.convert_failed` warnings per PDF file — flooding logs
during bulk conversion.

**Root cause:** `_extract_page_images()` in `pdf_handler.py` hardcoded `format="png"` for
all PDF image streams, regardless of the actual encoding. FlateDecode streams contain raw
pixel data that requires Width/Height/BPC metadata from the PDF dictionary to interpret.

**Fix (4 changes):**

1. **Format detection via magic bytes** — PDF handler now checks `\xff\xd8` (JPEG) and
   `\x89PNG` headers before calling `extract_image()`. Passes `"jpeg"`, `"png"`, or `"raw"`
   accordingly.

2. **Stream metadata passthrough** — For raw streams, Width and Height from
   `stream.attrs` are passed as `raw_width`/`raw_height` keyword args.

3. **Raw pixel reconstruction** — New `_reconstruct_raw_pixels()` function infers PIL
   colour mode (L/RGB/CMYK) from data length vs. dimensions, then uses
   `Image.frombytes()` to build a valid image and export as PNG.

4. **Log level downgrade** — `UnidentifiedImageError` now logs at debug level
   (`image_handler.raw_unidentified`) instead of warning. Unexpected errors still warn.

**Files changed:**
- `core/image_handler.py` — added `raw_width`/`raw_height` params, `_reconstruct_raw_pixels()`, split `UnidentifiedImageError` from general exceptions
- `formats/pdf_handler.py` — magic-byte format detection, stream metadata extraction
- `core/version.py` — bump to 0.19.6.10

---

## v0.19.6.9 — Fix Search Page Crash & Optimize Search API (2026-04-04)

**Two fixes that made the search page non-functional:**

1. **Search page JS crash (DOM ordering)** — The `preview-popup` and `flag-modal-backdrop`
   divs were placed after the `</script>` tag in `search.html`. An IIFE that wired up
   preview mouse events ran during parse and called `getElementById('preview-popup')`, which
   returned `null` because the element hadn't been parsed yet. The resulting `TypeError`
   killed the entire script block — `doSearch()`, event listeners, and all search
   functionality never initialized. Fix: moved both div blocks before the script tag.

2. **Search API response bloat (2.7 MB → 13 KB)** — `_map_hit()` in `api/routes/search.py`
   copied every field from Meilisearch results including `content` (full document text) and
   `headings` (1.38 MB for a single archive file). Added `attributesToRetrieve` whitelist
   to the Meilisearch query and rewrote `_map_hit()` to only include fields the frontend
   actually renders. Response size dropped from 2.7 MB to 13 KB for 10 results (205× reduction).

**Files changed:**
- `static/search.html` — moved preview-popup and flag-modal before script block
- `api/routes/search.py` — `attributesToRetrieve` whitelist, `_map_hit()` field whitelist
- `core/version.py` — bump to 0.19.6.9

---

## v0.19.6.8 — HEIC/HEIF Support & Search Auto-Browse (2026-04-04)

**Two improvements: new image format support and search page UX.**

1. **HEIC/HEIF image conversion** — Added `pillow-heif` dependency and registered the HEIF
   opener in `formats/image_handler.py`. HEIC/HEIF files (common iPhone photo format) are
   now handled like any other image, routed through `core.image_handler.extract_image` for
   consistent PNG normalization into the document model's asset pipeline. Extension list
   updated in handler and README.

2. **Search page auto-browse on load** — `static/search.html` now automatically loads all
   documents sorted by date when the page opens with no query, instead of showing a blank
   page. Users see their most recent documents immediately.

**Files changed:**
- `formats/image_handler.py` — HEIC/HEIF extensions, pillow-heif import, extract_image routing
- `requirements.txt` — added `pillow-heif`
- `static/search.html` — auto-browse on empty query
- `core/version.py` — bump to 0.19.6.8
- `README.md` — version bump, HEIC/HEIF in supported formats table
- `CLAUDE.md` — current status updated

---

## v0.19.6.7 — Scan Coordinator Crash Resilience (2026-04-04)

**Three fixes for scanner runs getting stuck after container restarts:**

1. **Coordinator state reset on startup** — Added `reset_coordinator()` called during
   app lifespan after `cleanup_orphaned_jobs()`. Previously, in-memory coordinator flags
   (`run_now_running`, `lifecycle_running`) persisted as ghost state if the container
   restarted mid-scan, blocking future scans indefinitely.

2. **Periodic counter flush during scan** — Scan run counters (`files_scanned`, `files_new`,
   etc.) are now flushed to the DB every 500 files during both serial and parallel walks.
   Previously, counters were only written at scan completion, so crash recovery left all
   counters at zero.

3. **Stale scan watchdog** — New `check_stale_scans()` runs every 5 minutes via the
   scheduler. If a run-now or lifecycle scan has been "running" for longer than 4 hours
   without completing (e.g. async task died silently), the watchdog resets the coordinator
   flag. The coordinator status API now includes elapsed time and timeout info.

**Files changed:**
- `core/scan_coordinator.py` — `reset_coordinator()`, `check_stale_scans()`, timestamp tracking, enriched status
- `core/lifecycle_scanner.py` — `_flush_counters_to_db()`, flush calls in serial and parallel walkers
- `core/scheduler.py` — `check_stale_scans` job (5-minute interval)
- `main.py` — call `reset_coordinator()` on startup
- `core/version.py` — bump to 0.19.6.7

---

## v0.19.6.6 — Fix OCR Confidence Threshold Slider Display (2026-04-03)

**Bug fix — OCR confidence threshold showed incorrect percentage (e.g. 400%):**

- `populateForm()` in `settings.html` had a generic `el.type === 'range'` branch that
  wrote every range slider's value to the shared `range-output` element. The conservatism
  factor slider (0.3–1.0) overwrote the OCR confidence display on page load.
- Fixed by routing each range slider to its own output element based on the preference key.

**Files changed:**
- `static/settings.html` — key-specific output updates in `populateForm()`

---

## v0.19.6.5 — DB Contention Logging for Lock Diagnosis (2026-04-03)

**TEMPORARY instrumentation to diagnose recurring "database is locked" errors:**

- New `core/db/contention_logger.py` module with three dedicated log files:
  - `db-contention.log` — every write acquire/release with caller identity, hold duration,
    and active connection count
  - `db-queries.log` — full SQL query log (statement, params, duration, caller, row count)
  - `db-active.log` — active-connection snapshots dumped whenever "database is locked" fires,
    showing exactly who is holding the lock
- All three logs capped at 1 GB with 3 sequential backup files
- `ActiveConnectionTracker` maintains a thread-safe registry of open DB connections;
  on lock error, dumps every active holder with caller, intent, thread, and hold time
- Instrumented `get_db()`, `db_fetch_one()`, `db_fetch_all()`, `db_execute()`, and
  `db_write_with_retry()` in `core/db/connection.py`
- **Deactivate once lock contention is resolved** — flagged in CLAUDE.md and gotchas.md

**Files changed:**
- `core/db/contention_logger.py` — new module (loggers, tracker, helpers)
- `core/db/connection.py` — instrumented all DB access paths

---

## v0.19.6.4 — Fix Scan Crash: Wrong Table Name in Incremental Counter (2026-04-03)

**Bug fix — scans crashed immediately with `no such table: preferences`:**

- Three raw SQL queries in `core/db/bulk.py` (`get_incremental_scan_count()`,
  `increment_scan_count()`, `reset_scan_count()`) referenced `preferences` instead of
  the correct `user_preferences` table.
- Any scan trigger (run-now, lifecycle) hit `OperationalError: no such table: preferences`
  and failed before scanning a single file.
- Root cause: the incremental scan counter functions added in v0.19.5 used hardcoded
  table names instead of the DB helper layer.

**Files changed:**
- `core/db/bulk.py` — `preferences` → `user_preferences` in 3 queries

---

## v0.19.6.3 — Pipeline Files Chip Colors UI Revision (2026-04-03)

**Minor UI revision for the pipeline files page filter chips:**

- Filter chips on `pipeline-files.html` now always display their category colors (matching the 
  status page pipeline pills), not just when the filter is active.
- Color scheme: purple for pending analysis, yellow for batched, red for failed/analysis failed, 
  green for indexed.
- Active state adds a border highlight and bold text weight for visual emphasis.

**Files changed:**
- `static/pipeline-files.html` — chip color styling and active state CSS

---

## v0.19.6.2 — LLM Banner CSS Fix (2026-04-03)

**Patch fix for the LLM provider status banner CSS on `pipeline-files.html`:**

- `.llm-banner` had `display: flex` which overrode the HTML `hidden` attribute, causing an
  empty red banner to render even when the provider was verified and active.
- Fixed by removing `hidden` from the HTML and defaulting `.llm-banner` to `display: none`.
  A new `.visible` class sets `display: flex`, toggled via `classList.add/remove('visible')` in JS.

**Files changed:**
- `static/pipeline-files.html` — CSS default `display: none` + `.visible` class toggle

---

## v0.19.6.1 — LLM Banner Empty Display Fix (2026-04-03)

**Patch fix for the LLM provider status banner on `pipeline-files.html`:**

- Banner was rendering as an empty red box even when the active provider was verified and
  active. Root cause: SQLite returns `is_active` / `is_verified` as integers (`0`/`1`), not
  Python booleans. Truthy checks passed for both truthy (`1`) and falsy (`0`) values in some
  code paths. Fixed with explicit `== 1` equality checks.
- Banner now hides (sets `display: none`) on fetch error instead of remaining visible in its
  default state, preventing a spurious red box when the provider API is unreachable.

**Files changed:**
- `static/pipeline-files.html` — integer equality checks for `is_active`/`is_verified`; hide banner on fetch error

---

## v0.19.6 — Pipeline Files Fixes + Provider UX (2026-04-03)

**Multiple fixes and features for the pipeline files page and LLM provider workflow:**

### 1. Pipeline files display fixes
- HTTP 500 on the `pending` filter resolved: the UNION query in `GET /api/pipeline/files`
  had ambiguous column names across joined tables. Fixed by wrapping the UNION in a
  subquery so ORDER BY / column references are unambiguous.
- Unicode escape sequences (e.g., `\u2190`, `\u2014`) were rendering as literal text
  in the HTML page. Replaced all JS `\u` escapes in HTML files with proper HTML entities
  (`&larr;`, `&mdash;`, etc.). JS escapes are only valid inside `<script>` blocks, not
  in HTML attribute values or `innerHTML`.

### 2. LLM provider status banner on pipeline files page
- Red eye-catching banner appears when the active AI provider is missing, inactive, or
  unverified.
- Shows a contextual message: "No AI provider configured", "No active AI provider", or
  "Active AI provider needs verification".
- Clickable link to the providers page. The link appends `?return=pipeline-files.html`
  so the user can navigate back with context after fixing the provider.

### 3. Return-to workflow on providers page
- When `static/providers.html` is loaded with a `?return=` query parameter, a blue
  banner appears at the top with a "Return to previous page" link.
- Minimizes workflow interruption when navigating from another page to fix a provider.

### 4. Auto-requeue failed analysis on provider verify
- `POST /api/llm-providers/{id}/verify` now resets all `analysis_queue` rows with
  `status='failed'` to `status='pending'` with `retry_count=0` on successful verification.
- Handles the common case where images failed analysis because the provider wasn't
  configured or verified — they automatically re-enter the processing queue.
- API response now includes a `requeued_analysis` field with the count of reset rows.

### 5. GPU health display fix
- `_read_host_worker_report()` in `core/gpu_detector.py` no longer requires `worker.lock`
  or a fresh timestamp check. Reads hardware capabilities directly from the reset script's
  `worker_capabilities.json`. Health check now correctly considers `host_worker_available`
  when determining OK status.

### 6. Providers page delete button fix
- `API.delete` → `API.del` in `static/providers.html`. `delete` is a JavaScript reserved
  word and cannot be used as a method name via dot notation.

**Files changed:**
- `api/routes/pipeline.py` — subquery fix for UNION ambiguous column names
- `api/routes/llm_providers.py` — auto-requeue failed analysis on verify; `requeued_analysis` in response
- `core/gpu_detector.py` — read capabilities from `worker_capabilities.json` directly
- `static/pipeline-files.html` — HTML entity fix for unicode escapes; LLM provider status banner
- `static/providers.html` — return-to banner; `API.delete` → `API.del`

---

## v0.19.5 — HDD Scan Optimizations (2026-04-03)

**Three targeted improvements to reduce mechanical HDD scan time:**

### 1. Directory mtime skip (incremental scanning)
- New `scan_dir_mtimes` table (migration 21): stores `(location_id, dir_path, mtime)`
  across scan runs for both bulk and lifecycle scanners.
- `core/db/bulk.py`: 5 new helpers — `load_dir_mtimes()`, `save_dir_mtimes_batch()`,
  `get_incremental_scan_count()`, `increment_scan_count()`, `reset_scan_count()`.
- `core/db/preferences.py`: 2 new defaults — `scan_incremental_enabled` (true),
  `scan_full_walk_interval` (5).
- On rescan, directories with unchanged mtimes are skipped entirely (no `os.walk`
  descent). Full walk is forced every Nth scan (preference-configurable) and any time
  the scan runs outside business hours (using `scanner_business_hours_start/end`).
- Applies to all 3 scan paths: bulk serial, bulk parallel (`_walker_thread`),
  and lifecycle (`_walker_thread`).

### 2. Batched serial DB writes
- The bulk serial (HDD) scan path now accumulates files in a 200-file buffer
  and flushes via `upsert_bulk_files_batch()` (introduced in v0.19.3) instead
  of committing per file. Previously the serial path did not use the batch helper.

### 3. Disk/DB overlap in serial scan
- After flushing a batch, DB writes are launched as `asyncio.create_task()` so the
  next round of stat() calls starts immediately without waiting for the DB commit.
  Disk I/O stays strictly serial; only DB writes run concurrently.
- Each pending write task is awaited before a new one is created to prevent unbounded
  task accumulation.

**Files changed:**
- `core/db/schema.py` — migration 21: `scan_dir_mtimes` table
- `core/db/bulk.py` — `load_dir_mtimes()`, `save_dir_mtimes_batch()`,
  `get_incremental_scan_count()`, `increment_scan_count()`, `reset_scan_count()`
- `core/db/preferences.py` — `scan_incremental_enabled`, `scan_full_walk_interval` defaults
- `core/bulk_scanner.py` — incremental decision in `scan()`, mtime skip in `_serial_scan`
  and `_walker_thread`, batched writes + async overlap in `_serial_scan`
- `core/lifecycle_scanner.py` — mtime skip in walker threads, incremental decision
  + mtime persistence

---

## v0.19.4 — Pipeline File Explorer (2026-04-03)

**Clickable stat badges and a dedicated file browser page for the pipeline:**
- `static/status.html`: Status page stat pills converted from `<span>` to `<a>` tags
  linking to `pipeline-files.html?status={category}`.
- New `static/pipeline-files.html`: Full-featured file browser page.
  - 8 filter chips (scanned, pending, failed, unrecognized, pending_analysis, batched,
    analysis_failed, indexed) as multi-select toggles.
  - Search with 300ms debounce.
  - Full-width paginated table with inline detail expansion (error msg, skip reason,
    timestamps, job links).
  - Row actions: open in viewer, browse to source location.
- New `GET /api/pipeline/files` endpoint in `api/routes/pipeline.py` — multi-status
  UNION queries across `source_files`, `bulk_files`, `analysis_queue`, and Meilisearch
  browse for indexed files.
- New `get_pipeline_files()` DB helper in `core/db/bulk.py`.
- New `_browse_search_index()` helper in `api/routes/pipeline.py`.
- "Files" nav item added to `static/app.js` NAV_ITEMS array.
- Hover styles added to `static/markflow.css` (`.stat-pill--link`).

---

## v0.19.3 — Batched Bulk Scanner DB Upserts (2026-04-03)

**100x faster scan phase for large file sets:**
- `core/db/bulk.py`: New `upsert_bulk_files_batch()` writes batches of up to 200
  files in a single SQLite transaction (one `BEGIN`/`COMMIT` per batch). Previously,
  each file triggered 2 commits (~72,600 commits for 36K files ≈ 5 hours at ~2 files/sec).
  Now ~220 files/sec on NAS (~3–5 min for 36K files).
  Falls back to per-file upserts on error (logged as `batch_upsert_fallback`).
- Re-exported through `core/db/__init__.py`.
- `core/bulk_scanner.py`: Consumer loop updated — batch size increased from 100 to 200,
  separates convertible vs. unrecognized files, calls `upsert_bulk_files_batch()` for
  convertible files.

---

## v0.19.2 — LLM Token Usage Tracking (2026-04-03)

**Token cost tracking for the image analysis queue:**
- New `tokens_used INTEGER` column on `analysis_queue` (migration 20).
- `VisionAdapter.describe_batch()`: Anthropic, OpenAI, and Gemini batch methods
  now extract token usage from API responses (previously discarded). Token count
  is distributed evenly per image in the batch and carried on `BatchImageResult`.
- `core/db/analysis.py`: `write_batch_results()` persists `tokens_used` per row.
  New `get_analysis_token_summary()` returns aggregate totals and per-model
  breakdowns (total files analyzed, total tokens, average tokens/file, grouped
  by provider + model).
- `core/analysis_worker.py`: passes `tokens_used` from vision results through to
  `write_batch_results()`.
- Tests: `test_token_summary` validates multi-model aggregation; existing test
  updated with `tokens_used` field.

**Why:** At 100K+ images, duplicate or untracked LLM calls have real monetary
cost. Token counts were already returned by every provider API but discarded at
the vision adapter layer. This change closes the loop so usage is auditable
from the DB without log parsing.

---

## v0.19.1 — Fix Concurrent Bulk Job Race Condition (2026-04-03)

**Bug fix — duplicate bulk jobs caused SQLite deadlock and permanent stall:**
- Two independent code paths could create bulk jobs simultaneously:
  (1) the backlog poller in `_run_deferred_conversions` and (2) the
  auto-conversion trigger in `_execute_auto_conversion` after lifecycle scan
  completion. Neither path checked whether the other had already started a job.
- Concurrent jobs scanning the same source path into `bulk_files` caused SQLite
  write contention. Both jobs stalled at ~85-90% of their scan phase and never
  transitioned from "scanning" to "running" — zero files were ever converted.
- The in-memory `get_all_active_jobs()` misreported scanning jobs as `"done"`
  because `_total_pending == 0` during the scan phase, allowing the guard in the
  backlog poller to pass when it should have blocked.

**Fixes applied:**
- `core/bulk_worker.py`: Added `_scanning` flag to `BulkJob.__init__()`, set to
  `True` during scan phase, cleared before transitioning to "running". Updated
  `get_all_active_jobs()` status derivation to return `"scanning"` when flag is set.
- `core/lifecycle_scanner.py`: Added concurrency guard to `_execute_auto_conversion()` —
  checks `get_all_active_jobs()` and refuses to create a new job if any existing
  job has status `scanning`, `running`, or `paused`.
- `core/scheduler.py`: Hardened the backlog poller guard with an explicit status
  filter on the in-memory check AND a DB-level fallback query against `bulk_jobs`
  to catch jobs that exist in the DB but not yet in memory.

---

## v0.19.0 — Decoupled Conversion Pipeline + Fast NAS Scanning (2026-04-03)

**Decoupled conversion from scan completion (producer-consumer pattern):**
- `core/scheduler.py`: `_run_deferred_conversions` now works in all modes
  (`immediate`, `queued`, `scheduled`), not just `scheduled`.
- Every 15 minutes, checks `bulk_files WHERE status='pending'`. If pending > 0
  and no active bulk job, creates a BulkJob and starts conversion immediately.
- Conversion no longer requires `on_scan_complete()` — scanner and converter
  run independently. Scanner produces work items, poller drains them.
- Fixes pipeline stall where 100K+ NAS files couldn't finish scanning within
  the 15-min interval, permanently blocking auto-conversion.

**Fast NAS detection in storage probe:**
- `core/storage_probe.py`: New `nas_fast` classification for network mounts
  with SSD-like latency (< 0.1ms, ratio < 2.0).
- Checks filesystem type via `stat -f -c %T` with `/proc/mounts` fallback
  to distinguish local SSD from CIFS/NFS/sshfs mounts.
- `nas_fast` gets 4 parallel scan threads (was 1 when misclassified as `ssd`).

**Scanner interval increased:**
- Default `scanner_interval_minutes` preference: 15 → 45 minutes.
- Scheduler hardcoded interval: 15 → 45 minutes.

---

## v0.18.1 — Bulk Upsert Race Condition Fix (2026-04-03)

**Bug fix — UNIQUE constraint race in `upsert_bulk_file()`:**
- `core/db/bulk.py`: Replaced SELECT-then-INSERT pattern with atomic
  `INSERT ... ON CONFLICT(job_id, source_path) DO UPDATE SET ...`.
- The old pattern checked for an existing row with SELECT, then INSERTed if not
  found. On rescans, previously-registered files caused `UNIQUE constraint failed:
  bulk_files.job_id, bulk_files.source_path` errors (286+ per scan cycle).
- The errors were caught per-file (scan continued), but the cumulative overhead of
  89K+ files on a NAS mount with per-file error handling prevented the scan from
  completing within the 15-minute scheduler interval.
- Since `on_scan_complete()` was never reached, auto-conversion was never triggered,
  leaving all files stuck at `pending_conversion` with 0 files converted or indexed.
- The atomic upsert preserves the same skip/pending logic via SQL CASE expressions:
  if `stored_mtime` matches the incoming `source_mtime`, status is set to `skipped`;
  otherwise status is reset to `pending` for re-conversion.

---

## v0.18.0 — Image Analysis Queue + Pipeline Stats (2026-04-02)

**Decoupled LLM vision analysis for standalone image files:**
- New `analysis_queue` table (migration 19): `pending -> batched -> completed | failed`.
- Bulk worker enqueues image files after successful conversion.
- Lifecycle scanner enqueues new and content-changed image files on discovery.
- New `core/analysis_worker.py` (APScheduler, 5-min interval): claims up to
  `analysis_batch_size` pending rows, marks them `batched`, calls
  `VisionAdapter.describe_batch()` (one API call for all), writes results, re-indexes.
- `VisionAdapter.describe_batch()`: single multi-image call for Anthropic, OpenAI,
  Gemini. Ollama falls back to sequential if model rejects multiple images.
- LLM description + extracted text appended to Meilisearch `content` field — image
  files are searchable by visual content.
- Retry: failed batches reset to `pending` up to 3 times, then permanently `failed`.
- New preferences: `analysis_enabled` (kill switch), `analysis_batch_size` (default 10).

**Pipeline funnel statistics:**
- `GET /api/pipeline/stats`: scanned, pending conversion, failed, unrecognized,
  pending analysis, batched for analysis, analysis failed, in search index.
- Status page: stat strip above job cards.
- Admin page: Pipeline Funnel stats card.

**Bug fix — lifecycle scanner auto-conversion (source_path kwarg):**
- `core/lifecycle_scanner.py:924` was calling `BulkJob(source_path=...)` but
  `BulkJob.__init__` expects `source_paths=` (plural). Every auto-conversion
  triggered by the lifecycle scanner was silently failing with
  `BulkJob.__init__() got an unexpected keyword argument 'source_path'` since
  approximately 2026-04-02T12:06. Fixed by correcting the kwarg name.

**Bug fix — stale GPU display:**
- `core/gpu_detector.py`: `_read_host_worker_report()` now checks `worker.lock`
  existence and timestamp age before trusting `worker_capabilities.json`.
  Stale workstation GPU (e.g. NVIDIA 1660 Ti from disconnected workstation) no
  longer displayed as the active GPU.
- `tools/markflow-hashcat-worker.py`: writes heartbeat timestamp every 2 minutes.

---

## v0.17.7 — Scan Priority Coordinator (2026-04-01)

**Scan priority hierarchy: Bulk Job > Run Now > Lifecycle Scan:**
- New `core/scan_coordinator.py` manages mutual exclusion between scan types
  using asyncio Events for cancel/pause signaling.
- **Bulk jobs** are highest priority: starting a bulk job cancels any active
  lifecycle scan (clean cancel, releases DB) and pauses any active run-now
  scan (resumes automatically when bulk completes).
- **Run-now** is mid priority: cancels lifecycle scans on start. If a bulk
  job is active, run-now pauses and waits for it to finish before proceeding.
- **Lifecycle scans** are lowest priority: never pause, only cancel. On
  cancellation, the scan finalizes with status "cancelled", skips deletion
  detection (incomplete seen_paths would incorrectly mark files as deleted),
  skips auto-conversion trigger, and picks up at the next scheduled interval.
- Lifecycle scanner walker loops (`_serial_lifecycle_walk`,
  `_parallel_lifecycle_walk`, `_walker_thread`) now check
  `is_lifecycle_cancelled()` alongside `should_stop()` at every file.
- `BulkJob.run()` calls `notify_bulk_started()` on entry and
  `notify_bulk_completed()` in `finally` block.
- New `/api/pipeline/coordinator` debug endpoint exposes coordinator state.
- Eliminates "database is locked" errors from concurrent lifecycle + bulk
  DB writes — lifecycle cleanly exits before bulk starts writing.

---

## v0.17.6 — Scheduler Yield Guards (2026-04-01)

**Scheduled jobs yield to bulk jobs:**
- Trash expiry, DB compaction, integrity check, and stale data check now all
  yield to active bulk jobs (matching the existing lifecycle scan pattern).
- Each job calls `get_all_active_jobs()` and returns early if any bulk job
  has status scanning/running/paused.
- Previously only the lifecycle scan checked for active jobs; trash moves
  during bulk scans caused "database is locked" errors.

---

## v0.17.5 — Scrollable Interactive Search Preview (2026-04-01)

- Preview popup body changed from `overflow: hidden` to `overflow: auto` —
  enables vertical and horizontal scrolling of preview content.
- Markdown preview changed from `overflow-y: auto` to `overflow: auto` —
  wide tables and code blocks now scroll horizontally.
- Re-applied v0.17.4 interactive preview + auto-dodge code that was overwritten
  by a concurrent git pull (pointer-events, idle timer, dodge transition).

---

## v0.17.4 — Interactive Search Preview with Auto-Dodge (2026-04-01)

**Interactive hover preview:**
- Search result hover preview popup is now interactive (`pointer-events: auto`).
- Users can scroll preview content, click the "Open" link to view in the document
  viewer, and interact with embedded iframes.
- After 2 seconds of mouse inactivity on the popup, it slides offscreen via CSS
  `transform: translateY(120vh)` with a smooth 0.3s ease transition ("dodge").
- If the mouse re-enters the dodged popup, it slides back and interaction resumes.
- Each period of 2 seconds idle triggers another dodge — the cycle repeats.
- 300ms grace period on row `mouseleave` prevents flicker when moving between the
  search result row and the preview popup.

**macOS deployment scripts:**
- New `Scripts/macos/` directory with `build-base.sh`, `reset-markflow.sh`, and
  `refresh-markflow.sh` for personal macOS machine.
- Hardcoded source/output paths for local development.
- `reset-markflow.sh` generates `.env` with hardware-tuned settings (worker count,
  Meilisearch memory) and macOS-compatible `DRIVE_C`/`DRIVE_D` variables.
- `.env` now includes `DRIVE_C` and `DRIVE_D` for macOS drive browser mounts
  (replaces Windows `C:/` and `D:/` defaults that caused container startup failure).

---

## v0.17.3 — Skip Reason Tracking & Startup Crash Fix (2026-04-01)

**Skip reason tracking:**
- New `skip_reason` column on `bulk_files` table (schema migration #18).
- Every file skip now records a human-readable reason:
  - **Path too long**: `"Output path too long (X chars, max Y)"`
  - **Output collision**: `"Output collision (skip strategy)"`
  - **OCR below threshold**: `"OCR confidence X% below threshold Y%"`
  - **Unchanged file**: `"Unchanged since last scan"`
- Path safety skips now properly update `bulk_files` status to `"skipped"` with
  counter increments (previously silently skipped with status left as `"pending"`).
- Job detail page displays skip reasons in amber text in the Details column,
  matching the existing `error_msg` pattern for failed files.

**Scheduled jobs yield to bulk jobs:**
- Trash expiry, DB compaction, integrity check, and stale data check now all
  yield to active bulk jobs (matching the existing lifecycle scan pattern).
  Previously only the lifecycle scan checked for active jobs; trash moves
  during bulk scans caused "database is locked" errors.

**Startup crash fix:**
- Fixed missing `Query` import in `api/routes/bulk.py` that caused a `NameError`
  on container startup, crash-looping the markflow service. The pending files
  endpoint (added in v0.17.2) used `Query()` for parameter validation without
  importing it from FastAPI.

---

## v0.17.2 — UI Layout Cleanup & Pending Files Viewer (2026-04-01)

- System Status health check moved from Convert page to Status page.
- Pending Files viewer on History page with live count, search, pagination,
  color-coded status badges.
- Convert page: Browse button for output directory, session-sticky path,
  Conversion Options section with disclaimer.

---

## v0.17.1 — Job Config Modal, Browse All, Auto-Convert Backlog Fix (2026-04-01)

**Job configuration modal:**
- "Start Job" now opens a configuration dialog before launching the job.
- Modal sections: **Conversion** (workers, fidelity, OCR mode, Adobe indexing),
  **Scan Options** (threads, collision strategy, max files), **OCR** (confidence
  threshold, unattended mode), **Password Recovery** (dictionary, brute-force,
  timeout, GPU acceleration).
- Each section shows global defaults with per-job override capability.
- API extended: `CreateBulkJobRequest` accepts optional override fields
  (`scan_max_threads`, `collision_strategy`, `max_files`, `ocr_confidence_threshold`,
  `unattended`, `password_*`). `BulkJob` stores overrides dict for downstream use.

**Search "Browse All":**
- New "Browse All" button on the Search page shows all indexed documents sorted
  by date when no query is entered.
- API `GET /api/search/all` now accepts empty queries (`q=""`) — Meilisearch
  natively supports empty-string queries returning all documents.
- Empty queries default to sort-by-date and skip highlighting.

**Auto-converter backlog fix:**
- The auto-converter previously only triggered on new/modified files from lifecycle
  scans. If a prior bulk job failed (e.g., due to the `_is_excluded` bug), the
  60K+ pending files were orphaned and never retried.
- New `_get_pending_backlog_count()` method checks `bulk_files` for pending rows
  when no new files are discovered. If backlog exists and no job is active,
  auto-conversion triggers to process it.

---

## v0.17.0 — Job Detail Page & Enhanced Viewer (2026-04-01)

**Job Detail page (industry-standard batch job monitoring):**
- Click any Job History row to open `/job-detail.html` with full job details.
- Summary header: status badge, job ID, source/output paths, timing (started/finished/duration).
- Cancellation/error reason banner — prominently displayed for cancelled/failed jobs.
- Stats bar: total/converted/failed/skipped/adobe counts with color-coded segmented progress bar.
- Three tabs: **Files** (paginated table with status filter chips + search), **Errors** (searchable
  list with expandable error details), **Info** (full job configuration).
- Re-run button starts a new job with identical settings.
- Error links in Job History now navigate to the Errors tab (were: broken raw JSON links).

**Cancellation reasons tracked:**
- New `cancellation_reason` column on `bulk_jobs` (migration #17).
- User cancel: "Cancelled by user". Error-rate abort: "Aborted: error rate X%...".
- Fatal exceptions: "Fatal error: ...". Container restart orphans: "Cancelled: container restarted...".

**Enhanced Document Viewer:**
- Three view modes: Source (iframe), Rendered (markdown via marked.js + DOMPurify), Raw (line numbers).
- In-document search: Ctrl+F opens search bar, highlights matches, navigate with arrows/Enter.
- Word wrap toggle for raw view. Copy to clipboard button. Sticky toolbar.

**Search preview upgrade:**
- Preview popup now renders markdown (was: raw text truncated at 2000 chars).
- Uses marked.js + DOMPurify for safe HTML rendering, shows up to 5000 chars.
- "Open" link in preview header opens the full viewer page.
- Proper CSS for tables, code blocks, and headings in preview popup.

**Bug fix — Scanner `_is_excluded` scope error:**
- `_is_excluded()` was a local function in `run_scan()` but referenced in `_walker_thread()`
  inside `_parallel_scan()` — a separate method. Closures don't cross method boundaries.
  All worker threads crashed with `NameError`, causing every scan to find 0 files.
- Fix: moved to `BulkScanner._is_excluded()` class method.

**Other:**
- Job History rows: clickable with hover effect, show start time + finish time + duration.
- Locations page: "Close & return to Bulk Jobs" link when opened from Manage link.
- Job History timestamps: added "Started" / "Finished" labels and computed duration display.

---

## v0.16.9 — Multi-Source Scanning (2026-04-01)

**All source locations scanned in a single run:**
- Lifecycle scanner now resolves all configured source locations (was: first only).
  Validates each root, skips inaccessible ones, walks the rest sequentially within
  the same scan run. Shared counters, `seen_paths`, and error tracking accumulate
  across roots. Each root gets its own storage probe (different mounts may be
  different hardware types).
- Bulk jobs accept `scan_all_sources: bool` in the API request. `BulkJob` accepts
  `source_paths: list[Path]` and loops the scanning phase, merging `ScanResult`
  fields. Workers convert the combined file queue as one batch — same job ID,
  same worker pool, same DB pipeline.
- New "Scan all source locations" checkbox on the Bulk Jobs page. When checked,
  disables the source dropdown and sends the flag. One job, one queue.
- All existing settings (throttling, error-rate abort, exclusions, pipeline
  controls, stop/cancel) apply per-root as before. No new settings needed.

---

## v0.16.8 — Job History Cleanup (2026-04-01)

**Job History readability improvements (Bulk page):**
- Timestamps now use `formatLocalTime()` — displays as "Apr 1, 2026, 3:13 PM"
  instead of raw ISO strings like `2026-04-01T15:13:45.077192+00:00`.
- Status labels title-cased: "Completed" instead of "COMPLETED".
- Stats show "X of Y converted" when total file count is available.
- Exclusion count now shown in Settings page Locations summary card
  (e.g. "3 locations: 2 source · 1 output · 1 exclusion").

---

## v0.16.7 — Collapsible Settings Sections (2026-04-01)

**Settings page UX cleanup:**
- All 16 settings sections wrapped in native `<details>/<summary>` collapsible elements.
- Only Locations and Conversion sections open by default; all others start collapsed.
- "Expand All / Collapse All" toggle button in the page header.
- Animated chevron (right-pointing triangle rotates 90 degrees on open).
- Smooth slide-down animation when opening a section.
- Uses semantic HTML — no JavaScript for open/close behavior.

---

## v0.16.6 — Location Exclusions (2026-04-01)

**Path exclusion for scanning:**
- New "Exclude Location" feature on the Locations page.
- Exclusions use prefix matching — excluding `/host/c/Archive` skips all files and
  subdirectories under that path during both bulk and lifecycle scans.
- New `location_exclusions` DB table with full CRUD.
- API endpoints: `GET/POST /api/locations/exclusions`, `GET/PUT/DELETE /api/locations/exclusions/{id}`.
- Both `BulkScanner` and lifecycle scanner load exclusion paths once at scan start.
- Filtering at the `os.walk()` level: excluded directories are pruned from `dirnames[:]`
  so Python never descends into them. File-level check as safety net.
- Fast walk counter (file count estimator) also respects exclusions.
- UI mirrors the existing Add Location form: name, path, notes, Browse, Check Access,
  inline edit/delete with confirmation.

---

## v0.16.5 — Activity Log Pagination (2026-04-01)

**Activity log UX improvements (Resources page):**
- Per-page buttons (10/30/50/100/All) matching search page pattern for consistency.
- Fixed-height scrollable container (600px max) with sticky table header.
- Default reduced from 100 to 10 rows to keep page manageable.
- "Showing X of Y events" count summary below table.
- "All" sends limit=500 (API max).

---

## v0.16.4 — Filename Search Normalization (2026-04-01)

**Filename-aware search matching:**
- New `filename_search` field added to all three Meilisearch indexes (documents,
  adobe-files, transcripts). Populated at index time by `normalize_filename_for_search()`.
- Normalizer splits filenames on:
  - Explicit separators: `_`, `.`, `-`
  - camelCase/PascalCase boundaries: `getUserName` -> `get User Name`
  - Letter/number transitions: `Resume2024` -> `Resume 2024`
- File extensions stripped before normalization (`.pdf`, `.docx`, etc.)
- Original `source_filename` preserved for display; `filename_search` is a shadow
  field used only for matching.
- Requires index rebuild after deploy to backfill existing documents.

**Rebuild Index button:**
- Added "Rebuild Index" button to Bulk page pipeline controls (between Pause and Run Now).
- Triggers `POST /api/search/index/rebuild` with toast confirmation.
- Button disables for 5 seconds to prevent double-clicks.

---

## v0.16.3 — Search Hover Preview (2026-04-01)

**Search result hover preview:**
- Hovering over a search result shows a preview popup of the file content after a
  configurable delay (default 400ms). Smart hybrid strategy selects the best preview:
  - **Inline-able files** (PDF, images, text, HTML, CSV) — rendered in a sandboxed iframe
    via the existing `/api/search/source/` endpoint
  - **Other converted files** — first 2000 characters of the converted markdown shown as
    plain text via `/api/search/view/`
  - **No preview available** — displays "Cannot render preview" message
- Preview popup positioned to the right of the hovered result, flips left when near
  viewport edge, clamped to stay on screen.
- Client-side doc-info cache avoids redundant API calls on repeated hovers.
- Three new user preferences (Settings > Search Preview):
  - `preview_enabled` — toggle on/off (default: on)
  - `preview_size` — small (320x240), medium (480x360), large (640x480)
  - `preview_delay_ms` — hover delay before popup appears (100-2000ms, default: 400)

---

## v0.16.2 — Streamlining Audit Complete + Search UX Fix (2026-04-01)

**Search viewer back-button fix:**
- Viewer pages (opened in new tabs from search results) now close the tab on back-button
  press or "Back to Search" click, returning focus to the search results page. Falls back
  to navigation if `window.close()` is blocked by the browser.

**Final 3 streamlining items resolved (24/24 complete):**
- **STR-05: database.py module split** — 2,300-line monolith split into `core/db/` package
  with 8 domain modules: `connection.py` (path, get_db, helpers), `schema.py` (DDL, migrations,
  init_db), `preferences.py`, `bulk.py` (jobs + files + source files), `conversions.py`
  (history, batch state, OCR, review queue), `catalog.py` (adobe, locations, LLM providers,
  unrecognized, archives), `lifecycle.py` (lifecycle queries, versions, path issues, scans,
  maintenance), `auth.py` (API keys). `core/database.py` remains as a backward-compatible
  re-export wrapper — all 40+ external import sites unchanged.
- **STR-13: upsert_source_file UPSERT** — converted from SELECT-then-INSERT/UPDATE to
  `INSERT ... ON CONFLICT(source_path) DO UPDATE SET ...`. Dynamic `**extra_fields` handled
  in both insert columns and conflict-update clause. Single atomic statement replaces two
  separate connection opens.
- **STR-17: Schema migration table** — new `schema_migrations` table replaces 40+
  `_add_column_if_missing()` calls (each doing `PRAGMA table_info()`). 16 versioned migration
  batches covering all historical ALTER TABLE additions. On startup: check one table, skip
  all applied migrations. First run on existing DBs: applies all (no-ops), records them.
  Subsequent startups: zero schema introspection queries.

---

## v0.16.1 — Code Streamlining + Security/Quality Audit (2026-04-01)

**Code quality (21 of 24 items resolved):**
- **Shared ODF utils** — new `formats/odf_utils.py` with `extract_odf_fonts()` and `get_odf_text()`.
  Replaces 3 near-identical implementations across odt/ods/odp handlers.
- **ALLOWED_EXTENSIONS from registry** — `converter.py` now derives upload extensions from the
  handler registry (`list_supported_extensions()`), auto-syncing when new formats are added.
- **`db_write_with_retry()` exported** — moved from private `bulk_worker.py` function to
  public `database.py` export. Available to all concurrent DB writers.
- **`now_iso()` consolidated** — single source in `database.py`, removed 3 duplicate definitions
  in lifecycle_scanner, metadata, and bulk routes.
- **`verify_source_mount()` shared** — renamed from `_verify_source_mount` in bulk_scanner,
  imported by lifecycle_scanner (replaced inline duplicate).
- **Singleton indexer enforced** — `flag_manager.py` now uses `get_search_indexer()` instead of
  `SearchIndexer()` direct instantiation.
- **Hoisted deferred imports** — `asyncio` in lifecycle_scanner (4 sites), `get_preference` in
  scheduler (5 sites), `record_activity_event` in 6 files.
- **`upsert_adobe_index`** — converted to `INSERT ... ON CONFLICT DO UPDATE` (single DB call).
- **`_count_by_status()` helper** — shared GROUP BY status reduce logic in database.py.
- **Removed legacy `formatDate()`** — all callers migrated to `formatLocalTime()`.
- **`_throwOnError()` helper** — deduplicated 4-copy API error extraction in app.js. `err.data`
  now consistently available on all error methods.
- **Dead code cleanup** — removed unused `aiosqlite` imports (auto_converter, auto_metrics_aggregator),
  redundant `_log` in database.py, inline `import os` in flag_manager.
- **Logger naming** — renamed `logger` to `log` in auto_converter and auto_metrics_aggregator.

**Deferred to future sessions:**
- STR-05: Split `database.py` into domain modules (1,800+ lines, 40+ importers)
- STR-17: Replace `_add_column_if_missing` chain with schema migration table

**Audit documentation:**
- `docs/security-audit.md` — 62 findings (10 critical, 18 high, 22 medium, 12 low/info)
- `docs/streamlining-audit.md` — 24 findings with resolution status

---

## v0.16.0 — File Flagging & Content Moderation (2026-04-01)

**New features:**
- **Self-service file flagging** — Any authenticated user can flag a file from search results,
  temporarily suppressing it from search and download. Flag includes a reason and configurable
  expiry (default from `flag_default_expiry_days` preference).
- **Admin triage page** — Dedicated admin page (`flagged.html`) with three-action escalation:
  dismiss (restore file to search), extend (keep suppressed longer), or remove (permanent
  blocklist). Filters by status, sort by date/filename, pagination.
- **Blocklist enforcement** — `blocklisted_files` table stores permanently removed files by
  content hash and source path. Scanner checks both during indexing — prevents re-indexing of
  removed files even if they reappear or are copied elsewhere.
- **Meilisearch `is_flagged` attribute** — Filterable attribute added to all 3 indexes
  (documents, adobe-files, transcripts). Search endpoint filters out flagged files by default;
  admins can override with `?include_flagged=true`.
- **Webhook notifications** — All flag events (create, dismiss, extend, remove) send webhook
  POST to `flag_webhook_url` preference if configured.
- **Hourly auto-expiry** — Scheduler job expires active flags past their `expires_at` timestamp.
- **File size fix** — Search results now show original source file size from `source_files`
  table instead of markdown output size.
- **New preferences**: `flag_webhook_url` (default empty), `flag_default_expiry_days` (default `7`).

**New files:**
- `core/flag_manager.py` — flag business logic, blocklist checks, Meilisearch is_flagged sync, webhooks
- `api/routes/flags.py` — flag API: user flagging + admin triage (dismiss/extend/remove/blocklist)
- `static/flagged.html` — admin flagged files page with filters, sort, pagination

**Modified files:**
- `core/database.py` — `file_flags` and `blocklisted_files` table schemas, flag preference defaults
- `core/search_indexer.py` — sets `is_flagged` attribute during indexing, checks `file_flags` table
- `core/search_client.py` — `is_flagged` added to filterable attributes for all indexes
- `core/bulk_scanner.py` — blocklist check during scan (skips blocklisted files)
- `core/scheduler.py` — hourly flag expiry job
- `api/routes/search.py` — flag filtering in search results, access blocking for flagged files
- `static/search.html` — flag button on search results, flag modal
- `static/admin.html` — flagged files KPI card, nav entry
- `static/settings.html` — flag preferences section
- `static/app.js` — nav entry for flagged files page
- `main.py` — mount flags router
- `core/version.py` — bumped to 0.16.0

**Design notes:**
- Multiple flags can exist per file. The file stays hidden while ANY flag has `status` in
  (`active`, `extended`). `is_flagged` is only set to `false` when the last active/extended
  flag resolves or expires.
- Flag state survives Meilisearch index rebuilds — `search_indexer.py` checks `file_flags`
  during re-indexing and sets `is_flagged=true` for any file with an active/extended flag.
- Blocklist uses dual-match: both `content_hash` (catches copies) and `source_path` (catches
  re-appearances at the same location). A file matches if either field matches a blocklist entry.
- Fixed-path routes (`/mine`, `/stats`, `/blocklist`, `/lookup-source`) are defined before the
  `/{flag_id}` catch-all in `flags.py` to prevent FastAPI from matching literal paths as flag IDs.

---

## v0.15.1 — Cloud File Prefetch (2026-03-31)

**New features:**
- **CloudDetector** — Platform-agnostic detection of cloud placeholder files. Probes via disk block
  allocation (`st_blocks == 0`) and a timed read-latency test. Covers OneDrive, Google Drive,
  Nextcloud, Dropbox, iCloud, and NAS tiered storage. Configurable via `cloud_prefetch_probe_all`
  to force-probe all files regardless of block count.
- **PrefetchManager** — Background worker pool that materializes cloud placeholders before
  conversion. Features: configurable concurrency, per-minute token-bucket rate limiting, adaptive
  per-file timeouts, retry with exponential backoff, and backpressure via queue size cap.
- **Scanner integration** — `bulk_scanner.py` and `lifecycle_scanner.py` enqueue detected
  placeholder files to the prefetch queue during scan, so prefetch runs ahead of conversion.
- **Converter integration** — `converter.py` waits for in-flight prefetch before opening a file.
  Falls back to inline prefetch if the file was never queued (still works, just slower).
- **Health check** — Prefetch stats (queue depth, active workers, completion rate) added to
  `/api/health` response.
- **Settings page** — New Cloud Prefetch section with all preference controls.
- **New preferences**: `cloud_prefetch_enabled` (default `true`),
  `cloud_prefetch_concurrency` (default `4`), `cloud_prefetch_rate_limit` (requests/min, default `60`),
  `cloud_prefetch_timeout_seconds` (default `120`), `cloud_prefetch_min_size_bytes` (default `0`),
  `cloud_prefetch_probe_all` (default `false`).

**New files:**
- `core/cloud_detector.py` — placeholder detection via st_blocks + read latency
- `core/cloud_prefetch.py` — background prefetch worker pool

**Modified files:**
- `core/bulk_scanner.py` — enqueue files for prefetch during scan
- `core/lifecycle_scanner.py` — enqueue files for prefetch during lifecycle scan
- `core/converter.py` — wait for prefetch before reading file; inline prefetch fallback
- `core/health.py` — prefetch stats in health response
- `core/database.py` — cloud prefetch preference defaults
- `static/settings.html` — Cloud Prefetch settings section
- `core/version.py` — bumped to 0.15.1

**Design notes:**
- Prefetch is purely additive — disabling `cloud_prefetch_enabled` restores original behavior
  exactly. No code paths change; the wait in converter.py short-circuits immediately.
- Prefetch state is ephemeral — the queue and worker pool are in-memory only. Container restart
  clears all state; the next scan re-enqueues any remaining placeholders.
- Rate limit tokens refill per minute, not per second. Expect bursty traffic at startup when
  many placeholders are discovered at once; the token bucket smooths sustained throughput.
- `st_blocks == 0` is a reliable placeholder signal on most FUSE-based cloud mounts, but some
  mount types do not populate `st_blocks` correctly. The timed read-latency probe is the fallback
  for those cases.
- Inline prefetch in converter.py covers files that were not pre-queued (e.g., single-file
  uploads, or files discovered after the queue was already drained). It is slower than pre-queued
  prefetch because it blocks the conversion worker, but it is never a correctness failure.

---

## v0.15.0 — Search UX Overhaul + Enterprise Scanner Robustness (2026-03-31)

**New features:**
- **Unified search** — New `/api/search/all` endpoint searches all 3 Meilisearch indexes
  (documents, adobe-files, transcripts) concurrently and merges results. Faceted format filtering
  with clickable chips. Sort by relevance/date/size/format.
- **Document viewer** — New `static/viewer.html` page. Click a search result to view the original
  source file (PDF inline, other formats show fallback). Toggle between Source and Markdown views.
  Download button.
- **Source file serving** — New endpoints: `/api/search/source/{index}/{doc_id}` (view original),
  `/api/search/download/{index}/{doc_id}` (download original),
  `/api/search/doc-info/{index}/{doc_id}` (metadata for viewer).
- **Batch download** — `POST /api/search/batch-download` accepts a list of doc IDs, creates a ZIP
  of original source files. Multi-select checkboxes on search results.
- **Search UX improvements** — Per-page buttons (10/30/50/100), fixed autocomplete (was broken due
  to competing input handlers), local time display instead of UTC, middle-click opens viewer in
  new tab.
- **Source path in search index** — `search_indexer.py` now looks up `source_path` from the
  `source_files` DB table when frontmatter doesn't have it.
- **AD-credentialed folder handling** — All `os.walk()` calls in `bulk_scanner.py`,
  `lifecycle_scanner.py`, and `storage_probe.py` now use `onerror` callbacks that log
  `scan_permission_denied` with an AD hint instead of silently skipping.
- **Enterprise scanner robustness** — FileNotFoundError handling (AV quarantine), NTFS ADS
  filtering (skip files with `:` in name), stale SMB connection retry, explicit PermissionError
  logging.
- **Global `formatLocalTime()`** — Added to `app.js` for consistent local time display across all
  pages.

**New files:**
- `static/viewer.html` — document viewer page

**Modified files:**
- `api/routes/search.py` — all new endpoints (unified search, source file serving, batch download)
- `static/search.html` — complete UX redesign (format chips, per-page, multi-select, viewer links)
- `static/app.js` — `formatLocalTime()` helper
- `core/search_indexer.py` — source_path DB lookup, source_format made sortable
- `core/bulk_scanner.py` — AD/permission/ADS/quarantine handling on all walks
- `core/lifecycle_scanner.py` — AD/permission handling on all walks
- `core/storage_probe.py` — permission handling on probe walk
- `core/version.py` — bumped to 0.15.0

**Design notes:**
- Unified search merges results from all 3 indexes in a single response, deduplicating by source
  path where applicable. Each result carries its index origin for viewer routing.
- Source file serving resolves the original file path from the Meilisearch document's `source_path`
  field, with a DB fallback for older entries that predate the frontmatter change.
- AD-credentialed folders are common on enterprise file servers. The `onerror` callback pattern
  ensures nothing is silently skipped — operators see exactly which folders need ACL adjustments.
- NTFS Alternate Data Streams (files with `:` in the name) are metadata, not user files. Skipping
  them prevents confusing errors downstream.

---

## v0.14.1 — Health-Gated Startup + Pipeline Watchdog (2026-03-31)

**New features:**
- **Health-gated startup** — `core/pipeline_startup.py` replaces the old immediate force-scan at
  boot. On startup, the pipeline waits the configured delay (`pipeline_startup_delay_minutes`,
  default 5), then polls health checks before triggering the first scan+convert cycle. Critical
  services (DB, disk) must pass; preferred services (Meilisearch, Tesseract, LibreOffice) produce
  warnings but do not block. Max additional wait: 3 minutes of retries.
- **Pipeline watchdog** — `_pipeline_watchdog()` in `scheduler.py` runs hourly when the pipeline is
  disabled. Logs WARN every hour and ERROR every 24h. After `pipeline_auto_reset_days` (default 3),
  it auto-re-enables the pipeline and clears `pipeline_disabled_at`.
- **`disabled_info` in pipeline status API** — `GET /api/pipeline/status` now includes
  `disabled_info` with the disabled timestamp and auto-reset countdown (days/hours remaining).
- **Disabled warning banner on Bulk page** — `static/bulk.html` shows a dismissible banner when the
  pipeline is disabled, including the auto-reset countdown.
- New preferences: `pipeline_startup_delay_minutes` (default 5), `pipeline_auto_reset_days`
  (default 3), `pipeline_disabled_at` (auto-set timestamp when pipeline is disabled).

**Modified files:**
- `core/pipeline_startup.py` — new file: health-gated startup task
- `core/scheduler.py` — `_pipeline_watchdog()` job, sets/clears `pipeline_disabled_at`
- `core/database.py` — added `pipeline_startup_delay_minutes`, `pipeline_auto_reset_days`,
  `pipeline_disabled_at` default preferences
- `api/routes/pipeline.py` — `disabled_info` field in status response
- `main.py` — launch `pipeline_startup.py` background task instead of immediate force-scan
- `static/bulk.html` — disabled warning banner with auto-reset countdown
- `static/settings.html` — pipeline startup delay and auto-reset days inputs
- `core/version.py` — bumped to 0.14.1

**Design notes:**
- Startup delay prevents race conditions where the first scan fires before NAS mounts or
  Meilisearch finishes initializing.
- Watchdog auto-reset is a self-healing safeguard — if an operator accidentally disables the
  pipeline and forgets, it recovers automatically after N days without manual intervention.
- `pipeline_disabled_at` is set by the disable/pause path and cleared on re-enable; the watchdog
  reads it to compute the auto-reset deadline.

---

## v0.14.0 — Automated Conversion Pipeline (2026-03-31)

**New features:**
- **Pipeline control system** — the lifecycle scanner is now the sole trigger for conversion. When it
  detects new or changed files, it automatically spins up bulk conversion. No manual scan/convert
  triggers needed.
- `pipeline_enabled` preference — master on/off for the entire scan+convert pipeline (default: true)
- `pipeline_max_files_per_run` preference — cap on files converted per pipeline cycle (default: 0 = unlimited)
- Pipeline API endpoints: `GET /api/pipeline/status`, `POST /api/pipeline/pause`, `POST /api/pipeline/resume`, `POST /api/pipeline/run-now`
- Pipeline status card on Bulk Conversion page — shows mode, last/next scan, pending files, pause/resume/run-now controls
- Pipeline settings section on Settings page — master toggle and per-cycle file cap

**Modified files:**
- `core/database.py` — added `pipeline_enabled` and `pipeline_max_files_per_run` default preferences
- `core/scheduler.py` — pipeline master gate (checks `pipeline_enabled` and `_pipeline_paused`), `get_pipeline_status()`, `set_pipeline_paused()`/`is_pipeline_paused()` functions
- `core/lifecycle_scanner.py` — `_execute_auto_conversion()` now applies `pipeline_max_files_per_run` cap
- `api/routes/pipeline.py` — new router: status, pause, resume, run-now endpoints
- `main.py` — register pipeline router
- `static/bulk.html` — pipeline status card with live refresh
- `static/settings.html` — pipeline settings section with toggle and max files input
- `core/version.py` — bumped to 0.14.0

**Design notes:**
- Two layers of control: `pipeline_enabled` (persistent DB preference, survives restarts) and `_pipeline_paused` (in-memory, resets on restart)
- "Run Now" bypasses both pause and business hours via `force=True`
- Existing bulk job API endpoints are preserved for backward compatibility
- Auto-conversion engine continues to handle worker count, batch size, and scheduling decisions

---

## v0.13.9 — Source Files Dedup + Image/Format Support (2026-03-31)

**New features:**
- **Global file registry (`source_files` table)** — eliminates cross-job row duplication in `bulk_files`.
  `source_files` holds one row per unique `source_path` with all file-intrinsic data. `bulk_files`
  retains per-job data and links via `source_file_id` FK. Existing data auto-migrated on startup.
- Image files (.jpg, .jpeg, .png, .tif, .tiff, .bmp, .gif, .eps) via ImageHandler
- `.docm` (macro-enabled Word) and `.wpd` (WordPerfect) via DocxHandler + LibreOffice
- `.ait` / `.indt` (Adobe templates) via AdobeHandler
- All previously unrecognized file types now have handlers

**Modified files:**
- `core/database.py` — source_files CREATE TABLE, migration, upsert_source_file, query helpers
- `core/lifecycle_manager.py` — lifecycle transitions update source_files alongside bulk_files
- `core/lifecycle_scanner.py` — deletion/move detection queries source_files
- `core/bulk_worker.py` — propagates file-intrinsic data to source_files after conversion
- `core/bulk_scanner.py` — propagates MIME classification to source_files
- `core/scheduler.py` — trash expiry uses source_files pending functions
- `core/db_maintenance.py` — integrity checks use source_files
- `core/search_indexer.py` — reindex joins source_files for dedup
- `api/routes/admin.py` — cross-job stats query source_files
- `api/routes/trash.py` — trash view queries source_files
- `mcp_server/tools.py` — file lookup uses source_files
- `formats/image_handler.py` — new ImageHandler
- `formats/docx_handler.py` — added .docm, .wpd extensions
- `formats/adobe_handler.py` — added .ait, .indt extensions

**Design notes:**
- source_files UNIQUE(source_path) prevents duplication regardless of scan job count
- Migration is idempotent — safe to run multiple times
- Admin stats response includes both old keys (by_status, unrecognized_by_category) and new keys (by_lifecycle, by_category) for frontend backward compatibility

---

## v0.13.8 — Image File Support (2026-03-31)

NOTE: Superseded by v0.13.9 which includes all v0.13.8 features plus dedup.

## Previous v0.13.8 — Image File Support (2026-03-31)

**New features:**
- Image files (.jpg, .jpeg, .png, .tif, .tiff, .bmp, .gif, .eps) now supported via `ImageHandler`
- Extracts image metadata (dimensions, color mode, EXIF data) using Pillow and exiftool
- Produces a DocumentModel with metadata summary, embedded IMAGE element, and EXIF details
- Previously the largest group of unrecognized files (~7,347 images) — now handled natively

**Modified files:**
- `formats/image_handler.py` — new handler: ingest extracts metadata + embeds image, export writes Markdown
- `formats/__init__.py` — register ImageHandler import
- `core/bulk_scanner.py` — add image extensions to SUPPORTED_EXTENSIONS

**Design notes:**
- Follows AdobeHandler pattern: ingest extracts metadata, export writes Markdown (can't author binary images from text)
- Uses Pillow (already in requirements.txt) for dimensions/color mode/EXIF
- Uses exiftool (already in Dockerfile.base) for extended metadata (same subprocess pattern as AdobeHandler)
- No new dependencies required
- EPS support via Pillow's GhostScript integration (if GhostScript is installed)
- `.docm` (macro-enabled Word) now handled by DocxHandler via LibreOffice preprocessing
- `.wpd` (WordPerfect) now handled by DocxHandler via LibreOffice preprocessing
- `.ait` / `.indt` (Adobe Illustrator/InDesign templates) now handled by AdobeHandler
- All previously unrecognized file types now have handlers

---

## v0.13.7 — Legacy Office Format Support + Scheduler Fix (2026-03-31)

**New features:**
- `.xls` files now convert to Markdown via LibreOffice → openpyxl pipeline (same as `.xlsx`)
- `.ppt` files now convert to Markdown via LibreOffice → python-pptx pipeline (same as `.pptx`)
- Shared `core/libreoffice_helper.py` extracts the LibreOffice headless conversion logic used by all three legacy format handlers (`.doc`, `.xls`, `.ppt`)
- Lifecycle scan now yields to active bulk jobs — skips entirely if any bulk job is scanning/running/paused, preventing SQLite lock contention

**Modified files:**
- `core/libreoffice_helper.py` — new shared helper: `convert_with_libreoffice(source, target_format, timeout)`
- `formats/xlsx_handler.py` — EXTENSIONS now includes "xls"; ingest + extract_styles preprocess via LibreOffice
- `formats/pptx_handler.py` — EXTENSIONS now includes "ppt"; ingest + extract_styles preprocess via LibreOffice
- `formats/docx_handler.py` — `_doc_to_docx()` now delegates to shared helper
- `core/scheduler.py` — `run_lifecycle_scan()` checks `get_all_active_jobs()` before proceeding

**Design notes:**
- Same pattern as existing `.doc` → `.docx` preprocessing in DocxHandler
- Temp files cleaned in `finally` blocks to avoid disk leaks on conversion errors
- Default timeout increased to 120s (legacy files can be larger/slower to convert)
- Bulk scanner already had `.xls` and `.ppt` in `SUPPORTED_EXTENSIONS` — files were being scanned but failing with "No handler registered"
- Lifecycle scan guard: checks in-memory `_active_jobs` registry (not DB) — zero overhead, instant check. Deferred conversion runner inherits the guard since it calls `run_lifecycle_scan()` internally
- Root cause of "database is locked" errors: lifecycle scan (every 15 min) + metrics collector (every 2 min) + bulk workers all competing for SQLite. The lifecycle scan was the heaviest contender — scanning the entire source directory while bulk conversion was already doing the same

**Known issues identified (not yet fixed):**
- `bulk_files` table keyed by `(job_id, source_path)` — each new scan job inserts duplicate rows for the same files. 12,847 distinct source paths → 34K+ rows across 5 jobs. Per-job counts correct, but DB grows unbounded with repeated scans
- 4,237 unrecognized files in source repo: mostly images (.jpg 4211, .png 1349, .tif/.tiff 787, .eps 714, .gif 211), plus .wpd (WordPerfect, 277), .docm (20), .ait/.indt (Adobe templates, 115)
- LLM providers configured but not yet verified: Anthropic (529 overload, transient), OpenAI (429 rate limit, likely billing/quota)

---

## v0.13.6 — ErrorRateMonitor Across All I/O Subsystems (2026-03-31)

**New features:**
- Meilisearch `rebuild_index()`: aborts early if search service unreachable (50% error rate in last 50 ops)
- Cloud transcriber: session-level monitor disables cloud fallback after repeated API failures (60% rate in last 20 calls)
- EML/MSG handler: attachment processing aborts if conversion failures cascade (50% rate in last 20 attachments)
- Archive password cracking: distinguishes I/O errors (OSError = file unreadable) from wrong-password exceptions, aborts only on I/O failures (95% threshold — most attempts are expected to fail)

**Modified files:**
- `core/search_indexer.py` — `rebuild_index()` uses ErrorRateMonitor
- `core/cloud_transcriber.py` — session-level `_cloud_error_monitor` with fast-fail
- `formats/eml_handler.py` — both `_process_attachments_eml()` and `_process_attachments_msg()`
- `formats/archive_handler.py` — `_find_password()` with I/O-specific error detection

**Design notes:**
- Cloud transcriber monitor is session-scoped (module-level singleton) — persists across files. Once cloud APIs are known-bad, skip immediately for all subsequent transcriptions
- Password cracking monitor uses 95% threshold because wrong-password exceptions are normal. Only triggers on actual I/O failures (OSError, IOError)
- EML/MSG monitors are per-email — each email gets a fresh monitor since attachments are independent

---

## v0.13.5 — Archive Handler Optimization (2026-03-31)

**New features:**
- Batch extraction: `extractall()` for zip/tar/7z/rar/cab — one archive open/read cycle instead of N per-member cycles. Massive speedup over NAS (one network read vs hundreds)
- Parallel inner-file conversion: after batch extraction, inner files converted via ThreadPoolExecutor (up to 8 threads, capped to CPU count)
- ISO batch extraction: single `PyCdlib.open()` for all members instead of open/close per member
- ErrorRateMonitor integrated: aborts archive processing gracefully if error rate spikes (NAS disconnect mid-extraction), cleans up temp directory
- Nested archives processed sequentially after parallel files (recursive depth tracking requires serial)
- Summary line now shows extraction mode (batch/per-member) and thread count used
- Batch extraction falls back to per-member if `extractall()` fails (e.g., corrupted member)

**Modified files:**
- `formats/archive_handler.py` — batch extraction functions, parallel conversion, error-rate abort

**Design notes:**
- Batch vs per-member: batch is always tried first. If it fails (corrupted archive, partial password protection), falls back to the original per-member path
- Thread count for conversion: `min(file_count, cpu_count, 8)` — conversion is CPU-bound, not I/O-bound (files are already on local temp dir)
- Nested archives are NOT parallelized — each recursive call modifies the shared `ExtractionTracker` (quine detection, total size tracking)
- Temp dir cleanup in `finally` block is preserved — even on error-rate abort, temp dir is always removed

---

## v0.13.4 — OCR Quality Dashboard & Scan Throttle History (2026-03-31)

**New features:**
- Resources page: OCR Quality section with avg/min/max confidence KPIs, color-coded gauge, confidence timeline chart, distribution histogram bar chart
- Resources page: Scan Throttle History section with adjustment events table and scan summary cards
- Throttle adjustment events persisted to `activity_events` table (event types: `scan_throttle`, `scan_throttle_summary`)
- New API: `GET /api/resources/ocr-quality?range=30d` — returns confidence stats, distribution buckets, daily timeline
- New API: `GET /api/resources/scan-throttle?range=7d` — returns throttle adjustments and scan summaries

**Modified files:**
- `api/routes/resources.py` — added 2 new endpoints
- `static/resources.html` — added 2 new sections with Chart.js rendering
- `core/bulk_scanner.py` — added `_persist_throttle_events()` helper
- `core/lifecycle_scanner.py` — calls `_persist_throttle_events()` after parallel walk
- `core/storage_probe.py` — added `adjustments` property to `ScanThrottler`

---

## v0.13.3 — Error-Rate Monitoring & Abort (2026-03-31)

**New features:**
- `ErrorRateMonitor` class: rolling-window success/failure tracking with configurable thresholds
- Abort triggers: >50% error rate in last 100 operations, or 20 consecutive errors
- Integrated into all scanning paths: bulk serial, bulk parallel, lifecycle serial, lifecycle parallel
- Integrated into bulk conversion workers: if conversion failure rate spikes, job auto-cancels
- SSE events: `scan_aborted` (scanners), `job_error_rate_abort` (workers)
- Once triggered, abort is sticky — prevents restart-and-fail loops within same job

**Modified files:**
- `core/storage_probe.py` — added `ErrorRateMonitor` class
- `core/bulk_scanner.py` — both `_serial_scan()` and `_parallel_scan()` use error monitoring
- `core/lifecycle_scanner.py` — both serial and parallel walks use error monitoring
- `core/bulk_worker.py` — `_worker()` checks error rate before each file, records success/failure

**Design notes:**
- 20-consecutive-error fast path catches mount failures instantly (no need to wait for 100 ops)
- Rolling window (deque) bounds memory regardless of scan size
- `should_abort()` is idempotent — once triggered, always returns True (no flapping)
- Walker threads check `error_monitor.should_abort()` alongside `should_stop()` via `_should_bail()`

---

## v0.13.2 — Feedback-Loop Scan Throttling (2026-03-31)

**New features:**
- `ScanThrottler` class provides TCP-style congestion control for parallel scan workers
- Workers report stat() latency in real-time; throttler parks/unparks threads dynamically
- If NAS latency exceeds 3x baseline: shed 2 threads. 2x baseline: shed 1. Below 1.5x: restore 1
- 5-second cooldown between adjustments prevents oscillation
- Both bulk scanner and lifecycle scanner use throttled parallel scanning
- Completion logs show `threads_initial`, `threads_final`, and `throttle_adjustments` counts

**Modified files:**
- `core/storage_probe.py` — added `ScanThrottler` class
- `core/bulk_scanner.py` — `_parallel_scan()` now creates throttler, workers report latency + check pause
- `core/lifecycle_scanner.py` — `_parallel_lifecycle_walk()` same throttling integration

**Design notes:**
- `record_latency()` is ~0.001ms (deque append under lock) — negligible vs 3-10ms stat calls
- `should_pause(worker_id)` reads a single int (no lock) — zero overhead for active workers
- `check_and_adjust()` runs once per 500 files, computes median of last 100 latencies
- Workers with higher IDs are parked first (clean priority ordering)

---

## v0.13.1 — Adaptive Scan Parallelism (2026-03-31)

**New features:**
- Storage latency probe auto-detects storage type (SSD, HDD, NAS) before each scan
- Parallel directory walkers for NAS/SMB/NFS sources (4-12 threads hide network latency)
- Serial scan preserved for local disks (avoids HDD seek thrashing)
- Probe uses sequential-vs-random stat() timing ratio — stable even under background I/O load
- Both bulk scanner and lifecycle scanner benefit from adaptive parallelism
- New `scan_max_threads` preference: `"auto"` (default, probe decides) or manual override
- Settings page gains Scan Performance section
- SSE event `storage_probe_result` emitted so UI can display detected storage type

**New files:**
- `core/storage_probe.py` — `StorageProfile` dataclass, `probe_storage_latency()` async function

**Modified files:**
- `core/bulk_scanner.py` — integrated probe + `_parallel_scan()` / `_serial_scan()` split
- `core/lifecycle_scanner.py` — integrated probe + `_parallel_lifecycle_walk()` / `_serial_lifecycle_walk()`
- `core/database.py` — added `scan_max_threads` preference
- `api/routes/preferences.py` — added schema + system key for scan_max_threads

**Design notes:**
- The sequential-vs-random stat ratio is the key discriminator: HDD shows ratio > 3x (seek penalty), NAS shows ratio < 2x (uniform network latency), SSD shows both fast + low ratio
- A busy HDD under background I/O still shows the seek penalty ratio — avoids misclassification
- Thread workers push `(path, ext, size, mtime)` tuples into a `queue.Queue`; a single async consumer drains to SQLite. DB writes never bottleneck because local SSD writes are ~100x faster than NAS reads

---

## v0.13.0 — Media Transcription Pipeline (2026-03-30)

**New features:**
- Audio/video files (.mp3, .mp4, .wav, .mkv, etc.) now convert to Markdown transcripts with timestamped segments
- Three output files per media conversion: `.md` (timestamped transcript), `.srt`, `.vtt`
- Local Whisper transcription with GPU auto-detect (CUDA when available, CPU fallback)
- Cloud transcription fallback — tries OpenAI Whisper API and Gemini audio in provider priority order
- Existing caption files (SRT/VTT/SBV) detected alongside media files and parsed automatically (no transcription cost)
- Meilisearch `transcripts` index for full-text search across spoken content
- Cowork search extended to cover documents + transcripts
- 2 new MCP tools: `search_transcripts`, `read_transcript`
- Visual enrichment (scene detection + keyframe pipeline) optionally interleaved into video transcripts
- Settings page gains Transcription section (Whisper model, device, language, cloud fallback, timeout, caption extensions)
- History page shows media-specific metadata: duration, engine badge, language
- Health check includes Whisper availability and device info
- Bulk conversion counters include "Transcribed" count

**New files (10 core + 2 handlers + 1 API route):**
- `core/media_probe.py`, `core/audio_extractor.py`, `core/whisper_transcriber.py`
- `core/cloud_transcriber.py`, `core/caption_ingestor.py`, `core/transcription_engine.py`
- `core/transcript_formatter.py`, `core/media_orchestrator.py`
- `formats/audio_handler.py`, `formats/media_handler.py`
- `api/routes/media.py`

**Database changes:**
- New table: `transcript_segments` (history_id, segment_index, start/end seconds, text, speaker, confidence)
- New columns on `conversion_history`: media_duration_seconds, media_engine, media_whisper_model, media_language, media_word_count, media_speaker_count, media_caption_path, media_vtt_path
- New columns on `bulk_files`: is_media, media_engine
- New columns on `bulk_jobs`: transcribed, transcript_failed

**Dependencies:**
- Added: `openai-whisper`, `ffmpeg-python`
- `torch` (CPU) pre-installed in Dockerfile.base for faster rebuilds
- `whisper-cache` Docker volume for persistent model storage

---

**Phase 0 complete** — Docker scaffold running. All system deps verified.

**Phase 1 complete** — DOCX → Markdown pipeline fully implemented. 60 tests passing. Tagged v0.1.0.

**Phase 2 complete** — Markdown → DOCX round-trip with fidelity tiers. 96 tests passing. Tagged v0.2.0.

**Phase 3 complete** — OCR pipeline: multi-signal detection, preprocessing, Tesseract extraction,
  confidence flagging, review API + UI, unattended mode, SQLite persistence. Tagged v0.3.0.

**Phase 4 complete** — PDF, PPTX, XLSX/CSV format handlers (both directions). 231 tests passing. Tagged v0.4.0.

**Phase 5 complete** — Full test suite (350+ tests), structured JSON logging throughout all
  pipeline stages, debug dashboard at /debug. Tagged v0.5.0.

**Phase 6 complete** — Full UI: live SSE batch progress, history page (filter/sort/search/
  redownload), settings page (preferences with validation), shared CSS design system,
  dark mode, comprehensive error UX. 378 tests passing. Tagged v0.6.0.

**Phase 7 complete** — Bulk conversion pipeline (scanner, worker pool, pause/resume/cancel),
  Adobe Level 2 indexing (.ai/.psd text + .indd/.aep/.prproj/.xd metadata), Meilisearch
  full-text search (documents + adobe-files indexes), search UI, bulk job UI,
  Cowork search API. 467 tests. Tagged v0.7.0.

**v0.7.1** — Named Locations system: friendly aliases for container paths used in bulk jobs.
  First-run wizard guides setup. Bulk form uses dropdowns instead of raw path inputs.
  Backwards compatible with BULK_SOURCE_PATH / BULK_OUTPUT_PATH env vars. 496 tests.

**v0.7.2** — Directory browser: Windows drives mounted at /host/c, /host/d etc.
  Browse endpoint (GET /api/browse) with path traversal protection.
  FolderPicker widget on Locations page — no need to type container paths manually.
  Unmounted drives show setup instructions inline.

**v0.7.3** — OCR confidence visibility and bulk skip-and-review. Confidence scores
  (mean, min, pages below threshold) recorded per file and shown in history with
  color-coded badges. Bulk mode skips PDFs below confidence threshold into a review
  queue instead of failing them. Post-job review UI (bulk-review.html) lets user
  convert anyway, skip permanently, or open per-page OCR review per file.

**v0.7.4** — LLM providers (Anthropic, OpenAI, Gemini, Ollama, custom), API key
  encryption, connection verification, opt-in OCR correction + summarization +
  heading inference. Auto-OCR gap-fill for PDFs converted without OCR.
  MCP server (port 8001) exposes 7 tools to Claude.ai (later expanded to 10): search, read, list,
  convert, adobe search, get summary, conversion status. 543 tests.

**v0.7.4b** — Path safety and collision handling. Deeply nested paths checked
  against configurable max length (default 240 chars). Output path collisions
  (same stem, different extension) detected at scan time and resolved per
  strategy: rename (default, no data loss), skip, or error. Case-sensitivity
  collisions detected separately. All issues recorded in bulk_path_issues table,
  reported in manifest, downloadable as CSV.

**v0.7.4c** — Active file display in bulk progress. Collapsible panel shows
  one row per worker with current filename. Worker count matches Settings value.
  Collapse state persists in localStorage. Hidden when preference is off.
  `file_start` SSE event added; `worker_id` added to all worker SSE events.

**v0.8.1** — Visual enrichment pipeline. Scene detection (PySceneDetect), keyframe
  extraction (ffmpeg), and AI frame descriptions via the existing LLM provider system.
  VisionAdapter wraps the active provider for image input (Anthropic, OpenAI, Gemini,
  Ollama). Vision preferences stored in existing preferences table (not a separate
  settings system). DB: scene_keyframes table, vision columns on conversion_history.
  Meilisearch index extended with frame_descriptions field. Settings UI Vision section
  with provider display linking to existing providers.html. History detail panel shows
  scenes/enrichment/descriptions. Debug dashboard shows vision stats.

**v0.8.2** — Unknown & unrecognized file cataloging. Bulk scanner records every
  file it encounters, even without a handler. MIME detection via python-magic with
  extension fallback classifies files into categories (disk_image, raster_image,
  video, audio, archive, executable, database, font, code, unknown). New columns
  mime_type and file_category on bulk_files. Unrecognized files get
  status='unrecognized' (distinct from failed/skipped). API: GET /api/unrecognized
  (list, filter, paginate), /stats, /export (CSV). UI: /unrecognized.html with
  category cards, filters, table. Bulk progress shows unrecognized count pill.
  MCP tool: list_unrecognized (8th tool).

**v0.8.5** — File lifecycle management, version tracking & database health.
  APScheduler runs lifecycle scans every 15 min during business hours. Detects
  new/modified/moved/deleted files in source share. Soft-delete pipeline:
  active → marked_for_deletion (36h grace) → in_trash (60d retention) → purged.
  Full version history with unified diff patches and bullet summaries per file.
  Trash management page, DB health dashboard, lifecycle badges on all file views.
  6 new preference keys for scanner and lifecycle config. DB maintenance: weekly
  compaction, integrity checks, stale data detection. WAL mode enabled.
  MCP tools 9-10: list_deleted_files, get_file_history.

**v0.9.0** — Auth layer & UnionCore integration contract. JWT-based auth
  middleware with HS256 validation (UnionCore as identity provider). Role-based
  route guards: search_user < operator < manager < admin. API key service
  accounts for UnionCore backend (BLAKE2b hashed, `mf_` prefixed). Admin panel
  for key management. CORS configured for UnionCore origin. DEV_BYPASS_AUTH=true
  for local dev (all requests treated as admin). `/` redirects to search page.
  Role-aware dynamic navigation (nav items filtered by user role). Preferences
  split: system-level keys require manager role. Integration contract at
  `docs/unioncore-integration-contract.md`. New env vars: UNIONCORE_JWT_SECRET,
  UNIONCORE_ORIGIN, DEV_BYPASS_AUTH, API_KEY_SALT.

**v0.9.1** — Search autocomplete & scan progress visibility.
  Autocomplete dropdown on search.html powered by Meilisearch (debounced 200ms,
  keyboard navigable, deduplicates across documents + adobe-files indexes).
  `GET /api/search/autocomplete` endpoint. Bulk scan phase now emits
  `scan_progress` SSE events (count, pct, current_file) every 50 files with
  pre-counted total estimate. Background lifecycle scanner exposes in-memory
  `_scan_state` via `GET /api/scanner/progress` (polled every 3s by UI).
  Lifecycle scan status bar on bulk.html and db-health.html shows progress
  or last-scan timestamp. New tests in test_search.py and test_scanner.py.

**v0.9.2** — Admin page: resource controls, task manager & stats dashboard.
  `core/resource_manager.py` wraps psutil for CPU affinity, process priority,
  and live metrics. Admin page gains three sections: Repository Overview
  (KPI cards, file/lifecycle/OCR/format/Meilisearch/scheduler/error stats),
  Task Manager (per-core CPU bars, memory, threads, 2s polling), Resource
  Controls (worker count, priority, core pinning). New endpoints:
  `PUT /api/admin/resources`, `GET /api/admin/system/metrics`,
  `GET /api/admin/stats`. New preferences: worker_count, cpu_affinity_cores,
  process_priority. `get_scheduler_status()` added to scheduler.py.
  psutil primed at startup in lifespan. 16 new tests in test_admin.py.

**v0.9.3** — Global stop controls, active jobs panel, admin DB tools, locations
  flagged for UX redesign. `core/stop_controller.py`: cooperative global stop
  flag checked by bulk workers, bulk scanner, and lifecycle scanner before each
  file. `POST /api/admin/stop-all` cancels all registered asyncio tasks.
  `POST /api/admin/reset-stop` clears the flag. `GET /api/admin/active-jobs`
  returns all running jobs for the global status bar. Persistent floating status
  bar (`global-status-bar.js`) on every page shows job count, STOP ALL button,
  and stop-requested banner. Active Jobs slide-in panel (`active-jobs-panel.js`)
  shows per-job detail with progress bars, active workers, per-directory stats,
  and individual stop buttons. `dir_stats` on BulkJob tracks top-level
  subdirectory counts. Admin DB Tools section: quick health check, full integrity
  check, dump-and-restore repair (blocked if jobs running). Locations page flagged
  for UX redesign with visible banner. New tests in test_stop_controller.py,
  test_active_jobs.py, and additions to test_admin.py.

**v0.9.4** — Status page & nav redesign. Floating global-status-bar and
  slide-in active-jobs-panel replaced by dedicated `/status.html` with
  stacked per-job cards (progress bars, active workers, per-dir stats,
  pause/resume/stop controls). STOP ALL button and lifecycle scanner card
  live on status page. Nav gains "Status" link with active-job count
  badge (pulses red when stop requested). `global-status-bar.js` rewritten
  to badge-only polling; `active-jobs-panel.js` retired and deleted.
  `app.js` dynamically loads badge script after `buildNav()`. Old `.gsb-*`
  and `.ajp-*` CSS replaced by `.job-card`, `.status-pill`, `.nav-badge`
  design system classes. No backend changes.

**v0.9.5** — Configurable logging levels with dual-file strategy. Three levels:
  Normal (WARNING+), Elevated (INFO+), Developer (DEBUG + frontend trace).
  Operational log always active (logs/markflow.log, 30-day rotation).
  Debug trace log (logs/markflow-debug.log, 7-day) only active in Developer mode.
  Dynamic level switching — no container restart required. Settings UI Logging section
  with log file downloads. POST /api/log/client-event instruments ~15 JS actions in
  Developer mode (rate-limited, silently dropped at other levels).
  log_level is a system-level preference requiring Manager role.

**v0.9.6** — Admin disk usage dashboard. `GET /api/admin/disk-usage` walks all
  MarkFlow directories in a thread and reports per-directory byte counts, file
  counts, and volume info. Trash excluded from output-repo total (no double-count).
  DB + WAL reported separately in API, combined in UI. Admin page gains Disk Usage
  section with volume progress bars, breakdown cards, and manual Refresh button.
  No auto-polling — directory walks can take seconds on large repos.

**v0.9.7** — Resources page & activity monitoring. New `system_metrics` table
  (30s samples via APScheduler), `disk_metrics` (6h snapshots), `activity_events`
  (bulk start/end, lifecycle scan, index rebuild, startup/shutdown, DB maintenance).
  `core/metrics_collector.py` owns collection, queries, and 90-day purge.
  Resources page (`/resources.html`, manager+ role) with: executive summary card
  (IT admin pitch with description sentences), CPU/memory Chart.js time-series,
  disk growth stacked area chart, live system metrics (moved from Admin), activity
  log with type filters and expandable metadata, repository overview. CSV export
  for all three metrics tables. Admin Task Manager replaced with link card to
  Resources; resource controls remain on Admin. 5 new API endpoints under
  `/api/resources/` (metrics, disk, events, summary, export).

**v0.9.8** — Password-protected document handling. `core/password_handler.py`
  detects two layers: restrictions (edit/print flags stripped automatically via
  pikepdf/lxml) and real encryption (password cascade: empty → user-supplied →
  org list → found-reuse → dictionary → brute-force → john). `pikepdf` handles
  PDF owner/user passwords. `msoffcrypto-tool` handles OOXML + legacy Office
  encryption. OOXML restriction tags (`documentProtection`, `sheetProtection`,
  `workbookProtection`, `modifyVerifier`) stripped via ZIP+lxml rewrite.
  Converter preprocesses files before `handler.ingest()` — no handler signature
  changes. Bulk worker shares `PasswordHandler` instance across files for
  found-password reuse. Convert page gains password input field. Settings page
  gains Password Recovery section (6 new preferences). DB columns:
  `protection_type`, `password_method`, `password_attempts` on both
  `conversion_history` and `bulk_files`. `john` installed in Docker for
  enhanced PDF cracking. Bundled `common.txt` dictionary (top passwords).

**v0.9.9** — GPU auto-detection & dual-path hashcat integration.
  `core/gpu_detector.py` probes container for NVIDIA (nvidia-smi) and reads
  host worker capabilities from `/mnt/hashcat-queue/worker_capabilities.json`.
  Execution path priority: NVIDIA container > host worker > hashcat CPU > none.
  `tools/markflow-hashcat-worker.py` runs outside Docker, watches shared queue
  volume for crack jobs, runs hashcat with host GPU (AMD ROCm, Intel OpenCL).
  Job queue is file-based JSON over a bind-mounted volume. `docker-compose.gpu.yml`
  overlay provides NVIDIA Container Toolkit GPU reservation. Dockerfile adds
  hashcat, OpenCL packages, clinfo. `CrackMethod` enum gains `HASHCAT_GPU`,
  `HASHCAT_CPU`, `HASHCAT_HOST`. New preferences: `password_hashcat_enabled`,
  `password_hashcat_workload`. Health endpoint reports dual-path GPU info.
  Settings page gains GPU Acceleration status card. Container starts normally
  with no GPU present — graceful degradation to CPU/john fallback.
  Apple Silicon Macs: Metal backend detection, unified memory estimation,
  Rosetta 2 binary guard, hashcat >= 6.2.0 version gate, thermal-safe
  workload profile (-w 2). macOS Intel discrete GPUs (Radeon Pro) supported
  via OpenCL.

**v0.10.0** — In-app help wiki & contextual help system. 19 markdown articles
  in `docs/help/` rendered via mistune at `GET /api/help/article/{slug}`.
  Searchable via `GET /api/help/search?q=`. Help page (`/help.html`) with sidebar
  TOC, search, hash-based navigation. Contextual "?" icons via `data-help`
  attributes + `static/js/help-link.js`. Nav gains "Help" link (all roles, no auth).
  Help API endpoints are public. CSS: help-layout classes in markflow.css.

**v0.10.1** — Apple Silicon Metal support for GPU hashcat worker.
  `tools/markflow-hashcat-worker.py` gains macOS detection: Apple Silicon
  (M1/M2/M3/M4) via Metal backend, Intel Mac discrete GPU via OpenCL.
  Rosetta 2 binary warning prevents silent Metal loss. hashcat version
  gated at >= 6.2.0 for Metal. Unified memory estimation (~75% of system
  RAM) replaces VRAM reporting on Apple Silicon. Thermal-safe workload
  profile (-w 2, not -w 3) prevents throttling on fanless Macs.
  `core/gpu_detector.py` recognizes vendor=apple/backend=Metal in worker
  capabilities. Settings GPU status card updated for Apple display.

**v0.11.0** — Intelligent auto-conversion engine. When the lifecycle
  scanner finds new/modified files, the engine decides whether, when,
  and how aggressively to convert them. Three modes: immediate (same
  scan cycle), queued (background task), scheduled (time-window only).
  Dynamic worker scaling and batch sizing based on real-time CPU/memory
  load + historical hourly averages. `core/auto_converter.py` (decision
  engine), `core/auto_metrics_aggregator.py` (hourly rollup from
  system_metrics into auto_metrics table). Two new SQLite tables:
  `auto_metrics` (hourly aggregated system metrics for pattern learning),
  `auto_conversion_runs` (decision/execution audit log). 9 new preferences
  (auto_convert_mode, workers, batch_size, schedule_windows,
  decision_log_level, metrics_retention_days, business_hours_start/end,
  conservative_factor). `BulkJob` gains `max_files` parameter for batch
  capping. `bulk_jobs` gains `auto_triggered` column. APScheduler gains
  hourly aggregation job (:05 past each hour) and 15-min deferred
  conversion runner. Status page gains mode override card (ephemeral,
  resets on container restart). Settings page gains Auto-Conversion
  section. API: GET/POST/DELETE /api/auto-convert/override,
  GET /api/auto-convert/status, /history, /metrics.

**v0.12.0** — Universal format support, unified scanning & folder drop UI.
  10 new format handlers: RTF (`rtf_handler.py`, control-word parser with font
  mapping), HTML/HTM (`html_handler.py`, BeautifulSoup + CSS font extraction),
  ODT/ODS/ODP (`odt_handler.py`, `ods_handler.py`, `odp_handler.py` via odfpy),
  TXT/LOG (`txt_handler.py`, encoding detection + heading heuristics),
  XML (`xml_handler.py`, DOM traversal + element extraction),
  EPUB (`epub_handler.py`, ebooklib chapter structure preservation),
  EML/MSG (`eml_handler.py`, RFC 5322 + Outlook OLE via olefile),
  Adobe unified handler (`adobe_handler.py`, PSD/AI/INDD/AEP/PRPROJ/XD
  metadata extraction via exiftool). Total supported extensions: 26 across
  16 handlers. Bulk scanner unified — no separate Adobe/convertible split;
  all formats go through the same scanning pipeline with single-pass
  extension lookup against the format registry. Font recognition added to
  `extract_styles()` across handlers for Tier 2 reconstruction fidelity.
  Convert page (`index.html`) gains folder drop: drag-and-drop entire
  directories, auto-scans for valid formats, queues matching files for
  conversion. `formats/__init__.py` imports all new handlers at module load.
  `core/bulk_scanner.py` refactored to use `list_supported_extensions()`
  instead of hardcoded extension sets. `core/converter.py` and
  `core/bulk_worker.py` updated for new handler lookup path.

**v0.12.1** — Data format handlers + recursive email attachment conversion.
  Three new handlers: `json_handler.py` (JSON with summary + structure outline +
  secret redaction), `yaml_handler.py` (YAML/YML with multi-document support,
  comments preservation in source block), `ini_handler.py` (INI/CFG/CONF/properties
  with configparser + line-by-line fallback; `.conf` without sections treated as
  plain text). All three produce Summary + Structure + Source markdown layout.
  Secret value redaction (password, token, api_key, credential, auth key patterns).
  EmlHandler upgraded with recursive attachment conversion — attachments with
  registered handlers are converted and embedded inline under `## Attachments`.
  Depth-limited to 3 for nested emails. Non-fatal failures. MSG attachments
  supported via olefile stream traversal. 7 new extensions registered:
  `.json`, `.yaml`, `.yml`, `.ini`, `.cfg`, `.conf`, `.properties`.
  Total supported extensions: 33 across 19 handlers. Convert page and folder
  drop UI updated for new extensions.

**v0.12.2** — Size-based log rotation + settings download loop fix.
  Replaced `TimedRotatingFileHandler` with `RotatingFileHandler` (50 MB main,
  100 MB debug, configurable via `LOG_MAX_SIZE_MB` / `DEBUG_LOG_MAX_SIZE_MB`).
  Log download endpoint gets size guard (HTTP 413 for files >500 MB) and
  explicit `Content-Length` header to prevent browser download restart loops.

**v0.12.3** — Compressed file scanning, archive extraction, file tracking.
  New `ArchiveHandler` for ZIP, TAR, TAR.GZ, 7z, RAR, CAB, ISO. Recursive
  extraction and conversion of inner documents (depth limit 20). Archive
  summary markdown per file. Zip-bomb protection (`core/archive_safety.py`):
  ratio check, total size cap, entry count cap, quine detection. Compound
  extension support in format registry (`_get_compound_extension()`) and
  bulk scanner (`_get_effective_extension()`). New `archive_members` DB table.
  Dependencies: py7zr, rarfile, pycdlib, cabextract, unrar-free, p7zip-full.
  Password file at `config/archive_passwords.txt`. 12 new extensions registered.
  Total supported extensions: 45 across 20 handlers.

**v0.12.4** — Archive password writeback and session-level reuse.
  Successful archive passwords saved back to `archive_passwords.txt` and
  cached in-memory for the process lifetime. Found passwords tried first
  on subsequent archives. Thread-safe via lock.

**v0.12.5** — Full password cracking cascade for encrypted archives.
  Archive handler now mirrors the PDF/Office password handler cascade:
  known passwords, dictionary attack (common.txt + mutations), brute-force.
  Respects user preferences for charset, max length, timeout. Settings read
  sync-safely via direct sqlite3 connection.

**v0.12.6** — Brute-force charset fixed to all printable characters as default
  for both archive and PDF/Office crackers. Fallback charset updated.

**v0.12.7** — Full ASCII charset (0x01-0x7F) including control characters.
  New `all_ascii` charset option in Settings UI. Default for both archive
  and PDF/Office brute-force. Encrypted ZIP, 7z, and RAR archives —
  including nested ones — get the full cracking cascade at every depth.

**v0.12.8** — Progress tracking and ETA for scan and bulk conversion jobs.
  New `core/progress_tracker.py`: `RollingWindowETA` (last 100 items),
  `ProgressSnapshot`, `format_eta()`, `estimate_single_file_eta()`.
  Concurrent fast-walk counter in `bulk_scanner.py` via `asyncio.create_task`
  — scan starts immediately, file count arrives in parallel (no blocking).
  Bulk worker writes ETA to DB every 2s and emits `progress_update` SSE
  events with `eta_human`, `files_per_second`, `percent`. All job status
  API endpoints (`GET /api/bulk/jobs/{id}`, active jobs) return `progress`
  block. DB: added `eta_seconds`, `files_per_second`, `eta_updated_at`,
  `total_files_counted`, `count_status` columns to `scan_runs`, `bulk_jobs`,
  `conversion_history`. UI: ETA display and speed indicator on bulk page,
  scan progress shows "X of Y files" with streaming count.

**v0.12.9** — Startup crash fix, log noise suppression, Docker build optimization (2026-03-30).
**Bugfixes:**
- Fixed: `NameError: name 'structlog' is not defined` in `database.py` — missing
  `import structlog` caused `cleanup_orphaned_jobs()` to crash on every startup,
  putting the markflow container in a restart loop (exit code 3).
- Suppressed pdfminer debug/info logging — pdfminer (used internally by pdfplumber)
  emits thousands of per-token debug messages during PDF extraction. A single bulk job
  was inflating the debug log to 500+ MB. All `pdfminer.*` loggers now set to WARNING
  in `configure_logging()`, matching existing pattern for noisy third-party libraries.
**Infrastructure:**
- Split Dockerfile into `Dockerfile.base` (system deps, ~25-30 min on HDD) and
  `Dockerfile` (pip + code copy, ~3-5 min). Daily rebuilds skip the heavy apt layer.
- Added deployment scripts for Windows work machine: `build-base.ps1` (one-time base
  image builder), `refresh-markflow.ps1` (quick code-only rebuild), `reset-markflow.ps1`
  and `pull-logs.ps1` (PowerShell equivalents of the Proxmox bash scripts).
- Updated reset scripts (both Proxmox and Windows) to preserve `markflow-base:latest`
  during Docker prune, auto-building it if missing.

**v0.12.10** — MCP server fixes, multi-machine Docker support, settings UI improvements (2026-03-30).
**Bugfixes:**
- Fixed: MCP server crash loop — `FastMCP.run()` does not accept `host` or `port` kwargs.
  First attempted kwargs (TypeError crash), then UVICORN env vars (ignored). Final fix:
  `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)` — bypass `mcp.run()` entirely.
- Fixed: MCP info panel showed `http://172.20.0.3:8001/mcp` (Docker-internal IP, wrong
  path). Replaced `socket.gethostbyname()` with hardcoded `localhost`, `/mcp` with `/sse`.
- Fixed: MCP health check 404 — `FastMCP.sse_app()` has no `/health` route. Added
  Starlette `Route("/health")` to the SSE app before passing to uvicorn.
**Features:**
- Multi-machine Docker support — `docker-compose.yml` volume paths now use `${SOURCE_DIR}`,
  `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}` from `.env` (gitignored). Same compose file
  works on Windows workstation and MacBook VM without edits. `.env.example` template added.
- MCP settings panel: replaced generic setup instructions with connection methods for
  Claude Code, Claude Desktop, and Claude.ai (web with ngrok tunnel).
- "Generate Config for Claude Desktop" button — merges markflow MCP entry into user's
  existing `claude_desktop_config.json` non-destructively (client-side JS, no backend).
- PowerShell deployment scripts (`reset-markflow.ps1`, `refresh-markflow.ps1`) gain `-GPU`
  switch to include `docker-compose.gpu.yml` override.
- Developer Mode checkbox at top of Settings page — toggles both `log_level` and
  `auto_convert_decision_log_level` between `developer` and `normal`. Syncs bidirectionally
  with the log level dropdown.
**Default preference changes (fresh deployments):**
- `auto_convert_mode`: `off` → `immediate` (scan + convert automatically)
- `auto_convert_workers`: `auto` → `10`
- `worker_count`: `4` → `10`
- `max_concurrent_conversions`: `3` → `10`
- `ocr_confidence_threshold`: `80` → `70`
- `max_output_path_length`: `240` → `250`
- `scanner_interval_minutes`: `15` → `30`
- `collision_strategy`: `rename` (unchanged, confirmed as desired default)
- `bulk_active_files_visible`: `true` (unchanged, confirmed)
- `password_brute_force_enabled`: `false` → `true`
- `password_brute_force_max_length`: `6` → `8`
- `password_brute_force_charset`: `alphanumeric` → `all_ascii`
- Auto-conversion worker select gains "10" option in UI.

**v0.12.1** — Bugfix + Stability Patch (2026-03-29).
**Bugfixes (from log analysis):**
- Fixed: structlog double `event` argument in lifecycle_scanner (two instances)
- Fixed: SQLite "database is locked" — all direct `aiosqlite.connect()` calls now use
  `get_db()` or set `PRAGMA busy_timeout=10000`; retry wrapper on metrics INSERT
- Fixed: collect_metrics interval increased from 60s to 120s with `misfire_grace_time=60`;
  added 30s timeout wrapper via `asyncio.wait_for`
- Fixed: DB compaction always deferred — removed `scan_running` guard, compaction now runs
  concurrently with scans (safe in WAL mode)
- Fixed: MCP server unreachable — health check now uses `MCP_HOST` env var (default
  `markflow-mcp` Docker service name) instead of hardcoded `localhost`
**Stability improvements:**
- Added: Startup orphan job recovery — auto-cancels stuck bulk_jobs and interrupts
  stuck scan_runs on container start (before scheduler starts)
- Fixed: Stop banner CSS — `.stop-banner[hidden]` override prevents `display:flex`
  from overriding the HTML `hidden` attribute; JS uses `style.display` toggle
- Note: Lifecycle scanner progress tracking + ETA already existed (v0.12.8)
- Added: Mount-readiness guard — bulk scanner and lifecycle scanner verify source mount
  is populated before scanning. Empty mountpoints (SMB not connected) abort gracefully.
- Added: Static file `Cache-Control: no-cache, must-revalidate` headers via middleware
- Added: `DEFAULT_LOG_LEVEL` env var for container-start log level override
