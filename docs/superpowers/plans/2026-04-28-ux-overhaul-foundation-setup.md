# UX Overhaul — Foundation Setup Plan (Plan 1A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Land all the *non-UI* foundation needed before any new chrome ships: feature flag, design-token CSS, shared component CSS scaffold, preferences DB migration, JWT role-claim parsing, `/pipeline → /activity` redirect, preferences server module + HTTP endpoints, mockup archive index, and `CLAUDE.md` cross-references.

**Architecture:** Pure backend + CSS + docs in this plan — zero new JavaScript. Backend uses existing FastAPI + aiosqlite + structlog. CSS uses custom properties as the single source of truth for the visual system; no styles consumed yet (Plan 1B mounts the first components). User preferences are a JSON blob keyed by UnionCore subject claim with per-key validation at the server. Plan 1B (Shared Chrome JS) and Plan 1C (Search-as-home + Document Card) build on this foundation.

**Tech Stack:** Python 3.11 · FastAPI · aiosqlite · pytest · structlog · vanilla CSS

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` — covers §1 (route rename), §2 (visual tokens), §10 (preferences), §11 (role binding), §13 (preflight setup section).

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/` — visual fidelity reference for the styles being declared in design-tokens.css.

**Out of scope for this plan:**
- All JS components (top-nav, avatar-menu, layout-icon, version-chip, preferences client) → Plan 1B
- Document card component → Plan 2
- Search-as-home page → Plan 3
- Settings detail pages → Plans 4–7
- Activity dashboard rendering → Plan 4

---

## File structure (this plan creates / modifies)

**Create:**
- `core/feature_flags.py` — feature flag accessors
- `static/css/design-tokens.css` — visual system as CSS custom properties
- `static/css/components.css` — shared component classes (consumes tokens; no usage yet)
- `core/db/migrations/<NNN>_user_preferences.py` — DB migration (use next free integer)
- `core/preferences.py` — server-side preferences logic with validation
- `api/routes/preferences.py` — GET/PUT preferences endpoints
- `tests/test_feature_flag.py`
- `tests/test_user_preferences_migration.py`
- `tests/test_role_claim_extraction.py`
- `tests/test_route_aliases.py`
- `tests/test_preferences.py`
- `tests/test_preferences_api.py`
- `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/index.html` — archive landing page

**Modify:**
- `.env.example` — add `ENABLE_NEW_UX` flag
- `core/auth.py` — add `Role` enum + `extract_role()`
- `main.py` — register `/api/preferences` router; add `/pipeline` → `/activity` 301
- `CLAUDE.md` — append architecture reminders + critical files rows

---

## Phase 0 — Foundation Setup

### Task 1: ENABLE_NEW_UX feature flag

**Files:**
- Create: `core/feature_flags.py`
- Create: `tests/test_feature_flag.py`
- Modify: `.env.example`

- [x] **Step 1: Confirm where existing feature flags live**

Run: `grep -rn "DEV_BYPASS_AUTH" core/ main.py`

Read whichever file currently parses that flag. The new flag follows the same pattern. If MarkFlow already has a `core/feature_flags.py` or equivalent, append to it instead of creating a new file.

- [x] **Step 2: Write the failing test**

Create `tests/test_feature_flag.py`:

```python
import pytest
from core.feature_flags import is_new_ux_enabled


def test_new_ux_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    assert is_new_ux_enabled() is False


def test_new_ux_enabled_when_set_true(monkeypatch):
    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    assert is_new_ux_enabled() is True


def test_new_ux_disabled_when_set_false(monkeypatch):
    monkeypatch.setenv("ENABLE_NEW_UX", "false")
    assert is_new_ux_enabled() is False


@pytest.mark.parametrize("val", ["1", "yes", "True", "TRUE", "on"])
def test_new_ux_truthy_values(monkeypatch, val):
    monkeypatch.setenv("ENABLE_NEW_UX", val)
    assert is_new_ux_enabled() is True


@pytest.mark.parametrize("val", ["0", "no", "False", "off", "", "  "])
def test_new_ux_falsy_values(monkeypatch, val):
    monkeypatch.setenv("ENABLE_NEW_UX", val)
    assert is_new_ux_enabled() is False
```

- [x] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_feature_flag.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'core.feature_flags'`.

- [x] **Step 4: Implement the flag accessor**

Create `core/feature_flags.py`:

```python
"""Feature flag accessors. Centralized so tests can monkeypatch one place."""
from __future__ import annotations
import os


_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(val: str | None) -> bool:
    return val is not None and val.strip().lower() in _TRUTHY


def is_new_ux_enabled() -> bool:
    """Whether the v0.35+ UX (Search-as-home, new chrome, role-gated nav) is active.

    Default: False. Production must explicitly set ENABLE_NEW_UX=true.

    Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §13
    """
    return _is_truthy(os.environ.get("ENABLE_NEW_UX"))
```

- [x] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_feature_flag.py -v`

Expected: 9 PASS (5 tests with parametrize expansions).

- [x] **Step 6: Update `.env.example`**

Append to `.env.example`:

```
# Feature flags
# Set to true to enable the v0.35+ UX (Search-as-home, new chrome, role-gated nav).
# Default: false. Production rollout flips this on after Plans 1A through 4 ship.
ENABLE_NEW_UX=false
```

- [x] **Step 7: Commit**

```bash
git add core/feature_flags.py tests/test_feature_flag.py .env.example
git commit -m "feat(ux): add ENABLE_NEW_UX feature flag (default off)

Centralized accessor for the v0.35 UX rollout. Default off so existing UI
is preserved; production flips on after the chrome and Search-as-home
plans ship. Spec §13."
```

---

### Task 2: Design tokens CSS

**Files:**
- Create: `static/css/design-tokens.css`

CSS-only — no test infrastructure required. Verification is a manual smoke check that the file loads and `:root` custom properties resolve in the browser.

- [x] **Step 1: Create the design tokens file**

Create `static/css/design-tokens.css`:

```css
/* MarkFlow design tokens — single source of truth for the visual system.
   Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §2

   Naming convention: --mf-<category>-<role>-<variant>
   All values reflect locked spec decisions; do not edit without updating the spec.
*/

:root {
  /* === Color — primary accent (purple) === */
  --mf-color-accent:           #5b3df5;
  --mf-color-accent-soft:      #9d7bff;
  --mf-color-accent-tint:      #f3f0ff;  /* hover backgrounds, soft chips */
  --mf-color-accent-tint-2:    #f5f3ff;  /* extra-soft surfaces */
  --mf-color-accent-border:    #d8ceff;  /* selected/recommended outlines */

  /* === Color — neutrals === */
  --mf-color-text:             #0a0a0a;
  --mf-color-text-soft:        #3a3a3a;
  --mf-color-text-muted:       #5a5a5a;
  --mf-color-text-faint:       #888888;
  --mf-color-text-fainter:     #aaaaaa;

  --mf-surface:                #ffffff;
  --mf-surface-soft:           #fafafa;
  --mf-surface-paper:          #fefefb;  /* document-card body bg */
  --mf-border:                 #ececec;
  --mf-border-soft:            #f0f0f0;

  /* === Color — status === */
  --mf-color-success:          #0e7c5a;
  --mf-color-success-bg:       #eafff5;
  --mf-color-warn:             #a36a00;
  --mf-color-warn-bg:          #fff5e0;
  --mf-color-error:            #c92a2a;
  --mf-color-error-bg:         #ffe7e7;

  /* === Format-coded gradients (PDF, DOCX, PPTX, XLSX, EML, PSD, MP4, MD) === */
  --mf-fmt-pdf:   linear-gradient(135deg, #ff6b6b 0%, #c92a2a 100%);
  --mf-fmt-docx:  linear-gradient(135deg, #4dabf7 0%, #1864ab 100%);
  --mf-fmt-pptx:  linear-gradient(135deg, #ffa94d 0%, #e8590c 100%);
  --mf-fmt-xlsx:  linear-gradient(135deg, #51cf66 0%, #2b8a3e 100%);
  --mf-fmt-eml:   linear-gradient(135deg, #cc5de8 0%, #862e9c 100%);
  --mf-fmt-psd:   linear-gradient(135deg, #5c7cfa 0%, #364fc7 100%);
  --mf-fmt-mp4:   linear-gradient(135deg, #22b8cf 0%, #0b7285 100%);
  --mf-fmt-md:    linear-gradient(135deg, #0a0a0a 0%, #495057 100%);

  /* === Type === */
  --mf-font-sans:    -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif;
  --mf-font-serif:   "Iowan Old Style", "Charter", "Cambria", Georgia, serif;
  --mf-font-mono:    ui-monospace, "SF Mono", Menlo, monospace;

  --mf-text-display:    2.4rem;
  --mf-text-display-sm: 2.0rem;
  --mf-text-h1:         1.85rem;
  --mf-text-h2:         1.4rem;
  --mf-text-h3:         1.05rem;
  --mf-text-body:       0.94rem;
  --mf-text-sm:         0.86rem;
  --mf-text-xs:         0.78rem;
  --mf-text-micro:      0.7rem;

  --mf-tracking-tight:  -0.025em;
  --mf-tracking-wide:   0.07em;
  --mf-leading-tight:   1.05;
  --mf-leading-body:    1.45;

  /* === Radius === */
  --mf-radius-pill:     999px;
  --mf-radius-card-lg:  14px;
  --mf-radius-card:     12px;
  --mf-radius-input:    10px;
  --mf-radius-thumb:    8px;

  /* === Shadows === */
  --mf-shadow-card:     0 1px 0 rgba(0,0,0,0.05), 0 24px 48px -24px rgba(0,0,0,0.18);
  --mf-shadow-popover:  0 16px 36px -8px rgba(0,0,0,0.2);
  --mf-shadow-thumb:    0 1px 0 rgba(0,0,0,0.04), 0 8px 16px -10px rgba(0,0,0,0.1);
  --mf-shadow-press:    0 1px 3px rgba(0,0,0,0.08);

  /* === Spacing — 4px scale === */
  --mf-space-1:  0.25rem;
  --mf-space-2:  0.5rem;
  --mf-space-3:  0.75rem;
  --mf-space-4:  1rem;
  --mf-space-5:  1.25rem;
  --mf-space-6:  1.5rem;
  --mf-space-8:  2rem;
  --mf-space-10: 2.5rem;

  /* === Layout === */
  --mf-page-pad-x:   2rem;
  --mf-page-pad-y:   2.2rem;
  --mf-content-max:  1280px;

  /* === Animation === */
  --mf-transition-fast: 0.15s;
  --mf-transition-med:  0.2s;
}

/* Production: hide the dev version chip (Plan 1B will style .mf-ver-chip). */
body[data-env="prod"] .mf-ver-chip { display: none; }
```

- [x] **Step 2: Smoke verify it loads**

Add a temporary `<link rel="stylesheet" href="/static/css/design-tokens.css">` to `static/index.html` `<head>`, then:

```bash
docker-compose up -d
```

Visit `http://localhost:8000/` in the browser, open DevTools → Elements → select `<html>` → Computed pane → search for `--mf-color-accent`. Should resolve to `#5b3df5`.

Revert the temporary `<link>` change in `static/index.html` (it gets re-added properly during Plan 1B / 1C work).

- [x] **Step 3: Commit**

```bash
git add static/css/design-tokens.css
git commit -m "feat(ux): add design tokens CSS — single source of truth

Mirrors spec §2. All colors, type sizes, radii, shadows, spacing as CSS
custom properties. Existing markflow.css will incrementally migrate to
consume these tokens during phase 1+ work; old hardcoded values stay
until each consumer is touched."
```

---

### Task 3: Components.css scaffolding

**Files:**
- Create: `static/css/components.css`

Initial scaffold lays out shared component base styles. Plan 1B and later append component-specific styles to this file.

- [x] **Step 1: Create the file**

Create `static/css/components.css`:

```css
/* Shared component styles. Builds on design-tokens.css.
   Spec: §2 visual system; §4 cards; §6 avatar menu chrome; §7 settings detail. */

@import url('./design-tokens.css');

/* === pill buttons === */
.mf-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--mf-space-2);
  padding: 0.55rem 1.15rem;
  border-radius: var(--mf-radius-pill);
  font-weight: 600;
  font-size: 0.86rem;
  font-family: var(--mf-font-sans);
  border: none;
  cursor: pointer;
  transition: opacity var(--mf-transition-fast);
}
.mf-pill--primary { background: var(--mf-color-accent); color: #ffffff; }
.mf-pill--primary:hover { opacity: 0.92; }
.mf-pill--outline {
  background: var(--mf-surface);
  color: var(--mf-color-accent);
  border: 1.5px solid var(--mf-color-accent);
}
.mf-pill--ghost {
  background: transparent;
  color: var(--mf-color-accent);
  padding: 0.5rem 0.7rem;
}
.mf-pill--sm { padding: 0.4rem 0.85rem; font-size: 0.78rem; }
.mf-pill--danger {
  background: var(--mf-surface);
  color: var(--mf-color-error);
  border: 1.5px solid #ffd0d0;
}

/* === toggles === */
.mf-toggle {
  width: 36px;
  height: 20px;
  border-radius: var(--mf-radius-pill);
  position: relative;
  flex-shrink: 0;
  cursor: pointer;
  transition: background var(--mf-transition-fast);
  border: none;
  padding: 0;
}
.mf-toggle--on  { background: var(--mf-color-accent); }
.mf-toggle--off { background: #e0e0e0; }
.mf-toggle__knob {
  width: 16px;
  height: 16px;
  background: #ffffff;
  border-radius: 50%;
  position: absolute;
  top: 2px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  transition: left var(--mf-transition-fast), right var(--mf-transition-fast);
}
.mf-toggle--on  .mf-toggle__knob { right: 2px; }
.mf-toggle--off .mf-toggle__knob { left: 2px; }

/* === segmented control === */
.mf-seg {
  display: inline-flex;
  background: #f3f3f3;
  border-radius: var(--mf-radius-pill);
  padding: 0.22rem;
  font-size: 0.84rem;
}
.mf-seg__opt {
  padding: 0.4rem 0.95rem;
  border-radius: var(--mf-radius-pill);
  cursor: pointer;
  color: #666666;
  font-weight: 500;
  background: transparent;
  border: none;
  font-family: var(--mf-font-sans);
}
.mf-seg__opt--on {
  background: var(--mf-surface);
  color: var(--mf-color-text);
  box-shadow: var(--mf-shadow-press);
}

/* === card surfaces === */
.mf-card {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  box-shadow: var(--mf-shadow-card);
  font-family: var(--mf-font-sans);
}

/* === status pulse === */
.mf-pulse {
  display: inline-flex;
  align-items: center;
  gap: var(--mf-space-2);
  background: var(--mf-color-success-bg);
  color: var(--mf-color-success);
  padding: 0.32rem 0.85rem;
  border-radius: var(--mf-radius-pill);
  font-size: var(--mf-text-xs);
  font-weight: 600;
}
.mf-pulse__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--mf-color-success);
  box-shadow: 0 0 0 4px rgba(14, 124, 90, 0.18);
}

/* === role pill === */
.mf-role-pill {
  font-size: 0.6rem;
  font-weight: 700;
  padding: 0.12rem 0.45rem;
  border-radius: var(--mf-radius-pill);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.mf-role-pill--member   { background: #e8f5ff; color: #1864ab; }
.mf-role-pill--operator { background: var(--mf-color-warn-bg); color: var(--mf-color-warn); }
.mf-role-pill--admin    { background: var(--mf-color-warn-bg); color: var(--mf-color-warn); }

/* === version chip (dev only — hidden in prod by design-tokens.css selector) === */
.mf-ver-chip {
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--mf-color-warn);
  background: var(--mf-color-warn-bg);
  padding: 0.18rem 0.5rem;
  border-radius: var(--mf-radius-pill);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-family: var(--mf-font-mono);
}
```

- [x] **Step 2: Commit**

```bash
git add static/css/components.css
git commit -m "feat(ux): scaffold components.css with shared base classes

pill / toggle / seg / pulse / role-pill / version-chip / card. All values
reference design-tokens.css custom properties — no hardcoded hex outside
tokens. Plan 1B and later append component-specific styles here."
```

---

### Task 4: User preferences DB migration

**Files:**
- Create: `core/db/migrations/<NNN>_user_preferences.py` (next free integer)
- Create: `tests/test_user_preferences_migration.py`

- [x] **Step 1: Confirm next migration number and the migration framework convention**

Run: `ls core/db/migrations/ | sort | tail -5`

Pick the next integer. Then read the most recent migration file to confirm the function signatures and conventions (some projects use `upgrade(conn)`, some use raw SQL files, some use Alembic). The example below uses an `async upgrade(conn)` / `async downgrade(conn)` shape — adapt to whatever convention this repo uses.

- [x] **Step 2: Write the failing test**

Create `tests/test_user_preferences_migration.py`:

```python
import json
import pytest
import aiosqlite


@pytest.mark.asyncio
async def test_user_preferences_table_created(tmp_path, run_migrations):
    """After migrations, user_preferences table exists with the right columns."""
    db = tmp_path / "test.db"
    await run_migrations(db)
    async with aiosqlite.connect(db) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "user_preferences table not created"

        async with conn.execute("PRAGMA table_info(user_preferences)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        assert {"user_id", "value", "schema_ver", "updated_at"}.issubset(cols)


@pytest.mark.asyncio
async def test_user_preferences_roundtrip(tmp_path, run_migrations):
    """Insert and read back a preference value."""
    db = tmp_path / "test.db"
    await run_migrations(db)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO user_preferences (user_id, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("xerxes@local46.org", json.dumps({"layout": "minimal", "density": "cards"})),
        )
        await conn.commit()
        async with conn.execute(
            "SELECT value FROM user_preferences WHERE user_id = ?",
            ("xerxes@local46.org",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        prefs = json.loads(row[0])
        assert prefs["layout"] == "minimal"


@pytest.mark.asyncio
async def test_user_preferences_unique_per_user(tmp_path, run_migrations):
    """user_id is PRIMARY KEY — duplicate INSERT raises IntegrityError."""
    db = tmp_path / "test.db"
    await run_migrations(db)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO user_preferences (user_id, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("alice@local46.org", json.dumps({"layout": "minimal"})),
        )
        await conn.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO user_preferences (user_id, value, updated_at) "
                "VALUES (?, ?, datetime('now'))",
                ("alice@local46.org", json.dumps({"layout": "maximal"})),
            )
            await conn.commit()
```

The `run_migrations` fixture should already exist in `tests/conftest.py`. If not, create one that mirrors how the app applies migrations on startup.

- [x] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_user_preferences_migration.py -v`

Expected: FAIL — table doesn't exist.

- [x] **Step 4: Write the migration**

Create `core/db/migrations/<NNN>_user_preferences.py` (replace `<NNN>` with the actual next integer determined in Step 1):

```python
"""User preferences — portable across machines, keyed by UnionCore subject claim.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §10
"""
from __future__ import annotations
import aiosqlite


async def upgrade(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id     TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            schema_ver  INTEGER NOT NULL DEFAULT 1,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_preferences_updated_at "
        "ON user_preferences(updated_at)"
    )


async def downgrade(conn: aiosqlite.Connection) -> None:
    await conn.execute("DROP INDEX IF EXISTS idx_user_preferences_updated_at")
    await conn.execute("DROP TABLE IF EXISTS user_preferences")
```

If the project's migration framework uses different signatures (raw SQL, Alembic, etc.), adapt — the schema (table + index) stays identical.

- [x] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_user_preferences_migration.py -v`

Expected: 3 PASS.

- [x] **Step 6: Apply migration locally and confirm**

```bash
docker-compose up -d
docker-compose logs app | grep -iE "migrat|user_preferences" | tail
docker-compose exec app sqlite3 /app/markflow.db ".schema user_preferences"
```

Expected: the table schema printed back.

- [x] **Step 7: Commit**

```bash
git add core/db/migrations/*user_preferences.py tests/test_user_preferences_migration.py
git commit -m "feat(db): add user_preferences table

Stores portable per-user preferences keyed by UnionCore subject claim.
JSON value column with schema_ver for future shape changes. Indexed on
updated_at for housekeeping. Spec §10."
```

---

### Task 5: JWT role claim extraction

**Files:**
- Modify: `core/auth.py`
- Create: `tests/test_role_claim_extraction.py`

- [x] **Step 1: Read the existing auth module**

Run: `grep -n "decode\|verify_token\|claims\|jwt" core/auth.py | head -30`

Locate the function that returns parsed JWT claims (likely a dict). The new helpers will sit alongside it.

- [x] **Step 2: Write the failing test**

Create `tests/test_role_claim_extraction.py`:

```python
import pytest
from core.auth import extract_role, Role


def test_role_admin_from_claims():
    assert extract_role({"sub": "x@local46.org", "role": "admin"}) == Role.ADMIN


def test_role_operator_from_claims():
    assert extract_role({"sub": "x", "role": "operator"}) == Role.OPERATOR


def test_role_member_from_claims():
    assert extract_role({"sub": "x", "role": "member"}) == Role.MEMBER


def test_role_missing_defaults_to_member():
    """Defensive: if UnionCore omits role, treat as member (lowest privilege)."""
    assert extract_role({"sub": "x"}) == Role.MEMBER


def test_role_unknown_value_defaults_to_member():
    """Defensive: unknown role string -> member."""
    assert extract_role({"sub": "x", "role": "superuser"}) == Role.MEMBER


def test_role_case_insensitive():
    assert extract_role({"sub": "x", "role": "ADMIN"}) == Role.ADMIN


def test_role_hierarchy_comparison():
    """IntEnum: admin >= operator >= member for visibility gates."""
    assert Role.ADMIN >= Role.OPERATOR
    assert Role.OPERATOR >= Role.MEMBER
    assert Role.ADMIN >= Role.MEMBER
    assert not (Role.MEMBER >= Role.ADMIN)
```

- [x] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_role_claim_extraction.py -v`

Expected: FAIL — `Role` and `extract_role` don't exist.

- [x] **Step 4: Add the helpers to `core/auth.py`**

Append to `core/auth.py` (or insert near the existing claims-parsing section):

```python
import enum


class Role(enum.IntEnum):
    """Role hierarchy. Defined upstream in UnionCore; MarkFlow consumes via JWT.

    Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §11
    """
    MEMBER = 0
    OPERATOR = 1
    ADMIN = 2


_ROLE_BY_NAME = {
    "member": Role.MEMBER,
    "operator": Role.OPERATOR,
    "admin": Role.ADMIN,
}


def extract_role(claims: dict) -> Role:
    """Return the Role from a JWT claims dict.

    Defensive: missing or unknown role -> MEMBER (least privilege).
    Case-insensitive on the role string.
    """
    raw = (claims.get("role") or "").strip().lower()
    return _ROLE_BY_NAME.get(raw, Role.MEMBER)
```

If `core/auth.py` already imports `enum`, omit the duplicate import.

- [x] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_role_claim_extraction.py -v`

Expected: 7 PASS.

- [x] **Step 6: Commit**

```bash
git add core/auth.py tests/test_role_claim_extraction.py
git commit -m "feat(auth): extract role claim from JWT into Role enum

Role.MEMBER < OPERATOR < ADMIN (IntEnum so visibility gates can use '>=').
Defensive: missing or unknown role defaults to MEMBER. Spec §11
(UnionCore-bound role hierarchy)."
```

---

### Task 6: `/pipeline` -> `/activity` 301 redirect

**Files:**
- Modify: `main.py`
- Create: `tests/test_route_aliases.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_route_aliases.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def test_pipeline_redirects_to_activity(client):
    """Old /pipeline URL -> 301 to /activity."""
    r = client.get("/pipeline")
    assert r.status_code == 301
    assert r.headers["location"] == "/activity"


def test_pipeline_subpath_redirects(client):
    """Subpath preserved: /pipeline/foo -> /activity/foo."""
    r = client.get("/pipeline/jobs/123")
    assert r.status_code == 301
    assert r.headers["location"] == "/activity/jobs/123"


def test_activity_route_exists(client):
    """/activity route should not 404 (even if it 401s under auth)."""
    r = client.get("/activity")
    assert r.status_code != 404
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_route_aliases.py -v`

Expected: FAIL — `/pipeline` either doesn't exist or doesn't redirect.

- [x] **Step 3: Add the redirect to `main.py`**

Find the route registration section in `main.py`. Append:

```python
from fastapi.responses import RedirectResponse


# /pipeline -> /activity 301 alias (one-release deprecation window).
# Spec §1: route renamed during UX overhaul. Remove this alias one
# release after Plan 4 ships and confirm no internal links / bookmarks
# still hit /pipeline.
@app.get("/pipeline", include_in_schema=False)
@app.get("/pipeline/{rest:path}", include_in_schema=False)
async def _pipeline_alias(rest: str = ""):
    target = "/activity" + (("/" + rest) if rest else "")
    return RedirectResponse(target, status_code=301)


# Placeholder /activity handler — Plan 4 replaces this with the real
# Activity dashboard. Returns to home so the redirect target exists
# and tests pass.
@app.get("/activity", include_in_schema=False)
async def _activity_placeholder():
    return RedirectResponse("/", status_code=302)
```

If a real `/activity` handler already exists, omit the placeholder block.

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_route_aliases.py -v`

Expected: 3 PASS.

- [x] **Step 5: Commit**

```bash
git add main.py tests/test_route_aliases.py
git commit -m "feat(routes): add /pipeline -> /activity 301 alias

Spec §1: rename Pipeline -> Activity. Subpath-preserving redirect for
one-release deprecation window. Placeholder /activity handler returns
home until Plan 4 wires the real dashboard. Schedule alias removal in
the release after Plan 4."
```

---

### Task 7: Server-side preferences module

**Files:**
- Create: `core/preferences.py`
- Create: `tests/test_preferences.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_preferences.py`:

```python
import pytest
from core.preferences import (
    DEFAULT_PREFERENCES,
    get_preferences,
    set_preference,
    set_preferences,
    PREFERENCE_KEYS,
)


@pytest.mark.asyncio
async def test_default_preferences_returned_for_new_user(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    prefs = await get_preferences(db, "new@local46.org")
    assert prefs == DEFAULT_PREFERENCES


@pytest.mark.asyncio
async def test_set_then_get(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    await set_preference(db, "alice@local46.org", "layout", "minimal")
    prefs = await get_preferences(db, "alice@local46.org")
    assert prefs["layout"] == "minimal"


@pytest.mark.asyncio
async def test_unknown_key_rejected(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    with pytest.raises(ValueError, match="unknown preference"):
        await set_preference(db, "alice@local46.org", "not_a_real_key", "x")


@pytest.mark.asyncio
async def test_layout_value_validated(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    with pytest.raises(ValueError, match="invalid value"):
        await set_preference(db, "alice@local46.org", "layout", "extreme")


@pytest.mark.asyncio
async def test_partial_update_preserves_other_keys(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    await set_preference(db, "alice@local46.org", "layout", "recent")
    await set_preference(db, "alice@local46.org", "density", "list")
    prefs = await get_preferences(db, "alice@local46.org")
    assert prefs["layout"] == "recent"
    assert prefs["density"] == "list"


@pytest.mark.asyncio
async def test_bulk_set_preferences(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    await set_preferences(db, "alice@local46.org", {
        "layout": "minimal",
        "density": "compact",
        "advanced_actions_inline": True,
    })
    prefs = await get_preferences(db, "alice@local46.org")
    assert prefs["layout"] == "minimal"
    assert prefs["density"] == "compact"
    assert prefs["advanced_actions_inline"] is True


@pytest.mark.asyncio
async def test_recent_searches_capped_at_50(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    queries = [f"q{i}" for i in range(60)]
    await set_preference(db, "alice@local46.org", "recent_searches", queries)
    prefs = await get_preferences(db, "alice@local46.org")
    assert len(prefs["recent_searches"]) == 50
    assert prefs["recent_searches"][0] == "q10"
    assert prefs["recent_searches"][-1] == "q59"


@pytest.mark.asyncio
async def test_items_per_page_bounds(tmp_path, run_migrations):
    db = tmp_path / "test.db"
    await run_migrations(db)
    with pytest.raises(ValueError):
        await set_preference(db, "alice@local46.org", "items_per_page_cards", 0)
    with pytest.raises(ValueError):
        await set_preference(db, "alice@local46.org", "items_per_page_cards", 99999)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_preferences.py -v`

Expected: FAIL — `core.preferences` doesn't exist.

- [x] **Step 3: Implement the module**

Create `core/preferences.py`:

```python
"""User preferences — portable across machines.

Stored as a JSON blob keyed by user_id (UnionCore subject claim).
Validation happens at write time; reads always return a dict with all keys
present (defaults filled in for any missing).

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §10
"""
from __future__ import annotations
import json
from pathlib import Path
import aiosqlite
import structlog

log = structlog.get_logger(__name__)


SCHEMA_VER = 1


# Default values for every supported preference. Reads return these for
# missing keys; writes are rejected for keys not in this dict.
DEFAULT_PREFERENCES: dict = {
    # Layout (Spec §3)
    "layout":                    "minimal",   # 'maximal' | 'recent' | 'minimal'
    "density":                   "cards",     # 'cards' | 'compact' | 'list'
    "snippet_length":            "medium",    # 'short' | 'medium' | 'long'
    "show_file_thumbnails":      False,

    # Power-user gate (Spec §9)
    "advanced_actions_inline":   False,       # default off for member; UI initializes True for operator/admin

    # Search history (Spec §3 Recent layout, §10)
    "track_recent_searches":     True,
    "recent_searches":           [],          # list[str], capped to 50

    # Items-per-page per density mode (Spec §13 settings table)
    "items_per_page_cards":      24,
    "items_per_page_compact":    48,
    "items_per_page_list":       250,

    # Pinned (Spec §3 Maximal mode)
    "pinned_folders":            [],
    "pinned_topics":             [],
}


PREFERENCE_KEYS = set(DEFAULT_PREFERENCES.keys())


_ENUMS = {
    "layout":         {"maximal", "recent", "minimal"},
    "density":        {"cards", "compact", "list"},
    "snippet_length": {"short", "medium", "long"},
}
_BOOLS = {"show_file_thumbnails", "advanced_actions_inline", "track_recent_searches"}
_INTS  = {"items_per_page_cards", "items_per_page_compact", "items_per_page_list"}
_LISTS = {"pinned_folders", "pinned_topics"}


def _validate(key: str, value):
    """Return (possibly normalized) value if valid; raise ValueError otherwise."""
    if key in _ENUMS:
        if value not in _ENUMS[key]:
            raise ValueError(f"invalid value for {key}: {value!r}")
        return value
    if key in _BOOLS:
        if not isinstance(value, bool):
            raise ValueError(f"invalid value for {key}: must be bool")
        return value
    if key in _INTS:
        if not isinstance(value, int) or value <= 0 or value > 10000:
            raise ValueError(f"invalid value for {key}: must be 1..10000")
        return value
    if key in _LISTS:
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"invalid value for {key}: must be list[str]")
        return value
    if key == "recent_searches":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"invalid value for recent_searches: must be list[str]")
        return value[-50:]
    raise ValueError(f"unknown preference: {key}")


async def get_preferences(db_path: Path | str, user_id: str) -> dict:
    """Return user's prefs, with defaults filled in for any missing keys."""
    async with aiosqlite.connect(str(db_path)) as conn:
        async with conn.execute(
            "SELECT value FROM user_preferences WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    stored = json.loads(row[0]) if row else {}
    merged = dict(DEFAULT_PREFERENCES)
    merged.update({k: v for k, v in stored.items() if k in PREFERENCE_KEYS})
    return merged


async def set_preference(db_path: Path | str, user_id: str, key: str, value) -> None:
    """Validate + persist a single preference."""
    if key not in PREFERENCE_KEYS:
        raise ValueError(f"unknown preference: {key}")
    validated = _validate(key, value)
    current = await get_preferences(db_path, user_id)
    current[key] = validated
    await _write_all(db_path, user_id, current)


async def set_preferences(db_path: Path | str, user_id: str, updates: dict) -> None:
    """Validate + persist multiple preferences atomically."""
    validated = {}
    for k, v in updates.items():
        if k not in PREFERENCE_KEYS:
            raise ValueError(f"unknown preference: {k}")
        validated[k] = _validate(k, v)
    current = await get_preferences(db_path, user_id)
    current.update(validated)
    await _write_all(db_path, user_id, current)


async def _write_all(db_path: Path | str, user_id: str, prefs: dict) -> None:
    blob = json.dumps(prefs, separators=(",", ":"), sort_keys=True)
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(
            """
            INSERT INTO user_preferences (user_id, value, schema_ver, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT (user_id) DO UPDATE SET
              value      = excluded.value,
              schema_ver = excluded.schema_ver,
              updated_at = datetime('now')
            """,
            (user_id, blob, SCHEMA_VER),
        )
        await conn.commit()
    log.info("user_prefs_saved", user_id=user_id, keys=sorted(prefs.keys()))
```

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_preferences.py -v`

Expected: 8 PASS.

- [x] **Step 5: Commit**

```bash
git add core/preferences.py tests/test_preferences.py
git commit -m "feat(prefs): server-side preferences module with validation

Per-key validators for layout/density/snippet_length enums, bool flags,
positive ints, and list[str] (recent searches capped at 50). Reads
always return a complete dict with defaults filled in. Atomic upsert
per user. Spec §10."
```

---

### Task 8: GET / PUT `/api/preferences` endpoints

**Files:**
- Create: `api/routes/preferences.py`
- Modify: `main.py`
- Create: `tests/test_preferences_api.py`

- [x] **Step 1: Confirm the project's auth dependency**

Run: `grep -rn "Depends\|require_user\|current_user\|get_current_user" api/routes/*.py | head -10`

Pick whichever existing dependency yields an authenticated user with at least a `user_id` (or equivalent) attribute. Adapt the import below.

- [x] **Step 2: Write the failing test**

Create `tests/test_preferences_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_client(fake_jwt):
    """fake_jwt fixture should be defined in conftest.py to inject a
    valid JWT for the test user. Adapt to the project's existing auth
    test helpers."""
    return TestClient(
        app,
        headers={"Authorization": "Bearer " + fake_jwt("alice@local46.org", "member")},
    )


def test_get_preferences_returns_defaults(authed_client):
    r = authed_client.get("/api/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["layout"] == "minimal"
    assert body["density"] == "cards"


def test_put_preferences_persists(authed_client):
    r = authed_client.put(
        "/api/preferences",
        json={"layout": "recent", "density": "compact"},
    )
    assert r.status_code == 200
    r2 = authed_client.get("/api/preferences")
    assert r2.json()["layout"] == "recent"
    assert r2.json()["density"] == "compact"


def test_put_invalid_value_returns_400(authed_client):
    r = authed_client.put("/api/preferences", json={"layout": "extreme"})
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"].lower()


def test_put_unknown_key_returns_400(authed_client):
    r = authed_client.put("/api/preferences", json={"not_a_real_key": "x"})
    assert r.status_code == 400


def test_unauthenticated_returns_401():
    client = TestClient(app)
    r = client.get("/api/preferences")
    assert r.status_code == 401
```

- [x] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_preferences_api.py -v`

Expected: FAIL — endpoints don't exist.

- [x] **Step 4: Implement the routes**

Create `api/routes/preferences.py`:

```python
"""Preferences GET/PUT endpoints. Spec §10."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException, Depends

from core.preferences import get_preferences, set_preferences
from core.auth import require_user
from core.db.connection import get_db_path

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("")
async def read_preferences(user=Depends(require_user)):
    db = get_db_path()
    return await get_preferences(db, user.user_id)


@router.put("")
async def write_preferences(
    payload: dict[str, Any],
    user=Depends(require_user),
):
    db = get_db_path()
    try:
        await set_preferences(db, user.user_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await get_preferences(db, user.user_id)
```

If your project's auth dependency or DB-path helper has different names, adapt the imports. The dependency should yield an object with a `user_id` attribute (or equivalent) populated from the JWT `sub` claim.

- [x] **Step 5: Wire the router into `main.py`**

Add to `main.py` (with the other `app.include_router` calls):

```python
from api.routes import preferences as preferences_routes
app.include_router(preferences_routes.router)
```

- [x] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_preferences_api.py -v`

Expected: 5 PASS.

- [x] **Step 7: Commit**

```bash
git add api/routes/preferences.py main.py tests/test_preferences_api.py
git commit -m "feat(api): GET/PUT /api/preferences endpoints

Authenticated. PUT validates payload via core/preferences (ValueError
-> 400). Unauthenticated -> 401. GET always returns a complete dict
with defaults filled in. Spec §10."
```

---

### Task 9: Mockup archive index page

**Files:**
- Create: `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/index.html`

Static HTML, no scripts. Devs/designers open one URL to browse all 16 mocks instead of guessing filenames.

- [x] **Step 1: Generate the index**

Create `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MarkFlow UX Overhaul — Mockup Archive</title>
  <style>
    body { font: 16px -apple-system, "SF Pro Display", Inter, system-ui, sans-serif;
           color: #1a1a1a; max-width: 880px; margin: 3rem auto; padding: 0 2rem;
           line-height: 1.5; }
    h1 { font-size: 2rem; letter-spacing: -0.02em; margin-bottom: 0.3rem; }
    .sub { color: #666; margin-bottom: 2rem; }
    h2 { font-size: 1.2rem; margin-top: 2rem; }
    ol { list-style: none; padding-left: 0; }
    li { padding: 0.6rem 0.8rem; border-radius: 8px; transition: background 0.15s;
         margin-bottom: 0.25rem; }
    li:hover { background: #f5f3ff; }
    a { color: #5b3df5; text-decoration: none; font-weight: 500; }
    .meta { color: #888; font-size: 0.85rem; margin-left: 0.5rem; }
    code { background: #f5f3ff; padding: 0.06rem 0.4rem; border-radius: 4px;
           font-family: ui-monospace, "SF Mono", monospace; font-size: 0.85rem;
           color: #5b3df5; }
  </style>
</head>
<body>
  <h1>MarkFlow UX Overhaul — Mockup Archive</h1>
  <p class="sub">Visual-fidelity reference for the v1 spec at <code>../2026-04-28-ux-overhaul-search-as-home-design.md</code>. Captured 2026-04-28. Mockups were rendered via the brainstorming visual companion's frame template — minor visual variation possible without it.</p>

  <h2>Visual identity exploration</h2>
  <ol>
    <li><a href="design-dna.html">design-dna.html</a><span class="meta">— common threads from Apple / Stripe / Airbnb references</span></li>
    <li><a href="convert-a-vs-b.html">convert-a-vs-b.html</a><span class="meta">— first A/B comparison on Convert page</span></li>
    <li><a href="full-product-a-vs-b.html">full-product-a-vs-b.html</a><span class="meta">— full-product feel comparison</span></li>
  </ol>

  <h2>Home page evolution</h2>
  <ol>
    <li><a href="home-search.html">home-search.html</a><span class="meta">— v1: gradient thumb cards</span></li>
    <li><a href="home-search-v2.html">home-search-v2.html</a><span class="meta">— v2: snippet thumbs + density toggle + expand</span></li>
    <li><a href="home-search-v3.html">home-search-v3.html</a><span class="meta">— v3 (final): gradient bands + role-aware rows + per-density pagination + version chip + avatar dropdown</span></li>
    <li><a href="home-layout-modes.html">home-layout-modes.html</a><span class="meta">— Maximal / Recent / Minimal layouts</span></li>
    <li><a href="layout-onboarding.html">layout-onboarding.html</a><span class="meta">— first-run picker + nav quick-toggle</span></li>
  </ol>

  <h2>Card interactions</h2>
  <ol>
    <li><a href="card-interactions.html">card-interactions.html</a><span class="meta">— hover preview, right-click menu, folder browse</span></li>
  </ol>

  <h2>Settings family</h2>
  <ol>
    <li><a href="settings-hybrid.html">settings-hybrid.html</a><span class="meta">— overview cards then scoped detail pattern</span></li>
    <li><a href="avatar-menu.html">avatar-menu.html</a><span class="meta">— role-gated settings menu</span></li>
    <li><a href="settings-detail-family.html">settings-detail-family.html</a><span class="meta">— Pipeline detail + 5 other taxonomies</span></li>
    <li><a href="settings-three-details.html">settings-three-details.html</a><span class="meta">— AI providers / Notifications / Account &amp; auth</span></li>
    <li><a href="cost-deep-dive.html">cost-deep-dive.html</a><span class="meta">— cost cap drill-down + CSV import</span></li>
  </ol>

  <h2>Operator dashboard</h2>
  <ol>
    <li><a href="activity-page.html">activity-page.html</a><span class="meta">— "Pipeline" -> "Activity" rename + dashboard layout</span></li>
  </ol>

  <h2>Recap</h2>
  <ol>
    <li><a href="recap.html">recap.html</a><span class="meta">— locked decisions + next-up choices</span></li>
  </ol>
</body>
</html>
```

- [x] **Step 2: Smoke check**

Open `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/index.html` directly in a browser (file:// is fine for static HTML). All 16 links resolve to existing files in the same directory.

- [x] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/index.html
git commit -m "docs(ux): add mockup archive index page

Single landing page linking all 16 brainstorm mockups grouped by purpose.
Devs/designers open one URL to browse every visual reference for the
v1 spec."
```

---

### Task 10: `CLAUDE.md` update — architecture references

**Files:**
- Modify: `CLAUDE.md`

- [x] **Step 1: Append architecture reminders**

In `CLAUDE.md`, find the `## Architecture Reminders` section. Append (preserve existing items):

```markdown
- **User preferences are portable** — `core/preferences.py` stores per-user prefs (layout, density, etc.) in `user_preferences` table keyed by UnionCore subject claim. Client mirror in `localStorage` via `static/js/preferences.js` (Plan 1B) with debounced server sync. Spec: `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §10.
- **Role hierarchy from JWT** — `core.auth.Role` IntEnum (MEMBER=0 < OPERATOR=1 < ADMIN=2). Use `extract_role(claims)` and `role >= Role.OPERATOR` for visibility gates. Spec §11.
- **`ENABLE_NEW_UX` feature flag** — gates new UX rendering across Plans 1B and beyond. Default off in prod until phase 4 ships. Read via `core.feature_flags.is_new_ux_enabled()`.
- **Design tokens are CSS variables** — `static/css/design-tokens.css` is the single source of truth for colors, type, spacing, shadows. Never hardcode hex outside that file. Component CSS in `static/css/components.css` consumes tokens via `var(--mf-*)`.
```

- [x] **Step 2: Append critical files**

Find the `## Critical Files` table. Append rows (preserve existing rows):

```markdown
| `core/preferences.py` | Server-side user preferences (portable, JSON value, schema versioned) |
| `core/feature_flags.py` | Feature flag accessors (e.g. `ENABLE_NEW_UX`) |
| `static/css/design-tokens.css` | Visual system as CSS variables — single source of truth |
| `static/css/components.css` | Shared component classes (pills, toggles, segmented, pulse, role pill, version chip) |
```

- [x] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(ux): CLAUDE.md — UX overhaul architecture references

Four architecture reminders (portable prefs, role hierarchy, feature
flag, design tokens) and four Critical Files rows. Cross-references
the v1 spec for deeper context."
```

---

## Acceptance check (run before declaring this plan complete)

- [x] `pytest tests/test_feature_flag.py tests/test_user_preferences_migration.py tests/test_role_claim_extraction.py tests/test_route_aliases.py tests/test_preferences.py tests/test_preferences_api.py -v` — all pass
- [x] `docker-compose up -d` succeeds, app starts, no migration errors in logs
- [x] `docker-compose exec app sqlite3 /app/markflow.db ".schema user_preferences"` returns the table schema
- [x] `curl -i http://localhost:8000/pipeline` shows `301` to `/activity`
- [x] `curl -i http://localhost:8000/static/css/design-tokens.css` returns 200 + CSS body
- [x] `git log --oneline | head -12` shows ~10 task commits in order

Once all green, **Plan 1A is done**. The next plan in the sequence is `2026-04-28-ux-overhaul-shared-chrome.md` (Plan 1B — JS components for top nav, version chip, avatar menu, layout icon, preferences client). Plan 1B explicitly uses safe DOM construction (`document.createElement` + `textContent`) to avoid XSS — no `innerHTML` with template literals.

---

## Self-review

**Spec coverage:**
- §1 (route rename, `/pipeline` -> `/activity` 301): ✓ Task 6
- §2 (visual system): ✓ Task 2 (design tokens) + Task 3 (components.css scaffold)
- §10 (portable preferences): ✓ Task 4 (DB) + Task 7 (server module) + Task 8 (HTTP)
- §11 (role binding): ✓ Task 5 (Role enum + extract_role)
- §13 (preflight setup, in scope for this plan): ✓ Task 1 (flag), 2 (tokens), 4 (migration), 5 (role), 6 (alias), 9 (mockup index), 10 (CLAUDE.md)

**Spec coverage gaps for this plan (deferred to later plans):**
- §3 (Search-as-home, layout modes) → Plan 1C / Plan 3
- §4 (document card) → Plan 2
- §6 (avatar menu chrome) → Plan 1B
- §7 (settings detail pages) → Plans 4–7
- §8 (cost deep-dive) → Plan 6+
- §9 (power-user gate UI) → Plan 1B (field) + Plan 2 (consumer)
- §12 (telemetry events, bundle baseline, browser matrix) → Plan 1B (telemetry helper); bundle/browser are operational concerns documented in spec §13

**Placeholder scan:** No TODOs, no "fill in details", no "similar to Task N" — every task contains the actual code. Migration number is `<NNN>` because it depends on the repo's current state (Step 1 of Task 4 resolves it).

**Type consistency:** `Role` enum + `extract_role` consistent across Task 5 use-sites. Preferences key set defined once in `DEFAULT_PREFERENCES` (Task 7), referenced as `PREFERENCE_KEYS` everywhere (Tasks 7, 8). DB column names (`user_id`, `value`, `schema_ver`, `updated_at`) match between migration (Task 4), tests (Tasks 4, 7, 8), and module (Task 7).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-foundation-setup.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — run tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints

Which approach?
