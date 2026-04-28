# Merge Pipeline + Lifecycle Scanner cards on the Status page

**Status:** Plan — not implemented.
**Author:** v0.32.11 follow-up planning, 2026-04-28.
**Triggers a release:** Yes — implementation produces a versioned cut (likely `v0.33.0` since the URL/API surface changes are operator-visible).

---

## Background

The Status page (`/static/status.html`) currently presents
**three top-level cards** that all read overlapping subsets of
the same scan data:

| Card | What it shows | Source endpoint |
|------|--------------|----|
| **Pipeline strip** (top) | Chip counts: scanned / pending / failed / unrecognized / pending_analysis / batched / analysis_failed / indexed | `/api/pipeline/stats` |
| **Lifecycle Scanner** card | "running / idle" + last scan timestamp + current file | `/api/scanner/progress` |
| **Pending** card | "N files pending conversion" + last-scan stats + next-scan time + last auto-conversion summary | `/api/pipeline/status` |

Three cards. One actual scan. The user (correctly) called this
out as confusing — *"Pipeline and Lifecycle Scanner sound like
the same thing. Am I wrong?"* They are NOT the same internally
(Pipeline orchestrates Lifecycle Scanner + Auto-Convert + Image
Analysis), but on the page they LOOK like peers, and operators
end up reading three slightly-different timestamps and
wondering which is canonical.

A separate page — `/static/bulk.html` (Bulk Jobs) — already has
**the right card**: a single rich Pipeline card with `Mode /
Last Scan / Next Scan / Source Files / Pending / Interval`
columns and `Pause / Rebuild Index / Run Now` action buttons.
That's the card we want as canonical.

The user's request:

> *"the best practice for a cohesive ux user experience would
> be to merge them and have the pipeline card move to the
> status page. or have it mirrored on the status page<?, i'm
> not sure what the best practice is>; fix the bug"*

The bug ("Last scan: never" after restart) was fixed in
v0.32.11. This plan handles the merge.

---

## Best-practice answer: single source of truth, not mirror

**Don't mirror — promote.**

Rationale:
- Two cards with two endpoints and two refresh cadences drift
  apart. Exactly the bug we just fixed (in-memory cache vs.
  DB).
- One canonical card is easier to maintain (one set of CSS
  rules, one polling loop, one set of click handlers).
- Operators looking for "what's the pipeline doing right
  now?" expect Status to be the answer. Bulk Jobs is for
  managing specific in-flight bulk conversions — the pipeline
  card is incidental there.
- Other entry points (home, bulk) get **summary cards with
  link-to-status**, not full mirrors. Pattern: macOS Activity
  Monitor, GitHub, k8s dashboards, AWS console.

So: **canonical Pipeline card lives on Status. Bulk Jobs gets a
2-line summary that deep-links.** Lifecycle Scanner standalone
card disappears (its data is already in the rich Pipeline
card). Pending card stays but compresses (see Phase 4).

---

## Goals

1. **Status page becomes the canonical "what is the system
   doing?" surface.** Operators land here for any
   pipeline-related question.
2. **Single Pipeline card** with all the fields from the
   current Bulk Jobs card: Mode, Last Scan, Next Scan, Source
   Files, Pending, Interval + Pause / Rebuild Index / Run Now.
3. **No more standalone Lifecycle Scanner card** — its data
   merges into the Pipeline card's "Last Scan" cell.
4. **Bulk Jobs page keeps a summary card** (1–2 lines + view
   link) — operators on Bulk Jobs aren't blocked from seeing
   pipeline state, just routed to Status for the rich view.
5. **No regressions** in deep-linkable URLs (chip clicks still
   land on Pipeline Files, the Pause / Run Now actions still
   work).

---

## Phase 0 — discovery (10 minutes)

Read what's actually there before writing anything.

### Read the rich Pipeline card

`static/bulk.html`:
- HTML structure: lines 84–137 (`<div id="pipeline-card" ...>` with
  `pl-cell-last-scan`, `pl-cell-next-scan`, etc.)
- CSS rules: search for `.pl-cell`, `.pipeline-card` in
  `static/markflow.css` (likely scoped via `bulk.html`'s
  `<style>` block — confirm whether they're inline or external).
- JS: `loadPipelineStatus()` at line ~412, plus
  `togglePipelinePause()`, `pipelineRunNow()`, polling at
  `setInterval(..., 30s)` ~ line 618.
- Data flow: `GET /api/pipeline/status` returns
  `pipeline_enabled`, `paused`, `auto_convert_mode`,
  `scanner_interval_minutes`, `is_scan_running`, `next_scan`,
  `last_scan`, `total_source_files`, `pending_conversion`,
  `last_auto_conversion`. Already used by both cards we want
  to merge.

### Read the standalone Lifecycle Scanner card

`static/status.html`:
- HTML: `<div id="lifecycle-container" ...>` (mounted by JS
  via `renderLifecycle()`).
- CSS: `.job-card` family in `markflow.css`.
- JS: `renderLifecycle(ls)` at line ~402. Reads from
  `GET /api/scanner/progress` (line 181).
- Data flow: `running`, `run_id`, `started_at`, `scanned`,
  `pct`, `current_file`, `eta_seconds`, `last_scan_at`,
  `last_scan_run_id`. Note: `last_scan_at` was the bug fixed
  in v0.32.11 (in-memory cache wasn't hydrated from DB on
  startup).

### Read the Pending card

`static/status.html`:
- HTML: `<div id="pending-container" ...>`.
- JS: somewhere in the `poll()` flow — calls
  `/api/pipeline/status` and renders into
  `#pending-content`.
- Data flow: same `/api/pipeline/status` the rich card uses,
  plus `/api/scanner/progress` for the live scanned count.

### Endpoint inventory

Three endpoints currently feed the cards:

| Endpoint | Used by | Data |
|---|---|---|
| `/api/pipeline/status` | Bulk Jobs Pipeline card, Status Pending card | Mode, last/next scan, totals, pause state |
| `/api/scanner/progress` | Status Lifecycle card | Live scan progress (running, current_file, pct) |
| `/api/pipeline/stats` | Status chip strip, Pipeline Files page | Bucket counts (scanned/pending/failed/etc.) |

**Decision point**: do we consolidate the first two into a
single endpoint, or keep them separate and have the Pipeline
card poll both? Recommendation in Phase 2 below — keep
separate, poll both, render into one card. Avoids API breakage
for other consumers.

---

## Phase 1 — extract Pipeline card to a shared partial

Currently the rich Pipeline card lives inline in `bulk.html`.
For both pages to render it (or for one place to maintain it),
factor it out.

Two options:

### Option 1A — JS module that builds the card via DOM API
- `static/js/pipeline-card.js` exports `mountPipelineCard(containerEl, opts)`.
- Builds DOM via `createElement` (XSS-safe, matches
  live-banner.js / auto-refresh.js convention).
- Returns a handle with `refresh()`, `destroy()`.
- Both `bulk.html` and `status.html` call `mountPipelineCard`
  on a placeholder div.

### Option 1B — HTML partial fetched at runtime
- `static/partials/pipeline-card.html` served as a static
  asset.
- Pages fetch the partial and inject it into a placeholder
  via DOMPurify → `appendChild`.
- Simpler to author (looks like HTML) but fragile (extra HTTP
  request, sanitization layering, harder to update both
  copies).

**Recommendation: 1A.** Matches the rest of the v0.32.x
shared-helper pattern (`auto-refresh.js`, `live-banner.js`),
no extra HTTP request, easier to evolve. ~250 LOC for the
JS module + ~100 LOC of CSS extracted to `markflow.css`.

### Files (Phase 1)
- `static/js/pipeline-card.js` (new) — `mountPipelineCard()`
- `static/markflow.css` — add `.pl-card`, `.pl-cell`, `.pl-pill`
  rules (move from `bulk.html` inline `<style>` if currently
  inline, or refactor existing if already in CSS file)
- `static/bulk.html` — replace inline card markup +
  `loadPipelineStatus` JS with a `<div id="pipeline-card-mount"></div>`
  + `mountPipelineCard()` call
- `tests/` — none (frontend-only refactor; verify by visual
  comparison)

---

## Phase 2 — replace Lifecycle Scanner card on Status

With the partial extracted, Status mounts the same Pipeline
card.

### `static/status.html` changes
1. Remove `<div id="lifecycle-container">` markup.
2. Remove the `renderLifecycle()` JS function and its caller.
3. Remove the `/api/scanner/progress` polling loop *for that
   card* — the Pipeline card will poll it itself if it needs
   live scan progress, OR the Pipeline card just reads
   `/api/pipeline/status` which already includes
   `is_scan_running` and `last_scan`.
4. Mount the Pipeline card in place of the lifecycle card:
   ```html
   <div id="pipeline-card-mount" style="margin-top:1.5rem"></div>
   <script>mountPipelineCard(document.getElementById('pipeline-card-mount'));</script>
   ```
5. Move the chip strip BELOW the Pipeline card (currently at
   the top — the Pipeline card with its rich data should be
   the visual anchor, chips are secondary).

### Live scan progress in the Pipeline card

The Bulk Jobs Pipeline card currently shows "Last Scan" with
a status pill (Running / Completed / Interrupted / Failed) and
a count. When a scan is actively running, that cell could
either:

a) **Show a static "Running" pill + the in-progress count
   from `last_scan.files_scanned`** — what the current Bulk
   Jobs card does. Refresh on the 30s poll.
b) **Show a live progress bar** with `current_file` and `pct`
   from `/api/scanner/progress` — needs faster polling (5s)
   and more screen space.

**Recommendation: a) — keep the simple version**. The Status
page also has the Active Jobs section above, which already
shows live progress for any running scan via
`renderJobs()`/`/api/admin/active-jobs`. Putting another live
view in the Pipeline card duplicates information. Operators
who want the per-file detail can scroll up to Active Jobs.

If the user later wants more detail in the Pipeline card,
`/api/scanner/progress` is one fetch away.

### Files (Phase 2)
- `static/status.html` — remove lifecycle-container HTML +
  JS, mount Pipeline card, reorder chip strip
- (no new files; `pipeline-card.js` already exists from Phase 1)

---

## Phase 3 — Bulk Jobs becomes a summary

`static/bulk.html` no longer renders the full Pipeline card
inline. Instead:

- A 2-line summary card with: status pill + last scan + next
  scan + pending count.
- "View on Status →" link.
- Optionally keep the Pause / Run Now buttons here (operators
  on Bulk Jobs may want quick controls without navigating —
  these are 3 lines of code, low cost).

### Mockup

```
┌─────────────────────────────────────────────────────────────┐
│ ● PIPELINE  Active · Last scan 28m ago · Next 12m · 1,493  │
│   pending  ·  [Pause]  [Run Now]  ·  view full status →     │
└─────────────────────────────────────────────────────────────┘
```

vs. the current Bulk Jobs Pipeline card which takes ~6 visual
rows.

### Files (Phase 3)
- `static/bulk.html` — replace full Pipeline card with summary.
  Reuse `pipeline-card.js` with a `compact: true` opt:
  ```js
  mountPipelineCard(el, { compact: true });
  ```
  Compact mode renders fewer cells, drops the cell descriptions,
  optionally keeps the action buttons.

---

## Phase 4 — Pending card on Status

The standalone "PENDING" card on Status currently shows:
- "N files pending conversion"
- "Source files tracked: N"
- "Last scan: N files (N new, N modified) — interrupted"
- "Last auto-conversion: running (N files, N workers)"
- "Next scan: 2:28 PM"

After Phase 2, the Pipeline card already shows: Mode, Last
Scan (with status pill + counts), Next Scan, Source Files
total, Pending count, Interval.

**Overlap is heavy.** Decision:

### 4a. Remove the standalone Pending card
- All of its fields are in the Pipeline card or one click
  away (chip strip → Pipeline Files filtered to `status=pending`).
- "Last auto-conversion: running (N files, N workers)" — this
  is unique. Could fold into the Pipeline card's "Last Scan"
  cell as a sub-line.
- Cleanest UX. Removes a card, no data lost.

### 4b. Keep the Pending card but trim it
- Keep ONLY the auto-conversion progress line ("running, N
  workers, batch=N").
- Move under or beside the Pipeline card visually.
- Lower-effort, retains the auto-conversion run detail.

**Recommendation: 4a.** Adds a "Last auto-conversion" sub-line
to the Pipeline card's Last Scan cell (it already shows scan
state — adding "auto-convert: running, 8 workers" is one more
line in the same cell). Drops the standalone card. The chip
strip + Pipeline card cover everything.

### Files (Phase 4)
- `static/status.html` — remove pending-container markup +
  JS (`pending-content`, `pending-label`)
- `static/js/pipeline-card.js` — extend Last Scan cell to
  optionally show auto-conversion sub-line (data is in
  `/api/pipeline/status` already as `last_auto_conversion`)

---

## Phase 5 — home page (deferred, but planned)

`static/index.html` is the landing page. It currently has its
own widgets (Convert dropzone, recent activity, etc.). It does
NOT currently have a Pipeline card. So nothing to remove —
just optionally ADD a 1-line summary if we want operators to
see pipeline state on landing.

```
┌─────────────────────────────────────────────────────────────┐
│ Pipeline: Active · 1,493 pending · Last scan 28m ago →     │
└─────────────────────────────────────────────────────────────┘
```

Click → `/status.html#pipeline`.

This is OPTIONAL. The Status page is the canonical view; the
home page already lets operators navigate via the nav bar.
Skip if it adds friction.

### Files (Phase 5, optional)
- `static/index.html` — add a 1-line summary linking to
  Status.

---

## Phase 6 — docs + help update

- `docs/help/status-page.md` — describe the new layout: the
  rich Pipeline card is the focus, chip strip below shows
  bucket counts, Active Jobs section shows live job
  progress.
- `docs/help/file-lifecycle.md` — the standalone "Lifecycle
  Scanner" terminology may still appear here; update to
  reference "the Pipeline card on the Status page" if
  appropriate.
- `docs/help/whats-new.md` — release notes.
- `docs/version-history.md` — release notes.
- `CLAUDE.md` — current-version block.
- `docs/key-files.md` — add `static/js/pipeline-card.js`.

---

## Implementation order (recommended)

1. **Phase 0** — read the existing code (15 min).
2. **Phase 1** — extract `pipeline-card.js` + verify Bulk Jobs
   page renders identically (~1 hour).
3. **Phase 2** — mount on Status page, remove standalone
   Lifecycle Scanner card (~30 min).
4. **Phase 4** — remove Pending card, fold auto-conversion
   line into Pipeline card (~30 min).
5. **Phase 3** — Bulk Jobs gets compact summary (~30 min).
6. **Phase 5** — *optional* home-page summary (~15 min).
7. **Phase 6** — docs + version bump (~30 min).
8. Visual QA across both pages, hard-refresh, click every
   button, verify the data matches what's in the DB
   (~15 min).

Total: ~3.5 hours of focused work. One commit per phase keeps
diffs reviewable.

---

## Risks & open questions

### Endpoint consolidation?

Currently the rich card reads `/api/pipeline/status`, the
Lifecycle card reads `/api/scanner/progress`, the chip strip
reads `/api/pipeline/stats`. Three endpoints, three poll
loops, three response shapes.

**Should we add a `/api/pipeline/everything`?** Tempting but
not in this plan. Keeping the existing endpoints stable lets
other consumers (mobile if it ever exists, MCP tools, the
Pipeline Files page) keep working. The Pipeline card just
polls `/api/pipeline/status` (which already includes most of
what the Lifecycle card showed) plus optionally
`/api/scanner/progress` if a finer-grained live indicator is
desired.

### URL stability

Operators may bookmark `/status.html` and expect to see the
Pending card or Lifecycle card. After this work, those cards
no longer exist. They'll see the Pipeline card containing the
same information. Worth a one-line note in
`docs/help/whats-new.md` so people aren't confused.

The chip strip's deep-links
(`/pipeline-files.html?status=pending` etc.) keep working
unchanged.

### Active scan progress

If an operator wants per-file live progress (current file
being scanned, ETA), they need the Active Jobs section. After
this merge, the Status page no longer shows it as a top-level
card — only inside Active Jobs (which is already there).
Confirm that's OK; if not, the Pipeline card's Last Scan cell
can render a progress bar when `is_scan_running=true` (~20
LOC addition).

### Compact-mode hover tooltips on Bulk Jobs

The current rich Pipeline card on Bulk Jobs has explanatory
tooltips on each cell ("The most recent pipeline scan that
walked the source tree...", etc.). The compact summary needs
to retain at least the key tooltips, or move them to the
"view on Status →" hover.

### Action button placement

Pause / Rebuild Index / Run Now currently render on the Bulk
Jobs Pipeline card. After Phase 3, they could:

a) Stay on Bulk Jobs (kept on the compact summary).
b) Move to Status only.
c) Both.

**Recommendation: (a) — keep on Bulk Jobs**, since operators
in the middle of managing bulk jobs may want quick access
without navigating. The same buttons render on Status's
Pipeline card too (full version). `compact:true` mode of
`pipeline-card.js` keeps action buttons by default.

### Live banner overlap

The v0.32.1 Live Banner already mirrors "Empty Trash" /
"Restore All" progress at the top of the page. The new
Pipeline card on Status overlaps somewhat — both show
pipeline state. Acceptable: the Live Banner is for *transient*
operations (Empty Trash takes 30 s); the Pipeline card is for
*continuous* state (scheduler tick). Different use cases.

---

## Testing strategy

### Phase 1 (extract partial)
- Visual diff: load Bulk Jobs before and after, take a
  screenshot of the Pipeline card. Should be byte-identical.
- Smoke test: click Pause / Resume / Run Now. All work the
  same.
- Cross-browser: Chrome, Edge, Firefox.

### Phase 2 (Status mount + remove Lifecycle card)
- Load `/status.html`. Expect: chip strip → Pipeline card →
  Active Jobs → (no Pending or Lifecycle cards) → Auto-Conv
  → System Health.
- Verify "Last Scan" cell shows the same value the Pending
  card used to show.
- Verify the chip strip's pending count matches the Pipeline
  card's `pending` field.

### Phase 4 (remove Pending card)
- Load `/status.html`. Pending card should be gone.
- Pipeline card's Last Scan cell should now have a sub-line
  with auto-conversion info.

### Phase 3 (Bulk Jobs compact)
- Load `/bulk.html`. Pipeline card should be 2 lines, not
  full grid.
- Click "view full status →" should navigate to
  `/status.html`.
- Click Pause / Run Now should still work from the compact
  card.

### Regression checks
- Pipeline Files page chip-click links still work.
- The v0.32.1 AutoRefresh helper still polls correctly.
- The v0.32.11 hydration fix remains intact (`Last scan:
  never` no longer regresses on restart).
- Status page's existing Stop All Jobs button still works.

---

## Done criteria

After this work:

- ✅ Status page has a single Pipeline card (rich version)
  as its primary "what's happening" surface.
- ✅ No standalone Lifecycle Scanner card.
- ✅ No standalone Pending card on Status (data merged into
  Pipeline card).
- ✅ Bulk Jobs has a compact summary linking to Status.
- ✅ Chip strip remains as a quick-navigation aid.
- ✅ All existing buttons and deep-links still work.
- ✅ `pipeline-card.js` is the single source of truth for the
  card's rendering — both pages call into it.
- ✅ `docs/help/whats-new.md` explains the change.
- ✅ Version bumped (suggested: `v0.33.0` since the operator-
  visible UI shifted notably).

---

## Estimate

**~3.5 hours of focused engineering** (code + visual QA),
plus ~30 min for docs / version bump / commit / push.

**One commit per phase** keeps diffs reviewable; phases are
independent enough that any could be paused without breaking
the others. Phase 5 (home-page summary) is genuinely
optional and can ship later.

---

## Open question for the operator

Before implementation: do you want the Active Jobs section on
Status to keep its existing per-file progress card during a
scan, or should the rich Pipeline card pick that up too?

Default if you don't say: **keep Active Jobs as-is** (it
already shows live per-file scan state via the existing
`renderJobs()` flow). The Pipeline card just shows a "Running"
status pill — no duplicate live-progress bar.
