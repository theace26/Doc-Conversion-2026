# UX Overhaul — Search-as-Home Page Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Land the new Search-as-home page with three layout modes (Maximal / Recent / Minimal). Wire to existing `/api/search`. Render Maximal-mode browse rows from mocks for v1 (real endpoints come in Plan 4 IA shift). Replace `static/index.html` behind the `ENABLE_NEW_UX` feature flag — old Convert page stays live when the flag is off.

**Architecture:** New `static/index.html` is split — feature-flag check at top decides whether to render the legacy Convert page or the new Search home. Layout-mode renderer is a single `MFSearchHome.mount(slot, opts)` function that swaps DOM based on `MFPrefs.layout`. Browse rows in Maximal mode use MFCardGrid + `MFFolderBrowse`-style sections. Hero search bar hits the existing `/api/search` endpoint (v1 preserves search-results behavior — only the home page is new). Recent layout reads `MFPrefs.recent_searches` and renders chips + recently-opened cards. Minimal layout shows the brand headline + centered search bar only. **Safe DOM construction throughout.**

**Tech stack:** Vanilla HTML / CSS / JS · existing `/api/search` for query handling

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §3 (layout modes), §10 (preferences for layout + recent searches), §12 phase 2 + 3 phasing

**Mockup reference:**
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/home-search-v3.html` (Maximal layout — final)
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/home-layout-modes.html` (all three modes)
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/home-search-v2.html` (density toggle + sections)

**Out of scope (deferred):**
- Real backend endpoints for browse rows (Plan 4 ships `/api/folders/pinned`, `/api/files/recently-opened`, `/api/files/flagged`, `/api/topics`, and the watched-folder feed)
- First-run onboarding (Plan 8 — welcome page + layout picker + pin folders)
- Activity dashboard (Plan 4)
- Settings detail pages (Plans 5–7)
- Search results page redesign — v1 preserves the existing `/static/search.html` rendering; only the home page is new

**Prerequisites:** Plans 1A + 1B + 1C + 2A + 2B must all be complete. Run `git log --oneline | head -25` and confirm: `f37e633` (1A), `50e552e` (1B), `3d5b1e9` (1C), `6228373` (2A), `1dc467c` (2B).

---

## File structure (this plan creates / modifies)

**Create:**
- `static/js/components/search-bar.js` — Airbnb-style segmented hero search bar
- `static/js/components/browse-row.js` — generic horizontal-scroll row with title link + cards
- `static/js/components/topic-cloud.js` — pill cloud of topics
- `static/js/pages/search-home.js` — top-level page mount that swaps layouts
- `static/js/sample-rows.js` — mock browse-row data (Plan 4 replaces with API calls)
- `static/index-new.html` — the new Search-as-home page template
- `tests/test_search_home_flag.py` — server-side feature-flag routing test

**Modify:**
- `static/css/components.css` — append search-bar, browse-row, topic-cloud, hero, layout-mode styles
- `main.py` — flag-aware index route (serves `index-new.html` when `ENABLE_NEW_UX=true`)
- `static/dev-chrome.html` — load new scripts; add a Search-home demo section
- `static/dev-chrome.js` — wire the layout-mode demo

---

## Task 1: Hero search bar component (Airbnb-style segmented)

**Files:**
- Create: `static/js/components/search-bar.js`

`760px` segmented bar: **Looking for** · **Format** · **When** · circular submit button. On submit, navigates to `/search?q=...` (existing endpoint).

- [x] **Step 1: Create the component**

Create `static/js/components/search-bar.js`:

```javascript
/* Hero search bar. Airbnb-style segmented input with three fields and
 * a circular submit button.
 *
 * Usage:
 *   MFSearchBar.mount(slot, {
 *     onSubmit: function(payload) { ... }   // { q, format, when }
 *   });
 *
 * Safe DOM throughout. No frameworks.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function makeSeg(label, placeholder, name, flex) {
    var seg = el('div', 'mf-sb__seg');
    if (flex) seg.style.flex = String(flex);
    var lab = el('div', 'mf-sb__label');
    lab.textContent = label;
    var input = el('input', 'mf-sb__input');
    input.type = 'text';
    input.name = name;
    input.placeholder = placeholder;
    seg.appendChild(lab);
    seg.appendChild(input);
    return { wrap: seg, input: input };
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSearchBar.mount: slot is required');
    var onSubmit = (opts && opts.onSubmit) || function () {};

    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var form = el('form', 'mf-sb');
    form.setAttribute('role', 'search');
    var q = makeSeg('Looking for', 'Keywords, filename, or natural language', 'q', 2);
    var fmt = makeSeg('Format', 'Any', 'format', 1);
    var when = makeSeg('When', 'Anytime', 'when', 1);
    form.appendChild(q.wrap);
    form.appendChild(fmt.wrap);
    form.appendChild(when.wrap);

    var btn = el('button', 'mf-sb__go');
    btn.type = 'submit';
    btn.setAttribute('aria-label', 'Submit search');
    btn.textContent = '⌕';   // ⌕ search-shape glyph
    form.appendChild(btn);

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var payload = {
        q: q.input.value.trim(),
        format: fmt.input.value.trim() || null,
        when: when.input.value.trim() || null,
      };
      try { onSubmit(payload); } catch (e) { console.error(e); }
    });

    slot.appendChild(form);

    return {
      focus: function () { q.input.focus(); },
      clear: function () { q.input.value = ''; fmt.input.value = ''; when.input.value = ''; },
    };
  }

  global.MFSearchBar = { mount: mount };
})(window);
```

- [x] **Step 2: Append CSS to components.css**

```css
/* === hero search bar === */
.mf-sb {
  display: flex;
  align-items: center;
  max-width: 760px;
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-pill);
  box-shadow: 0 4px 14px -6px rgba(0,0,0,0.08);
  padding: 0.4rem;
  font-family: var(--mf-font-sans);
  transition: box-shadow var(--mf-transition-med);
}
.mf-sb:hover {
  box-shadow: 0 8px 28px -10px rgba(0,0,0,0.12);
}
.mf-sb__seg {
  padding: 0.55rem 1.2rem;
  flex: 1;
  min-width: 0;
  border-right: 1px solid var(--mf-border-soft);
  display: flex;
  flex-direction: column;
}
.mf-sb__seg:last-of-type { border-right: none; }
.mf-sb__label {
  font-size: 0.66rem;
  font-weight: 700;
  color: var(--mf-color-text);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 0.1rem;
}
.mf-sb__input {
  border: none;
  background: transparent;
  font-size: 0.88rem;
  color: var(--mf-color-text);
  font-family: inherit;
  padding: 0;
  outline: none;
  width: 100%;
}
.mf-sb__input::placeholder { color: var(--mf-color-text-faint); }
.mf-sb__go {
  width: 38px; height: 38px;
  border-radius: 50%;
  background: var(--mf-color-accent);
  color: #fff;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.95rem;
  flex-shrink: 0;
  cursor: pointer;
}
```

- [x] **Step 3: Commit**

```bash
git add static/js/components/search-bar.js static/css/components.css
git commit -m "feat(ux): hero search bar — Airbnb-style segmented input

760px max-width with three fields (Looking for / Format / When) +
circular submit button. Form-based submit fires onSubmit({q, format,
when}) with trimmed values. Safe DOM throughout."
```

---

## Task 2: Browse-row component

**Files:**
- Create: `static/js/components/browse-row.js`

Generic horizontal-scroll row used by Maximal and Recent layouts. Structure: title (link to expanded view) + count + arrow controls + grid of items (cards or folder cards or tag pills).

- [x] **Step 1: Create the component**

Create `static/js/components/browse-row.js`:

```javascript
/* Generic browse-row. Title + count + L/R arrows + content slot.
 * Spec §3 (Maximal mode rows).
 *
 * Usage:
 *   MFBrowseRow.mount(slot, {
 *     title: 'Pinned folders',
 *     count: 14,
 *     countSuffix: 'pinned',
 *     onSeeAll: function() { ... },   // fires on title click + arrow icon
 *     content: domNode,               // pre-built children (any layout)
 *   });
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFBrowseRow.mount: slot is required');
    var title = (opts && opts.title) || '';
    var count = (opts && typeof opts.count === 'number') ? opts.count : null;
    var countSuffix = (opts && opts.countSuffix) || '';
    var content = (opts && opts.content) || null;
    var onSeeAll = (opts && opts.onSeeAll) || null;

    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var row = el('div', 'mf-row');
    var head = el('div', 'mf-row__head');

    var titleLink = el('a', 'mf-row__title-link');
    titleLink.href = '#';
    if (onSeeAll) {
      titleLink.addEventListener('click', function (ev) {
        ev.preventDefault();
        onSeeAll();
      });
    }
    var h3 = el('h3', 'mf-row__title');
    h3.textContent = title;
    titleLink.appendChild(h3);
    var arrow = el('span', 'mf-row__arrow');
    arrow.textContent = '→';   // →
    titleLink.appendChild(arrow);
    head.appendChild(titleLink);

    var controls = el('div', 'mf-row__controls');
    if (count !== null) {
      var c = el('span', 'mf-row__count');
      c.textContent = count.toLocaleString() + (countSuffix ? ' ' + countSuffix : '');
      controls.appendChild(c);
    }
    var leftBtn = el('button', 'mf-row__nav-btn');
    leftBtn.type = 'button'; leftBtn.setAttribute('aria-label', 'Scroll left');
    leftBtn.textContent = '←'; // ←
    var rightBtn = el('button', 'mf-row__nav-btn');
    rightBtn.type = 'button'; rightBtn.setAttribute('aria-label', 'Scroll right');
    rightBtn.textContent = '→'; // →
    controls.appendChild(leftBtn);
    controls.appendChild(rightBtn);
    head.appendChild(controls);

    row.appendChild(head);

    var body = el('div', 'mf-row__body');
    if (content) body.appendChild(content);
    row.appendChild(body);

    leftBtn.addEventListener('click', function () { body.scrollBy({ left: -400, behavior: 'smooth' }); });
    rightBtn.addEventListener('click', function () { body.scrollBy({ left: 400, behavior: 'smooth' }); });

    slot.appendChild(row);
  }

  global.MFBrowseRow = { mount: mount };
})(window);
```

- [x] **Step 2: Append CSS to components.css**

```css
/* === browse row === */
.mf-row { margin-top: 1.7rem; font-family: var(--mf-font-sans); }
.mf-row__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 0.85rem;
}
.mf-row__title-link {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  cursor: pointer;
  text-decoration: none;
  color: inherit;
}
.mf-row__title {
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.018em;
  color: var(--mf-color-text);
  margin: 0;
}
.mf-row__arrow {
  width: 22px; height: 22px;
  border-radius: 50%;
  background: #f3f3f3;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--mf-color-text-muted);
  font-size: 0.72rem;
  transition: background var(--mf-transition-fast), color var(--mf-transition-fast);
}
.mf-row__title-link:hover .mf-row__arrow {
  background: var(--mf-color-accent);
  color: #fff;
}
.mf-row__controls { display: flex; gap: 0.4rem; align-items: center; }
.mf-row__count {
  font-size: 0.78rem;
  color: var(--mf-color-text-faint);
  margin-right: 0.4rem;
}
.mf-row__nav-btn {
  width: 30px; height: 30px;
  border-radius: 50%;
  background: var(--mf-surface);
  border: 1px solid #e0e0e0;
  cursor: pointer;
  color: var(--mf-color-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
}
.mf-row__nav-btn:hover { background: var(--mf-surface-soft); }
.mf-row__body {
  /* Default: regular grid; consumers can override on body. */
  overflow-x: auto;
  scroll-behavior: smooth;
}
```

- [x] **Step 3: Commit**

```bash
git add static/js/components/browse-row.js static/css/components.css
git commit -m "feat(ux): browse-row component — title + count + arrows + slot

Generic horizontal-scroll row used by Search-home Maximal mode and
Recent mode. Title click and arrow icon both fire onSeeAll. L/R nav
buttons scroll the body slot by 400px. Content slot accepts any
pre-built DOM (cards / folder cards / tag pills). Safe DOM."
```

---

## Task 3: Topic cloud component (pill cloud for "Browse by topic")

**Files:**
- Create: `static/js/components/topic-cloud.js`

Flex-wrap of pill-shaped tags with name + count. Used in Maximal mode bottom row.

- [x] **Step 1: Create the component**

Create `static/js/components/topic-cloud.js`:

```javascript
/* Topic cloud — pill cloud of topics with counts.
 * Spec §3 (Maximal mode "Browse by topic" row).
 *
 * Usage:
 *   var node = MFTopicCloud.build([
 *     { name: 'Contracts', count: 428 },
 *     ...
 *   ], onClick);
 *
 * Returns a DOM node ready to drop into MFBrowseRow content slot.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function build(topics, onClick) {
    var wrap = el('div', 'mf-topic-cloud');
    (topics || []).forEach(function (t) {
      var pill = el('a', 'mf-topic-cloud__pill');
      pill.href = '#';
      pill.setAttribute('data-topic', t.name);
      var name = el('span'); name.textContent = t.name;
      pill.appendChild(name);
      if (typeof t.count === 'number') {
        var c = el('span', 'mf-topic-cloud__count');
        c.textContent = ' ' + t.count.toLocaleString();
        pill.appendChild(c);
      }
      pill.addEventListener('click', function (ev) {
        ev.preventDefault();
        if (typeof onClick === 'function') onClick(t);
      });
      wrap.appendChild(pill);
    });
    return wrap;
  }

  global.MFTopicCloud = { build: build };
})(window);
```

- [x] **Step 2: Append CSS to components.css**

```css
/* === topic cloud === */
.mf-topic-cloud {
  display: flex;
  gap: 0.55rem;
  flex-wrap: wrap;
  font-family: var(--mf-font-sans);
}
.mf-topic-cloud__pill {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-pill);
  padding: 0.45rem 0.95rem;
  font-size: 0.84rem;
  color: var(--mf-color-text-soft);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  text-decoration: none;
  transition: border-color var(--mf-transition-fast), color var(--mf-transition-fast);
}
.mf-topic-cloud__pill:hover {
  border-color: var(--mf-color-accent-border);
  color: var(--mf-color-accent);
}
.mf-topic-cloud__count {
  color: var(--mf-color-text-faint);
  font-size: 0.76rem;
}
```

- [x] **Step 3: Commit**

```bash
git add static/js/components/topic-cloud.js static/css/components.css
git commit -m "feat(ux): topic cloud — pill cloud of topics with counts

build(topics, onClick) returns a DOM node consumable by MFBrowseRow.
Each pill carries data-topic attribute for downstream filtering. Safe
DOM throughout."
```

---

## Task 4: Sample browse-row data (mock for v1)

**Files:**
- Create: `static/js/sample-rows.js`

Mock data for Maximal-mode browse rows. Plan 4 replaces this with real `/api/folders/pinned`, `/api/files/recently-opened`, etc.

- [x] **Step 1: Create the fixture**

Create `static/js/sample-rows.js`:

```javascript
/* Sample browse-row data for the v1 Search-home page.
 * Plan 4 will replace these with live API calls. */
(function (global) {
  'use strict';

  global.MFSampleRows = {
    pinnedFolders: [
      { id: 'p1', path: '/local-46/contracts',     count: 428,   meta: '3 added today' },
      { id: 'p2', path: '/training/curriculum',    count: 1206,  meta: 'updated 2 days ago' },
      { id: 'p3', path: '/finance/2025',           count: 847,   meta: 'updated this week' },
      { id: 'p4', path: '/governance/bylaws',      count: 62,    meta: 'revision in progress' },
    ],

    fromWatchedFolders: window.MFSampleDocs ? window.MFSampleDocs.slice(0, 6) : [],

    mostAccessedThisWeek: window.MFSampleDocs ? window.MFSampleDocs.slice(0, 6).map(function (d, i) {
      return Object.assign({}, d, { opens: 42 - i * 4 });
    }) : [],

    flaggedForReview: window.MFSampleDocs ? window.MFSampleDocs.slice(0, 3).map(function (d) {
      return Object.assign({}, d, {
        snippet: 'AI flagged: ' + (d.snippet || '').slice(0, 80),
      });
    }) : [],

    topics: [
      { name: 'Contracts',           count: 428 },
      { name: 'Safety bulletins',    count: 312 },
      { name: 'Training materials',  count: 1206 },
      { name: 'Financial reports',   count: 847 },
      { name: 'Correspondence',      count: 2140 },
      { name: 'Bylaws & governance', count: 62 },
      { name: 'Member records',      count: 4820 },
      { name: 'Apprentice',          count: 1890 },
      { name: 'Pension & benefits',  count: 340 },
      { name: 'Jurisdiction',        count: 156 },
    ],

    recentSearches: [
      'arc-flash PPE requirements',
      'jurisdiction Local 76',
      'apprentice OJT shortfall',
      'master agreement section 12',
      'healthcare contribution cap',
      'steward training grievance',
      'pension allocation 2026',
      'bylaws delegate selection',
    ],
  };
})(window);
```

- [x] **Step 2: Commit**

```bash
git add static/js/sample-rows.js
git commit -m "test(ux): sample browse-row data for Plan 3 v1

Pinned folders, From watched (reuses MFSampleDocs), Most accessed
(annotated with opens count), Flagged for review (annotated with
'AI flagged:'), topics with counts, recent searches. Plan 4 wires
live /api/* endpoints; this fixture lives until then."
```

---

## Task 5: Search-home page mount (the orchestrator)

**Files:**
- Create: `static/js/pages/search-home.js`

The top-level page renderer. Reads `MFPrefs.layout`, swaps DOM accordingly. On layout change (via popover or `⌘\`), re-renders. Routes search submit to `/search?q=...`.

- [x] **Step 1: Create the page module**

Create `static/js/pages/search-home.js`:

```javascript
/* Search-as-home page mount. Spec §3 (three layout modes).
 *
 * Usage:
 *   MFSearchHome.mount(document.getElementById('mf-home'), {
 *     systemStatus: 'All systems running · 12,847 indexed',
 *   });
 *
 * Reads MFPrefs.layout for which mode to render. Subscribes to layout
 * changes for re-render. Search submit navigates to /search.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildPulse(text) {
    var p = el('div', 'mf-pulse');
    var dot = el('span', 'mf-pulse__dot');
    p.appendChild(dot);
    p.appendChild(document.createTextNode(' ' + text));
    return p;
  }

  function buildHeadline(text, sub, opts) {
    var head = el('h1', 'mf-home__headline' + (opts && opts.huge ? ' mf-home__headline--huge' : ''));
    text.split('\n').forEach(function (line, i) {
      if (i > 0) head.appendChild(document.createElement('br'));
      head.appendChild(document.createTextNode(line));
    });
    var subEl = sub ? el('p', 'mf-home__subtitle') : null;
    if (subEl) subEl.textContent = sub;
    return { headline: head, subtitle: subEl };
  }

  function buildSearchBar(onSubmit) {
    var wrap = el('div', 'mf-home__search-wrap');
    MFSearchBar.mount(wrap, { onSubmit: onSubmit });
    return wrap;
  }

  function navigateToSearch(payload) {
    var qs = new URLSearchParams();
    if (payload.q) qs.set('q', payload.q);
    if (payload.format) qs.set('format', payload.format);
    if (payload.when) qs.set('when', payload.when);
    window.location.href = '/static/search.html' + (qs.toString() ? '?' + qs : '');
  }

  // === Layout renderers ===

  function renderMaximal(slot, ctx) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-home__body');
    body.appendChild(buildPulse(ctx.systemStatus));
    var heading = buildHeadline("Find anything you've ever\nconverted.");
    body.appendChild(heading.headline);
    body.appendChild(buildSearchBar(navigateToSearch));

    // Browse rows
    var rows = el('div', 'mf-home__rows');
    body.appendChild(rows);
    addPinnedFoldersRow(rows);
    addCardRow(rows, 'From watched folders', MFSampleRows.fromWatchedFolders, '87 ingested today');
    addCardRow(rows, 'Most accessed this week', MFSampleRows.mostAccessedThisWeek, 'top ' + MFSampleRows.mostAccessedThisWeek.length);
    addCardRow(rows, 'Flagged for review', MFSampleRows.flaggedForReview, MFSampleRows.flaggedForReview.length + ' need review');
    addTopicsRow(rows);

    slot.appendChild(body);
  }

  function renderRecent(slot, ctx) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-home__body');
    body.appendChild(buildPulse(ctx.systemStatus));
    var heading = buildHeadline("Find anything you've ever\nconverted.");
    body.appendChild(heading.headline);
    body.appendChild(buildSearchBar(navigateToSearch));

    // Recent searches chip row
    var rs = MFPrefs.get('recent_searches') || MFSampleRows.recentSearches || [];
    if (rs.length) {
      var chipRow = el('div', 'mf-home__rows');
      var chipSlot = el('div');
      MFBrowseRow.mount(chipSlot, {
        title: 'Recent searches',
        content: buildRecentChips(rs),
      });
      chipRow.appendChild(chipSlot);
      body.appendChild(chipRow);
    }

    // Recently opened (cards)
    var rows = el('div', 'mf-home__rows');
    body.appendChild(rows);
    addCardRow(rows, 'Recently opened', MFSampleDocs ? MFSampleDocs.slice(0, 6) : [], null);

    slot.appendChild(body);
  }

  function renderMinimal(slot, ctx) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-home__body mf-home__body--minimal');
    body.appendChild(buildPulse(ctx.systemStatus));
    var heading = buildHeadline('MarkFlow.', "Find anything you've ever converted.", { huge: true });
    body.appendChild(heading.headline);
    if (heading.subtitle) body.appendChild(heading.subtitle);
    body.appendChild(buildSearchBar(navigateToSearch));
    slot.appendChild(body);
  }

  function buildRecentChips(queries) {
    var wrap = el('div', 'mf-recent-chips');
    queries.forEach(function (q) {
      var chip = el('a', 'mf-recent-chip');
      chip.href = '/static/search.html?q=' + encodeURIComponent(q);
      var icon = el('span', 'mf-recent-chip__icon');
      icon.textContent = '⚲';   // search-glyph-ish dingbat
      chip.appendChild(icon);
      var t = el('span'); t.textContent = q;
      chip.appendChild(t);
      var x = el('span', 'mf-recent-chip__x');
      x.textContent = '×';   // ×
      x.setAttribute('aria-label', 'Remove from recent');
      x.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var rs = (MFPrefs.get('recent_searches') || []).filter(function (s) { return s !== q; });
        MFPrefs.set('recent_searches', rs);
      });
      chip.appendChild(x);
      wrap.appendChild(chip);
    });
    return wrap;
  }

  function addPinnedFoldersRow(rows) {
    var slot = el('div');
    var grid = el('div', 'mf-folder-cards');
    (MFSampleRows.pinnedFolders || []).forEach(function (f) {
      var card = el('a', 'mf-folder-card');
      card.href = '/folder' + f.path;
      var icon = el('div', 'mf-folder-card__icon');
      icon.textContent = '⧇';   // folder-ish dingbat
      var name = el('h4', 'mf-folder-card__name');
      name.textContent = f.path;
      var meta = el('div', 'mf-folder-card__meta');
      meta.textContent = f.count.toLocaleString() + ' docs · ' + f.meta;
      card.appendChild(icon);
      card.appendChild(name);
      card.appendChild(meta);
      grid.appendChild(card);
    });
    MFBrowseRow.mount(slot, {
      title: 'Pinned folders',
      count: (MFSampleRows.pinnedFolders || []).length,
      countSuffix: 'pinned',
      content: grid,
      onSeeAll: function () { console.log('see all pinned folders'); },
    });
    rows.appendChild(slot);
  }

  function addCardRow(rows, title, docs, countText) {
    var slot = el('div');
    var grid = el('div');
    grid.className = 'mf-card-grid mf-card-grid--cards';
    docs.forEach(function (d) { grid.appendChild(MFDocCard.create(d)); });
    MFBrowseRow.mount(slot, {
      title: title,
      count: countText ? null : docs.length,
      content: grid,
      onSeeAll: function () { console.log('see all:', title); },
    });
    if (countText) {
      var c = slot.querySelector('.mf-row__controls');
      if (c) {
        var span = el('span', 'mf-row__count');
        span.textContent = countText;
        c.insertBefore(span, c.firstChild);
      }
    }
    rows.appendChild(slot);
  }

  function addTopicsRow(rows) {
    var slot = el('div');
    var cloud = MFTopicCloud.build(MFSampleRows.topics, function (t) {
      window.location.href = '/static/search.html?topic=' + encodeURIComponent(t.name);
    });
    MFBrowseRow.mount(slot, {
      title: 'Browse by topic',
      content: cloud,
      onSeeAll: function () { console.log('see all topics'); },
    });
    rows.appendChild(slot);
  }

  // === Top-level mount ===

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSearchHome.mount: slot is required');
    var ctx = {
      systemStatus: (opts && opts.systemStatus) || 'All systems running',
    };

    function render() {
      var mode = MFPrefs.get('layout') || 'minimal';
      if (mode === 'maximal') renderMaximal(slot, ctx);
      else if (mode === 'recent') renderRecent(slot, ctx);
      else renderMinimal(slot, ctx);
    }

    render();
    var unsub = MFPrefs.subscribe('layout', render);
    return function unmount() {
      unsub();
      while (slot.firstChild) slot.removeChild(slot.firstChild);
    };
  }

  global.MFSearchHome = { mount: mount };
})(window);
```

- [x] **Step 2: Append CSS to components.css**

```css
/* === search home (layouts + supporting bits) === */
.mf-home__body { padding: 2.2rem var(--mf-page-pad-x) 2.5rem; max-width: var(--mf-content-max); margin: 0 auto; }
.mf-home__body--minimal {
  padding: 7rem var(--mf-page-pad-x) 9rem;
  text-align: center;
}
.mf-home__body--minimal .mf-pulse { margin: 0 0 2rem; }
.mf-home__body--minimal .mf-sb { margin: 0 auto; max-width: 880px; }

.mf-home__headline {
  font-family: var(--mf-font-sans);
  font-size: 2.4rem;
  line-height: var(--mf-leading-tight);
  letter-spacing: var(--mf-tracking-tight);
  font-weight: 700;
  color: var(--mf-color-text);
  margin: 0.4rem 0 1.4rem;
}
.mf-home__headline--huge {
  font-size: 3.4rem;
  margin: 0 0 0.5rem;
}
.mf-home__subtitle {
  color: var(--mf-color-text-muted);
  font-size: 1.1rem;
  margin: 0 auto 2.5rem;
  max-width: 42ch;
  font-family: var(--mf-font-sans);
}
.mf-home__rows { margin-top: 2.6rem; }

/* recent chips */
.mf-recent-chips {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.mf-recent-chip {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-pill);
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  color: var(--mf-color-text-soft);
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  text-decoration: none;
  font-family: var(--mf-font-sans);
}
.mf-recent-chip:hover { border-color: var(--mf-color-accent-border); color: var(--mf-color-accent); }
.mf-recent-chip__icon { color: var(--mf-color-text-fainter); font-size: 0.78rem; }
.mf-recent-chip__x {
  color: var(--mf-color-text-fainter);
  font-size: 0.72rem;
  padding-left: 0.3rem;
  border-left: 1px solid var(--mf-border-soft);
  margin-left: 0.2rem;
  cursor: pointer;
}
.mf-recent-chip__x:hover { color: var(--mf-color-error); }

/* pinned folder cards (re-used outside folder-browse) */
.mf-folder-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.9rem;
}
.mf-folder-card {
  background: var(--mf-surface-soft);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card);
  padding: 1rem 1.1rem;
  cursor: pointer;
  text-decoration: none;
  color: inherit;
  font-family: var(--mf-font-sans);
}
.mf-folder-card:hover { border-color: var(--mf-color-accent-border); transform: translateY(-1px); }
.mf-folder-card__icon {
  width: 34px; height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--mf-color-accent-tint), var(--mf-color-accent-border));
  display: flex; align-items: center; justify-content: center;
  color: var(--mf-color-accent);
  font-size: 0.95rem;
  margin-bottom: 0.7rem;
}
.mf-folder-card__name {
  font-size: 0.92rem;
  font-weight: 600;
  color: var(--mf-color-text);
  margin: 0 0 0.15rem;
}
.mf-folder-card__meta { font-size: 0.76rem; color: var(--mf-color-text-faint); }
```

- [x] **Step 3: Commit**

```bash
git add static/js/pages/search-home.js static/css/components.css
git commit -m "feat(ux): search-home page mount (3 layouts: Maximal/Recent/Minimal)

Reads MFPrefs.layout, swaps DOM accordingly. Subscribes to layout
changes (re-renders on Cmd+\\ cycle or popover choice). Submit routes
to /static/search.html?q=... preserving v1 search-results UI per spec.

- Maximal: pulse + headline + search bar + 5 browse rows (Pinned folders /
  From watched / Most accessed / Flagged / Topics)
- Recent: pulse + headline + search bar + Recent searches chip row +
  Recently opened cards. Reads MFPrefs.recent_searches (Plan 1A's
  preferences), x-click removes from history.
- Minimal: pulse + brand headline + centered search bar only.

Browse rows use MFBrowseRow + MFCardGrid + MFDocCard from earlier plans.
Folder cards built inline (the format/snippet is doc-specific; folders
are a different shape). Topics use MFTopicCloud.

Sample data from sample-rows.js. Plan 4 wires live API endpoints."
```

---

## Task 6: Replace `static/index.html` behind feature flag

**Files:**
- Create: `static/index-new.html` — the new home page template
- Modify: `main.py` — flag-aware index route
- Create: `tests/test_search_home_flag.py`

- [x] **Step 1: Create the new home page template**

Create `static/index-new.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MarkFlow — Search</title>
  <link rel="stylesheet" href="/static/css/components.css">
  <style>
    body { margin: 0; background: #f7f7f9; font-family: -apple-system, "SF Pro Display", Inter, system-ui, sans-serif; min-height: 100vh; }
  </style>
</head>
<body data-env="dev">
  <div id="mf-top-nav"></div>
  <div id="mf-home"></div>

  <script src="/static/js/preferences.js"></script>
  <script src="/static/js/telemetry.js"></script>
  <script src="/static/js/keybinds.js"></script>
  <script src="/static/js/components/top-nav.js"></script>
  <script src="/static/js/components/version-chip.js"></script>
  <script src="/static/js/components/avatar.js"></script>
  <script src="/static/js/components/avatar-menu.js"></script>
  <script src="/static/js/components/layout-icon.js"></script>
  <script src="/static/js/components/layout-popover.js"></script>
  <script src="/static/js/components/doc-card.js"></script>
  <script src="/static/js/components/card-grid.js"></script>
  <script src="/static/js/components/density-toggle.js"></script>
  <script src="/static/js/components/hover-preview.js"></script>
  <script src="/static/js/components/context-menu.js"></script>
  <script src="/static/js/components/card-selection.js"></script>
  <script src="/static/js/components/bulk-bar.js"></script>
  <script src="/static/js/components/folder-browse.js"></script>
  <script src="/static/js/components/search-bar.js"></script>
  <script src="/static/js/components/browse-row.js"></script>
  <script src="/static/js/components/topic-cloud.js"></script>
  <script src="/static/js/sample-docs.js"></script>
  <script src="/static/js/sample-rows.js"></script>
  <script src="/static/js/pages/search-home.js"></script>
  <script src="/static/js/index-new-boot.js"></script>
</body>
</html>
```

- [x] **Step 2: Create the boot script**

Create `static/js/index-new-boot.js`:

```javascript
/* Boot script for the new Search-as-home page (Plan 3).
 * Mounts top-nav + companions, then mounts MFSearchHome.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var homeRoot = document.getElementById('mf-home');

  // TODO Plan 4: pull real role from /api/me. For now default to 'admin'
  // so Activity link is visible during development.
  var role = 'admin';
  var build = { version: 'v0.34.5-dev', branch: 'main', sha: 'unknown', date: 'today' };
  var user = { name: 'Operator', role: role, scope: '' };

  var avatarMenu = MFAvatarMenu.create({
    user: user,
    build: build,
    onSelectItem: function (id) { console.log('avatar item:', id); },
    onSignOut: function () { console.log('sign out'); },
  });

  var layoutPop = MFLayoutPopover.create({
    current: MFPrefs.get('layout') || 'minimal',
    onChoose: function (mode) {
      MFPrefs.set('layout', mode);
      MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
    },
  });

  function mountChrome() {
    MFTopNav.mount(navRoot, { role: role, activePage: 'search' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: build.version }
    );
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, onClick: function (btn) { avatarMenu.openAt(btn); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );
  }

  // Cmd+\ cycles layouts
  var MODES = ['maximal', 'recent', 'minimal'];
  MFKeybinds.on('mod+\\', function () {
    var current = MFPrefs.get('layout') || 'minimal';
    var next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
    MFPrefs.set('layout', next);
    layoutPop.setCurrent(next);
    MFTelemetry.emit('ui.layout_mode_selected', { mode: next, source: 'kbd' });
    return true;
  });

  // Wire hover + context menu + selection (the doc-card interaction
  // event listeners are global at body level, just like dev-chrome).
  var hp = MFHoverPreview.create({
    onAction: function (action, doc) { console.log('hover:', action, doc.id); },
  });
  var cm = MFContextMenu.create({
    onAction: function (action, doc) { console.log('ctx:', action, doc.id); },
  });
  document.addEventListener('mf:doc-contextmenu', function (ev) {
    cm.openAt(ev.detail.x, ev.detail.y, ev.detail.doc);
  });

  // Hydrate prefs, then render
  MFPrefs.load().then(function () {
    mountChrome();
    MFSearchHome.mount(homeRoot, {
      systemStatus: 'All systems running · 12,847 indexed',
    });
    // Re-arm hover-preview after each render
    function rearm() {
      var cards = homeRoot.querySelectorAll('.mf-doc-card');
      cards.forEach(function (card) {
        var docId = card.getAttribute('data-doc-id');
        var doc = (window.MFSampleDocs || []).find(function (d) { return d.id === docId; });
        if (doc) hp.armOn(card, doc);
      });
    }
    rearm();
    MFPrefs.subscribe('layout', function () {
      requestAnimationFrame(rearm);
    });
  });
})();
```

- [x] **Step 3: Add the flag-aware route to `main.py`**

Find the existing `/` route in `main.py` (likely a `FileResponse('static/index.html')`-style handler). Modify to check the flag:

```python
from fastapi.responses import FileResponse
from core.feature_flags import is_new_ux_enabled


@app.get("/", include_in_schema=False)
async def root_index():
    """Serve the home page. New UX rendered when ENABLE_NEW_UX=true."""
    if is_new_ux_enabled():
        return FileResponse("static/index-new.html")
    return FileResponse("static/index.html")
```

If the existing route already does something more elaborate (auth check, role lookup), preserve that and only swap the file path.

- [x] **Step 4: Write the test**

Create `tests/test_search_home_flag.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_root_serves_legacy_index_when_flag_off(monkeypatch, client):
    monkeypatch.setenv("ENABLE_NEW_UX", "false")
    r = client.get("/")
    assert r.status_code == 200
    # Legacy index.html has the Convert page heading
    assert b"Convert Documents" in r.content or b"Document Conversion" in r.content


def test_root_serves_new_index_when_flag_on(monkeypatch, client):
    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    r = client.get("/")
    assert r.status_code == 200
    # New index.html mounts mf-home div and loads search-home page module
    assert b'id="mf-home"' in r.content
    assert b"search-home.js" in r.content


def test_root_default_serves_legacy(monkeypatch, client):
    """No env var set → legacy UI is served (production-safe default)."""
    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    r = client.get("/")
    assert r.status_code == 200
    assert b'id="mf-home"' not in r.content
```

- [x] **Step 5: Run tests**

```bash
pytest tests/test_search_home_flag.py -v
```

Expected: 3 PASS.

- [x] **Step 6: Commit**

```bash
git add static/index-new.html static/js/index-new-boot.js main.py tests/test_search_home_flag.py
git commit -m "feat(ux): flag-aware index route + new Search-home template

main.py / route serves static/index-new.html when ENABLE_NEW_UX=true,
falls back to legacy static/index.html otherwise. Production-safe
default (flag off → legacy preserved).

index-new.html loads every component from Plans 1A through 3 and
boots via static/js/index-new-boot.js. Boot script: mounts chrome,
arms keybind cycle, wires hover + context menu, hydrates MFPrefs,
mounts MFSearchHome.

3 tests for the routing fork. role=admin hardcoded in boot for now;
Plan 4 wires the real /api/me role lookup."
```

---

## Task 7: Wire dev-chrome demo for layout-mode preview

**Files:**
- Modify: `static/dev-chrome.html` — load new scripts (most are already loaded from earlier plans)
- Modify: `static/dev-chrome.js` — add a Search-home preview section

- [x] **Step 1: Update dev-chrome.html script tags**

Add these before `dev-chrome.js`:

```html
  <script src="/static/js/components/search-bar.js"></script>
  <script src="/static/js/components/browse-row.js"></script>
  <script src="/static/js/components/topic-cloud.js"></script>
  <script src="/static/js/sample-rows.js"></script>
  <script src="/static/js/pages/search-home.js"></script>
```

Append a Search-home demo section after the folder-browse demo:

```html
  <div class="dev-banner">
    <h2 style="font-size: 1.05rem; margin: 1.4rem 0 0.4rem; color: #0a0a0a">Search-home page demo</h2>
    <p style="color: #888; font-size: 0.84rem; margin-bottom: 1rem">Cmd+\\ cycles layout modes. Layout-icon in nav also opens chooser. Currently using sample data — Plan 4 wires real /api endpoints.</p>
    <div id="mf-search-home-demo" style="background: #fff; border: 1px solid #ececec; border-radius: 14px;"></div>
  </div>
```

- [x] **Step 2: Append to dev-chrome.js**

Append (inside the existing IIFE, before `})();`):

```javascript
  // === Search-home demo ===
  var shSlot = document.getElementById('mf-search-home-demo');
  MFSearchHome.mount(shSlot, {
    systemStatus: 'All systems running · 12,847 indexed (sample)',
  });
```

- [x] **Step 3: Smoke verify**

```bash
docker-compose up -d
```

Visit `http://localhost:8000/static/dev-chrome.html`. Expected:

1. All previous demos still work (chrome, card grid, folder browse).
2. New "Search-home page demo" section at the bottom.
3. Default mode = whatever `MFPrefs.get('layout')` returns (Minimal if first visit).
4. Press `⌘\` (or Ctrl+\\ on Linux/Windows) → cycles Maximal → Recent → Minimal → Maximal.
5. **Maximal mode:** pulse + headline + search bar + 5 browse rows (Pinned folders → From watched → Most accessed → Flagged for review → Browse by topic).
6. **Recent mode:** pulse + headline + search bar + Recent searches chips + Recently opened cards.
7. **Minimal mode:** centered "MarkFlow." brand headline + subtitle + centered search bar.
8. Hover any card → preview popover (from Plan 2B).
9. Right-click any card → context menu (from Plan 2B).
10. Click a recent-search chip's `×` → it disappears from the list.

Then test the live page:

```bash
ENABLE_NEW_UX=true docker-compose up -d --force-recreate markflow
```

Visit `http://localhost:8000/`. Expected: same Search-home page (not the legacy Convert page).

Then:

```bash
ENABLE_NEW_UX=false docker-compose up -d --force-recreate markflow
```

Visit `http://localhost:8000/`. Expected: legacy Convert page back (production-safe default).

- [x] **Step 4: Commit**

```bash
git add static/dev-chrome.html static/dev-chrome.js
git commit -m "feat(ux): dev-chrome adds Search-home demo (Plan 3 integration)

Search-home demo section at bottom of dev-chrome.html exercises all
three layout modes via Cmd+\\ cycling. Hover and right-click work end
to end (inherits Plan 2B's listeners on document). End-to-end test
target before flipping ENABLE_NEW_UX in production."
```

---

## Acceptance check (run before declaring this plan complete)

- [x] `pytest tests/test_search_home_flag.py -v` — 3 PASS
- [x] `grep -rn "innerHTML" static/js/components/search-bar.js static/js/components/browse-row.js static/js/components/topic-cloud.js static/js/pages/search-home.js static/js/index-new-boot.js` — zero matches
- [x] `docker-compose up -d` succeeds, no console errors
- [x] All 10 smoke checks from Task 7 Step 3 pass
- [x] `ENABLE_NEW_UX=true` flag flip serves the new page at `/`
- [x] `ENABLE_NEW_UX=false` flag flip serves the legacy page at `/`
- [x] Layout preference round-trips (set Minimal, reload, still Minimal)
- [x] `git log --oneline | head -10` shows ~7 task commits in order

Once all green, **Plan 3 is done**. Next plan: `2026-04-28-ux-overhaul-ia-shift.md` (Plan 4 — IA shift: Activity rename, role-gated nav, real /api/me, real /api/folders, real recently-opened, removes dev-chrome scaffold once components have a real home).

---

## Self-review

**Spec coverage:**
- §3 (three layout modes — Maximal/Recent/Minimal): ✓ Task 5
- §3 (hero search bar): ✓ Task 1
- §3 (browse rows): ✓ Tasks 2, 4, 5
- §3 (recent searches chip with X-to-remove + persistence): ✓ Task 5
- §3 (`⌘\` cycle + nav layout-icon both work): ✓ Tasks 5+6 + Plan 1C reuse
- §10 (preferences persistence — layout, recent_searches): ✓ Task 5
- §13 (telemetry: `ui.layout_mode_selected` already in Plan 1C; `ui.search_submitted` deferred — search bar logs would happen server-side in /api/search)

**Spec gaps for this plan (deferred to later plans):**
- §1 (Activity rename, role-gated nav driven by real /api/me): Plan 4
- §4 (real /api endpoints for browse rows): Plan 4
- §5 (Activity dashboard): Plan 4
- §7 (Settings detail pages): Plans 5–7
- §8 (cost cap drill-down): Plan 7

**Placeholder scan:**
- Boot script's `role = 'admin'` is a hardcoded placeholder — explicitly TODO-noted with Plan 4 cross-reference. This is intentional for v1 and called out in commit message.
- Build info in boot is `'unknown'` placeholder — Plan 4 will inject real values via the build pipeline.

**Type / API consistency:**
- `MFSearchBar.mount(slot, opts)` consistent with other mount-pattern components
- `MFBrowseRow.mount(slot, opts)` ditto
- `MFTopicCloud.build(items, onClick)` returns DOM (not a mount — different shape because consumed by MFBrowseRow.content)
- `MFSearchHome.mount(slot, opts)` returns unmount function (consistent with Plan 2B's MFFolderBrowse.mount)

**Safe-DOM verification (mandatory final scan):**

```
grep -rn "innerHTML" static/js/components/search-bar.js \
  static/js/components/browse-row.js \
  static/js/components/topic-cloud.js \
  static/js/pages/search-home.js \
  static/js/index-new-boot.js
```

Expected: empty.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-search-as-home.md`.

Sized for: 7 implementer dispatches + 7 spec reviews + 7 code quality reviews ≈ 21 subagent calls.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
