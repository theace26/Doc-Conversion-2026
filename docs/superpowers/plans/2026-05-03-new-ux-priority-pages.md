# Plan: New-UX Page Audit + Build-Out

**Date:** 2026-05-03
**Status:** planned
**Target releases:** v0.39.0 hot-revert (today) + v0.40.0–v0.42.0 (multi-wave build-out)
**Spec/inventory:** `docs/new-ux-pages.md`
**Predecessor:** v0.39.0 shipped per-user UX dispatch + 5 new-UX pages.

---

## Goal

Audit every page in `static/*.html` against the new-UX surface, identify gaps and silent failures (BUG-033 class — JS references BEM classes that have no CSS), recommend consolidations where the new-UX information architecture lets us collapse redundant surfaces, and route the build-out into model-and-effort-tiered subagent dispatches so we ship the long tail of pages efficiently.

**Why a full audit:** v0.39.0 unblocked per-user UX dispatch but hard-coded route dispatch for several pages whose new-UX twins exist as HTML + JS but have no CSS, so users with `mf_use_new_ux=1` hit unstyled pages. The user reported the search-results regression first; the audit found the same pattern on `/status`, `/history`, `/flagged`, and `/storage`. This plan inventories the full surface so we don't keep playing whack-a-mole.

## Page inventory (50 HTML files)

The full list is the union of `static/*.html` (50 files as of 2026-05-03). Each row is categorized into one of five tiers.

### Top-nav structure (anchors operator navigation)

```
member  : Search (/) | Convert (/convert)
operator: Search (/) | Activity (/activity) | Convert (/convert)
admin   : same as operator
```

### Avatar menu structure (anchors ~80% of menu surface)

```
URLS_NEW (new UX):
  notifications → /settings/notifications
  storage       → /settings/storage
  pipeline      → /settings/pipeline
  ai            → /settings/ai-providers
  auth          → /settings/auth
  db            → /settings/db-health
  logs          → /log-mgmt
  log-viewer    → /log-viewer
  log-levels    → /log-levels
  all-settings  → /settings
  help          → /help
  display       → drawer (not a page)
  profile, pinned, api-keys, shortcuts, bug → "coming soon" toast

URLS_ORIGINAL (original UX):
  storage       → /storage.html
  pipeline      → /pipeline-files.html
  ai            → /providers.html
  db            → /db-health.html
  logs          → /log-management.html
  all-settings  → /settings
  help          → /help
```

### Tier A — silent-failure CSS gaps (urgent: BUG-033 class)

Pages that are server-dispatched in new UX but whose `mf-<page>__*` BEM classes have **no CSS definitions**. JS mounts the page; HTML structure is correct; every element is unstyled. Users see a wall of un-styled HTML. Same class of bug as BUG-033 (search-results, fixed in v0.39.0).

| Page | URL | Twin file | JS prefix | CSS state | Severity |
|------|-----|-----------|-----------|-----------|----------|
| Status (Active Jobs) | `/status` | `status-new.html` | `mf-status__*` | **0 selectors** | high |
| History | `/history` | `history-new.html` | `mf-hist__*` | **0 selectors** | high |
| Flagged | `/flagged` | `flagged-new.html` | `mf-fl__*` | **0 selectors** | high |
| Storage (top-level) | `/storage` | `storage-new.html` | `mf-st__*` | **0 selectors** (CSS uses `mf-stg__*` for the *settings* sub-page, not storage-new) | high |
| Help | `/help` | `help-new.html` | wiki-renderer-driven | **mf-help: 0 selectors** | medium (renderer may inject styles) — verify |
| Search home | `/` | `index-new.html` (search-home component) | likely `mf-home__*` | **mf-search-home: 0 selectors** | medium — verify with browser load |

**Recommendation for v0.39.0:** revert the dispatch for the 4 high-severity pages (`/status`, `/history`, `/flagged`, `/storage`) — drop them out of `serve_ux_page` and serve original-UX directly until their CSS lands in v0.40.0. The dispatch infrastructure stays; only these specific routes revert. One-line edit per route.

**Why revert vs. ship + fix-forward:** building the CSS for 4 pages right now would add another 1000+ lines and another full release-discipline pass. Reverting routes is a 4-line change that ships the headline v0.39.0 feature (per-user dispatch) with no broken surfaces.

### Tier B — original-UX pages with no new-UX twin

Need full new-UX builds. Listed in implementation priority order (operator value × effort).

| # | Page | URL | Original file | Suggested new path | Suggested model | Effort | Notes |
|---|------|-----|---------------|--------------------|-----------------|--------|-------|
| 1 | Active Jobs (after Tier-A revert) | `/status` | `status.html` | `/status` (or merge into `/operations`, see Tier C) | Sonnet | medium | Polls 4 endpoints; real-time op cards w/ progress + cancel. |
| 2 | History (after Tier-A revert) | `/history` | `history.html` | `/history` | Haiku | medium | List + pagination + filter; mostly mechanical from template. |
| 3 | Flagged (after Tier-A revert) | `/flagged` | `flagged.html` | `/flagged` | Haiku | medium | List + filter + flag-reason editor. |
| 4 | Storage (top-level) | `/storage` | `storage.html` | merge into `/settings/storage` (already exists in new UX) | (consolidate, no new build) | low | New UX already has `/settings/storage` as the canonical location. Drop `/storage` route or 301-redirect to `/settings/storage`. |
| 5 | Pipeline Files | `/pipeline-files` | `pipeline-files.html` | `/pipeline-files` (operator drill-down from /status or /activity) | Sonnet | medium | Tree-of-states view; recursive rendering; stats panel. |
| 6 | Locations | `/locations` | `locations.html` | `/settings/locations` (settings sub-page) | Sonnet | medium | CRUD + browse picker integration + exclusions. New IA: surface under settings, not top-level. |
| 7 | Bulk family (3 surfaces) | `/bulk`, `/bulk-review`, `/job-detail` | `bulk.html`, `bulk-review.html`, `job-detail.html` | `/bulk` overview + `/bulk/:id` detail (consolidate to 2 pages) | Sonnet | high | Pause/resume/cancel state machine; consolidate `bulk-review` and `job-detail` into a single tabbed detail. |
| 8 | Viewer | `/viewer.html` | `viewer.html` | `/viewer` or `/doc/:id` | Opus | high | Markdown render + original-format display + sidecar nav + hover-preview. Largest LOC; novel UI. |
| 9 | Activity (existing CSS works; may need polish) | `/activity` | `activity.html` (twin shipped) | `/activity` | Sonnet | low | Already partially wired; finish polishing + chart integration. |
| 10 | Resources / Monitoring | `/resources.html` | `resources.html` | `/settings/resources` or merge into `/operations` | Haiku | medium | System metrics + charts; could fold into operations dashboard. |
| 11 | Trash | `/trash.html` | `trash.html` | `/trash` (utility surface) | Haiku | low | Restore-or-empty list; thin UI. |
| 12 | Unrecognized | `/unrecognized.html` | `unrecognized.html` | `/unrecognized` (operator surface) | Haiku | low | List + reclassification action. |
| 13 | Review | `/review.html` | `review.html` | `/review` | Sonnet | medium | Per-batch review queue; touches sidecar APIs. |
| 14 | Preview | `/preview.html` | `preview.html` | `/preview` (deep-link only — no menu surface) | Sonnet | medium | Per-file inspection; force-process button; selection-driven search. |
| 15 | Progress | `/progress.html` | `progress.html` | merge into `/status` (single-row in active ops list) | (consolidate) | low | Single-job progress is a slice of /status — fold in. |
| 16 | Admin panel | `/admin.html` | `admin.html` | `/settings/admin` (sub-page) | Sonnet | medium | Operator-only tools; small surface. |
| 17 | Batch management | `/batch-management.html` | `batch-management.html` | `/bulk` (consolidate) | (consolidate) | low | Overlaps with bulk; merge. |

### Tier C — recommended consolidations (new-UX-only IA shifts)

The new UX is anchored by avatar menu + top-nav. We can consolidate redundant pages without breaking original UX.

| Original (split) | New (consolidated) | Rationale |
|------------------|--------------------|-----------|
| `/status` (Active Jobs) + `/activity` (Trends) | **`/operations`** with two tabs: "Active now" + "Trends" | Both answer "operational health" but for different time horizons. Single page reduces top-nav to 2 items + avatar (member: Search + Convert; operator: Search + Operations + Convert). |
| `/bulk` + `/bulk-review` + `/job-detail` | **`/bulk` (overview)** + `/bulk/:id` (tabbed detail with files / progress / errors / actions) | Three pages today; one detail-with-tabs is cleaner. |
| `/storage` + `/settings/storage` | **`/settings/storage` only** | Already canonical in new UX; drop the top-level `/storage`. |
| `/providers` + `/settings/ai-providers` | **`/settings/ai-providers` only** | Already done in v0.39.0 avatar menu mapping. |
| `/db-health` + `/settings/db-health` | **`/settings/db-health` only** | Same. |
| `/log-management` + `/settings/log-management` + `/log-mgmt` | **`/log-mgmt` (canonical)** with `/settings/log-management` as alias | v0.39.0 already routes `/log-mgmt`; keep settings-link as alias. |
| `/results.html` (redirect) | **drop or keep as 301** | Already a redirect; safe to delete. |
| `/progress` (single-job) | merge into `/status` | A single-job progress widget is one row in the active-ops table. |
| `/batch-management` | merge into `/bulk` overview | Overlap is total. |

**Consolidation savings:**
- Top-nav: 3 items → 3 items (no change, but Operations replaces Activity for operators with the implicit /status merge).
- Avatar menu: removes need for separate /storage, /providers, /db-health, /log-management entries (they're already settings sub-pages in new UX).
- Total page count after consolidation: ~22 distinct surfaces in new UX vs. 50 HTML files in original UX. Roughly half. Maintenance + review cost halves with it.

### Tier D — leave original-only (no new-UX twin needed)

| Page | Reason |
|------|--------|
| `/debug.html` | Internal dev page; not user-facing; gitignored from menu surfaces. |
| `/results.html` | Pure redirect to `/history`; no UI. |

### Tier E — already shipped in new UX (v0.36–v0.39)

| Page | URL | Status |
|------|-----|--------|
| Search home | `/` | both (CSS verify pending) |
| Convert | `/convert` | both ✓ |
| Search results | `/search` | both ✓ (v0.39.0 CSS fix) |
| Settings overview | `/settings` | both ✓ |
| Settings sub-pages (9) | `/settings/*` | new-only ✓ |
| Help | `/help` | both ✓ (CSS verify pending) |
| Log viewer | `/log-viewer` | both ✓ |
| Log management | `/log-mgmt` | both ✓ |
| Log levels | `/log-levels` | both ✓ |
| Activity | `/activity` | both (verify) |

---

## Per-page subagent dispatch (model + effort)

After the v0.39.0 hot-revert, the build-out runs in three waves. Model and effort are picked per the picking-model-and-effort skill: **Haiku** for mechanical template-driven work, **Sonnet** for real logic + integration, **Opus** for novel UI complexity. Effort scales with state complexity, not LOC.

### Wave 1 (v0.40.0 — fix the silent failures): 4 parallel agents

Goal: re-dispatch the Tier-A reverted routes by adding their CSS sections.

| Page | Subagent | Model | Effort | Why |
|------|----------|-------|--------|-----|
| `/status` CSS | mf-impl-medium | Sonnet | medium | ~40 BEM classes; real-time op cards with progress + cancel buttons need theme-correct styling. |
| `/history` CSS | mf-impl-medium | Haiku | medium | List + pagination is mostly mechanical from search-results template. |
| `/flagged` CSS | mf-impl-medium | Haiku | medium | Similar list/filter pattern. |
| `/storage` consolidation | mf-impl-medium | Haiku | low | Drop `/storage` dispatch; 301 to `/settings/storage`. One-line plus avatar-menu update. |

**Review:** mf-rev-medium (Sonnet) sweeps all 4 with the BEM-grep verifier. Re-enable dispatch in `main.py`.

### Wave 2 (v0.41.0 — operator surfaces): 4 parallel agents

| Page | Subagent | Model | Effort | Why |
|------|----------|-------|--------|-----|
| `/operations` (Status + Activity merge) | mf-impl-high | Sonnet | high | New tabbed page; merges /status (live ops) + /activity (trends). State machine for tab switch + shared chrome. |
| `/pipeline-files` | mf-impl-medium | Sonnet | medium | Tree view, recursive rendering. |
| `/locations` (settings sub-page) | mf-impl-medium | Sonnet | medium | CRUD + browse picker. |
| `/bulk` family consolidation | mf-impl-high | Sonnet | high | 3 pages → `/bulk` + `/bulk/:id` tabs. State machine. |

**Review:** mf-rev-high (Sonnet) — these are state-heavy pages, real review needed.

### Wave 3 (v0.42.0 — long tail): 4 parallel agents

| Page | Subagent | Model | Effort | Why |
|------|----------|-------|--------|-----|
| `/viewer` | mf-impl-high | **Opus** | high | Markdown render + original-format viewer + sidecar nav + hover-preview. Highest novelty; worth Opus. |
| `/trash` + `/unrecognized` | mf-impl-medium | Haiku | low (each) | Thin UI; bundle two cheap pages into one Haiku dispatch. |
| `/review` + `/preview` | mf-impl-medium | Sonnet | medium | Sidecar API integration; bundle two related pages. |
| `/settings/admin` (admin panel) | mf-impl-medium | Sonnet | medium | Operator-only tools; touches sensitive endpoints, deserves careful review. |

**Review:** mf-rev-high (Sonnet) for /viewer + /settings/admin (security-adjacent), mf-rev-medium for the others.

### Final integration pass (after all waves)

One Sonnet medium agent runs the inventory diff (`docs/new-ux-pages.md`), verifies route table in `main.py`, runs the cross-page theme verification (load each `/page` under `mf_use_new_ux=1` + each of nebula / classic-dark / spring themes; confirm no console errors and no unstyled BEM classes via DevTools).

## Cost-shaping summary

Total dispatches across 3 waves: 12 build agents + 3 review agents + 1 integration = 16 subagent runs.

| Tier | Count | Approx model spread |
|------|-------|---------------------|
| Haiku tasks | 4 | /history, /flagged, /storage, /trash+/unrecognized |
| Sonnet medium | 6 | /status, /pipeline-files, /locations, /review+/preview, /settings/admin, integration |
| Sonnet high | 2 | /operations, /bulk family |
| Opus high | 1 | /viewer |
| Reviewers (Sonnet) | 3 | one per wave |

Compared to a sequential one-Opus-for-everything approach: **~70% cost reduction** by routing mechanical work to Haiku and reserving Opus for the one page (/viewer) that genuinely needs it.

## Acceptance criteria (per page)

- [ ] Page renders with no console errors in `mf_use_new_ux=1` mode
- [ ] BEM lint: every `el(<tag>, 'mf-<page>__<part>')` reference has a matching `.mf-<page>__<part>` selector in `components.css`
- [ ] Token lint: zero hardcoded hex in the new CSS section (`grep -E 'var\(--[a-z]' new-section | grep -v -- '--mf-'` returns nothing)
- [ ] Theme + font + text-scale changes propagate live (drawer toggles work)
- [ ] Original UX still works (toggle off → original page served)
- [ ] All API responses handled (loading, empty, error, success branches)
- [ ] `docs/new-ux-pages.md` row updated to `both`
- [ ] If a class-of-bug was exposed, a row added in `docs/gotchas.md`

## Risks / blast radius

- **BUG-033 replay:** every new page is a chance to forget CSS. Mitigation: the BEM-grep verifier MUST pass before any subagent claims completion. Documented in `docs/gotchas.md` Per-User UX Dispatch section.
- **Original-UX regression:** shared `app.js` and shared CSS sections could drift. Mitigation: each subagent loads the original page once after their work and confirms parity.
- **Consolidation breaks bookmarks:** dropping `/storage`, `/providers`, `/db-health` top-level URLs in favor of `/settings/*` could 404 existing bookmarks. Mitigation: 301 redirect from old path to new for one release window; remove redirect in v0.43.0+.
- **Avatar menu drift:** `URLS_NEW` and `URLS_ORIGINAL` maps in `avatar-menu-wiring.js` need synced updates as routes consolidate. Mitigation: each consolidation PR includes the avatar-menu-wiring change in the same commit.

## v0.39.0 hot-revert decision

Before pushing v0.39.0, the user must choose:

- **Option A (recommended):** revert the new-UX dispatch for `/status`, `/history`, `/flagged`, `/storage` — they fall back to original UX. Ship v0.39.0 with the headline per-user dispatch + search-results CSS fix. Build the CSS in v0.40.0 (Wave 1).
- **Option B:** build the missing CSS for the 4 pages now (~1000+ lines). Adds 2–4 hours. Ship v0.39.0 with all pages styled.
- **Option C:** ship v0.39.0 as-is, accept that `/status`, `/history`, `/flagged`, `/storage` are visually broken in new UX for one release. Document as known issue.

Cost / time / risk:
| Option | Cost | Time | Risk |
|--------|------|------|------|
| A | Low (4-line revert) | 5 min | Low — known-good fallback path |
| B | High | 2–4 h | Medium — large CSS surface, high BEM-gap retest cost |
| C | Zero | 0 min | High — silent broken UX for users who toggle on |

## Estimated wall-clock

With 4 parallel agents per wave + sequential review:

| Stage | Time |
|-------|------|
| v0.39.0 hot-revert (Option A) | 10 min |
| Wave 1 (v0.40.0) impl + review | 1 h |
| Wave 2 (v0.41.0) impl + review | 1.5 h |
| Wave 3 (v0.42.0) impl + review | 2 h |
| Final integration verification | 30 min |
| **Total (parallel)** | **~5 hours** |
| Total (sequential, one agent) | ~15+ h |

## Out-of-scope follow-ups (queue for later plans)

- Mobile responsive breakpoints (audit + fix per-page)
- Full-page screenshot tests (Playwright) for visual regression on every theme
- Hover-preview component new-UX twin (referenced by viewer + search-results)
- AI-assist drawer integration on every results-bearing page (today only on `/search`)
- Bookmark redirect cleanup (drop the 301 fallbacks introduced by consolidation)

## Change log

- 2026-05-03 — initial plan written; expanded to full audit after user request to scan every page and verify equivalents exist
