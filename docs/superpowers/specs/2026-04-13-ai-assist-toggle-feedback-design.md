# AI Assist Toggle — Better Feedback + Pre-Search Intent

**Date:** 2026-04-13
**Target version:** v0.24.1
**Scope:** Search page AI Assist toggle only. No drawer, provider, or results-layout changes.

## Problem

Two user complaints, one session:

1. **"Better feedback when selected"** — the active state (accent border + 10% accent tint + accent text) is too subtle. Label stays `AI Assist` regardless of on/off. Easy to miss.
2. **"Can it be selected before completing a search?"** — yes, it already can (persistent localStorage preference), but the UI gives no signal about what that state *means* before a search runs. And toggling ON *after* a search doesn't retroactively synthesize — another silent-failure surprise.

## Design

### 1. Stronger active visual

- **Off:** unchanged (transparent, muted border + text).
- **On:** solid accent fill, white text. Remove the small dot (redundant with solid fill).

### 2. Label state

- Off: `✦ AI Assist`
- On: `✦ AI Assist · On` (with `On` styled bold inside a small inline pill)

### 3. Intent hint under the search box

One-line caption, only visible when `enabled === true` AND no results currently rendered:

> ✦ AI synthesis will run on your next search

Disappears on first results render. Reappears if the user toggles ON again from a no-results state.

### 4. "Synthesize these results" action

When the user toggles ON *while results are already on screen*, show an inline button in the results toolbar:

> ✦ Synthesize these results

Clicking calls `AIAssist.runOnCurrentResults()`, which re-invokes `onResults(currentQuery, currentHits)`. Button hides once synthesis starts or after results are cleared.

### 5. needs-config state

Unchanged.

## Files touched

| File | Change |
|------|--------|
| `static/css/ai-assist.css` | Stronger `.active` (solid accent fill, white text, hide dot). New `.ai-assist-hint` and `.ai-assist-run-btn` styles. |
| `static/search.html` | Update toggle markup (`On` pill span); add `#ai-assist-hint` element under `.search-box`; add `#ai-assist-run-btn` inside toolbar-right. |
| `static/js/ai-assist.js` | New `_updateHint()` and `_updateRunButton()` helpers; public `runOnCurrentResults()`. Wire into `setEnabled()` and `onResults()`. Expose a `setCurrentResultsRef(getter)` so the search page can supply current results without reaching into internals. |
| `core/version.py` | Bump to v0.24.1. |
| `CLAUDE.md`, `docs/version-history.md`, `docs/help/whats-new.md`, `docs/help/search.md` | Release note + help update. |

## Out of scope

Drawer redesign, provider UX, autocomplete/results redesign, keyboard shortcut for AI toggle.

## Test plan

Manual in the running container:

1. Load `/search.html` cold with toggle off — label reads `✦ AI Assist`, no hint.
2. Click toggle — label gains `· On`, button fills solid accent, hint appears under search box.
3. Run a search — hint disappears, drawer opens with streaming response.
4. Clear search; toggle remains on; hint reappears.
5. Toggle off; reload page; toggle stays off (localStorage persists).
6. Toggle on *after* results are already showing — `Synthesize these results` button appears in toolbar, clicking it streams synthesis without a new search.
7. `needs-config` path still shows amber styling when provider unconfigured.

## Rollback

All changes isolated to three static files + version + docs. Revert the release commit.
