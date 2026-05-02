# Change Index — MarkFlow CSS Theme-Aware Refactor

> **Rollback artifact.** Each row records one substitution, rename, or deletion in `static/markflow.css` (and supporting files). Reverting the squashed refactor commit + deleting this file restores pre-refactor state.

**Plan:** [`docs/superpowers/plans/2026-05-01-markflow-theme-refactor.md`](../plans/2026-05-01-markflow-theme-refactor.md)
**Spec:** [`docs/superpowers/specs/2026-05-01-markflow-theme-refactor-design.md`](2026-05-01-markflow-theme-refactor-design.md)

---

## Phase commits (local, before squash)

| sha | task | description |
|-----|------|-------------|
| _filled_ | 2 | tokens(theme): add 5 new --mf-* tokens for legacy-ux refactor |
| _filled_ | 3 | tokens(theme): add classic-dark overrides for new tokens |
| _filled_ | 4 | refactor(orig-ux): delete markflow.css :root + main @media block |
| _filled_ | 5 | refactor(orig-ux): convert 6 remaining @media blocks to [data-theme="classic-dark"] |
| _filled_ | 6 | refactor(orig-ux): rename markflow.css local custom-props to --mf-* |
| _filled_ | 7 | refactor(orig-ux): page bg + body text literals -> var() |
| _filled_ | 8 | refactor(orig-ux): nav + header literals -> var() |
| _filled_ | 9 | refactor(orig-ux): buttons + forms literals -> var() |
| _filled_ | 10 | refactor(orig-ux): cards + panels + modals literals -> var() |
| _filled_ | 11 | refactor(orig-ux): tables + lists + pagination literals -> var() |
| _filled_ | 12 | refactor(orig-ux): status + edge-case literals -> var() |

## New tokens added

| token | :root default | added in design-themes.css? | rationale |
|-------|---------------|-----------------------------|-----------|
| `--mf-surface-alt` | `#f0f1f5` | yes (classic-dark: `#232638`) | secondary surface; replaces markflow's `--surface-alt` |
| `--mf-color-text-on-accent` | `#ffffff` | no | text on accent-colored backgrounds; replaces markflow's `--text-on-accent` |
| `--mf-color-accent-hover` | `#3d49b8` | yes (classic-dark: `#8189e8`) | hover state for accent; replaces markflow's `--accent-hover` |
| `--mf-color-accent-glow` | `rgba(91,61,245,0.4)` | no | toggle on-state shadow glow; aligned to accent hue (was `rgba(99,102,241,.4)`); task 10 |
| `--mf-color-info` | `#2563eb` | yes (classic-dark: `#60a5fa`) | info status; replaces markflow's `--info` |
| `--mf-radius-sm` | `4px` | no | small radius; replaces markflow's `--radius-sm` |
| `--mf-shadow-press` (existing) | n/a (already in design-tokens.css) | yes (classic-dark: `0 1px 3px rgba(0,0,0,.3)`) | dark-mode shadow override; preserves markflow's @media (prefers-color-scheme: dark) shadow |
| `--mf-shadow-popover` (existing) | n/a (already in design-tokens.css) | yes (classic-dark: `0 4px 12px rgba(0,0,0,.4)`) | dark-mode shadow override; preserves markflow's @media (prefers-color-scheme: dark) shadow-lg |

## Deleted blocks

| line range (pre-delete) | description | reason | task # |
|-------------------------|-------------|--------|--------|
| 7–50 | `:root { … }` + main `@media (prefers-color-scheme: dark) { :root { … } }` | local custom-prop system superseded by `design-tokens.css` + `[data-theme]` | 4 |

## Converted @media blocks (prefers-color-scheme → [data-theme="classic-dark"])

| pre-Task-4 line | post-Task-4 line | block content | new selector pattern | task # |
|-----------------|------------------|---------------|----------------------|--------|
| 270 | 226 | `.badge-docx/.badge-pdf/.badge-pptx/.badge-xlsx/.badge-csv/.badge-tsv/.badge-md` | `html[data-theme="classic-dark"] .badge-…` | 5 |
| 350 | 306 | `.storage-verify .sv-*` (5 selectors) | `html[data-theme="classic-dark"] .storage-verify .sv-…` | 5 |
| 1168 | 1124 | `.flag-banner` | `html[data-theme="classic-dark"] .flag-banner` | 5 |
| 1231 | 1187 | `.stop-banner`, `.stop-banner__text` | `html[data-theme="classic-dark"] .stop-banner…` | 5 |
| 1384 | 1340 | `.tool-fast/.tool-slow/.tool-danger` | `html[data-theme="classic-dark"] .tool-…` | 5 |
| 1402 | 1358 | `.db-tool-ok`, `.db-tool-error` | `html[data-theme="classic-dark"] .db-tool-…` | 5 |

## Local-prop rename map applied

| markflow local prop | replaced by | occurrence count in markflow.css |
|---------------------|-------------|----------------------------------|
| `--text-on-accent` | `--mf-color-text-on-accent` | 4 |
| `--text-muted` | `--mf-color-text-muted` | 45 |
| `--text` | `--mf-color-text` | 76 |
| `--bg` | `--mf-bg-page` | 4 |
| `--surface-alt` | `--mf-surface-alt` | 26 |
| `--surface` | `--mf-surface` | 43 |
| `--border` | `--mf-border` | 48 |
| `--accent-hover` | `--mf-color-accent-hover` | 1 |
| `--accent` | `--mf-color-accent` | 39 |
| `--ok` | `--mf-color-success` | 11 |
| `--warn` | `--mf-color-warn` | 9 |
| `--error` | `--mf-color-error` | 17 |
| `--info` | `--mf-color-info` | 3 |
| `--radius-sm` | `--mf-radius-sm` | 17 |
| `--radius` | `--mf-radius-thumb` | 25 |
| `--font-sans` | `--mf-font-sans` | 5 |
| `--font-mono` | `--mf-font-mono` | 8 |
| **REVISED:** `--font-sans` | `--mf-font-family` (NOT `--mf-font-sans`; 5 occurrences) | 5 | spec A11 mapped to `--mf-font-sans` but that token isn't theme-overridden by `[data-font]`; `--mf-font-family` is. Rebound in fixup commit. |
| `--shadow-lg` | `--mf-shadow-popover` | 4 |
| `--shadow` | `--mf-shadow-press` | 2 |
| `--transition` | `--mf-transition-med` | 9 |

## Snapped colors (decision tree branch 2 / 5)

| original literal | snapped to | max RGB drift | reason |
|------------------|------------|---------------|--------|
| `var(--bg-tertiary,#252540)` (line 1488, `.stat-pill`) | `var(--mf-surface-alt)` | ~5 (vs classic-dark default `#232638`) | dead-code reference to undefined var; fallback `#252540` was always winning. Snapped because `--bg-tertiary` was never defined in markflow.css :root |
| `var(--text-secondary,#aaa)` (line 1488, `.stat-pill`) | `var(--mf-color-text-fainter)` | 0 (exact match — `#aaaaaa`) | dead-code reference to undefined var; fallback `#aaa` was always winning. Exact match to existing `--mf-color-text-fainter` |
| `html { font-size: 16px }` (line 11) | `html { font-size: calc(16px * var(--mf-text-scale, 1)) }` | n/a (formula change) | wires legacy pages into the `[data-text-scale]` system; all rem-based sizes downstream now scale with the drawer's text-size selection. Bug fix from Phase-2 visual checkpoint #1 |
| `rgba(79,91,213,.08)` (line 91, `.nav-link--active`) | `var(--mf-color-accent-tint)` | ~5 (accent `#4f5bd5` vs `#5b3df5`; tint `#f3f0ff` is lightest representation) | accent-at-low-alpha active bg; spec explicitly calls out snap to `--mf-color-accent-tint`; task 9 |
| `rgba(79,91,213,.15)` (line 404, `.form-group input:focus` etc.) | `var(--mf-color-accent-ring)` | acceptable per spec plan guidance | focus ring shadow; spec instructs snap to `--mf-color-accent-ring`; task 10 |

## Substitutions (decision tree branch 1)

| line | selector | property | old literal | new var | new-token? | task # |
|------|----------|----------|-------------|---------|------------|--------|
| 470 | `.toggle input:checked + .toggle-track` | `box-shadow` | `rgba(99,102,241,.4)` | `var(--mf-color-accent-glow)` | yes | 10 |
| 475 | `.toggle input:checked + .toggle-track::after` | `background` | `#fff` | `var(--mf-color-text-on-accent)` | no (existing) | 10 |
| 522 | `.toast-success` | `color` | `white` | `var(--mf-color-text-on-accent)` | no (existing) | 11 |
| 523 | `.toast-error` | `color` | `white` | `var(--mf-color-text-on-accent)` | no (existing) | 11 |
| 524 | `.toast-info` | `color` | `white` | `var(--mf-color-text-on-accent)` | no (existing) | 11 |

## Kept literals (decision tree branch 4)

| line | selector | property | literal | reason |
|------|----------|----------|---------|--------|
| 125 | `.btn` | `border` | `transparent` | CSS keyword, not a color; no token needed |
| 147 | `.btn-ghost` | `background` | `transparent` | CSS keyword, not a color; no token needed |
| 446 | `.toggle-track` | `background` | `rgba(255,255,255,.08)` | theme-agnostic UI overlay (toggle off-state track); spec instructs keep |
| 447 | `.toggle-track` | `border` | `rgba(255,255,255,.15)` | theme-agnostic UI overlay (toggle off-state track border); spec instructs keep |
| 462 | `.toggle-track::after` | `background` | `rgba(255,255,255,.35)` | theme-agnostic UI overlay (toggle off-state thumb); spec instructs keep |
| 463 | `.toggle-track::after` | `box-shadow` | `rgba(0,0,0,.3)` | shadow; spec instructs keep |
| 476 | `.toggle input:checked + .toggle-track::after` | `box-shadow` | `rgba(0,0,0,.25)` | shadow; spec instructs keep |
| 530 | `.dialog-backdrop` | `background` | `rgba(0,0,0,.4)` | theme-agnostic modal overlay; spec instructs keep |
| 637 | `.drop-zone:hover, .drop-zone.drag-over` | `background` | `rgba(79,91,213,.04)` | drift vs `--mf-color-accent-tint` is 8 (> 5 threshold); keep as literal |
| 646 | `.error-banner` | `background` | `rgba(220,38,38,.08)` | drift vs `--mf-color-error-bg` is 6 (> 5 threshold); semi-transparent overlay has no solid token match |
| 647 | `.error-banner` | `border` | `rgba(220,38,38,.2)` | semi-transparent error border; no solid token match; keep as literal |
| 748 | `.ocr-banner` | `background` | `rgba(245,158,11,.08)` | snapped to `var(--mf-color-warn-bg)` in task 13 (A4 mandate — warn-tone) |
| 749 | `.ocr-banner` | `border` | `rgba(245,158,11,.2)` | snapped to `var(--mf-color-warn)` border in task 13 (A4 mandate — warn-tone) |
| 764 | `.reconnecting` | `background` | `rgba(245,158,11,.1)` | snapped to `var(--mf-color-warn-bg)` in task 13 (A4 mandate — warn-tone) |

## Phase 8 substitutions (task 13)

### Snapped colors (branch 2/5)

| original literal | snapped to | context | task # |
|-----------------|------------|---------|--------|
| `rgba(22,163,74,.12)` (`.status-ok/success` bg) | `var(--mf-color-success-bg)` | success status badge bg | 13 |
| `rgba(220,38,38,.1)` (`.status-error` bg) | `var(--mf-color-error-bg)` | error status badge bg | 13 |
| `rgba(217,119,6,.1)` (`.status-warn` bg) | `var(--mf-color-warn-bg)` | warn status badge bg | 13 |
| `#fee2e2; #991b1b` (`.badge-pdf`) | `var(--mf-color-error-bg); var(--mf-color-error)` | error-toned format badge | 13 |
| `#fef3c7; #92400e` (`.badge-pptx`) | `var(--mf-color-warn-bg); var(--mf-color-warn)` | warn-toned format badge | 13 |
| `#dcfce7; #166534` (`.badge-xlsx`) | `var(--mf-color-success-bg); var(--mf-color-success)` | success-toned format badge | 13 |
| `#e0e7ff; #3730a3` (`.badge-csv`) | `var(--mf-color-accent-tint); var(--mf-color-accent)` | accent-toned format badge | 13 |
| `#ede9fe; #5b21b6` (`.badge-tsv`) | `var(--mf-color-accent-tint-2); var(--mf-color-accent)` | accent-toned format badge | 13 |
| `#f0f0f0; #374151` (`.badge-md`) | `var(--mf-surface-alt); var(--mf-color-text-soft)` | neutral format badge | 13 |
| `#dcfce7; #15803d` (`.sv-ok`) | `var(--mf-color-success-bg); var(--mf-color-success)` | storage-verify ok icon | 13 |
| `#fee2e2; #b91c1c` (`.sv-bad`) | `var(--mf-color-error-bg); var(--mf-color-error)` | storage-verify bad icon | 13 |
| `#15803d` (`.sv-ok-sub`) | `var(--mf-color-success)` | storage-verify ok sub-text | 13 |
| `#b91c1c` (`.sv-bad-sub`) | `var(--mf-color-error)` | storage-verify bad sub-text | 13 |
| `#a16207` (`.sv-warn`) | `var(--mf-color-warn)` | storage-verify warn text (A4 snap) | 13 |
| `rgba(220,38,38,.08); rgba(220,38,38,.2)` (`.error-banner`) | `var(--mf-color-error-bg); var(--mf-color-error)` | error banner bg/border | 13 |
| `rgba(217,119,6,0.08); rgba(217,119,6,0.25)` (`.deletion-banner`) | `var(--mf-color-warn-bg); var(--mf-color-warn)` | deletion warning banner | 13 |
| `rgba(245,158,11,.08); rgba(245,158,11,.2)` (`.ocr-banner`) | `var(--mf-color-warn-bg); var(--mf-color-warn)` | OCR banner bg/border | 13 |
| `rgba(245,158,11,.1)` (`.reconnecting`) | `var(--mf-color-warn-bg)` | reconnecting badge bg | 13 |
| `#fff` (`.nav-badge color`) | `var(--mf-color-text-on-accent)` | nav badge text | 13 |
| `#fff8e1; #f9a825; #5d4037` (`.flag-banner`) | `var(--mf-color-warn-bg); var(--mf-color-warn); var(--mf-color-text-soft)` | flag banner light variant | 13 |
| `#fff3e0; #f9a825` (`.stop-banner`) | `var(--mf-color-warn-bg); var(--mf-color-warn)` | stop banner bg/border | 13 |
| `#e65100` (`.stop-banner__text`) | `var(--mf-color-warn)` | stop banner text (A4 snap) | 13 |
| pl-status-pill ok/warn/err/muted bg+color (5 rules) | status-bg tokens + status text tokens | pipeline status pills | 13 |
| `rgba(99,102,241,0.06)` (`.job-card__progress-link:hover`) | `var(--mf-color-accent-tint)` | job card hover | 13 |
| `rgba(99,102,241,0.12)` (`.job-card__open-link:hover`) | `var(--mf-color-accent-tint)` | job card open link hover | 13 |
| `#7c4dff` (`.status-pill--scanning`) | `var(--mf-color-accent-soft)` | scanning status pill | 13 |
| `#fff` (`.status-pill--running/paused/done/completed/failed color`) | `var(--mf-color-text-on-accent)` | status pill text on color | 13 |
| `#fff` (`.btn-danger-outline:hover color`) | `var(--mf-color-text-on-accent)` | danger outline button hover | 13 |
| `#ef9a9a` (`.db-tool-card-danger border-color`) | `var(--mf-color-error)` | danger tool card border | 13 |
| `#e8f5e9; #2e7d32` (`.tool-fast`) | `var(--mf-color-success-bg); var(--mf-color-success)` | fast tool badge | 13 |
| `#fff3e0; #e65100` (`.tool-slow`) | `var(--mf-color-warn-bg); var(--mf-color-warn)` | slow tool badge | 13 |
| `#ffebee; #c62828` (`.tool-danger`) | `var(--mf-color-error-bg); var(--mf-color-error)` | danger tool badge | 13 |
| `#e8f5e9; #1b5e20` (`.db-tool-ok`) | `var(--mf-color-success-bg); var(--mf-color-success)` | db tool ok result | 13 |
| `#ffebee; #b71c1c` (`.db-tool-error`) | `var(--mf-color-error-bg); var(--mf-color-error)` | db tool error result | 13 |
| `#d32f2f; #fff` (`.btn-danger`) | `var(--mf-color-error); var(--mf-color-text-on-accent)` | danger button | 13 |
| stat-pill analysis/batched/afailed/indexed (4 rules bg+color) | accent-tint/warn-bg/error-bg/success-bg + text tokens | stat pills | 13 |
| `rgba(79,91,213,0.15)` (`.status-pill--pending`) | `var(--mf-color-accent-tint)` | pending status pill | 13 |
| `#888` (`.mount-status-dot` default) | `var(--mf-color-text-faint)` | mount status dot unknown | 13 |
| `#4ade80` (`.mount-status-dot.ok`) | `var(--mf-color-success)` | mount status dot ok | 13 |
| `#f87171` (`.mount-status-dot.err`) | `var(--mf-color-error)` | mount status dot error | 13 |
| `#b45309; #fff8e7` (`.restart-banner`) | `var(--mf-color-warn); var(--mf-color-text-on-accent)` | restart banner bg/color | 13 |

### Kept literals (phase 8, branch 4)

| line | selector | property | literal | reason |
|------|----------|----------|---------|--------|
| 203 | `.status-info` | `background` | `rgba(37,99,235,.1)` | no `--mf-color-info-bg` token; spec says don't introduce new status tokens |
| 219 | `.badge-docx` | `background/color` | `#dbeafe; #1e40af` | blue/info toned; no `--mf-color-info-bg` token exists |
| 261–262 | `.sv-pending` | `background/color` | `rgba(96,165,250,0.18); #3b82f6` | info/running blue; no matching info token; single occurrence |
| 1293 | `.status-pill--stopped/cancelled` | `background` | `#9e9e9e` | neutral grey; no grey token in design system |
| 1363 | `.btn-danger:hover` | `background` | `#b71c1c` | darker error hover; no `--mf-color-error-hover` token |
| all shadow/overlay rgba | various | box-shadow/backdrop | `rgba(0,0,0,…)` / `rgba(255,255,255,…)` | shadows and overlays; theme-agnostic; spec instructs keep |
