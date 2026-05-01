# UX Overhaul — Document Card + Density Modes Implementation Plan (Plan 2A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Land the document card component (gradient top-band + paper snippet body), the linear list-row variant, the card-grid container that renders any density mode, and the density toggle UI that switches between **Cards** (6/row), **Compact** (8/row), and **List** (linear). Density persists via `MFPrefs` (Plan 1C). The dev-chrome page demonstrates all three densities switchable via the toggle, with a sample of 12 IBEW Local 46 documents.

**Architecture:** Pure DOM-level components with `MFDocCard` and `MFCardGrid` globals. **Safe DOM construction throughout** — every element via createElement, every text via textContent. Format-coded gradients consumed via `--mf-fmt-*` CSS vars (already in design-tokens.css from Plan 1A). Cards and Compact share the same card DOM with different container classes; List is a separate per-row DOM. Density toggle reads/writes `MFPrefs.get('density')`.

**Tech stack:** Vanilla HTML / CSS / JS

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §4 (document card anatomy + density modes), §10 (density persistence)

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/home-search-v3.html` (final card visuals at all three densities)

**Out of scope (deferred to Plan 2B):**
- Hover preview popover with full meta + AI summary
- Right-click context menu (with Advanced expander)
- Multi-select state on cards (checkboxes on hover)
- Bulk action bar
- Folder browse page (breadcrumb + folder header + bulk actions)

**Prerequisites:** Plans 1A + 1B + 1C must all be complete. Run `git log --oneline | head -20` and confirm: `f37e633` (Plan 1A), `50e552e` (Plan 1B), `3d5b1e9` (Plan 1C).

---

## Model + effort

| Role | Model | Effort |
|------|-------|--------|
| Implementer | Haiku | low (2-4h) |
| Reviewer | Sonnet | low (<1h) |

**Reasoning:** Presentational card component with three density modes driven by CSS variables and `MFPrefs`. Implementation is mechanical given the explicit mockups, but bumping reviewer to Sonnet because the density toggle interacts with the prefs system landed in 1C — worth verifying the binding is correct, not just the visuals. Review fits in a single short pass since the surface area is small.

**Execution mode:** Dispatch this plan via `superpowers:subagent-driven-development`. Each role is a separate `Agent` call — `Agent({model: "haiku", ...})` for implementation, `Agent({model: "sonnet", ...})` for review. A single-session `executing-plans` read will *not* switch models on its own; this metadata is routing input for the orchestrator.

**Source:** [`docs/spreadsheet/phase_model_plan.xlsx`](../../spreadsheet/phase_model_plan.xlsx)

---

## File structure (this plan creates / modifies)

**Create:**
- `static/js/components/doc-card.js` — `MFDocCard.create(doc)` for cards/compact, `MFDocCard.createListRow(doc)` for list
- `static/js/components/card-grid.js` — `MFCardGrid.mount(slot, docs, density)` orchestrator
- `static/js/components/density-toggle.js` — segmented control bound to `MFPrefs.density`
- `static/js/sample-docs.js` — fixture data for dev-chrome (12 IBEW Local 46 docs)

**Modify:**
- `static/css/components.css` — append doc-card, card-grid (per-density), density-toggle styles
- `static/dev-chrome.html` — add a `<div id="mf-card-demo">` section + load the new scripts
- `static/dev-chrome.js` — mount density toggle + grid; subscribe to density changes

---

## Task 1: Document card component (cards / compact densities)

**Files:**
- Create: `static/js/components/doc-card.js`

The card consumes a `doc` record with shape:

```javascript
{
  id: 'doc-id',                // stable identifier
  title: 'Q4 2025 Financial Summary',
  format: 'pdf',               // 'pdf' | 'docx' | 'pptx' | 'xlsx' | 'eml' | 'psd' | 'mp4' | 'md'
  snippet: 'Revenue increased 18% year over year...',
  path: '/finance/2025/q4/Q4-financials.pdf',
  size: 3355443,
  modified: '2026-04-28T14:08:00Z',
  favorite: false              // optional
}
```

- [x] **Step 1: Create the component**

Create `static/js/components/doc-card.js`:

```javascript
/* Document card. Gradient top-band + paper snippet body.
 * Used in Cards (6/row) and Compact (8/row) densities.
 * Spec §4.
 *
 * Usage:
 *   var cardEl = MFDocCard.create(doc);
 *   gridEl.appendChild(cardEl);
 *
 * For List density, use MFDocCard.createListRow(doc) which returns a
 * linear row element with a tiny format icon instead of a gradient band.
 *
 * Safe DOM throughout — no innerHTML.
 */
(function (global) {
  'use strict';

  var SUPPORTED_FORMATS = ['pdf', 'docx', 'pptx', 'xlsx', 'eml', 'psd', 'mp4', 'md'];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function safeFormat(fmt) {
    if (typeof fmt !== 'string') return 'md';
    var f = fmt.toLowerCase();
    return SUPPORTED_FORMATS.indexOf(f) >= 0 ? f : 'md';
  }

  // Build the card DOM (cards / compact density).
  function create(doc) {
    if (!doc) throw new Error('MFDocCard.create: doc record required');
    var fmt = safeFormat(doc.format);

    var card = el('div', 'mf-doc-card');
    card.setAttribute('data-doc-id', doc.id || '');
    card.setAttribute('data-doc-format', fmt);

    var thumb = el('div', 'mf-doc-card__thumb');

    // Gradient band with format label.
    var band = el('div', 'mf-doc-card__band mf-doc-card__band--' + fmt);
    var label = el('span', 'mf-doc-card__band-label');
    label.textContent = fmt.toUpperCase();
    band.appendChild(label);
    thumb.appendChild(band);

    // Heart icon (favorite indicator).
    var fav = el('span', 'mf-doc-card__fav');
    fav.setAttribute('aria-hidden', 'true');
    fav.textContent = doc.favorite ? '♥' : '♡';   // heart filled / outline
    thumb.appendChild(fav);

    // Snippet body — serif text. Title shown as bold first line.
    var snippet = el('div', 'mf-doc-card__snippet');
    var h = el('div', 'mf-doc-card__snippet-h');
    h.textContent = doc.title || '(untitled)';
    snippet.appendChild(h);
    if (doc.snippet) {
      snippet.appendChild(document.createTextNode(doc.snippet));
    }
    thumb.appendChild(snippet);

    card.appendChild(thumb);
    return card;
  }

  // Build a linear row DOM (list density).
  function createListRow(doc) {
    if (!doc) throw new Error('MFDocCard.createListRow: doc record required');
    var fmt = safeFormat(doc.format);

    var row = el('div', 'mf-doc-list-row');
    row.setAttribute('data-doc-id', doc.id || '');
    row.setAttribute('data-doc-format', fmt);

    var icon = el('span', 'mf-doc-list-row__fmt mf-doc-list-row__fmt--' + fmt);
    icon.textContent = fmt.toUpperCase().slice(0, 3);
    row.appendChild(icon);

    var title = el('span', 'mf-doc-list-row__title');
    title.textContent = doc.title || '(untitled)';
    row.appendChild(title);

    var path = el('span', 'mf-doc-list-row__path');
    path.textContent = doc.path || '';
    row.appendChild(path);

    var size = el('span', 'mf-doc-list-row__size');
    size.textContent = formatSize(doc.size);
    row.appendChild(size);

    var stamp = el('span', 'mf-doc-list-row__stamp');
    stamp.textContent = formatStamp(doc.modified);
    row.appendChild(stamp);

    var fav = el('span', 'mf-doc-list-row__fav');
    fav.setAttribute('aria-hidden', 'true');
    fav.textContent = doc.favorite ? '♥' : '♡';
    row.appendChild(fav);

    return row;
  }

  function formatSize(bytes) {
    if (typeof bytes !== 'number' || bytes < 0) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  function formatStamp(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      var now = new Date();
      var diff = (now - d) / 1000;
      if (diff < 60) return Math.floor(diff) + ' sec ago';
      if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
      if (diff < 86400) return Math.floor(diff / 3600) + ' hr ago';
      if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' d ago';
      return d.toISOString().slice(0, 10);
    } catch (e) { return ''; }
  }

  global.MFDocCard = {
    create: create,
    createListRow: createListRow,
    formatSize: formatSize,
    formatStamp: formatStamp
  };
})(window);
```

- [x] **Step 2: Append base CSS to components.css**

Append to `static/css/components.css`:

```css
/* === document card (cards / compact densities) === */
.mf-doc-card {
  cursor: pointer;
  transition: transform var(--mf-transition-fast);
  font-family: var(--mf-font-sans);
}
.mf-doc-card:hover { transform: translateY(-2px); }

.mf-doc-card__thumb {
  aspect-ratio: 0.78;
  border-radius: var(--mf-radius-thumb);
  overflow: hidden;
  position: relative;
  background: var(--mf-surface-paper);
  border: 1px solid #e8e6df;
  box-shadow: var(--mf-shadow-thumb);
  display: flex;
  flex-direction: column;
}

.mf-doc-card__band { height: 32%; position: relative; }
.mf-doc-card__band--pdf  { background: var(--mf-fmt-pdf); }
.mf-doc-card__band--docx { background: var(--mf-fmt-docx); }
.mf-doc-card__band--pptx { background: var(--mf-fmt-pptx); }
.mf-doc-card__band--xlsx { background: var(--mf-fmt-xlsx); }
.mf-doc-card__band--eml  { background: var(--mf-fmt-eml); }
.mf-doc-card__band--psd  { background: var(--mf-fmt-psd); }
.mf-doc-card__band--mp4  { background: var(--mf-fmt-mp4); }
.mf-doc-card__band--md   { background: var(--mf-fmt-md); }

.mf-doc-card__band-label {
  position: absolute;
  left: 0.55rem; bottom: 0.4rem;
  color: #fff;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  text-shadow: 0 1px 2px rgba(0,0,0,0.18);
}

.mf-doc-card__fav {
  position: absolute;
  top: 0.45rem; right: 0.45rem;
  width: 24px; height: 24px;
  border-radius: 50%;
  background: rgba(255,255,255,0.92);
  color: var(--mf-color-text-muted);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.78rem;
}

.mf-doc-card__snippet {
  padding: 0.6rem 0.7rem 0.5rem;
  font-size: 0.65rem;
  color: #2a2a2a;
  line-height: 1.45;
  font-family: var(--mf-font-serif);
  flex: 1;
  overflow: hidden;
  position: relative;
}
.mf-doc-card__snippet::after {
  content: '';
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 30%;
  background: linear-gradient(180deg, rgba(254,254,251,0) 0%, rgba(254,254,251,1) 92%);
  pointer-events: none;
}
.mf-doc-card__snippet-h {
  font-weight: 700;
  font-size: 0.74rem;
  margin-bottom: 0.25rem;
  color: var(--mf-color-text);
  font-family: var(--mf-font-sans);
}
```

- [x] **Step 3: Append List-row CSS**

Append to `static/css/components.css`:

```css
/* === document list-row (list density) === */
.mf-doc-list-row {
  display: grid;
  grid-template-columns: 24px 2.4fr 2fr 64px 0.9fr 24px;
  gap: 0.85rem;
  align-items: center;
  padding: 0.5rem;
  border-bottom: 1px solid #f4f4f4;
  font-size: 0.84rem;
  cursor: pointer;
  font-family: var(--mf-font-sans);
}
.mf-doc-list-row:hover { background: var(--mf-surface-soft); }

.mf-doc-list-row__fmt {
  width: 24px; height: 24px;
  border-radius: 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.55rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: #fff;
}
.mf-doc-list-row__fmt--pdf  { background: var(--mf-fmt-pdf); }
.mf-doc-list-row__fmt--docx { background: var(--mf-fmt-docx); }
.mf-doc-list-row__fmt--pptx { background: var(--mf-fmt-pptx); }
.mf-doc-list-row__fmt--xlsx { background: var(--mf-fmt-xlsx); }
.mf-doc-list-row__fmt--eml  { background: var(--mf-fmt-eml); }
.mf-doc-list-row__fmt--psd  { background: var(--mf-fmt-psd); }
.mf-doc-list-row__fmt--mp4  { background: var(--mf-fmt-mp4); }
.mf-doc-list-row__fmt--md   { background: var(--mf-fmt-md); }

.mf-doc-list-row__title {
  color: var(--mf-color-text);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mf-doc-list-row__path {
  color: var(--mf-color-text-faint);
  font-size: 0.78rem;
  font-family: var(--mf-font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mf-doc-list-row__size {
  font-size: 0.7rem;
  color: var(--mf-color-text-muted);
}
.mf-doc-list-row__stamp {
  color: var(--mf-color-text-muted);
  font-size: 0.78rem;
}
.mf-doc-list-row__fav {
  color: var(--mf-color-text-fainter);
  font-size: 0.85rem;
}
```

- [x] **Step 4: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/components/doc-card.js`

Expected: zero matches.

- [x] **Step 5: Commit**

```bash
git add static/js/components/doc-card.js static/css/components.css
git commit -m "feat(ux): document card component (cards/compact + list-row)

MFDocCard.create(doc) returns the gradient-band-plus-snippet card DOM
used in cards (6/row) and compact (8/row) densities. createListRow(doc)
returns the linear row used in list density. formatSize / formatStamp
helpers exposed for reuse. Format-coded gradients consume CSS vars from
design-tokens.css. Safe DOM throughout. Spec §4."
```

---

## Task 2: Card grid orchestrator

**Files:**
- Create: `static/js/components/card-grid.js`

The grid takes a list of doc records and a density mode and renders the appropriate variant. Density-specific styling lives in CSS (next task).

- [x] **Step 1: Create the component**

Create `static/js/components/card-grid.js`:

```javascript
/* Card grid orchestrator. Renders a list of docs in the chosen density.
 * Spec §4 (densities), §10 (density preference).
 *
 * Usage:
 *   MFCardGrid.mount(slot, docs, 'cards');     // 6 per row
 *   MFCardGrid.mount(slot, docs, 'compact');   // 8 per row
 *   MFCardGrid.mount(slot, docs, 'list');      // linear rows
 *
 * Re-rendering replaces children — the grid is stateless about its docs.
 */
(function (global) {
  'use strict';

  var DENSITIES = { cards: 1, compact: 1, list: 1 };

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function mount(slot, docs, density) {
    if (!slot) throw new Error('MFCardGrid.mount: slot is required');
    if (!Array.isArray(docs)) docs = [];
    if (!DENSITIES[density]) density = 'cards';

    clear(slot);
    slot.classList.remove(
      'mf-card-grid--cards',
      'mf-card-grid--compact',
      'mf-card-grid--list'
    );
    slot.classList.add('mf-card-grid');
    slot.classList.add('mf-card-grid--' + density);

    if (density === 'list') {
      for (var i = 0; i < docs.length; i++) {
        slot.appendChild(MFDocCard.createListRow(docs[i]));
      }
    } else {
      for (var j = 0; j < docs.length; j++) {
        slot.appendChild(MFDocCard.create(docs[j]));
      }
    }
  }

  global.MFCardGrid = { mount: mount, DENSITIES: Object.keys(DENSITIES) };
})(window);
```

- [x] **Step 2: Append density-specific CSS to components.css**

Append to `static/css/components.css`:

```css
/* === card grid (per-density layout) === */
.mf-card-grid--cards {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 0.85rem;
}

.mf-card-grid--compact {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 0.6rem;
}
.mf-card-grid--compact .mf-doc-card__band { height: 38%; }
.mf-card-grid--compact .mf-doc-card__band-label { font-size: 0.6rem; }
.mf-card-grid--compact .mf-doc-card__snippet { padding: 0.4rem 0.5rem 0.35rem; font-size: 0.56rem; }
.mf-card-grid--compact .mf-doc-card__snippet-h { font-size: 0.62rem; }
.mf-card-grid--compact .mf-doc-card__fav { width: 20px; height: 20px; font-size: 0.66rem; }

.mf-card-grid--list {
  display: block;
  border-top: 1px solid var(--mf-border-soft);
}
```

- [x] **Step 3: Commit**

```bash
git add static/js/components/card-grid.js static/css/components.css
git commit -m "feat(ux): card grid orchestrator with per-density rendering

MFCardGrid.mount(slot, docs, density) replaces slot contents with the
appropriate doc-card variant for the chosen density. CSS supplies the
6-col / 8-col / linear layout. Cards and compact share the same DOM —
compact tunes via descendant selectors. List uses the linear-row DOM."
```

---

## Task 3: Density toggle component

**Files:**
- Create: `static/js/components/density-toggle.js`

A segmented control with Cards / Compact / List. Reads the current density from `MFPrefs`, writes back on click, fires telemetry.

- [x] **Step 1: Create the component**

Create `static/js/components/density-toggle.js`:

```javascript
/* Density toggle — segmented control bound to MFPrefs.density.
 * Spec §4, §10, §13.
 *
 * Usage:
 *   var unsub = MFDensityToggle.mount(slot, {
 *     onChange: function(density) { ... }   // optional, before-prefs hook
 *   });
 *
 * Reads/writes MFPrefs.density. Returns an unmount function that
 * unsubscribes from prefs changes.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var OPTIONS = [
    { id: 'cards',   label: 'Cards' },
    { id: 'compact', label: 'Compact' },
    { id: 'list',    label: 'List' }
  ];

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function buildBtn(opt, current) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'mf-seg__opt' + (opt.id === current ? ' mf-seg__opt--on' : '');
    b.setAttribute('data-density', opt.id);
    b.textContent = opt.label;
    return b;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFDensityToggle.mount: slot is required');
    var onChange = (opts && opts.onChange) || null;

    function render() {
      clear(slot);
      slot.classList.add('mf-seg');
      var current = MFPrefs.get('density') || 'cards';
      OPTIONS.forEach(function (o) {
        slot.appendChild(buildBtn(o, current));
      });
    }

    function onClick(ev) {
      var t = ev.target;
      while (t && t !== slot && !t.getAttribute('data-density')) t = t.parentNode;
      if (!t || t === slot) return;
      var next = t.getAttribute('data-density');
      var current = MFPrefs.get('density') || 'cards';
      if (next === current) return;
      if (onChange) {
        try { onChange(next); } catch (e) { console.error(e); }
      }
      MFPrefs.set('density', next);
      MFTelemetry.emit('ui.density_toggle', { from: current, to: next });
    }

    slot.addEventListener('click', onClick);
    var unsub = MFPrefs.subscribe('density', render);
    render();

    return function unmount() {
      slot.removeEventListener('click', onClick);
      unsub();
      clear(slot);
    };
  }

  global.MFDensityToggle = { mount: mount, OPTIONS: OPTIONS };
})(window);
```

- [x] **Step 2: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/components/density-toggle.js`

Expected: zero matches.

- [x] **Step 3: Commit**

```bash
git add static/js/components/density-toggle.js
git commit -m "feat(ux): density toggle (Cards/Compact/List) bound to MFPrefs

Segmented control. Reads MFPrefs.density on render, writes on click,
fires ui.density_toggle telemetry. Subscribes so external prefs changes
re-render. Returns unmount() for cleanup. Reuses .mf-seg base styles
from Plan 1A."
```

---

## Task 4: Sample doc fixtures (for dev-chrome)

**Files:**
- Create: `static/js/sample-docs.js`

A small dataset of realistic IBEW Local 46 documents for visual verification on the dev-chrome page. Twelve docs, mixing all eight formats.

- [x] **Step 1: Create the fixture**

Create `static/js/sample-docs.js`:

```javascript
/* Sample doc records for dev-chrome smoke testing.
 * Twelve realistic IBEW Local 46 documents covering all eight formats.
 * Plan 3 replaces this with real /api/search results.
 */
(function (global) {
  'use strict';

  var SAMPLE_DOCS = [
    {
      id: 'd1', format: 'pdf',
      title: 'Q4 2025 Financial Summary',
      snippet: 'Revenue increased 18% year over year, driven primarily by member dues growth and the new training-fund distributions approved in March.',
      path: '/finance/2025/q4/Q4-financials.pdf',
      size: 3355443, modified: '2026-04-28T14:08:00Z', favorite: true
    },
    {
      id: 'd2', format: 'docx',
      title: 'Contract Negotiation Prep v3',
      snippet: 'Opening positions for the May 2026 cycle. Priority items: wage scale adjustment, healthcare contribution cap, apprentice ratio.',
      path: '/local-46/contracts/contract-prep-v3.docx',
      size: 901120, modified: '2026-04-28T14:00:00Z'
    },
    {
      id: 'd3', format: 'pptx',
      title: 'Member Orientation 2026',
      snippet: 'Welcome to IBEW Local 46. Benefits enrollment, dues schedule, training pathways, first-year apprentice timeline.',
      path: '/training/onboard/orientation-2026.pptx',
      size: 14680064, modified: '2026-04-28T13:54:00Z'
    },
    {
      id: 'd4', format: 'xlsx',
      title: 'Apprentice Hours Tracking',
      snippet: 'FY2026 cohort progress as of period 4. 18 apprentices on track, 3 flagged for OJT shortfall, 1 on probation pending steward review.',
      path: '/training/tracking/apprentice-hours.xlsx',
      size: 1153434, modified: '2026-04-28T13:46:00Z'
    },
    {
      id: 'd5', format: 'eml',
      title: 'Re: Jurisdiction dispute',
      snippet: 'From Local 76 BA: regarding the Mercer Island substation work, our position remains that fiber pulls within the control building fall under our agreement.',
      path: '/correspondence/2026-q1/jurisdiction-thread.eml',
      size: 145408, modified: '2026-04-28T13:30:00Z'
    },
    {
      id: 'd6', format: 'md',
      title: '# Bylaws Revision Draft',
      snippet: 'Section 4 amendments for the May general meeting vote. Delegate selection, executive board terms, finance-review committee scope.',
      path: '/governance/bylaws/bylaws-revision-draft.md',
      size: 28672, modified: '2026-04-28T13:08:00Z'
    },
    {
      id: 'd7', format: 'psd',
      title: 'Brand Refresh Assets',
      snippet: 'Layered source for member portal redesign. Includes typography, color palette, logo lockups, business-card treatments.',
      path: '/design/2026-refresh/brand-refresh.psd',
      size: 87654321, modified: '2026-04-28T12:08:00Z'
    },
    {
      id: 'd8', format: 'mp4',
      title: 'JATC Welcome Video',
      snippet: 'Transcribed and indexed. Covers training milestones, classroom expectations, and union history. 14:22 runtime, 1080p.',
      path: '/training/media/jatc-welcome.mp4',
      size: 587202560, modified: '2026-04-28T11:08:00Z'
    },
    {
      id: 'd9', format: 'pdf',
      title: 'Safety Bulletin Q1',
      snippet: 'Updated arc-flash PPE requirements per OSHA 1910 revisions. Effective immediately for all energized work above 240V.',
      path: '/safety/bulletins/safety-q1.pdf',
      size: 2516582, modified: '2026-04-28T10:08:00Z'
    },
    {
      id: 'd10', format: 'xlsx',
      title: 'Pension Allocation 2026',
      snippet: 'Q1 distribution table with member-by-member breakdown. Includes vesting status, contribution year, projected payout at retirement age.',
      path: '/finance/pension/pension-2026.xlsx',
      size: 4194304, modified: '2026-04-28T09:08:00Z'
    },
    {
      id: 'd11', format: 'docx',
      title: 'Steward Training Notes',
      snippet: 'Consolidated from three sessions. Grievance handling, escalation paths, member-rights primer, common contract-language traps.',
      path: '/training/stewards/steward-notes.docx',
      size: 327680, modified: '2026-04-28T08:08:00Z'
    },
    {
      id: 'd12', format: 'eml',
      title: 'Re: Apprentice probation',
      snippet: 'Following up on the steward review — recommend extending the period by 30 days with weekly check-ins. Coordinate with JATC.',
      path: '/correspondence/2026-q1/probation-thread.eml',
      size: 98304, modified: '2026-04-28T07:08:00Z'
    }
  ];

  global.MFSampleDocs = SAMPLE_DOCS;
})(window);
```

- [x] **Step 2: Commit**

```bash
git add static/js/sample-docs.js
git commit -m "test(ux): sample doc fixtures for dev-chrome smoke testing

12 realistic IBEW Local 46 docs across all 8 supported formats. Used
on dev-chrome to verify card / grid / density rendering. Plan 3 replaces
this with live /api/search results."
```

---

## Task 5: Wire density toggle + grid into dev-chrome

**Files:**
- Modify: `static/dev-chrome.html` to load new scripts and add a card-demo section
- Modify: `static/dev-chrome.js` to mount the toggle + grid + subscribe to density changes

- [x] **Step 1: Update dev-chrome.html**

Add the new script tags before `dev-chrome.js`:

```html
  <script src="/static/js/components/doc-card.js"></script>
  <script src="/static/js/components/card-grid.js"></script>
  <script src="/static/js/components/density-toggle.js"></script>
  <script src="/static/js/sample-docs.js"></script>
```

Append a card-demo section to the body, after the existing `.dev-banner`:

```html
  <div class="dev-banner">
    <h2 style="font-size: 1.05rem; margin: 1.4rem 0 0.4rem; color: #0a0a0a">Card grid demo</h2>
    <div style="display: flex; gap: 1rem; align-items: center; margin-bottom: 1rem;">
      <span style="color: #5a5a5a; font-size: 0.86rem">Density:</span>
      <div id="mf-density-toggle"></div>
      <span style="color: #888; font-size: 0.78rem; margin-left: auto;">12 sample docs</span>
    </div>
    <div id="mf-card-grid"></div>
  </div>
```

- [x] **Step 2: Update dev-chrome.js**

Append to `static/dev-chrome.js` (inside the same IIFE — find the closing `})();` and add this BEFORE it):

```javascript
  // === Card grid demo ===
  function renderCardGrid() {
    var slot = document.getElementById('mf-card-grid');
    var density = MFPrefs.get('density') || 'cards';
    MFCardGrid.mount(slot, MFSampleDocs, density);
  }

  // Mount density toggle once.
  MFDensityToggle.mount(document.getElementById('mf-density-toggle'));

  // Re-render grid when density changes.
  MFPrefs.subscribe('density', renderCardGrid);

  // Initial render.
  renderCardGrid();
```

- [x] **Step 3: Smoke verify**

```bash
docker-compose up -d
```

Visit `http://localhost:8000/static/dev-chrome.html`. Expected:

1. Existing chrome (nav, avatar, layout-icon) still works
2. **New section below**: "Card grid demo" with a Cards/Compact/List segmented toggle
3. Default density = `cards`; grid shows 6 cards per row × 2 rows = 12 cards visible. Each card has a colored gradient band (PDF red, DOCX blue, etc.), format label, and 3-4 lines of serif snippet.
4. Click **Compact** → grid re-renders with 8 cards per row, smaller padding, smaller text. Cards still have gradient bands but more compressed.
5. Click **List** → grid re-renders as 12 linear rows. Each row: tiny colored format icon · title · path · size · timestamp · heart icon. No gradient band.
6. Reload page → density preference is preserved.
7. Network tab: `PUT /api/user-prefs` 500ms after each toggle click; `POST /api/telemetry` immediately on each click with `event: ui.density_toggle`.
8. Open Cards mode → verify gradient colors match the format (PDFs red, DOCX blue, PPTX orange, XLSX green, EML purple, MD charcoal, PSD indigo, MP4 teal).

If anything reads wrong visually, cross-check against `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/home-search-v3.html`.

- [x] **Step 4: Commit**

```bash
git add static/dev-chrome.html static/dev-chrome.js
git commit -m "feat(ux): dev-chrome card grid demo with density toggle

Adds card-grid demo section beneath the chrome demo. Density toggle
+ 12 sample docs + MFCardGrid orchestrator. Switching density
persists via MFPrefs and fires ui.density_toggle telemetry. Validates
the full card-grid-density flow before mounting on real pages
(Plan 3+)."
```

---

## Acceptance check (run before declaring this plan complete)

- [x] `git log --oneline | head -10` shows 5 task commits in order, on top of Plan 1C
- [x] `grep -rn "innerHTML" static/js/components/doc-card.js static/js/components/card-grid.js static/js/components/density-toggle.js` — zero matches
- [x] `docker-compose up -d` succeeds, no console errors
- [x] Visit `/static/dev-chrome.html` — full chrome flow still works AND card grid demo renders correctly in all three densities
- [x] Density preference persists across page reloads
- [x] All 8 format gradients render distinctly (PDF red, DOCX blue, PPTX orange, XLSX green, EML purple, MD dark, PSD indigo, MP4 teal)
- [x] `ui.density_toggle` telemetry events visible in `docker-compose logs app`

Once all green, **Plan 2A is done**. Next plan: `2026-04-28-ux-overhaul-card-interactions.md` (Plan 2B — hover preview popover, right-click context menu with Advanced expander, multi-select state, bulk action bar, folder browse).

---

## Self-review

**Spec coverage:**
- §4 (document card anatomy + density modes — visual rendering): ✓ Tasks 1, 2
- §10 (density preference persistence): ✓ Task 3 (density toggle subscribes to MFPrefs)
- §13 (telemetry: `ui.density_toggle`): ✓ Task 3

**Spec gaps for this plan (deferred to Plan 2B):**
- §4 hover preview, right-click menu, multi-select, bulk action bar, folder browse: Plan 2B
- §9 power-user gate Advanced expander in context menu: Plan 2B
- §13 telemetry: `ui.hover_preview_shown`, `ui.context_menu_action`: Plan 2B

**Placeholder scan:** No TODOs. Every task contains complete, runnable code.

**Type / API consistency:**
- `MFDocCard.create(doc)` and `MFDocCard.createListRow(doc)` consistently take a doc record with `{id, format, title, snippet, path, size, modified, favorite}` shape
- `MFCardGrid.mount(slot, docs, density)` consistent with other `MFFoo.mount(slot, opts)` patterns
- `MFDensityToggle.mount(slot, opts)` returns unmount() (consistent with subscribe-style cleanup)
- Format-coded gradient class names match between doc-card.js (`mf-doc-card__band--pdf`), components.css selector, and the format string in doc records

**Safe-DOM verification (mandatory final scan):**

```
grep -rn "innerHTML" static/js/components/doc-card.js \
  static/js/components/card-grid.js \
  static/js/components/density-toggle.js \
  static/js/sample-docs.js
```

Expected: empty.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-document-card.md`.

Sized for: 5 implementer dispatches + 5 spec reviews + 5 code quality reviews ≈ 15 subagent calls.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
