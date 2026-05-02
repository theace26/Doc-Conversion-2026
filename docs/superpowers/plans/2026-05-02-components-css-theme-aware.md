# components.css Theme-Aware Refactor Implementation Plan (v0.38.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three gaps left by v0.37.1 — the font picker bypass on new-UX, the latent v0.37.1 import regression on legacy pages, and font-size drift across 311 raw rem literals — by tokenizing both files into a single 11-token grid.

**Architecture:** Single PR on a feature branch. ~14 ordered local commits, squashed before PR. Sub-tasks split components.css and markflow.css into 4 ranges each so substitution stays bite-sized. A change-index sidecar doc captures every per-site decision (rollback artifact).

**Tech Stack:** Pure CSS. Bash + grep + sed for substitution. Browser-based manual visual review at three checkpoints. No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-05-02-components-css-theme-aware-design.md`](../specs/2026-05-02-components-css-theme-aware-design.md)

---

## Model + effort (overall)

| Role | Model | Effort |
|------|-------|--------|
| Implementer (default) | Sonnet 4.6 | medium (4–6h) |
| Reviewer (default) | Sonnet 4.6 | low (2h) |

**Reasoning:** Plan is paste-and-test mechanical. Substitution mapping is pre-computed (Section "Substitution mapping" below). Implementer's discretion is bounded to the ~33 outlier sites in Task 12, where Sonnet 4.6 / high effort is appropriate. Reviewer checks grep output, visual checkpoints, and the change-index doc.

**Execution mode:** Dispatch via `superpowers:subagent-driven-development`. User reviews at visual checkpoints (after Tasks 1, 3, 7, 11, 13).

## Per-task model + effort routing

| Task | Phase | Implementer | Effort | Why |
|---|---|---|---|---|
| 0 | Phase 0 | Sonnet 4.6 | low | 2-line edit + browser verification |
| 1 | Phase 1a | Sonnet 4.6 | low | Token def replacement, exact code given |
| 2 | Phase 1b | Sonnet 4.6 | low | Move 1 line + add deprecation comment |
| 3 | Phase 2 | Sonnet 4.6 | low | Single sed across components.css |
| 4 | Phase 3a | Sonnet 4.6 | medium | Substitution by selector group |
| 5 | Phase 3b | Sonnet 4.6 | medium | Substitution by selector group |
| 6 | Phase 3c | Sonnet 4.6 | medium | Substitution by selector group |
| 7 | Phase 3d | Sonnet 4.6 | medium | Substitution by selector group |
| 8 | Phase 4a | Sonnet 4.6 | medium | Substitution by section |
| 9 | Phase 4b | Sonnet 4.6 | medium | Substitution by section |
| 10 | Phase 4c | Sonnet 4.6 | medium | Substitution by section |
| 11 | Phase 4d | Sonnet 4.6 | medium | Substitution by section |
| 12 | Phase 5 | Sonnet 4.6 | high | Per-site outlier judgment |
| 13 | Phase 6 | Sonnet 4.6 | medium | Visual sweep + release docs |

---

## Substitution mapping (used by Tasks 4–11)

This is the canonical sed mapping. Apply **only inside `font-size:` declarations** — do NOT touch `padding`, `margin`, `gap`, etc. that may share rem values.

| Literal | Token | sed pattern (extended regex) |
|---|---|---|
| `0.66rem` | `var(--mf-text-2xs)` | `s/font-size:\s*0\.66rem/font-size: var(--mf-text-2xs)/g` |
| `0.68rem` | `var(--mf-text-2xs)` | `s/font-size:\s*0\.68rem/font-size: var(--mf-text-2xs)/g` |
| `0.7rem` | `var(--mf-text-2xs)` | `s/font-size:\s*0\.7rem/font-size: var(--mf-text-2xs)/g` |
| `0.72rem` | `var(--mf-text-2xs)` | `s/font-size:\s*0\.72rem/font-size: var(--mf-text-2xs)/g` |
| `0.74rem` | `var(--mf-text-2xs)` | `s/font-size:\s*0\.74rem/font-size: var(--mf-text-2xs)/g` |
| `0.75rem` | `var(--mf-text-2xs)` | `s/font-size:\s*0\.75rem/font-size: var(--mf-text-2xs)/g` |
| `0.76rem` | `var(--mf-text-2xs)` | `s/font-size:\s*0\.76rem/font-size: var(--mf-text-2xs)/g` |
| `0.78rem` | `var(--mf-text-xs)` | `s/font-size:\s*0\.78rem/font-size: var(--mf-text-xs)/g` |
| `0.8rem` | `var(--mf-text-sm)` | `s/font-size:\s*0\.8rem/font-size: var(--mf-text-sm)/g` |
| `0.82rem` | `var(--mf-text-sm)` | `s/font-size:\s*0\.82rem/font-size: var(--mf-text-sm)/g` |
| `0.84rem` | `var(--mf-text-sm)` | `s/font-size:\s*0\.84rem/font-size: var(--mf-text-sm)/g` |
| `0.85rem` | `var(--mf-text-base)` | `s/font-size:\s*0\.85rem/font-size: var(--mf-text-base)/g` |
| `0.86rem` | `var(--mf-text-base)` | `s/font-size:\s*0\.86rem/font-size: var(--mf-text-base)/g` |
| `0.875rem` | `var(--mf-text-base)` | `s/font-size:\s*0\.875rem/font-size: var(--mf-text-base)/g` |
| `0.88rem` | `var(--mf-text-base)` | `s/font-size:\s*0\.88rem/font-size: var(--mf-text-base)/g` |
| `0.9rem` | `var(--mf-text-body)` | `s/font-size:\s*0\.9rem/font-size: var(--mf-text-body)/g` |
| `0.92rem` | `var(--mf-text-body)` | `s/font-size:\s*0\.92rem/font-size: var(--mf-text-body)/g` |
| `0.95rem` | `var(--mf-text-body)` | `s/font-size:\s*0\.95rem/font-size: var(--mf-text-body)/g` |
| `0.96rem` | `var(--mf-text-body)` | `s/font-size:\s*0\.96rem/font-size: var(--mf-text-body)/g` |
| `1rem` | `var(--mf-text-md)` | `s/font-size:\s*1rem\b/font-size: var(--mf-text-md)/g` |
| `1.0rem` | `var(--mf-text-md)` | `s/font-size:\s*1\.0rem/font-size: var(--mf-text-md)/g` |
| `1.2rem` | `var(--mf-text-h3)` | `s/font-size:\s*1\.2rem/font-size: var(--mf-text-h3)/g` |
| `1.35rem` | `var(--mf-text-h2)` | `s/font-size:\s*1\.35rem/font-size: var(--mf-text-h2)/g` |
| `1.4rem` | `var(--mf-text-h2)` | `s/font-size:\s*1\.4rem/font-size: var(--mf-text-h2)/g` |
| `1.85rem` | `var(--mf-text-h1)` | `s/font-size:\s*1\.85rem/font-size: var(--mf-text-h1)/g` |
| `2.3rem` | `var(--mf-text-display)` | `s/font-size:\s*2\.3rem/font-size: var(--mf-text-display)/g` |
| `2.4rem` | `var(--mf-text-display)` | `s/font-size:\s*2\.4rem/font-size: var(--mf-text-display)/g` |
| `2.5rem` | `var(--mf-text-display)` | `s/font-size:\s*2\.5rem/font-size: var(--mf-text-display)/g` |
| `3rem` | `var(--mf-text-display-lg)` | `s/font-size:\s*3rem\b/font-size: var(--mf-text-display-lg)/g` |
| `3.0rem` | `var(--mf-text-display-lg)` | `s/font-size:\s*3\.0rem/font-size: var(--mf-text-display-lg)/g` |

**DO NOT substitute these in Tasks 4–11** — they are outliers handled in Task 12:
- `0.5rem`, `0.55rem`, `0.56rem`, `0.6rem`, `0.62rem`, `0.65rem`
- `1.05rem`, `1.1rem`, `1.15rem`, `1.25rem`, `1.3rem`
- `1.7rem`, `1.75rem`, `1.8rem`
- `3.4rem`

---

## Task 0: Phase 0 — Add @imports to markflow.css (foundation fix)

**Files:**
- Modify: `static/markflow.css:1-6`

**Why first:** Closes the v0.37.1 import regression. Without this, every later phase compounds onto a broken foundation.

- [ ] **Step 1: Verify current state — confirm the regression**

Run: `grep -nE "@import" static/markflow.css`
Expected: only one match — the Google Fonts URL on line 5. No design-tokens or design-themes imports.

- [ ] **Step 2: Edit `static/markflow.css` lines 1–5**

Find:
```css
/* MarkFlow — Shared Design System
   Imported by all user-facing pages. Debug dashboard excluded. */

/* ── Fonts ──────────────────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
```

Replace with:
```css
/* MarkFlow — Shared Design System
   Imported by all user-facing pages. Debug dashboard excluded. */

/* ── Token system (v0.38.0: required for legacy pages to receive --mf-* defs and [data-theme] overrides) ─ */
@import url('./css/design-tokens.css');
@import url('./css/design-themes.css');

/* ── Fonts ──────────────────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
```

- [ ] **Step 3: Verify edit**

Run: `head -10 static/markflow.css`
Expected: 3 @import lines visible (2 design + 1 fonts).

- [ ] **Step 4: Browser verification — MANDATORY GATE**

Restart the container if needed:
```bash
docker compose -f /opt/doc-conversion-2026/docker-compose.yml restart markflow
sleep 3
curl -s -I http://localhost:8000/static/markflow.css | head -1
```
Expected: `HTTP/1.1 200 OK`

In a browser (NOT just curl — needs JS to apply theme):
1. Open `http://<VM_IP>:8000/static/status.html` in a fresh incognito/private window
2. Open DevTools → Application → Local Storage → clear `mf:preferences:v1`
3. Reload — note the page colors (Classic Light defaults)
4. Open `http://<VM_IP>:8000/static/settings-appearance.html`, change theme to Classic Dark
5. Return to status.html, reload
6. **Verify:** status.html now renders with Classic Dark colors (dark background, light text)

If theme switching has no visible effect on legacy pages: STOP. The import path is wrong; debug before continuing.

- [ ] **Step 5: Commit**

```bash
git add static/markflow.css
git commit -m "fix(markflow.css): @import design-tokens + design-themes (Phase 0)

Closes v0.37.1 latent regression: legacy HTML pages link only
markflow.css and Google Fonts, never design-tokens.css or
design-themes.css. After v0.37.1 deleted markflow.css's local
:root block and renamed all 302 var refs to --mf-*, those refs
were undefined on legacy pages — and [data-theme] overrides
never reached them.

Adding the two @imports at the top of markflow.css gives legacy
pages the full token system without changing any HTML.

Browser-verified: theme switching now visibly re-themes
status.html, history.html, and other legacy pages."
```

---

## Task 1: Phase 1a — Update design-tokens.css with new 11-token grid

**Files:**
- Modify: `static/css/design-tokens.css:63-76`

- [ ] **Step 1: Verify current token block**

Run: `sed -n '63,76p' static/css/design-tokens.css`
Expected output:
```
  /* === Type === */
  --mf-font-sans:    -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif;
  --mf-font-serif:   "Iowan Old Style", "Charter", "Cambria", Georgia, serif;
  --mf-font-mono:    ui-monospace, "SF Mono", Menlo, monospace;

  --mf-text-display:    2.4rem;
  --mf-text-display-sm: 2.0rem;
  --mf-text-h1:         1.85rem;
  --mf-text-h2:         1.4rem;
  --mf-text-h3:         1.05rem;
  --mf-text-body:       calc(0.94rem * var(--mf-text-scale));
  --mf-text-sm:         calc(0.86rem * var(--mf-text-scale));
  --mf-text-xs:         calc(0.78rem * var(--mf-text-scale));
  --mf-text-micro:      calc(0.7rem  * var(--mf-text-scale));
```

- [ ] **Step 2: Edit `static/css/design-tokens.css` lines 63–76**

Replace the block above with:
```css
  /* === Type === */
  /* DEPRECATED in v0.38.0: --mf-font-sans is a hardcoded fallback that bypasses the font picker.
     Picker-bound token is --mf-font-family (defined at line 11; overridden by [data-font="..."]).
     Kept here as a safety net for any external/legacy consumer; no MarkFlow code should reference it. */
  --mf-font-sans:    -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif;
  --mf-font-serif:   "Iowan Old Style", "Charter", "Cambria", Georgia, serif;
  --mf-font-mono:    ui-monospace, "SF Mono", Menlo, monospace;

  /* Text-size grid (v0.38.0). Plain rem values; --mf-text-scale applies once via
     html { font-size: calc(16px * --mf-text-scale) } in design-themes.css. Do NOT
     re-introduce `* var(--mf-text-scale)` in these defs — that creates double-scaling. */
  --mf-text-2xs:        0.7rem;
  --mf-text-xs:         0.78rem;
  --mf-text-sm:         0.82rem;
  --mf-text-base:       0.86rem;
  --mf-text-body:       0.92rem;
  --mf-text-md:         1.0rem;
  --mf-text-h3:         1.2rem;
  --mf-text-h2:         1.4rem;
  --mf-text-h1:         1.85rem;
  --mf-text-display:    2.4rem;
  --mf-text-display-lg: 3.0rem;
```

Note: `--mf-text-display-sm` and `--mf-text-micro` are removed. `--mf-text-micro` is replaced by `--mf-text-2xs` (same 0.7rem value, new name).

- [ ] **Step 3: Find all current callers of removed/renamed tokens**

Run:
```bash
grep -rnE "var\(--mf-text-(display-sm|micro)\)" static/ 2>/dev/null
```
Expected: zero matches (these tokens are unused per spec inventory). If there ARE matches, treat as a discovery — surface to user before continuing.

- [ ] **Step 4: Verify token block syntactically valid**

Run: `grep -cE "^\s*--mf-text-" static/css/design-tokens.css`
Expected: `11` (eleven new size tokens)

- [ ] **Step 5: Commit**

```bash
git add static/css/design-tokens.css
git commit -m "feat(tokens): redefine text-size grid as 11 plain-rem tokens (Phase 1a)

Drops * var(--mf-text-scale) from token defs to eliminate
double-scaling. Adds --mf-text-2xs/base/md/display-lg.
Renames --mf-text-micro to --mf-text-2xs (same 0.7rem value).
Removes --mf-text-display-sm (unused).
Marks --mf-font-sans deprecated (kept as fallback for safety).

Scaling remains via html { font-size } rule — moved in Task 2."
```

---

## Task 2: Phase 1b — Move html font-size rule to design-themes.css

**Files:**
- Modify: `static/css/design-themes.css` (append at end)
- Modify: `static/markflow.css:11` (delete one line)

- [ ] **Step 1: Append rule to design-themes.css**

Run: `tail -5 static/css/design-themes.css`
Expected:
```
[data-text-scale="small"]  { --mf-text-scale: 0.84; }
[data-text-scale="large"]  { --mf-text-scale: 1.18; }
[data-text-scale="xl"]     { --mf-text-scale: 1.36; }
/* default (1.0) is :root — no override block needed */
```

Edit `static/css/design-themes.css` — append at end of file:
```css

/* ─── Root font-size (drives text-scale) ─────────────────────────────────── */
/* Single source of truth for text-scale propagation. Every page that loads
   this stylesheet (which is all of them, after Phase 0) inherits this rule. */
html { font-size: calc(16px * var(--mf-text-scale, 1)); -webkit-font-smoothing: antialiased; }
```

- [ ] **Step 2: Remove the html rule from markflow.css**

Find on `static/markflow.css:11`:
```css
html { font-size: calc(16px * var(--mf-text-scale, 1)); -webkit-font-smoothing: antialiased; }
```

Delete that line.

- [ ] **Step 3: Verify exactly one html font-size rule remains in the codebase**

Run: `grep -rnE "^\s*html\s*\{[^}]*font-size" static/css/ static/markflow.css`
Expected: one match, in design-themes.css.

- [ ] **Step 4: Browser verification — visual checkpoint**

In browser:
1. Open `http://<VM_IP>:8000/static/index-new.html`
2. Settings → Appearance → switch text scale to xl
3. Reload — page text should grow uniformly. Text rendered via `--mf-text-xs/sm/body` should NO LONGER be jumbo (was double-scaled before). All text scales by ~1.36×.
4. Repeat on `/static/status.html` (legacy page).

If any text element renders disproportionately (much larger or smaller than expected): note it for Task 12 (likely a token caller affected by the scale-removal).

- [ ] **Step 5: Commit**

```bash
git add static/css/design-themes.css static/markflow.css
git commit -m "refactor(themes): move html font-size rule to design-themes.css (Phase 1b)

Single source of truth for text-scale propagation. Was at
markflow.css:11; now lives alongside [data-text-scale] defs.
Both new-UX and legacy pages inherit because both code paths
load design-themes.css after Phase 0."
```

---

## Task 3: Phase 2 — Rebind --mf-font-sans → --mf-font-family in components.css

**Files:**
- Modify: `static/css/components.css` (51 sites)

- [ ] **Step 1: Pre-state count**

Run: `grep -cE "var\(--mf-font-sans\)" static/css/components.css`
Expected: `51`

- [ ] **Step 2: Apply substitution**

```bash
sed -i 's/var(--mf-font-sans)/var(--mf-font-family)/g' static/css/components.css
```

- [ ] **Step 3: Post-state verification**

Run: `grep -cE "var\(--mf-font-sans\)" static/css/components.css`
Expected: `0`

Run: `grep -cE "var\(--mf-font-family\)" static/css/components.css`
Expected: should be the previous count of `--mf-font-family` plus 51. To confirm net gain:
```bash
git diff --stat static/css/components.css
```
Expected: 51 changed lines, +51 −51.

Run: `grep -cE "var\(--mf-font-mono\)" static/css/components.css`
Expected: unchanged from pre-state (mono refs intentionally untouched).

- [ ] **Step 4: Browser verification**

In browser:
1. Open `/static/index-new.html`
2. Settings → Appearance → change font to "JetBrains Mono"
3. Reload — main type should switch to monospace. Code/file-path elements (which use `--mf-font-mono`) should remain monospace as before.
4. Switch font back to "System UI" (default) — verify type returns to system stack.
5. Switch to "Comic Sans MS" — verify type changes everywhere (now that the picker actually binds).

- [ ] **Step 5: Commit**

```bash
git add static/css/components.css
git commit -m "fix(components.css): rebind font picker to --mf-font-family (Phase 2)

51 sites switched from var(--mf-font-sans) (a hardcoded fallback
in design-tokens.css) to var(--mf-font-family) (the picker-bound
token). Resolves the silent no-op of the v0.37.0 font picker
on every component using these classes.

--mf-font-mono untouched (intentionally non-picker for code blocks
and file paths).

Browser-verified: font picker now visibly retunes type on
index-new.html and settings-appearance.html."
```

---

## Task 4: Phase 3a — components.css size literals (lines 1–237: pills, toggles, segmented, cards, status, role, nav, version chip, avatar, layout-icon)

**Files:**
- Modify: `static/css/components.css:1-237`

- [ ] **Step 1: Pre-state count**

Run:
```bash
sed -n '1,237p' static/css/components.css | grep -cE "font-size:\s*[0-9.]+rem"
```
Note the count.

- [ ] **Step 2: Apply the full substitution mapping (range-limited)**

Use `sed` with the address range `1,237`. All 30 mappings from the substitution table apply:
```bash
sed -i '1,237 {
  s/font-size:\s*0\.66rem/font-size: var(--mf-text-2xs)/g
  s/font-size:\s*0\.68rem/font-size: var(--mf-text-2xs)/g
  s/font-size:\s*0\.7rem/font-size: var(--mf-text-2xs)/g
  s/font-size:\s*0\.72rem/font-size: var(--mf-text-2xs)/g
  s/font-size:\s*0\.74rem/font-size: var(--mf-text-2xs)/g
  s/font-size:\s*0\.75rem/font-size: var(--mf-text-2xs)/g
  s/font-size:\s*0\.76rem/font-size: var(--mf-text-2xs)/g
  s/font-size:\s*0\.78rem/font-size: var(--mf-text-xs)/g
  s/font-size:\s*0\.8rem/font-size: var(--mf-text-sm)/g
  s/font-size:\s*0\.82rem/font-size: var(--mf-text-sm)/g
  s/font-size:\s*0\.84rem/font-size: var(--mf-text-sm)/g
  s/font-size:\s*0\.85rem/font-size: var(--mf-text-base)/g
  s/font-size:\s*0\.86rem/font-size: var(--mf-text-base)/g
  s/font-size:\s*0\.875rem/font-size: var(--mf-text-base)/g
  s/font-size:\s*0\.88rem/font-size: var(--mf-text-base)/g
  s/font-size:\s*0\.9rem/font-size: var(--mf-text-body)/g
  s/font-size:\s*0\.92rem/font-size: var(--mf-text-body)/g
  s/font-size:\s*0\.95rem/font-size: var(--mf-text-body)/g
  s/font-size:\s*0\.96rem/font-size: var(--mf-text-body)/g
  s/font-size:\s*1rem\b/font-size: var(--mf-text-md)/g
  s/font-size:\s*1\.0rem/font-size: var(--mf-text-md)/g
  s/font-size:\s*1\.2rem/font-size: var(--mf-text-h3)/g
  s/font-size:\s*1\.35rem/font-size: var(--mf-text-h2)/g
  s/font-size:\s*1\.4rem/font-size: var(--mf-text-h2)/g
  s/font-size:\s*1\.85rem/font-size: var(--mf-text-h1)/g
  s/font-size:\s*2\.3rem/font-size: var(--mf-text-display)/g
  s/font-size:\s*2\.4rem/font-size: var(--mf-text-display)/g
  s/font-size:\s*2\.5rem/font-size: var(--mf-text-display)/g
  s/font-size:\s*3rem\b/font-size: var(--mf-text-display-lg)/g
  s/font-size:\s*3\.0rem/font-size: var(--mf-text-display-lg)/g
}' static/css/components.css
```

- [ ] **Step 3: Post-state verification — only outliers should remain in this range**

Run:
```bash
sed -n '1,237p' static/css/components.css | grep -nE "font-size:\s*[0-9.]+rem"
```

Expected output: only outlier sizes from the spec's outlier list — i.e., values matching `0\.5|0\.55|0\.56|0\.6rem|0\.62|0\.65|1\.05|1\.1rem|1\.15|1\.25|1\.3rem|1\.7rem|1\.75|1\.8rem|3\.4`. Anything else is a sed miss — investigate before proceeding.

Run:
```bash
sed -n '1,237p' static/css/components.css | grep -cE "var\(--mf-text-"
```
Should be a positive number (the substitution count).

- [ ] **Step 4: Visual diff against pre-refactor**

In browser:
1. Open `/static/index-new.html` (homepage of new-UX).
2. Compare to a screenshot taken before this commit (or open a second tab on a backup branch). Look at: nav bar pill buttons, role pill chip, version chip, avatar circle, layout-icon button.
3. Expect only ≤0.6px shifts on individual elements. No layout breakage.

- [ ] **Step 5: Commit**

```bash
git add static/css/components.css
git commit -m "refactor(components.css): tokenize font-sizes lines 1-237 (Phase 3a)

Pills, toggles, segmented controls, status pulse, role pill,
nav bar, version chip, avatar circle, layout-icon button.
Outliers (0.5–0.65 / 1.05–1.3 / 1.7–1.8 / 3.4) deferred to Task 12."
```

---

## Task 5: Phase 3b — components.css size literals (lines 238–684: avatar menu, layout popover, document card, list-row, card grid, list view header, hover preview popover)

**Files:**
- Modify: `static/css/components.css:238-684`

- [ ] **Step 1: Pre-state count**

Run: `sed -n '238,684p' static/css/components.css | grep -cE "font-size:\s*[0-9.]+rem"`
Note the count.

- [ ] **Step 2: Apply substitution mapping (same as Task 4, range 238,684)**

Same `sed -i '238,684 { ... }'` block as Task 4 Step 2 — copy the entire mapping in, change only the address range to `238,684`.

- [ ] **Step 3: Post-state verification**

Run: `sed -n '238,684p' static/css/components.css | grep -nE "font-size:\s*[0-9.]+rem"`
Expected: only outlier sizes remain.

- [ ] **Step 4: Visual diff**

In browser:
1. Open `/static/index-new.html`.
2. Click avatar circle (top-right) — confirm the avatar-menu popover renders identically.
3. Click layout-icon → confirm layout popover renders.
4. Confirm document cards, list rows, and the header bar all look like pre-refactor.

- [ ] **Step 5: Commit**

```bash
git add static/css/components.css
git commit -m "refactor(components.css): tokenize font-sizes lines 238-684 (Phase 3b)

Avatar menu popover, layout popover, document card (all densities),
document list-row, card grid, list view header, hover preview."
```

---

## Task 6: Phase 3c — components.css size literals (lines 685–1040: context menu, multi-select checkbox, bulk action bar, folder browse, hero search, browse row, topic cloud)

**Files:**
- Modify: `static/css/components.css:685-1041`

- [ ] **Step 1: Pre-state count**

Run: `sed -n '685,1040p' static/css/components.css | grep -cE "font-size:\s*[0-9.]+rem"`
Note the count.

- [ ] **Step 2: Apply substitution mapping (range 685,1040)**

Same mapping block as Task 4 Step 2, range `685,1040`.

- [ ] **Step 3: Post-state verification**

Run: `sed -n '685,1040p' static/css/components.css | grep -nE "font-size:\s*[0-9.]+rem"`
Expected: only outliers.

- [ ] **Step 4: Visual diff**

In browser, open `/static/index-new.html`:
1. Right-click a document card → confirm context menu renders.
2. Hover the multi-select checkbox on a doc card.
3. Look at the hero search bar at top.
4. Browse rows and topic cloud (if visible on homepage).

- [ ] **Step 5: Commit**

```bash
git add static/css/components.css
git commit -m "refactor(components.css): tokenize font-sizes lines 685-1040 (Phase 3c)

Right-click context menu, multi-select checkbox, bulk action bar,
folder browse, hero search bar, browse row, topic cloud."
```

---

## Task 7: Phase 3d — components.css size literals (lines 1041–end: search home, activity dashboard, settings overview, storage detail, mf-btn, pipeline settings)

**Files:**
- Modify: `static/css/components.css:1041-end`

- [ ] **Step 1: Pre-state count**

Run: `sed -n '1041,$p' static/css/components.css | grep -cE "font-size:\s*[0-9.]+rem"`
Note the count.

- [ ] **Step 2: Apply substitution mapping (range 1041,$)**

Same mapping block as Task 4 Step 2, range `1041,$`.

- [ ] **Step 3: Post-state verification — file-wide assertion**

Run:
```bash
grep -nE "font-size:\s*[0-9.]+rem" static/css/components.css | grep -vE "0\.5|0\.55|0\.56|0\.6rem|0\.62|0\.65|1\.05|1\.1rem|1\.15|1\.25|1\.3rem|1\.7rem|1\.75|1\.8rem|3\.4"
```
Expected: zero output (all non-outlier raw font-size literals are now tokens).

- [ ] **Step 4: Visual checkpoint — full new-UX sweep**

In browser, screen tour:
1. `/static/index-new.html` — homepage
2. `/static/settings-appearance.html` — settings detail
3. `/static/settings-storage.html`
4. `/static/settings-ai-providers.html`
5. `/static/settings-cost-cap.html`
6. `/static/settings-pipeline.html`

Each page should render with the same visual weight as before. Note any element that appears unusually large or small — log to Task 12 outlier review.

- [ ] **Step 5: Commit**

```bash
git add static/css/components.css
git commit -m "refactor(components.css): tokenize font-sizes lines 1041-end (Phase 3d)

Search home, activity dashboard, settings overview, storage detail,
shared mf-btn, pipeline settings detail. Completes components.css
size tokenization. Outliers (~10 sites) deferred to Task 12."
```

---

## Task 8: Phase 4a — markflow.css size literals (lines 1–310: reset, typography, layout, nav, card, buttons, status & format badges)

**Files:**
- Modify: `static/markflow.css:1-310`

- [ ] **Step 1: Pre-state count**

Run: `sed -n '1,310p' static/markflow.css | grep -cE "font-size:\s*[0-9.]+rem"`
Note the count.

- [ ] **Step 2: Apply substitution mapping (range 1,310)**

Same mapping block as Task 4 Step 2, applied to markflow.css with range `1,310`.

- [ ] **Step 3: Post-state verification**

Run: `sed -n '1,310p' static/markflow.css | grep -nE "font-size:\s*[0-9.]+rem"`
Expected: only outliers (markflow.css contains `1.75rem` for h1 — that's an outlier).

- [ ] **Step 4: Visual diff (legacy page)**

In browser:
1. Open `/static/status.html`.
2. Look at: nav bar, page header (h1), card headers, button rows, status badges, format-coded badges.
3. Compare to pre-refactor — should be visually equivalent.

Note: markflow.css's `h1 { font-size: 1.75rem }` is an outlier — will be addressed in Task 12. Do not preemptively change.

- [ ] **Step 5: Commit**

```bash
git add static/markflow.css
git commit -m "refactor(markflow.css): tokenize font-sizes lines 1-310 (Phase 4a)

Reset, typography, layout, nav bar, card, buttons, status badges,
format badges. Outliers (h1 1.75rem etc.) deferred to Task 12."
```

---

## Task 9: Phase 4b — markflow.css size literals (lines 311–526: progress, ETA, spinner, forms, inline error, toast)

**Files:**
- Modify: `static/markflow.css:311-526`

- [ ] **Step 1: Pre-state count**

Run: `sed -n '311,526p' static/markflow.css | grep -cE "font-size:\s*[0-9.]+rem"`
Note the count.

- [ ] **Step 2: Apply substitution (range 311,526)**

Same mapping, range `311,526`.

- [ ] **Step 3: Post-state verification**

Run: `sed -n '311,526p' static/markflow.css | grep -nE "font-size:\s*[0-9.]+rem"`
Expected: only outliers.

- [ ] **Step 4: Visual diff**

In browser, screen tour: `/static/status.html` (progress bars, spinners), forms on settings pages, toast notifications (trigger one via theme-switch).

- [ ] **Step 5: Commit**

```bash
git add static/markflow.css
git commit -m "refactor(markflow.css): tokenize font-sizes lines 311-526 (Phase 4b)

Progress bar, ETA display, spinner, forms, inline error, toast."
```

---

## Task 10: Phase 4c — markflow.css size literals (lines 525–720: dialog/modal, table, pagination, drop zone, error banner, empty state, filter bar, detail panel, utility)

**Files:**
- Modify: `static/markflow.css:527-722`

- [ ] **Step 1: Pre-state count**

Run: `sed -n '527,722p' static/markflow.css | grep -cE "font-size:\s*[0-9.]+rem"`
Note the count.

- [ ] **Step 2: Apply substitution (range 527,722)**

Same mapping, range `527,722`.

- [ ] **Step 3: Post-state verification**

Run: `sed -n '527,722p' static/markflow.css | grep -nE "font-size:\s*[0-9.]+rem"`
Expected: only outliers.

- [ ] **Step 4: Visual diff**

In browser:
1. `/static/history.html` — table, pagination
2. `/static/index.html` — drop zone
3. `/static/settings.html` — filter bar
4. Trigger a modal (e.g., Discovery dialog from Storage page)

- [ ] **Step 5: Commit**

```bash
git add static/markflow.css
git commit -m "refactor(markflow.css): tokenize font-sizes lines 527-722 (Phase 4c)

Modal/dialog, table, pagination, drop zone, error/empty banners,
filter bar, detail panel, utility classes."
```

---

## Task 11: Phase 4d — markflow.css size literals (lines 720–end: stats row + remaining)

**Files:**
- Modify: `static/markflow.css:720-end`

- [ ] **Step 1: Pre-state count**

Run: `sed -n '720,$p' static/markflow.css | grep -cE "font-size:\s*[0-9.]+rem"`
Note the count.

- [ ] **Step 2: Apply substitution (range 720,$)**

Same mapping, range `720,$`.

- [ ] **Step 3: Post-state verification — file-wide**

Run:
```bash
grep -nE "font-size:\s*[0-9.]+rem" static/markflow.css | grep -vE "0\.5|0\.55|0\.56|0\.6rem|0\.62|0\.65|1\.05|1\.1rem|1\.15|1\.25|1\.3rem|1\.7rem|1\.75|1\.8rem|3\.4"
```
Expected: zero output.

- [ ] **Step 4: Visual checkpoint — full legacy sweep**

In browser, screen tour:
1. `/static/status.html`
2. `/static/history.html`
3. `/static/storage.html`
4. `/static/help.html`
5. `/static/settings.html`
6. `/static/log-viewer.html`
7. `/static/preview.html`

Each page should render with the same visual weight as before. Note any unexpectedly-sized element for Task 12.

- [ ] **Step 5: Commit**

```bash
git add static/markflow.css
git commit -m "refactor(markflow.css): tokenize font-sizes lines 720-end (Phase 4d)

Stats row and remaining edge-case selectors. Completes markflow.css
size tokenization. Outliers (~25 sites) deferred to Task 12."
```

---

## Task 12: Phase 5 — Outlier review and decisions

**Files:**
- Create: `docs/superpowers/specs/2026-05-02-components-css-theme-aware-change-index.md`
- Modify: `static/css/components.css` (per outlier decisions)
- Modify: `static/markflow.css` (per outlier decisions)

This is the only task in the plan that requires per-site judgment. **Implementer effort: Sonnet 4.6 / high.**

- [ ] **Step 1: Inventory all remaining outliers**

Run:
```bash
echo "=== components.css outliers ===" && \
grep -nE "font-size:\s*[0-9.]+rem" static/css/components.css && \
echo "" && \
echo "=== markflow.css outliers ===" && \
grep -nE "font-size:\s*[0-9.]+rem" static/markflow.css
```

Expected: a list of every remaining raw font-size literal, with line numbers.

- [ ] **Step 2: Build the change-index doc skeleton**

Create `docs/superpowers/specs/2026-05-02-components-css-theme-aware-change-index.md` with:
```markdown
# Change Index — components.css Theme-Aware Refactor (v0.38.0)

**Spec:** `2026-05-02-components-css-theme-aware-design.md`
**Plan:** `2026-05-02-components-css-theme-aware.md`
**Branch:** `refactor/components-css-theme-aware`

This is the rollback artifact. Every per-site outlier decision lives here.
Every literal touched in Tasks 4–11 is implicit (mechanical mapping per spec).

---

## Outlier decisions

| File | Line | Selector | Current | Action | New value | Why |
|---|---|---|---|---|---|---|
```

- [ ] **Step 3: For each outlier site, fill in a row**

For each site from Step 1's output:

1. Read the line and the surrounding selector block (use `Read` with offset/limit).
2. Apply this decision tree:
   - **0.5/0.55/0.56rem** (sub-icon labels): default action `keep-raw` with comment `/* exception: sub-icon glyph */`. If the selector clearly serves a sub-icon role (icon labels, micro-badges), keep raw. If it's general text drift, snap to `--mf-text-2xs`.
   - **0.6/0.62/0.65rem**: default `snap` to `--mf-text-2xs` (0.7rem). Note the +0.1rem shift in the row's "Why" column.
   - **1.05rem**: default `snap` to `--mf-text-md` (1.0rem) — small downshift, less than h3.
   - **1.1/1.15rem**: default `snap` to `--mf-text-h3` (1.2rem) — small upshift.
   - **1.25/1.3rem**: default `snap` to `--mf-text-h3` (1.2rem) — small downshift.
   - **1.7/1.75/1.8rem**: default `snap` to `--mf-text-h1` (1.85rem) — these are h1 drift.
   - **3.4rem**: default `snap` to `--mf-text-display-lg` (3.0rem) IF the site is just hero text. If it's a singular hero number (e.g. `.mf-act__queue-stat` or settings-headline), `keep-raw` with comment.

3. Apply the chosen edit to the source file. Document the edit in the change-index row.

4. Format each row:
```markdown
| `static/css/components.css` | 122 | `.mf-pill__count` | `0.6rem` | snap | `var(--mf-text-2xs)` | Drift from 0.7rem; pill counts are uniform |
| `static/css/components.css` | 279 | `.mf-av-menu__avatar-glyph` | `0.5rem` | keep-raw | `0.5rem` /* exception: sub-icon */ | Sub-icon glyph; visual at 0.7rem would dominate |
```

- [ ] **Step 4: Final file-wide verification**

Run:
```bash
echo "=== components.css remaining font-size literals ===" && \
grep -nE "font-size:\s*[0-9.]+rem" static/css/components.css && \
echo "" && \
echo "=== markflow.css remaining font-size literals ===" && \
grep -nE "font-size:\s*[0-9.]+rem" static/markflow.css
```

Each remaining literal MUST have a `/* exception: ... */` comment on the same line, and a `keep-raw` row in the change-index.

- [ ] **Step 5: Visual checkpoint on outlier sites**

In browser, visit each page that contains an outlier site (per change-index row). Verify the rendering is acceptable.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-02-components-css-theme-aware-change-index.md \
       static/css/components.css static/markflow.css
git commit -m "refactor(outliers): per-site decisions for ~33 outlier font-sizes (Phase 5)

Snaps: drift sites pulled to nearest grid token.
Keep-raw: intentional sub-icon labels and singular hero numbers
preserved with /* exception: ... */ comments.

Every decision recorded in
docs/superpowers/specs/2026-05-02-components-css-theme-aware-change-index.md
as the rollback artifact."
```

---

## Task 13: Phase 6 — Final visual checkpoint + release docs

**Files:**
- Modify: `docs/version-history.md`
- Modify: `docs/whats-new.md`
- Modify: `static/help/whats-new.html` (if pattern matches v0.37.1)
- Modify: `CLAUDE.md` (Current Version section)
- Modify: `docs/gotchas.md` (if any new gotchas surfaced)
- Modify: `docs/bug-log.md` (if BUG-* IDs apply for v0.37.1 regression closure)

- [ ] **Step 1: Full screen tour**

In browser, walk through every page below. For each, cycle through 3 themes (Classic Light, Classic Dark, Cobalt), 3 fonts (System UI, Source Sans 3, JetBrains Mono), and 3 text scales (small, default, xl) — sample 9 combinations total.

Pages:
1. `/static/index-new.html`
2. `/static/index.html`
3. `/static/status.html`
4. `/static/history.html`
5. `/static/search.html`
6. `/static/storage.html`
7. `/static/settings-appearance.html`
8. `/static/settings-storage.html`
9. `/static/help.html`
10. `/static/log-viewer.html`

For each combination, verify: theme renders correctly (colors), font picker takes effect (type face), text scale applies uniformly (no jumbo or shrunken text on any element).

- [ ] **Step 2: Update CLAUDE.md "Current Version" section**

Open `CLAUDE.md`, find the `## Current Version — v0.37.1` block, replace its content with a v0.38.0 block following the same structure (one-line summary, multi-paragraph rationale, list of major changes, list of loose ends).

Use this template:
```markdown
## Current Version — v0.38.0

**components.css theme-aware refactor — completes the v0.37.x type system.** Closes three gaps left by v0.37.1: the font picker bypass on new-UX (51 components.css sites used `var(--mf-font-sans)` instead of the picker-bound `var(--mf-font-family)`), the latent v0.37.1 import regression on legacy pages (markflow.css referenced 364 `var(--mf-*)` tokens but never imported `design-tokens.css` or `design-themes.css`, and the 27 legacy HTML pages didn't link them either — so v0.37.1's color refactor was silently a no-op on every legacy page), and font-size drift across both files (311 raw `font-size: Xrem` literals across 39 distinct values, with token-using sites double-scaling because both their definitions and the `html { font-size }` rule applied `* var(--mf-text-scale)`).

The fix lands as a single PR on `refactor/components-css-theme-aware` (12 phase commits squashed). Phase 0 prepends two `@import` lines to markflow.css. Phase 1 redefines the text-size grid as 11 plain-rem tokens (drops `* scale` from defs; html font-size rule moved to design-themes.css for single-source scaling). Phase 2 rebinds the 51 font-sans sites in components.css. Phases 3–4 substitute 269 raw `font-size: Xrem` literals to grid tokens across both files, by selector group. Phase 5 captures ~33 outlier per-site decisions (snap or keep-raw with comment) in a change-index sidecar doc. Phase 6 verifies the whole system across 9 sample combinations of theme × font × scale, on 10 representative pages.

After v0.38.0:
- `/api/version` reports `0.38.0`.
- Theme/font/scale switching works uniformly across all 39 user-facing pages (legacy + new-UX).
- Token-using sites no longer double-scale; xl text scale renders ~7px smaller on those sites than pre-refactor (correcting a v0.37.0 bug, called out below).
- The text-size grid is 11 tokens: 2xs, xs, sm, base, body, md, h3, h2, h1, display, display-lg.

**Loose ends tracked forward:**
1. Tight grid follow-up audit. With everything tokenized, run a "consolidate" pass — does `--mf-text-base` still need to exist as distinct from `--mf-text-sm`?
2. Inline `<style>` block cleanup. ~30 legacy HTML pages have inline styles using pre-v0.37.0 token names (`var(--text)`, `var(--surface)`); separate cleanup pass.

**Heads-up for users on xl text scale:** elements whose CSS used `--mf-text-xs/sm/body/micro` were silently double-scaling pre-v0.38.0. After this fix they shrink by ~30% on xl. Set text-scale to "large" or default if pre-fix size is preferred.
```

- [ ] **Step 3: Append to version-history.md**

Open `docs/version-history.md`. Find the most recent version entry (v0.37.1). Above it, prepend a v0.38.0 entry following the same format. Use the CLAUDE.md content as the basis but adapt to version-history.md's house style (typically more terse).

- [ ] **Step 4: Append to whats-new.md and (if exists) static/help/whats-new.html**

Add a v0.38.0 user-facing entry. Tone: emphasize what's fixed for the user (theme/font picker now works app-wide, text scale is consistent), not implementation details.

- [ ] **Step 5: Bump version**

Find the version string definition. Run:
```bash
grep -rnE "version\s*=\s*[\"']0\.37\.1[\"']" --include="*.py" --include="*.toml" --include="*.json" .
```
Update each match to `0.38.0`.

Verify: `curl -s http://localhost:8000/api/version` after restart should report 0.38.0 (post-restart).

- [ ] **Step 6: Optional — bug-log entries**

If the v0.37.1 import regression warrants a bug ID (it did silently ship), add an entry to `docs/bug-log.md` with the BUG ID style used in v0.37.1 (BUG-029 if continuing the sequence). Then reference the resolution in the v0.38.0 commit.

- [ ] **Step 7: Verify all release-discipline files were updated**

Run the pre-release-checklist skill (if available) or manually check:
- [ ] `CLAUDE.md` Current Version section
- [ ] `docs/version-history.md`
- [ ] `docs/whats-new.md`
- [ ] `static/help/whats-new.html` (if present and was updated for v0.37.1)
- [ ] Version string in code reports 0.38.0
- [ ] `docs/bug-log.md` (if applicable)

- [ ] **Step 8: Final commit**

```bash
git add CLAUDE.md docs/version-history.md docs/whats-new.md \
       static/help/whats-new.html docs/bug-log.md \
       <any-version-string-files>
git commit -m "docs(release): v0.38.0 — components.css theme-aware refactor

Per-release-discipline updates: Current Version block, version-history,
whats-new (both Markdown and HTML if applicable), bug-log entry for
the v0.37.1 latent import regression closure, and version-string bump.

See spec: docs/superpowers/specs/2026-05-02-components-css-theme-aware-design.md
See plan: docs/superpowers/plans/2026-05-02-components-css-theme-aware.md
See change-index: docs/superpowers/specs/2026-05-02-components-css-theme-aware-change-index.md"
```

- [ ] **Step 9: Squash into rollup commit**

User-driven choice — the implementation history can stay (granular bisect) or get squashed into a single v0.38.0 commit (mirrors v0.37.1's ship style). Default: squash.

```bash
# Find the commit immediately before Task 0:
LAST_BASE=$(git rev-parse refactor/markflow-css-theme-aware)
git reset --soft $LAST_BASE
git commit -m "v0.38.0: components.css theme-aware refactor"
```

(Do not run this until the user explicitly approves squashing — `git reset --soft` is destructive of commit history.)

---

## Plan self-review

**Spec coverage check:**

| Spec section | Tasks | Status |
|---|---|---|
| Goal: font picker fix | Task 3 | ✓ |
| Goal: import regression fix | Task 0 | ✓ |
| Goal: size token grid | Tasks 1, 4–11 | ✓ |
| Goal: scale double-app fix | Tasks 1, 2 | ✓ |
| Token grid (11 tokens) | Task 1 | ✓ |
| Outlier handling | Task 12 | ✓ |
| Phase 0–6 plan | Tasks 0–13 | ✓ |
| Verification strategy | Tasks 0, 2, 3, 7, 11, 13 | ✓ |
| Risk: scale-shrink at xl | Task 13 (CLAUDE.md heads-up) | ✓ |
| Risk: 3.4rem outlier shift | Task 12 decision tree | ✓ |
| Risk: html inline styles out-of-scope | Spec only; no task | ✓ |
| Branch + version | Task 13 | ✓ |
| Change-index doc | Task 12 | ✓ |
| Release docs | Task 13 | ✓ |

**Placeholder scan:** No "TBD"/"TODO" left. Every step has explicit code/commands. Decision tree in Task 12 covers every outlier cluster with a default action.

**Type/token consistency check:** Every token name appears identically across Tasks 1, 4–11, and 12 (`--mf-text-2xs`, not `--mf-text-2xs-`; `--mf-text-display-lg`, not `--mf-text-display-large`). Substitution table values match grid table values.

**Sequencing dependencies:**
- Task 0 → Task 1 (need imports before testing token defs visually)
- Task 1 → Task 2 (need new grid before moving the scale rule)
- Task 2 → Tasks 3–11 (need single-scale system before substituting sites)
- Tasks 3 (font) and 4–11 (sizes) can technically run in parallel after Task 2, but plan assumes sequential for review simplicity
- Tasks 4–11 → Task 12 (need all non-outlier sites tokenized before outlier review)
- Tasks 0–12 → Task 13 (release docs reflect the cumulative work)

---

## Execution mode handoff

**Plan complete. Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh Sonnet 4.6 subagent per task with the per-task model/effort routing above. I review between tasks; user reviews at visual checkpoints (Tasks 0, 2, 3, 7, 11, 13).
2. **Inline Execution** — Execute tasks in this session via `superpowers:executing-plans`. Batch with checkpoints for review.

Subagent-Driven is the recommended mode for this plan — most tasks are mechanical sed runs, fresh subagents keep context cleaner, and the visual-checkpoint cadence maps naturally to user-review gates.
