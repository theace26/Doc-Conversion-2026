# Change Index — components.css Theme-Aware Refactor (v0.38.0)

**Spec:** `2026-05-02-components-css-theme-aware-design.md`
**Plan:** `2026-05-02-components-css-theme-aware.md`
**Branch:** `refactor/components-css-theme-aware`
**Status:** Outlier review pending — awaiting per-site human decisions

This is the rollback artifact. Every per-site outlier decision lives here.
Every literal touched in Tasks 4–11 (mechanical sed substitutions) is implicit;
the canonical mapping is in the plan. This document captures only the outlier
sites the spec deferred to Task 12.

---

## Outlier inventory

### components.css (24 sites)

| # | Line | Selector | Current | Default action | Default new value | Surrounding context | DECISION |
|---|---|---|---|---|---|---|---|
| 1 | 122 | `.mf-role-pill` | `0.6rem` | snap | `var(--mf-text-2xs)` | uppercase track-wide role label (MEMBER/ADMIN/OPERATOR); weight 700, padding 0.12rem 0.45rem, pill border-radius | _pending_ |
| 2 | 148 | `.mf-nav__logo` | `1.05rem` | snap | `var(--mf-text-md)` | nav bar brand name / logo wordmark; weight 700, inline-flex with icon gap 0.55rem | _pending_ |
| 3 | 173 | `.mf-ver-chip` | `0.62rem` | snap | `var(--mf-text-2xs)` | dev-only version chip (hidden in prod via design-tokens.css selector); weight 700, warn-color, mono font, uppercase tracking | _pending_ |
| 4 | 271 | `.mf-av-menu__sec-label` | `0.62rem` | snap | `var(--mf-text-2xs)` | avatar-menu section header label; weight 700, uppercase track-wide (0.07em), fainter text color | _pending_ |
| 5 | 279 | `.mf-av-menu__gate` | `0.5rem` | review-then-keep-raw | `/* exception: sub-icon */` | gate/feature-flag indicator pill inside avatar menu; weight 700, warn-color, pill shape — extremely small glyph (0.5rem is intentionally sub-icon scale) | _pending_ |
| 6 | 424 | `.mf-doc-card__snippet` | `0.65rem` | snap | `var(--mf-text-2xs)` | document card text-snippet preview (serif font, line-height 1.45); base card size, not compact variant — at 0.65rem this is already borderline small | _pending_ |
| 7 | 502 | `.mf-doc-list-row__fmt` | `0.55rem` | review-then-keep-raw | `/* exception: sub-icon */` | format badge — 24×24px colored box containing 3–4 char abbreviation (PDF/DOCX/etc); weight 800, tracked, white-on-color — needs extreme density; sub-icon scale intentional | _pending_ |
| 8 | 557 | `.mf-card-grid--compact .mf-doc-card__band-label` | `0.6rem` | snap | `var(--mf-text-2xs)` | compact-grid override of band label (base is already `--mf-text-2xs`/0.7rem); overrides to 0.6rem in 8-column compact grid — snap brings it back to match base, eliminating the override entirely | _pending_ |
| 9 | 558 | `.mf-card-grid--compact .mf-doc-card__snippet` | `0.56rem` | review-then-keep-raw | `/* exception: sub-icon */` | compact-grid snippet text (0.56rem); paired with reduced padding (0.4rem 0.5rem 0.35rem); at 8-column density this is intentionally sub-readable summary text — closer to sub-icon glyph scale | _pending_ |
| 10 | 559 | `.mf-card-grid--compact .mf-doc-card__snippet-h` | `0.62rem` | snap | `var(--mf-text-2xs)` | compact-grid snippet heading; at 8-column density, this heading is ~0.62rem; snapping to 0.7rem adds ~1.3px at base scale | _pending_ |
| 11 | 656 | `.mf-hover-preview__summary-lab` | `0.62rem` | snap | `var(--mf-text-2xs)` | hover-preview panel "SUMMARY" label; weight 700, accent color, uppercase track-wide (0.08em), section marker inside floating preview | _pending_ |
| 12 | 699 | `.mf-ctx__sec-label` | `0.62rem` | snap | `var(--mf-text-2xs)` | context-menu section divider label; weight 700, fainter text, uppercase track-wide (0.07em) — mirrors `.mf-av-menu__sec-label` visually | _pending_ |
| 13 | 754 | `.mf-ctx__exp-chev` | `0.62rem` | snap | `var(--mf-text-2xs)` | expand-chevron icon inside context-menu expandable rows; purely a chevron glyph, not readable text — 0.62→0.7rem shift adds ~1px to glyph; single-line rule with `transition: transform` | _pending_ |
| 14 | 965 | `.mf-row__title` | `1.25rem` | snap | `var(--mf-text-h3)` | section-row page title (home page row headers, weight 700, tracking -0.018em); h3 token is 1.2rem — 0.05rem reduction, visually minor but worth a watch | _pending_ |
| 15 | 1060 | `.mf-home__headline--huge` | `3.4rem` | review | `var(--mf-text-display-lg)` | home page hero headline "huge" variant modifier (parent `.mf-home__headline` uses `--mf-text-display` 2.4rem); `--mf-text-display-lg` is 3.0rem — a 0.4rem reduction (≈6px at base scale); this is the most visible text on the page | _pending_ |
| 16 | 1065 | `.mf-home__subtitle` | `1.1rem` | snap | `var(--mf-text-h3)` | home page subtitle below headline; muted color, max-width 42ch centered, body font — h3 token (1.2rem) snaps upward by 0.1rem; consider whether `--mf-text-md` (1.0rem) might be a better fit semantically | _pending_ |
| 17 | 1191 | `.mf-act__sec-h` | `1.3rem` | snap | `var(--mf-text-h3)` | activity-panel section heading (weight 700, tracking -0.018em, `text-transform: none`); NOTE: line 1184 assigns this selector the shared rule `font-size: var(--mf-text-2xs)` which is immediately overridden here — cleanup opportunity (remove from shared rule) | _pending_ |
| 18 | 1308 | `.mf-settings__card-arrow` | `1.1rem` | snap | `var(--mf-text-h3)` | hover-reveal directional arrow on settings card (opacity 0 at rest, translateX on hover); this is a chevron/arrow icon glyph (not readable text) — h3 at 1.2rem adds ~1.6px; consider whether `--mf-text-md` (1.0rem) preserves the intended "subtle" hover cue better | _pending_ |
| 19 | 1613 | `.mf-ai__type-badge` | `0.65rem` | snap | `var(--mf-text-2xs)` | AI provider type badge pill (e.g. "OPENAI", "LOCAL"); weight 700, uppercase track-wide (0.04em), accent-tint background | _pending_ |
| 20 | 1624 | `.mf-ai__active-badge` | `0.65rem` | snap | `var(--mf-text-2xs)` | AI "active" status badge pill; weight 700, success-color background — same visual pattern as `.mf-ai__type-badge` above | _pending_ |
| 21 | 1819 | `.mf-log__compressed-badge` | `0.65rem` | snap | `var(--mf-text-2xs)` | log-viewer "COMPRESSED" state badge; weight 700, uppercase track-wide (0.04em), accent-tint background — same pill pattern as AI badges | _pending_ |
| 22 | 1863 | `.mf-cost__tile-value` | `1.7rem` | snap | `var(--mf-text-h1)` | cost tile large numeric value (weight 700, tracking -0.02em); h1 token is 1.85rem — snaps upward by 0.15rem; consider whether that enlarges the KPI number more than desired | _pending_ |
| 23 | 2024 | `.mf-ob__headline` | `1.8rem` | snap | `var(--mf-text-h1)` | onboarding step headline (weight 700, tracking -0.02em, `--mf-text-primary`); h1 token is 1.85rem — 0.05rem upward nudge, negligible visually | _pending_ |
| 24 | 2076 | `.mf-ob__recommended-badge` | `0.65rem` | snap | `var(--mf-text-2xs)` | onboarding "RECOMMENDED" badge in top-right corner of option card; weight 700, uppercase track-wide (0.04em), accent background, white text — same pill pattern as AI/log badges | _pending_ |

### markflow.css (7 sites)

| # | Line | Selector | Current | Default action | Default new value | Surrounding context | DECISION |
|---|---|---|---|---|---|---|---|
| 1 | 29 | `h1` (global) | `1.75rem` | snap | `var(--mf-text-h1)` | global h1 reset rule (weight 700, line-height 1.2, accent color); h1 token is 1.85rem — snaps upward 0.1rem; see also `.help-content h1` at line 1393 which duplicates this value | _pending_ |
| 2 | 31 | `h3` (global) | `1.1rem` | snap | `var(--mf-text-h3)` | global h3 reset rule (weight 600, line-height 1.4, accent color); h3 token is 1.2rem — snaps upward 0.1rem; see also `.help-content h3` at line 1395 which duplicates this value | _pending_ |
| 3 | 66 | `.nav-logo` | `1.15rem` | snap | `var(--mf-text-h3)` | main-nav logo/wordmark (weight 700, text color, tracking -0.01em); h3 token is 1.2rem — 0.05rem upward nudge; note this is markflow.css nav (legacy), separate from `.mf-nav__logo` in components.css (line 148) | _pending_ |
| 4 | 1075 | `.kpi-value` | `1.8rem` | snap | `var(--mf-text-h1)` | dashboard KPI large numeric value (weight 700, line-height 1.1); h1 token is 1.85rem — 0.05rem upward nudge; mirrors `.mf-cost__tile-value` pattern (components.css #22 above) | _pending_ |
| 5 | 1142 | `.nav-badge` | `0.65rem` | snap | `var(--mf-text-2xs)` | nav active-job-count badge (inline-flex, 1.1rem min-width/height, accent background, white text, weight 700); tight circular badge — 0.65→0.7rem adds ~0.8px, watch for clipping in the 1.1rem container | _pending_ |
| 6 | 1393 | `.help-content h1` | `1.75rem` | snap | `var(--mf-text-h1)` | help-panel article h1 (weight 700, margin-bottom 0.5rem); duplicates the global `h1` value at line 29 — both should snap together to `--mf-text-h1`; can fold into same decision as site #1 | _pending_ |
| 7 | 1395 | `.help-content h3` | `1.1rem` | snap | `var(--mf-text-h3)` | help-panel article h3 (weight 600, margin-top 1.5rem); duplicates the global `h3` value at line 31 — both should snap together to `--mf-text-h3`; can fold into same decision as site #2 | _pending_ |

---

## Watch-items from prior code reviews (worth verifying during morning visual sweep, not necessarily edits)

- `.mf-layout-pop__check` — at xl text-scale, the 0.95→0.92rem shift may be visible (~0.65px at xl)
- `.mf-doc-card__fav` in `.mf-card-grid--compact` — 0.66→0.70rem may clip the icon glyph in tightest grids
- `.mf-av-menu__item` vs `.mf-av-menu__who-name` — hierarchy compression (0.86 vs 0.92 = 0.06rem; was 0.86 vs 0.95 = 0.09rem)
- `.mf-sb__input` (hero search) — `--mf-text-base` (0.86rem) is semantically light for a hero input; consider bumping to body
- `.mf-row__title` (1.25rem outlier) — listed above as components.css #14; visual check before snap to h3
- `.mf-act__sec-h` (1.3rem outlier) — has redundant shared-rule assignment of `--mf-text-2xs` that gets immediately overridden; cleanup opportunity (listed as components.css #17)
- `.storage-reverify-btn` (markflow) — already tokenized to `var(--mf-text-2xs)` in prior task; was 0.75rem → 0.7rem shift — verify button label not cramped at smallest viewport
- `small, .text-sm` (markflow line 34) — semantic mismatch: utility class named "sm" maps to `--mf-text-base` not `--mf-text-sm`. Consider documenting or snapping to actual sm.
- `.help-content h1`/`.help-content h3` (markflow lines 1393/1395) — duplicate the legacy h1/h3 outlier values; folded into same decision as global h1/h3 sites #1/#2 above

---

## Decision instructions for the morning

For each row's DECISION cell, replace `_pending_` with one of:
- `snap` — accept the default new value (use the canonical token)
- `keep-raw` — preserve the current literal with a `/* exception: <reason> */` comment on the same line in the CSS file
- `new-token` — propose a new token (specify name + value)
- `redirect-to <token>` — snap, but to a different token than the default

After all decisions are recorded, the implementer will:
1. Apply each `snap`/`redirect-to` edit to the CSS files
2. Add `/* exception: ... */` comments to each `keep-raw` line
3. Define any new tokens in design-tokens.css
4. Commit both the change-index doc and the CSS edits in a single Phase 5 commit
