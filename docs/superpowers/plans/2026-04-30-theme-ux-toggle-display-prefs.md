# Theme System, UX Toggle & Display Preferences — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 28 color themes, 14 fonts, 4 text scale steps, a per-user Display Preferences drawer, and a system-level Appearance settings page — all gated behind CSS custom properties on `<html data-theme data-font data-text-scale data-ux>`.

**Architecture:** Synchronous inline init script in every HTML `<head>` reads `localStorage` and sets `data-*` attrs before paint (zero flash). `design-themes.css` resolves those attrs to CSS token overrides. `preferences.js` syncs from `/api/user-prefs` and hot-swaps attrs live. Default: Nebula theme + New UX.

**Tech Stack:** FastAPI/Python (backend), vanilla JS IIFEs (frontend), CSS custom properties, Google Fonts, pytest + pytest-asyncio (tests).

---

## Parallel Execution Map

```
P1 (no deps):     Task 1, Task 3
P2 (after P1):    Task 2, Task 4, Task 5
P3 (after P2):    Task 6, Task 7, Task 8
P4 (after P3):    Task 9
P5 (after P4):    Task 10
```

---

## Task 1: Python — user_prefs SCHEMA_VER + new keys (TDD)

**Files:**
- Modify: `core/user_prefs.py`
- Modify: `tests/test_user_prefs.py`

- [ ] **Step 1: Write failing tests for new pref keys**

Append to `tests/test_user_prefs.py`:

```python
async def test_new_pref_defaults(db):
    prefs = await get_user_prefs(db, "new@local46.org")
    assert prefs["theme"] == "nebula"
    assert prefs["font"] == "system"
    assert prefs["text_scale"] == "default"
    assert prefs["use_new_ux"] is True


async def test_theme_enum_validated(db):
    with pytest.raises(ValueError, match="invalid value"):
        await set_user_pref(db, "alice@local46.org", "theme", "not-a-theme")


async def test_theme_valid_accepted(db):
    await set_user_pref(db, "alice@local46.org", "theme", "nebula")
    prefs = await get_user_prefs(db, "alice@local46.org")
    assert prefs["theme"] == "nebula"


async def test_font_enum_validated(db):
    with pytest.raises(ValueError, match="invalid value"):
        await set_user_pref(db, "alice@local46.org", "font", "comic-sans")


async def test_text_scale_enum_validated(db):
    with pytest.raises(ValueError, match="invalid value"):
        await set_user_pref(db, "alice@local46.org", "text_scale", "huge")


async def test_use_new_ux_bool_validated(db):
    with pytest.raises(ValueError, match="must be bool"):
        await set_user_pref(db, "alice@local46.org", "use_new_ux", "yes")


async def test_schema_ver_is_2(db):
    await set_user_pref(db, "alice@local46.org", "theme", "aurora")
    async with aiosqlite.connect(str(db)) as conn:
        async with conn.execute(
            "SELECT schema_ver FROM mf_user_prefs WHERE user_id = ?",
            ("alice@local46.org",)
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 2


async def test_existing_row_gets_new_defaults(db):
    """Rows written before v0.37.0 (SCHEMA_VER 1) must pick up new defaults on read."""
    import json
    old_blob = json.dumps({"layout": "minimal", "density": "cards"})
    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute(
            "INSERT INTO mf_user_prefs (user_id, value, schema_ver) VALUES (?, ?, 1)",
            ("olduser@local46.org", old_blob)
        )
        await conn.commit()
    prefs = await get_user_prefs(db, "olduser@local46.org")
    assert prefs["theme"] == "nebula"
    assert prefs["use_new_ux"] is True
    assert prefs["layout"] == "minimal"   # old value preserved
```

- [ ] **Step 2: Run tests — expect failures**

```
pytest tests/test_user_prefs.py -k "new_pref or theme or font or text_scale or use_new_ux or schema_ver or existing_row" -v
```

Expected: FAIL — `theme`, `font`, etc. not in `DEFAULT_USER_PREFS`.

- [ ] **Step 3: Update `core/user_prefs.py`**

Replace the `SCHEMA_VER` constant and `DEFAULT_USER_PREFS` dict:

```python
SCHEMA_VER = 2

DEFAULT_USER_PREFS: dict = {
    # Layout (Spec §3)
    "layout":                    "minimal",
    "density":                   "cards",
    "snippet_length":            "medium",
    "show_file_thumbnails":      False,

    # Power-user gate (Spec §9)
    "advanced_actions_inline":   False,

    # Search history
    "track_recent_searches":     True,
    "recent_searches":           [],

    # Items-per-page
    "items_per_page_cards":      24,
    "items_per_page_compact":    48,
    "items_per_page_list":       250,

    # Pinned
    "pinned_folders":            [],
    "pinned_topics":             [],

    # Onboarding
    "onboarding_completed_at":   "",

    # Display preferences (v0.37.0)
    "theme":      "nebula",
    "font":       "system",
    "text_scale": "default",
    "use_new_ux": True,
}
```

Add new keys to validation sets (find the `_ENUMS`, `_BOOLS`, `_INTS`, `_LISTS`, `_STRS` blocks and add):

```python
_ENUMS = {
    "layout":         {"maximal", "recent", "minimal"},
    "density":        {"cards", "compact", "list"},
    "snippet_length": {"short", "medium", "long"},
    "theme": {
        "classic-light", "classic-dark", "cobalt", "sage", "slate",
        "crimson", "sandstone", "graphite",
        "nebula", "aurora", "cobalt-new", "rose-quartz", "midnight-slate",
        "forest", "obsidian", "dusk",
        "hc-light", "hc-dark", "hc-light-new", "hc-dark-new",
        "pastel-lavender", "pastel-mint", "pastel-lavender-new", "pastel-mint-new",
        "spring-orig", "summer-orig", "fall-orig", "winter-orig",
        "spring-new", "summer-new", "fall-new", "winter-new",
    },
    "font": {
        "system", "inter", "ibm-plex-sans", "roboto", "source-sans-3",
        "lato", "merriweather", "jetbrains-mono", "nunito",
        "playfair-display", "raleway", "poppins", "dm-sans", "crimson-pro",
    },
    "text_scale": {"small", "default", "large", "xl"},
}
_BOOLS = {
    "show_file_thumbnails", "advanced_actions_inline",
    "track_recent_searches", "use_new_ux",
}
```

- [ ] **Step 4: Run tests — expect pass**

```
pytest tests/test_user_prefs.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add core/user_prefs.py tests/test_user_prefs.py
git commit -m "feat(user-prefs): SCHEMA_VER 1->2, add theme/font/text_scale/use_new_ux keys"
```

---

## Task 2: Python — is_new_ux_enabled_for + system pref key (TDD)

**Files:**
- Modify: `core/feature_flags.py`
- Modify: `core/db/preferences.py`
- Create: `tests/test_feature_flags.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_feature_flags.py`:

```python
"""Tests for core.feature_flags — three-tier UX lookup."""
import os
import pytest

pytestmark = pytest.mark.asyncio


async def _make_get_user_prefs(prefs: dict):
    async def _get(db, user_sub):
        return prefs
    return _get


async def _make_get_preference(value):
    async def _get(key, default=None):
        return value
    return _get


async def test_user_pref_wins_over_env(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.setenv("ENABLE_NEW_UX", "false")
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs(
        {"use_new_ux": True}
    ))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is True


async def test_user_pref_opt_out_wins_over_env(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up

    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs(
        {"use_new_ux": False}
    ))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is False


async def test_env_bypass_wins_over_system_pref(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs({}))
    monkeypatch.setattr(dbp, "get_preference", await _make_get_preference("false"))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is True


async def test_system_pref_used_when_no_env(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs({}))
    monkeypatch.setattr(dbp, "get_preference", await _make_get_preference("true"))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is True


async def test_default_is_false(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs({}))
    monkeypatch.setattr(dbp, "get_preference", await _make_get_preference(None))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is False
```

- [ ] **Step 2: Run — expect failures**

```
pytest tests/test_feature_flags.py -v
```

Expected: FAIL — `is_new_ux_enabled_for` not defined.

- [ ] **Step 3: Update `core/feature_flags.py`**

Replace entire file:

```python
"""Feature flag accessors. Centralized so tests can monkeypatch one place."""
from __future__ import annotations
import os

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(val: str | None) -> bool:
    return val is not None and val.strip().lower() in _TRUTHY


def is_new_ux_enabled() -> bool:
    """Env-only check — for non-auth contexts (e.g. middleware, health).

    Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §13
    """
    return _is_truthy(os.environ.get("ENABLE_NEW_UX"))


async def is_new_ux_enabled_for(user_sub: str) -> bool:
    """Three-tier lookup: user pref > env bypass > system pref > False.

    User pref always wins (users can always opt in/out).
    Env var bypasses the system DB pref but not the user pref.

    Spec: docs/superpowers/specs/2026-04-30-theme-ux-toggle-display-prefs-design.md §3
    """
    from core.db.connection import get_db_path
    from core.user_prefs import get_user_prefs
    from core.db.preferences import get_preference

    user_pref = await get_user_prefs(get_db_path(), user_sub)
    if "use_new_ux" in user_pref:
        return bool(user_pref["use_new_ux"])

    env_val = os.environ.get("ENABLE_NEW_UX", "").strip().lower()
    if env_val in ("true", "false"):
        return env_val == "true"

    sys_pref = await get_preference("enable_new_ux")
    if sys_pref is not None:
        return sys_pref.strip().lower() == "true"

    return False
```

- [ ] **Step 4: Add `enable_new_ux` to system preference defaults**

In `core/db/preferences.py`, find `DEFAULT_PREFERENCES` and add after `"cost_alert_threshold_usd"`:

```python
    # Interface defaults (v0.37.0)
    "enable_new_ux": "false",
    "allow_user_theme_override": "true",
    "default_theme": "nebula",
```

- [ ] **Step 5: Run tests — expect pass**

```
pytest tests/test_feature_flags.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```
git add core/feature_flags.py core/db/preferences.py tests/test_feature_flags.py
git commit -m "feat(feature-flags): add is_new_ux_enabled_for three-tier lookup + system pref keys"
```

---

## Task 3: CSS — design-tokens.css + design-themes.css

**Files:**
- Modify: `static/css/design-tokens.css`
- Create: `static/css/design-themes.css`

- [ ] **Step 1: Add new tokens to `static/css/design-tokens.css`**

After the opening `:root {` line, add before `/* === Color — primary accent */`:

```css
  /* === Theme system (v0.37.0) === */
  --mf-text-scale:   1;
  --mf-font-family:  system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  --mf-btn-bg:       var(--mf-color-accent);
```

Update the five text-size tokens (find and replace each one):

```css
  --mf-text-body:       calc(0.94rem * var(--mf-text-scale));
  --mf-text-sm:         calc(0.86rem * var(--mf-text-scale));
  --mf-text-xs:         calc(0.78rem * var(--mf-text-scale));
  --mf-text-micro:      calc(0.7rem  * var(--mf-text-scale));
```

After the final `}` of `:root`, add the `font-family` root declaration:

```css
:root { font-family: var(--mf-font-family); }
```

- [ ] **Step 2: Create `static/css/design-themes.css`**

```css
/* MarkFlow theme overrides — CSS custom property blocks keyed by data-theme.
   Loaded via @import in components.css. Font + text-scale blocks also here.
   Spec: docs/superpowers/specs/2026-04-30-theme-ux-toggle-display-prefs-design.md §5
*/

/* ─── Group A: Original UX themes ────────────────────────────────────────── */

[data-theme="classic-light"] { /* matches :root defaults — empty intentional */ }

[data-theme="classic-dark"] {
  --mf-bg-page:             #1a1a1f;
  --mf-surface:             #222228;
  --mf-surface-soft:        #1e1e24;
  --mf-surface-paper:       #26262e;
  --mf-border:              #333340;
  --mf-border-soft:         #2a2a38;
  --mf-color-accent:        #7c5ff8;
  --mf-color-accent-soft:   #a080ff;
  --mf-color-accent-tint:   rgba(124,95,248,0.12);
  --mf-color-accent-border: rgba(124,95,248,0.30);
  --mf-color-text:          #f0f0ff;
  --mf-color-text-soft:     #b0b0c8;
  --mf-color-text-muted:    #808098;
  --mf-color-text-faint:    #606078;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.4), 0 24px 48px -24px rgba(0,0,0,0.6);
  --mf-btn-bg:              linear-gradient(135deg,#7c5ff8,#9d80ff);
}

[data-theme="cobalt"] {
  --mf-bg-page:             #0d1628;
  --mf-surface:             #14203a;
  --mf-surface-soft:        #101c34;
  --mf-surface-paper:       #182640;
  --mf-border:              #1e3050;
  --mf-border-soft:         #182840;
  --mf-color-accent:        #f0a500;
  --mf-color-accent-soft:   #f5c040;
  --mf-color-accent-tint:   rgba(240,165,0,0.12);
  --mf-color-accent-border: rgba(240,165,0,0.30);
  --mf-color-text:          #e8f0ff;
  --mf-color-text-soft:     #a0b8d8;
  --mf-color-text-muted:    #6080a8;
  --mf-color-text-faint:    #405878;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.4), 0 24px 48px -24px rgba(0,0,0,0.6);
  --mf-btn-bg:              linear-gradient(135deg,#f0a500,#f5c040);
}

[data-theme="sage"] {
  --mf-bg-page:             #f5f0e8;
  --mf-surface:             #fdfaf5;
  --mf-surface-soft:        #f9f6ef;
  --mf-surface-paper:       #fefcf8;
  --mf-border:              #e4ddd0;
  --mf-border-soft:         #eae4d8;
  --mf-color-accent:        #2d6a4f;
  --mf-color-accent-soft:   #52b788;
  --mf-color-accent-tint:   rgba(45,106,79,0.08);
  --mf-color-accent-border: rgba(45,106,79,0.25);
  --mf-color-text:          #1a1a14;
  --mf-color-text-soft:     #3a3a28;
  --mf-color-text-muted:    #6a6a50;
  --mf-color-text-faint:    #909070;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.10);
  --mf-btn-bg:              linear-gradient(135deg,#2d6a4f,#52b788);
}

[data-theme="slate"] {
  --mf-bg-page:             #e8e8ec;
  --mf-surface:             #f4f4f8;
  --mf-surface-soft:        #eeeef2;
  --mf-surface-paper:       #f8f8fc;
  --mf-border:              #d4d4dc;
  --mf-border-soft:         #dadae0;
  --mf-color-accent:        #b05520;
  --mf-color-accent-soft:   #d4824a;
  --mf-color-accent-tint:   rgba(176,85,32,0.08);
  --mf-color-accent-border: rgba(176,85,32,0.25);
  --mf-color-text:          #1a1a24;
  --mf-color-text-soft:     #3a3a50;
  --mf-color-text-muted:    #6a6a80;
  --mf-color-text-faint:    #9090a8;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.05), 0 24px 48px -24px rgba(0,0,0,0.12);
  --mf-btn-bg:              linear-gradient(135deg,#b05520,#d4824a);
}

[data-theme="crimson"] {
  --mf-bg-page:             #1a0a0f;
  --mf-surface:             #280e16;
  --mf-surface-soft:        #22101a;
  --mf-surface-paper:       #30121c;
  --mf-border:              #401828;
  --mf-border-soft:         #361422;
  --mf-color-accent:        #c8c8d8;
  --mf-color-accent-soft:   #d8d8e8;
  --mf-color-accent-tint:   rgba(200,200,216,0.12);
  --mf-color-accent-border: rgba(200,200,216,0.25);
  --mf-color-text:          #f5e8ec;
  --mf-color-text-soft:     #c8a8b8;
  --mf-color-text-muted:    #906080;
  --mf-color-text-faint:    #604060;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.4), 0 24px 48px -24px rgba(0,0,0,0.6);
  --mf-btn-bg:              linear-gradient(135deg,#c8c8d8,#e8e8f8);
}

[data-theme="sandstone"] {
  --mf-bg-page:             #f2e8d8;
  --mf-surface:             #fdf8f0;
  --mf-surface-soft:        #f8f2e8;
  --mf-surface-paper:       #fefbf5;
  --mf-border:              #e0d0b8;
  --mf-border-soft:         #e8d8c4;
  --mf-color-accent:        #c04520;
  --mf-color-accent-soft:   #e06840;
  --mf-color-accent-tint:   rgba(192,69,32,0.08);
  --mf-color-accent-border: rgba(192,69,32,0.25);
  --mf-color-text:          #1a120a;
  --mf-color-text-soft:     #3a2a18;
  --mf-color-text-muted:    #6a5038;
  --mf-color-text-faint:    #907060;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.10);
  --mf-btn-bg:              linear-gradient(135deg,#c04520,#e06840);
}

[data-theme="graphite"] {
  --mf-bg-page:             #22242a;
  --mf-surface:             #2c2e38;
  --mf-surface-soft:        #282a34;
  --mf-surface-paper:       #30323e;
  --mf-border:              #3c3e50;
  --mf-border-soft:         #363848;
  --mf-color-accent:        #00a0a0;
  --mf-color-accent-soft:   #00c8c8;
  --mf-color-accent-tint:   rgba(0,160,160,0.12);
  --mf-color-accent-border: rgba(0,160,160,0.30);
  --mf-color-text:          #e8e8f0;
  --mf-color-text-soft:     #c0c0d0;
  --mf-color-text-muted:    #8080a0;
  --mf-color-text-faint:    #606080;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.4), 0 24px 48px -24px rgba(0,0,0,0.6);
  --mf-btn-bg:              linear-gradient(135deg,#00a0a0,#00c8c8);
}

/* ─── Group B: New UX themes ─────────────────────────────────────────────── */

[data-theme="nebula"] {
  --mf-bg-page:             #05060e;
  --mf-surface:             #0d0f1c;
  --mf-surface-soft:        #090b18;
  --mf-surface-paper:       #111328;
  --mf-border:              #1e2240;
  --mf-border-soft:         #181c38;
  --mf-color-accent:        #7c3aed;
  --mf-color-accent-soft:   #a855f7;
  --mf-color-accent-tint:   rgba(124,58,237,0.15);
  --mf-color-accent-border: rgba(124,58,237,0.35);
  --mf-color-text:          #f5f5ff;
  --mf-color-text-soft:     #a0a8d0;
  --mf-color-text-muted:    #5c6494;
  --mf-color-text-faint:    #3c4474;
  --mf-shadow-card:         0 2px 12px rgba(124,58,237,0.18), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#7c3aed,#a855f7);
}

[data-theme="aurora"] {
  --mf-bg-page:             #030d10;
  --mf-surface:             #061820;
  --mf-surface-soft:        #04141c;
  --mf-surface-paper:       #0a2430;
  --mf-border:              #0f3040;
  --mf-border-soft:         #0c2838;
  --mf-color-accent:        #00d4aa;
  --mf-color-accent-soft:   #00f5d4;
  --mf-color-accent-tint:   rgba(0,212,170,0.12);
  --mf-color-accent-border: rgba(0,212,170,0.30);
  --mf-color-text:          #e0f5f0;
  --mf-color-text-soft:     #80c0b8;
  --mf-color-text-muted:    #406060;
  --mf-color-text-faint:    #2a4848;
  --mf-shadow-card:         0 2px 12px rgba(0,212,170,0.12), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#00d4aa,#00f5d4);
}

[data-theme="cobalt-new"] {
  --mf-bg-page:             #030810;
  --mf-surface:             #060f20;
  --mf-surface-soft:        #040c1c;
  --mf-surface-paper:       #0a1830;
  --mf-border:              #0f2040;
  --mf-border-soft:         #0c1c38;
  --mf-color-accent:        #f0a000;
  --mf-color-accent-soft:   #f5c000;
  --mf-color-accent-tint:   rgba(240,160,0,0.12);
  --mf-color-accent-border: rgba(240,160,0,0.30);
  --mf-color-text:          #e0f0ff;
  --mf-color-text-soft:     #90b8d8;
  --mf-color-text-muted:    #405880;
  --mf-color-text-faint:    #2a4060;
  --mf-shadow-card:         0 2px 12px rgba(240,160,0,0.12), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#f0a000,#f5c800);
}

[data-theme="rose-quartz"] {
  --mf-bg-page:             #180c0e;
  --mf-surface:             #241418;
  --mf-surface-soft:        #201018;
  --mf-surface-paper:       #301c22;
  --mf-border:              #402030;
  --mf-border-soft:         #381c28;
  --mf-color-accent:        #d4a020;
  --mf-color-accent-soft:   #f0c040;
  --mf-color-accent-tint:   rgba(212,160,32,0.12);
  --mf-color-accent-border: rgba(212,160,32,0.30);
  --mf-color-text:          #ffe0e8;
  --mf-color-text-soft:     #c090a0;
  --mf-color-text-muted:    #804060;
  --mf-color-text-faint:    #603050;
  --mf-shadow-card:         0 2px 12px rgba(212,160,32,0.10), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#d4a020,#f0c040);
}

[data-theme="midnight-slate"] {
  --mf-bg-page:             #08090f;
  --mf-surface:             #101218;
  --mf-surface-soft:        #0c0e14;
  --mf-surface-paper:       #181a24;
  --mf-border:              #202430;
  --mf-border-soft:         #1c2028;
  --mf-color-accent:        #4080ff;
  --mf-color-accent-soft:   #60a0ff;
  --mf-color-accent-tint:   rgba(64,128,255,0.12);
  --mf-color-accent-border: rgba(64,128,255,0.30);
  --mf-color-text:          #e0e8ff;
  --mf-color-text-soft:     #9098c0;
  --mf-color-text-muted:    #505880;
  --mf-color-text-faint:    #344060;
  --mf-shadow-card:         0 2px 12px rgba(64,128,255,0.12), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#4080ff,#60a0ff);
}

[data-theme="forest"] {
  --mf-bg-page:             #040c06;
  --mf-surface:             #081408;
  --mf-surface-soft:        #061008;
  --mf-surface-paper:       #0c1e10;
  --mf-border:              #102818;
  --mf-border-soft:         #0e2414;
  --mf-color-accent:        #ff6820;
  --mf-color-accent-soft:   #ff9040;
  --mf-color-accent-tint:   rgba(255,104,32,0.12);
  --mf-color-accent-border: rgba(255,104,32,0.30);
  --mf-color-text:          #e0f0e0;
  --mf-color-text-soft:     #80b880;
  --mf-color-text-muted:    #406040;
  --mf-color-text-faint:    #2a4830;
  --mf-shadow-card:         0 2px 12px rgba(255,104,32,0.10), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#ff6820,#ff9040);
}

[data-theme="obsidian"] {
  --mf-bg-page:             #000000;
  --mf-surface:             #0a0a0a;
  --mf-surface-soft:        #060606;
  --mf-surface-paper:       #141414;
  --mf-border:              #202020;
  --mf-border-soft:         #1a1a1a;
  --mf-color-accent:        #e040fb;
  --mf-color-accent-soft:   #f060ff;
  --mf-color-accent-tint:   rgba(224,64,251,0.12);
  --mf-color-accent-border: rgba(224,64,251,0.30);
  --mf-color-text:          #f5f5f5;
  --mf-color-text-soft:     #b0b0b0;
  --mf-color-text-muted:    #606060;
  --mf-color-text-faint:    #404040;
  --mf-shadow-card:         0 2px 12px rgba(224,64,251,0.12), 0 24px 48px -24px rgba(0,0,0,0.9);
  --mf-btn-bg:              linear-gradient(135deg,#e040fb,#f060ff);
}

[data-theme="dusk"] {
  --mf-bg-page:             #0e0a06;
  --mf-surface:             #1c1208;
  --mf-surface-soft:        #180e06;
  --mf-surface-paper:       #281c0e;
  --mf-border:              #382614;
  --mf-border-soft:         #2e200e;
  --mf-color-accent:        #40c0f8;
  --mf-color-accent-soft:   #60d8ff;
  --mf-color-accent-tint:   rgba(64,192,248,0.12);
  --mf-color-accent-border: rgba(64,192,248,0.30);
  --mf-color-text:          #fff0e0;
  --mf-color-text-soft:     #c0a080;
  --mf-color-text-muted:    #806040;
  --mf-color-text-faint:    #605030;
  --mf-shadow-card:         0 2px 12px rgba(64,192,248,0.10), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#40c0f8,#60d8ff);
}

/* ─── Group C: High Contrast ─────────────────────────────────────────────── */

[data-theme="hc-light"] {
  --mf-bg-page:             #ffffff;
  --mf-surface:             #ffffff;
  --mf-surface-soft:        #ffffff;
  --mf-surface-paper:       #ffffff;
  --mf-border:              #000000;
  --mf-border-soft:         #333333;
  --mf-color-accent:        #0000cc;
  --mf-color-accent-soft:   #0033ff;
  --mf-color-accent-tint:   rgba(0,0,204,0.08);
  --mf-color-accent-border: #0000cc;
  --mf-color-text:          #000000;
  --mf-color-text-soft:     #000000;
  --mf-color-text-muted:    #333333;
  --mf-color-text-faint:    #555555;
  --mf-shadow-card:         0 0 0 2px #000000;
  --mf-btn-bg:              #0000cc;
}

[data-theme="hc-dark"] {
  --mf-bg-page:             #000000;
  --mf-surface:             #000000;
  --mf-surface-soft:        #000000;
  --mf-surface-paper:       #000000;
  --mf-border:              #ffffff;
  --mf-border-soft:         #aaaaaa;
  --mf-color-accent:        #ffff00;
  --mf-color-accent-soft:   #ffff60;
  --mf-color-accent-tint:   rgba(255,255,0,0.12);
  --mf-color-accent-border: #ffff00;
  --mf-color-text:          #ffffff;
  --mf-color-text-soft:     #ffffff;
  --mf-color-text-muted:    #cccccc;
  --mf-color-text-faint:    #aaaaaa;
  --mf-shadow-card:         0 0 0 2px #ffffff;
  --mf-btn-bg:              #333300;
}

[data-theme="hc-light-new"] {
  --mf-bg-page:             #ffffff;
  --mf-surface:             #ffffff;
  --mf-surface-soft:        #ffffff;
  --mf-surface-paper:       #ffffff;
  --mf-border:              #000000;
  --mf-border-soft:         #333333;
  --mf-color-accent:        #0000cc;
  --mf-color-accent-soft:   #0033ff;
  --mf-color-accent-tint:   rgba(0,0,204,0.08);
  --mf-color-accent-border: #0000cc;
  --mf-color-text:          #000000;
  --mf-color-text-soft:     #000000;
  --mf-color-text-muted:    #333333;
  --mf-color-text-faint:    #555555;
  --mf-shadow-card:         0 0 0 2px #000000;
  --mf-btn-bg:              #0000cc;
}

[data-theme="hc-dark-new"] {
  --mf-bg-page:             #000000;
  --mf-surface:             #000000;
  --mf-surface-soft:        #000000;
  --mf-surface-paper:       #000000;
  --mf-border:              #ffffff;
  --mf-border-soft:         #aaaaaa;
  --mf-color-accent:        #ffff00;
  --mf-color-accent-soft:   #ffff60;
  --mf-color-accent-tint:   rgba(255,255,0,0.12);
  --mf-color-accent-border: #ffff00;
  --mf-color-text:          #ffffff;
  --mf-color-text-soft:     #ffffff;
  --mf-color-text-muted:    #cccccc;
  --mf-color-text-faint:    #aaaaaa;
  --mf-shadow-card:         0 0 0 2px #ffffff;
  --mf-btn-bg:              #333300;
}

/* ─── Group D: Pastel ────────────────────────────────────────────────────── */

[data-theme="pastel-lavender"] {
  --mf-bg-page:             #f0eaf8;
  --mf-surface:             #f8f4fc;
  --mf-surface-soft:        #f4eef8;
  --mf-surface-paper:       #fcf8fe;
  --mf-border:              #e0d0f0;
  --mf-border-soft:         #e8daf4;
  --mf-color-accent:        #c2195a;
  --mf-color-accent-soft:   #e04080;
  --mf-color-accent-tint:   rgba(194,25,90,0.08);
  --mf-color-accent-border: rgba(194,25,90,0.25);
  --mf-color-text:          #1a0a24;
  --mf-color-text-soft:     #4a2a5a;
  --mf-color-text-muted:    #7a5a90;
  --mf-color-text-faint:    #a088b8;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.10);
  --mf-btn-bg:              linear-gradient(135deg,#c2195a,#e040a0);
}

[data-theme="pastel-mint"] {
  --mf-bg-page:             #e8f8f0;
  --mf-surface:             #f4fcf8;
  --mf-surface-soft:        #eef8f2;
  --mf-surface-paper:       #f8fefb;
  --mf-border:              #c8e8d8;
  --mf-border-soft:         #d4eee0;
  --mf-color-accent:        #c04040;
  --mf-color-accent-soft:   #e06060;
  --mf-color-accent-tint:   rgba(192,64,64,0.08);
  --mf-color-accent-border: rgba(192,64,64,0.25);
  --mf-color-text:          #0a1a10;
  --mf-color-text-soft:     #2a5038;
  --mf-color-text-muted:    #508068;
  --mf-color-text-faint:    #80a890;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.10);
  --mf-btn-bg:              linear-gradient(135deg,#c04040,#e06060);
}

[data-theme="pastel-lavender-new"] {
  --mf-bg-page:             #e8e0f5;
  --mf-surface:             #f0e8fc;
  --mf-surface-soft:        #ece4f8;
  --mf-surface-paper:       #f4f0fe;
  --mf-border:              #d0c0e8;
  --mf-border-soft:         #d8ccec;
  --mf-color-accent:        #8020c8;
  --mf-color-accent-soft:   #a040e8;
  --mf-color-accent-tint:   rgba(128,32,200,0.10);
  --mf-color-accent-border: rgba(128,32,200,0.25);
  --mf-color-text:          #0a0418;
  --mf-color-text-soft:     #3a2050;
  --mf-color-text-muted:    #6a50a0;
  --mf-color-text-faint:    #9070c8;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.05), 0 24px 48px -24px rgba(0,0,0,0.15);
  --mf-btn-bg:              linear-gradient(135deg,#8020c8,#a040e8);
}

[data-theme="pastel-mint-new"] {
  --mf-bg-page:             #ddf5ea;
  --mf-surface:             #ecfcf4;
  --mf-surface-soft:        #e4f8ee;
  --mf-surface-paper:       #f4fff8;
  --mf-border:              #b0e8cc;
  --mf-border-soft:         #bcecd4;
  --mf-color-accent:        #a83060;
  --mf-color-accent-soft:   #c85080;
  --mf-color-accent-tint:   rgba(168,48,96,0.08);
  --mf-color-accent-border: rgba(168,48,96,0.25);
  --mf-color-text:          #040f0a;
  --mf-color-text-soft:     #204838;
  --mf-color-text-muted:    #487860;
  --mf-color-text-faint:    #70a088;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.12);
  --mf-btn-bg:              linear-gradient(135deg,#a83060,#c85080);
}

/* ─── Group E: Seasonal — Original UX ───────────────────────────────────── */

[data-theme="spring-orig"] {
  --mf-bg-page:             #fff0f3;
  --mf-surface:             #fff8fa;
  --mf-surface-soft:        #fff4f7;
  --mf-surface-paper:       #fffcfd;
  --mf-border:              #ffd0dc;
  --mf-border-soft:         #ffe0e8;
  --mf-color-accent:        #2d8a4e;
  --mf-color-accent-soft:   #50c078;
  --mf-color-accent-tint:   rgba(45,138,78,0.08);
  --mf-color-accent-border: rgba(45,138,78,0.25);
  --mf-color-text:          #1a080c;
  --mf-color-text-soft:     #4a2030;
  --mf-color-text-muted:    #806070;
  --mf-color-text-faint:    #b09090;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.10);
  --mf-btn-bg:              linear-gradient(135deg,#2d8a4e,#50c078);
}

[data-theme="summer-orig"] {
  --mf-bg-page:             #fef8e8;
  --mf-surface:             #fffcf4;
  --mf-surface-soft:        #fef9ee;
  --mf-surface-paper:       #fffef8;
  --mf-border:              #f0e4b8;
  --mf-border-soft:         #f5ecc8;
  --mf-color-accent:        #0080a0;
  --mf-color-accent-soft:   #00a8c8;
  --mf-color-accent-tint:   rgba(0,128,160,0.08);
  --mf-color-accent-border: rgba(0,128,160,0.25);
  --mf-color-text:          #1a1408;
  --mf-color-text-soft:     #4a3820;
  --mf-color-text-muted:    #806040;
  --mf-color-text-faint:    #a88860;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.10);
  --mf-btn-bg:              linear-gradient(135deg,#0080a0,#00a8c8);
}

[data-theme="fall-orig"] {
  --mf-bg-page:             #fdf0d8;
  --mf-surface:             #fff8ec;
  --mf-surface-soft:        #fdf4e4;
  --mf-surface-paper:       #fffcf4;
  --mf-border:              #f0d8a0;
  --mf-border-soft:         #f5e0b4;
  --mf-color-accent:        #a04020;
  --mf-color-accent-soft:   #c86030;
  --mf-color-accent-tint:   rgba(160,64,32,0.08);
  --mf-color-accent-border: rgba(160,64,32,0.25);
  --mf-color-text:          #1a0c04;
  --mf-color-text-soft:     #4a2810;
  --mf-color-text-muted:    #806040;
  --mf-color-text-faint:    #a08060;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.10);
  --mf-btn-bg:              linear-gradient(135deg,#a04020,#c86030);
}

[data-theme="winter-orig"] {
  --mf-bg-page:             #e8f4ff;
  --mf-surface:             #f4f9ff;
  --mf-surface-soft:        #eef6ff;
  --mf-surface-paper:       #f8fbff;
  --mf-border:              #c8e0f8;
  --mf-border-soft:         #d4e8fa;
  --mf-color-accent:        #0a3060;
  --mf-color-accent-soft:   #1858a0;
  --mf-color-accent-tint:   rgba(10,48,96,0.08);
  --mf-color-accent-border: rgba(10,48,96,0.25);
  --mf-color-text:          #04101a;
  --mf-color-text-soft:     #204058;
  --mf-color-text-muted:    #506080;
  --mf-color-text-faint:    #8098b8;
  --mf-shadow-card:         0 1px 0 rgba(0,0,0,0.04), 0 24px 48px -24px rgba(0,0,0,0.12);
  --mf-btn-bg:              linear-gradient(135deg,#0a3060,#1858a0);
}

/* ─── Group F: Seasonal — New UX ─────────────────────────────────────────── */

[data-theme="spring-new"] {
  --mf-bg-page:             #030f06;
  --mf-surface:             #061808;
  --mf-surface-soft:        #041208;
  --mf-surface-paper:       #0a2410;
  --mf-border:              #0f3016;
  --mf-border-soft:         #0c2812;
  --mf-color-accent:        #f080a0;
  --mf-color-accent-soft:   #f8b0c0;
  --mf-color-accent-tint:   rgba(240,128,160,0.12);
  --mf-color-accent-border: rgba(240,128,160,0.30);
  --mf-color-text:          #f0ffe8;
  --mf-color-text-soft:     #90c880;
  --mf-color-text-muted:    #406040;
  --mf-color-text-faint:    #2a4830;
  --mf-shadow-card:         0 2px 12px rgba(240,128,160,0.10), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#f080a0,#f8b0c0);
}

[data-theme="summer-new"] {
  --mf-bg-page:             #030810;
  --mf-surface:             #051018;
  --mf-surface-soft:        #040c14;
  --mf-surface-paper:       #081828;
  --mf-border:              #0c2038;
  --mf-border-soft:         #0a1c30;
  --mf-color-accent:        #ff6860;
  --mf-color-accent-soft:   #ff9080;
  --mf-color-accent-tint:   rgba(255,104,96,0.12);
  --mf-color-accent-border: rgba(255,104,96,0.30);
  --mf-color-text:          #e0f8ff;
  --mf-color-text-soft:     #70c8e8;
  --mf-color-text-muted:    #306080;
  --mf-color-text-faint:    #1c4860;
  --mf-shadow-card:         0 2px 12px rgba(255,104,96,0.10), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#ff6860,#ff9080);
}

[data-theme="fall-new"] {
  --mf-bg-page:             #0f0600;
  --mf-surface:             #1c0e04;
  --mf-surface-soft:        #160a02;
  --mf-surface-paper:       #281808;
  --mf-border:              #38200a;
  --mf-border-soft:         #301a08;
  --mf-color-accent:        #e0a000;
  --mf-color-accent-soft:   #f0c820;
  --mf-color-accent-tint:   rgba(224,160,0,0.12);
  --mf-color-accent-border: rgba(224,160,0,0.30);
  --mf-color-text:          #fff0e0;
  --mf-color-text-soft:     #d0a060;
  --mf-color-text-muted:    #806030;
  --mf-color-text-faint:    #605020;
  --mf-shadow-card:         0 2px 12px rgba(224,160,0,0.10), 0 24px 48px -24px rgba(0,0,0,0.8);
  --mf-btn-bg:              linear-gradient(135deg,#e0a000,#f0c820);
}

[data-theme="winter-new"] {
  --mf-bg-page:             #020408;
  --mf-surface:             #040810;
  --mf-surface-soft:        #030610;
  --mf-surface-paper:       #060c1c;
  --mf-border:              #0a1428;
  --mf-border-soft:         #081020;
  --mf-color-accent:        #c8e8ff;
  --mf-color-accent-soft:   #e8f4ff;
  --mf-color-accent-tint:   rgba(200,232,255,0.12);
  --mf-color-accent-border: rgba(200,232,255,0.30);
  --mf-color-text:          #e8f4ff;
  --mf-color-text-soft:     #80a8cc;
  --mf-color-text-muted:    #406080;
  --mf-color-text-faint:    #2a4860;
  --mf-shadow-card:         0 2px 12px rgba(200,232,255,0.06), 0 24px 48px -24px rgba(0,0,0,0.9);
  --mf-btn-bg:              linear-gradient(135deg,#406080,#c8e8ff);
}

/* ─── Fonts ──────────────────────────────────────────────────────────────── */

[data-font="inter"]           { --mf-font-family: 'Inter', system-ui, sans-serif; }
[data-font="ibm-plex-sans"]   { --mf-font-family: 'IBM Plex Sans', system-ui, sans-serif; }
[data-font="roboto"]          { --mf-font-family: 'Roboto', system-ui, sans-serif; }
[data-font="source-sans-3"]   { --mf-font-family: 'Source Sans 3', system-ui, sans-serif; }
[data-font="lato"]            { --mf-font-family: 'Lato', system-ui, sans-serif; }
[data-font="merriweather"]    { --mf-font-family: 'Merriweather', Georgia, serif; }
[data-font="jetbrains-mono"]  { --mf-font-family: 'JetBrains Mono', 'Courier New', monospace; }
[data-font="nunito"]          { --mf-font-family: 'Nunito', system-ui, sans-serif; }
[data-font="playfair-display"]{ --mf-font-family: 'Playfair Display', Georgia, serif; }
[data-font="raleway"]         { --mf-font-family: 'Raleway', system-ui, sans-serif; }
[data-font="poppins"]         { --mf-font-family: 'Poppins', system-ui, sans-serif; }
[data-font="dm-sans"]         { --mf-font-family: 'DM Sans', system-ui, sans-serif; }
[data-font="crimson-pro"]     { --mf-font-family: 'Crimson Pro', Georgia, serif; }

/* ─── Text scale ─────────────────────────────────────────────────────────── */

[data-text-scale="small"]  { --mf-text-scale: 0.84; }
[data-text-scale="large"]  { --mf-text-scale: 1.18; }
[data-text-scale="xl"]     { --mf-text-scale: 1.36; }
/* default (1.0) is :root — no override block needed */
```

- [ ] **Step 3: Commit**

```
git add static/css/design-tokens.css static/css/design-themes.css
git commit -m "feat(css): design-themes.css — 28 themes, 13 fonts, 4 text scales; --mf-text-scale + --mf-btn-bg tokens"
```

---

## Task 4: CSS — components.css (@import + button token + drawer styles)

**Files:**
- Modify: `static/css/components.css`

- [ ] **Step 1: Add `@import` for design-themes.css**

In `static/css/components.css`, find line 3:
```css
@import url('./design-tokens.css');
```

Add after it:
```css
@import url('./design-themes.css');
```

- [ ] **Step 2: Update `.mf-pill--primary` to use `--mf-btn-bg`**

Find:
```css
.mf-pill--primary { background: var(--mf-color-accent); color: #ffffff; }
```
Replace with:
```css
.mf-pill--primary { background: var(--mf-btn-bg); color: #ffffff; }
```

- [ ] **Step 3: Add drawer styles**

Append to `static/css/components.css`:

```css
/* === Display Preferences Drawer (v0.37.0) === */
.mf-disp-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 320px;
  background: var(--mf-surface);
  border-left: 1px solid var(--mf-border);
  box-shadow: -8px 0 32px rgba(0,0,0,0.18);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  font-family: var(--mf-font-family);
  overflow: hidden;
}
.mf-disp-drawer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.1rem 1.25rem;
  border-bottom: 1px solid var(--mf-border);
  flex-shrink: 0;
}
.mf-disp-drawer__title {
  font-weight: 700;
  font-size: var(--mf-text-body);
  color: var(--mf-color-text);
  margin: 0;
}
.mf-disp-drawer__close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--mf-color-text-muted);
  font-size: 1.2rem;
  padding: 0.25rem;
  line-height: 1;
  border-radius: var(--mf-radius-thumb);
}
.mf-disp-drawer__close:hover { color: var(--mf-color-text); }
.mf-disp-drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}
.mf-disp-drawer__section-label {
  font-size: var(--mf-text-xs);
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--mf-color-text-muted);
  margin-bottom: 0.6rem;
}
/* Theme swatches */
.mf-disp-drawer__swatches {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem;
}
.mf-disp-drawer__swatch {
  width: 100%;
  aspect-ratio: 1;
  border-radius: var(--mf-radius-thumb);
  border: 2px solid transparent;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition: transform 0.1s;
}
.mf-disp-drawer__swatch:hover { transform: scale(1.08); }
.mf-disp-drawer__swatch--active { border-color: var(--mf-color-accent); }
.mf-disp-drawer__swatch--dim { opacity: 0.45; }
.mf-disp-drawer__swatch-bg { position: absolute; inset: 0; }
.mf-disp-drawer__swatch-acc {
  position: absolute;
  bottom: 0; right: 0;
  width: 40%; height: 40%;
  border-radius: var(--mf-radius-thumb) 0 0 0;
}
/* Font list */
.mf-disp-drawer__font-list {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.mf-disp-drawer__font-item {
  padding: 0.45rem 0.7rem;
  border-radius: var(--mf-radius-thumb);
  cursor: pointer;
  font-size: var(--mf-text-body);
  color: var(--mf-color-text-soft);
  border: 1px solid transparent;
}
.mf-disp-drawer__font-item:hover {
  background: var(--mf-color-accent-tint);
  color: var(--mf-color-text);
}
.mf-disp-drawer__font-item--active {
  background: var(--mf-color-accent-tint);
  border-color: var(--mf-color-accent-border);
  color: var(--mf-color-accent);
  font-weight: 600;
}
/* Text scale */
.mf-disp-drawer__scale-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.4rem;
}
.mf-disp-drawer__scale-btn {
  padding: 0.4rem 0;
  text-align: center;
  border-radius: var(--mf-radius-thumb);
  border: 1px solid var(--mf-border);
  background: transparent;
  color: var(--mf-color-text-soft);
  cursor: pointer;
  font-size: var(--mf-text-sm);
  font-family: var(--mf-font-family);
}
.mf-disp-drawer__scale-btn:hover { border-color: var(--mf-color-accent); }
.mf-disp-drawer__scale-btn--active {
  background: var(--mf-color-accent-tint);
  border-color: var(--mf-color-accent);
  color: var(--mf-color-accent);
  font-weight: 600;
}
/* UX toggle row */
.mf-disp-drawer__ux-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mf-disp-drawer__ux-label { color: var(--mf-color-text-soft); font-size: var(--mf-text-body); }
/* Overlay backdrop */
.mf-disp-drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.3);
  z-index: 999;
}
/* Group header within swatches */
.mf-disp-drawer__group-label {
  grid-column: 1 / -1;
  font-size: var(--mf-text-xs);
  color: var(--mf-color-text-faint);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-top: 0.3rem;
}
```

- [ ] **Step 4: Commit**

```
git add static/css/components.css
git commit -m "feat(css): @import design-themes, --mf-btn-bg in pill, display-prefs drawer styles"
```

---

## Task 5: HTML — init script + Google Fonts on all 35 pages

**Files (all 35 in `static/`):**
`progress.html`, `results.html`, `help.html`, `bulk-review.html`, `review.html`,
`debug.html`, `locations.html`, `viewer.html`, `job-detail.html`, `db-health.html`,
`providers.html`, `resources.html`, `search.html`, `log-management.html`, `flagged.html`,
`unrecognized.html`, `log-viewer.html`, `index.html`, `admin.html`, `batch-management.html`,
`bulk.html`, `history.html`, `pipeline-files.html`, `preview.html`, `settings.html`,
`status.html`, `storage.html`, `trash.html`, `activity.html`, `index-new.html`,
`settings-ai-providers.html`, `settings-auth.html`, `settings-cost-cap.html`,
`settings-db-health.html`, `settings-log-mgmt.html`, `settings-new.html`,
`settings-notifications.html`, `settings-pipeline.html`, `settings-storage.html`

- [ ] **Step 1: In each file, add the following block immediately after `<meta name="viewport" ...>`**

```html
  <script>
  (function(){
    var D={theme:'nebula',font:'system',textScale:'default',useNewUx:true};
    var p=Object.assign({},D,JSON.parse(localStorage.getItem('mf:preferences:v1')||'{}'));
    var h=document.documentElement;
    h.setAttribute('data-theme',p.theme);
    h.setAttribute('data-font',p.font);
    h.setAttribute('data-text-scale',p.textScale);
    h.setAttribute('data-ux',p.useNewUx?'new':'orig');
  })();
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=Roboto:wght@400;500;700&family=Source+Sans+3:wght@400;600&family=Lato:wght@400;700&family=Merriweather:wght@400;700&family=JetBrains+Mono:wght@400;500&family=Nunito:wght@400;500;700&family=Playfair+Display:wght@400;700&family=Raleway:wght@400;500;700&family=Poppins:wght@400;500;600&family=DM+Sans:wght@400;500&family=Crimson+Pro:wght@400;600&display=swap">
```

Example — `index-new.html` before:
```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MarkFlow — Search</title>
```

After:
```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script>
  (function(){
    var D={theme:'nebula',font:'system',textScale:'default',useNewUx:true};
    var p=Object.assign({},D,JSON.parse(localStorage.getItem('mf:preferences:v1')||'{}'));
    var h=document.documentElement;
    h.setAttribute('data-theme',p.theme);
    h.setAttribute('data-font',p.font);
    h.setAttribute('data-text-scale',p.textScale);
    h.setAttribute('data-ux',p.useNewUx?'new':'orig');
  })();
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=Roboto:wght@400;500;700&family=Source+Sans+3:wght@400;600&family=Lato:wght@400;700&family=Merriweather:wght@400;700&family=JetBrains+Mono:wght@400;500&family=Nunito:wght@400;500;700&family=Playfair+Display:wght@400;700&family=Raleway:wght@400;500;700&family=Poppins:wght@400;500;600&family=DM+Sans:wght@400;500&family=Crimson+Pro:wght@400;600&display=swap">
  <title>MarkFlow — Search</title>
```

- [ ] **Step 2: Commit**

```
git add static/*.html
git commit -m "feat(html): add theme init script + Google Fonts to all 35 pages"
```

---

## Task 6: JS — preferences.js data-* attr sync + UX migration

**Files:**
- Modify: `static/js/preferences.js`

- [ ] **Step 1: Add attr sync helpers after the `var subs = {}` line**

In `preferences.js`, after `var subs = {};   // key -> array of callbacks`, add:

```javascript
  var COUNTERPART = {
    'classic-light':'nebula','classic-dark':'nebula',
    'cobalt':'cobalt-new','sage':'forest','slate':'midnight-slate',
    'crimson':'rose-quartz','sandstone':'dusk','graphite':'obsidian',
    'nebula':'classic-dark','aurora':'classic-light',
    'cobalt-new':'cobalt','rose-quartz':'crimson','midnight-slate':'slate',
    'forest':'sage','obsidian':'graphite','dusk':'sandstone',
    'hc-light':'hc-light-new','hc-dark':'hc-dark-new',
    'hc-light-new':'hc-light','hc-dark-new':'hc-dark',
    'pastel-lavender':'pastel-lavender-new','pastel-mint':'pastel-mint-new',
    'pastel-lavender-new':'pastel-lavender','pastel-mint-new':'pastel-mint',
    'spring-orig':'spring-new','summer-orig':'summer-new',
    'fall-orig':'fall-new','winter-orig':'winter-new',
    'spring-new':'spring-orig','summer-new':'summer-orig',
    'fall-new':'fall-orig','winter-new':'winter-orig'
  };

  function syncAttrs(updates) {
    var h = document.documentElement;
    if (!h) return;
    if (updates.theme !== undefined)      h.setAttribute('data-theme',      updates.theme);
    if (updates.font  !== undefined)      h.setAttribute('data-font',       updates.font);
    if (updates.text_scale !== undefined) h.setAttribute('data-text-scale', updates.text_scale);
    if (updates.use_new_ux !== undefined) h.setAttribute('data-ux',         updates.use_new_ux ? 'new' : 'orig');
  }
```

- [ ] **Step 2: Update `set()` to call `syncAttrs`**

Find the `set()` function body. After `prefs[key] = value;` add:

```javascript
    var u = {}; u[key] = value; syncAttrs(u);
```

- [ ] **Step 3: Update `setMany()` to call `syncAttrs` + handle UX migration**

Find the `setMany()` function. After the changed-keys loop, add before `writeLocal()`:

```javascript
    // Auto-migrate theme when use_new_ux flips
    if (updates.use_new_ux !== undefined && updates.theme === undefined) {
      var cur = prefs['theme'] || 'nebula';
      var isNew = updates.use_new_ux;
      var partner = COUNTERPART[cur];
      if (partner) { prefs['theme'] = partner; keys.push('theme'); changed = true; }
    }
    syncAttrs(prefs);
```

- [ ] **Step 4: Call `syncAttrs` after server load in `load()`**

In the `.then(function(server){` block inside `load()`, after `prefs = server;` add:
```javascript
        syncAttrs(prefs);
```

- [ ] **Step 5: Commit**

```
git add static/js/preferences.js
git commit -m "feat(preferences.js): sync data-* attrs on pref change, UX-mode theme migration"
```

---

## Task 7: JS — display-prefs-drawer.js (new component)

**Files:**
- Create: `static/js/components/display-prefs-drawer.js`

- [ ] **Step 1: Create the file**

```javascript
/* Display Preferences Drawer — theme, font, text scale, UX toggle.
 * Usage:
 *   var drawer = MFDisplayPrefsDrawer.create();
 *   drawer.open();   // appends to body, adds backdrop
 *   drawer.close();
 *
 * Requires: MFPrefs (preferences.js) loaded before this file.
 * Safe DOM: no innerHTML. All text via textContent.
 */
(function (global) {
  'use strict';

  var THEMES = [
    {g:'orig',id:'classic-light',label:'Classic Light',bg:'#f7f7f9',acc:'#5b3df5'},
    {g:'orig',id:'classic-dark', label:'Classic Dark', bg:'#1a1a1f',acc:'#7c5ff8'},
    {g:'orig',id:'cobalt',       label:'Cobalt',       bg:'#0d1628',acc:'#f0a500'},
    {g:'orig',id:'sage',         label:'Sage',         bg:'#f5f0e8',acc:'#2d6a4f'},
    {g:'orig',id:'slate',        label:'Slate',        bg:'#e8e8ec',acc:'#b05520'},
    {g:'orig',id:'crimson',      label:'Crimson',      bg:'#1a0a0f',acc:'#c8c8d8'},
    {g:'orig',id:'sandstone',    label:'Sandstone',    bg:'#f2e8d8',acc:'#c04520'},
    {g:'orig',id:'graphite',     label:'Graphite',     bg:'#22242a',acc:'#00a0a0'},
    {g:'new', id:'nebula',       label:'Nebula',       bg:'#05060e',acc:'#7c3aed'},
    {g:'new', id:'aurora',       label:'Aurora',       bg:'#030d10',acc:'#00d4aa'},
    {g:'new', id:'cobalt-new',   label:'Cobalt',       bg:'#030810',acc:'#f0a000'},
    {g:'new', id:'rose-quartz',  label:'Rose Quartz',  bg:'#180c0e',acc:'#d4a020'},
    {g:'new', id:'midnight-slate',label:'Midnight',    bg:'#08090f',acc:'#4080ff'},
    {g:'new', id:'forest',       label:'Forest',       bg:'#040c06',acc:'#ff6820'},
    {g:'new', id:'obsidian',     label:'Obsidian',     bg:'#000000',acc:'#e040fb'},
    {g:'new', id:'dusk',         label:'Dusk',         bg:'#0e0a06',acc:'#40c0f8'},
    {g:'hc',  id:'hc-light',     label:'HC Light',     bg:'#ffffff',acc:'#0000cc'},
    {g:'hc',  id:'hc-dark',      label:'HC Dark',      bg:'#000000',acc:'#ffff00'},
    {g:'hc',  id:'hc-light-new', label:'HC Light+',    bg:'#ffffff',acc:'#0000cc'},
    {g:'hc',  id:'hc-dark-new',  label:'HC Dark+',     bg:'#000000',acc:'#ffff00'},
    {g:'pas', id:'pastel-lavender',    label:'Lavender',   bg:'#f0eaf8',acc:'#c2195a'},
    {g:'pas', id:'pastel-mint',        label:'Mint',        bg:'#e8f8f0',acc:'#c04040'},
    {g:'pas', id:'pastel-lavender-new',label:'Lavender+',  bg:'#e8e0f5',acc:'#8020c8'},
    {g:'pas', id:'pastel-mint-new',    label:'Mint+',       bg:'#ddf5ea',acc:'#a83060'},
    {g:'sea', id:'spring-orig',  label:'Spring',       bg:'#fff0f3',acc:'#2d8a4e'},
    {g:'sea', id:'summer-orig',  label:'Summer',       bg:'#fef8e8',acc:'#0080a0'},
    {g:'sea', id:'fall-orig',    label:'Fall',         bg:'#fdf0d8',acc:'#a04020'},
    {g:'sea', id:'winter-orig',  label:'Winter',       bg:'#e8f4ff',acc:'#0a3060'},
    {g:'sea', id:'spring-new',   label:'Spring+',      bg:'#030f06',acc:'#f080a0'},
    {g:'sea', id:'summer-new',   label:'Summer+',      bg:'#030810',acc:'#ff6860'},
    {g:'sea', id:'fall-new',     label:'Fall+',        bg:'#0f0600',acc:'#e0a000'},
    {g:'sea', id:'winter-new',   label:'Winter+',      bg:'#020408',acc:'#c8e8ff'},
  ];

  var FONTS = [
    {id:'system',          label:'System UI'},
    {id:'inter',           label:'Inter'},
    {id:'ibm-plex-sans',   label:'IBM Plex Sans'},
    {id:'roboto',          label:'Roboto'},
    {id:'source-sans-3',   label:'Source Sans 3'},
    {id:'lato',            label:'Lato'},
    {id:'merriweather',    label:'Merriweather'},
    {id:'jetbrains-mono',  label:'JetBrains Mono'},
    {id:'nunito',          label:'Nunito'},
    {id:'playfair-display',label:'Playfair Display'},
    {id:'raleway',         label:'Raleway'},
    {id:'poppins',         label:'Poppins'},
    {id:'dm-sans',         label:'DM Sans'},
    {id:'crimson-pro',     label:'Crimson Pro'},
  ];

  var SCALES = [
    {id:'small',   label:'Small'},
    {id:'default', label:'Default'},
    {id:'large',   label:'Large'},
    {id:'xl',      label:'X-Large'},
  ];

  var GROUP_LABELS = {
    orig:'Original UX', new:'New UX', hc:'High Contrast',
    pas:'Pastel', sea:'Seasonal'
  };

  var FONT_FAMILIES = {
    'system':'system-ui,sans-serif','inter':'Inter,system-ui,sans-serif',
    'ibm-plex-sans':'IBM Plex Sans,system-ui,sans-serif',
    'roboto':'Roboto,system-ui,sans-serif',
    'source-sans-3':'Source Sans 3,system-ui,sans-serif',
    'lato':'Lato,system-ui,sans-serif','merriweather':'Merriweather,Georgia,serif',
    'jetbrains-mono':'JetBrains Mono,monospace','nunito':'Nunito,system-ui,sans-serif',
    'playfair-display':'Playfair Display,Georgia,serif',
    'raleway':'Raleway,system-ui,sans-serif','poppins':'Poppins,system-ui,sans-serif',
    'dm-sans':'DM Sans,system-ui,sans-serif','crimson-pro':'Crimson Pro,Georgia,serif'
  };

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildSwatches(currentTheme, currentUx) {
    var wrap = el('div');
    var lastGroup = null;
    var grid = null;

    THEMES.forEach(function(t) {
      if (t.g !== lastGroup) {
        lastGroup = t.g;
        if (grid) wrap.appendChild(grid);
        grid = el('div', 'mf-disp-drawer__swatches');
        var glabel = el('div', 'mf-disp-drawer__group-label');
        glabel.textContent = GROUP_LABELS[t.g] || t.g;
        grid.appendChild(glabel);
      }
      var sw = el('button', 'mf-disp-drawer__swatch');
      sw.setAttribute('type', 'button');
      sw.setAttribute('title', t.label);
      sw.setAttribute('data-theme-id', t.id);
      if (t.id === currentTheme) sw.className += ' mf-disp-drawer__swatch--active';
      // Dim cross-UX themes (but still selectable — switching migrates UX)
      var isNewTheme = (t.g === 'new' || t.id.endsWith('-new'));
      if ((isNewTheme && currentUx !== 'new') || (!isNewTheme && t.g !== 'hc' && t.g !== 'pas' && t.g !== 'sea' && currentUx === 'new')) {
        // don't dim — all themes are selectable; UX migrates automatically
      }
      var bg = el('div', 'mf-disp-drawer__swatch-bg');
      bg.style.background = t.bg;
      var acc = el('div', 'mf-disp-drawer__swatch-acc');
      acc.style.background = t.acc;
      sw.appendChild(bg);
      sw.appendChild(acc);
      grid.appendChild(sw);
    });
    if (grid) wrap.appendChild(grid);
    return wrap;
  }

  function buildFonts(currentFont) {
    var list = el('div', 'mf-disp-drawer__font-list');
    FONTS.forEach(function(f) {
      var item = el('button', 'mf-disp-drawer__font-item' + (f.id === currentFont ? ' mf-disp-drawer__font-item--active' : ''));
      item.setAttribute('type', 'button');
      item.setAttribute('data-font-id', f.id);
      item.style.fontFamily = FONT_FAMILIES[f.id] || 'system-ui';
      item.textContent = f.label;
      list.appendChild(item);
    });
    return list;
  }

  function buildScales(currentScale) {
    var row = el('div', 'mf-disp-drawer__scale-row');
    SCALES.forEach(function(s) {
      var btn = el('button', 'mf-disp-drawer__scale-btn' + (s.id === currentScale ? ' mf-disp-drawer__scale-btn--active' : ''));
      btn.setAttribute('type', 'button');
      btn.setAttribute('data-scale-id', s.id);
      btn.textContent = s.label;
      row.appendChild(btn);
    });
    return row;
  }

  function buildUxRow(currentUx) {
    var row = el('div', 'mf-disp-drawer__ux-row');
    var lbl = el('span', 'mf-disp-drawer__ux-label');
    lbl.textContent = 'New interface';
    var toggle = el('button', 'mf-toggle mf-toggle--' + (currentUx === 'new' ? 'on' : 'off'));
    toggle.setAttribute('type', 'button');
    toggle.setAttribute('data-ux-toggle', '1');
    var knob = el('span', 'mf-toggle__knob');
    toggle.appendChild(knob);
    row.appendChild(lbl);
    row.appendChild(toggle);
    return row;
  }

  function section(labelText, content) {
    var wrap = el('div');
    var lbl = el('div', 'mf-disp-drawer__section-label');
    lbl.textContent = labelText;
    wrap.appendChild(lbl);
    wrap.appendChild(content);
    return wrap;
  }

  function create() {
    var backdrop = el('div', 'mf-disp-drawer-backdrop');
    var drawer = el('div', 'mf-disp-drawer');

    // ── Header
    var head = el('div', 'mf-disp-drawer__head');
    var title = el('h2', 'mf-disp-drawer__title');
    title.textContent = 'Display preferences';
    var closeBtn = el('button', 'mf-disp-drawer__close');
    closeBtn.setAttribute('type', 'button');
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.textContent = '×';
    head.appendChild(title);
    head.appendChild(closeBtn);
    drawer.appendChild(head);

    // ── Body (built fresh on each open so active states are current)
    function buildBody() {
      var old = drawer.querySelector('.mf-disp-drawer__body');
      if (old) drawer.removeChild(old);

      var currentTheme = (MFPrefs.get('theme') || 'nebula');
      var currentUx    = document.documentElement.getAttribute('data-ux') || 'new';
      var currentFont  = (MFPrefs.get('font') || 'system');
      var currentScale = (MFPrefs.get('text_scale') || 'default');

      var body = el('div', 'mf-disp-drawer__body');

      body.appendChild(section('Interface', buildUxRow(currentUx)));
      body.appendChild(section('Theme', buildSwatches(currentTheme, currentUx)));
      body.appendChild(section('Font', buildFonts(currentFont)));
      body.appendChild(section('Text size', buildScales(currentScale)));

      // Delegate all clicks
      body.addEventListener('click', function(ev) {
        var t = ev.target;
        // Theme swatch
        var sw = t.closest ? t.closest('[data-theme-id]') : null;
        if (sw) {
          var tid = sw.getAttribute('data-theme-id');
          MFPrefs.set('theme', tid);
          buildBody();
          return;
        }
        // Font item
        var fi = t.closest ? t.closest('[data-font-id]') : null;
        if (fi) {
          MFPrefs.set('font', fi.getAttribute('data-font-id'));
          buildBody();
          return;
        }
        // Scale button
        var sc = t.closest ? t.closest('[data-scale-id]') : null;
        if (sc) {
          MFPrefs.set('text_scale', sc.getAttribute('data-scale-id'));
          buildBody();
          return;
        }
        // UX toggle
        var ux = t.closest ? t.closest('[data-ux-toggle]') : null;
        if (ux) {
          var useNew = currentUx !== 'new';
          MFPrefs.setMany({use_new_ux: useNew});
          buildBody();
          return;
        }
      });

      drawer.appendChild(body);
    }

    closeBtn.addEventListener('click', close);
    backdrop.addEventListener('click', close);

    var open = false;

    function openDrawer() {
      if (open) return;
      open = true;
      buildBody();
      document.body.appendChild(backdrop);
      document.body.appendChild(drawer);
      var onEsc = function(ev) {
        if (ev.key === 'Escape') { close(); document.removeEventListener('keydown', onEsc); }
      };
      document.addEventListener('keydown', onEsc);
    }

    function close() {
      if (!open) return;
      open = false;
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
      if (drawer.parentNode)   drawer.parentNode.removeChild(drawer);
    }

    return { open: openDrawer, close: close };
  }

  global.MFDisplayPrefsDrawer = { create: create };
})(window);
```

- [ ] **Step 2: Commit**

```
git add static/js/components/display-prefs-drawer.js
git commit -m "feat(js): MFDisplayPrefsDrawer component — theme/font/scale/UX toggle drawer"
```

---

## Task 8: JS + HTML — Settings Appearance page

**Files:**
- Modify: `static/js/pages/settings-overview.js`
- Create: `static/js/pages/settings-appearance.js`
- Create: `static/js/settings-appearance-boot.js`
- Create: `static/settings-appearance.html`

- [ ] **Step 1: Add Appearance card to `settings-overview.js`**

In `ALL_CARDS`, add after the `pipeline` entry:

```javascript
    {
      id: 'appearance',
      icon: '\u{1F3A8}',
      label: 'Appearance',
      desc: 'Default theme, UX mode, and whether users can customize their own display.',
      href: '/settings/appearance',
      adminOnly: true,
    },
```

- [ ] **Step 2: Create `static/js/pages/settings-appearance.js`**

```javascript
/* Settings — Appearance page. Operator-only system defaults for theme + UX.
 * Usage: MFSettingsAppearance.mount(slot, { envUxOverride: bool|null });
 * Safe DOM: no innerHTML.
 */
(function (global) {
  'use strict';

  var ENDPOINT_PREFS = '/api/preferences';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function row(labelText, control, hint) {
    var wrap = el('div', 'mf-settings__pref-row');
    var lbl = el('label', 'mf-settings__pref-label');
    lbl.textContent = labelText;
    wrap.appendChild(lbl);
    wrap.appendChild(control);
    if (hint) {
      var h = el('p', 'mf-settings__pref-hint');
      h.textContent = hint;
      wrap.appendChild(h);
    }
    return wrap;
  }

  function buildToggle(isOn, onChange) {
    var btn = el('button', 'mf-toggle mf-toggle--' + (isOn ? 'on' : 'off'));
    btn.setAttribute('type', 'button');
    var knob = el('span', 'mf-toggle__knob');
    btn.appendChild(knob);
    btn.addEventListener('click', function () {
      var next = btn.classList.contains('mf-toggle--off');
      btn.className = 'mf-toggle mf-toggle--' + (next ? 'on' : 'off');
      onChange(next);
    });
    return btn;
  }

  function mount(slot, opts) {
    if (!slot) return;
    var envOverride = opts && opts.envUxOverride;   // true | false | null

    var body = el('div', 'mf-settings__body');

    var h1 = el('h1', 'mf-settings__headline');
    h1.textContent = 'Appearance';
    body.appendChild(h1);

    var sub = el('p', 'mf-settings__subtitle');
    sub.textContent = 'System-wide defaults for interface and theme. Users can override these in their own Display preferences.';
    body.appendChild(sub);

    var card = el('div', 'mf-card');
    card.style.cssText = 'padding:1.5rem;display:flex;flex-direction:column;gap:1.2rem;';

    // ── New UX toggle
    var uxNote = null;
    if (envOverride !== null) {
      uxNote = 'Deployment default: ' + (envOverride ? 'on' : 'off') + ' (ENABLE_NEW_UX env var). Toggle sets the DB fallback used when the env var is absent.';
    }
    var uxToggle = buildToggle(
      envOverride !== null ? envOverride : false,
      function (next) {
        fetch(ENDPOINT_PREFS, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ enable_new_ux: next ? 'true' : 'false' }),
        }).catch(function (e) { console.warn('appearance: pref save failed', e); });
      }
    );
    card.appendChild(row('New interface (default)', uxToggle, uxNote));

    // ── Allow per-user overrides
    var overrideToggle = buildToggle(true, function (next) {
      fetch(ENDPOINT_PREFS, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ allow_user_theme_override: next ? 'true' : 'false' }),
      }).catch(function (e) { console.warn('appearance: pref save failed', e); });
    });
    card.appendChild(row(
      'Allow per-user display overrides',
      overrideToggle,
      'When off, the Display preferences option is hidden from the avatar menu.'
    ));

    body.appendChild(card);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFSettingsAppearance = { mount: mount };
})(window);
```

- [ ] **Step 3: Create `static/js/settings-appearance-boot.js`**

```javascript
/* Boot for Settings > Appearance page. Operator-only. */
(function () {
  'use strict';

  var navRoot      = document.getElementById('mf-top-nav');
  var contentRoot  = document.getElementById('mf-settings');

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('me ' + r.status); return r.json(); })
      .catch(function () {
        return { user_id: 'dev', name: 'dev', role: 'operator', scope: '',
                 build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' } };
      });
  }

  function fetchEnvInfo() {
    return fetch('/api/version', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });
  }

  Promise.all([MFPrefs.load(), fetchMe(), fetchEnvInfo()]).then(function (res) {
    var me   = res[1];
    var info = res[2];
    var user = { name: me.name, role: me.role, scope: me.scope };

    var avatarMenu = MFAvatarMenu.create({
      user: user,
      build: me.build,
      onSelectItem: function (id) {
        if (id === 'display') {
          var drawer = MFDisplayPrefsDrawer.create();
          drawer.open();
        }
      },
      onSignOut: function () {
        fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
          .finally(function () { window.location.href = '/'; });
      },
    });

    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) { MFPrefs.set('layout', mode); },
    });

    MFTopNav.mount(navRoot, { role: me.role, activePage: 'settings' });
    MFVersionChip.mount(navRoot.querySelector('[data-mf-slot="version-chip"]'), { version: me.build.version });
    MFAvatar.mount(navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, onClick: function (btn) { avatarMenu.openAt(btn); } });
    MFLayoutIcon.mount(navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } });

    // Redirect non-operators away
    if (me.role !== 'operator' && me.role !== 'admin') {
      window.location.href = '/settings-new.html';
      return;
    }

    var envUxOverride = info.env_enable_new_ux != null ? !!info.env_enable_new_ux : null;
    MFSettingsAppearance.mount(contentRoot, { envUxOverride: envUxOverride });
  });
})();
```

- [ ] **Step 4: Create `static/settings-appearance.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script>
  (function(){
    var D={theme:'nebula',font:'system',textScale:'default',useNewUx:true};
    var p=Object.assign({},D,JSON.parse(localStorage.getItem('mf:preferences:v1')||'{}'));
    var h=document.documentElement;
    h.setAttribute('data-theme',p.theme);
    h.setAttribute('data-font',p.font);
    h.setAttribute('data-text-scale',p.textScale);
    h.setAttribute('data-ux',p.useNewUx?'new':'orig');
  })();
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=Roboto:wght@400;500;700&family=Source+Sans+3:wght@400;600&family=Lato:wght@400;700&family=Merriweather:wght@400;700&family=JetBrains+Mono:wght@400;500&family=Nunito:wght@400;500;700&family=Playfair+Display:wght@400;700&family=Raleway:wght@400;500;700&family=Poppins:wght@400;500;600&family=DM+Sans:wght@400;500&family=Crimson+Pro:wght@400;600&display=swap">
  <title>MarkFlow — Appearance</title>
  <link rel="stylesheet" href="/static/css/components.css">
  <style>
    body { margin: 0; background: var(--mf-bg-page); font-family: var(--mf-font-family); min-height: 100vh; }
  </style>
</head>
<body data-env="dev">
  <div id="mf-top-nav"></div>
  <div id="mf-settings"></div>

  <script src="/static/js/preferences.js"></script>
  <script src="/static/js/telemetry.js"></script>
  <script src="/static/js/keybinds.js"></script>
  <script src="/static/js/components/top-nav.js"></script>
  <script src="/static/js/components/version-chip.js"></script>
  <script src="/static/js/components/avatar.js"></script>
  <script src="/static/js/components/avatar-menu.js"></script>
  <script src="/static/js/components/layout-icon.js"></script>
  <script src="/static/js/components/layout-popover.js"></script>
  <script src="/static/js/components/display-prefs-drawer.js"></script>
  <script src="/static/js/pages/settings-appearance.js"></script>
  <script src="/static/js/settings-appearance-boot.js"></script>
</body>
</html>
```

- [ ] **Step 5: Commit**

```
git add static/js/pages/settings-overview.js static/js/pages/settings-appearance.js static/js/settings-appearance-boot.js static/settings-appearance.html
git commit -m "feat(settings): Appearance page — system UX toggle + per-user override gate"
```

---

## Task 9: JS — Wire drawer into all boot files + avatar menu

**Files:**
- Modify: `static/js/index-new-boot.js`
- Modify: `static/js/settings-new-boot.js`
- Modify: `static/js/settings-ai-providers-boot.js`
- Modify: `static/js/settings-auth-boot.js`
- Modify: `static/js/settings-cost-cap-boot.js`
- Modify: `static/js/settings-db-health-boot.js`
- Modify: `static/js/settings-log-mgmt-boot.js`
- Modify: `static/js/settings-notifications-boot.js`
- Modify: `static/js/settings-pipeline-boot.js`
- Modify: `static/js/settings-storage-boot.js`
- Modify: `static/js/activity-boot.js`

- [ ] **Step 1: In each boot file, update `onSelectItem` to handle `'display'`**

Find the `onSelectItem` callback in `MFAvatarMenu.create({...})`. Currently reads:
```javascript
onSelectItem: function (id) { console.log('avatar item:', id); },
```

Replace with:
```javascript
onSelectItem: function (id) {
  if (id === 'display') {
    var drawer = MFDisplayPrefsDrawer.create();
    drawer.open();
    return;
  }
  console.log('avatar item:', id);
},
```

- [ ] **Step 2: Add `display-prefs-drawer.js` `<script>` tag to all new UX HTML pages**

In each HTML page that has a boot file listed above, add before the boot script tag:
```html
  <script src="/static/js/components/display-prefs-drawer.js"></script>
```

Pages to update: `index-new.html`, `settings-new.html`, `settings-ai-providers.html`,
`settings-auth.html`, `settings-cost-cap.html`, `settings-db-health.html`,
`settings-log-mgmt.html`, `settings-notifications.html`, `settings-pipeline.html`,
`settings-storage.html`, `activity.html`

- [ ] **Step 3: Commit**

```
git add static/js/*-boot.js static/js/activity-boot.js static/*.html
git commit -m "feat(boot): wire MFDisplayPrefsDrawer into all new-UX page boot files"
```

---

## Task 10: Docs + version bump

**Files:**
- Modify: `core/version.py`
- Modify: `docs/help/whats-new.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Bump version**

In `core/version.py`, change `__version__` to `"0.37.0"`.

- [ ] **Step 2: Add whats-new entry**

Prepend to `docs/help/whats-new.md`:

```markdown
## v0.37.0 — Display Preferences & Theme System

**28 color themes.** Choose from Original UX, New UX, High Contrast, Pastel, and Seasonal palettes. Themes apply instantly — no page reload.

**14 font choices.** System UI through Playfair Display and JetBrains Mono. Rendered live so you see what you're picking.

**Text size control.** Small / Default / Large / X-Large, independent of browser zoom.

**Per-user Display Preferences.** Open from the avatar menu. Everything saves automatically.

**New UX toggle.** Users can switch between the original interface and the new search-as-home design at any time. Operators can set the system default in Settings → Appearance.
```

- [ ] **Step 3: Update CLAUDE.md Current Version block**

Replace the `## Current Version — v0.36.0` heading and its opening sentence with:

```markdown
## Current Version — v0.37.0

**Display Preferences & Theme System.** 28 color themes (Original UX / New UX / High Contrast / Pastel / Seasonal), 14 font choices, 4 text scale steps. Per-user Display Preferences drawer (avatar menu). System-level Appearance settings page (operator). Three-tier UX toggle: user pref > env bypass > system pref. Default experience: Nebula theme + New UX. CSS custom properties via `data-*` attrs on `<html>`. SCHEMA_VER 1→2 in `mf_user_prefs`.
```

- [ ] **Step 4: Commit**

```
git add core/version.py docs/help/whats-new.md CLAUDE.md
git commit -m "docs(release): v0.37.0 — theme system + display preferences"
```

---

## Self-Review

**Spec coverage check:**
- §2 Architecture (data-* attrs, init script, zero-flash) → Task 5 ✓
- §3 Three-tier UX lookup → Task 2 ✓
- §4 Data model (SCHEMA_VER 2, DEFAULT_USER_PREFS, validation) → Task 1 ✓
- §5 CSS architecture (design-tokens + design-themes) → Task 3 ✓
- §6 All 28 themes → Task 3 (design-themes.css) ✓
- §7 UX-mode theme migration (COUNTERPART map) → Task 6 (preferences.js) ✓
- §8 Display Preferences drawer → Task 7 ✓
- §8 Settings > Appearance page → Task 8 ✓
- §9 Font loading (Google Fonts link) → Task 5 ✓
- §10 Error handling (localStorage fallback, CSS fallback) → Task 5 (init script defaults) + Task 3 (font fallbacks) ✓
- §11 File list → all tasks ✓

**Placeholder scan:** No TBD, TODO, or vague steps found.

**Type consistency:** `COUNTERPART` object defined in Task 6 (preferences.js) matches the spec §7 map. `is_new_ux_enabled_for` signature matches usage in Task 2 tests. `MFDisplayPrefsDrawer.create()` returns `{open, close}` — matches Task 9 usage.
