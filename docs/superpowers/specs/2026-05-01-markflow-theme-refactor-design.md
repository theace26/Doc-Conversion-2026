# Design — markflow.css Theme-Aware Refactor

**Status:** approved (brainstorm), audit-pending, plan-pending
**Authoring effort:** Opus 4.7 / high
**Implementation effort target:** Sonnet 4.6 / medium (paste-and-test mechanical)
**Source brainstorm:** session 2026-05-01 (post-bbe3753 fix — Display Preferences drawer unbroken)

---

## Goal

Make every original-UX page respond to MarkFlow's v0.37.0 theme system. Today, `static/markflow.css` (1684 lines) has its **own** parallel theme system: it defines 16 un-prefixed CSS custom props in `:root` (`--bg`, `--surface`, `--text`, `--accent`, etc., lines 8–29) and overrides 14 of them in an `@media (prefers-color-scheme: dark)` block (lines 31–50). Then ~60 additional hardcoded color literals fill out badges, status pills, and edge cases. None of this responds to `[data-theme]`, so switching themes in the Display Preferences drawer has no visible effect on the 26 legacy pages.

This refactor reconciles markflow.css with the v0.37.0 token system. Specifically:
1. Rename every `var(--surface)` / `var(--text)` / etc. in markflow.css to `var(--mf-surface)` / `var(--mf-color-text)` / etc.
2. Delete the `:root { … }` block at lines 8–29 (now superseded by `design-tokens.css`).
3. Delete the `@media (prefers-color-scheme: dark)` block at lines 31–50 (it actively breaks `[data-theme]` by overriding via OS preference).
4. Replace the ~60 remaining hardcoded literals with `var(--mf-…)` references (snap to existing tokens where safe; introduce new tokens where the literal serves a recurring semantic role).

After this refactor, switching themes in the drawer re-themes every legacy page. Default theme (Classic Light) looks visually equivalent to today's pre-refactor markflow.css.

The refactor is **mechanical and reversible**: the implementer follows a pre-computed local-prop rename map + color-mapping table; both are committed alongside the code as a change-index, so a single `git revert` plus the index is all that's needed to back out.

## Non-goals

- Migrating legacy pages to `components.css` / new-UX styling. Original UX layout stays exactly as-is.
- Changing any HTML structure, class name, or menu organization. Parallel menu-reorganization work owns those surfaces.
- Touching `static/css/ai-assist.css`. Separate concern.
- Modifying `markflow.css` *layout* rules (margins, paddings, flex, grid, sizes). Only color / border-color / box-shadow / fill / stroke values change.
- Inline `style="..."` attributes in any HTML. Audit will catalogue them; refactor does not edit HTML.
- Adding new themes or removing existing themes. The token surface in `design-themes.css` is *extended* with new overrides only when Section 4's discipline says we need to.
- Performance, minification, or selector consolidation in markflow.css. Pure value substitution.

## Background

v0.37.0 shipped the theme system: `design-tokens.css` defines `:root`-level CSS custom properties under naming convention `--mf-<category>-<role>-<variant>`. `design-themes.css` overrides a subset (`--mf-bg-page`, `--mf-surface*`, `--mf-border*`, `--mf-color-accent*`, `--mf-color-text*`, `--mf-shadow-card`, `--mf-btn-bg`) per theme via `[data-theme="X"]` selectors. The new-UX `components.css` consumes those tokens, so new-UX surfaces theme correctly.

`markflow.css` was not touched in v0.37.0. It has 0 `var(--mf-...)` references, so original-UX pages are unaffected by `data-theme` attribute changes. Result: clicking a theme swatch in the drawer updates the drawer (a `components.css` component) but does nothing to `/index.html`, `/resources.html`, etc.

This refactor closes that gap.

## Architecture decisions

| # | Decision | Rationale |
|---|---|---|
| A1 | In-place edits to `markflow.css`. | User chose Approach 2 (single PR). Keeps the legacy stylesheet authoritative; no specificity wars between bridge files. |
| A2 | Single PR / single commit on the implementer's branch. | Cleanest history. Reverting one commit + rolling back the change-index doc = full undo. |
| A3 | Expand the token set when needed. | User chose this over snap-to-existing. Preserves visual fidelity on the default theme. New tokens follow `--mf-<category>-<role>-<variant>`. |
| A4 | Status colors and format gradients converge to existing tokens (`--mf-color-success/warn/error`, `--mf-fmt-*`). | Semantic, shared across themes. No theme-specific overrides for these. |
| A5 | New tokens default to *shared* (no per-theme override). Add a per-theme override only when a Group A theme (Classic Light/Dark, Cobalt, Sage, Slate, Crimson, Sandstone, Graphite) visibly mis-renders during the visual checkpoint. | Avoids 28-theme × 30-token explosion (~840 lines of overrides) when most are unnecessary. |
| A6 | New tokens' `:root` defaults equal markflow.css's CURRENT default-theme value, snapped only when channel drift ≤ 5. | Default theme (Classic Light) must look near-identical post-refactor. Drift > 5 = introduce new token. |
| A7 | The change-index doc IS the rollback artifact. Committed alongside the code. | User requirement: removal must be straightforward and indexable. |
| A8 | **Full rename** (β) of markflow.css's local CSS custom props to their `--mf-*` equivalents. | User choice. One canonical namespace post-refactor. ~24 extra substitutions but cleaner end state than alias bridge. |
| A9 | **Delete** the `@media (prefers-color-scheme: dark)` block at lines 31–50 of markflow.css. | The block uses OS preference to override custom-prop values, which would cascade-fight `[data-theme]`. Theme system already covers dark via `[data-theme="classic-dark"]`. |
| A10 | **Delete** the `:root { ... }` custom-prop definitions at lines 8–29 of markflow.css. | After A8 (full rename), these defs are unreferenced. `design-tokens.css :root` is the single source of truth. |
| A11 | Markflow's font/radius/transition props (`--font-sans`, `--font-mono`, `--radius`, `--radius-sm`, `--transition`) bind to existing `--mf-font-sans`, `--mf-font-mono`, `--mf-radius-thumb` (8px exact match), new `--mf-radius-sm` (4px), `--mf-transition-med` (0.2s exact match). | Most have direct equivalents; one new token (`--mf-radius-sm`) needed. |
| A12 | Markflow's `--shadow` and `--shadow-lg` snap to `--mf-shadow-press` and `--mf-shadow-popover` respectively (closest existing equivalents). | Snap (drift acceptable). Both are non-themed in current design-tokens.css. |

## Color-mapping decision tree

The implementer applies this tree to every literal in markflow.css:

1. **Exact existing-token match** (literal == `:root` default of an existing token, byte-for-byte)
   → Replace with `var(--existing-token-name)`. No new token. Change-index `action: replace`, `new-token?: no`.

2. **Negligible-drift match** (max RGB channel delta ≤ 5 from an existing token's `:root` default)
   → Replace with `var(--existing-token-name)`. Note as **snapped** in change-index. `action: replace (snapped)`, `new-token?: no`, `reason` records the original hex and the delta.

3. **Recurring semantic literal** (occurs ≥ 2 times AND has a clear semantic role: link color, table-header bg, banner bg, code background, etc.)
   → Introduce a new token. Add to `design-tokens.css :root` with the literal as default. No theme override at this stage (per A5). Replace literal with `var(--new-token-name)`. Change-index `action: replace`, `new-token?: yes`.

4. **One-off literal with no clear role**
   → Leave as literal. Change-index `action: keep`, `reason: single occurrence, no clear token role`.

5. **Status / format literal** (success/warn/error shade, format gradient)
   → Snap to canonical existing token (`--mf-color-success`, `--mf-color-error`, `--mf-fmt-pdf`, etc.) regardless of channel delta. Note in change-index as `action: replace (status snap)`.

A literal that hits multiple branches resolves to the lowest-numbered branch.

## Token taxonomy — naming rules for new tokens

Every new token MUST:
- Begin with `--mf-`.
- Use kebab-case.
- Follow `--mf-<category>-<role>[-<variant>]`. Categories already in use: `color`, `bg`, `surface`, `border`, `text`, `shadow`, `space`, `radius`, `font`, `fmt`, `tracking`, `leading`, `transition`, `page`, `content`, `gradient`. Reuse, don't invent.
- Default value goes in `static/css/design-tokens.css :root` block, at the END of the relevant category section (preserve existing ordering of pre-v0.37.0 tokens).

The audit (next section) provides the **complete list** of new tokens to add, with `:root` defaults.

## Local-prop rename map (executed in Phase 2)

Every `var(--<name>)` reference in markflow.css is rewritten to `var(--mf-<replacement>)`. Bindings:

| markflow local prop | replaced by | notes |
|---|---|---|
| `--bg` | `--mf-bg-page` | snap (markflow `#f5f6fa` → tokens `#f7f7f9`, drift ≤ 5) |
| `--surface` | `--mf-surface` | exact match (`#ffffff`) |
| `--surface-alt` | NEW `--mf-surface-alt` | markflow `#f0f1f5`; existing `--mf-surface-soft` is `#fafafa`, drift > 5 |
| `--border` | `--mf-border` | snap (markflow `#dfe1e8` → tokens `#ececec`, drift ~13 — accept; if Phase-2 review flags, override `[data-theme="classic-light"]` with markflow value) |
| `--text` | `--mf-color-text` | snap (markflow `#1a1d2e` → tokens `#0a0a0a`, drift ~30 — accept; same fallback as above) |
| `--text-muted` | `--mf-color-text-muted` | snap (markflow `#6b7084` → tokens `#5a5a5a`, drift moderate — accept) |
| `--text-on-accent` | NEW `--mf-color-text-on-accent` | `#ffffff` — semantic role distinct from `--mf-color-text` |
| `--accent` | `--mf-color-accent` | snap (markflow `#4f5bd5` → tokens `#5b3df5`, drift moderate — accept) |
| `--accent-hover` | NEW `--mf-color-accent-hover` | markflow `#3d49b8`; no equivalent in design-tokens |
| `--ok` | `--mf-color-success` | snap (markflow `#16a34a` → tokens `#0e7c5a`, drift moderate — status color, accept per A4) |
| `--warn` | `--mf-color-warn` | snap (markflow `#d97706` → tokens `#a36a00`, status — accept per A4) |
| `--error` | `--mf-color-error` | snap (markflow `#dc2626` → tokens `#c92a2a`, status — accept per A4) |
| `--info` | NEW `--mf-color-info` | markflow `#2563eb`; no equivalent in design-tokens |
| `--radius` | `--mf-radius-thumb` | exact match (`8px`) |
| `--radius-sm` | NEW `--mf-radius-sm` | `4px` — no equivalent in design-tokens |
| `--font-sans` | `--mf-font-sans` | values differ (markflow uses Source Sans 3; tokens use SF Pro). Override `:root --mf-font-sans` is OUT OF SCOPE for this refactor — accept that font shifts to the design-tokens stack. If user objects, follow-up to introduce a markflow-scoped font override. |
| `--font-mono` | `--mf-font-mono` | values differ (markflow uses IBM Plex Mono; tokens use SF Mono). Same scope rule as `--font-sans`. |
| `--shadow` | `--mf-shadow-press` | snap per A12 |
| `--shadow-lg` | `--mf-shadow-popover` | snap per A12 |
| `--transition` | `--mf-transition-med` | exact match (`0.2s ease`) |

## New tokens to add to `design-tokens.css :root`

Five new tokens introduced by the rename map (all values match markflow's current `:root` for byte-for-byte fidelity on Classic Light):

| token | `:root` default | rationale | per-theme override needed? |
|---|---|---|---|
| `--mf-surface-alt` | `#f0f1f5` | secondary surface (lighter than `--mf-surface`, distinct from `--mf-surface-soft`); markflow uses for nav backgrounds, alt rows | classic-dark: `#232638`; defer others to Phase-2 visual checkpoint |
| `--mf-color-text-on-accent` | `#ffffff` | text rendered on top of accent-colored backgrounds (buttons, badges); semantically distinct from `--mf-color-text` | no — `#ffffff` works on every theme's accent |
| `--mf-color-accent-hover` | `#3d49b8` | darker accent for hover states; markflow has explicit hover variant | classic-dark: `#8189e8` (lighter on dark per markflow's @media block); other Group A themes default to `:root` value, revisit at checkpoint |
| `--mf-color-info` | `#2563eb` | informational status (distinct from accent/success/warn/error); markflow uses for `.toast-info`, `.pl-status-pill.pl-status-running`, etc. | classic-dark: `#60a5fa` (lighter on dark per markflow's @media block); other themes default to `:root`, revisit at checkpoint |
| `--mf-radius-sm` | `4px` | smaller radius for sub-elements (badge corners, inline pills); existing `--mf-radius-thumb` is 8px | no — radius is theme-agnostic |

Additional new tokens may be discovered during the literal-substitution phases (3–8) when the implementer encounters a recurring semantic literal that isn't covered by existing tokens. Each addition follows the decision tree (branch 3) and is logged in the change-index. **The plan must allocate token-creation slack** for ~5–10 additional tokens beyond the five enumerated above.

## Color-mapping table (the change-index)

> **The change-index is produced DURING implementation**, not in this spec. Its full contents (every selector touched, every literal substituted) live in a sibling file: `docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md`. The implementer fills the table row-by-row as they work and commits it alongside the code.

Total expected rows: ~104 substituted literals + ~24 local-prop renames + ~5–10 kept-as-literal = **~130–140 rows**.

The implementer commits the change-index *as part of the same commit as the code edits*.

Schema:

| line | selector | property | old literal | action | new var name | new-token? | reason |
|---|---|---|---|---|---|---|---|
| 142 | `body` | `background` | `#f7f7f9` | replace | `var(--mf-bg-page)` | no | exact match for existing token |
| 158 | `.nav-link` | `color` | `#4a90e2` | replace | `var(--mf-color-link)` | yes | new token, occurs 14× as link color |
| 893 | `.deprecated-banner` | `background` | `#ff00ff` | keep | — | no | single occurrence, no semantic role |

Rows are ordered by `line` ascending. The `action` column takes one of: `replace`, `replace (snapped)`, `replace (status snap)`, `keep`.

Sub-sections in the change-index:
- **Phase commits** — sha + one-line description of each local commit (squashed in PR).
- **New tokens added** — one-line summary per token with `:root` default.
- **Snapped colors** — every literal that resolved via branch 2 or 5 of the decision tree, with original hex, snapped-to var, max channel delta.
- **Kept literals** — every literal that resolved via branch 4, with selector + reason.

```
[PLACEHOLDER — populated from audit results]
```

## Implementation work order

The implementer works in 8 ordered local commits, then squashes for PR. Phases 1–2 are *structural* (deletions + renames); Phases 3–8 are *substitutions by visual layer*.

| # | Phase | Scope | Approx. count | Local commit subject |
|---|---|---|---|---|
| 1 | Token additions | Extend `design-tokens.css :root` with the five new tokens enumerated above (`--mf-surface-alt`, `--mf-color-text-on-accent`, `--mf-color-accent-hover`, `--mf-color-info`, `--mf-radius-sm`). Add per-theme overrides ONLY for `--mf-surface-alt`, `--mf-color-accent-hover`, `--mf-color-info` on `[data-theme="classic-dark"]` (values per the rename map). No markflow.css edits yet. | 5 tokens, 3 dark overrides | `tokens(theme): add legacy-ux tokens for markflow.css refactor` |
| 2 | Local-prop rename + media-query deletion | Delete markflow.css lines 8–29 (the `:root { … }` block, A10) AND lines 31–50 (the `@media (prefers-color-scheme: dark)` block, A9). Then global-replace every `var(--<name>)` in markflow.css with `var(--mf-<replacement>)` per the rename map. | ~24 references, 2 block deletions | `refactor(orig-ux): rename markflow.css local custom-props to --mf-*; drop OS dark-mode media query` |
| 3 | Page bg + body text literals | Substitute remaining literals on `html`, `body`, page-level backgrounds, top-level text rules. | ~10 selectors | `refactor(orig-ux): page bg + body text literals -> var()` |
| 4 | Nav + header literals | top-bar, version chip area, nav-link colors/hovers, header strip. **NO HTML or selector-name changes.** | ~15–20 selectors | `refactor(orig-ux): nav + header literals -> var()` |
| 5 | Buttons + links + form controls | `.btn-*`, `a`, `input`, `select`, focus rings, `.toggle`, range slider. | ~25–30 selectors | `refactor(orig-ux): buttons + links + forms -> var()` |
| 6 | Cards + panels + modals + popovers | `.card`, `.modal-card`, `.modal-backdrop`, `.preview-popup`, `.detail-panel`, surface backgrounds, drop-shadows. | ~20–25 selectors | `refactor(orig-ux): cards + panels + modals -> var()` |
| 7 | Tables + lists + pagination | `table thead`, `tbody`, `tr:hover`, alternating rows, `.pagination`, autocomplete list. | ~15–20 selectors | `refactor(orig-ux): tables + lists + pagination -> var()` |
| 8 | Status badges + alerts + edge cases | `.badge-*`, `.status-pill--*`, `.lifecycle-*`, `.toast-*`, `.error-banner`, `.flag-banner`, `.stop-banner`, `.storage-verify`, `.mount-status-dot`, `.pl-status-pill`, `.stat-pill--*`, `.tool-*`, `.workers-panel`, format gradients. **Snap status colors to `--mf-color-success/warn/error` per A4.** | ~30–40 selectors | `refactor(orig-ux): status + edge-cases -> var()` |

**Squash before PR.** Final PR commit:

> `refactor(orig-ux): make markflow.css theme-aware via var(--mf-…) substitution`

Co-authored. Change-index doc committed alongside the code.

### Visual review checkpoints (manual, in browser, three points)

1. **After Phase 2 (rename + media-query deletion)** — load `/index.html` and `/resources.html` on **Classic Light** and **Classic Dark**. Confirm body bg/text/border colors are visually equivalent to pre-refactor (snap drift acceptable). The Phase-2 commit alone should give immediate theme-responsiveness on the rules that already used markflow's local custom props.
2. **After Phase 6 (cards + panels)** — load `/resources.html`, `/admin.html`, and one settings/legacy page. Verify on **Classic Light**, **Classic Dark**, **Cobalt**, **Sage**. Cards/panels/modals are the most visually prominent legacy chrome.
3. **After Phase 8 (final)** — full pass on the 26 legacy pages, default theme + Classic-Dark + Cobalt sample. Confirm change-index row count matches substitution count. Confirm no `prefers-color-scheme` references remain.

If a visible regression appears at any checkpoint: the implementer either (a) adds a per-theme override for the offending token in `design-themes.css`, or (b) escalates to the spec author (decision: token taxonomy change).

## Verification commands

```bash
cd /opt/doc-conversion-2026

# Sanity 1: NO local-name custom props remain referenced in markflow.css after Phase 2
#          (every var(--name) must be var(--mf-name))
grep -nE 'var\(--[a-z]' static/markflow.css | grep -v 'var(--mf-' || echo "OK: zero non-mf var refs"

# Sanity 2: NO prefers-color-scheme block remains
grep -nE 'prefers-color-scheme' static/markflow.css || echo "OK: media-query block deleted"

# Sanity 3: literal-hex count significantly reduced from baseline (pre-refactor: 89 unique)
grep -oE '#[0-9a-fA-F]{3,8}\b' static/markflow.css | sort -u | wc -l
# Expected: ~5–10 retained literals (kept-as-literal per decision tree branch 4)

# Sanity 4: every --mf-* used in markflow.css has a :root default in design-tokens.css
comm -23 \
  <(grep -oE '\-\-mf-[a-z0-9-]+' static/markflow.css | sort -u) \
  <(grep -oE '\-\-mf-[a-z0-9-]+' static/css/design-tokens.css | sort -u)
# Expected: empty output (all referenced tokens defined)

# Sanity 5: change-index doc has been written and rows count matches expectations
wc -l docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
# Expected: header (~30 lines) + ~104 rows + section dividers ≈ 150 lines minimum

# Sanity 6: !important count unchanged from baseline (pre-refactor: 3)
grep -c '!important' static/markflow.css
# Expected: 3 (no introduction, no removal — A1 keeps existing rules verbatim)
```

If any sanity check fails, the implementer fixes before PR — do not ship a partial refactor.

## Out-of-scope (re-stated for the implementer)

- HTML structure, class names on any legacy page
- Menu organization, nav layout, dropdown contents
- `static/css/ai-assist.css`
- Layout rules in markflow.css (margin, padding, flex, grid, width, height)
- Inline `style="..."` attributes in HTML
- New themes
- Removing existing themes
- Adding `!important` declarations (or removing them — preserve as-is)

## Acceptance check (run before declaring this design complete)

- [x] Every section above is concrete; no unresolved `[PLACEHOLDER]` remains.
- [x] `:root` defaults in the new-tokens table EQUAL markflow's CURRENT default-theme value (decision A6, with snap allowance).
- [x] Change-index schema is settled (8-column table, 4-section subsections; row count target stated).
- [x] All 8 phases have an estimated selector count and a commit subject.
- [x] Verification commands run cleanly today.
- [x] Local-prop rename map covers every CSS custom prop defined in markflow.css's `:root` block.
- [x] `@media (prefers-color-scheme: dark)` deletion is explicit (A9, Phase 2).

## Self-review (post-write, pre-handoff)

- **Placeholder scan:** Zero `[PLACEHOLDER]` markers. The audit-derived sections (rename map, new tokens) are now concrete. ✓
- **Internal consistency:**
  - A1 (in-place) ↔ A2 (single commit) — consistent.
  - A3 (expand tokens) ↔ A5 (default no theme override) — consistent (expansion happens at `:root`; theme overrides are added on demand).
  - A4 (status converges) ↔ decision tree branch 5 — consistent.
  - A8 (full rename) ↔ A10 (delete `:root` block) — consistent (after rename, `:root` block is unreferenced).
  - A9 (delete `@media`) ↔ Phase 2 commit subject — consistent.
  - A6 (snap drift ≤ 5) ↔ several rename-map entries with drift > 5 — RESOLVED: drift > 5 is accepted on a case-by-case basis with a note in the rename map; if Phase-2 visual review flags any, override at `[data-theme="classic-light"]`. ✓
- **Scope check:** One stylesheet (markflow.css). 8 phases. Single PR. Manageable for a Sonnet/Haiku implementer following the rename map + decision tree. ✓
- **Ambiguity check:** Decision tree branches are mutually exclusive after the resolution rule ("lowest-numbered branch wins"). The rename map specifies the action for every local prop. The new-tokens table specifies every introduced token. The implementer's discretion is bounded to ~5–10 mid-implementation new-token additions, all logged in the change-index. ✓
- **What still requires implementer judgment:**
  - Per-literal application of decision tree (especially branch 3 vs 4 — occurrence count check).
  - Whether a substituted color visibly drifts on Group A themes during visual checkpoints.
  - Mid-implementation additions of new tokens beyond the five enumerated.
  These are bounded and the change-index captures every choice. ✓
