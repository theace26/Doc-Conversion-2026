# Design — components.css Theme-Aware Refactor (v0.38.0)

**Status:** approved (brainstorm), audit-pending, plan-pending
**Authoring effort:** Opus 4.7 / high
**Implementation effort target:** Sonnet 4.6 / medium (paste-and-test mechanical, except outlier review which is Sonnet 4.6 / high)
**Source brainstorm:** session 2026-05-02 (post-v0.37.1 ship)
**Builds on:** `2026-05-01-markflow-theme-refactor-design.md` (v0.37.1)

---

## Goal

Make every text element in MarkFlow respond uniformly to the v0.37.0 font picker and the `--mf-text-scale` system, with a single text-size token grid shared across `static/css/components.css` (new-UX) and `static/markflow.css` (legacy original-UX).

This refactor closes three gaps left by v0.37.1:

1. **Font picker bypass.** `components.css` references `var(--mf-font-sans)` (51 sites) — a hardcoded fallback in `design-tokens.css` line 64 — instead of `var(--mf-font-family)`, the picker-bound token. Result: the picker silently no-ops on every component that uses it.
2. **Latent v0.37.1 import regression.** `markflow.css` references 364 `var(--mf-*)` tokens but does not `@import` `design-tokens.css` or `design-themes.css`, and the 27 legacy HTML pages do not link those files either. The theme init script in each `<head>` sets `data-theme`/`data-font`/`data-text-scale` on `<html>`, but no stylesheet that uses those attributes is loaded on legacy pages. The v0.37.1 release shipped a regression that masquerades as working (browser default colors happen to roughly resemble Classic Light).
3. **Drift in the size system.** 311 raw `font-size: Xrem` literals across 39 distinct values in the two files. Token-using sites (`--mf-text-xs/sm/body/micro`) double-scale because both their definition and the `html { font-size }` rule include `* var(--mf-text-scale)`.

After this refactor, the picker, font, and text-scale work app-wide; the size vocabulary is a single 11-token grid; double-scaling is gone.

## Non-goals

- Redesigning the type scale itself. The grid is informed by current usage, not a fresh design pass.
- Touching CSS files outside `components.css`, `markflow.css`, `design-tokens.css`, `design-themes.css`.
- Adding new themes or fonts.
- Layout, spacing, or color changes (this is *type-system* work; color literals already shipped in v0.37.1).
- Modifying HTML structure, class names, or template inheritance.
- Inline `<style>` blocks in HTML pages (out of scope; some have `var(--text)` non-prefixed refs that are pre-existing dead code, captured in change-index but unchanged).

## Background

v0.37.0 shipped the theme system: `design-tokens.css` defines `:root`-level `--mf-*` custom properties; `design-themes.css` overrides a subset per `[data-theme="X"]` selector; `--mf-font-family` binds to `[data-font="X"]`; `--mf-text-scale` binds to `[data-text-scale="X"]`.

v0.37.1 attempted to bring the legacy `markflow.css` into this system. It deleted markflow.css's local `:root` block, renamed all 302 var refs to `--mf-*`, and substituted ~50 hardcoded color literals to tokens. The release notes claim "Every --mf-* used in markflow.css has a :root default" — but that `:root` block lives in `design-tokens.css`, which is not imported by markflow.css and not linked by the 27 legacy HTML pages. The fix is incomplete; theme switching has no real effect on legacy pages today.

`components.css` was already in good shape for color theming (it imports both design-tokens.css and design-themes.css and uses `--mf-color-*` tokens correctly). Its remaining issues are font-family rebinding and font-size tokenization — neither addressed in v0.37.1.

This refactor closes both gaps.

## Architecture decisions

| # | Decision | Rationale |
|---|---|---|
| A1 | **Phase 0: prepend two `@import`s to markflow.css.** Adds `@import url('./css/design-tokens.css'); @import url('./css/design-themes.css');` at the top, before the Google Fonts import. | Closes the v0.37.1 import regression. After Phase 0, legacy pages have all token defs available and `[data-theme]` actually re-themes. |
| A2 | **In-place edits to both target files.** No bridge files. | Same rationale as v0.37.1: avoid specificity wars; keep canonical namespace. |
| A3 | **Single PR, multiple commits during implementation, squashed to a rollup commit at ship time.** | Mirrors v0.37.1 pattern. Per-phase commits give granular bisect; final history shows one v0.38.0 commit. |
| A4 | **Tight grid (11 tokens):** 9 core + 2 display tokens. | User chose Tight in brainstorm. Forces design discipline; aligns with Polaris/Tailwind small-end vocabulary. Display tokens added because 5 occurrences of 2.3+rem warrant a dedicated semantic role. |
| A5 | **Drop `* var(--mf-text-scale)` from token definitions.** Tokens become plain rem values; scale applies once via `html { font-size: calc(16px * --mf-text-scale) }`. | Eliminates double-scaling bug. Single source of truth for scaling. |
| A6 | **Move the `html { font-size }` rule to `design-themes.css`.** | Logical home alongside `[data-text-scale]` defs. components.css already imports design-themes.css; after Phase 0 markflow.css will too — so the rule reaches every page that needs it. |
| A7 | **Per-site outlier review.** ~33 sites in 0.5–0.65rem, 1.05–1.3rem, 1.7–1.8rem ranges get explicit decisions in the change-index. Each row records: current size, proposed bucket, action (`snap`/`keep-raw`/`new-token`), and reasoning. | Tight bucketing only works for dense bands. Snapping a 1.05rem h3 to 1.2rem is a >2px shift — not acceptable silently. The change-index makes outliers reviewable and reversible. |
| A8 | **Mark `--mf-font-sans` deprecated** with a comment in `design-tokens.css`; keep the definition. No callers in MarkFlow code post-refactor. | Defensive. External consumers (browser extensions, embeds) might rely on it. Cost of keeping = 1 line + comment. |
| A9 | **`--mf-font-mono` and `--mf-font-serif` stay unchanged.** Mono is intentionally non-picker (code blocks, file paths). Serif is unused but kept available for future. | These tokens have distinct semantic roles outside the picker. Don't conflate. |
| A10 | **Heading tokens (`--mf-text-h1/h2/h3`, `--mf-text-display`, `--mf-text-display-lg`) scale via the html rule, same as body tokens.** | Uniform scaling. Currently h1/h2/h3 don't scale at all because their definitions lack `* scale`; after A5, they scale via the html rule, which is the desired behavior. |
| A11 | **Change-index doc is the rollback artifact.** Committed alongside the code. Format mirrors v0.37.1's change-index. | Per-site action log; lets `git revert` + replay-of-skipped-rows recover from any regression. |
| A12 | **Phase 0 mandates browser verification before any other phase begins.** | The latent v0.37.1 bug is the foundation; if Phase 0 doesn't fix it, every later phase is built on sand. |

## Token grid

Defined in `static/css/design-tokens.css`. All values raw rem (no `* var(--mf-text-scale)`); html font-size scales them.

| Token | Value | Catches (raw rem) | ~Calls | Max shift |
|---|---|---|---|---|
| `--mf-text-2xs` | 0.7rem | 0.66 / 0.68 / 0.7 / 0.72 / 0.74 / 0.75 / 0.76 | 51 | ±0.04rem (~0.6px) |
| `--mf-text-xs` | 0.78rem | 0.78 | 35 | 0 |
| `--mf-text-sm` | 0.82rem | 0.8 / 0.82 / 0.84 | 52 | ±0.02rem (~0.3px) |
| `--mf-text-base` | 0.86rem | 0.85 / 0.86 / 0.875 / 0.88 | 66 | ±0.02rem (~0.3px) |
| `--mf-text-body` | 0.92rem | 0.9 / 0.92 / 0.94 / 0.95 / 0.96 | 37 | ±0.04rem (~0.6px) |
| `--mf-text-md` | 1.0rem | 1.0 | 9 | 0 |
| `--mf-text-h3` | 1.2rem | 1.2 | 3 | 0 |
| `--mf-text-h2` | 1.4rem | 1.35 / 1.4 | 3 | ±0.05rem (~0.8px) |
| `--mf-text-h1` | 1.85rem | 1.85 | 6 | 0 |
| `--mf-text-display` | 2.4rem | 2.3 / 2.4 / 2.5 | 5 | ±0.1rem (~1.6px) |
| `--mf-text-display-lg` | 3.0rem | 3.0 / 3.4 | 2 | ±0.4rem (~6.4px) |

Covers ~269 of 311 raw `font-size: Xrem` literals (~86%). Remaining ~33 raw literals are outliers (handled below). Another ~9 sites already use existing `--mf-text-*` tokens; those automatically inherit the new grid values after Phase 1.

**Token redefinitions in this refactor:**

| Existing token | Current value | New value | Notes |
|---|---|---|---|
| `--mf-text-display` | `2.4rem` | `2.4rem` | Same value; `* scale` stays out (was already out) |
| `--mf-text-display-sm` | `2.0rem` | *deleted* | No callers in inventory |
| `--mf-text-h1` | `1.85rem` | `1.85rem` | Same value, no change |
| `--mf-text-h2` | `1.4rem` | `1.4rem` | Same value, no change |
| `--mf-text-h3` | `1.05rem` | `1.2rem` | Value shift — see Phase 4 visual diff for legacy h3 (now driven by this token) |
| `--mf-text-body` | `calc(0.94rem * --mf-text-scale)` | `0.92rem` | Drops scale; value shifts -0.02rem |
| `--mf-text-sm` | `calc(0.86rem * --mf-text-scale)` | `0.82rem` | Drops scale; value shifts -0.04rem |
| `--mf-text-xs` | `calc(0.78rem * --mf-text-scale)` | `0.78rem` | Drops scale; same base value |
| `--mf-text-micro` | `calc(0.7rem * --mf-text-scale)` | *renamed to `--mf-text-2xs`* | Same base value (0.7rem); existing callers must update name in Phase 1 |

**New tokens:** `--mf-text-2xs` (0.7rem, replaces micro), `--mf-text-base` (0.86rem), `--mf-text-md` (1.0rem), `--mf-text-display-lg` (3.0rem).

## Outliers handling

Each outlier site gets a row in `2026-05-02-components-css-theme-aware-change-index.md` with: file, line, selector, current value, proposed action, reasoning.

| Cluster | Sizes | ~Calls | Default proposal |
|---|---|---|---|
| Below 2xs (sub-icon text) | 0.5 / 0.55 / 0.56 / 0.6 / 0.62 / 0.65 / 0.66 | ~20 | Snap up to 2xs (0.7rem) for sites in 0.62–0.66 range. Sites ≤0.6rem get individual review — likely 2-3 stay raw with a `/* exception: sub-icon label */` comment. |
| Between body and h3 | 1.05 / 1.1 / 1.15 / 1.25 / 1.3 | ~8 | Snap to nearest grid token (md=1.0 or h3=1.2). Per-site judgment for any deliberate "between-h3" choices. |
| Between h2 and h1 | 1.7 / 1.75 / 1.8 | ~5 | Snap to h1 (1.85). Likely just drift from h1. |
| Above display | (none unmapped — 3.0/3.4 covered by display-lg) | 0 | n/a |

**Sites where snap creates >0.3px shift get explicit per-site review** — change-index records the human decision for each.

## Phase plan

| Phase | Scope | Files touched | Commits | Verification |
|---|---|---|---|---|
| **0** | Prepend 2 `@import` lines to markflow.css | `static/markflow.css` | 1 | Browser test: open `/static/status.html` (legacy) on fresh cache, switch theme via picker, confirm visible re-theming. **Halt and debug if not.** |
| **1** | Update token defs in design-tokens.css (11-token grid, drop `* scale`, deprecate `--mf-font-sans`); move `html { font-size }` rule from markflow.css to design-themes.css | `static/css/design-tokens.css`, `static/css/design-themes.css`, `static/markflow.css` (delete one line) | 1–2 | Visual checkpoint: browser test on a representative new-UX page (`/static/index-new.html`) and a legacy page (`/static/status.html`). Confirm no visible change at default scale; confirm text-scale=xl now scales uniformly (no jumbo-text on token-using sites). |
| **2** | components.css — rebind `var(--mf-font-sans)` → `var(--mf-font-family)` (51 sites) | `static/css/components.css` | 1 | Browser test: font picker now retunes type on `/static/index-new.html`, `/static/settings-appearance.html`. |
| **3** | components.css — substitute 182 size literals to tokens, by selector group | `static/css/components.css` | 4–5 | Per-group visual diff against pre-refactor screenshots. |
| **4** | markflow.css — substitute 129 size literals to tokens, by section | `static/markflow.css` | 4–5 | Per-section visual diff. |
| **5** | Outlier review — ~33 sites get explicit decisions captured in change-index | both files + change-index doc | 1–2 | Per-site judgment captured in the change-index doc. |
| **6** | Final visual checkpoint sweep + release docs (version-history, what's-new, CLAUDE.md) | docs only | 1–2 | Manual screen tour: index-new, status, settings-appearance, history, search, viewer, settings-storage, batch-management. Theme picker exercise: 9 sample combinations of 5 themes × 3 fonts × 3 text scales. |

Per-phase commits get squashed into a single `v0.38.0:` rollup commit at ship time, mirroring v0.37.1.

## Verification strategy

1. **After Phase 0:** mandatory browser test on legacy pages. Pass-fail gate before any other phase begins.
2. **After Phase 1:** confirm no visible change at default scale; confirm xl scale now uniformly scales (xs-tagged text no longer jumbo).
3. **After Phases 2–4:** per-phase manual visual diff. Use the screen tour list from Phase 6.
4. **After Phase 5:** outlier sites individually inspected and signed off.
5. **Before rollup commit:** full screen tour + theme picker exercise (9 sample combinations).

Cycle through these themes during checkpoint: Classic Light, Classic Dark, Cobalt, Sage, Crimson. Cycle through these fonts: System UI, Source Sans 3, JetBrains Mono. Cycle through these text scales: small, default, xl.

## Risk callouts

- **Phase 0 may surface other v0.37.1 latent issues.** Once design-themes.css actually loads on legacy pages, palette drift between markflow.css's expected default values and design-tokens.css's defaults may become visible. Capture each instance in the change-index; address by adjusting design-tokens.css defaults or adding a token where needed. Do not silently fix in markflow.css.
- **Current callers of `--mf-text-xs/sm/body/micro` will visually shrink at non-default text scales** when we drop `* scale` from token defs. Specifically, at `xl` scale: ~12.5px×1.85 → ~12.5px×1.36 = ~7px reduction. This is correcting a bug, not introducing one — call out in version-history so users on xl who memorized the current size aren't surprised.
- **`--mf-text-display-lg` 3.0rem catches a 3.4rem call site with a 6.4px shift.** Largest single shift in the grid; flag for per-site outlier review (the 3.4rem occurrence is a single hero number; a designer may want it preserved as raw rem with a comment).
- **HTML inline `<style>` blocks reference non-`--mf-*` tokens** (`--text`, `--border`, `--surface`, etc.) — pre-existing dead code from before v0.37.0. Out of scope for this refactor; capture in change-index but unchanged.
- **Cache-busting `?v=` query strings on stylesheet links** are inconsistent across legacy pages (some say `v=0.35.0`, some have no version). Unrelated to this refactor; do not touch.

## Branch & version

- **Branch:** `refactor/components-css-theme-aware`, branched from current HEAD (`refactor/markflow-css-theme-aware`, which carries v0.37.1 unpushed)
- **Version target:** **v0.38.0** (theme system completion: legacy + new-UX uniform under one type/scale/font system)
- **Spec doc:** this file
- **Change-index doc:** `docs/superpowers/specs/2026-05-02-components-css-theme-aware-change-index.md`
- **Plan doc:** to be written next (writing-plans skill)

## Loose ends tracked forward

After v0.38.0 ships, these remain on the type-system roadmap:

1. **Tight grid follow-up audit.** With everything tokenized, run a "consolidate" pass — does `--mf-text-base` still need to exist as distinct from `--mf-text-sm`, or has all real usage settled near one of them? Outlier exception sites (sub-icon labels, hero numbers) get the same audit.
2. **Heading tokens for legacy h1/h2/h3.** markflow.css has `h1 { font-size: 1.75rem }` etc. — currently raw, will become tokenized as part of Phase 4. After v0.38.0, the h1 token (1.85rem) drives both new-UX h1 and legacy h1, which may visually differ from today's 1.75rem. Capture in change-index; user signs off as part of Phase 4 visual diff.
3. **Inline `<style>` block cleanup.** ~30 legacy HTML pages have inline styles using pre-v0.37.0 token names (`var(--text)`, `var(--surface)`). These render as undefined post-v0.38.0 just as they did pre-refactor (no functional regression), but they're stale. Separate cleanup pass.
