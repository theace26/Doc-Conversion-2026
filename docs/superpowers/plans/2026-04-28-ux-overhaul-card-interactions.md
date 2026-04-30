# UX Overhaul — Card Interactions Implementation Plan (Plan 2B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the four interactions document cards need to feel like a real tool: hover preview popover (rich meta + AI summary + action buttons), right-click context menu (with the power-user `Advanced ▾` expander gating Markdown actions), multi-select state with hover-checkboxes, and a bulk action bar that surfaces when items are selected. Wrap with a folder browse page (breadcrumb + folder header + grid + bulk bar) that demonstrates the whole thing end-to-end on `dev-chrome.html`.

**Architecture:** Extends Plan 2A's `MFDocCard` and `MFCardGrid` with event hooks. New globals: `MFHoverPreview`, `MFContextMenu`, `MFCardSelection` (state manager — observable, exposes selected IDs), `MFBulkBar`. **Safe DOM construction throughout — zero `innerHTML` with template literals.** Popovers append to `document.body` like Plan 1C's avatar menu and layout popover. Context-menu Advanced section honors `MFPrefs.advanced_actions_inline` from Plan 1C — when ON the Markdown items render inline (de-emphasized); when OFF they hide behind a click-to-expand row.

**Tech stack:** Vanilla HTML / CSS / JS

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §4 (cards + interactions), §9 (power-user gate), §10 (preferences), §13 (telemetry events `ui.hover_preview_shown`, `ui.context_menu_action`)

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/card-interactions.html` (hover, right-click, folder browse all on one page)

**Out of scope (deferred):**
- Search-as-home page rendering (Plan 3 — uses these interactions)
- Real `/api/files/<id>/preview` endpoint for hover preview content (Plan 3 wires actual data)
- Real action handlers for menu items (Plan 4 — wires Pin/Flag/Download to real endpoints)
- Folder navigation backend (Plan 4 — `/api/folders/<path>` and routing)

**Prerequisites:** Plans 1A + 1B + 1C + 2A must all be complete. Run `git log --oneline | head -20` and confirm: `f37e633` (1A), `50e552e` (1B), `3d5b1e9` (1C), `6228373` (2A).

---

## Model + effort

| Role | Model | Effort |
|------|-------|--------|
| Implementer | Sonnet | high (8-16h) |
| Reviewer | Sonnet | med (3-5h) |

**Reasoning:** Hover preview popover, right-click context menu, multi-select observable state, bulk action bar, folder-browse page wrapping it all. Multiple interaction systems coexisting without listener leaks is the failure mode. This is the biggest UX-overhaul phase — reviewer needs medium effort because there are 4 distinct interaction surfaces to walk through, not one.

**Execution mode:** Dispatch this plan via `superpowers:subagent-driven-development`. Each role is a separate `Agent` call — `Agent({model: "sonnet", ...})` for implementation, `Agent({model: "sonnet", ...})` for review. A single-session `executing-plans` read will *not* switch models on its own; this metadata is routing input for the orchestrator.

**Source:** [`docs/spreadsheet/phase_model_plan.xlsx`](../../spreadsheet/phase_model_plan.xlsx)

---

## File structure (this plan creates / modifies)

**Create:**
- `static/js/components/hover-preview.js`
- `static/js/components/context-menu.js`
- `static/js/components/card-selection.js`
- `static/js/components/bulk-bar.js`
- `static/js/components/folder-browse.js`

**Modify:**
- `static/js/components/doc-card.js` — emit hover/contextmenu events; render checkbox slot
- `static/css/components.css` — append hover-preview, context-menu, multi-select, bulk-bar, folder-browse styles
- `static/dev-chrome.html` — load new scripts, add a folder-browse demo section
- `static/dev-chrome.js` — wire hover + right-click + selection + bulk bar + folder browse demo

---

## Task 1: Hover preview popover component

**Files:**
- Create: `static/js/components/hover-preview.js`

`340px` floating popover anchored to a card's right side (or top if rightmost column). Triggered after **400ms** hover delay. Shows full title, full path, format/size, modified-by, indexed-status, AI summary block, and four action buttons (Preview / Download / Go to folder / `…` more).

- [ ] **Step 1: Create the component using safe DOM construction**

Create `static/js/components/hover-preview.js`:

```javascript
/* Hover preview popover for document cards.
 * Spec §4 (anatomy). 400ms hover delay. Body-mounted to escape
 * overflow:hidden ancestors.
 *
 * Usage:
 *   var hp = MFHoverPreview.create({
 *     onAction: function(action, doc) { ... }   // 'preview' | 'download' | 'goto-folder' | 'more'
 *   });
 *   hp.armOn(cardEl, doc);   // arms hover trigger; 400ms after enter -> show
 *   hp.disarm(cardEl);       // remove the listeners
 *
 * Safe DOM throughout — every text via textContent.
 */
(function (global) {
  'use strict';

  var DELAY_MS = 400;

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function build(doc, onAction, onClose) {
    var root = el('div', 'mf-hover-preview');
    root.setAttribute('role', 'tooltip');

    var title = el('h3', 'mf-hover-preview__title');
    title.textContent = doc.title || '(untitled)';
    root.appendChild(title);

    var path = el('div', 'mf-hover-preview__path');
    path.textContent = doc.path || '';
    root.appendChild(path);

    // Meta grid
    var grid = el('div', 'mf-hover-preview__grid');
    var rows = [
      ['Format', formatLine(doc)],
      ['Modified', doc.modified_human || formatStamp(doc.modified) || '-'],
      ['Indexed', doc.indexed_status || '-'],
      ['Opens', doc.opens != null ? String(doc.opens) + ' in last 7 days' : '-'],
      ['Status', doc.status || '-'],
    ];
    rows.forEach(function (pair) {
      var k = el('span', 'mf-hover-preview__k'); k.textContent = pair[0];
      var v = el('span', 'mf-hover-preview__v'); v.textContent = pair[1];
      grid.appendChild(k); grid.appendChild(v);
    });
    root.appendChild(grid);

    if (doc.ai_summary) {
      var summary = el('div', 'mf-hover-preview__summary');
      var lab = el('div', 'mf-hover-preview__summary-lab');
      lab.textContent = 'AI Summary';
      summary.appendChild(lab);
      summary.appendChild(document.createTextNode(doc.ai_summary));
      root.appendChild(summary);
    }

    var actions = el('div', 'mf-hover-preview__actions');
    [
      { id: 'preview',   label: 'Preview',       primary: true },
      { id: 'download',  label: 'Download' },
      { id: 'goto-folder', label: 'Go to folder' },
      { id: 'more',      label: '…' },
    ].forEach(function (a) {
      var b = el('button', 'mf-hover-preview__btn' + (a.primary ? ' mf-hover-preview__btn--primary' : ''));
      b.type = 'button';
      b.textContent = a.label;
      b.setAttribute('data-action', a.id);
      b.addEventListener('click', function () {
        if (typeof onAction === 'function') onAction(a.id, doc);
        if (typeof onClose === 'function') onClose();
      });
      actions.appendChild(b);
    });
    root.appendChild(actions);

    return root;
  }

  function formatLine(doc) {
    var parts = [];
    if (doc.format) parts.push(String(doc.format).toUpperCase());
    if (typeof doc.size === 'number') parts.push(MFDocCard.formatSize(doc.size));
    return parts.length ? parts.join(' · ') : '-';
  }
  function formatStamp(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      return d.toISOString().slice(0, 10);
    } catch (e) { return ''; }
  }

  function create(opts) {
    var onAction = (opts && opts.onAction) || function () {};
    var current = null;       // { card, popover, doc }
    var timer = null;

    function close() {
      if (timer) { clearTimeout(timer); timer = null; }
      if (current && current.popover && current.popover.parentNode) {
        current.popover.parentNode.removeChild(current.popover);
      }
      if (current && current.card) {
        current.card.removeAttribute('data-mf-hover-active');
      }
      current = null;
    }

    function show(card, doc) {
      close();
      var pop = build(doc, onAction, close);
      pop.style.position = 'absolute';
      document.body.appendChild(pop);
      anchor(pop, card);
      card.setAttribute('data-mf-hover-active', 'true');
      current = { card: card, popover: pop, doc: doc };
      MFTelemetry && MFTelemetry.emit && MFTelemetry.emit(
        'ui.hover_preview_shown', { doc_id: doc.id || '' }
      );
    }

    function anchor(pop, card) {
      var r = card.getBoundingClientRect();
      var width = 340;
      var spaceRight = document.documentElement.clientWidth - r.right;
      var spaceTop = r.top;
      // Default: anchor to card's right side, vertically aligned to its top
      pop.style.width = width + 'px';
      if (spaceRight > width + 16) {
        pop.style.left = (window.scrollX + r.right + 12) + 'px';
        pop.style.top = (window.scrollY + r.top - 12) + 'px';
      } else if (spaceTop > 280) {
        // Anchor above
        pop.style.left = (window.scrollX + r.left) + 'px';
        pop.style.top = (window.scrollY + r.top - 280) + 'px';
      } else {
        // Anchor below
        pop.style.left = (window.scrollX + r.left) + 'px';
        pop.style.top = (window.scrollY + r.bottom + 12) + 'px';
      }
    }

    function armOn(card, doc) {
      function onEnter() {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () { show(card, doc); }, DELAY_MS);
      }
      function onLeave() {
        if (timer) { clearTimeout(timer); timer = null; }
        if (current && current.card === card) close();
      }
      card.addEventListener('mouseenter', onEnter);
      card.addEventListener('mouseleave', onLeave);
      // Store for disarm
      card._mfHoverHandlers = { onEnter: onEnter, onLeave: onLeave };
    }

    function disarm(card) {
      var h = card._mfHoverHandlers;
      if (!h) return;
      card.removeEventListener('mouseenter', h.onEnter);
      card.removeEventListener('mouseleave', h.onLeave);
      delete card._mfHoverHandlers;
      if (current && current.card === card) close();
    }

    return { armOn: armOn, disarm: disarm, close: close };
  }

  global.MFHoverPreview = { create: create, DELAY_MS: DELAY_MS };
})(window);
```

- [ ] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === hover preview popover === */
.mf-hover-preview {
  position: absolute;
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card);
  box-shadow: 0 12px 40px -8px rgba(0,0,0,0.22);
  padding: 1rem 1rem 0.85rem;
  z-index: 25;
  font-family: var(--mf-font-sans);
  pointer-events: auto;
}
.mf-hover-preview__title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--mf-color-text);
  margin: 0 0 0.25rem;
  line-height: 1.25;
}
.mf-hover-preview__path {
  font-size: 0.74rem;
  color: var(--mf-color-accent);
  font-family: var(--mf-font-mono);
  margin-bottom: 0.7rem;
  word-break: break-all;
}
.mf-hover-preview__grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.3rem 0.7rem;
  font-size: 0.78rem;
  margin-bottom: 0.85rem;
}
.mf-hover-preview__k { color: var(--mf-color-text-faint); }
.mf-hover-preview__v {
  color: var(--mf-color-text);
  font-weight: 500;
}
.mf-hover-preview__summary {
  font-size: 0.78rem;
  color: var(--mf-color-text-soft);
  line-height: 1.45;
  padding: 0.7rem 0.8rem;
  background: var(--mf-surface-soft);
  border-radius: var(--mf-radius-thumb);
  margin-bottom: 0.85rem;
  border-left: 2px solid var(--mf-color-accent);
}
.mf-hover-preview__summary-lab {
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--mf-color-accent);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 0.25rem;
}
.mf-hover-preview__actions {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.mf-hover-preview__btn {
  background: var(--mf-surface);
  border: 1px solid #e0e0e0;
  border-radius: var(--mf-radius-thumb);
  padding: 0.4rem 0.75rem;
  font-size: 0.78rem;
  color: var(--mf-color-text-soft);
  cursor: pointer;
  font-weight: 500;
  font-family: inherit;
}
.mf-hover-preview__btn--primary {
  background: var(--mf-color-accent);
  border-color: var(--mf-color-accent);
  color: #fff;
}
```

- [ ] **Step 3: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/components/hover-preview.js`

Expected: zero matches.

- [ ] **Step 4: Commit**

```bash
git add static/js/components/hover-preview.js static/css/components.css
git commit -m "feat(ux): hover preview popover for document cards

400ms hover delay. Body-mounted (escapes overflow:hidden). Anchors
right-of-card by default, falls back to top/bottom on edge cases.
Title + path + meta grid + AI summary + 4 action buttons (preview /
download / goto-folder / more). Telemetry: ui.hover_preview_shown.
Safe DOM throughout — every text via textContent."
```

---

## Task 2: Right-click context menu component

**Files:**
- Create: `static/js/components/context-menu.js`

`240px` menu with grouped items: View / Export / AI / Pin & Flag / Advanced. Advanced section honors the `advanced_actions_inline` preference (Plan 1C) — when ON the items render inline (de-emphasized); when OFF they hide behind an `Advanced ▾` expander row.

- [ ] **Step 1: Create the component**

Create `static/js/components/context-menu.js`:

```javascript
/* Right-click context menu for document cards.
 * Spec §4 (menu items), §9 (power-user gate via Advanced expander).
 *
 * Usage:
 *   var cm = MFContextMenu.create({
 *     onAction: function(action, doc) { ... }
 *   });
 *   cm.openAt(clientX, clientY, doc);
 *   cm.close();
 *
 * Reads MFPrefs.advanced_actions_inline (Plan 1C) to decide whether
 * Markdown / AI integration items render inline or behind an
 * Advanced expander row.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    {
      label: 'View',
      items: [
        { id: 'preview',     label: 'Preview file',           kbd: 'Space' },
        { id: 'open',        label: 'Open original',          kbd: '⌘O' },
        { id: 'goto-folder', label: 'Go to containing folder', kbd: '⌘↑' },
      ],
    },
    {
      label: 'Export',
      items: [
        { id: 'download',  label: 'Download original' },
        { id: 'copy-path', label: 'Copy file path' },
      ],
    },
    {
      label: 'AI',
      items: [
        { id: 'summarize', label: 'Summarize with AI' },
        { id: 'ask',       label: 'Ask a question about this file' },
      ],
    },
  ];

  // Power-user-gated items (the Advanced section).
  var ADVANCED_ITEMS = [
    { id: 'download-md',     label: 'Download as Markdown', kbd: '⌘D' },
    { id: 'copy-md',         label: 'Copy Markdown to clipboard' },
    { id: 'view-md-source',  label: 'View raw Markdown source' },
  ];

  var TRAILING_ITEMS = [
    { id: 'pin',  label: 'Pin to favorites' },
    { id: 'flag', label: 'Flag for review', danger: true },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildSectionLabel(text) {
    var l = el('div', 'mf-ctx__sec-label');
    l.textContent = text;
    return l;
  }

  function buildItem(item, opts) {
    var a = el('a', 'mf-ctx__item');
    if (item.danger) a.className += ' mf-ctx__item--danger';
    if (opts && opts.adv) a.className += ' mf-ctx__item--adv';
    a.setAttribute('role', 'menuitem');
    a.setAttribute('data-action', item.id);
    var label = el('span', 'mf-ctx__grow');
    label.textContent = item.label;
    a.appendChild(label);
    if (item.kbd) {
      var kbd = el('span', 'mf-ctx__kbd');
      kbd.textContent = item.kbd;
      a.appendChild(kbd);
    }
    return a;
  }

  function buildAdvExpander(open) {
    var row = el('div', 'mf-ctx__exp' + (open ? ' mf-ctx__exp--open' : ''));
    row.setAttribute('data-mf-exp', '1');
    var lab = el('span'); lab.textContent = 'Advanced · Markdown & AI integrations';
    var chev = el('span', 'mf-ctx__exp-chev');
    chev.textContent = '▾';
    row.appendChild(lab);
    row.appendChild(chev);
    return row;
  }

  function buildSep(heavy) {
    var s = el('div', heavy ? 'mf-ctx__sep mf-ctx__sep--heavy' : 'mf-ctx__sep');
    return s;
  }

  function create(opts) {
    var onAction = (opts && opts.onAction) || function () {};
    var root = el('div', 'mf-ctx');
    root.setAttribute('role', 'menu');
    root.style.display = 'none';

    var current = null;       // { doc, x, y }
    var advExpanded = false;

    function rerender() {
      while (root.firstChild) root.removeChild(root.firstChild);
      SECTIONS.forEach(function (sec) {
        root.appendChild(buildSectionLabel(sec.label));
        sec.items.forEach(function (item) {
          root.appendChild(buildItem(item));
        });
        root.appendChild(buildSep());
      });
      // Trailing items (pin / flag)
      TRAILING_ITEMS.forEach(function (item) {
        root.appendChild(buildItem(item));
      });

      // Advanced section — depends on prefs
      var inlineDefault = MFPrefs && MFPrefs.get && MFPrefs.get('advanced_actions_inline');
      var showInline = inlineDefault === true || advExpanded;
      root.appendChild(buildSep(true));
      if (showInline) {
        root.appendChild(buildSectionLabel('Advanced · Markdown & AI integrations'));
        ADVANCED_ITEMS.forEach(function (item) {
          root.appendChild(buildItem(item, { adv: true }));
        });
      } else {
        root.appendChild(buildAdvExpander(false));
      }
    }

    root.addEventListener('click', function (ev) {
      // Expander toggle
      var exp = ev.target.closest && ev.target.closest('[data-mf-exp]');
      if (exp) {
        advExpanded = !advExpanded;
        rerender();
        return;
      }
      // Item click
      var item = ev.target.closest && ev.target.closest('[data-action]');
      if (!item) return;
      var action = item.getAttribute('data-action');
      if (current && current.doc) {
        try { onAction(action, current.doc); } catch (e) { console.error(e); }
        MFTelemetry && MFTelemetry.emit && MFTelemetry.emit(
          'ui.context_menu_action', { action: action, doc_id: current.doc.id || '' }
        );
      }
      close();
    });

    var onOutside = null, onEsc = null;

    function openAt(x, y, doc) {
      current = { doc: doc, x: x, y: y };
      advExpanded = false;
      rerender();
      root.style.position = 'absolute';
      root.style.left = (window.scrollX + x) + 'px';
      root.style.top = (window.scrollY + y) + 'px';
      root.style.display = 'block';
      document.body.appendChild(root);

      // Keep menu inside viewport
      var r = root.getBoundingClientRect();
      var vw = document.documentElement.clientWidth;
      var vh = document.documentElement.clientHeight;
      if (r.right > vw - 8) {
        root.style.left = (window.scrollX + Math.max(8, x - r.width)) + 'px';
      }
      if (r.bottom > vh - 8) {
        root.style.top = (window.scrollY + Math.max(8, y - r.height)) + 'px';
      }

      requestAnimationFrame(function () {
        onOutside = function (ev) {
          if (!root.contains(ev.target)) close();
        };
        onEsc = function (ev) { if (ev.key === 'Escape') close(); };
        document.addEventListener('click', onOutside);
        document.addEventListener('keydown', onEsc);
      });
    }

    function close() {
      root.style.display = 'none';
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener('click', onOutside);
      document.removeEventListener('keydown', onEsc);
      current = null;
    }

    return { openAt: openAt, close: close };
  }

  global.MFContextMenu = { create: create };
})(window);
```

- [ ] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === right-click context menu === */
.mf-ctx {
  position: absolute;
  width: 240px;
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-input);
  box-shadow: 0 12px 32px -6px rgba(0,0,0,0.22);
  padding: 0.35rem;
  z-index: 30;
  font-size: 0.85rem;
  font-family: var(--mf-font-sans);
}
.mf-ctx__sec-label {
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--mf-color-text-fainter);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  padding: 0.45rem 0.65rem 0.2rem;
}
.mf-ctx__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.45rem 0.65rem;
  border-radius: 7px;
  color: var(--mf-color-text-soft);
  cursor: pointer;
  text-decoration: none;
}
.mf-ctx__item:hover {
  background: var(--mf-color-accent-tint-2);
  color: var(--mf-color-accent);
}
.mf-ctx__item--danger:hover {
  background: var(--mf-color-error-bg);
  color: var(--mf-color-error);
}
.mf-ctx__item--adv {
  color: #7a7a8a;
  font-size: 0.8rem;
}
.mf-ctx__grow { flex: 1; min-width: 0; }
.mf-ctx__kbd {
  font-size: 0.7rem;
  color: var(--mf-color-text-fainter);
  font-family: var(--mf-font-mono);
}
.mf-ctx__sep { height: 1px; background: var(--mf-border-soft); margin: 0.3rem 0.35rem; }
.mf-ctx__sep--heavy {
  height: 1px;
  background: var(--mf-border);
  margin: 0.5rem 0.35rem 0.35rem;
}
.mf-ctx__exp {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.65rem;
  color: #9a9a9a;
  font-size: 0.78rem;
  cursor: pointer;
  border-radius: 7px;
}
.mf-ctx__exp:hover {
  background: var(--mf-surface-soft);
  color: var(--mf-color-accent);
}
.mf-ctx__exp-chev { font-size: 0.62rem; transition: transform 0.15s; }
.mf-ctx__exp--open .mf-ctx__exp-chev { transform: rotate(180deg); }
```

- [ ] **Step 3: Commit**

```bash
git add static/js/components/context-menu.js static/css/components.css
git commit -m "feat(ux): right-click context menu with power-user gate

3 sections (View / Export / AI) + Pin & Flag + Advanced section. The
Advanced section reads MFPrefs.advanced_actions_inline — inline when
true, behind an 'Advanced ▾' expander when false. Default off for
member role, on for operator/admin (set by Plan 1C). Telemetry:
ui.context_menu_action. Click-outside / Esc close. Auto-flips to
left or up if menu would overflow viewport. Safe DOM throughout."
```

---

## Task 3: Card-selection state manager

**Files:**
- Create: `static/js/components/card-selection.js`

State manager (not a UI component — just a publish-subscribe store) tracking which doc IDs are currently selected. Other components (cards, bulk bar) subscribe to update their visuals.

- [ ] **Step 1: Create the module**

Create `static/js/components/card-selection.js`:

```javascript
/* Multi-select state manager for document cards.
 * Pub-sub store. Other components subscribe to render based on selection.
 *
 * Usage:
 *   MFCardSelection.toggle(docId);
 *   MFCardSelection.set([docId1, docId2]);
 *   MFCardSelection.clear();
 *   MFCardSelection.has(docId);
 *   MFCardSelection.size();
 *   MFCardSelection.list();           // array copy
 *   MFCardSelection.subscribe(fn);    // fn(selectedSet) on change
 *
 * No DOM. Pure state.
 */
(function (global) {
  'use strict';

  var selected = new Set();
  var subs = [];

  function fire() {
    var snapshot = new Set(selected);
    subs.forEach(function (fn) {
      try { fn(snapshot); } catch (e) { console.error(e); }
    });
  }

  function toggle(id) {
    if (!id) return;
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    fire();
  }
  function set(ids) {
    selected = new Set(ids || []);
    fire();
  }
  function clear() {
    if (selected.size === 0) return;
    selected.clear();
    fire();
  }
  function has(id) { return selected.has(id); }
  function size() { return selected.size; }
  function list() { return Array.from(selected); }
  function subscribe(fn) {
    subs.push(fn);
    return function unsubscribe() {
      var i = subs.indexOf(fn);
      if (i >= 0) subs.splice(i, 1);
    };
  }

  global.MFCardSelection = {
    toggle: toggle, set: set, clear: clear,
    has: has, size: size, list: list,
    subscribe: subscribe,
  };
})(window);
```

- [ ] **Step 2: Commit**

```bash
git add static/js/components/card-selection.js
git commit -m "feat(ux): card-selection pub-sub state manager

Tracks which doc IDs are currently selected. No DOM — pure state with
subscribe API. Cards and bulk-bar subscribe to update visuals when
selection changes."
```

---

## Task 4: Wire hover, right-click, and selection into doc-card

**Files:**
- Modify: `static/js/components/doc-card.js` — add a hover-checkbox slot and emit/handle interaction events

The card from Plan 2A is presentational only. Extend it to:

1. Render a checkbox slot (visible on hover or when selected)
2. Emit a `mf:contextmenu` custom event on right-click (controller decides where the menu opens)
3. Add a `data-doc-id` attribute (already there from Plan 2A — confirm) so external handlers can identify the card
4. Subscribe to `MFCardSelection` to set `mf-doc-card--selected` class

This task is a small surgical edit to doc-card.js.

- [ ] **Step 1: Modify doc-card.js — add checkbox slot to thumb**

In `static/js/components/doc-card.js`, find the `function create(doc)` body. After the line that appends `band` and `fav` to `thumb`, add a checkbox before snippet:

```javascript
    // Multi-select checkbox slot (visible on hover or when selected).
    var cb = el('span', 'mf-doc-card__checkbox');
    cb.setAttribute('aria-hidden', 'true');
    cb.setAttribute('data-mf-checkbox', '1');
    thumb.appendChild(cb);
```

- [ ] **Step 2: Add a contextmenu event handler that emits a custom event**

In `MFDocCard.create()`, after the `card` element is fully built (before `return card`), add:

```javascript
    card.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      var detail = { doc: doc, x: ev.clientX, y: ev.clientY };
      card.dispatchEvent(new CustomEvent('mf:doc-contextmenu', { detail: detail, bubbles: true }));
    });

    // Click-on-checkbox toggles selection (clicking elsewhere on the card
    // is reserved for "open" — left-click default).
    card.addEventListener('click', function (ev) {
      var t = ev.target;
      if (t && t.getAttribute && t.getAttribute('data-mf-checkbox') === '1') {
        ev.stopPropagation();
        if (typeof MFCardSelection !== 'undefined') MFCardSelection.toggle(doc.id);
      }
    });
```

- [ ] **Step 3: Append CSS for the checkbox + selected state**

Append to `static/css/components.css`:

```css
/* === multi-select checkbox on doc-card === */
.mf-doc-card__checkbox {
  position: absolute;
  top: 0.45rem;
  left: 0.45rem;
  width: 20px;
  height: 20px;
  border-radius: 5px;
  background: rgba(255,255,255,0.92);
  border: 1.5px solid rgba(255,255,255,0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity var(--mf-transition-fast);
  z-index: 3;
  cursor: pointer;
}
.mf-doc-card:hover .mf-doc-card__checkbox { opacity: 1; }
.mf-doc-card--selected .mf-doc-card__checkbox {
  opacity: 1;
  background: var(--mf-color-accent);
  border-color: var(--mf-color-accent);
  color: #fff;
}
.mf-doc-card--selected .mf-doc-card__checkbox::before {
  content: "\2713";
  font-size: 0.8rem;
}
.mf-doc-card--selected .mf-doc-card__thumb {
  box-shadow: 0 0 0 3px rgba(91, 61, 245, 0.32),
              var(--mf-shadow-thumb);
}
```

- [ ] **Step 4: Subscribe to MFCardSelection from card-grid (post-mount)**

Modify `MFCardGrid.mount()` in `static/js/components/card-grid.js` — after the children are appended, register a one-time subscription that updates `mf-doc-card--selected` classes on selection change. (Avoid stacking subscriptions on each remount: keep a module-scoped unsubscribe and call it before resubscribing.)

In `static/js/components/card-grid.js`, modify the IIFE to include this state:

```javascript
  var unsub = null;

  function applySelection(slot, selectedSet) {
    var cards = slot.querySelectorAll('.mf-doc-card');
    cards.forEach(function (card) {
      var id = card.getAttribute('data-doc-id');
      if (id && selectedSet.has(id)) card.classList.add('mf-doc-card--selected');
      else card.classList.remove('mf-doc-card--selected');
    });
  }

  function mount(slot, docs, density) {
    // ... existing rendering code ...

    // Re-apply current selection after re-render.
    if (typeof MFCardSelection !== 'undefined') {
      applySelection(slot, new Set(MFCardSelection.list()));
      if (unsub) unsub();
      unsub = MFCardSelection.subscribe(function (selectedSet) {
        applySelection(slot, selectedSet);
      });
    }
  }
```

- [ ] **Step 5: Verify safe DOM on edits**

Run: `grep -n "innerHTML" static/js/components/doc-card.js static/js/components/card-grid.js`

Expected: zero matches.

- [ ] **Step 6: Commit**

```bash
git add static/js/components/doc-card.js static/js/components/card-grid.js static/css/components.css
git commit -m "feat(ux): wire hover-checkbox + contextmenu event into doc-card

doc-card emits 'mf:doc-contextmenu' CustomEvent on right-click (controller
decides where the menu opens). Hover-checkbox slot toggles MFCardSelection
on click. card-grid subscribes to MFCardSelection and re-applies the
.mf-doc-card--selected class on every change. List-row variant unaffected
(scope: cards/compact density only — Plan 3 will add list-row selection
if needed)."
```

---

## Task 5: Bulk-action bar component

**Files:**
- Create: `static/js/components/bulk-bar.js`

Purple bar that appears at the top of a card grid when items are selected. Shows count + bulk actions: Download / Preview / Copy paths / Tag / Flag / Clear.

- [ ] **Step 1: Create the component**

Create `static/js/components/bulk-bar.js`:

```javascript
/* Bulk-action bar that surfaces when MFCardSelection has any items.
 * Spec §4 (folder browse + bulk).
 *
 * Usage:
 *   var bb = MFBulkBar.create({
 *     onAction: function(action, ids) { ... }   // 'download' | 'preview' | 'copy-paths' | 'tag' | 'flag' | 'clear'
 *   });
 *   bb.mount(slot);     // attaches listeners + initial render (hidden if empty)
 *   bb.unmount();
 *
 * Hidden by display:none when selection is empty; renders + slides in
 * when at least one item is selected.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var ACTIONS = [
    { id: 'download',   label: 'Download selected', solid: true },
    { id: 'preview',    label: 'Preview' },
    { id: 'copy-paths', label: 'Copy paths' },
    { id: 'tag',        label: 'Tag …' },
    { id: 'flag',       label: 'Flag for review' },
    { id: 'clear',      label: 'Clear' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function create(opts) {
    var onAction = (opts && opts.onAction) || function () {};
    var root = el('div', 'mf-bulk-bar');
    root.style.display = 'none';

    var left = el('div', 'mf-bulk-bar__left');
    var check = el('div', 'mf-bulk-bar__check');
    check.textContent = '0';
    left.appendChild(check);
    var text = el('span'); text.textContent = '0 files selected';
    left.appendChild(text);
    root.appendChild(left);

    var right = el('div', 'mf-bulk-bar__right');
    ACTIONS.forEach(function (a) {
      var b = el('button', 'mf-bulk-bar__btn' + (a.solid ? ' mf-bulk-bar__btn--solid' : ''));
      b.type = 'button';
      b.textContent = a.label;
      b.setAttribute('data-action', a.id);
      b.addEventListener('click', function () {
        var ids = MFCardSelection.list();
        if (a.id === 'clear') {
          MFCardSelection.clear();
        } else {
          try { onAction(a.id, ids); } catch (e) { console.error(e); }
        }
      });
      right.appendChild(b);
    });
    root.appendChild(right);

    var unsub = null;

    function update(selectedSet) {
      var n = selectedSet.size;
      if (n === 0) {
        root.style.display = 'none';
      } else {
        root.style.display = 'flex';
        check.textContent = String(n);
        text.textContent = n + (n === 1 ? ' file selected' : ' files selected');
      }
    }

    function mount(slot) {
      slot.appendChild(root);
      unsub = MFCardSelection.subscribe(update);
      update(new Set(MFCardSelection.list()));
    }

    function unmount() {
      if (unsub) { unsub(); unsub = null; }
      if (root.parentNode) root.parentNode.removeChild(root);
    }

    return { mount: mount, unmount: unmount };
  }

  global.MFBulkBar = { create: create };
})(window);
```

- [ ] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === bulk action bar === */
.mf-bulk-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--mf-color-accent);
  color: #fff;
  padding: 0.7rem 1rem;
  border-radius: var(--mf-radius-input);
  margin-bottom: 1rem;
  font-size: 0.88rem;
  font-family: var(--mf-font-sans);
}
.mf-bulk-bar__left {
  display: flex;
  align-items: center;
  gap: 0.7rem;
}
.mf-bulk-bar__check {
  width: 20px;
  height: 20px;
  border-radius: 5px;
  background: rgba(255,255,255,0.95);
  color: var(--mf-color-accent);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 0.78rem;
}
.mf-bulk-bar__right { display: flex; gap: 0.45rem; flex-wrap: wrap; }
.mf-bulk-bar__btn {
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.3);
  color: #fff;
  padding: 0.4rem 0.85rem;
  border-radius: 7px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
}
.mf-bulk-bar__btn:hover { background: rgba(255,255,255,0.25); }
.mf-bulk-bar__btn--solid {
  background: #fff;
  color: var(--mf-color-accent);
  border-color: #fff;
  font-weight: 600;
}
```

- [ ] **Step 3: Commit**

```bash
git add static/js/components/bulk-bar.js static/css/components.css
git commit -m "feat(ux): bulk action bar — appears when selection non-empty

Shows count badge + 5 actions (Download / Preview / Copy paths / Tag /
Flag) + Clear. Subscribes to MFCardSelection — display:none when 0
selected, slides into flex layout when 1+. Clear button calls
MFCardSelection.clear() directly; other actions delegate to onAction
callback with the ID list. Safe DOM throughout."
```

---

## Task 6: Folder-browse component (the integration target)

**Files:**
- Create: `static/js/components/folder-browse.js`

Single-page mountable component that demonstrates all the interactions together: breadcrumb + folder header (icon + path + stats + Pin / Download-all + density toggle) + bulk-bar + card-grid. Plan 4 will mount this on a real `/folder/<path>` route; for now it lives on dev-chrome.

- [ ] **Step 1: Create the component**

Create `static/js/components/folder-browse.js`:

```javascript
/* Folder browse — breadcrumb + header + bulk bar + card grid.
 * Spec §4. Single-page mount that wires Plan 2A's grid + Plan 2B's
 * interactions together.
 *
 * Usage:
 *   MFFolderBrowse.mount(slot, {
 *     path: '/local-46/contracts',
 *     stats: { count: 428, addedToday: 3, lastScanned: '4 min ago' },
 *     docs: [...],
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

  function buildBreadcrumb(path) {
    var crumb = el('div', 'mf-folder__crumb');
    var segs = path.split('/').filter(Boolean);
    var home = el('a', 'mf-folder__crumb-seg');
    home.textContent = 'Home';
    home.href = '/';
    crumb.appendChild(home);
    var acc = '';
    segs.forEach(function (s, i) {
      var sep = el('span', 'mf-folder__crumb-sep');
      sep.textContent = '/';
      crumb.appendChild(sep);
      acc += '/' + s;
      if (i === segs.length - 1) {
        var here = el('span', 'mf-folder__crumb-here');
        here.textContent = s;
        crumb.appendChild(here);
      } else {
        var seg = el('a', 'mf-folder__crumb-seg');
        seg.href = '/folder' + acc;
        seg.textContent = s;
        crumb.appendChild(seg);
      }
    });
    return crumb;
  }

  function buildHeader(path, stats) {
    var h = el('div', 'mf-folder__header');
    var leftCol = el('div');
    var icon = el('div', 'mf-folder__icon-lg');
    icon.textContent = '⛬';   // dingbat folder-ish glyph
    leftCol.appendChild(icon);
    var title = el('h1', 'mf-folder__title');
    title.textContent = path;
    leftCol.appendChild(title);
    var s = el('div', 'mf-folder__stats');
    var parts = [];
    if (stats && typeof stats.count === 'number') parts.push(stats.count.toLocaleString() + ' documents');
    if (stats && typeof stats.addedToday === 'number') parts.push(stats.addedToday + ' added today');
    if (stats && stats.lastScanned) parts.push('last scanned ' + stats.lastScanned);
    s.textContent = parts.join(' · ');
    leftCol.appendChild(s);
    h.appendChild(leftCol);

    var right = el('div', 'mf-folder__header-actions');
    var densitySlot = el('div'); densitySlot.setAttribute('data-mf-slot', 'density-toggle');
    right.appendChild(densitySlot);
    var pin = el('button', 'mf-pill mf-pill--outline mf-pill--sm');
    pin.type = 'button'; pin.textContent = 'Pin folder';
    right.appendChild(pin);
    var dl = el('button', 'mf-pill mf-pill--outline mf-pill--sm');
    dl.type = 'button'; dl.textContent = 'Download all (zip)';
    right.appendChild(dl);
    h.appendChild(right);

    return h;
  }

  function mount(slot, opts) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.classList.add('mf-folder');

    var path = (opts && opts.path) || '/';
    var stats = (opts && opts.stats) || {};
    var docs = (opts && opts.docs) || [];

    slot.appendChild(buildBreadcrumb(path));
    slot.appendChild(buildHeader(path, stats));

    // Bulk action bar (hidden until selection)
    var bbSlot = el('div');
    slot.appendChild(bbSlot);

    // Card grid container
    var gridSlot = el('div');
    slot.appendChild(gridSlot);

    // Mount density toggle into header slot
    var densitySlot = slot.querySelector('[data-mf-slot="density-toggle"]');
    MFDensityToggle.mount(densitySlot);

    // Mount bulk bar (auto-hides when empty)
    var bb = MFBulkBar.create({
      onAction: function (action, ids) {
        console.log('bulk:', action, ids);
      },
    });
    bb.mount(bbSlot);

    // Render grid in current density; resubscribe to density changes
    function render() {
      var density = MFPrefs.get('density') || 'cards';
      MFCardGrid.mount(gridSlot, docs, density);
    }
    render();
    var unsub = MFPrefs.subscribe('density', render);

    return function unmount() {
      unsub();
      bb.unmount();
      while (slot.firstChild) slot.removeChild(slot.firstChild);
    };
  }

  global.MFFolderBrowse = { mount: mount };
})(window);
```

- [ ] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === folder browse === */
.mf-folder { font-family: var(--mf-font-sans); }
.mf-folder__crumb {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--mf-color-accent);
  font-size: 0.84rem;
  font-weight: 500;
  margin-bottom: 0.7rem;
  flex-wrap: wrap;
}
.mf-folder__crumb-seg { color: inherit; text-decoration: none; cursor: pointer; }
.mf-folder__crumb-seg:hover { text-decoration: underline; }
.mf-folder__crumb-sep { color: var(--mf-color-text-fainter); font-weight: 400; }
.mf-folder__crumb-here { color: var(--mf-color-text); font-weight: 500; }

.mf-folder__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 1.2rem;
  gap: 1rem;
  flex-wrap: wrap;
}
.mf-folder__icon-lg {
  width: 48px; height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--mf-color-accent-tint), var(--mf-color-accent-border));
  display: flex; align-items: center; justify-content: center;
  color: var(--mf-color-accent);
  font-size: 1.4rem;
  margin-bottom: 0.7rem;
}
.mf-folder__title {
  font-size: 1.85rem;
  letter-spacing: -0.018em;
  font-weight: 700;
  color: var(--mf-color-text);
  margin: 0 0 0.2rem;
}
.mf-folder__stats { color: var(--mf-color-text-faint); font-size: 0.92rem; }
.mf-folder__header-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}
```

- [ ] **Step 3: Commit**

```bash
git add static/js/components/folder-browse.js static/css/components.css
git commit -m "feat(ux): folder-browse component — breadcrumb + header + grid + bulk

Single-page mount that wires breadcrumb (Home / segments / current),
folder header (icon + path + stats + density toggle + Pin /
Download-all), bulk-bar (auto-shows on selection), and card-grid
(density-aware via MFPrefs subscribe).

Plan 4 will mount this on a real /folder/<path> route. For now it's
the integration target on dev-chrome to demonstrate Plans 2A + 2B
together. Safe DOM throughout."
```

---

## Task 7: Wire dev-chrome to demonstrate everything

**Files:**
- Modify: `static/dev-chrome.html` — load new scripts, add a folder-browse demo section
- Modify: `static/dev-chrome.js` — wire the hover preview, context menu, folder-browse demo

- [ ] **Step 1: Update dev-chrome.html**

Add the new script tags before `dev-chrome.js`:

```html
  <script src="/static/js/components/hover-preview.js"></script>
  <script src="/static/js/components/context-menu.js"></script>
  <script src="/static/js/components/card-selection.js"></script>
  <script src="/static/js/components/bulk-bar.js"></script>
  <script src="/static/js/components/folder-browse.js"></script>
```

Append a folder-browse demo section after the existing card-grid demo:

```html
  <div class="dev-banner">
    <h2 style="font-size: 1.05rem; margin: 1.4rem 0 0.4rem; color: #0a0a0a">Folder browse demo</h2>
    <p style="color: #888; font-size: 0.84rem; margin-bottom: 1rem">Right-click any card for context menu. Hover for preview popover. Click any card's checkbox (visible on hover) to select; bulk bar appears. Density toggle changes layout.</p>
    <div id="mf-folder-demo"></div>
  </div>
```

- [ ] **Step 2: Append wiring to dev-chrome.js**

Append to `static/dev-chrome.js` (inside the existing IIFE, before the closing `})();`):

```javascript
  // === Folder browse demo (Plan 2B integration) ===
  var hp = MFHoverPreview.create({
    onAction: function (action, doc) { console.log('hover-action:', action, doc.id); },
  });
  var cm = MFContextMenu.create({
    onAction: function (action, doc) { console.log('ctx-action:', action, doc.id); },
  });

  // Listen for the contextmenu custom event from any card.
  document.addEventListener('mf:doc-contextmenu', function (ev) {
    cm.openAt(ev.detail.x, ev.detail.y, ev.detail.doc);
  });

  // Arm hover preview on every card after the folder browse renders.
  // We re-arm on density changes since cards are re-created.
  var folderUnmount = MFFolderBrowse.mount(
    document.getElementById('mf-folder-demo'),
    {
      path: '/local-46/contracts',
      stats: { count: 428, addedToday: 3, lastScanned: '4 min ago' },
      docs: MFSampleDocs.slice(0, 12),
    }
  );

  function rearmHovers() {
    var cards = document.querySelectorAll('#mf-folder-demo .mf-doc-card');
    cards.forEach(function (card) {
      var docId = card.getAttribute('data-doc-id');
      var doc = MFSampleDocs.find(function (d) { return d.id === docId; });
      if (doc) hp.armOn(card, doc);
    });
  }
  rearmHovers();
  MFPrefs.subscribe('density', function () {
    requestAnimationFrame(rearmHovers);
  });
```

- [ ] **Step 3: Smoke verify the full integration**

```bash
docker-compose up -d
```

Visit `http://localhost:8000/static/dev-chrome.html`. Expected:

1. Existing nav + chrome demos still work.
2. Existing card grid demo still works.
3. **New folder-browse section** below — breadcrumb, folder title, stats, density toggle, sample card grid.
4. **Hover any card for ~400ms** → preview popover slides in to the right of the card with title, path, meta, AI summary (if doc has one), and 4 action buttons. Move mouse away → popover dismisses.
5. **Right-click any card** → context menu opens at cursor with View / Export / AI / Pin / Flag sections + Advanced expander row at bottom. Click `Advanced ▾` → expander rotates and reveals Markdown actions.
6. **Hover a card and click the checkbox (top-left)** → card gets a purple ring and persistent checkbox. Bulk bar slides in at top of folder section showing "1 file selected" + actions. Select more → count updates. Click "Clear" → bar disappears.
7. **Switch density to Compact or List** → cards re-render, hover preview re-arms, selection state persists across re-render.
8. **Press Esc** during a context menu open → closes.
9. **Click outside** any popover → closes.
10. **Network tab:** `POST /api/telemetry` for `ui.hover_preview_shown`, `ui.context_menu_action`, `ui.density_toggle`.

If anything reads wrong visually, cross-check against `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/card-interactions.html`.

- [ ] **Step 4: Commit**

```bash
git add static/dev-chrome.html static/dev-chrome.js
git commit -m "feat(ux): dev-chrome integrates Plan 2B (hover + ctx + selection + folder)

Folder browse demo section wires the full Plan 2A+2B flow:
- MFHoverPreview armed on every card (re-armed on density change)
- MFContextMenu listens for the bubbled mf:doc-contextmenu event
- MFCardSelection drives the hover-checkboxes + .mf-doc-card--selected
  + the bulk bar visibility
- MFBulkBar mounts at the top of the folder section, auto-shows on
  selection, Clear empties it
- MFFolderBrowse owns the layout (breadcrumb + header + bulk slot +
  grid slot + density-aware re-render)

Plan 4 will mount the folder browse on a real /folder/<path> route
and replace MFSampleDocs with /api/folders responses."
```

---

## Acceptance check (run before declaring this plan complete)

- [ ] `git log --oneline | head -10` shows 6 task commits in order, on top of Plan 2A
- [ ] `grep -rn "innerHTML" static/js/components/hover-preview.js static/js/components/context-menu.js static/js/components/card-selection.js static/js/components/bulk-bar.js static/js/components/folder-browse.js` — zero matches
- [ ] `docker-compose up -d` succeeds, no console errors
- [ ] All 10 smoke checks from Task 7 Step 3 pass
- [ ] Hover preview appears after ~400ms (not instantly, not slower than ~600ms)
- [ ] Context menu Advanced expander toggles inline section visibility
- [ ] Setting `MFPrefs.set('advanced_actions_inline', true)` in console → next right-click shows Markdown items inline (no expander needed)
- [ ] Selecting 3 cards → bulk bar reads "3 files selected"; Clear empties

Once all green, **Plan 2B is done**. Next plan: `2026-04-28-ux-overhaul-search-as-home.md` (Plan 3 — Search-as-home page with three layout modes).

---

## Self-review

**Spec coverage:**
- §4 (cards: hover preview, right-click menu, multi-select, folder browse): ✓ Tasks 1-7
- §9 (power-user gate via Advanced expander honoring `advanced_actions_inline`): ✓ Task 2
- §10 (preferences: `advanced_actions_inline` consumed): ✓ Task 2
- §13 (telemetry: `ui.hover_preview_shown`, `ui.context_menu_action`): ✓ Tasks 1, 2

**Spec gaps for this plan (deferred to later plans):**
- §3 (Search-as-home page rendering, 3 layout modes): Plan 3
- §5 (Activity dashboard): Plan 4
- §7 (Settings detail pages): Plans 5–7
- §8 (cost cap drill-down): Plan 7

**Placeholder scan:** No TODOs. Every task has runnable code blocks.

**Type / API consistency:**
- All popovers use `body-mounted + click-outside + Esc` pattern (consistent with Plan 1C avatar menu and layout popover)
- Custom event name `mf:doc-contextmenu` namespaced consistently
- All components expose `mount(slot)` / `unmount()` (component) or `create(opts)` / `openAt()` / `close()` (popover) — same patterns as Plan 1C
- `MFCardSelection` API consistent: `toggle / set / clear / has / size / list / subscribe`

**Safe-DOM verification (mandatory final scan):**

```
grep -rn "innerHTML" static/js/components/*.js static/dev-chrome.js
```

Expected: empty. The whole UX overhaul rejects `innerHTML` with template literals.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-card-interactions.md`.

Sized for: 6 implementer dispatches + 6 spec reviews + 6 code quality reviews ≈ 18 subagent calls.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
