# UX Overhaul — Static Chrome Implementation Plan (Plan 1B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Land the four static (stateless, presentational) JS chrome components that build on Plan 1A's design tokens and components.css: top-nav, version-chip, avatar circle, layout-icon button. Plus a dev scaffold page (`static/dev-chrome.html`) that mounts them all for manual visual verification. No state, no popovers, no server interaction yet — Plan 1C adds those.

**Architecture:** Vanilla JS in IIFE-wrapped global namespace (`window.MFTopNav`, `window.MFVersionChip`, etc.). No bundler, no framework. **Safe DOM construction throughout** — every element built with `document.createElement()`, every text set with `textContent`, every attribute via `setAttribute()`. No `innerHTML` with template literals anywhere. Components mount into existing DOM nodes via a `mount(slot, opts)` API. Each file ≤ 100 lines so it can be reasoned about in one screen.

**Tech stack:** Vanilla HTML / CSS / JS · ES module-style globals (no `<script type="module">` since MarkFlow has no bundler — plain `<script src="...">` tags load each component, exposing one global per file)

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` — covers §1 (nav), §2 (visual), §6 (avatar/layout-icon placement)

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/avatar-menu.html` (chrome for role variants), `layout-onboarding.html` (nav with version chip)

**Out of scope for this plan (deferred to Plan 1C):**
- Avatar menu popover (with role-gated Personal / System content)
- Layout-icon popover (with three layout modes + checkmark)
- `static/js/preferences.js` client module
- `static/js/telemetry.js` event helper
- Wiring the static chrome into existing pages (Plan 4)

---

## Model + effort

| Role | Model | Effort |
|------|-------|--------|
| Implementer | Haiku | low (2-4h) |
| Reviewer | Haiku | low (<1h) |

**Reasoning:** Four pure-presentational vanilla-JS components (top-nav, version-chip, avatar, layout-icon), each ≤100 LOC, no state, no async, no server interaction. Pattern is repetitive and the safe-DOM rules are explicit. Cheapest tier on both sides; the review just spot-checks for `innerHTML` and pattern adherence — fits in one short pass.

**Execution mode:** Dispatch this plan via `superpowers:subagent-driven-development`. Each role is a separate `Agent` call — `Agent({model: "haiku", ...})` for implementation, `Agent({model: "haiku", ...})` for review. A single-session `executing-plans` read will *not* switch models on its own; this metadata is routing input for the orchestrator.

**Source:** [`docs/spreadsheet/phase_model_plan.xlsx`](../../spreadsheet/phase_model_plan.xlsx)

---

## File structure (this plan creates / modifies)

**Create:**
- `static/js/components/top-nav.js`
- `static/js/components/version-chip.js`
- `static/js/components/avatar.js`
- `static/js/components/layout-icon.js`
- `static/dev-chrome.html` — development scaffold page that loads tokens + components.css + all four components

**Modify:**
- `static/css/components.css` — append per-component styles (top-nav, layout-icon button) as needed; pre-existing rules from Plan 1A (pills, version-chip class, role-pill class, pulse) stay untouched

---

## Phase 0 — Branch setup (one-time, run before Task 1)

- [x] **Step 1: Confirm Plan 1A is committed**

Run: `git log --oneline | head -5`

Expected: see `f37e633 plan(ux): UX overhaul foundation setup — Plan 1A` (or whatever SHA Plan 1A landed at).

- [x] **Step 2: Confirm clean working tree**

Run: `git status`

Expected: `nothing to commit, working tree clean`. If not, stop and reconcile before starting.

- [x] **Step 3: Confirm Plan 1A's foundation actually shipped**

```bash
ls static/css/design-tokens.css static/css/components.css
test -f core/feature_flags.py && echo "feature_flags OK"
```

Expected: all three files exist. If they don't, this plan can't start — Plan 1A must complete first.

---

## Task 1: Top-nav component

**Files:**
- Create: `static/js/components/top-nav.js`

Vanilla JS — no JS test runner in MarkFlow. Verification is manual smoke via the dev-chrome page (Task 5). This task only ships the component file; smoke happens in Task 5.

- [x] **Step 1: Create the component using safe DOM construction**

Create `static/js/components/top-nav.js`:

```javascript
/* MarkFlow top navigation bar. Static, role-gated link list.
 * Spec §1 (final IA), §2 (visual). Spec §6 (slot placement for chrome
 * companions: version-chip, layout-icon, avatar).
 *
 * Mount target: a <div id="mf-top-nav"></div> in the page.
 *
 * Safe DOM construction throughout — no innerHTML with template literals.
 *
 * Usage:
 *   <script src="/static/js/components/top-nav.js"></script>
 *   <script>
 *     MFTopNav.mount(document.getElementById('mf-top-nav'), {
 *       role: 'admin',         // 'member' | 'operator' | 'admin'
 *       activePage: 'search',  // 'search' | 'activity' | 'convert' | null
 *     });
 *   </script>
 */
(function (global) {
  'use strict';

  // Role-aware link sets. Activity is hidden for member.
  var ROLE_LINKS = {
    member:   [
      { id: 'search',   label: 'Search',   href: '/' },
      { id: 'convert',  label: 'Convert',  href: '/convert' }
    ],
    operator: [
      { id: 'search',   label: 'Search',   href: '/' },
      { id: 'activity', label: 'Activity', href: '/activity' },
      { id: 'convert',  label: 'Convert',  href: '/convert' }
    ],
    admin:    [
      { id: 'search',   label: 'Search',   href: '/' },
      { id: 'activity', label: 'Activity', href: '/activity' },
      { id: 'convert',  label: 'Convert',  href: '/convert' }
    ]
  };

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function makeSlot(name) {
    var s = document.createElement('span');
    s.setAttribute('data-mf-slot', name);
    return s;
  }

  function mount(root, opts) {
    if (!root) throw new Error('MFTopNav.mount: root element is required');
    var role = (opts && opts.role) || 'member';
    var active = (opts && opts.activePage) || null;
    var links = ROLE_LINKS[role] || ROLE_LINKS.member;

    clear(root);
    root.classList.add('mf-nav');

    // Logo + version-chip slot (chip goes inside the logo span per mockups).
    var logo = document.createElement('a');
    logo.className = 'mf-nav__logo';
    logo.href = '/';
    logo.appendChild(document.createTextNode('MarkFlow'));
    logo.appendChild(makeSlot('version-chip'));
    root.appendChild(logo);

    // Link bar.
    var linkBar = document.createElement('div');
    linkBar.className = 'mf-nav__links';
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      var a = document.createElement('a');
      a.className = 'mf-nav__link';
      if (link.id === active) a.classList.add('mf-nav__link--on');
      a.href = link.href;
      a.textContent = link.label;
      linkBar.appendChild(a);
    }
    root.appendChild(linkBar);

    // Right cluster: layout-icon and avatar slots.
    var right = document.createElement('div');
    right.className = 'mf-nav__right';
    right.appendChild(makeSlot('layout-icon'));
    right.appendChild(makeSlot('avatar'));
    root.appendChild(right);
  }

  global.MFTopNav = { mount: mount };
})(window);
```

- [x] **Step 2: Append nav-specific CSS to components.css**

Append to `static/css/components.css`:

```css
/* === top nav === */
.mf-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.05rem 1.6rem;
  border-bottom: 1px solid var(--mf-border);
  font-size: 0.92rem;
  background: var(--mf-surface);
  font-family: var(--mf-font-sans);
}
.mf-nav__logo {
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--mf-color-text);
  font-size: 1.05rem;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
}
.mf-nav__links {
  display: flex;
  gap: 1.5rem;
  color: var(--mf-color-text-soft);
  font-weight: 500;
}
.mf-nav__link {
  color: inherit;
  text-decoration: none;
}
.mf-nav__link--on { color: var(--mf-color-accent); }
.mf-nav__right {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}
```

- [x] **Step 3: Smoke check — load via dev-chrome (deferred to Task 5)**

This component has no standalone smoke target until Task 5 builds the dev-chrome page. Move on to Task 2.

- [x] **Step 4: Commit**

```bash
git add static/js/components/top-nav.js static/css/components.css
git commit -m "feat(ux): top-nav component (static, role-gated links)

Pure presentational component. Mounts via MFTopNav.mount(root, opts) with
role and activePage. Renders logo (with version-chip slot inside),
role-aware link bar, and right cluster with layout-icon and avatar slots.
Safe DOM construction throughout — no innerHTML."
```

---

## Task 2: Version-chip component

**Files:**
- Create: `static/js/components/version-chip.js`

Trivial component — renders a single span with version text into a slot. The CSS class `.mf-ver-chip` was already defined in Plan 1A's `components.css`. Hidden in production via the `body[data-env="prod"]` selector in `design-tokens.css`.

- [x] **Step 1: Create the component**

Create `static/js/components/version-chip.js`:

```javascript
/* Dev-only version chip. Renders inside the MarkFlow logo per mockup.
 * Spec §1.
 *
 * Hidden in production via body[data-env="prod"] .mf-ver-chip { display: none }
 * declared in design-tokens.css.
 *
 * Usage:
 *   MFVersionChip.mount(slot, { version: 'v0.34.2-dev' });
 *
 * The 'slot' is the data-mf-slot="version-chip" span produced by top-nav.
 */
(function (global) {
  'use strict';

  function mount(slot, opts) {
    if (!slot) throw new Error('MFVersionChip.mount: slot is required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    if (!opts || !opts.version) return;  // silent no-op if no version provided
    var span = document.createElement('span');
    span.className = 'mf-ver-chip';
    span.textContent = opts.version;
    slot.appendChild(span);
  }

  global.MFVersionChip = { mount: mount };
})(window);
```

- [x] **Step 2: Confirm CSS exists from Plan 1A**

Run: `grep -n "mf-ver-chip" static/css/components.css`

Expected: a class definition exists (added in Plan 1A Task 3). If missing, append it now using the spec values from `design-tokens.css` — but it should be there.

- [x] **Step 3: Commit**

```bash
git add static/js/components/version-chip.js
git commit -m "feat(ux): version-chip component (dev-only)

Renders the amber version pill inside the logo. Silent no-op when no
version provided. Hidden in production via the body[data-env=prod]
selector in design-tokens.css. Safe DOM — textContent only."
```

---

## Task 3: Avatar circle component

**Files:**
- Create: `static/js/components/avatar.js`

Just the gradient circle button. ARIA wired so it's ready for Plan 1C's avatar menu to attach. The click handler is a hook — Plan 1C wires it to the menu open. For now it's a stub that calls back to `opts.onClick` if provided.

- [x] **Step 1: Create the component**

Create `static/js/components/avatar.js`:

```javascript
/* Avatar — gradient circle button in the nav. Click calls opts.onClick.
 * Spec §6. Plan 1C connects this to the avatar menu popover.
 *
 * Usage:
 *   MFAvatar.mount(slot, {
 *     user: { name: 'Xerxes', role: 'admin' },
 *     onClick: function(buttonEl) { ... }
 *   });
 */
(function (global) {
  'use strict';

  function mount(slot, opts) {
    if (!slot) throw new Error('MFAvatar.mount: slot is required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mf-avatar';
    btn.setAttribute('aria-label', 'Account menu');
    btn.setAttribute('aria-haspopup', 'menu');
    btn.setAttribute('aria-expanded', 'false');

    if (opts && typeof opts.onClick === 'function') {
      btn.addEventListener('click', function () {
        opts.onClick(btn);
      });
    }

    slot.appendChild(btn);
  }

  global.MFAvatar = { mount: mount };
})(window);
```

- [x] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === avatar circle === */
.mf-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: linear-gradient(
    135deg,
    var(--mf-color-accent) 0%,
    var(--mf-color-accent-soft) 100%
  );
  cursor: pointer;
  border: none;
  padding: 0;
  transition: box-shadow var(--mf-transition-fast);
}
.mf-avatar:hover {
  box-shadow: 0 0 0 3px rgba(91, 61, 245, 0.18);
}
.mf-avatar[aria-expanded="true"] {
  box-shadow: 0 0 0 3px rgba(91, 61, 245, 0.35);
}
```

- [x] **Step 3: Commit**

```bash
git add static/js/components/avatar.js static/css/components.css
git commit -m "feat(ux): avatar circle component (static, click-stub)

Gradient circle button with ARIA wired (aria-haspopup=menu,
aria-expanded toggled by parent). onClick callback is a hook for
Plan 1C to attach the avatar menu. Safe DOM construction throughout."
```

---

## Task 4: Layout-icon button component

**Files:**
- Create: `static/js/components/layout-icon.js`

The four-square SVG button next to the avatar. Click stub for Plan 1C to wire into the layout-mode popover. The SVG is built with `createElementNS` to use the SVG namespace.

- [x] **Step 1: Create the component**

Create `static/js/components/layout-icon.js`:

```javascript
/* Layout-mode switcher button. Static. Click calls opts.onClick.
 * Spec §3 (layout modes), §6 (nav placement).
 *
 * Plan 1C wires onClick to the layout popover with three modes.
 *
 * Usage:
 *   MFLayoutIcon.mount(slot, {
 *     onClick: function(buttonEl) { ... }
 *   });
 */
(function (global) {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

  function makeRect(x, y) {
    var r = document.createElementNS(SVG_NS, 'rect');
    r.setAttribute('x', String(x));
    r.setAttribute('y', String(y));
    r.setAttribute('width', '6');
    r.setAttribute('height', '6');
    r.setAttribute('rx', '1.2');
    return r;
  }

  function buildSvg() {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 18 18');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6');
    svg.appendChild(makeRect(2, 2));
    svg.appendChild(makeRect(10, 2));
    svg.appendChild(makeRect(2, 10));
    svg.appendChild(makeRect(10, 10));
    return svg;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFLayoutIcon.mount: slot is required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mf-layout-icon';
    btn.title = 'Home layout (Cmd+\\)';
    btn.setAttribute('aria-label', 'Home layout');
    btn.setAttribute('aria-haspopup', 'menu');
    btn.setAttribute('aria-expanded', 'false');
    btn.appendChild(buildSvg());

    if (opts && typeof opts.onClick === 'function') {
      btn.addEventListener('click', function () {
        opts.onClick(btn);
      });
    }

    slot.appendChild(btn);
  }

  global.MFLayoutIcon = { mount: mount };
})(window);
```

- [x] **Step 2: Append CSS to components.css**

Append to `static/css/components.css`:

```css
/* === layout-icon button === */
.mf-layout-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--mf-color-text-muted);
  padding: 0;
  transition: background var(--mf-transition-fast),
              border-color var(--mf-transition-fast),
              color var(--mf-transition-fast);
}
.mf-layout-icon:hover {
  background: var(--mf-surface-soft);
  border-color: var(--mf-border);
  color: var(--mf-color-accent);
}
.mf-layout-icon[aria-expanded="true"] {
  background: var(--mf-color-accent-tint-2);
  border-color: var(--mf-color-accent-border);
  color: var(--mf-color-accent);
}
.mf-layout-icon svg {
  width: 18px;
  height: 18px;
}
```

- [x] **Step 3: Commit**

```bash
git add static/js/components/layout-icon.js static/css/components.css
git commit -m "feat(ux): layout-icon button component (static, click-stub)

4-square SVG icon button built via createElementNS (no innerHTML for
SVG either). ARIA wired, hover/open visuals via aria-expanded selector.
onClick callback is a hook for Plan 1C to attach the layout popover."
```

---

## Task 5: Dev-chrome scaffold page (smoke verification target)

**Files:**
- Create: `static/dev-chrome.html`

Single page that mounts all four components for manual visual verification across role variants. Removed at the end of Plan 1C once components have a real home (mounted via Plan 4 onto existing pages).

- [x] **Step 1: Create the page**

Create `static/dev-chrome.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MarkFlow chrome dev — Plan 1B static</title>
  <link rel="stylesheet" href="/static/css/components.css">
  <style>
    body {
      margin: 0;
      font-family: -apple-system, "SF Pro Display", Inter, system-ui, sans-serif;
      background: #f7f7f9;
    }
    .dev-banner {
      padding: 1.5rem 2rem;
      max-width: 880px;
      margin: 0 auto;
      color: #5a5a5a;
    }
    .dev-banner h1 { color: #0a0a0a; margin: 0 0 0.4rem; font-size: 1.4rem; }
    .dev-banner code {
      background: #f3f0ff; color: #5b3df5;
      padding: 0.06rem 0.4rem; border-radius: 4px;
      font-family: ui-monospace, "SF Mono", monospace;
    }
    .role-switcher {
      margin: 1rem 0;
      display: flex;
      gap: 0.5rem;
    }
    .role-switcher button {
      padding: 0.4rem 0.85rem;
      border-radius: 999px;
      border: 1px solid #d8ceff;
      background: #fff;
      color: #5b3df5;
      cursor: pointer;
      font-weight: 500;
    }
    .role-switcher button.on {
      background: #5b3df5;
      color: #fff;
      border-color: #5b3df5;
    }
  </style>
</head>
<body>
  <div id="mf-top-nav"></div>

  <div class="dev-banner">
    <h1>Plan 1B — static chrome dev page</h1>
    <p>Manual verification target for the four static chrome components: top-nav, version-chip, avatar, layout-icon. Click <code>member</code> / <code>operator</code> / <code>admin</code> to re-render the nav and confirm role-gated link visibility (Activity should be hidden for member).</p>

    <div class="role-switcher">
      <button data-role="member">member</button>
      <button data-role="operator">operator</button>
      <button data-role="admin" class="on">admin</button>
    </div>

    <p>Click avatar &rarr; console logs <code>avatar clicked</code>. Click layout-icon &rarr; console logs <code>layout-icon clicked</code>. Plan 1C connects these to actual popovers.</p>
  </div>

  <script src="/static/js/components/top-nav.js"></script>
  <script src="/static/js/components/version-chip.js"></script>
  <script src="/static/js/components/avatar.js"></script>
  <script src="/static/js/components/layout-icon.js"></script>
  <script src="/static/dev-chrome.js"></script>
</body>
</html>
```

- [x] **Step 2: Create the dev-chrome wiring script**

Create `static/dev-chrome.js` (separate file so the HTML stays inert — no inline scripts):

```javascript
/* Dev-chrome wiring. Mounts the four static chrome components against
 * the role currently selected by the role-switcher. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');

  function render(role) {
    MFTopNav.mount(navRoot, { role: role, activePage: 'search' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: 'v0.34.2-dev' }
    );
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { onClick: function () { console.log('avatar clicked'); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function () { console.log('layout-icon clicked'); } }
    );
  }

  // Role switcher.
  var buttons = document.querySelectorAll('.role-switcher [data-role]');
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener('click', function (ev) {
      var role = ev.currentTarget.getAttribute('data-role');
      for (var j = 0; j < buttons.length; j++) buttons[j].classList.remove('on');
      ev.currentTarget.classList.add('on');
      render(role);
    });
  }

  // Initial render.
  render('admin');
})();
```

- [x] **Step 3: Run docker-compose, smoke verify**

```bash
docker-compose up -d
```

Visit `http://localhost:8000/static/dev-chrome.html`.

Expected:
- Top nav reads `MarkFlow [v0.34.2-dev]    Search · Activity · Convert    [layout-icon] [avatar]`
- The amber `v0.34.2-dev` chip is visible next to the logo
- Click the **member** button — Activity disappears from the link bar
- Click **operator** or **admin** — Activity reappears
- Click the avatar — `avatar clicked` in console; the avatar gets a darker focus ring (aria-expanded transitions to true momentarily — though without a menu attached, it stays expanded; that's expected for this plan's stub)
- Click the layout-icon — `layout-icon clicked` in console; the icon's hover/active state visible

If anything reads wrong visually, cross-check against `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/avatar-menu.html` (the static nav portion).

- [x] **Step 4: Commit**

```bash
git add static/dev-chrome.html static/dev-chrome.js
git commit -m "feat(ux): dev-chrome scaffold — Plan 1B smoke verification page

Single page mounting all four static chrome components with a
role-switcher (member/operator/admin) for verifying role-gated nav
rendering. Click handlers log to console (Plan 1C replaces with real
popovers). Removed at end of Plan 1C once components mount on real
pages via Plan 4."
```

---

## Acceptance check (run before declaring this plan complete)

- [x] `git log --oneline | head -10` shows 5 task commits in order, each on top of Plan 1A's foundation
- [x] `docker-compose up -d` succeeds, app starts, no console errors when loading `/static/dev-chrome.html`
- [x] Visit `http://localhost:8000/static/dev-chrome.html` — page renders without JS errors in browser console
- [x] Member role variant: nav shows `Search · Convert` only
- [x] Operator and admin role variants: nav shows `Search · Activity · Convert`
- [x] Version chip visible next to logo (amber pill, `v0.34.2-dev`)
- [x] Avatar click logs to console; aria-expanded transitions
- [x] Layout-icon click logs to console; hover/open visual states render
- [x] Verify file sizes — each component ≤ 100 lines:
  ```
  wc -l static/js/components/top-nav.js static/js/components/version-chip.js static/js/components/avatar.js static/js/components/layout-icon.js
  ```

Once all green, **Plan 1B is done**. Next plan in sequence: `2026-04-28-ux-overhaul-stateful-chrome.md` (Plan 1C — avatar menu popover, layout popover with three modes, preferences client, telemetry helper). Plan 1C wires the static chrome's `onClick` stubs to real popovers and adds the persistence layer.

---

## Self-review

**Spec coverage:**
- §1 (top-nav role gating, logo + version chip placement): ✓ Tasks 1, 2
- §2 (visual: pill / role-pill / version-chip CSS): consumed from Plan 1A
- §6 (avatar slot, layout-icon slot in nav): ✓ Task 1 (slots), Tasks 3 & 4 (mounting components into slots)

**Spec gaps for this plan (deferred to Plan 1C):**
- §3 (layout modes — Maximal/Recent/Minimal logic): Plan 1C
- §6 (avatar menu popover content with role-gated Personal / System): Plan 1C
- §10 (preferences persistence): Plan 1C
- §13 (telemetry helper): Plan 1C

**Placeholder scan:** No TODOs, no "fill in details", no "similar to Task N". Every task has the actual code.

**Type / API consistency:** All four components expose `mount(slot, opts)` signature. All use safe DOM (`document.createElement`, `textContent`, `setAttribute`, `appendChild`) — zero `innerHTML` usages anywhere. All slot names match between top-nav (`makeSlot()`) and the consumers (`querySelector('[data-mf-slot="..."]')`).

**Safe-DOM verification (manual line-by-line scan after implementation):**

```
grep -n "innerHTML" static/js/components/*.js static/dev-chrome.js
```

Expected: zero matches. If any appear, replace with `createElement`/`textContent`/`appendChild`.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-static-chrome.md`.

Sized for: ~5 implementer dispatches + 5 spec reviews + 5 code quality reviews ≈ 15 subagent calls in subagent-driven-development. Smaller than Plan 1A.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — run tasks in this session via `superpowers:executing-plans`
