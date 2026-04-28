# Token + Cost Estimation Subsystem

**Status:** Plan — not implemented.
**Author:** v0.32.11 follow-up planning, 2026-04-28.
**Triggers a release:** Yes — three release cuts (one per phase). Suggested tags: `v0.33.1`, `v0.33.2`, `v0.33.3` (after the v0.33.0 Pipeline-cards merge).

---

## Background

MarkFlow's image-analysis queue talks to one of four LLM
vision providers (Anthropic / OpenAI / Gemini / Ollama). Each
analyzed file consumes tokens; cloud providers charge for
those tokens at published per-1M-token rates. As of v0.32.11
the operator can see the **count** of tokens used per row
(`analysis_queue.tokens_used`) but has no way to translate
that into **dollars**, no per-batch rollup, and no monthly
running-total view. They're flying blind on actual
provider-bill exposure.

The user's request, distilled:

> *"...estimate how many tokens would be used per batch ->
> clicking on the batch it would give an educated estimate
> on a per file basis how many tokens; With that, since
> these are API calls can estimate dollar amount be give per
> batch, per file, running total for the month <having the
> month be defined somewhere in the settings page>"*

User clarifications received during planning:

1. **Cost lookup**: JSON file, easy to update externally
2. **Per-file estimate logic** + **per-batch aggregate**: implementer's call (this plan picks the approach)
3. **Monthly running total**: lives as a **card on the Admin page**
4. **Month-start day**: configurable in **Settings**
5. **Per-batch click → modal** with the full breakdown

This plan ships the subsystem in three phases so each release
is independently shippable, reviewable, and rollback-able.

---

## Best practices baked in

| Practice | How |
|---|---|
| **Single source of truth** for cost data | `core/data/llm_costs.json` is the only place rates live. All callers read through one loader. |
| **Schema validation on load** | The loader rejects malformed entries at startup (or refresh) and logs a structured warning per bad row. Bad data does NOT silently drop rows. |
| **Defensive degradation** | When cost data is missing for a provider/model combo, the UI shows the row with `cost: null` + `Cost rate not configured for X` rather than blanking or erroring. |
| **Operator transparency** | Every estimate displays the rate used (e.g., `$15 / 1M input`) so operators can verify the calculation. |
| **Observable** | Every cost calculation emits a structured log line. Admin page surfaces an audit-trail link. |
| **Operational** | JSON file is editable in the container's `/app/core/data/` mount; a POST `/api/admin/llm-costs/reload` triggers a hot reload without container restart. |
| **Tested** | Unit tests for cost arithmetic + monthly-window logic + schema validation. |
| **No mutable global state** | Cost cache is held in a small module-level frozen dataclass; reload swaps the whole reference atomically. |
| **Backwards compatible** | New endpoints are additive; existing `/api/analysis/batches` etc. unchanged. |

---

## Data model

### `core/data/llm_costs.json` schema

```json
{
  "schema_version": 1,
  "updated_at": "2026-04-28",
  "source_url": "https://docs.anthropic.com/en/docs/about-claude/pricing",
  "providers": {
    "anthropic": {
      "claude-opus-4-6": {
        "input_per_million_usd":  15.00,
        "output_per_million_usd": 75.00,
        "cache_write_per_million_usd": 18.75,
        "cache_read_per_million_usd": 1.50,
        "notes": "Effective 2026-Q1; check source_url"
      },
      "claude-sonnet-4-6": {
        "input_per_million_usd":   3.00,
        "output_per_million_usd":  15.00
      },
      "claude-haiku-4-5-20251001": {
        "input_per_million_usd":   0.25,
        "output_per_million_usd":   1.25
      }
    },
    "openai": {
      "gpt-4o":      { "input_per_million_usd": 2.50, "output_per_million_usd": 10.00 },
      "gpt-4o-mini": { "input_per_million_usd": 0.15, "output_per_million_usd":  0.60 }
    },
    "gemini": {
      "gemini-1.5-pro":   { "input_per_million_usd": 1.25, "output_per_million_usd":  5.00 },
      "gemini-1.5-flash": { "input_per_million_usd": 0.075, "output_per_million_usd": 0.30 }
    },
    "ollama": {
      "*": { "input_per_million_usd": 0.00, "output_per_million_usd": 0.00, "notes": "Local — no per-token cost" }
    }
  }
}
```

### Why JSON (not DB)?

- **Externally updatable**: operator drops a new file in
  `/app/core/data/llm_costs.json` (host-mounted), hits the
  reload endpoint, done. No DB migration, no UI for the
  rate table itself.
- **Auditable**: file content + timestamps live in the
  source repo (or a host volume), so changes have a clear
  history.
- **Bootable**: ships in the container image so v0.33.1 has
  reasonable defaults out of the box.

### `analysis_queue.tokens_used` — what we have

Already populated by all four `_*_sub_batch` workers in
`core/vision_adapter.py`. Per-image tokens are computed as
`(input_tokens + output_tokens) // batch_size` (a per-row
share of the batch's total). Good enough for cost estimation;
the subsystem doesn't need finer-grained per-row token
splitting.

### New DB pref (Phase 2)

Single key:
```
billing_cycle_start_day: int (1-28, default 1)
```

Why 1-28: avoids February edge case. Monthly window for
"running total" runs from `<start_day>` of the current month
(or previous month if today < start_day) through "now".

---

## Phase 1 — backend foundation (no UI yet)

**Suggested release: v0.33.1**
**Estimated: ~3 hours**

### Goals

- Ship the cost data file.
- Ship the loader + accessor functions.
- Ship a per-row + per-batch + period-aggregate API.
- Ship admin-only reload endpoint.
- Unit tests for arithmetic + schema validation + window logic.
- **No UI changes** — verifies the backend in isolation
  before any HTML touches.

### Files to create

#### `core/data/llm_costs.json`
The data file (schema above).

#### `core/llm_costs.py` (~200 LOC)

```python
"""LLM token-cost lookup + arithmetic.

Public surface:
    load_costs() -> CostTable             # called once at startup
    reload_costs() -> CostTable           # admin-triggered hot reload
    get_costs() -> CostTable              # frozen accessor
    estimate_cost(provider, model, tokens, breakdown=None) -> CostEstimate
    aggregate_batch_cost(rows: list) -> BatchCostSummary
    aggregate_period_cost(rows: list, cycle_start_day: int) -> PeriodCostSummary

Returns dataclasses (frozen) for thread-safety + JSON-serializable.
"""

@dataclass(frozen=True)
class TokenRate:
    provider: str
    model: str
    input_per_million_usd: float
    output_per_million_usd: float
    cache_write_per_million_usd: float | None
    cache_read_per_million_usd: float | None
    notes: str

@dataclass(frozen=True)
class CostEstimate:
    tokens_used: int
    cost_usd: float | None         # None if rate unavailable
    rate_used: TokenRate | None
    error: str | None              # "rate not configured" etc.

@dataclass(frozen=True)
class BatchCostSummary:
    batch_id: str
    total_files: int
    files_with_tokens: int          # known cost
    files_estimated: int            # extrapolated from EWMA
    actual_tokens: int
    estimated_tokens: int
    actual_cost_usd: float
    estimated_cost_usd: float
    total_cost_usd: float           # actual + estimated
    per_file_avg_tokens: float
    per_file_avg_cost_usd: float
    rates_used: list[TokenRate]     # all distinct rates touched

@dataclass(frozen=True)
class PeriodCostSummary:
    cycle_start_iso: str
    cycle_end_iso: str
    cycle_label: str                # "April 2026 (cycle starts day 1)"
    total_tokens: int
    total_cost_usd: float
    by_provider: dict[str, float]   # provider -> usd
    by_model: dict[str, float]      # "anthropic/claude-opus-4-6" -> usd
    file_count: int
    days_into_cycle: int
    days_remaining: int
    projected_full_cycle_cost_usd: float  # linear extrapolation
```

Schema-validation strategy:
```python
def _validate_costs(payload: dict) -> CostTable:
    """Raise ValueError on malformed input. Empty fields -> defaults
    -> log warning but accept (for ollama-style 0-cost rows)."""
    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported schema_version: {payload.get('schema_version')}")
    ...
```

Loader is called in `main.py` lifespan after `init_db()`.
Failure to load is **fatal in dev** (raise) but **soft-fails
in prod** (log warning + serve `null` rates) — operators can
fix the file and hit `/api/admin/llm-costs/reload` without
container restart.

#### `api/routes/llm_costs.py` (~180 LOC)

```python
GET  /api/admin/llm-costs              -> serves the loaded JSON
POST /api/admin/llm-costs/reload       -> admin-only; reloads from disk
GET  /api/analysis/cost/batch/{id}     -> BatchCostSummary
GET  /api/analysis/cost/period         -> PeriodCostSummary (current cycle)
GET  /api/analysis/cost/period?days=30 -> PeriodCostSummary for arbitrary window
GET  /api/analysis/cost/file/{id}      -> CostEstimate for one row
```

Auth: `OPERATOR+` for the analysis/cost reads, `ADMIN` for
the llm-costs admin endpoints.

### Files to modify

#### `main.py`
- Add `from core.llm_costs import load_costs` to the lifespan.
- Call `load_costs()` after `init_db()` so cost data is ready
  before any request lands.
- Register the new router.

#### `core/db/preferences.py` (defaults)
- Add `billing_cycle_start_day = "1"` to the default
  preferences seeded on first boot.

### Tests

#### `tests/test_llm_costs.py` (~150 LOC)

- Schema validation: rejects missing `schema_version`,
  rejects negative rates, accepts ollama `*` wildcard,
  accepts missing optional fields.
- `estimate_cost` arithmetic: known model → exact cost;
  unknown model → null with error; ollama → 0.0.
- `aggregate_batch_cost`: mixed actual + estimated → sums
  match.
- `aggregate_period_cost`: cycle window respects
  `start_day`; today < start_day rolls back a month;
  projection is `actual / days_into_cycle * total_days`.
- Edge case: `start_day=31` falls back to last day of
  shorter months.

### Acceptance (Phase 1)

- ✅ `load_costs()` succeeds on a fresh container start
  with the shipped `llm_costs.json`.
- ✅ `curl /api/analysis/cost/batch/{id}` returns the
  expected shape with non-null cost values for a batch
  that has tokens_used set.
- ✅ Hot-reload via `POST /api/admin/llm-costs/reload`
  picks up file changes without restart.
- ✅ Unit tests pass.
- ✅ Existing `/api/analysis/batches` endpoint unchanged.

---

## Phase 2 — UI surfaces

**Suggested release: v0.33.2**
**Estimated: ~3 hours**

### Goals

- Modal on Batch Management click → per-batch + per-file
  cost estimate.
- New card on Admin page → monthly running total.
- New Settings entry → billing cycle start day picker.

### Files to modify

#### `static/batch-management.html`

- Each batch card already has a click handler that opens a
  detail modal (or uses the row click). Extend it to fetch
  `/api/analysis/cost/batch/{id}` and render a "Cost
  Estimate" panel:

```
┌─ Batch 6f1ef512 — Cost Estimate ─────────────────────────┐
│                                                            │
│ 10 files · 8 analyzed (actual) · 2 estimated              │
│                                                            │
│ Tokens                                                     │
│   Actual:    34,021 tokens                                 │
│   Estimated:  8,505 tokens (avg 4,253 / file × 2)          │
│   Total:     42,526 tokens                                 │
│                                                            │
│ Cost @ anthropic/claude-opus-4-6 ($15 in / $75 out per 1M)│
│   Actual:    $1.23                                         │
│   Estimated: $0.31                                         │
│   Total:     $1.54                                         │
│                                                            │
│ Per-file average: 4,253 tokens · $0.154                    │
│                                                            │
│ [Show per-file breakdown ▼]                                │
└────────────────────────────────────────────────────────────┘
```

The "Show per-file breakdown" disclosure expands a small
table with one row per file showing its individual
tokens_used + computed cost. Files with no tokens yet show
"Pending — estimated $X.XX based on batch average".

#### `static/admin.html`

New card slot — "Provider spend (current cycle)":

```
┌─ Provider spend — April 2026 (cycle starts day 1) ────────┐
│                                                            │
│ $42.18  total this cycle                                   │
│ 12.6M tokens · 3,407 files analyzed                        │
│                                                            │
│ By provider                                                │
│   anthropic: $39.50 (93%)                                  │
│   openai:     $2.68 (6%)                                   │
│   gemini:     $0.00 (0%)                                   │
│                                                            │
│ Cycle: day 12 of 30 · 18 days remaining                    │
│ Projected at current pace: $105.45 by month-end            │
│                                                            │
│ [Settings → change cycle start day]                        │
│ [Edit rate table → /api/admin/llm-costs (raw JSON)]        │
└────────────────────────────────────────────────────────────┘
```

Card auto-refreshes every 60 s (matches the page's existing
admin refresh cadence).

#### `static/settings.html`

New entry under "Billing" or "AI Options" section:

```html
<label>Billing cycle start day</label>
<input type="number" min="1" max="28" id="billing-cycle-start-day" />
<p class="hint">
  Day of the month your provider's billing cycle starts.
  Match this to your invoice date so the running total on
  the Admin page reflects what you'll owe at month end.
  Example: if your Anthropic bill closes on the 15th, set
  this to 15.
</p>
```

#### `static/js/cost-estimator.js` (new, ~120 LOC)

Shared module:
- `formatUsd(amount)` — `$1.23` / `$1,234.56`
- `formatTokens(n)` — `34,021 tokens` / `12.6M tokens`
- `renderBatchCostPanel(container, batchCost)`
- `renderPeriodCostCard(container, periodCost)`

Both pages import this module.

#### `docs/help/admin-tools.md`

Document the new "Provider spend" card with a worked
example:

> "If your operator analyzes ~500 photos a month at an avg
> of 3,400 tokens/photo on claude-opus-4-6, your monthly
> bill projection lands around $25.50. Watch the projected
> figure trend over the cycle to budget for the next month."

#### `docs/help/settings-guide.md`

Document the billing-cycle-start-day setting with the
"match your invoice date" example.

#### `docs/help/whats-new.md`

User-facing release notes for the cost estimation feature
with multiple worked examples.

### Tests

- E2E smoke: load Batch Management, click a batch, expect
  cost panel to render. Set `billing_cycle_start_day=15`,
  load Admin, expect the cycle label to read "March 16 –
  April 15" or similar.

### Acceptance (Phase 2)

- ✅ Click on any batch on Batch Management → cost modal
  appears with actual + estimated breakdown.
- ✅ Admin page shows the running-total card with provider
  breakdown.
- ✅ Settings page has the billing-cycle-start-day input;
  changing it re-renders the Admin card with the new
  cycle window.
- ✅ Help docs include user-friendly worked examples.
- ✅ Cost values match what you'd compute by hand from
  `tokens_used × rate / 1_000_000`.

---

## Phase 3 — operational hardening

**Suggested release: v0.33.3**
**Estimated: ~2 hours**

### Goals

- CSV export of the period cost data (for accountants).
- Admin-only "Edit rates" UI (or at least a clear path to
  edit the JSON).
- Audit-log link from the Admin card → past cost
  computations.
- Rate-staleness warning: if `llm_costs.json:updated_at` is
  > 90 days old, surface a banner reminding the operator to
  check provider pricing pages.

### Files

#### `api/routes/llm_costs.py`
- New: `GET /api/analysis/cost/period.csv` — same data as
  the JSON endpoint, formatted as CSV. Useful for handing
  to finance / pasting into a spreadsheet.

#### `static/admin.html`
- "Export CSV" button on the Provider Spend card.
- "Last updated: X days ago — check provider pricing
  pages" warning when `llm_costs.json:updated_at` is stale.

#### `core/llm_costs.py`
- New helper `is_data_stale(threshold_days=90)` returns a
  bool. Used by both the admin card and a new scheduler job.

#### `core/scheduler.py`
- New job: `check_llm_costs_staleness` runs daily. If stale,
  emits a structured log warning so admins can grep for it.
  No automatic refresh — the file is operator-curated.

### Audit trail

Every cost calculation that fires (`estimate_cost`,
`aggregate_batch_cost`, `aggregate_period_cost`) emits a
structured log line:

```
{"event": "llm_cost.computed", "scope": "batch", "batch_id": "...",
 "rates_used": ["anthropic/claude-opus-4-6"], "total_cost_usd": 1.54}
```

Searchable in the Log Viewer with `?q=llm_cost.computed`.
Documented as a tracable audit trail.

### Tests

- Stale-detection: file date in the past → `is_data_stale`
  returns True; recent → False.
- CSV export: contains expected columns, escapes commas in
  notes correctly.

### Acceptance (Phase 3)

- ✅ Export CSV downloads a parseable file with one row per
  provider+model+day.
- ✅ Operator gets a visible warning when rate data is > 90
  days old.
- ✅ Scheduled `check_llm_costs_staleness` runs daily and
  logs a warning if needed.
- ✅ Every cost calculation is traceable via the Log Viewer.

---

## Cross-phase concerns

### Edge cases to handle

| Edge case | Handling |
|---|---|
| Rate not configured for a provider/model | UI shows `-- (rate not configured)`, suggests editing `llm_costs.json`. Cost field returns `null`. Audit log emits `llm_cost.no_rate`. |
| Ollama (no cost) | Wildcard `*` match in JSON → 0.0 input/output rates. UI labels as "Local (free)". |
| Old analyses with `tokens_used = NULL` | Excluded from "actual" totals. Counted into "files awaiting analysis" if the batch is still pending. |
| `billing_cycle_start_day` = 31 in February | Window calculation falls back to last day of the shorter month. Tested. |
| Provider/model rename between analyses (e.g., `claude-3-opus` → `claude-opus-4-6`) | Each row keeps its own provider+model strings. Aggregations are by exact-match. Doc explains this. |
| Per-file estimate when batch has 0 completed | Estimate is null, UI shows "Estimate unavailable until at least 1 file is analyzed". |
| `tokens_used` reported but cost rate is 0 (ollama) | Cost = $0.00; not null. Audit log differentiates "0 cost" from "no rate". |

### Security

- All endpoints `OPERATOR+` for read, `ADMIN` for write/reload.
- The JSON file is loaded with `json.loads(file.read_text())`
  with a strict schema check; no `eval`, no dynamic Python
  loading.
- The reload endpoint rate-limits to 1 per second per user
  (cheap defense against accidental loops).

### Performance

- `load_costs` reads the JSON once at startup and caches
  the frozen dataclass.
- `aggregate_batch_cost` is O(N) over the batch's files —
  for a 200-file batch, ~negligible.
- `aggregate_period_cost` is a single SQL query against
  `analysis_queue` indexed on `analyzed_at` (the index
  exists per `core/db/schema.py`). Sub-second for 100K+
  rows.

### Backwards compatibility

- No DB migration in Phase 1.
- New `billing_cycle_start_day` preference defaults to 1
  (calendar month) in Phase 2 — operators upgrading see
  reasonable behavior with no config.
- All existing endpoints unchanged.

### Rollback story

Each phase is independently rollback-able:

- Phase 1: revert `core/llm_costs.py`, `core/data/`, and
  the new router. No data lost (no migrations, no schema
  changes).
- Phase 2: revert the UI files. Phase 1's APIs continue to
  work.
- Phase 3: revert the CSV export + staleness check. Phase
  1+2 unaffected.

---

## Implementation order (within Phase 1, recommended)

1. Author `core/data/llm_costs.json` with current rates for
   the 4 providers. Verify against each provider's
   public pricing page on the day of writing. (~15 min)
2. Implement `core/llm_costs.py` loader + dataclasses
   first. Get unit tests passing. (~45 min)
3. Implement the cost-arithmetic helpers + tests. (~30 min)
4. Implement the API router. (~30 min)
5. Wire `load_costs` into `main.py` lifespan. (~10 min)
6. Add the `billing_cycle_start_day` preference default.
   (~5 min)
7. Smoke test with `curl` against a real running container.
   (~15 min)
8. Docs + version bump + commit + push. (~30 min)

---

## Done criteria (overall, after all 3 phases)

- ✅ Cost data lives in one editable JSON file.
- ✅ Operators can see per-file, per-batch, and monthly
  cost estimates without leaving MarkFlow.
- ✅ Monthly running total matches actual provider invoice
  ±5% when `billing_cycle_start_day` matches the invoice
  cycle.
- ✅ Rate updates require no container restart.
- ✅ Stale rate data triggers a visible operator warning.
- ✅ Help docs include user-friendly worked examples for a
  typical operator workflow.
- ✅ All cost calculations are traceable via the Log Viewer.
- ✅ Subsystem ships in 3 reviewable releases (v0.33.1 →
  v0.33.2 → v0.33.3) — operator can pause after any phase
  without breaking the others.
