# UX Overhaul — First-Run Onboarding Flow (Plan 8)

**Goal:** Show new users a 3-step onboarding overlay on their first visit to the search home page: (1) Welcome, (2) Layout picker, (3) Pin folders. After completion (or skip), the overlay is suppressed permanently via a user preference. This is the final phase of the UX overhaul.

**Architecture:** `MFOnboarding` is a self-contained overlay component mounted on top of `#mf-home` by the index-new-boot.js. It does NOT replace the home page — the home page mounts underneath it. The overlay is shown only when `MFPrefs.get('onboarding_done')` is falsy. On completion or skip, it sets the preference (server + local) and removes itself from the DOM.

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/layout-onboarding.html` — Step 2 (Layout picker) is fully mocked. Step 1 and Step 3 are described in spec §3 ("mock pending").

**Out of scope:**
- Convert page redesign (Phase 9, separate sub-spec, explicitly out of scope for this spec)
- Step 3 folder drag-and-drop reordering (checkbox-select only for v1)
- Onboarding reset UI in settings (future admin tool)

**Prerequisites:** Plans 1–7 complete. `MFPrefs` (preferences.js) working with server sync. `/api/storage/sources` available (used to populate the folder list in Step 3). `/api/user-prefs` available for setting `onboarding_done`.

---

## Agent dispatch guide

| Task | Impl agent | Impl model | Review agent | Review model | Rationale |
|---|---|---|---|---|---|
| Task 1 — Overlay shell + Steps 1 & 2 | `mf-impl-high` | **sonnet** | `mf-rev-high` | **sonnet** | Multi-step state machine; preference sync; layout-mode side-effect on home page underneath |
| Task 2 — Step 3 (pin folders) | `mf-impl-high` | **sonnet** | `mf-rev-medium` | **haiku** | Folder list from API + checkbox selection + save to user prefs; established pattern |
| Task 3 — Boot integration | `mf-impl-high` | **sonnet** | `mf-rev-high` | **sonnet** | Modifies existing `index-new-boot.js`; timing/ordering matters; regression risk on home page |

Override Task 1 or Task 3 to opus only if the home-page mount ordering proves difficult (e.g., flash of underlying home while overlay transitions in).

---

## File structure

**Create:**
- `static/js/components/onboarding.js` — `MFOnboarding` overlay component

**Modify:**
- `static/js/index-new-boot.js` — check onboarding state after mount, conditionally show overlay
- `static/css/components.css` — append `mf-ob__*` block (overlay, step cards, layout previews, folder list)

No new HTML templates or routes needed — the overlay is injected into the existing home page DOM.

---

## Task 1: Overlay shell + Step 1 (Welcome) + Step 2 (Layout picker)

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-high` (model: **sonnet**)

**Component: `MFOnboarding.show({ onComplete, onSkip })`**

`show()` creates and appends a full-viewport overlay to `document.body`. Returns `{ hide }` so the boot can tear it down programmatically if needed.

**Overlay shell structure:**

```
.mf-ob__backdrop           — full-viewport semi-transparent overlay (rgba(10,10,10,0.55))
  .mf-ob__card             — centered card (max-width 640px), white, radius 18px, shadow
    .mf-ob__progress       — 3 dots (filled/unfilled) indicating current step
    .mf-ob__step           — step content (swapped per step)
    .mf-ob__footer         — nav: "Back" ghost · "Skip setup" ghost (right) · "Next →" primary
```

Step transitions: remove current step node, append next step node. No CSS animation required for v1 (keep it simple — no flash).

**Step 1 — Welcome:**

```
Large emoji icon: 🗂️
Headline: "Welcome to MarkFlow."
Subtitle: "Find any document on the K Drive in seconds. Let's get you set up."
[Next →]  [Skip setup]
```

Content is static text. No API calls. "Skip setup" calls `onSkip()` immediately.

**Step 2 — Layout picker:**

Three cards in a row (matches `layout-onboarding.html` mockup):

| Card | Mini preview | Name | "Best for…" | Recommended badge |
|---|---|---|---|---|
| Maximal | Grid of small cards + search bar | Maximal | "Tuesday at 10am — browse everything" | — |
| Recent | Search bar + chip row + recent cards | Recent | "Friday catch-up — jump back in" | — |
| Minimal | Large centered search bar only | Minimal | "Mid-meeting lookup — just search" | **Recommended** (purple ring + badge) |

Each card: `button.mf-ob__layout-card`. Selected state: purple ring (`box-shadow: 0 0 0 2px var(--mf-color-accent)`). Default selected: Minimal.

Mini-previews are tiny SVG wireframes or CSS-rendered block layouts — do NOT use external images or base64 data URIs. Use simple CSS rectangles/divs inside the card to approximate the layout.

On "Next →": save the selected layout immediately via `MFPrefs.set('layout', selectedMode)` (this updates both localStorage and server). Then advance to Step 3.

Keyboard: `←` / `→` arrows cycle card selection. `Enter` selects and advances.

---

## Task 2: Step 3 (Pin folders)

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-medium` (model: **haiku**)

**APIs consumed:**
- `GET /api/storage/sources` → `[{ id, path, label }]` — indexed source paths to offer as pinnable folders
- `PUT /api/user-prefs/pinned_folders` → save selected folder IDs (array of path strings)

Alternatively, if source paths are too few or zero (fresh install), show a "No folders indexed yet — you can pin folders later from the home page" stub and allow the user to complete setup anyway.

**Step 3 — Pin folders:**

```
Icon: 📌
Headline: "Pin your first folders."
Subtitle: "These appear as quick-access cards on your home page."
```

Folder list: `ul.mf-ob__folder-list`. Each item: `li.mf-ob__folder-item` with a checkbox (18px), folder icon, path label. Up to 8 items shown; if more, "Show all" expander.

Pinned state: `li.mf-ob__folder-item--pinned`. Clicking the row toggles pinned state. Max 6 pins; if user tries to add a 7th, show inline note: "Unpin one to add another."

On "Finish setup" (replaces "Next →" in footer):
1. Collect pinned paths array
2. `MFPrefs.set('pinned_folders', JSON.stringify(pinnedPaths))` — local + server sync
3. Call `onComplete()` — boot will call `MFOnboarding.hide()` and set `onboarding_done`

On "Skip" at Step 3: pinned folders not saved; `onComplete()` still called (skipping a step is still completing setup).

**Empty state (no sources):**

```
.mf-ob__folder-empty
  Icon: 🗂️ (muted)
  "No indexed folders yet."
  "Folders appear here once the pipeline scans your K Drive."
  [Finish setup →]
```

- [ ] **Step 3:** Add Step 3 `_renderPinFolders(sources)` function to `onboarding.js`
- [ ] **Step 4:** Wire "Finish setup" button to save pinned folders + call `onComplete()`

---

## Task 3: Boot integration

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-high` (model: **sonnet**)

**Modify `static/js/index-new-boot.js`:**

After `MFHome.mount(homeRoot, ...)` completes (inside the `.then()` block), add:

```javascript
// Show onboarding overlay for first-time users
if (!MFPrefs.get('onboarding_done')) {
  var sources = summaryData ? (summaryData.sources || []) : [];
  MFOnboarding.show({
    sources: sources,
    onComplete: function () {
      MFPrefs.set('onboarding_done', '1');
    },
    onSkip: function () {
      MFPrefs.set('onboarding_done', '1');
    },
  });
}
```

`summaryData` is already fetched by the boot (from `/api/activity/summary`). Extract sources from it if present, otherwise fetch `/api/storage/sources` lazily inside `MFOnboarding.show()` (pass a `fetchSources` function instead of raw data — this avoids the extra request for returning users).

**Revised approach (lazy fetch inside component):**

```javascript
MFOnboarding.show({
  fetchSources: function () {
    return fetch('/api/storage/sources', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { sources: [] }; })
      .catch(function () { return { sources: [] }; });
  },
  onComplete: function () { MFPrefs.set('onboarding_done', '1'); },
  onSkip:     function () { MFPrefs.set('onboarding_done', '1'); },
});
```

`MFOnboarding.show()` starts the lazy fetch before the user reaches Step 3 (initiate in the background when Step 2 renders), so the folder list is ready by the time the user clicks "Next →."

**CSS: `mf-ob__*` block (append to `components.css`):**

- `.mf-ob__backdrop` — `position: fixed; inset: 0; background: rgba(10,10,10,0.55); z-index: 100; display: flex; align-items: center; justify-content: center;`
- `.mf-ob__card` — `background: var(--mf-surface); border-radius: 18px; width: 100%; max-width: 640px; padding: 2.4rem 2.6rem; box-shadow: 0 24px 80px -24px rgba(0,0,0,0.38); position: relative;`
- `.mf-ob__progress` — dot row
- `.mf-ob__dot` + `.mf-ob__dot--active` — step indicator dots
- `.mf-ob__step-icon` — 56px emoji display
- `.mf-ob__headline` — 1.8rem, weight 700, tight tracking
- `.mf-ob__subtitle` — muted, max-width 40ch
- `.mf-ob__layout-cards` — 3-column grid, gap 0.85rem
- `.mf-ob__layout-card` — button, border 1.5px solid var(--mf-border), radius 12px, padding 1rem, cursor pointer
- `.mf-ob__layout-card--selected` — box-shadow 0 0 0 2px var(--mf-color-accent), border-color var(--mf-color-accent)
- `.mf-ob__layout-card--recommended` — has `.mf-ob__recommended-badge` (purple pill top-right)
- `.mf-ob__layout-preview` — 90px tall CSS wireframe area inside the card
- `.mf-ob__card-name` — layout mode name, weight 600
- `.mf-ob__card-desc` — "best for…" text, muted, 0.8rem
- `.mf-ob__folder-list` — list-style none, margin/padding 0
- `.mf-ob__folder-item` — flex row, checkbox + icon + label, padding 0.6rem 0, border-bottom soft
- `.mf-ob__folder-item--pinned` — checkbox filled accent
- `.mf-ob__folder-empty` — centered, muted, dashed border
- `.mf-ob__footer` — flex row, justify-content space-between, margin-top 2rem

- [ ] **Step 5:** Append `mf-ob__*` CSS to `components.css`
- [ ] **Step 6:** Add `onboarding.js` script tag to `static/index-new.html` (before `index-new-boot.js`)
- [ ] **Step 7:** Modify `static/js/index-new-boot.js` — add onboarding check after home mount
- [ ] **Step 8:** Commit `feat(ux): First-run onboarding overlay — welcome, layout picker, pin folders (Plan 8)`

---

## Acceptance checks

- [ ] `grep -n "innerHTML" static/js/components/onboarding.js` — zero matches
- [ ] Fresh user (no `onboarding_done` in localStorage): overlay appears on home page load
- [ ] Returning user (`onboarding_done` set): overlay does NOT appear
- [ ] Step 1 → Step 2 → Step 3 navigation works (Next / Back)
- [ ] "Skip setup" on Step 1 sets `onboarding_done` immediately and hides overlay
- [ ] "Skip" on Step 3 still sets `onboarding_done`
- [ ] Layout card selection: keyboard `←`/`→` cycles selection; Minimal pre-selected
- [ ] Selecting Minimal on Step 2 and clicking Next: home page underneath reflects Minimal layout (MFPrefs.get('layout') === 'minimal')
- [ ] Pin folder checkboxes correctly toggle pinned state; max-6 warning appears at 7th
- [ ] "Finish setup" saves pinned_folders pref and sets onboarding_done
- [ ] Empty-state renders when /api/storage/sources returns empty array
- [ ] Overlay focus is trapped (Tab key stays within the overlay card)
- [ ] Home page underneath is interactive after overlay is dismissed
- [ ] `MFPrefs.get('onboarding_done')` is '1' after completion — verified in browser console
