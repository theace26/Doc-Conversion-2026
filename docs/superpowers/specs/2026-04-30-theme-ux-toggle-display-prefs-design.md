# Theme System, UX Toggle & Display Preferences — Design Spec

**Date:** 2026-04-30
**Status:** Approved, pending implementation
**Version target:** v0.37.0

---

## 1. Overview

Adds a full visual personalization system to MarkFlow:

- **UX toggle** — system-level and per-user control over the `ENABLE_NEW_UX` feature flag
- **Color themes** — 28 themes across 6 groups, designed for both Original and New UX chrome
- **Font picker** — 14 typeface choices (system + 13 Google Fonts)
- **Text scale** — 4 size steps independent of browser zoom
- All preferences persisted to `mf_user_prefs` (per-user) and `user_preferences` (system defaults)
- Default experience: **Nebula theme + New UX** — showcases the complementary color work and gradient card bands at their best

---

## 2. Architecture & Data Flow

### Approach: CSS custom properties via `data-*` attributes on `<html>`

Industry-standard pattern (GitHub, Linear, Vercel, Stripe, Notion, VS Code). The `<html>` element carries:

```html
<html data-theme="nebula" data-font="inter" data-text-scale="large" data-ux="new">
```

CSS attribute selectors in `design-themes.css` resolve the correct token values. No JavaScript required after initial load — changes are a single `setAttribute()` call.

### Zero-flash init (multi-page static HTML)

Since MarkFlow is a multi-page app (no SPA, no Jinja2 templating), a **synchronous inline script** runs in every page's `<head>` before stylesheets paint. It reads `localStorage` and applies `data-*` attrs immediately:

```html
<script>
(function(){
  var D = {theme:'nebula', font:'system', textScale:'default', useNewUx:true};
  var p = Object.assign({}, D, JSON.parse(localStorage.getItem('mf:preferences:v1')||'{}'));
  var h = document.documentElement;
  h.setAttribute('data-theme',      p.theme);
  h.setAttribute('data-font',       p.font);
  h.setAttribute('data-text-scale', p.textScale);
  h.setAttribute('data-ux',         p.useNewUx ? 'new' : 'orig');
})();
</script>
```

First-time visitors (empty `localStorage`) get the hardcoded defaults: Nebula + system font + default scale + new UX. No server round-trip needed; no flash of wrong theme.

`preferences.js` (existing) then loads, calls `/api/user-prefs`, updates `localStorage` and live `data-*` attrs via the existing `set()`/`subscribe()` pattern. Subsequent page loads read the warm cache.

---

## 3. UX Toggle — Three-Tier Lookup

Evaluated per-request by `is_new_ux_enabled_for(user_sub)` in `core/feature_flags.py`:

```
1. mf_user_prefs["use_new_ux"]          → user always wins (can always opt in or out)
2. ENABLE_NEW_UX env var                → env-level bypass (overrides system DB pref)
3. user_preferences["enable_new_ux"]    → system default (operator-set via Settings UI)
4. hardcoded default                    → False (old UX)
```

```python
async def is_new_ux_enabled_for(user_sub: str) -> bool:
    user_pref = await get_user_prefs(user_sub)
    if "use_new_ux" in user_pref:
        return user_pref["use_new_ux"]
    env_val = os.environ.get("ENABLE_NEW_UX", "").lower()
    if env_val in ("true", "false"):
        return env_val == "true"
    sys_pref = await get_preference("enable_new_ux")
    if sys_pref is not None:
        return sys_pref == "true"
    return False
```

The env var is an **env-level bypass** — it overrides the operator DB preference but does NOT prevent users from opting out via their own preference. The existing `is_new_ux_enabled()` (env-only, no `user_sub`) is kept for non-auth contexts.

---

## 4. Data Model

### `core/user_prefs.py` — SCHEMA_VER 1 → 2

New keys added to `DEFAULT_USER_PREFS`:

```python
DEFAULT_USER_PREFS = {
    # existing
    "layout":   "maximal",
    "density":  "cards",
    # new in v0.37.0
    "theme":      "nebula",
    "font":       "system",
    "text_scale": "default",
    "use_new_ux": True,
}
```

`SCHEMA_VER` bumps from `1` to `2`. Existing rows get the new keys automatically via the existing `merged = {**DEFAULT_USER_PREFS, **stored}` pattern in `get_user_prefs()`. No migration script required.

Validation additions:

```python
_ENUMS["theme"]      = {all 28 theme IDs}
_ENUMS["font"]       = {"system","inter","ibm-plex-sans","roboto","source-sans-3",
                         "lato","merriweather","jetbrains-mono","nunito",
                         "playfair-display","raleway","poppins","dm-sans","crimson-pro"}
_ENUMS["text_scale"] = {"small","default","large","xl"}
_BOOLS.add("use_new_ux")
```

### `core/db/preferences.py` — system-level

New key: `enable_new_ux` (string `"true"`/`"false"`, consistent with existing preference format). Set via Settings > Appearance (operator role required).

---

## 5. CSS Architecture

### `static/css/design-tokens.css` (existing — minimal additions)

Two new root tokens; all text-size tokens updated to use the scale multiplier:

```css
:root {
  --mf-text-scale:   1;
  --mf-font-family:  system-ui, -apple-system, BlinkMacSystemFont, sans-serif;

  --mf-text-body:    calc(0.94rem * var(--mf-text-scale));
  --mf-text-sm:      calc(0.81rem * var(--mf-text-scale));
  --mf-text-lg:      calc(1.06rem * var(--mf-text-scale));
  --mf-text-xl:      calc(1.25rem * var(--mf-text-scale));
  --mf-text-2xl:     calc(1.5rem  * var(--mf-text-scale));

  font-family: var(--mf-font-family);
}
```

### `static/css/design-themes.css` (new file, ~700 lines)

Loaded after `design-tokens.css`, before `components.css`. Contains:

**Theme blocks** — attribute selectors that override only the tokens that differ from base:

```css
[data-theme="nebula"] {
  --mf-bg-page:             #05060e;
  --mf-bg-surface:          #0d0f1c;
  --mf-bg-card:             #111328;
  --mf-color-border:        #1e2240;
  --mf-color-accent:        #7c3aed;
  --mf-color-btn-gradient:  linear-gradient(135deg, #7c3aed, #a855f7);
  --mf-text-primary:        #f5f5ff;
  --mf-text-secondary:      #a0a8d0;
  --mf-text-muted:          #5c6494;
  --mf-shadow-card:         0 2px 12px rgba(124,58,237,0.18);
}
```

**Font blocks:**

```css
[data-font="inter"]          { --mf-font-family: 'Inter', system-ui, sans-serif; }
[data-font="ibm-plex-sans"]  { --mf-font-family: 'IBM Plex Sans', system-ui, sans-serif; }
[data-font="roboto"]         { --mf-font-family: 'Roboto', system-ui, sans-serif; }
[data-font="source-sans-3"]  { --mf-font-family: 'Source Sans 3', system-ui, sans-serif; }
[data-font="lato"]           { --mf-font-family: 'Lato', system-ui, sans-serif; }
[data-font="merriweather"]   { --mf-font-family: 'Merriweather', Georgia, serif; }
[data-font="jetbrains-mono"] { --mf-font-family: 'JetBrains Mono', 'Courier New', monospace; }
[data-font="nunito"]         { --mf-font-family: 'Nunito', system-ui, sans-serif; }
[data-font="playfair-display"]{ --mf-font-family: 'Playfair Display', Georgia, serif; }
[data-font="raleway"]        { --mf-font-family: 'Raleway', system-ui, sans-serif; }
[data-font="poppins"]        { --mf-font-family: 'Poppins', system-ui, sans-serif; }
[data-font="dm-sans"]        { --mf-font-family: 'DM Sans', system-ui, sans-serif; }
[data-font="crimson-pro"]    { --mf-font-family: 'Crimson Pro', Georgia, serif; }
```

**Text scale blocks:**

```css
[data-text-scale="small"]  { --mf-text-scale: 0.84; }
/* default (1.0) is :root — no override needed */
[data-text-scale="large"]  { --mf-text-scale: 1.18; }
[data-text-scale="xl"]     { --mf-text-scale: 1.36; }
```

Components never reference themes directly — they use `var(--mf-text-body)`, `var(--mf-color-accent)`, etc., which resolve correctly regardless of which theme is active.

---

## 6. Theme Catalog — 28 Themes

### Group A: Original UX (8 themes)
Tuned for the pre-overhaul chrome (top nav-bar, sidebar layout).

| ID | Label | Character |
|----|-------|-----------|
| `classic-light` | Classic Light | Off-white bg, violet accent — default Original UX |
| `classic-dark` | Classic Dark | Near-black bg, violet accent |
| `cobalt` | Cobalt | Deep navy bg, gold accent |
| `sage` | Sage | Warm cream bg, forest green accent |
| `slate` | Slate | Medium-gray bg, copper accent |
| `crimson` | Crimson | Deep burgundy bg, silver accent |
| `sandstone` | Sandstone | Warm tan bg, rust accent |
| `graphite` | Graphite | Charcoal bg, teal accent |

### Group B: New UX (8 themes)
Tuned for new-UX chrome (search-as-home, avatar menu). Complementary colors chosen so gradient card bands (PDF red, DOCX blue, PPTX orange, XLSX green) always pop.

| ID | Label | Character |
|----|-------|-----------|
| `nebula` | Nebula | Deep space purple — **default** |
| `aurora` | Aurora | Northern lights: dark teal bg, green/cyan accent |
| `cobalt-new` | Cobalt | Deep navy, amber accent — New UX counterpart |
| `rose-quartz` | Rose Quartz | Dusty rose bg, gold accent |
| `midnight-slate` | Midnight Slate | Cool dark gray, electric blue accent |
| `forest` | Forest | Deep hunter green, warm orange accent |
| `obsidian` | Obsidian | True black, bright magenta accent |
| `dusk` | Dusk | Warm dark brown, sky blue accent |

### Group C: High Contrast (4 themes, 2 per UX style)

| ID | Label | Notes |
|----|-------|-------|
| `hc-light` | HC Light (Orig) | Pure white bg, pure black text, WCAG AAA |
| `hc-dark` | HC Dark (Orig) | Pure black bg, pure white text, WCAG AAA |
| `hc-light-new` | HC Light (New) | Same contrast targets, new UX chrome |
| `hc-dark-new` | HC Dark (New) | Same contrast targets, new UX chrome |

### Group D: Pastel (4 themes, 2 per UX style)

| ID | Label | Character |
|----|-------|-----------|
| `pastel-lavender` | Pastel Lavender (Orig) | Soft lilac bg, rose accent |
| `pastel-mint` | Pastel Mint (Orig) | Pale mint bg, coral accent |
| `pastel-lavender-new` | Pastel Lavender (New) | Same palette, new UX chrome |
| `pastel-mint-new` | Pastel Mint (New) | Same palette, new UX chrome |

### Group E: Seasonal — Original UX (4 themes)

| ID | Label | Character |
|----|-------|-----------|
| `spring-orig` | Spring (Orig) | Cherry blossom pink bg, fresh green accent |
| `summer-orig` | Summer (Orig) | Sandy cream bg, ocean teal accent |
| `fall-orig` | Fall (Orig) | Warm amber bg, burnt sienna accent |
| `winter-orig` | Winter (Orig) | Icy light blue bg, deep navy accent |

### Group F: Seasonal — New UX (4 themes)

| ID | Label | Character |
|----|-------|-----------|
| `spring-new` | Spring (New) | Deeper green bg, blossom pink accent |
| `summer-new` | Summer (New) | Deep ocean bg, coral accent |
| `fall-new` | Fall (New) | Deep mahogany bg, harvest gold accent |
| `winter-new` | Winter (New) | Deep midnight blue bg, ice white accent |

---

## 7. UX-Mode Theme Migration

When a user switches UX mode, the active theme auto-migrates to its counterpart:

```javascript
var COUNTERPART = {
  'classic-light':       'nebula',           // orig → default new UX on first switch
  'classic-dark':        'nebula',
  'cobalt':              'cobalt-new',
  'sage':                'forest',
  'slate':               'midnight-slate',
  'crimson':             'rose-quartz',
  'sandstone':           'dusk',
  'graphite':            'obsidian',
  'nebula':              'classic-dark',
  'aurora':              'classic-light',
  'cobalt-new':          'cobalt',
  'rose-quartz':         'crimson',
  'midnight-slate':      'slate',
  'forest':              'sage',
  'obsidian':            'graphite',
  'dusk':                'sandstone',
  'hc-light':            'hc-light-new',
  'hc-dark':             'hc-dark-new',
  'hc-light-new':        'hc-light',
  'hc-dark-new':         'hc-dark',
  'pastel-lavender':     'pastel-lavender-new',
  'pastel-mint':         'pastel-mint-new',
  'pastel-lavender-new': 'pastel-lavender',
  'pastel-mint-new':     'pastel-mint',
  'spring-orig':         'spring-new',
  'summer-orig':         'summer-new',
  'fall-orig':           'fall-new',
  'winter-orig':         'winter-new',
  'spring-new':          'spring-orig',
  'summer-new':          'summer-orig',
  'fall-new':            'fall-orig',
  'winter-new':          'winter-orig',
};
```

If a theme has no counterpart, falls back to `nebula` (new UX) or `classic-light` (orig UX).

---

## 8. Display Preferences UI

### Per-user: Avatar menu → "Display preferences"

A **slide-in drawer** on the right edge (overlays page so changes are visible live):

- **UX Mode** — toggle: Original / New UX. Always visible; users can always opt in or out.
- **Theme** — grid of two-tone swatches, grouped by A–F. Active swatch gets a ring. Swatches incompatible with current UX mode are dimmed but selectable — switching applies UX mode migration automatically with tooltip: `"Switching to a New UX theme will also enable the new interface."`
- **Font** — scrollable list; each item rendered in its own typeface.
- **Text Size** — four labeled buttons: Small / Default / Large / X-Large.

All changes apply instantly (CSS attr swap + `localStorage` write + debounced server sync via `MFPrefs.setMany()`). No save button.

### System-level: Settings → Appearance (operator role)

New card on the Settings overview grid:

```
┌─────────────────────────────────┐
│  Appearance                     │
│  Interface & theme defaults     │
│  [Manage →]                     │
└─────────────────────────────────┘
```

`/settings/appearance` page (operator role gate):

- **New UX** toggle — sets `enable_new_ux` in `user_preferences` DB table. Read-only informational note when env var is set: `"Deployment default: on (ENABLE_NEW_UX=true)"`. Toggle remains editable — it takes effect only when no env var is present.
- **Default theme** — swatch grid, sets org-wide default for new users.
- **Allow per-user overrides** — checkbox. If unchecked, the Display Preferences drawer is hidden from the avatar menu.

---

## 9. Font Loading

A single Google Fonts `<link>` in the shared `<head>` requests all 13 non-system typefaces:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=Roboto:wght@400;500;700&family=Source+Sans+3:wght@400;600&family=Lato:wght@400;700&family=Merriweather:wght@400;700&family=JetBrains+Mono:wght@400;500&family=Nunito:wght@400;500;700&family=Playfair+Display:wght@400;700&family=Raleway:wght@400;500;700&family=Poppins:wght@400;500;600&family=DM+Sans:wght@400;500&family=Crimson+Pro:wght@400;600&display=swap">
```

`display=swap` — text always visible. System font shows instantly; typeface swaps in when loaded. If Google Fonts is unreachable (air-gapped deploy), `--mf-font-family` cascades to `system-ui` via fallback stacks already in every font declaration.

---

## 10. Error Handling & Fallbacks

| Scenario | Behavior |
|----------|----------|
| `/api/user-prefs` fails on load | `preferences.js` falls back to `localStorage` (existing behavior) |
| `localStorage` empty + API fails | Init script hardcoded defaults: `nebula`, `system` font, `default` scale, new UX |
| Unknown `data-theme` value | No CSS match → `:root` tokens → Classic Light (graceful degradation) |
| Google Fonts unreachable | `system-ui` fallback in every font declaration |
| `use_new_ux` missing from stored prefs | `merged = {**DEFAULT_USER_PREFS, **stored}` fills in `True` (existing pattern) |

---

## 11. Files Modified / Created

| File | Change |
|------|--------|
| `core/user_prefs.py` | SCHEMA_VER 1→2; add 4 new keys to `DEFAULT_USER_PREFS` and validation sets |
| `core/db/preferences.py` | Add `enable_new_ux` system preference key |
| `core/feature_flags.py` | Add `is_new_ux_enabled_for(user_sub)` async function (three-tier lookup) |
| `static/css/design-tokens.css` | Add `--mf-text-scale` + `--mf-font-family` tokens; update text-size tokens to use `calc()` |
| `static/css/design-themes.css` | **New file** — 28 theme blocks + font blocks + text-scale blocks |
| `static/js/preferences.js` | Add `data-*` attr sync on pref change; add UX-mode migration logic |
| `static/js/components/avatar-menu.js` | Wire "Display preferences" item to open new drawer |
| `static/js/components/display-prefs-drawer.js` | **New file** — drawer UI: theme swatches, font list, text scale, UX toggle |
| `static/js/pages/settings-appearance.js` | **New file** — system-level appearance settings page |
| Every `static/*.html` page | Add synchronous init `<script>` in `<head>`; add Google Fonts `<link>` |
| `static/css/components.css` | Add `.display-prefs-drawer` styles |
| `docs/help/whats-new.md` | Add v0.37.0 entry |

---

## 12. Out of Scope

- Custom color picker (hex input) — user picks from 28 presets only
- Per-page theme (one theme per account session)
- Dark/light mode auto-detection via `prefers-color-scheme` — Nebula (dark) is default; OS match is not automatic (user picks explicitly)
- Theming of converted document output — only the app shell is themed
