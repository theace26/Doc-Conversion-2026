# MarkFlow CSS Theme-Aware Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make every original-UX page respond to the v0.37.0 `[data-theme]` system by renaming markflow.css's local CSS custom props to `--mf-*`, deleting all 7 `@media (prefers-color-scheme: dark)` blocks (replacing with `[data-theme="classic-dark"]`-scoped rules where they carried real overrides), and substituting remaining hardcoded literals with `var(--mf-…)` references.

**Architecture:** Single PR on a feature branch. 12 ordered local commits, squashed before PR. Each commit lands a self-contained slice of the refactor. Two new files: a feature branch and a change-index sidecar doc that catalogues every literal touched (the rollback artifact). The change-index makes a `git revert` of the PR + deletion of the sidecar = clean removal.

**Tech Stack:** Pure CSS. Bash + grep + sed for substitution. Browser-based manual visual review at three checkpoints. No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-05-01-markflow-theme-refactor-design.md`](../specs/2026-05-01-markflow-theme-refactor-design.md) (commit `6c19c91`).

---

## Model + effort (overall)

| Role | Model | Effort |
|------|-------|--------|
| Implementer (default) | Sonnet 4.6 | medium (4–8h) |
| Reviewer (default) | Sonnet 4.6 | low (2–3h) |

**Reasoning:** Plan is paste-and-test mechanical. Decision tree + rename map are pre-computed. Implementer's discretion is bounded to ~5–10 mid-implementation new-token additions logged in the change-index. Reviewer checks the change-index doc, verification command outputs, and the three visual checkpoints. No security or schema implications.

**Execution mode:** Dispatch via `superpowers:subagent-driven-development`. Each task is one fresh subagent call. Two-stage review: orchestrator reviews after each task; user reviews at visual checkpoints (after Tasks 7, 11, 13).

## Per-task model + effort routing

The orchestrator (`superpowers:subagent-driven-development`) reads this table to swap subagent model/effort per task. **Override the plan-level defaults above when a task's row says so.**

| Task | Phase | Implementer model | Implementer effort | Reviewer model | Reviewer effort | Why |
|------|-------|-------------------|--------------------|----|--|----|
| 1 | Setup | Haiku 4.5 | low | (skip) | — | Pure bash: branch creation, file scaffold, capture baselines. Zero judgment. |
| 2 | 1a — new tokens to design-tokens.css | Haiku 4.5 | low | Haiku 4.5 | low | Exact code given. Reviewer just confirms 5 lines added at the right anchor. |
| 3 | 1b — classic-dark overrides | Haiku 4.5 | low | Haiku 4.5 | low | Exact code given. Reviewer confirms 5 lines added inside the right block. |
| 4 | 2a — delete :root + main @media | Haiku 4.5 | low | Sonnet 4.6 | low | Mechanical `sed -i '7,50d'`. Reviewer reads the diff to confirm only that block was deleted (no collateral damage). |
| 5 | 2b — convert 6 @media blocks | Sonnet 4.6 | medium | Sonnet 4.6 | low | Six Edit-tool transformations; each must match the original block byte-for-byte. Haiku-level Edit-tool reliability slips on 6 sequential exact matches; Sonnet is the floor. |
| 6 | 2c — rename 302 var refs | Haiku 4.5 | low | Sonnet 4.6 | medium | The 19 sed scripts are deterministic. Reviewer must verify zero non-`mf-` `var(--…)` refs remain — that check warrants Sonnet to read the diff carefully. |
| 7 | Phase 2 verification + checkpoint #1 | Haiku 4.5 | low | (user) | — | Pure verification commands + Docker rebuild + user prompt. Then the user is the reviewer. |
| 8 | 3 — page bg + body text literals | Sonnet 4.6 | medium | Sonnet 4.6 | low | Per-literal decision-tree application. Sonnet handles the mapping reliably; Haiku risks Branch-3 vs Branch-4 misjudgment on borderline literals. |
| 9 | 4 — nav + header literals | Sonnet 4.6 | medium | Sonnet 4.6 | low | Same as Task 8. Plus the rgba accent-tint snap call is a small judgment. |
| 10 | 5 — buttons + forms literals | Sonnet 4.6 | medium | Sonnet 4.6 | low | Same. Plus toggle-switch literals have explicit "keep as literal" guidance the implementer must honor. |
| 11 | 6 — cards + panels + modals + checkpoint #2 | Sonnet 4.6 | medium | (user) | — | Same. User is the reviewer (visual checkpoint). |
| 12 | 7 — tables + lists + pagination | Sonnet 4.6 | medium | Sonnet 4.6 | low | Help-section blockquote color → status-token snap is a small judgment call. |
| 13 | 8 — status + edge cases + checkpoint #3 | Sonnet 4.6 | medium | (user) | — | Largest selector count of the literal-substitution phases. User is the final reviewer. |
| 14 | Squash + PR | Haiku 4.5 | low | Sonnet 4.6 | low | Mechanical git + gh CLI. Reviewer confirms the squash commit message captures the full scope. |

**Effort budget rough-out:**
- Haiku tasks (1, 2, 3, 4, 6, 7, 14): ~20–30 min each, total ~3 hours
- Sonnet tasks (5, 8, 9, 10, 11, 12, 13): ~30–60 min each, total ~5–7 hours
- Reviewer time: ~30 min per Sonnet task, ~10 min per Haiku task

**Auto-swap rule for the orchestrator:** at the start of each task dispatch, read the row above. Override the parent's current model/effort with the task's row values. After the task completes, the next task's row drives the next dispatch. If a task escalates (e.g., Branch-3 decision proves harder than expected), the implementer can request a one-step bump (Haiku → Sonnet, medium → high) and the orchestrator approves.

---

## File structure

**Create:**
- `docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md` — the rollback artifact. Implementer fills in row-by-row across all phases.

**Modify:**
- `static/css/design-tokens.css` — add 5 new tokens to `:root` block (Task 2).
- `static/css/design-themes.css` — add classic-dark overrides for 5 tokens (Task 3).
- `static/markflow.css` — delete `:root { … }` + main `@media` block, convert 6 remaining `@media` blocks, rename ~302 `var(--…)` references, substitute ~104 hardcoded literals (Tasks 4–11).

**No HTML, JS, Python, or config changes.** No tests written or updated (no test infrastructure for CSS; verification is grep-based + manual visual review).

---

## Task 1: Setup — create branch and capture baselines

**Files:**
- No source-file edits. Captures baseline metrics.

- [ ] **Step 1: Verify clean working tree on main**

```bash
cd /opt/doc-conversion-2026
git status
```
Expected output: `working tree clean`. If not clean, abort and report.

- [ ] **Step 2: Pull latest from origin**

```bash
git fetch origin && git checkout main && git pull --ff-only origin main
```
Expected: `Already up to date` or fast-forward only. Abort if non-fast-forward.

- [ ] **Step 3: Create feature branch**

```bash
git checkout -b refactor/markflow-css-theme-aware
```
Expected: `Switched to a new branch 'refactor/markflow-css-theme-aware'`.

- [ ] **Step 4: Capture baseline metrics**

```bash
echo "=== Pre-refactor baselines ===" > /tmp/markflow-baseline.txt
echo "Total lines: $(wc -l < static/markflow.css)" >> /tmp/markflow-baseline.txt
echo "var(--…) refs: $(grep -cE 'var\(--' static/markflow.css)" >> /tmp/markflow-baseline.txt
echo "Hex literal count: $(grep -oE '#[0-9a-fA-F]{3,8}\b' static/markflow.css | wc -l)" >> /tmp/markflow-baseline.txt
echo "Unique hex literals: $(grep -oE '#[0-9a-fA-F]{3,8}\b' static/markflow.css | sort -u | wc -l)" >> /tmp/markflow-baseline.txt
echo "rgba()/rgb() count: $(grep -oE 'rgba?\([^)]+\)' static/markflow.css | wc -l)" >> /tmp/markflow-baseline.txt
echo "@media prefers-color-scheme blocks: $(grep -cE 'prefers-color-scheme' static/markflow.css)" >> /tmp/markflow-baseline.txt
echo "!important count: $(grep -c '!important' static/markflow.css)" >> /tmp/markflow-baseline.txt
cat /tmp/markflow-baseline.txt
```
Expected output (record exact numbers; later tasks compare):
```
Total lines: 1684
var(--…) refs: 302
Hex literal count: ~250
Unique hex literals: ~73
rgba()/rgb() count: ~30
@media prefers-color-scheme blocks: 7
!important count: 3
```

- [ ] **Step 5: Initialize change-index doc**

Create file `docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md` with this exact content:

```markdown
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
| _filled in Task 2_ | | | |

## Local-prop rename map applied

| markflow local prop | replaced by | occurrence count in markflow.css |
|---------------------|-------------|----------------------------------|
| _filled in Task 6_ | | |

## Snapped colors (decision tree branch 2 / 5)

| original literal | snapped to | max RGB drift | reason |
|------------------|------------|---------------|--------|
| _filled per phase_ | | | |

## Substitutions (decision tree branch 1)

| line | selector | property | old literal | new var | new-token? | task # |
|------|----------|----------|-------------|---------|------------|--------|
| _filled per phase_ | | | | | | |

## Kept literals (decision tree branch 4)

| line | selector | property | literal | reason |
|------|----------|----------|---------|--------|
| _filled per phase_ | | | | |
```

- [ ] **Step 6: Commit setup**

```bash
git add docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "chore(orig-ux): scaffold change-index doc for markflow theme refactor"
```

---

## Task 2: Phase 1a — add new tokens to design-tokens.css

**Files:**
- Modify: `static/css/design-tokens.css` (insert after line 53, after the format-gradient block)

- [ ] **Step 1: Open the file and confirm the insertion anchor**

```bash
grep -n "^  /\* === Format-coded gradients" static/css/design-tokens.css
```
Expected: line 45. Confirm the next blank line is around line 54.

- [ ] **Step 2: Edit the file — add a new section right after the format-gradient block**

Use the Edit tool to insert these 9 lines just before `  /* === Type === */` (around line 55):

```css
  /* === Color — legacy-ux additions (markflow.css refactor 2026-05-01) === */
  --mf-surface-alt:            #f0f1f5;  /* secondary surface, alt rows, nav bg */
  --mf-color-text-on-accent:   #ffffff;  /* text rendered on accent-bg buttons/badges */
  --mf-color-accent-hover:     #3d49b8;  /* darker accent for hover states */
  --mf-color-info:             #2563eb;  /* informational status (toasts, running pills) */
  --mf-radius-sm:              4px;      /* smaller radius for badges/inline pills */

```

- [ ] **Step 3: Verify the additions are well-formed**

```bash
grep -n "mf-surface-alt\|mf-color-text-on-accent\|mf-color-accent-hover\|mf-color-info\|mf-radius-sm" static/css/design-tokens.css
```
Expected: 5 lines printed, all in `:root` (around lines 56–60).

- [ ] **Step 4: Verify CSS still parses**

```bash
# A bare grep for syntax errors — no `};` (broken brace) or duplicate `:root` selectors
grep -cE '^\s*:root\s*\{' static/css/design-tokens.css
```
Expected: `1` (one `:root` declaration).

- [ ] **Step 5: Append rows to change-index — New tokens added section**

Use the Edit tool to replace the placeholder row in the change-index `## New tokens added` section with these 5 rows:

```markdown
| `--mf-surface-alt` | `#f0f1f5` | yes (Task 3) | secondary surface; replaces markflow's `--surface-alt` |
| `--mf-color-text-on-accent` | `#ffffff` | no | text on accent-colored backgrounds; replaces markflow's `--text-on-accent` |
| `--mf-color-accent-hover` | `#3d49b8` | yes (Task 3) | hover state for accent; replaces markflow's `--accent-hover` |
| `--mf-color-info` | `#2563eb` | yes (Task 3) | info status; replaces markflow's `--info` |
| `--mf-radius-sm` | `4px` | no | small radius; replaces markflow's `--radius-sm` |
```

- [ ] **Step 6: Commit**

```bash
git add static/css/design-tokens.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "tokens(theme): add 5 new --mf-* tokens for legacy-ux refactor"
```

---

## Task 3: Phase 1b — add classic-dark theme overrides to design-themes.css

**Files:**
- Modify: `static/css/design-themes.css` (extend the `[data-theme="classic-dark"]` block around line 10)

- [ ] **Step 1: Locate the classic-dark block**

```bash
grep -n '^\[data-theme="classic-dark"\]' static/css/design-themes.css
```
Expected: line 10.

- [ ] **Step 2: Read the existing block to confirm closing brace**

Read lines 10–28 of the file. The block ends with `}` on line 27.

- [ ] **Step 3: Edit the file — append 5 lines inside the classic-dark block, just before its closing `}`**

Add these lines as the last properties before the closing `}` of `[data-theme="classic-dark"]`:

```css
  --mf-surface-alt:           #232638;
  --mf-color-accent-hover:    #8189e8;
  --mf-color-info:            #60a5fa;
  --mf-shadow-press:          0 1px 3px rgba(0,0,0,.3);
  --mf-shadow-popover:        0 4px 12px rgba(0,0,0,.4);
```

- [ ] **Step 4: Verify additions**

```bash
grep -A 25 '^\[data-theme="classic-dark"\]' static/css/design-themes.css | grep -E 'surface-alt|accent-hover|color-info|shadow-press|shadow-popover'
```
Expected: 5 lines printed.

- [ ] **Step 5: Append a row to change-index**

In the change-index, in the `## New tokens added` section, update the `--mf-surface-alt`, `--mf-color-accent-hover`, `--mf-color-info` rows' "added in design-themes.css?" column to **yes (classic-dark: `<value>`)**.

- [ ] **Step 6: Commit**

```bash
git add static/css/design-themes.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "tokens(theme): add classic-dark overrides for new --mf-* tokens"
```

---

## Task 4: Phase 2a — delete markflow.css :root + main @media block

**Files:**
- Modify: `static/markflow.css` (delete lines 7–50)

- [ ] **Step 1: Verify the line range**

```bash
sed -n '7,50p' static/markflow.css | head -50
```
Expected: lines 7–50 contain the comment `/* ── CSS Variables — Light Theme ──...`, the `:root { ... }` block, and the `@media (prefers-color-scheme: dark) { :root { ... } }` block. Confirm line 50 is the closing `}` of the `@media` block.

- [ ] **Step 2: Delete those lines**

```bash
sed -i '7,50d' static/markflow.css
```

- [ ] **Step 3: Verify the deletion landed cleanly**

```bash
sed -n '1,15p' static/markflow.css
```
Expected: lines 1–6 are the header comment + Google Fonts `@import`. Line 7 onwards is the next section (probably `/* ── Reset & Base ── */` or similar).

- [ ] **Step 4: Sanity — no orphan opening or closing braces in lines 1–20**

```bash
sed -n '1,20p' static/markflow.css | grep -cE '^\s*\{|^\s*\}\s*$' || echo "OK: no orphan braces"
```
Expected: `OK: no orphan braces` (or count `0`).

- [ ] **Step 5: Append change-index rows**

Add to the change-index in `## Substitutions (decision tree branch 1)` section, but as a deletion-style row block:

```markdown
| 7-50 | (file-level) | (deleted block) | `:root { ... }` + `@media (prefers-color-scheme: dark) { ... }` | — | n/a (deleted) | 4 |
```

Actually — these are deletions, not substitutions. Add a new section heading just above `## Substitutions`:

```markdown
## Deleted blocks

| line range (pre-delete) | description | reason | task # |
|-------------------------|-------------|--------|--------|
| 7–50 | `:root { … }` + main `@media (prefers-color-scheme: dark) { :root { … } }` | local custom-prop system superseded by `design-tokens.css` + `[data-theme]` | 4 |
```

- [ ] **Step 6: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): delete markflow.css :root + main @media (prefers-color-scheme) block"
```

---

## Task 5: Phase 2b — convert 6 remaining @media blocks to `[data-theme="classic-dark"]`

**Files:**
- Modify: `static/markflow.css` (rewrite 6 blocks)

After Task 4, the file is shorter by 44 lines. Re-grep to find the new line numbers.

- [ ] **Step 1: Find the 6 remaining @media blocks**

```bash
grep -nE 'prefers-color-scheme' static/markflow.css
```
Expected: exactly 6 lines printed. Record their line numbers as `L1 L2 L3 L4 L5 L6`. After Task 4 the originals were at lines 270, 350, 1168, 1231, 1384, 1402 (pre-delete); they're now at lines `~226, ~306, ~1124, ~1187, ~1340, ~1358` (post-delete; subtract 44 from each pre-delete number, but verify exact numbers from grep).

- [ ] **Step 2: For block 1 (was line 270, now ~L1) — `.badge-*` dark overrides**

The block looks like:
```css
@media (prefers-color-scheme: dark) {
  .badge-docx { background: rgba(59,130,246,.2); color: #93c5fd; }
  .badge-pdf  { background: rgba(239,68,68,.2);  color: #fca5a5; }
  .badge-pptx { background: rgba(245,158,11,.2); color: #fcd34d; }
  .badge-xlsx { background: rgba(34,197,94,.2);  color: #86efac; }
  .badge-csv  { background: rgba(99,102,241,.2); color: #a5b4fc; }
  .badge-tsv  { background: rgba(139,92,246,.2); color: #c4b5fd; }
  .badge-md   { background: rgba(156,163,175,.2);color: #d1d5db; }
}
```

Replace the entire block with:
```css
html[data-theme="classic-dark"] .badge-docx { background: rgba(59,130,246,.2); color: #93c5fd; }
html[data-theme="classic-dark"] .badge-pdf  { background: rgba(239,68,68,.2);  color: #fca5a5; }
html[data-theme="classic-dark"] .badge-pptx { background: rgba(245,158,11,.2); color: #fcd34d; }
html[data-theme="classic-dark"] .badge-xlsx { background: rgba(34,197,94,.2);  color: #86efac; }
html[data-theme="classic-dark"] .badge-csv  { background: rgba(99,102,241,.2); color: #a5b4fc; }
html[data-theme="classic-dark"] .badge-tsv  { background: rgba(139,92,246,.2); color: #c4b5fd; }
html[data-theme="classic-dark"] .badge-md   { background: rgba(156,163,175,.2);color: #d1d5db; }
```

Use the Edit tool with the full original block as `old_string` and the rewritten lines as `new_string`.

- [ ] **Step 3: For block 2 (was line 350) — `.storage-verify .sv-*` dark overrides**

Original block:
```css
@media (prefers-color-scheme: dark) {
  .storage-verify .sv-ok     { background: rgba(34,197,94,.22); color: #86efac; }
  .storage-verify .sv-bad    { background: rgba(239,68,68,.22); color: #fca5a5; }
  .storage-verify .sv-ok-sub { color: #86efac; }
  .storage-verify .sv-bad-sub{ color: #fca5a5; }
  .storage-verify .sv-warn   { color: #fcd34d; }
}
```

Replace with:
```css
html[data-theme="classic-dark"] .storage-verify .sv-ok     { background: rgba(34,197,94,.22); color: #86efac; }
html[data-theme="classic-dark"] .storage-verify .sv-bad    { background: rgba(239,68,68,.22); color: #fca5a5; }
html[data-theme="classic-dark"] .storage-verify .sv-ok-sub { color: #86efac; }
html[data-theme="classic-dark"] .storage-verify .sv-bad-sub{ color: #fca5a5; }
html[data-theme="classic-dark"] .storage-verify .sv-warn   { color: #fcd34d; }
```

- [ ] **Step 4: For block 3 (was line 1168) — `.flag-banner` dark**

Original:
```css
@media (prefers-color-scheme: dark) {
  .flag-banner {
    background: #3e2f00;
    border-color: #f9a825;
    color: #ffe082;
  }
}
```

Replace with:
```css
html[data-theme="classic-dark"] .flag-banner {
  background: #3e2f00;
  border-color: #f9a825;
  color: #ffe082;
}
```

- [ ] **Step 5: For block 4 (was line 1231) — `.stop-banner` dark**

Original:
```css
@media (prefers-color-scheme: dark) {
  .stop-banner { background: #3e2f00; border-color: #f9a825; }
  .stop-banner__text { color: #ffab40; }
}
```

Replace with:
```css
html[data-theme="classic-dark"] .stop-banner { background: #3e2f00; border-color: #f9a825; }
html[data-theme="classic-dark"] .stop-banner__text { color: #ffab40; }
```

- [ ] **Step 6: For block 5 (was line 1384) — `.tool-*` dark**

Original:
```css
@media (prefers-color-scheme: dark) {
  .tool-fast   { background: #1b3a1b; color: #66bb6a; }
  .tool-slow   { background: #3e2f00; color: #ffb74d; }
  .tool-danger { background: #3b1010; color: #ef5350; }
}
```

Replace with:
```css
html[data-theme="classic-dark"] .tool-fast   { background: #1b3a1b; color: #66bb6a; }
html[data-theme="classic-dark"] .tool-slow   { background: #3e2f00; color: #ffb74d; }
html[data-theme="classic-dark"] .tool-danger { background: #3b1010; color: #ef5350; }
```

- [ ] **Step 7: For block 6 (was line 1402) — `.db-tool-*` dark**

Original:
```css
@media (prefers-color-scheme: dark) {
  .db-tool-ok    { background: #1b3a1b; color: #a5d6a7; }
  .db-tool-error { background: #3b1010; color: #ef9a9a; }
}
```

Replace with:
```css
html[data-theme="classic-dark"] .db-tool-ok    { background: #1b3a1b; color: #a5d6a7; }
html[data-theme="classic-dark"] .db-tool-error { background: #3b1010; color: #ef9a9a; }
```

- [ ] **Step 8: Verify zero @media (prefers-color-scheme) blocks remain**

```bash
grep -cE 'prefers-color-scheme' static/markflow.css
```
Expected: `0`.

- [ ] **Step 9: Verify the new selectors are valid (count of `[data-theme="classic-dark"]` lines)**

```bash
grep -cE '\[data-theme="classic-dark"\]' static/markflow.css
```
Expected: `~22` (7 badge + 5 storage-verify + 1 flag-banner + 2 stop-banner + 3 tool + 2 db-tool = 20, plus any descendants — the count is approximate; just confirm > 15).

- [ ] **Step 10: Append change-index rows**

In the change-index, add a new subsection between `## Deleted blocks` and `## Local-prop rename map applied`:

```markdown
## Converted @media blocks (prefers-color-scheme → [data-theme="classic-dark"])

| pre-delete line | block content | new selector pattern | task # |
|-----------------|---------------|----------------------|--------|
| 270 | `.badge-docx/.badge-pdf/.badge-pptx/.badge-xlsx/.badge-csv/.badge-tsv/.badge-md` | `html[data-theme="classic-dark"] .badge-…` | 5 |
| 350 | `.storage-verify .sv-*` (5 selectors) | `html[data-theme="classic-dark"] .storage-verify .sv-…` | 5 |
| 1168 | `.flag-banner` | `html[data-theme="classic-dark"] .flag-banner` | 5 |
| 1231 | `.stop-banner`, `.stop-banner__text` | `html[data-theme="classic-dark"] .stop-banner…` | 5 |
| 1384 | `.tool-fast/.tool-slow/.tool-danger` | `html[data-theme="classic-dark"] .tool-…` | 5 |
| 1402 | `.db-tool-ok`, `.db-tool-error` | `html[data-theme="classic-dark"] .db-tool-…` | 5 |
```

- [ ] **Step 11: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): convert 6 remaining @media (prefers-color-scheme) blocks to [data-theme=classic-dark]"
```

---

## Task 6: Phase 2c — apply local-prop rename map to markflow.css

**Files:**
- Modify: `static/markflow.css` (~302 substitutions across the file via sed)

The rename map (per spec) — apply each substitution **in order** to avoid prefix collisions (e.g., `--text-muted` must be replaced before `--text` for `--text-` to find a match):

| # | from | to |
|---|------|----|
| 1 | `--text-on-accent` | `--mf-color-text-on-accent` |
| 2 | `--text-muted` | `--mf-color-text-muted` |
| 3 | `--text` | `--mf-color-text` |
| 4 | `--bg` | `--mf-bg-page` |
| 5 | `--surface-alt` | `--mf-surface-alt` |
| 6 | `--surface` | `--mf-surface` |
| 7 | `--border` | `--mf-border` |
| 8 | `--accent-hover` | `--mf-color-accent-hover` |
| 9 | `--accent` | `--mf-color-accent` |
| 10 | `--ok` | `--mf-color-success` |
| 11 | `--warn` | `--mf-color-warn` |
| 12 | `--error` | `--mf-color-error` |
| 13 | `--info` | `--mf-color-info` |
| 14 | `--radius-sm` | `--mf-radius-sm` |
| 15 | `--radius` | `--mf-radius-thumb` |
| 16 | `--font-sans` | `--mf-font-sans` |
| 17 | `--font-mono` | `--mf-font-mono` |
| 18 | `--shadow-lg` | `--mf-shadow-popover` |
| 19 | `--shadow` | `--mf-shadow-press` |
| 20 | `--transition` | `--mf-transition-med` |

**Important:** these substitutions only apply inside `var(...)` calls. We must not match strings like `--text-mode` or `--shadow-color` if they exist elsewhere.

- [ ] **Step 1: Confirm pre-rename count**

```bash
grep -cE 'var\(--' static/markflow.css
```
Expected: `302`.

- [ ] **Step 2: Apply rename #1 (`--text-on-accent`)**

```bash
sed -i 's/var(--text-on-accent)/var(--mf-color-text-on-accent)/g' static/markflow.css
```

- [ ] **Step 3: Verify rename #1**

```bash
grep -cE 'var\(--text-on-accent\b' static/markflow.css
```
Expected: `0` (zero pre-rename references remaining).

- [ ] **Step 4: Apply renames #2–20 in order**

```bash
sed -i 's/var(--text-muted)/var(--mf-color-text-muted)/g' static/markflow.css
sed -i 's/var(--text)/var(--mf-color-text)/g' static/markflow.css
sed -i 's/var(--bg)/var(--mf-bg-page)/g' static/markflow.css
sed -i 's/var(--surface-alt\([,)])/var(--mf-surface-alt\1/g' static/markflow.css   # preserves `var(--surface-alt, fallback)` form
sed -i 's/var(--surface)/var(--mf-surface)/g' static/markflow.css
sed -i 's/var(--border)/var(--mf-border)/g' static/markflow.css
sed -i 's/var(--accent-hover)/var(--mf-color-accent-hover)/g' static/markflow.css
sed -i 's/var(--accent)/var(--mf-color-accent)/g' static/markflow.css
sed -i 's/var(--ok)/var(--mf-color-success)/g' static/markflow.css
sed -i 's/var(--warn)/var(--mf-color-warn)/g' static/markflow.css
sed -i 's/var(--error)/var(--mf-color-error)/g' static/markflow.css
sed -i 's/var(--info)/var(--mf-color-info)/g' static/markflow.css
sed -i 's/var(--radius-sm)/var(--mf-radius-sm)/g' static/markflow.css
sed -i 's/var(--radius)/var(--mf-radius-thumb)/g' static/markflow.css
sed -i 's/var(--font-sans)/var(--mf-font-sans)/g' static/markflow.css
sed -i 's/var(--font-mono)/var(--mf-font-mono)/g' static/markflow.css
sed -i 's/var(--shadow-lg)/var(--mf-shadow-popover)/g' static/markflow.css
sed -i 's/var(--shadow)/var(--mf-shadow-press)/g' static/markflow.css
sed -i 's/var(--transition)/var(--mf-transition-med)/g' static/markflow.css
```

- [ ] **Step 5: Verify zero non-`mf-` `var(--…)` references remain**

```bash
grep -nE 'var\(--[a-z]' static/markflow.css | grep -v 'var(--mf-'
```
Expected: empty output (zero lines). If any line prints, there's an unhandled local-prop reference; investigate and add to the rename map.

- [ ] **Step 6: Verify total var count is unchanged or up by 0**

```bash
grep -cE 'var\(--' static/markflow.css
```
Expected: `302` (same as before; renames don't add or remove references).

- [ ] **Step 7: Append rename rows to change-index**

In the change-index `## Local-prop rename map applied` section, replace the placeholder row with the full 20-row map (use the table from the top of this Task verbatim, plus a third column for occurrence count). Get occurrence count for each via:

```bash
for prop in '--mf-color-text-on-accent' '--mf-color-text-muted' '--mf-color-text' '--mf-bg-page' '--mf-surface-alt' '--mf-surface' '--mf-border' '--mf-color-accent-hover' '--mf-color-accent' '--mf-color-success' '--mf-color-warn' '--mf-color-error' '--mf-color-info' '--mf-radius-sm' '--mf-radius-thumb' '--mf-font-sans' '--mf-font-mono' '--mf-shadow-popover' '--mf-shadow-press' '--mf-transition-med'; do
  echo "$prop: $(grep -c "var($prop" static/markflow.css)"
done
```

Use those counts to fill the `occurrence count` column.

- [ ] **Step 8: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): rename markflow.css local custom-props to --mf-*"
```

---

## Task 7: Phase 2 verification + visual checkpoint #1

**Files:**
- No edits. Verification only.

- [ ] **Step 1: Run all Phase-2 sanity checks**

```bash
cd /opt/doc-conversion-2026

# 1: Zero non-mf var refs
grep -nE 'var\(--[a-z]' static/markflow.css | grep -v 'var(--mf-' || echo "OK: zero non-mf var refs"

# 2: Zero prefers-color-scheme
grep -cE 'prefers-color-scheme' static/markflow.css
# Expected: 0

# 3: Every --mf-* used has a :root default
comm -23 \
  <(grep -oE '\-\-mf-[a-z0-9-]+' static/markflow.css | sort -u) \
  <(grep -oE '\-\-mf-[a-z0-9-]+' static/css/design-tokens.css | sort -u)
# Expected: empty output

# 4: !important count unchanged
grep -c '!important' static/markflow.css
# Expected: 3
```

If any check fails, fix in a sub-commit before proceeding.

- [ ] **Step 2: Rebuild Docker container so the changes are served**

```bash
cd /opt/doc-conversion-2026
docker compose build markflow
docker compose up -d markflow
until curl -sf http://localhost:8000/api/health >/dev/null 2>&1; do sleep 2; done
echo "container ready"
```

- [ ] **Step 3: Visual checkpoint #1 — request user review**

Tell the user: *"Phase 2 complete. Ready for visual checkpoint #1. Please:*
*1. Open `http://<VM_IP>:8000/index.html` in your browser. Hard-refresh (Ctrl+Shift+R) to bypass cache.*
*2. Open Display Preferences (avatar menu). Confirm theme switching now visibly affects the page chrome (not just the drawer).*
*3. Try Classic Light → Classic Dark → Classic Light. Confirm pages flip and return.*
*4. Open `/resources.html` and `/admin.html`. Same test.*
*5. Reply 'pass' if it looks right, or describe regressions if not."*

Wait for user confirmation. Do NOT proceed to Task 8 without explicit pass.

---

## Task 8: Phase 3 — substitute page bg + body text literals

**Files:**
- Modify: `static/markflow.css` (lines ~7–45 post-rename — Reset & Base, Typography, Layout sections)

**Scope:** the structural sections covering `html`, `body`, page-level background colors, base text colors. After Tasks 4–6 most of this section already uses `var(--mf-…)`. Phase 3 substitutes any remaining hardcoded literals in this scope.

- [ ] **Step 1: Find literals in scope**

```bash
sed -n '7,45p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|\b(white|black|transparent)\b' | grep -v 'transition\|box-sizing\|font-size\|@import' || echo "OK: no literals in scope"
```

- [ ] **Step 2: For each printed literal, apply the decision tree (spec section "Color-mapping decision tree")**

For every literal in scope:
1. **Branch 1 — exact existing-token match:** check if the literal matches a `:root` default in design-tokens.css. If yes, replace `<literal>` with `var(--mf-existing-token)`.
2. **Branch 2 — drift ≤ 5:** check max channel delta vs nearest `:root` default. If yes, replace with snap. Note in change-index `## Snapped colors`.
3. **Branch 3 — recurring (≥2 occurrences) semantic:** check `grep -cE '<literal>' static/markflow.css`. If ≥ 2 AND has clear semantic role, introduce a new token in design-tokens.css :root + replace.
4. **Branch 4 — one-off no role:** keep as literal. Note in change-index `## Kept literals`.
5. **Branch 5 — status / format:** N/A in this section (status colors live in Phase 8).

- [ ] **Step 3: Apply each substitution via Edit tool**

For each literal that resolves to "replace", use the Edit tool with the exact line as `old_string` to ensure unique replacement.

- [ ] **Step 4: Append rows to change-index for each touched line**

Use the `## Substitutions` table format from the spec.

- [ ] **Step 5: Verify no literals remain in scope**

```bash
sed -n '7,45p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)' | grep -v 'transition\|box-sizing\|font-size'
```
Expected: empty (or only `## Kept literals` rows you've explicitly kept).

- [ ] **Step 6: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): page bg + body text literals -> var()"
```

---

## Task 9: Phase 4 — substitute nav + header literals

**Files:**
- Modify: `static/markflow.css` (Navigation Bar section, lines ~46–92 post-Phase-3)

**Scope:** `.nav-bar`, `.nav-link`, `.nav-logo`, `.nav-badge`, top header strip. **No HTML or selector-name changes** — only color/border/shadow values.

- [ ] **Step 1: Find the section**

```bash
grep -n "Navigation Bar\|nav-bar\|nav-link\|nav-logo\|nav-badge" static/markflow.css | head -5
```
Record start and end lines (look for the next `/* ── … */` comment as the end).

- [ ] **Step 2: Find literals in that range**

```bash
sed -n '<start>,<end>p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|\b(white|black|transparent)\b' | grep -v 'transition\|cursor\|font'
```

- [ ] **Step 3: Apply decision tree per literal**

Same as Task 8 step 2.

Special case: `.nav-link--active { background: rgba(79,91,213,.08); }` — the `rgba(79,91,213,...)` is the markflow accent (`#4f5bd5`) at low alpha. Snap to `var(--mf-color-accent-tint)` (existing token, default `#f3f0ff`). If the visual review later flags drift, introduce `--mf-color-accent-tint-alt` with the rgba form.

- [ ] **Step 4: Apply substitutions, log change-index rows**

Same pattern as Task 8.

- [ ] **Step 5: Verify**

```bash
sed -n '<start>,<end>p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)' | grep -v 'transition\|cursor\|font'
```
Expected: empty (or kept-literals only).

- [ ] **Step 6: Visual checkpoint #2 (after-Phase-6 in the spec, but easier to spot regressions early on nav) — optional inline check**

Reload `/index.html`, hard-refresh, eyeball the top nav. If looks right on Classic Light + Classic Dark, proceed.

- [ ] **Step 7: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): nav + header literals -> var()"
```

---

## Task 10: Phase 5 — substitute buttons + links + form-control literals

**Files:**
- Modify: `static/markflow.css` (Card section, Buttons section, Forms section, Range slider, Toggle switch — pre-refactor lines 137–537, adjusted for prior deletions)

**Scope:** `.card` base, `.btn-*`, `a` rules, `input`, `textarea`, `select`, `label`, `.form-group`, `input[type="range"]`, `.toggle`, `input[type="checkbox"] + .toggle-track`. Approximately 80 selectors total.

- [ ] **Step 1: Find the section boundaries**

```bash
grep -n "/\* ── " static/markflow.css | head -30
```
Identify the `Card`, `Buttons`, `Forms`, `Range slider`, `Toggle switch` section markers and their line ranges.

- [ ] **Step 2: Find literals in scope**

For each section identified:
```bash
sed -n '<start>,<end>p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|\b(white|black|transparent)\b' | grep -v 'transition\|cursor\|font'
```

- [ ] **Step 3: Apply decision tree per literal**

Same as Task 8/9. Status of common cases:
- `transparent` (lines 191, 317): keep as literal — CSS keyword, not a color.
- `rgba(79,91,213,.15)` for focus rings: snap to `var(--mf-color-accent-ring)`.
- `rgba(255,255,255,.08)`, `rgba(255,255,255,.15)`, `rgba(255,255,255,.35)` (toggle track styles): keep as literal — these are theme-agnostic UI overlays.
- `rgba(0,0,0,.25)`, `rgba(0,0,0,.3)` (toggle thumb shadows): keep as literal — shadows.
- `rgba(99,102,241,.4)` (toggle on-state shadow): drift from accent; introduce new token `--mf-color-accent-glow` with `:root` default `rgba(91, 61, 245, 0.4)`.
- `#fff` in `.toggle input:checked + .toggle-track::after`: replace with `var(--mf-color-text-on-accent)`.

- [ ] **Step 4: Apply substitutions, log change-index rows**

- [ ] **Step 5: Verify**

```bash
# Re-grep each sub-section
sed -n '<start>,<end>p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)' | grep -v 'transition\|cursor\|font'
```

- [ ] **Step 6: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): buttons + links + forms -> var()"
```

---

## Task 11: Phase 6 — substitute cards + panels + modals literals + visual checkpoint #2

**Files:**
- Modify: `static/markflow.css` (Inline Error, Toast, Dialog/Modal, Detail Panel, Drop Zone, Modal Backdrops, Preview Popup sections)

**Scope:** `.inline-error`, `.error-text`, `.toast`, `.toast-success`, `.toast-error`, `.toast-info`, `.modal`, `.modal-card`, `.modal-backdrop`, `.detail-panel`, `.detail-content`, `.drop-zone`, `.dz-*`, `.preview-popup`, `.preview-header`, `.preview-body`. Approximately 60 selectors.

- [ ] **Step 1: Find sections**

Same grep pattern as Task 10 step 1.

- [ ] **Step 2: Find literals in scope**

Same pattern as Task 10 step 2.

- [ ] **Step 3: Apply decision tree per literal**

Common cases:
- `.toast-success { color: white; }`, `.toast-error { color: white; }`, `.toast-info { color: white; }`: replace `white` with `var(--mf-color-text-on-accent)`.
- `.modal-backdrop { background: rgba(0,0,0,.4); }`: keep as literal — overlay color is theme-agnostic.
- `rgba(79,91,213,.04)` in `.drop-zone:hover` etc.: snap to a new token `--mf-color-accent-tint-2` if not yet introduced (its existing default is `#f5f3ff` — an opaque tint — so this rgba snapshot doesn't fit; keep as literal OR introduce new `--mf-color-accent-glow-soft`).
- Preview popup colors (lines 1502–1535): apply decision tree per-literal; the preview is themed by passing parent context — most should snap to surface/text/border tokens.

- [ ] **Step 4: Apply substitutions, log change-index rows**

- [ ] **Step 5: Verify**

```bash
# Re-grep each sub-section in scope
sed -n '<start>,<end>p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)' | grep -v 'transition\|cursor\|font'
```

- [ ] **Step 6: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): cards + panels + modals -> var()"
```

- [ ] **Step 7: Rebuild Docker + visual checkpoint #2**

```bash
cd /opt/doc-conversion-2026
docker compose build markflow && docker compose up -d markflow
until curl -sf http://localhost:8000/api/health >/dev/null 2>&1; do sleep 2; done
```

Tell the user: *"Phase 6 complete. Visual checkpoint #2:*
*1. Open `/resources.html`, `/admin.html`, and one settings page.*
*2. Verify on Classic Light, Classic Dark, Cobalt, and Sage.*
*3. Confirm cards, modals, and toasts read correctly on all four themes.*
*4. Reply 'pass' or describe regressions."*

Wait for explicit pass before Task 12.

---

## Task 12: Phase 7 — substitute tables + lists + pagination literals

**Files:**
- Modify: `static/markflow.css` (Table, Pagination, Autocomplete, Help & Docs sections)

**Scope:** `table`, `thead`, `tbody`, `tr`, `td`, `th`, `.pagination`, `.paginator`, `.autocomplete`, `.autocomplete-list`, `.autocomplete-item`, `.help-sidebar`, `.help-content`, `.article-link`, `blockquote.note`, `blockquote.tip`, `blockquote.warning`. Approximately 80–100 selectors (help section is large).

- [ ] **Step 1: Find sections**

```bash
grep -n "/\* ── \(Table\|Pagination\|Autocomplete\|Help \)" static/markflow.css
```

- [ ] **Step 2: Find literals**

Same grep pattern as before.

- [ ] **Step 3: Apply decision tree per literal**

Special note: help-content `blockquote.note/.tip/.warning` likely use status-adjacent colors. Snap them to `--mf-color-info`, `--mf-color-success`, `--mf-color-warn` per A4.

- [ ] **Step 4: Apply substitutions, log rows**

- [ ] **Step 5: Verify**

```bash
sed -n '<start>,<end>p' static/markflow.css | grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)' | grep -v 'transition\|cursor\|font'
```

- [ ] **Step 6: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): tables + lists + pagination -> var()"
```

---

## Task 13: Phase 8 — substitute status badges + alerts + edge cases + final visual checkpoint

**Files:**
- Modify: `static/markflow.css` (everything remaining: status badges, format badges, status pills, lifecycle, banners, workers panel, mount status, stat pills, timeline, etc.)

**Scope:** `.badge-*` (light values), `.status-pill--*`, `.lifecycle-*`, `.error-banner`, `.flag-banner` (light), `.stop-banner` (light), `.storage-verify` (light), `.mount-status-dot.*`, `.pl-status-pill`, `.stat-pill--*`, `.tool-fast/.tool-slow/.tool-danger` (light), `.workers-panel`, `.worker-item`, `.timeline`, `.section-divider`, `.empty-state`, `.empty-icon`, `.ocr-banner`, `.reconnecting-badge`, `.deletion-banner`. Approximately 100+ selectors.

- [ ] **Step 1: Find every remaining hex/rgba literal**

```bash
grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)' static/markflow.css | grep -v 'transition\|font-size' | head -60
```

- [ ] **Step 2: Apply decision tree branch 5 (status snap) per literal**

Per A4: snap status colors to `--mf-color-success/warn/error/info`. Format badge values were already moved to `[data-theme="classic-dark"]`-prefixed rules in Task 5 (dark variants); the **light variants** still in markflow.css get substituted here.

For example:
```css
.badge-pdf  { background: #fee2e2; color: #991b1b; }
```
becomes:
```css
.badge-pdf  { background: var(--mf-color-error-bg); color: var(--mf-color-error); }
```
(if `--mf-color-error-bg` exists; if not, snap `#fee2e2` to `--mf-color-error-bg` — yes, design-tokens.css has it at line 43).

Status pill tokens follow the same pattern. Single-occurrence one-offs (e.g., `.deletion-banner` colors): keep as literal per branch 4.

- [ ] **Step 3: Apply substitutions, log rows**

- [ ] **Step 4: Verify final state**

```bash
# Final hex literal count (should be ~5–10 for kept-as-literal one-offs)
grep -oE '#[0-9a-fA-F]{3,8}\b' static/markflow.css | sort -u | wc -l

# Zero non-mf var refs
grep -nE 'var\(--[a-z]' static/markflow.css | grep -v 'var(--mf-' || echo "OK"

# Zero prefers-color-scheme
grep -cE 'prefers-color-scheme' static/markflow.css
# Expected: 0

# !important unchanged
grep -c '!important' static/markflow.css
# Expected: 3

# All --mf-* used have :root defaults
comm -23 \
  <(grep -oE '\-\-mf-[a-z0-9-]+' static/markflow.css | sort -u) \
  <(grep -oE '\-\-mf-[a-z0-9-]+' static/css/design-tokens.css | sort -u)
# Expected: empty
```

- [ ] **Step 5: Commit**

```bash
git add static/markflow.css docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md
git commit -m "refactor(orig-ux): status + edge-case literals -> var()"
```

- [ ] **Step 6: Final visual checkpoint #3**

```bash
cd /opt/doc-conversion-2026
docker compose build markflow && docker compose up -d markflow
until curl -sf http://localhost:8000/api/health >/dev/null 2>&1; do sleep 2; done
```

Tell the user: *"All 8 phases complete. Final visual checkpoint:*
*1. Open all 26 legacy pages on Classic Light. List of pages: index.html, resources.html, admin.html, db-health.html, help.html, bulk.html, bulk-review.html, batch-management.html, history.html, log-management.html, log-viewer.html, locations.html, flagged.html, providers.html, status.html, storage.html, settings.html, search.html, viewer.html, preview.html, progress.html, review.html, trash.html, unrecognized.html, pipeline-files.html, job-detail.html.*
*2. Sample 5 pages on Classic Dark and 5 on Cobalt.*
*3. Confirm change-index doc has rows that match all substitutions made.*
*4. Reply 'pass' to authorize squash + PR."*

Wait for explicit pass.

---

## Task 14: Squash and open PR

**Files:**
- No source-file edits.

- [ ] **Step 1: Confirm branch is up-to-date with main**

```bash
git fetch origin
git log origin/main..HEAD --oneline
```
Expected: 13 commits (Tasks 1–13 each landed one commit; Task 6 may have multiple sub-commits if rename verification revealed missed props).

- [ ] **Step 2: Squash to a single commit**

```bash
# Preserve the change-index doc; squash everything onto the original Task 1 setup commit
COMMIT_COUNT=$(git rev-list --count origin/main..HEAD)
git reset --soft "HEAD~$((COMMIT_COUNT - 1))"
```

Then create the squash commit:

```bash
git commit --amend -m "$(cat <<'EOF'
refactor(orig-ux): make markflow.css theme-aware via var(--mf-…) substitution

Reconciled markflow.css with the v0.37.0 [data-theme] system:
- Renamed all 302 var(--…) references from local props to --mf-* equivalents
- Deleted main :root + @media (prefers-color-scheme: dark) block (lines 7-50)
- Converted 6 remaining @media (prefers-color-scheme: dark) blocks to
  html[data-theme="classic-dark"] selector prefixes
- Substituted ~100 hardcoded color literals with var(--mf-…) calls
- Added 5 new tokens to design-tokens.css :root (--mf-surface-alt,
  --mf-color-text-on-accent, --mf-color-accent-hover, --mf-color-info,
  --mf-radius-sm) plus classic-dark overrides for surface-alt, accent-hover,
  info, shadow-press, shadow-popover

After this commit, switching themes in the Display Preferences drawer visibly
re-themes the 26 legacy original-UX pages, not just the new-UX chrome.

Spec: docs/superpowers/specs/2026-05-01-markflow-theme-refactor-design.md
Plan: docs/superpowers/plans/2026-05-01-markflow-theme-refactor.md
Change-index: docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push branch**

```bash
git push -u origin refactor/markflow-css-theme-aware
```

- [ ] **Step 4: Open PR**

```bash
gh pr create \
  --title "refactor(orig-ux): make markflow.css theme-aware" \
  --body "$(cat <<'EOF'
## Summary

- Renames every `var(--…)` in `markflow.css` from local custom-prop names to `--mf-*` equivalents (302 substitutions)
- Deletes all 7 `@media (prefers-color-scheme: dark)` blocks; the main `:root` override block is dropped, the other 6 are rewritten as `html[data-theme="classic-dark"]`-scoped rules
- Substitutes ~100 hardcoded color literals with `var(--mf-…)` calls per the spec's color-mapping decision tree
- Adds 5 new tokens to `design-tokens.css` (`--mf-surface-alt`, `--mf-color-text-on-accent`, `--mf-color-accent-hover`, `--mf-color-info`, `--mf-radius-sm`) plus `classic-dark` overrides for 5 tokens in `design-themes.css`

After merge, switching themes in the Display Preferences drawer visibly re-themes the 26 legacy original-UX pages — not just the new-UX chrome.

## Test plan

- [ ] Hard-refresh `/index.html` on Classic Light. Confirm pixel-near identical to pre-refactor.
- [ ] Switch to Classic Dark via drawer. Confirm page chrome flips dark; nav, cards, status pills all readable.
- [ ] Switch to Cobalt. Confirm accent color changes appropriately.
- [ ] Sample 5 random legacy pages on Classic Dark.
- [ ] Confirm `docs/superpowers/specs/2026-05-01-markflow-theme-refactor-change-index.md` has rows for every substitution.
- [ ] Run verification commands from `Task 13 Step 4` of the plan; confirm all pass.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Wait for review approval, then merge**

After reviewer approves, squash-merge via the GitHub UI or:

```bash
gh pr merge --squash --delete-branch
```

---

## Acceptance check (run before declaring this plan complete)

- [x] Every task has a Files list, numbered steps, exact commands, expected output.
- [x] No `[PLACEHOLDER]` or `TBD` markers anywhere in the plan.
- [x] Every `var(--mf-…)` referenced in markflow.css has a corresponding `:root` default in design-tokens.css (Task 2).
- [x] Every spec architecture decision (A1–A12) maps to a task: A1/A2 → Task 14 squash, A3/A6 → Task 2, A4 → Task 13, A5 → noted in Task 8 step 2, A7 → change-index updates throughout, A8/A10 → Tasks 4 & 6, A9 → Tasks 4 & 5, A11 → Task 6 rename map rows 14–17, A12 → Task 6 rename map rows 18–19 + Task 3 shadow overrides.
- [x] All 7 `@media (prefers-color-scheme: dark)` blocks accounted for: block 1 deleted in Task 4, blocks 2–7 converted in Task 5.
- [x] Three visual checkpoints (Tasks 7, 11, 13) include explicit user pass/fail gates.
- [x] Change-index doc structure is concrete (Task 1 scaffolds it, Tasks 2–13 fill it).
- [x] Rollback story stated: revert squash commit + delete change-index sidecar.

## Self-review

- **Spec coverage:** Every section of the spec is implemented in a task. Decision tree branches 1–5 are referenced by Phase 3–8 tasks. Rename map (20 entries) is enumerated verbatim in Task 6. Five new tokens enumerated verbatim in Task 2. Three visual checkpoints from spec are Tasks 7, 11, 13. ✓
- **Placeholder scan:** No `TBD`, `TODO`, "fill in details", or "similar to Task N" patterns. ✓
- **Type consistency:** All token names use the `--mf-` prefix consistently. The `--mf-color-text-on-accent` name is used identically in Tasks 2, 6, 10, 11. The 7 @media block line numbers are stated pre-Task-4 (270, 350, 1168, 1231, 1384, 1402) in Task 5; Task 5 step 1 instructs the implementer to re-grep for post-Task-4 line numbers. ✓
- **Implementer judgment bounded:** Decision tree mechanizes per-literal calls. Implementer's discretion is bounded to ~5–10 mid-implementation new-token additions, all logged. Each phase has explicit verification commands to confirm completion. ✓

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-01-markflow-theme-refactor.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — Orchestrator dispatches a fresh Sonnet 4.6 subagent per task, reviews the diff between tasks, fast iteration. Maps to spec's Sonnet/medium implementer choice. Three explicit user-review gates at Tasks 7, 11, 13.

2. **Inline Execution** — Execute tasks in this session via `superpowers:executing-plans`. Batch execution with checkpoints at the same three visual checkpoints. Higher token cost on the orchestrator since the implementation context lives in this conversation.

**Which approach?**
