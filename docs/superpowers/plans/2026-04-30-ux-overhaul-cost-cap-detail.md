# UX Overhaul — Cost Cap & Alerts Deep-Dive (Plan 7)

**Goal:** Land the `/settings/ai-providers/cost` sub-page with its own sidebar, spend overview tiles, daily-spend chart, CSV rate import, and help file. This is the deepest drill in the settings IA — it replaces (not nests) the AI providers sidebar when active.

**Architecture:** Single HTML template + `MFCostCapDetail` JS component + boot + CSS. The cost sidebar is self-contained: it does not share `MFAIProvidersDetail`'s sidebar. Route `/settings/ai-providers/cost` must be registered **before** the `{section}` catch-all in `main.py` (the catch-all only matches one segment, so this path would 404 without an explicit route).

**Mockup reference:** `docs/superpowers/specs/2026-04-28-ux-overhaul-mockups/cost-deep-dive.html` — full page with both single-provider and multi-provider layouts shown side by side.

**Out of scope:**
- Alert delivery (email/Slack hooks for threshold breaches) — Notifications backend (future)
- Auto-fetch rates from Anthropic/OpenAI API — CSV import and manual entry are sufficient for v1
- Period CSV export (`/api/analysis/cost/period.csv` variant noted in the route file as Phase 3)

**Prerequisites:** Plan 6 Task 2 (AI providers detail) complete. `/settings/ai-providers` registered in `main.py`.

---

## Agent dispatch guide

| Task | Impl agent | Impl model | Review agent | Review model | Rationale |
|---|---|---|---|---|---|
| Task 1 — Cost overview + chart | `mf-impl-high` | **sonnet** | `mf-rev-high` | **sonnet** | Provider-adaptive layout (1 vs N providers); SVG chart; multi-API fetch |
| Task 2 — CSV import UI | `mf-impl-high` | **sonnet** | `mf-rev-medium` | **haiku** | Drag-and-drop + file validation + format preview; no novel patterns |
| Task 3 — Help file + route | `mf-impl-medium` | **haiku** | `mf-rev-medium` | **haiku** | Markdown file + one route registration — fully mechanical |

Override Task 1 to opus only if the provider-adaptive logic proves complex enough to fail review twice.

---

## File structure

**Create:**
- `static/settings-cost-cap.html` — template
- `static/js/pages/settings-cost-cap.js` — `MFCostCapDetail`
- `static/js/settings-cost-cap-boot.js`
- `docs/help/cost-rates-csv-format.md` — operator-facing CSV format reference

**Modify:**
- `static/css/components.css` — append `mf-cost__*` block
- `main.py` — add `/settings/ai-providers/cost` route

---

## Task 1: Cost overview, spend tiles, and daily chart

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-high` (model: **sonnet**)

**APIs consumed:**
- `GET /api/admin/llm-costs` → rate table array `[{ provider, model, input_per_1m, output_per_1m, ... }]`
- `GET /api/analysis/cost/period` → `{ total_usd, by_provider: { name: usd }, by_model: [...], daily: [{ date, usd }] }`
- `GET /api/analysis/cost/period?days=30` — same shape, trailing 30 days
- `GET /api/analysis/cost/staleness` → `{ is_stale, age_days }`

**Sidebar groups (cost-specific, replaces AI providers sidebar):**
```
COST
  Overview                    ← active by default

RATES BY PROVIDER
  <one entry per active provider type in rate table>

DATA
  Sources & CSV import
  Spend history

NOTIFY
  Alerts & thresholds

[external link]
  CSV format reference ↗      → /help (or docs/help/cost-rates-csv-format.md served statically)
```

The sidebar's "Rates by provider" group is built dynamically: one entry per unique `provider` value in the rate table. If the rate table is empty, this group shows "No rates loaded — import a CSV."

**Component: `MFCostCapDetail.mount(slot, { rateTable, period, period30, staleness, providers })`**

Where `providers` is a deduplicated list of provider names present in `rateTable`.

**Overview sub-section:**

Layout adapts to provider count (single vs. multiple):

- **Single provider** (1 unique provider in rate table):
  - 2-tile grid: "Spend today" (from period filtered to today) · "Spend this month" (period.total_usd)
  - Stale-data warning banner if `staleness.is_stale`
  - Daily spend chart (SVG polyline, same technique as `MFActivity` sparkline): single color (`--mf-color-accent`), x-axis = last 14 days, y-axis auto-scaled, no legend
  - Spend breakdown table: model · input tokens · output tokens · cost. No provider column.

- **Multiple providers**:
  - 3-tile grid: "Spend today" · "Spend this month" · "Active providers" (count + name list as tooltip)
  - Daily spend chart: stacked polylines, one color per provider, with legend chips below the chart
  - Spend breakdown table: provider column added, totals row separated by a `2px solid var(--mf-color-accent)` line, bold text

**Rates by provider sub-sections (one per provider):**

Content: mini-table of models for that provider — model name, input rate ($/1M), output rate ($/1M), cache write (if present), cache read (if present), effective date. All read-only. "Rates loaded from [source]" note; source is always "CSV import" for v1. "Update rates →" links to Sources & CSV import.

**Spend history sub-section:**

Same spend breakdown table as Overview but scoped to last 30 days. No chart. "Download as CSV" button → `GET /api/analysis/cost/period?days=30` with `Accept: text/csv` header (if the endpoint supports it; otherwise render a "CSV export coming soon" stub).

**Alerts & thresholds sub-section:**

For v1: display current threshold preferences from `/api/preferences` (cost_alert_threshold_usd, cost_alert_enabled). Toggle + numeric input. Save bar. Note: "Alert delivery (Slack / email) configured in Notifications → Channels."

- [x] **Step 1:** Create `static/settings-cost-cap.html` — same chrome stack, slot `#mf-cost-cap`
- [x] **Step 2:** Create `static/js/pages/settings-cost-cap.js` — `MFCostCapDetail` with adaptive layout logic
- [x] **Step 3:** Create `static/js/settings-cost-cap-boot.js` — fetches `/api/me` + all 3 cost endpoints in parallel; handles `staleness.is_stale` and passes to component; members → `/`, operators+

---

## Task 2: CSV import UI (Sources & CSV import sub-section)

**Agent dispatch:** `mf-impl-high` (model: **sonnet**) · review: `mf-rev-medium` (model: **haiku**)

This sub-section lives inside `MFCostCapDetail` as the "Sources & CSV import" content panel. It is added to the component built in Task 1 — **do not create a separate component**.

**API consumed:**
- `POST /api/admin/llm-costs/reload` → `{ ok, loaded_count }` — hot-reloads from the JSON rate file on disk. The actual CSV parsing and file-save mechanism is currently manual (operator edits the JSON file). For v1, the import UI validates the CSV client-side, shows a preview, and instructs the operator to save the file then click "Reload."

**UI spec (safe DOM throughout):**

- **Drag-and-drop zone** — `div.mf-cost__drop-zone` with dashed lavender border (`var(--mf-color-accent-border)`), purple-tint background (`var(--mf-color-accent-tint)`), 48px upload icon (text: ↑), label "Drop a CSV rate file here". On dragover: border becomes solid accent.
- **"Choose file" pill button** — opens `<input type="file" accept=".csv">` (hidden). "Paste from clipboard" pill button — reads `navigator.clipboard.readText()` and feeds the text to the parser.
- **Client-side CSV parser** — `_parseCSV(text)` validates required columns (provider, model, input_per_1m, output_per_1m). Returns `{ rows, errors }`. Pure function, no network.
- **Format preview** — after successful parse, renders a dark code block (`mf-cost__preview-block`: `#1a1a1a` bg, `#e6e6e6` text, monospace 0.78rem) showing the first 5 rows re-serialized as color-coded CSV (provider column in accent purple, model in white, rate columns in green).
- **Error list** — if parse errors, show `mf-cost__error-list` with row + column + message per error. Clears on next successful parse.
- **"Reload rates" button** (primary) — disabled until a valid parse has been produced. On click: POST `/api/admin/llm-costs/reload`. Show spinner inline; on success show "Loaded N rate entries" success banner. On error show error text.
- **Per-provider source note** — below each provider's rates sub-section: "Source: CSV import. Update rates in Sources & CSV import →."

- [x] **Step 4:** Extend `settings-cost-cap.js` — add `_renderCSVImport()` function and wire into "Sources & CSV import" content panel
- [x] **Step 5:** Append `mf-cost__*` CSS to `components.css`:
  - `mf-cost__tiles` (2-up and 3-up grid variants)
  - `mf-cost__chart-wrap` + `mf-cost__chart-svg`
  - `mf-cost__legend` (chip row)
  - `mf-cost__breakdown-table` (with provider column and totals row variant)
  - `mf-cost__drop-zone` (drag-and-drop area)
  - `mf-cost__preview-block` (dark code preview)
  - `mf-cost__error-list`
  - `mf-cost__stale-banner`

---

## Task 3: Help file and route wiring

**Agent dispatch:** `mf-impl-medium` (model: **haiku**) · review: `mf-rev-medium` (model: **haiku**)

- [x] **Step 6:** Create `docs/help/cost-rates-csv-format.md` with:
  - Title: "Cost Rate CSV Format"
  - Required columns table: provider, model, input_per_1m, output_per_1m
  - Optional columns table: cache_write_per_1m, cache_read_per_1m, vision_per_image, batch_discount_pct, effective_date
  - Full example CSV block (3–4 rows covering Anthropic claude-3-5-sonnet + claude-3-haiku + OpenAI gpt-4o)
  - Notes: UTF-8 only; empty cells = "doesn't apply" not zero; historical rates via effective_date; "providers change pricing without notice — verify against provider dashboard"

- [x] **Step 7:** Add route in `main.py` **before** the `{section}` catch-all:
  ```python
  @app.get("/settings/ai-providers/cost", include_in_schema=False)
  async def settings_cost_cap_page():
      return FileResponse("static/settings-cost-cap.html")
  ```
  Note: `/settings/{section}` only matches one path segment, so this route would 404 without explicit registration.

- [x] **Step 8:** Commit `feat(ux): Cost cap & alerts deep-dive sub-page (Plan 7)`

---

## Acceptance checks

- [x] `grep -n "innerHTML" static/js/pages/settings-cost-cap.js` — zero matches
- [x] `GET /settings/ai-providers/cost` → 200 (not 302)
- [x] `GET /settings/ai-providers` still → 200 (sibling route not broken)
- [x] Single-provider mode: 2 tiles, no legend, no provider column in table
- [x] Multi-provider mode: 3 tiles, legend chips, totals row with accent border
- [x] Stale banner appears when `staleness.is_stale === true`
- [x] CSV import: valid CSV parses and shows preview; invalid CSV shows error list
- [x] "Reload rates" button disabled before valid parse; fires POST on click
- [x] "Paste from clipboard" reads clipboard text and feeds to parser
- [x] `docs/help/cost-rates-csv-format.md` exists with all required + optional columns documented
- [x] Sidebar "CSV format reference ↗" link points to the help file or `/help` anchor
