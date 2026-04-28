# UX Overhaul: Search-as-Home, Activity Dashboard, Avatar-Centric Settings

| | |
|---|---|
| **Status** | Spec — ready for plan |
| **Date** | 2026-04-28 |
| **Author** | Xerxes Shelley + Claude (brainstorming session) |
| **Scope** | Front-end redesign: IA, visual identity, home page, operator dashboard, settings shell |
| **Out of scope** | Convert page redesign · backend behavior · UnionCore integration · responsive/mobile · empty-state polish |

## V1 expectation

This is **V1**. The decisions below are the deliberate starting point — not the final answer. Once real IBEW Local 46 staff and operators use it day-to-day, expect tweaks: spacing that reads cramped at certain monitor sizes, density-mode preferences that don't match how people actually scan, CSV columns that need adjustment as provider pricing evolves. Bake the willingness-to-iterate into the implementation: feature flags around new pages, simple paths to roll back individual decisions, instrumentation on layout-mode selection and density-toggle usage so we know what people actually pick.

---

## Why this exists

MarkFlow's UI grew organically across 11 phases. Symptoms:

- 30+ static HTML pages with no consistent IA or visual language
- Settings page has 15+ inline sections
- The current `index.html` is the Convert page, but converting is rarely the user's *daily* verb — finding documents is
- "Pipeline" is engineering jargon that doesn't tell an operator what the page does
- Premium-grade visual polish (Apple, Stripe, Airbnb references the user provided) hasn't been applied
- Settings live on shared workstations but don't roam with the user across machines

The autonomous "deploy and forget" pipeline is mature (v0.34.1). The UI hasn't caught up to the product narrative. This spec catches it up.

## Goals

- **Search-as-home** — the daily verb is finding documents, so the home page is search
- **Premium visual identity** — display typography, gradient color discipline, generous whitespace, soft shadows, pill buttons
- **Role-aware IA** — `member` sees the minimum; `admin`/`operator` sees the full operator dashboard
- **Avatar as the unified settings entry** — `Settings` link removed from top nav
- **Power-user gate** — Markdown / AI-integration actions hidden by default, opt-in via toggle
- **Portable preferences** — settings follow the user across workstations
- **Decomposed Settings** — each section opens to its own scoped sidebar + form (no more single 15-section page)

## Non-goals (v1)

- Convert page redesign (separate cycle once it stops being the front door)
- Detailed mocks for first-run welcome step + pin-folders step (separate sub-spec)
- Mobile / narrow-viewport behavior (current MarkFlow is desktop-first)
- Empty states for first-time ingest, no-results, no-flagged-files
- Migration of existing data — pure presentation layer
- Backend changes for UnionCore (consumed via JWT only)

## V1 expectations callouts (operational)

- All new pages ship behind a `ENABLE_NEW_UX` feature flag
- Layout-mode selection, density-toggle changes, advanced-toggle usage all emit telemetry events
- Each detail-page section ships independently — phasing in section §11

---

## 1. Information Architecture (locked)

### Top nav

| Role | Nav |
|------|-----|
| `member` | Logo · Search · Convert · *layout-icon* · *avatar* |
| `operator` / `admin` | Logo · Search · **Activity** · Convert · *layout-icon* · *avatar* |

- Logo includes a dev-only `v0.34.1-dev` chip (CSS class `.ver-chip`, hidden in prod via build-time CSS or `display: none` on a `body[data-env="prod"]` selector).
- The `Settings` link is **removed** from the top nav. Settings are reached via the avatar menu only.
- "Pipeline" → renamed to **Activity**. The route remains `/pipeline` initially; `/activity` is the canonical URL going forward, with `/pipeline` as a 301 alias for one release.
- `Activity` is hidden from `member` nav entirely (not just disabled).

### Page hierarchy

```
/                                Search (home, all roles)
/activity                        Activity dashboard (admin, operator)
/convert                         Convert utility (all roles, demoted from front door)
/settings                        Settings overview (card grid, all roles, role-gated content)
/settings/<section>              Detail pages (scoped sidebar + form)
/settings/ai-providers/cost      Cost cap & alerts (deeper drill, own scoped sidebar)
```

---

## 2. Visual Design System

### Type

- Display headlines: SF Pro Display / Inter / system-ui sans, **2.0–2.6rem**, **-0.025em letter-spacing**, **700 weight**, **1.05 line-height**
- Subtitles: 0.94–1rem, color `#5a5a5a`, max-width `60ch`
- Body: system-ui, 0.86–0.92rem, line-height 1.45–1.55
- Snippet text inside document cards: serif (`Iowan Old Style, Charter, Cambria, Georgia`), 0.65rem, color `#2a2a2a` — gives the "this is a document tool" feel
- Field labels: 0.72rem, **700**, **uppercase**, **0.07em letter-spacing**, color `#6a6a6a`

### Color

- **Primary accent**: `#5b3df5` (purple). Used for primary buttons, active states, hover highlights, the avatar gradient, the pipeline progress fills, and accent links.
- **Secondary accent**: `#9d7bff` (lighter purple, gradients only — paired with primary)
- **Format-coded gradients** for document type bands:
  - PDF: `#ff6b6b → #c92a2a` (red)
  - DOCX: `#4dabf7 → #1864ab` (blue)
  - PPTX: `#ffa94d → #e8590c` (orange)
  - XLSX: `#51cf66 → #2b8a3e` (green)
  - EML: `#cc5de8 → #862e9c` (purple-magenta)
  - PSD: `#5c7cfa → #364fc7` (indigo)
  - MP4: `#22b8cf → #0b7285` (teal)
  - MD: `#0a0a0a → #495057` (charcoal)
- **Status colors**: success `#0e7c5a` on `#eafff5`, warning `#a36a00` on `#fff5e0`, error `#c92a2a` on `#ffe7e7`
- **Surfaces**: white `#fff`, soft `#fafafa`, paper-card `#fefefb`, border `#ececec`

### Spacing & shape

- Card radius: `14px` (large) / `10–12px` (medium) / `8px` (small) / `999px` (pills)
- Card shadow: `0 1px 0 rgba(0,0,0,0.05), 0 24px 48px -24px rgba(0,0,0,0.18)`
- Borders: `1px solid #ececec` (light), `1.5px solid #5b3df5` for selected/recommended
- Page body padding: `2.2rem 2rem 2.6rem` (default), reduced to `1.6rem 2rem` on dense pages
- Section spacing: `2.2rem` between major sections, `1.4rem` between sub-sections

### Pills (buttons)

- Primary: `#5b3df5` fill, white text, weight 600, padding `0.55–0.7rem 1.05–1.4rem`, radius 999px
- Outline: white fill, `#5b3df5` text, `1.5px` purple border
- Ghost: transparent fill, `#5b3df5` text, no border, smaller padding
- Sizes: default / `.sm` (0.36–0.4rem padding, 0.78–0.84rem font)
- Danger variant: `#c92a2a` text on white with light red border

### Status pulse

`<span class="pulse"><span class="pulse-dot"></span> All systems running · 12,847 indexed</span>`

`#eafff5` background with `#0e7c5a` text, 7px green dot with 4px green-alpha glow.

---

## 3. Search-as-Home

### Three layout modes (locked)

| Mode | What's on the page |
|------|---------------------|
| **Maximal** | Status pulse · headline · search bar · density toggle · *Pinned folders* · *From watched folders* · *Most accessed this week* · *Flagged for review* · *Browse by topic* |
| **Recent** | Status pulse · headline · search bar · *Recent searches* (chips with X-to-remove + Clear history) · *Recently opened* (cards) |
| **Minimal** | Status pulse · brand headline (`MarkFlow.`) + one-line subtitle · large centered search bar |

### Onboarding (first-run)

- **Step 1**: Welcome — *"What do you want to find on the K Drive?"* (mock pending)
- **Step 2**: Layout picker — three preview cards with mini-wireframes and "Best for…" examples (Friday catch-up / Tuesday at 10am / mid-meeting lookup). **Minimal is recommended** (purple ring) and the skip-fallback. Skip ("I'll pick later") lands user on Minimal.
- **Step 3**: Pin your first folders — drag-pickable list of indexed folders, mark 3–4 favorites (mock pending)

### Switching layout

- **`⌘\`** keyboard shortcut cycles modes anywhere in the app
- **Layout icon** in nav (4-square SVG, `34px` button next to avatar) opens a popover chooser:
  - Three rows, each with mini-visual + name + description + checkmark (current mode)
  - Footer: "Layout: **Recent**" + "More display options →"
- Single-click cycles by default; click-and-hold or right-click opens the popover chooser

### Persistence

- Layout mode + density + snippet length + advanced visibility + recent search history all stored against user identity (see §10)

### Search UI

- Airbnb-style segmented bar: **Looking for** · **Format** · **When** · circular search button
- Below the bar: chip row of one-click filters ("Last 7 days", "PDFs only", "Office docs", "Has AI summary", "In /folder", "+ More filters")
- Search results page (separate spec — current behavior preserved for v1; visual polish only)

---

## 4. Document Card (reusable component)

The document card is used on the home page, expanded section views, folder browse, and inside hover/preview surfaces. It's the most-rendered atom in the redesign.

### Anatomy

```
┌─────────────┐
│  GRADIENT   │  ← top band (32% of card height)
│  [PDF pill] │     format-coded color, format label inset
├─────────────┤
│ Title       │
│             │
│ First three │  ← serif snippet body on paper background
│ lines of    │     fades to white at bottom
│ converted… │
└─────────────┘
```

- Aspect ratio `0.78` (slightly taller than wide — book/document feel)
- Border `1px solid #e8e6df`, paper background `#fefefb`
- Shadow `0 1px 0 rgba(0,0,0,0.04), 0 8px 16px -10px rgba(0,0,0,0.1)`
- Heart icon top-right (`24px` round) for fav state
- **No metadata under the card** — title is the snippet header; everything else is in hover/right-click

### Density modes

| Mode | Cards/row | Snippet length | Items-per-page options |
|------|-----------|----------------|------------------------|
| Cards | 6 | full | 12 / 24 / 48 / 96 |
| Compact | 8 | abbreviated | 24 / 48 / 96 / 192 |
| List | 1 (linear) | none — title + path + size + timestamp + fav | 100 / 250 / 500 / 1000 / All |

In List mode, the gradient band collapses to a `24×24px` icon at the start of each row.

### Hover preview

A `340px` floating popover anchored to the card's right side (or top if the card is in the rightmost column). Triggered after `400ms` hover delay (configurable in v1.1; locked to 400ms in v1).

Contents:
- Full title + full path (purple, monospace)
- Meta grid: Format · Modified · Indexed · Opens · Status
- AI Summary block (purple-bordered, soft gray background, 2–4 sentence summary)
- Action buttons: Preview (primary) · Download · Go to folder · `…` (more)

### Right-click context menu

`240px` wide, grouped:

- **View** — Preview file (`Space`) · Open original (`⌘O`) · Go to containing folder (`⌘↑`)
- **Export** — Download original · Copy file path
- **AI** — Summarize with AI · Ask a question about this file
- (separator)
- Pin to favorites · Flag for review *(red on hover)*
- (heavy separator)
- **Advanced ▾** *(power-user gate — see §9)*
  - Download as Markdown · Copy Markdown to clipboard · View raw Markdown source

When multiple cards are selected, the context menu pivots to bulk actions: "Download 3 selected", "Tag 3 selected", "Flag 3 selected".

### Folder browse (after "Go to containing folder")

- Breadcrumb: `Home / local-46 / contracts` (current folder is plain text, ancestors are purple links)
- Folder header: large icon + path + stats line ("428 documents · 3 added today · last scanned 4 min ago")
- Right-side: density toggle, Pin folder, Download all (zip)
- Hover-checkbox selection on cards (always visible when selected)
- **Bulk-action bar** appears when items selected — purple background, white text, count badge, actions: Download selected (solid white) · Preview · Copy paths · Tag … · Flag for review · Clear

---

## 5. Activity (admin/operator only)

The dashboard formerly known as "Pipeline." Members never see it.

### Sections (top to bottom)

1. **Header** — status pulse (extended: `All systems running · 12,847 indexed · pipeline at 62%`), `Activity.` headline, K-drive subtitle ("The conversion engine for the K Drive at a glance")
2. **Top tiles** — 4 across: Files processed today · In queue · Active jobs · Last error
3. **24h throughput sparkline** — single chart with peak/dip annotations
4. **Running now** — active bulk jobs as cards with progress bar, file counts, ETA, pause/cancel/open controls
5. **Queues & recent activity** — 4-card row: Recently converted · Needs OCR · Awaiting AI summary · Recently failed (each clickable to expand)
6. **Recent jobs** — last 7 days table: name + crumb + status (running/done/paused/error) + ETA-or-time + counts + action
7. **Pipeline controls** — 4 cards: Pipeline running (toggle) · Run scan now · Logs & diagnostics · Database health

### Behavior

- "Pause pipeline" toggle persists; matches the toggle in Settings → Pipeline & lifecycle
- Live-updating throughput sparkline (SSE; reuse existing `/api/pipeline/throughput` if available, or new endpoint)
- "Run scan now" → triggers an immediate scan, navigates to a live progress view inline
- Tile values pull from `/api/activity/summary` (new endpoint or repurposed from existing status endpoints)
- Pause-with-duration dialog (already shipped v0.30.0) reused

---

## 6. Avatar Menu (the new settings entry)

`300px` wide popover anchored to the avatar in the top-right.

### Header

- Avatar (38px gradient circle) · Name · Role pill (`member` blue, `operator` / `admin` amber) · scope ("IBEW Local 46")

### Personal section (everyone)

- Profile
- Display preferences (→ §9 power gate, density, snippet length, layout)
- Pinned folders & topics
- Notifications
- API keys *(admin/operator only — gated)*

### System section (admin/operator only)

Header: **System** with right-aligned `Admin only` amber gate badge.

- Storage & mounts
- Pipeline & lifecycle
- AI providers
- Account & auth
- Database health
- Log management

### Footer

- "All settings →" — jumps to the card-grid overview (§7)
- (separator)
- **Help**: Help & docs · Keyboard shortcuts (`?`) · Report a bug
- (separator)
- Sign out *(red text)*
- Build info strip: `v0.34.1-dev · main · build d15ddb3 · 2026-04-28` (monospace, `0.7rem`, `#888`)

---

## 7. Settings Detail Pattern

### Overview page (`/settings`)

Card grid (2 columns × N rows). Each card: icon + section name + one-line description. Hover lifts the card and reveals a `→` arrow. Click → navigates to that section's detail page.

Cards (admin sees all; member sees only their accessible ones):

- Storage (admin)
- Pipeline & lifecycle (admin)
- AI providers (admin)
- Account & auth (admin)
- Notifications (admin + member preferences)
- Database health (admin)
- Log management (admin)
- Display (member preferences)
- Pinned folders (member preferences)
- Profile (member)

### Detail page (`/settings/<section>`)

Two-column layout:

- **Left**: scoped sidebar — only this section's sub-sections (`200–240px` wide)
- **Right**: form for the active sub-section

Header: breadcrumb (`← All settings`), small section icon, headline, one-line subtitle.

Footer: save bar — `Save changes` (primary) · contextual actions ("Test connection", "Run scan now") · `Discard` (ghost).

### Sub-section sidebars (locked)

| Section | Sub-sections |
|---------|--------------|
| Storage & mounts | Mounts · Output paths · Cloud prefetch · Credentials · Write guard · Sync & verification |
| Pipeline & lifecycle | Scan schedule · Lifecycle & retention · Trash & cleanup · Stale data check · Pipeline watchdog · Pause & resume *(live badge)* |
| AI providers | Active provider chain · Anthropic · OpenAI · Image analysis routing · Vector indexing · Cost cap & alerts *(drill-down — own page)* |
| Account & auth | Identity (UnionCore) · JWT validation · Role mapping · Sessions & timeout · Audit log |
| Database health | Connection pool · Backups · Maintenance window · Migrations · Integrity check |
| Log management | Levels per subsystem · Retention & rotation · Live viewer · Export & archive |
| Notifications | Channels · Trigger rules · Quiet hours · Test send |

### Form components

- **Text input** — `padding: 0.62rem 0.85rem`, `border-radius: 10px`, `background: #fafafa`, `border: 1px solid #e0e0e0`. Read-only variant: `background: #f0f0f0`, color `#5a5a5a`
- **Segmented control** — pill-shaped, gray track, white selected pill with subtle shadow
- **Toggle** — `36×20px` rounded rect, `#5b3df5` on / `#e0e0e0` off, white knob with subtle shadow
- **Day-of-week pills** — `#5b3df5` selected, white unselected with gray border
- **Mini tables** — soft gray background, head row in uppercase tiny gray, 5–7 row preview

---

## 8. Cost Cap & Alerts (drill-down sub-page)

Reached from `Settings → AI providers → Cost cap & alerts`. **Has its own scoped sidebar** — the AI providers sidebar is replaced (not nested) by the cost sidebar to keep one level of navigation visible.

### Sidebar groups

```
COST
  Overview                       (active by default)

RATES BY PROVIDER
  Anthropic                      (nested — only shown if active)
  OpenAI                         (nested — only shown if active)
  …                              (one entry per active provider)

DATA
  Sources & CSV import
  Spend history

NOTIFY
  Alerts & thresholds

[external link]
  CSV format reference ↗         → docs/help/cost-rates-csv-format.md
```

### Dynamic per-provider behavior

The whole page **re-shapes based on active provider count**:

- **Single provider** (e.g., only Anthropic active):
  - Top tiles: 2-up grid (Spend today, Spend this month) — drops the "Active providers" tile
  - Spend breakdown table titled "Anthropic spend by model" — no totals row, no provider column, no comparison chart legend
  - Sidebar's "Rates by provider" group shrinks to one entry
  - Daily-spend chart is single-color
- **Multiple providers**:
  - Top tiles: 3-up (Today, Month, Active providers count + names)
  - Spend breakdown table with provider column, totals row in bold separated by purple line
  - Stacked daily-spend chart with color-coded legend
  - Sidebar lists each provider as a nested rate destination

### CSV import

- Drag-and-drop area (purple gradient backdrop, dashed lavender border, `48px` cloud-upload icon)
- "Choose file" + "Paste from clipboard" pill buttons
- Below: live format preview in a dark code block (`#1a1a1a` background, `#e6e6e6` text, monospace, color-coded per row type)
- Help callout linking to the format reference
- Per-provider source dropdown: CSV import / Manual entry / Auto-fetch from API (independent — each provider chooses its source)

### CSV format

Columns:

| Column | Required | Description |
|--------|----------|-------------|
| `provider` | Y | lowercase: `anthropic`, `openai`, `local` |
| `model` | Y | model ID exactly as the provider returns it |
| `input_per_1m` | Y | USD per 1M input tokens |
| `output_per_1m` | Y | USD per 1M output tokens |
| `cache_write_per_1m` | N | for prompt-cache providers |
| `cache_read_per_1m` | N | for prompt-cache providers |
| `vision_per_image` | N | per-image vision rate |
| `batch_discount_pct` | N | e.g., `50` for Anthropic batch API |
| `effective_date` | N | ISO date — supports historical rates |

Empty cells mean *"doesn't apply"*, not zero. UTF-8 only.

### Help file

Create `docs/help/cost-rates-csv-format.md` with: required columns, optional columns, the canonical example block, notes (UTF-8 encoding, historical rates via `effective_date`, "providers change pricing without notice — verify").

---

## 9. Power-user Gate

A single Settings → Display toggle gates "MarkFlow / AI integration actions" across the app:

- **Off** (default for `member`): Markdown-related and integration actions hide behind an `Advanced ▾` expander in context menus, hover popovers, and detail pages. The expander is a single muted line at the bottom of the menu.
- **On** (default for `operator` / `admin`): Same actions appear inline in a de-emphasized gray block at the bottom of the menu (no extra click).

Items currently gated:
- Download as Markdown
- Copy Markdown to clipboard
- View raw Markdown source

Items to add to the gate as we build them:
- Raw API response inspection
- Share-link generation (vs. Download)
- Copy content hash / SHA-256
- View AI Assist transcript

The gate principle: *if it requires the user to know something about how MarkFlow stores or exposes data internally, it lives behind this toggle.*

---

## 10. User Preferences (portable)

All user-scoped preferences are stored against the user's identity (UnionCore subject claim) — **not** the workstation. When the user signs in on a different machine, the preferences come with them.

### Preferences in scope

- Layout mode (Maximal / Recent / Minimal)
- Density mode (Cards / Compact / List)
- Snippet length (Short / Medium / Long)
- Show file thumbnails (boolean)
- Power-user gate toggle (boolean)
- Track recent searches (boolean — default ON)
- Recent search history (capped to last 50 queries)
- Pinned folders (list)
- Pinned topics (list)
- Notifications preferences
- Items-per-page per density mode
- API keys (admin/operator)

### Storage

- Server-side: persisted in the existing `core/db/` package, new table `user_preferences` keyed by `user_id` (UnionCore sub claim)
- Client-side: `localStorage` mirror for fast first paint; reconciled against server on login
- Sync: on preference change, debounced 500ms, then `PUT /api/preferences/<key>`

### Privacy

- "Track recent searches" toggle off → search history is not logged server-side; localStorage cache also cleared
- "Clear history" link in Recent layout → wipes the cap-50 history server- and client-side

---

## 11. Role Binding via UnionCore

- Roles defined upstream in UnionCore. MarkFlow consumes via JWT.
- Role hierarchy: `member` < `operator` < `admin`
- All visibility gates check the role claim from the JWT (no local role config; UnionCore is source of truth)
- The local `JWT validation` settings page (Account & auth section) is **read-only** for issuer / audience / JWKS — UnionCore deployment owns those

### Gates summary (single source of truth for visibility)

| Surface | Gated by |
|---------|----------|
| `Activity` nav link | role ≥ `operator` |
| Avatar `System` section | role ≥ `operator` |
| Avatar Personal `API keys` | role ≥ `operator` |
| Settings overview cards (system) | role ≥ `operator` |
| Recently converted / Needs OCR / Awaiting AI summary / Recently failed (admin rows) | role ≥ `operator` |
| Power-user actions inline (vs. expander) | preference toggle (default off for member, on for operator/admin) |
| Re-auth required to change System settings | preference toggle in Account & auth (default ON for admin/operator); not applicable to member since member can't access System settings |

---

## 12. Implementation phasing

| Phase | Deliverable | Why first |
|-------|-------------|-----------|
| 1 | Visual design tokens (CSS vars), shared chrome (nav, avatar menu shell, layout-icon button, version chip) | Everything else depends on the tokens; nav is on every page |
| 2 | Search-as-home page replacement (the index) + three layout modes + density preferences + onboarding step 2 | Highest user-visible impact; isolates well from existing pages |
| 3 | Document card component + hover + right-click + folder browse | Reusable atom; unblocks home + later pages |
| 4 | IA shift — `Pipeline` → `Activity` rename, admin-only nav gating, settings link removal, avatar menu fully wired | One-time IA transition; should ship as a bundle so users don't see half-finished nav |
| 5 | Settings overview card grid + first detail page (Storage, since already designed) | Establishes the detail-page pattern |
| 6 | Remaining settings detail pages — Pipeline · AI providers · Account & auth · Notifications · Database health · Log management | Pattern is set; each can ship independently |
| 7 | Cost cap & alerts deep-dive sub-page + CSV import + help file | Deepest drill; can ship after AI providers detail page is live |
| 8 | First-run flow steps 1 & 3 (welcome + pin folders) | Onboarding completes once everything else is in place |
| 9 | Convert page redesign (separate sub-spec — out of scope for this spec) | Demoted from front door, can wait |

Each phase ships behind `ENABLE_NEW_UX` flag. Telemetry on layout-mode selection, density-toggle, advanced-toggle from phase 2 onward.

---

## 13. Preflight checklist

Run through before phase 1 starts; revisit at each phase boundary. Items missed here become production bugs.

### Setup (one-time, before phase 1)

- [ ] `ENABLE_NEW_UX` feature flag added — default `false` in prod, `true` in dev
- [ ] `static/css/design-tokens.css` — all §2 tokens declared as `--mf-*` CSS variables; existing `markflow.css` migrated to consume them incrementally
- [ ] `user_preferences` DB migration — JSON-valued, keyed by `user_id` (UnionCore `sub` claim); migration in `core/db/migrations/`
- [ ] UnionCore role claim parsed and exposed via `core/auth.py` request context — confirmed against staging UnionCore
- [ ] Telemetry event taxonomy agreed: at minimum `ui.layout_mode_selected`, `ui.density_toggle`, `ui.advanced_toggle`, `ui.hover_preview_shown`, `ui.context_menu_action` — emitted via existing `structlog` to a dedicated subsystem
- [ ] `/pipeline` → `/activity` 301 redirect added in `main.py`; old route slated for removal one release later
- [ ] Bundle size baseline measured for `static/markflow.css` + `static/app.js`; **20% growth budget** through V1
- [ ] Browser target matrix confirmed (Chrome 120+, Edge 120+, Firefox 120+; document any internal IE/older-Edge constraint)
- [ ] Mockup archive accessible at `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/` — index `.html` created linking all 16 mockups so devs/designers browse one URL

### Per-phase ship gate

Apply to phases 2 onward, each user-visible release:

- [ ] **Visual diff** — side-by-side against the archived mockup
- [ ] **Feature flag** — page renders old behavior with flag off, new with flag on; mid-session toggle works in both directions
- [ ] **Keyboard / a11y** — tab order, visible focus rings, ARIA labels on density toggle / layout icon / avatar menu / context menu
- [ ] **Color contrast** — primary text ≥ 4.5:1, large text ≥ 3:1, muted text on `#fafafa` re-checked
- [ ] **Empty + loading states** — what renders while data loads; what renders with no data
- [ ] **Telemetry events** firing in dev and visible in the log viewer
- [ ] **Manual smoke** — search a known query, open avatar menu, open Activity (admin only), drop a file on Convert

### Phase 5 specifically (settings detail + preferences)

- [ ] Preferences sync verified across two machines under same identity
- [ ] Track-recent-searches OFF path: server-side logs disabled, localStorage history cleared
- [ ] Re-auth gate triggers correctly when flipping system settings (5-min freshness)
- [ ] localStorage mirror reconciliation tested with conflicting writes (server wins)

### Pre-production cutover

- [ ] Version chip hidden / stripped for prod (`body[data-env="prod"] .ver-chip { display:none }` or build-time strip)
- [ ] `DEV_BYPASS_AUTH=false` confirmed in production `.env`
- [ ] Mockup archive `index.html` created and linked from this spec
- [ ] One-week telemetry review: which layout mode are people picking, are advanced-toggle users actually existing, hover-preview engagement rate
- [ ] Rollback procedure documented — flipping `ENABLE_NEW_UX` off restores prior UI without data loss
- [ ] `/pipeline` 301 alias removal scheduled for the release after rollout

---

## 14. Open questions / deferred to follow-up

- **Convert page redesign** — separate sub-spec once it's no longer the front door
- **First-run welcome step** — copy and visual ("What do you want to find on the K Drive?")
- **First-run pin-folders step** — drag-pickable indexed folders UI
- **Search results page polish** — current behavior preserved in v1; visual layer only
- **Mobile / narrow viewport** — current MarkFlow is desktop-first
- **Empty states** — first-run ingest, zero results, no flagged files
- **AI Assist chat panel** — natural-language search variant (option #3 from earlier exploration) — possible future home-page mode
- **Detailed Storage / Database / Log / Notifications form fields** — taxonomy locked; full form contents per sub-section to be detailed during phase 6 implementation
- **`⌘\` cycle vs nav-icon** — both shipping; usage telemetry will tell us if one becomes redundant
- **`hover preview delay`** — locked to 400ms in v1; may make configurable in v1.1 based on user feedback
- **Onboarding skip behavior** — currently lands user on Minimal; revisit if telemetry shows people are confused

---

## 15. References

- Brainstorming session artifacts: `.superpowers/brainstorm/118153-1777404285/content/` (gitignored — visual mockups). Key files:
  - `home-search-v3.html` — final home page
  - `card-interactions.html` — hover, right-click, folder view
  - `home-layout-modes.html` — three modes
  - `layout-onboarding.html` — first-run picker (step 2)
  - `avatar-menu.html` — avatar settings menu
  - `activity-page.html` — operator dashboard
  - `settings-detail-family.html` — Pipeline detail + taxonomies
  - `settings-three-details.html` — AI / Notifications / Auth detail pages
  - `cost-deep-dive.html` — cost sub-page + CSV import + help file
- Existing related specs: `docs/superpowers/specs/2026-04-21-universal-storage-manager-design.md` (Storage internals), `2026-04-05-vector-search-design.md` (vector indexing — relevant to AI providers section)
- User references provided as visual anchor: Apple iPhone landing, Stripe homepage, Airbnb homes browse
- Related memories: `~/.claude/projects/<this-project>/memory/MEMORY.md` — `project_ux_overhaul.md`, `project_ai_assist_provider.md`, `feedback_settings_toggle_pattern.md`, `feedback_timestamp_localization.md`

## 16. Mockup archival

Before this brainstorming session ends, the visual companion server's content directory should be archived. Recommended:

```bash
# Manual archival (until automated)
cp -r .superpowers/brainstorm/118153-1777404285/content \
      docs/superpowers/specs/2026-04-28-ux-overhaul-mockups
git add docs/superpowers/specs/2026-04-28-ux-overhaul-mockups
git commit -m "docs(ux-overhaul): archive brainstorm mockups for spec reference"
```

The mockups are HTML files served by the brainstorming visual companion. They render on their own without the companion server (the frame template injects styling — for archival, the frame template at `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/scripts/frame-template.html` may also need to be co-located, or the archived files inlined with the frame styles).
