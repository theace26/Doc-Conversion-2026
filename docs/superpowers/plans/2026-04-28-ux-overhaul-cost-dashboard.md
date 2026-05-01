# UX Overhaul — Cost Cap & Alerts Dashboard Plan (Plan 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Cost cap & alerts deep-dive sub-page at `/settings/ai-providers/cost`. The page **re-shapes based on active provider count** (single-provider vs. multi-provider layouts), supports CSV-driven rate import (drag-drop or paste), persists cost caps + alert thresholds, and ships the operator-facing CSV format reference at `docs/help/cost-rates-csv-format.md`.

**Architecture:** New page reuses Plan 5's `MFSettingsDetail` shell with custom sub-section ordering (groups: COST → RATES BY PROVIDER → DATA → NOTIFY). New backend endpoint `POST /api/admin/llm-costs/import-csv` accepts a raw CSV body (or multipart upload) and writes parsed rows into the existing rate store, replacing or upserting based on `(provider, model, effective_date)`. New aggregator `GET /api/analysis/cost/dashboard` returns one payload (today / month / active providers / breakdown / 30-day history) so the page renders from a single fetch and re-shapes client-side. Re-auth gate (Plan 6) wraps every save. **Safe DOM throughout.**

**Tech stack:** Python 3.11 · FastAPI · pytest · vanilla JS · existing `/api/admin/llm-costs/*` + `/api/analysis/cost/*` (v0.33.x cost estimation) · `MFSettingsDetail` + `MFFormControls` (Plan 5) · `MFReauthGate` (Plan 6)

**Spec:** `docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md` §8 (Cost cap & alerts drill-down — sidebar groups, dynamic per-provider behavior, CSV import + format, help file)

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/cost-deep-dive.html`

**Out of scope (deferred):**
- Real-time cost streaming (SSE per-call updates) — v1.1
- Per-tenant cost segregation (UnionCore tenant claim → separate spend buckets) — separate plan once UnionCore exposes the claim
- Forecasting (model spend trajectory based on rolling-7-day average) — v1.1; the 30-day history sparkline is the v1 surface
- Auto-disable on cap exceeded — alerts only in v1; the operator decides what to do
- Member-facing cost visibility — admin/operator only

**Prerequisites:** Plans 1A through 6 complete. In particular, `/settings/ai-providers` exists (Plan 6 Task 3) with the Cost sub-section linking here, and `MFReauthGate.requireFresh(300)` is mountable (Plan 6 Task 1).

---

## File structure (this plan creates / modifies)

**Create:**
- `api/routes/cost_dashboard.py` — `GET /api/analysis/cost/dashboard` (aggregator) + `POST /api/admin/llm-costs/import-csv`
- `static/settings-cost.html`
- `static/js/pages/settings-cost.js` — `MFCostDashboard.mount(slot)` (the page component)
- `static/js/settings-cost-boot.js`
- `docs/help/cost-rates-csv-format.md` — operator-facing CSV format reference
- `tests/test_cost_dashboard_endpoint.py` — 4 tests
- `tests/test_csv_import_endpoint.py` — 5 tests

**Modify:**
- `static/css/components.css` — append cost-dashboard-specific styles (drag-drop area, code block, stacked chart)
- `main.py` — register `cost_dashboard` router; add `/settings/ai-providers/cost` flag-aware route

---

## Task 1: `GET /api/analysis/cost/dashboard` aggregator

**Files:**
- Create: `api/routes/cost_dashboard.py` (the aggregator endpoint only — CSV import goes in Task 2)
- Create: `tests/test_cost_dashboard_endpoint.py`
- Modify: `main.py`

Returns one payload the page renders from. Today / month spend, active providers, model-level breakdown, 30-day history, current caps + alert thresholds. Re-shapes happen client-side.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cost_dashboard_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_admin_client(fake_jwt):
    return TestClient(app, headers={"Authorization": "Bearer " + fake_jwt("xerxes@local46.org", "admin")})


@pytest.fixture
def authed_member_client(fake_jwt):
    return TestClient(app, headers={"Authorization": "Bearer " + fake_jwt("sarah@local46.org", "member")})


def test_dashboard_admin_can_read(authed_admin_client):
    r = authed_admin_client.get("/api/analysis/cost/dashboard")
    assert r.status_code == 200
    body = r.json()
    for key in ("today", "month", "active_providers", "breakdown", "history", "caps", "alerts"):
        assert key in body, f"missing key: {key}"
    assert isinstance(body["active_providers"], list)
    assert isinstance(body["history"], list)
    assert "daily_usd" in body["caps"]
    assert "monthly_usd" in body["caps"]


def test_dashboard_member_forbidden(authed_member_client):
    r = authed_member_client.get("/api/analysis/cost/dashboard")
    assert r.status_code == 403


def test_dashboard_unauthenticated_401():
    client = TestClient(app)
    r = client.get("/api/analysis/cost/dashboard")
    assert r.status_code == 401


def test_dashboard_history_returns_30_days(authed_admin_client):
    body = authed_admin_client.get("/api/analysis/cost/dashboard").json()
    # Front-end expects exactly 30 entries (zero-padded if no spend); list
    # length matters because the chart uses index → x-axis position.
    assert len(body["history"]) == 30
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_cost_dashboard_endpoint.py -v`

Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Implement the endpoint**

Create `api/routes/cost_dashboard.py`:

```python
"""Cost cap & alerts dashboard aggregator.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §8
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_user, extract_role, Role
from core.db.preferences import get_all_preferences
from core import llm_costs as cost_mod  # existing v0.33 module that backs /api/analysis/cost/*

router = APIRouter(prefix="/api/analysis/cost", tags=["cost"])


def _require_operator_or_admin(user=Depends(require_user)):
    role = extract_role(user.claims if hasattr(user, "claims") else {"role": getattr(user, "role", "member")})
    if role < Role.OPERATOR:
        raise HTTPException(status_code=403, detail="operator/admin only")
    return user


@router.get("/dashboard")
async def dashboard(user=Depends(_require_operator_or_admin)):
    """One-shot payload for /settings/ai-providers/cost. Re-shapes client-side
    based on len(active_providers)."""
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)

    today_spend, month_spend, active, breakdown, history_rows, prefs = await asyncio.gather(
        cost_mod.spend_in_range(today, today + timedelta(days=1)),
        cost_mod.spend_in_range(month_start, today + timedelta(days=1)),
        cost_mod.active_providers(),  # returns list of {name, has_recent_calls}
        cost_mod.spend_breakdown(month_start, today + timedelta(days=1)),
        cost_mod.daily_spend(today - timedelta(days=29), today + timedelta(days=1)),
        get_all_preferences(),
    )

    # Zero-pad history to exactly 30 days (chart depends on fixed length)
    by_day = {row["date"]: row["usd"] for row in history_rows}
    history = []
    for i in range(30):
        d = (today - timedelta(days=29 - i)).isoformat()
        history.append({"date": d, "usd": by_day.get(d, 0.0)})

    return {
        "today":  {"usd": today_spend},
        "month":  {"usd": month_spend},
        "active_providers": active,
        "breakdown": breakdown,  # list of {provider, model, calls, input_tok, output_tok, usd}
        "history":  history,
        "caps":   {
            "daily_usd":   float(prefs.get("cost_cap_daily_usd", "0") or 0),
            "monthly_usd": float(prefs.get("cost_cap_monthly_usd", "0") or 0),
        },
        "alerts": {
            "email":      prefs.get("cost_alert_email", ""),
            "warn_at_pct":  int(prefs.get("cost_alert_warn_at_pct", "75") or 75),
            "block_at_pct": int(prefs.get("cost_alert_block_at_pct", "100") or 100),
        },
    }
```

If `core/llm_costs.py` exposes different function names (e.g., `get_spend_period` instead of `spend_in_range`), adapt the calls — keep the response shape stable since the tests + front-end depend on it.

- [ ] **Step 4: Wire into `main.py`**

```python
from api.routes import cost_dashboard as cost_dashboard_routes
app.include_router(cost_dashboard_routes.router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `pytest tests/test_cost_dashboard_endpoint.py -v`

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/cost_dashboard.py main.py tests/test_cost_dashboard_endpoint.py
git commit -m "feat(api): GET /api/analysis/cost/dashboard aggregator

One payload powers the cost dashboard: today + month spend, active
providers, model-level breakdown, 30-day history (zero-padded),
current caps + alert thresholds. Operator/admin only. Spec §8."
```

---

## Task 2: `POST /api/admin/llm-costs/import-csv`

**Files:**
- Modify: `api/routes/cost_dashboard.py` (append the import endpoint)
- Create: `tests/test_csv_import_endpoint.py`

Accepts raw CSV (text/csv) **or** multipart file upload. Parses, validates, upserts into the rate store. Returns `{ rows_upserted, rows_skipped, errors }`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_csv_import_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def authed_admin_client(fake_jwt):
    return TestClient(app, headers={"Authorization": "Bearer " + fake_jwt("xerxes@local46.org", "admin")})


VALID_CSV = """provider,model,input_per_1m,output_per_1m,cache_write_per_1m,cache_read_per_1m,vision_per_image,batch_discount_pct,effective_date
anthropic,claude-sonnet-4-6,3.00,15.00,3.75,0.30,,50,2026-04-01
anthropic,claude-haiku-4-5-20251001,0.25,1.25,,,,,2026-04-01
openai,gpt-4o,2.50,10.00,,,0.001275,,2026-04-01
"""


def test_import_valid_csv_upserts(authed_admin_client):
    r = authed_admin_client.post(
        "/api/admin/llm-costs/import-csv",
        content=VALID_CSV.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rows_upserted"] == 3
    assert body["rows_skipped"] == 0
    assert body["errors"] == []


def test_import_missing_required_column_returns_422(authed_admin_client):
    bad = "provider,model,input_per_1m\nanthropic,claude-x,3.00\n"  # missing output_per_1m
    r = authed_admin_client.post(
        "/api/admin/llm-costs/import-csv",
        content=bad.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
    )
    assert r.status_code == 422


def test_import_per_row_errors_returned(authed_admin_client):
    """Mixed valid + invalid rows: valid get upserted, invalid get reported."""
    mixed = (
        "provider,model,input_per_1m,output_per_1m\n"
        "anthropic,good,3.00,15.00\n"
        "openai,bad,not-a-number,15.00\n"
    )
    r = authed_admin_client.post(
        "/api/admin/llm-costs/import-csv",
        content=mixed.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rows_upserted"] == 1
    assert body["rows_skipped"] == 1
    assert len(body["errors"]) == 1
    assert "row 2" in body["errors"][0].lower() or "input_per_1m" in body["errors"][0]


def test_import_member_forbidden(fake_jwt):
    member = TestClient(app, headers={"Authorization": "Bearer " + fake_jwt("u@local.org", "member")})
    r = member.post("/api/admin/llm-costs/import-csv", content=VALID_CSV.encode("utf-8"),
                    headers={"Content-Type": "text/csv"})
    assert r.status_code in (403, 401)


def test_import_unauthenticated_401():
    client = TestClient(app)
    r = client.post("/api/admin/llm-costs/import-csv", content=VALID_CSV.encode("utf-8"),
                    headers={"Content-Type": "text/csv"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_csv_import_endpoint.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the endpoint**

Append to `api/routes/cost_dashboard.py`:

```python
import csv
import io
from fastapi import Body, Request

REQUIRED_COLS = {"provider", "model", "input_per_1m", "output_per_1m"}
OPTIONAL_COLS = {"cache_write_per_1m", "cache_read_per_1m", "vision_per_image", "batch_discount_pct", "effective_date"}
ALL_COLS = REQUIRED_COLS | OPTIONAL_COLS


def _parse_decimal(s: str, field: str, row: int) -> float | None:
    """Empty cells mean 'doesn't apply' — return None, not 0.0."""
    if s is None or s.strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"row {row}: {field} is not a number: {s!r}")


@router.post("/import-csv", include_in_schema=True)
async def import_csv(request: Request, user=Depends(_require_operator_or_admin)):
    raw = (await request.body()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_COLS - headers
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required columns: {sorted(missing)}")

    upserted = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):  # start=2 because row 1 is the header
        try:
            entry = {
                "provider":           (row.get("provider") or "").strip().lower(),
                "model":              (row.get("model") or "").strip(),
                "input_per_1m":       _parse_decimal(row.get("input_per_1m", ""), "input_per_1m", i),
                "output_per_1m":      _parse_decimal(row.get("output_per_1m", ""), "output_per_1m", i),
                "cache_write_per_1m": _parse_decimal(row.get("cache_write_per_1m", ""), "cache_write_per_1m", i),
                "cache_read_per_1m":  _parse_decimal(row.get("cache_read_per_1m", ""), "cache_read_per_1m", i),
                "vision_per_image":   _parse_decimal(row.get("vision_per_image", ""), "vision_per_image", i),
                "batch_discount_pct": _parse_decimal(row.get("batch_discount_pct", ""), "batch_discount_pct", i),
                "effective_date":     (row.get("effective_date") or "").strip() or None,
            }
            if not entry["provider"] or not entry["model"]:
                raise ValueError(f"row {i}: provider and model are required")
            if entry["input_per_1m"] is None or entry["output_per_1m"] is None:
                raise ValueError(f"row {i}: input_per_1m and output_per_1m are required")
            await cost_mod.upsert_rate(**entry)
            upserted += 1
        except ValueError as e:
            skipped += 1
            errors.append(str(e))
        except Exception as e:
            skipped += 1
            errors.append(f"row {i}: {e}")

    return {"rows_upserted": upserted, "rows_skipped": skipped, "errors": errors}
```

If `core/llm_costs.py` doesn't expose `upsert_rate`, add a thin wrapper there that calls into the existing rate-store schema. The CSV layer must not bypass the existing data model.

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest tests/test_csv_import_endpoint.py -v`

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routes/cost_dashboard.py tests/test_csv_import_endpoint.py
git commit -m "feat(api): POST /api/admin/llm-costs/import-csv

Accepts text/csv body, validates required columns (provider, model,
input_per_1m, output_per_1m), upserts row-by-row, reports per-row
errors without aborting the whole import. Empty optional cells mean
'doesn't apply' (None, not 0.0). Operator/admin only. Spec §8."
```

---

## Task 3: CSV format help file

**Files:**
- Create: `docs/help/cost-rates-csv-format.md`

Operator-facing reference. Linked from the cost dashboard's CSV import sub-section. Per CLAUDE.md "user-facing help articles rendered in the in-app help drawer", this lives in `docs/help/`.

- [ ] **Step 1: Write the help file**

Create `docs/help/cost-rates-csv-format.md`:

```markdown
# Cost Rates CSV Format

Use this format when importing per-model cost rates into MarkFlow.

## Required columns

| Column | Description |
|--------|-------------|
| `provider` | Lowercase provider ID. One of: `anthropic`, `openai`, `local`. |
| `model` | Model ID exactly as the provider returns it (e.g., `claude-sonnet-4-6`, `gpt-4o`). Match must be exact — case-sensitive. |
| `input_per_1m` | USD per 1 million input tokens. |
| `output_per_1m` | USD per 1 million output tokens. |

## Optional columns

| Column | Description |
|--------|-------------|
| `cache_write_per_1m` | USD per 1M tokens for prompt-cache writes (Anthropic). |
| `cache_read_per_1m` | USD per 1M tokens for prompt-cache reads (Anthropic). |
| `vision_per_image` | USD per image for vision models. |
| `batch_discount_pct` | Integer percentage discount when using the batch API (e.g. `50` for Anthropic batch). |
| `effective_date` | ISO date (YYYY-MM-DD). MarkFlow keeps history; the most recent row before "now" wins. Useful when prices change mid-month. |

## Empty cells

Empty cells mean **"doesn't apply"** — not zero. A blank `vision_per_image` means the model has no vision pricing, not that vision is free.

## Encoding

UTF-8 only. Files saved as Windows-1252 (the default for Excel on Windows when "Save As CSV" is chosen) won't import — re-save as **CSV UTF-8** in Excel, or use Notepad / VS Code.

## Canonical example

```csv
provider,model,input_per_1m,output_per_1m,cache_write_per_1m,cache_read_per_1m,vision_per_image,batch_discount_pct,effective_date
anthropic,claude-sonnet-4-6,3.00,15.00,3.75,0.30,,50,2026-04-01
anthropic,claude-haiku-4-5-20251001,0.25,1.25,,,,,2026-04-01
anthropic,claude-opus-4-7,15.00,75.00,18.75,1.50,,50,2026-04-01
openai,gpt-4o,2.50,10.00,,,0.001275,,2026-04-01
local,blip-base,0.00,0.00,,,,,2026-04-01
```

## Provider pricing changes

Providers change pricing without notice. **Verify against the provider's pricing page before relying on cost numbers for budgeting.** This file is your record, not theirs.

## Importing

1. Settings → AI providers → Cost cap & alerts → **Sources & CSV import**
2. Drag the CSV onto the upload area, or click **Choose file**, or paste the CSV text into the **Paste from clipboard** input
3. Review the live preview — color-coded by valid / invalid row
4. Click **Import**
5. Per-row errors appear inline; valid rows import even if some rows fail
```

- [ ] **Step 2: Commit**

```bash
git add docs/help/cost-rates-csv-format.md
git commit -m "docs(help): cost-rates-csv-format reference

Operator-facing CSV format guide linked from the new cost dashboard's
Sources & CSV import sub-section. Spec §8."
```

---

## Task 4: Cost dashboard page (`MFCostDashboard`)

**Files:**
- Create: `static/settings-cost.html`
- Create: `static/js/pages/settings-cost.js`
- Create: `static/js/settings-cost-boot.js`
- Modify: `static/css/components.css`
- Modify: `main.py`

The page mounts `MFSettingsDetail` with the §8 sidebar groups. Dynamic sub-section list comes from the dashboard payload — the **RATES BY PROVIDER** group nests one entry per active provider (computed client-side from `dashboard.active_providers`).

- [ ] **Step 1: Append cost-dashboard CSS to `static/css/components.css`**

```css
/* === cost dashboard === */
.mf-cost-tiles { display: grid; gap: 0.85rem; margin-bottom: 1.6rem; }
.mf-cost-tiles--2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.mf-cost-tiles--3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.mf-cost-tile {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 1.2rem;
}
.mf-cost-tile__lab {
  font-size: var(--mf-text-xs);
  font-weight: 700;
  color: var(--mf-color-text-faint);
  text-transform: uppercase;
  letter-spacing: var(--mf-tracking-wide);
  margin-bottom: 0.4rem;
}
.mf-cost-tile__val {
  font-size: 1.85rem;
  line-height: 1.05;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--mf-color-text);
}
.mf-cost-chart {
  background: var(--mf-surface);
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 1.1rem 1.2rem;
  margin-bottom: 1.6rem;
}
.mf-cost-chart svg { width: 100%; height: 80px; }

.mf-csv-drop {
  background: linear-gradient(135deg, var(--mf-color-accent-tint), var(--mf-color-accent-tint-2));
  border: 2px dashed var(--mf-color-accent-border);
  border-radius: var(--mf-radius-card-lg);
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  margin-bottom: 1rem;
}
.mf-csv-drop--active { border-color: var(--mf-color-accent); background: var(--mf-color-accent-tint); }
.mf-csv-drop__icon { font-size: 3rem; color: var(--mf-color-accent); margin-bottom: 0.5rem; }
.mf-code {
  background: #1a1a1a;
  color: #e6e6e6;
  font-family: var(--mf-font-mono);
  font-size: 0.78rem;
  padding: 1rem 1.2rem;
  border-radius: var(--mf-radius-input);
  white-space: pre;
  overflow-x: auto;
}
.mf-code .mf-code__row--header  { color: #74c0fc; }
.mf-code .mf-code__row--ok      { color: #c0eb75; }
.mf-code .mf-code__row--err     { color: #ff8787; }
```

- [ ] **Step 2: Create the template**

Create `static/settings-cost.html` (mirror of Plan 5's `settings-storage.html`, swapping IDs to `mf-settings-cost` and adding the page-script + boot-script tags). Include `<script src="/static/js/components/reauth-gate.js"></script>` before `pages/settings-cost.js`.

- [ ] **Step 3: Create the boot**

Create `static/js/settings-cost-boot.js` (mirror of `settings-storage-boot.js` from Plan 5). Member-role redirect target stays `/settings`.

- [ ] **Step 4: Create the page component**

Create `static/js/pages/settings-cost.js`:

```javascript
/* MFCostDashboard — Settings → AI providers → Cost cap & alerts.
 * One-shot fetch from /api/analysis/cost/dashboard; sub-sections re-shape
 * based on len(active_providers). Spec §8. Safe DOM throughout. */
(function (global) {
  'use strict';

  var FC = null;
  var DATA = null;  // dashboard payload, mutated by sub-section saves

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }

  function fetchJson(url, init) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, init || {}))
      .then(function (r) {
        if (!r.ok) throw new Error(url + ' ' + r.status);
        if (r.status === 204) return null;
        return r.json();
      });
  }

  function gatedSave(saveFn) { return MFReauthGate.requireFresh(300).then(saveFn); }

  function buildSubsections(active) {
    var providers = active.filter(function (p) { return p.has_recent_calls || p.is_active; });
    var subs = [
      { id: 'overview', label: 'Overview',  icon: '◷', group: 'COST' },
    ];
    providers.forEach(function (p) {
      subs.push({ id: 'provider:' + p.name, label: p.label || p.name, icon: '◆',
                  group: 'RATES BY PROVIDER', nested: true });
    });
    subs.push({ id: 'csv',     label: 'Sources & CSV import', icon: '⬆', group: 'DATA' });
    subs.push({ id: 'history', label: 'Spend history',         icon: '⊿', group: 'DATA' });
    subs.push({ id: 'alerts',  label: 'Alerts & thresholds',   icon: '⚠', group: 'NOTIFY' });
    subs.push({ id: '__doclink__', label: 'CSV format reference ↗', icon: '⤴', group: 'EXTERNAL' });
    return subs;
  }

  // --- Overview -------------------------------------------------------------
  function renderOverview(formArea, ctx) {
    var single = DATA.active_providers.length === 1;

    var tiles = el('div', 'mf-cost-tiles ' + (single ? 'mf-cost-tiles--2' : 'mf-cost-tiles--3'));
    function tile(lab, val) {
      var t = el('div', 'mf-cost-tile');
      var l = el('div', 'mf-cost-tile__lab'); l.textContent = lab;
      var v = el('div', 'mf-cost-tile__val'); v.textContent = val;
      t.appendChild(l); t.appendChild(v); return t;
    }
    tiles.appendChild(tile('Spend today',     '$' + DATA.today.usd.toFixed(2)));
    tiles.appendChild(tile('Spend this month', '$' + DATA.month.usd.toFixed(2)));
    if (!single) {
      tiles.appendChild(tile('Active providers',
        DATA.active_providers.length + ' · ' + DATA.active_providers.map(function (p) { return p.name; }).join(', ')
      ));
    }
    formArea.appendChild(tiles);

    // Spend breakdown — single-provider gets a model-only table, multi gets provider+model+totals
    var rows;
    var cols;
    if (single) {
      cols = [
        { id: 'model',  label: 'Model',     fr: 1.6 },
        { id: 'calls',  label: 'Calls',     fr: 0.6 },
        { id: 'in_tok', label: 'Input tok', fr: 0.8 },
        { id: 'out_tok', label: 'Output tok', fr: 0.8 },
        { id: 'usd',     label: 'Spend',    fr: 0.7 },
      ];
      rows = DATA.breakdown.map(function (b) {
        return { model: b.model, calls: b.calls.toLocaleString(),
                 in_tok: b.input_tok.toLocaleString(), out_tok: b.output_tok.toLocaleString(),
                 usd: '$' + b.usd.toFixed(2) };
      });
    } else {
      cols = [
        { id: 'provider', label: 'Provider', fr: 1 },
        { id: 'model',    label: 'Model',    fr: 1.4 },
        { id: 'calls',    label: 'Calls',    fr: 0.6 },
        { id: 'usd',      label: 'Spend',    fr: 0.8 },
      ];
      rows = DATA.breakdown.map(function (b) {
        return { provider: b.provider, model: b.model, calls: b.calls.toLocaleString(), usd: '$' + b.usd.toFixed(2) };
      });
      // Totals row — bold
      var total = DATA.breakdown.reduce(function (acc, b) {
        acc.calls += b.calls; acc.usd += b.usd; return acc;
      }, { calls: 0, usd: 0 });
      rows.push({ provider: 'TOTAL', model: '', calls: total.calls.toLocaleString(),
                  usd: '$' + total.usd.toFixed(2), _tone: 'ok' });
    }
    formArea.appendChild(FC.formSection({
      title: single ? (DATA.active_providers[0].label || DATA.active_providers[0].name) + ' spend by model' : 'Spend breakdown · this month',
      body: FC.miniTable({ columns: cols, rows: rows }),
    }));

    // 30-day history sparkline (single-color when single provider, single-color in v1 either way)
    var spark = el('div', 'mf-cost-chart');
    var lab = el('div', 'mf-form-section__h'); lab.textContent = 'Last 30 days';
    spark.appendChild(lab);
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 800 80'); svg.setAttribute('preserveAspectRatio', 'none');
    var max = Math.max.apply(null, DATA.history.map(function (h) { return h.usd; })) || 0.01;
    var pts = DATA.history.map(function (h, i) {
      var x = (i / (DATA.history.length - 1)) * 800;
      var y = 80 - (h.usd / max) * 70 - 5;
      return x + ',' + y;
    }).join(' ');
    var line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', pts); line.setAttribute('fill', 'none');
    line.setAttribute('stroke', '#5b3df5'); line.setAttribute('stroke-width', '2');
    svg.appendChild(line);
    var fill = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    fill.setAttribute('points', '0,80 ' + pts + ' 800,80');
    fill.setAttribute('fill', 'rgba(91,61,245,0.08)'); fill.setAttribute('stroke', 'none');
    svg.appendChild(fill);
    spark.appendChild(svg);
    formArea.appendChild(spark);
  }

  // --- Per-provider rates -------------------------------------------------
  function renderProviderRates(providerName, formArea, ctx) {
    fetchJson('/api/admin/llm-costs?provider=' + encodeURIComponent(providerName)).then(function (data) {
      var rows = (data.rates || []).map(function (r) {
        return {
          model:    r.model,
          input:    '$' + Number(r.input_per_1m).toFixed(2),
          output:   '$' + Number(r.output_per_1m).toFixed(2),
          vision:   r.vision_per_image != null ? '$' + Number(r.vision_per_image).toFixed(4) : '—',
          batch:    r.batch_discount_pct != null ? r.batch_discount_pct + '%' : '—',
          effective: r.effective_date || '—',
        };
      });
      formArea.appendChild(FC.formSection({
        title: providerName + ' rates',
        desc: 'Current per-model rates. Edit via Sources & CSV import.',
        body: FC.miniTable({
          columns: [
            { id: 'model',    label: 'Model',     fr: 1.6 },
            { id: 'input',    label: 'In / 1M',   fr: 0.8 },
            { id: 'output',   label: 'Out / 1M',  fr: 0.8 },
            { id: 'vision',   label: 'Vision',    fr: 0.7 },
            { id: 'batch',    label: 'Batch %',   fr: 0.6 },
            { id: 'effective', label: 'Effective', fr: 0.9 },
          ],
          rows: rows,
        }),
      }));
    });
  }

  // --- Sources & CSV import -------------------------------------------------
  function renderCSV(formArea, ctx) {
    var drop = el('div', 'mf-csv-drop');
    drop.tabIndex = 0;
    drop.setAttribute('role', 'button');
    drop.setAttribute('aria-label', 'Drop CSV file or click to choose');
    var ico = el('div', 'mf-csv-drop__icon'); ico.textContent = '☁'; drop.appendChild(ico);
    var msg = el('div'); msg.style.cssText = 'font-weight:600;color:#0a0a0a';
    msg.textContent = 'Drop CSV here or click to choose'; drop.appendChild(msg);
    var sub = el('div'); sub.style.cssText = 'font-size:0.84rem;color:#5a5a5a;margin-top:0.3rem';
    sub.textContent = 'UTF-8 encoded — see CSV format reference for required columns'; drop.appendChild(sub);

    var fileInput = document.createElement('input');
    fileInput.type = 'file'; fileInput.accept = '.csv,text/csv';
    fileInput.style.display = 'none';

    drop.addEventListener('click', function () { fileInput.click(); });
    drop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } });
    drop.addEventListener('dragover', function (e) { e.preventDefault(); drop.classList.add('mf-csv-drop--active'); });
    drop.addEventListener('dragleave', function () { drop.classList.remove('mf-csv-drop--active'); });
    drop.addEventListener('drop', function (e) {
      e.preventDefault(); drop.classList.remove('mf-csv-drop--active');
      var f = (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) || null;
      if (f) handleFile(f);
    });
    fileInput.addEventListener('change', function (e) {
      var f = e.target.files && e.target.files[0]; if (f) handleFile(f);
    });

    formArea.appendChild(drop);
    formArea.appendChild(fileInput);

    // Paste-from-clipboard textarea (alt path)
    var pasteWrap = el('div'); pasteWrap.style.cssText = 'margin-bottom:1rem';
    var pasteLabel = el('span', 'mf-field-label'); pasteLabel.textContent = 'Or paste CSV text';
    pasteWrap.appendChild(pasteLabel);
    var pasteArea = document.createElement('textarea');
    pasteArea.className = 'mf-field-input';
    pasteArea.style.cssText = 'min-height:120px;font-family:ui-monospace,monospace;font-size:0.82rem;margin-top:0.4rem';
    pasteWrap.appendChild(pasteArea);
    var pasteBtn = el('button', 'mf-pill mf-pill--outline mf-pill--sm');
    pasteBtn.type = 'button'; pasteBtn.textContent = 'Import pasted text';
    pasteBtn.style.marginTop = '0.6rem';
    pasteBtn.addEventListener('click', function () { handleText(pasteArea.value); });
    pasteWrap.appendChild(pasteBtn);
    formArea.appendChild(pasteWrap);

    // Live preview block
    var previewWrap = el('div'); previewWrap.style.display = 'none';
    var previewLabel = el('span', 'mf-field-label'); previewLabel.textContent = 'Preview';
    previewWrap.appendChild(previewLabel);
    var preview = el('pre', 'mf-code'); previewWrap.appendChild(preview);
    formArea.appendChild(previewWrap);

    // Result block
    var resultWrap = el('div'); resultWrap.style.cssText = 'margin-top:1rem;display:none';
    formArea.appendChild(resultWrap);

    function handleFile(f) {
      var reader = new FileReader();
      reader.onload = function () { handleText(String(reader.result || '')); };
      reader.readAsText(f, 'utf-8');
    }

    function colorizePreview(text) {
      while (preview.firstChild) preview.removeChild(preview.firstChild);
      previewWrap.style.display = '';
      var lines = text.split(/\r?\n/);
      lines.forEach(function (line, i) {
        var span = document.createElement('span');
        if (i === 0) span.className = 'mf-code__row--header';
        else if (line.trim() === '') span.className = '';
        else if (line.split(',').length < 4) span.className = 'mf-code__row--err';
        else span.className = 'mf-code__row--ok';
        span.textContent = line + '\n';
        preview.appendChild(span);
      });
    }

    function showResult(r) {
      while (resultWrap.firstChild) resultWrap.removeChild(resultWrap.firstChild);
      resultWrap.style.display = '';
      var head = el('p'); head.style.cssText = 'margin:0 0 0.5rem;font-weight:600';
      head.textContent = r.rows_upserted + ' upserted · ' + r.rows_skipped + ' skipped';
      head.style.color = r.rows_skipped > 0 ? '#a36a00' : '#0e7c5a';
      resultWrap.appendChild(head);
      if (r.errors && r.errors.length) {
        var ul = el('ul'); ul.style.cssText = 'color:#c92a2a;font-size:0.84rem;margin:0;padding-left:1.2rem';
        r.errors.forEach(function (e) { var li = el('li'); li.textContent = e; ul.appendChild(li); });
        resultWrap.appendChild(ul);
      }
    }

    function handleText(text) {
      colorizePreview(text);
      gatedSave(function () {
        ctx.setStatus('saving', 'Importing…');
        return fetch('/api/admin/llm-costs/import-csv', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'text/csv' }, body: text,
        }).then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        });
      }).then(function (result) {
        showResult(result);
        ctx.setStatus(result.rows_skipped > 0 ? 'error' : 'saved',
          result.rows_skipped > 0 ? 'Some rows skipped' : 'Imported');
        MFTelemetry.emit('ui.cost_csv_import', {
          upserted: result.rows_upserted, skipped: result.rows_skipped,
        });
      }).catch(function (e) {
        if (e && e.message !== 'cancelled') ctx.setStatus('error', 'Import failed: ' + e.message);
        else ctx.setStatus('', '');
      });
    }
  }

  // --- Spend history -------------------------------------------------------
  function renderHistory(formArea, ctx) {
    formArea.appendChild(FC.formSection({
      title: 'Spend history · last 30 days',
      body: FC.miniTable({
        columns: [
          { id: 'date', label: 'Date',  fr: 1 },
          { id: 'usd',  label: 'Spend', fr: 1 },
        ],
        rows: DATA.history.slice().reverse().map(function (h) {
          return { date: h.date, usd: '$' + h.usd.toFixed(2) };
        }),
      }),
    }));
    ctx.setActions([
      { id: 'export', label: 'Export CSV', variant: 'outline',
        onClick: function () { window.location.href = '/api/analysis/cost/period.csv?days=30'; } },
    ]);
  }

  // --- Alerts & thresholds -------------------------------------------------
  function renderAlerts(formArea, ctx) {
    var caps = DATA.caps; var alerts = DATA.alerts;
    var draft = {
      cost_cap_daily_usd:       String(caps.daily_usd || ''),
      cost_cap_monthly_usd:     String(caps.monthly_usd || ''),
      cost_alert_email:         alerts.email || '',
      cost_alert_warn_at_pct:   String(alerts.warn_at_pct),
      cost_alert_block_at_pct:  String(alerts.block_at_pct),
    };
    var orig = Object.assign({}, draft);

    function txt(key, type, tight) {
      return FC.textInput({ value: draft[key], type: type || 'text', tight: !!tight,
        onInput: function (v) { draft[key] = v; ctx.markDirty(); } });
    }

    formArea.appendChild(FC.formSection({
      title: 'Spend caps',
      desc: 'Alerts fire when spend reaches a percentage of these caps. Caps do not auto-disable providers in v1 — they alert.',
      body: (function () {
        var grid = el('div'); grid.style.cssText = 'display:flex;gap:1rem';
        grid.appendChild(FC.fieldRow({ label: 'Daily ($)',   control: txt('cost_cap_daily_usd', 'number', true) }));
        grid.appendChild(FC.fieldRow({ label: 'Monthly ($)', control: txt('cost_cap_monthly_usd', 'number', true) }));
        return grid;
      })(),
    }));

    formArea.appendChild(FC.formSection({
      title: 'Alert thresholds',
      body: (function () {
        var grid = el('div'); grid.style.cssText = 'display:flex;gap:1rem';
        grid.appendChild(FC.fieldRow({ label: 'Warn at %',  control: txt('cost_alert_warn_at_pct',  'number', true),
          help: 'Send a non-blocking warning at this fraction of the cap.' }));
        grid.appendChild(FC.fieldRow({ label: 'Block at %', control: txt('cost_alert_block_at_pct', 'number', true),
          help: 'Critical alert at this fraction. (No auto-disable in v1.)' }));
        return grid;
      })(),
    }));

    formArea.appendChild(FC.formSection({
      title: 'Alert email',
      desc: 'Where alerts go. Leave blank to disable alerts entirely.',
      body: FC.fieldRow({ label: 'Email', control: txt('cost_alert_email') }),
    }));

    ctx.onSave(function () {
      gatedSave(function () {
        ctx.setStatus('saving', 'Saving…');
        var dirty = Object.keys(draft).filter(function (k) { return draft[k] !== orig[k]; });
        return Promise.all(dirty.map(function (k) {
          return fetch('/api/preferences/' + k, {
            method: 'PUT', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: draft[k] }),
          }).then(function (r) { if (!r.ok) throw new Error(k + ': ' + r.status); });
        }));
      }).then(function () { orig = Object.assign({}, draft); ctx.markClean();
        MFTelemetry.emit('ui.settings_save', { section: 'cost', sub: 'alerts' });
      }).catch(function (e) { if (e && e.message !== 'cancelled') ctx.setStatus('error', e.message); else ctx.setStatus('', ''); });
    });
  }

  function renderForm(activeId, formArea, ctx) {
    if (activeId === 'overview')   return renderOverview(formArea, ctx);
    if (activeId === 'csv')        return renderCSV(formArea, ctx);
    if (activeId === 'history')    return renderHistory(formArea, ctx);
    if (activeId === 'alerts')     return renderAlerts(formArea, ctx);
    if (activeId === '__doclink__') {
      window.open('/help#cost-rates-csv-format', '_blank');
      // Returning the user to overview after the new-tab open
      return renderOverview(formArea, ctx);
    }
    if (activeId.indexOf('provider:') === 0) {
      return renderProviderRates(activeId.slice('provider:'.length), formArea, ctx);
    }
  }

  function mount(slot) {
    if (!global.MFFormControls || !global.MFSettingsDetail || !global.MFReauthGate) {
      throw new Error('MFCostDashboard: deps missing');
    }
    FC = global.MFFormControls;
    fetchJson('/api/analysis/cost/dashboard').then(function (data) {
      DATA = data;
      MFSettingsDetail.mount(slot, {
        icon: '$',
        title: 'Cost cap & alerts.',
        subtitle: 'Spend, rates, alerts, and the rate-import pipeline.',
        subsections: buildSubsections(data.active_providers),
        activeId: 'overview',
        onSubsectionChange: function (id) {
          MFTelemetry.emit('ui.settings_subsection_change', { section: 'cost', sub: id });
        },
        renderForm: renderForm,
      });
    }).catch(function (e) {
      console.error('mf: cost dashboard load failed', e);
      var msg = el('div'); msg.style.cssText = 'padding:2rem;color:#888;text-align:center';
      msg.textContent = 'Cost dashboard unavailable. Check console.';
      slot.appendChild(msg);
    });
  }

  global.MFCostDashboard = { mount: mount };
})(window);
```

- [ ] **Step 5: Wire `/settings/ai-providers/cost` route in `main.py` (flag-aware)**

```python
@app.get("/settings/ai-providers/cost", include_in_schema=False)
async def settings_cost_page():
    if is_new_ux_enabled():
        return FileResponse("static/settings-cost.html")
    # Legacy fallback — providers.html exposes basic cost view
    return FileResponse("static/providers.html")
```

- [ ] **Step 6: Verify safe DOM**

Run: `grep -n "innerHTML" static/js/pages/settings-cost.js static/js/settings-cost-boot.js`

Expected: zero matches.

- [ ] **Step 7: Smoke verify**

```bash
docker-compose up -d --force-recreate markflow
```

As an admin user with `ENABLE_NEW_UX=true`:
- Visit `/settings/ai-providers` → click "Open cost dashboard →" → lands on `/settings/ai-providers/cost`
- **Single provider** state (only Anthropic active): top tiles are 2-up, breakdown table titled "Anthropic spend by model", sidebar's RATES BY PROVIDER group has one entry
- **Multi-provider** state (Anthropic + OpenAI active): top tiles 3-up, breakdown table has provider column + bold totals row, sidebar lists each provider as a nested entry
- Click each sub-section: Overview · Anthropic rates · (OpenAI rates) · Sources & CSV import · Spend history · Alerts & thresholds
- CSV import:
  - Drag the canonical example CSV from `docs/help/cost-rates-csv-format.md` onto the drop area → preview colorizes → re-auth gate fires (after 5min from login) → "3 upserted · 0 skipped"
  - Paste a row with a non-numeric `input_per_1m` → "Some rows skipped" with per-row error
- Alerts: edit cap values → save → re-fetch dashboard → values reflected
- "CSV format reference ↗" sidebar entry opens `/help#cost-rates-csv-format` in a new tab

- [ ] **Step 8: Commit**

```bash
git add static/settings-cost.html static/js/pages/settings-cost.js \
        static/js/settings-cost-boot.js static/css/components.css main.py
git commit -m "feat(ux): /settings/ai-providers/cost dashboard

One-shot fetch from /api/analysis/cost/dashboard powers Overview tiles,
spend breakdown, 30-day sparkline, per-provider rate tables. Sub-section
list re-shapes based on active_providers count (single vs multi). CSV
import via drag-drop / file picker / paste — colorized preview, per-row
errors, re-auth gate. Alerts & thresholds save to preferences. Spec §8."
```

---

## Task 5: Acceptance check + plan close

**Files:** none modified — verification only.

- [ ] `pytest tests/test_cost_dashboard_endpoint.py tests/test_csv_import_endpoint.py -v` — 9 PASS
- [ ] `grep -rn "innerHTML" static/js/pages/settings-cost.js static/js/settings-cost-boot.js` — zero matches
- [ ] As admin with `ENABLE_NEW_UX=true`:
  - `/settings/ai-providers/cost` loads from one fetch
  - Sub-section list correctly re-shapes for single vs multi-provider state (verify by toggling `is_active` on OpenAI in `/settings/ai-providers` and reloading the cost page)
  - CSV import end-to-end: drop file → preview → import → result block; per-row errors visible
  - Alerts save persists across reload
  - "CSV format reference ↗" sidebar item opens `/help#cost-rates-csv-format` in new tab
- [ ] As admin with `ENABLE_NEW_UX=false`:
  - `/settings/ai-providers/cost` falls back to legacy `/static/providers.html`
- [ ] As member with `ENABLE_NEW_UX=true`:
  - `/api/analysis/cost/dashboard` returns 403 (verified by Task 1's test)
  - Direct visit to `/settings/ai-providers/cost` redirects to `/settings` (boot redirect)
- [ ] Help drawer (`/help` page) renders the new `cost-rates-csv-format.md` article — verify by visiting `/help` and finding the article in the index
- [ ] Telemetry: `ui.cost_csv_import`, `ui.settings_save` (cost section), `ui.settings_subsection_change` visible in logs
- [ ] `git log --oneline | head -8` shows ~5 task commits

If any item fails, file in `docs/bug-log.md`. **Don't silently fix.**

Once all green, **Plan 7 is done**. Next plan: `2026-04-28-ux-overhaul-onboarding.md` (Plan 8 — first-run welcome + pin-folders steps).

---

## Self-review

**Spec coverage:**
- §8 sidebar groups (COST · RATES BY PROVIDER · DATA · NOTIFY + external doclink): ✓ Task 4 `buildSubsections`
- §8 dynamic per-provider behavior (single vs multi tiles + breakdown shape): ✓ Task 4 `renderOverview`
- §8 CSV import (drag-drop area, choose-file + paste, color-coded preview, per-provider source dropdown): ✓ Task 4 `renderCSV` (per-provider source dropdown is part of the existing AI providers detail page from Plan 6, not duplicated here)
- §8 CSV format (required + optional columns, empty cells = N/A, UTF-8): ✓ Task 2 + Task 3 help file
- §8 help file at `docs/help/cost-rates-csv-format.md`: ✓ Task 3

**Spec gaps for this plan (deferred):**
- Real-time SSE cost stream: v1.1 (declared out-of-scope at top)
- Auto-disable on cap exceeded: v1.1 (declared out-of-scope; v1 alerts only)
- Per-tenant cost segregation: separate plan once UnionCore exposes the tenant claim

**Placeholder scan:**
- No "TODO" / "TBD" in shipped task bodies
- The `MFCostDashboard` `__doclink__` sub-section's renderForm fallback returns to overview after `window.open` — that's deliberate, not a placeholder

**Type / API consistency:**
- `MFCostDashboard.mount(slot)` signature matches Plan 6's `MF<Section>Settings.mount(slot)` pattern
- `gatedSave` helper inlined per file (same pattern as Plan 6 — keep each page self-contained)
- Aggregator response keys (`today` / `month` / `active_providers` / `breakdown` / `history` / `caps` / `alerts`) match between Task 1 backend and Task 4 consumer; tests pin the shape

**Safe-DOM verification:**

```
grep -rn "innerHTML" static/js/pages/settings-cost.js static/js/settings-cost-boot.js
```

Expected: empty.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-ux-overhaul-cost-dashboard.md`.

Sized for: 5 implementer dispatches + 5 spec reviews + 5 code-quality reviews ≈ 15 subagent calls.

When ready to execute, two options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review per task
2. **Inline Execution** — `superpowers:executing-plans` in this session
