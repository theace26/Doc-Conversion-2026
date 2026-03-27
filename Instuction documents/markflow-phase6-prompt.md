# MarkFlow Phase 6 Build Prompt
# Full UI, Batch Progress, History Page, Settings, Polish

**Version:** v1.0  
**Targets:** v0.6.0 tag  
**Prerequisite:** Phase 5 complete — 350+ tests passing, debug dashboard live, tagged v0.5.0

---

## 0. Read First

Load `CLAUDE.md` before writing a single line. Pay particular attention to the new Phase 5
gotchas — especially the `/api/health` envelope change and `MarkdownHandler.ingest()` signature.

This phase is **UI-only**. No new backend conversion logic, no new format handlers, no schema
changes. If you find yourself writing new conversion code, stop — that belongs in a later phase.
The only backend changes allowed in Phase 6 are:
- New API endpoints that serve UI state (progress polling, settings reads/writes)
- Adding fields to existing response models if the UI needs them
- Bug fixes discovered during UI integration testing

---

## 1. Phase 6 Scope

| Track | Deliverable |
|-------|-------------|
| A | Batch progress — live conversion progress without polling hacks |
| B | History page — browse, filter, and re-download past conversions |
| C | Settings page — preferences UI backed by existing preferences API |
| D | UI cohesion pass — consistent design system across all pages |
| E | Error UX — clear, actionable error states everywhere |

---

## 2. Track A — Batch Progress

### 2.1 Goal

After submitting files for conversion, the user sees live progress — per-file status updates,
overall completion percentage, and a clear success/error summary — without polling hacks or
full page reloads.

### 2.2 Backend

#### `api/routes/batch.py` (modify)

Add `GET /api/batch/{batch_id}/stream` — a Server-Sent Events (SSE) endpoint.

The endpoint streams events until the batch is complete (all files either succeeded or failed),
then sends a final `event: done` and closes. If the client reconnects with a `Last-Event-ID`
header, replay events from that point.

Event types:

```
event: file_start
data: {"file_id": "...", "filename": "report.docx", "index": 1, "total": 5}

event: file_complete
data: {"file_id": "...", "filename": "report.docx", "status": "success",
       "duration_ms": 840, "output_filename": "report.md", "tier": 2}

event: file_error
data: {"file_id": "...", "filename": "bad.pdf", "status": "error",
       "error": "Password-protected PDF — cannot extract text"}

event: ocr_flag
data: {"file_id": "...", "filename": "scan.pdf", "flag_count": 3,
       "review_url": "/review.html?batch_id=..."}

event: batch_complete
data: {"batch_id": "...", "success": 4, "error": 1, "total": 5,
       "duration_ms": 4200, "download_url": "/api/batch/.../download"}

event: done
data: {}
```

Implementation notes:
- Use `fastapi.responses.StreamingResponse` with `media_type="text/event-stream"`.
- The converter must write progress events into an in-memory queue (per batch_id) that the SSE
  endpoint reads from. Use `asyncio.Queue` — one queue per active batch, stored in a
  module-level dict in `core/converter.py`.
- Queue is cleaned up when the SSE stream closes (client disconnects) or after 5 minutes of
  inactivity.
- If the batch is already complete when the SSE endpoint is hit (client reconnected after
  completion), immediately stream all recorded events from the SQLite history and close.

#### `core/converter.py` (modify)

- Add `_progress_queues: dict[str, asyncio.Queue]` at module level.
- `ConversionOrchestrator` takes a `batch_id` at construction time.
- Before processing each file, emit `file_start` to the queue.
- After processing each file, emit `file_complete` or `file_error`.
- If OCR flags were raised, emit `ocr_flag`.
- After all files, emit `batch_complete` then `done`.
- Helper: `get_progress_queue(batch_id) -> asyncio.Queue | None` (used by SSE endpoint).

#### `api/routes/convert.py` (modify)

After validating and starting the batch job, return the SSE URL in the response:
```json
{
  "batch_id": "...",
  "file_count": 5,
  "stream_url": "/api/batch/{batch_id}/stream"
}
```

### 2.3 Frontend — `static/index.html` (modify) + `static/progress.html` (new)

**`static/index.html`**:
- After successful `POST /api/convert`, redirect to `progress.html?batch_id=...`.
- Do not poll for status on the index page itself.

**`static/progress.html`** (new page):

Layout:
```
┌────────────────────────────────────────────────┐
│  MarkFlow                            [History]  │
├────────────────────────────────────────────────┤
│  Converting 5 files...                          │
│  ████████████░░░░░░░  3 / 5                    │
├────────────────────────────────────────────────┤
│  ✓  report.docx          → report.md     840ms │
│  ✓  slides.pptx          → slides.md   1.2s    │
│  ✓  data.xlsx            → data.md      310ms  │
│  ⟳  scan.pdf             converting...         │
│  ·  notes.csv            waiting               │
├────────────────────────────────────────────────┤
│  [Download All]  [View History]                 │
└────────────────────────────────────────────────┘
```

Behavior:
- Open `EventSource` to `/api/batch/{batch_id}/stream`.
- On `file_start`: set file row to "converting..." with spinner.
- On `file_complete`: update row to ✓ with duration. Advance progress bar.
- On `file_error`: update row to ✗ with error message (truncated to ~60 chars, full message
  in a `<details>` expand).
- On `ocr_flag`: append a banner below the file row — "3 pages need OCR review" with a
  link to `/review.html?batch_id=...`. The link is prominent — OCR review is a dead end
  if the user can't find it.
- On `batch_complete`: update header to "Done — 4 of 5 succeeded". Enable "Download All"
  button (links to `/api/batch/{batch_id}/download`). Enable "View History" button.
- On `done`: close EventSource.
- On EventSource error (connection dropped): show a "Reconnecting..." badge. Retry with
  exponential backoff (1s, 2s, 4s, max 10s). After 3 failed reconnects: show
  "Connection lost — [Refresh]" with manual refresh button.
- Progress bar: CSS transition on width, 0% → 100% as files complete. Use a smooth CSS
  animation on the bar itself (not just jumps). Indeterminate state before first event.

### 2.4 Track A Done Criteria

- [ ] Upload 3+ files → progress.html shows live per-file updates
- [ ] Each file shows ✓ / ✗ / spinner with correct state
- [ ] Progress bar advances smoothly as files complete
- [ ] OCR flag banner appears when a file has flagged pages
- [ ] "Download All" is disabled until batch_complete, then enabled
- [ ] Client reconnect after disconnect replays events from correct position
- [ ] `GET /api/batch/{id}/stream` is covered by a test using `httpx` in streaming mode

---

## 3. Track B — History Page

### 3.1 Goal

A dedicated page showing all past conversions — filterable by format, searchable by filename,
sortable by date/duration, with re-download and detail views.

### 3.2 Backend

#### `api/routes/history.py` (modify)

**`GET /api/history`** (extend existing)

Add query params:
- `format` — filter by source format (`docx`, `pdf`, `pptx`, `xlsx`, `csv`)
- `status` — filter by status (`success`, `error`)
- `search` — substring match on filename (case-insensitive)
- `sort` — `date_desc` (default), `date_asc`, `duration_asc`, `duration_desc`
- `page` — 1-indexed (default 1)
- `per_page` — 10, 25, 50 (default 25)

Response (extend existing `HistoryListResponse`):
```json
{
  "records": [...],
  "total": 312,
  "page": 1,
  "per_page": 25,
  "total_pages": 13,
  "formats_available": ["docx", "pdf", "pptx"],
  "has_errors": true
}
```

**`GET /api/history/{id}/redownload`** (new)

Returns the output `.md` file (or zip if the batch had multiple files) for a past conversion.
If the output files have been cleaned up (output directory deleted), return 410 Gone with a
JSON body: `{"error": "output_expired", "message": "Output files for this batch are no longer available"}`.

**`GET /api/history/stats`** (extend existing)

Add to response:
```json
{
  "total_conversions": 312,
  "success_count": 307,
  "error_count": 5,
  "by_format": {"docx": 120, "pdf": 98, "pptx": 45, "xlsx": 30, "csv": 19},
  "avg_duration_ms": 720,
  "total_size_bytes_processed": 1240000000
}
```

### 3.3 Frontend — `static/history.html` (new)

Layout (full-width):
```
┌────────────────────────────────────────────────────────┐
│  MarkFlow                         [Convert] [Settings]  │
├────────────────────────────────────────────────────────┤
│  Conversion History                                     │
│                                                         │
│  Stats: 312 conversions · 98.4% success · avg 720ms    │
│  ────────────────────────────────────────────────────  │
│  [All formats ▾] [All status ▾]  🔍 Search files...    │
│  ────────────────────────────────────────────────────  │
│  Filename          Format  Status  Duration  Date  [↓]  │
│  ─────────────────────────────────────────────────────  │
│  report.docx       DOCX    ✓       840ms     Today      │
│  budget.xlsx       XLSX    ✓       310ms     Today      │
│  scan.pdf          PDF     ✗       —         Yesterday  │
│  ─────────────────────────────────────────────────────  │
│  ← 1 2 3 … 13 →     Showing 1–25 of 312                │
└────────────────────────────────────────────────────────┘
```

Behaviors:
- Clicking a filename row opens an inline detail panel (not a new page) below the row:
  ```
  ▼ report.docx
    Converted: 2026-03-21 14:32:01
    Format: DOCX → Markdown
    Fidelity tier: 2
    Duration: 840ms
    Output: report.md (12.4 KB)
    [Download]  [Open OCR Review ↗]   ← OCR review link only shown if ocr_flags > 0
    Error detail: (only shown if status=error)
  ```
- Inline detail panel closes when row is clicked again.
- "Download" button hits `/api/history/{id}/redownload`. If 410, show inline
  "Output files expired — cannot re-download" (do not open a broken link).
- Filter dropdowns update URL query params (`?format=pdf&status=error&page=1`) so the
  filtered view is bookmarkable/shareable.
- Search input debounces 300ms before fetching.
- Column header clicks toggle sort (`date_desc` ↔ `date_asc`, etc.). Active sort column
  shows ↑ or ↓ indicator.
- Pagination: show page numbers with ellipsis for large sets. `← Prev` and `Next →` always
  visible. Current page highlighted.
- Format badges (pill labels): DOCX, PDF, PPTX, XLSX, CSV — each with a distinct color
  using CSS variables. Consistent with whatever color system the design track (Track D) establishes.
- Error rows: ✗ in status column, row gets a subtle red left-border to stand out.

### 3.4 Track B Done Criteria

- [ ] `GET /api/history?format=pdf&status=error` returns filtered results
- [ ] `GET /api/history?search=report` returns filename-matched results
- [ ] `GET /api/history?sort=duration_asc` returns sorted results
- [ ] `GET /api/history/{id}/redownload` returns file or 410
- [ ] History page loads and paginates correctly
- [ ] Inline detail panel opens/closes on row click
- [ ] Filter + search update URL params and survive page refresh
- [ ] Column sort toggles and shows correct indicator
- [ ] 410 on redownload shows inline "expired" message (not a broken download)

---

## 4. Track C — Settings Page

### 4.1 Goal

A settings page that exposes user preferences via a form backed by the existing
`GET /api/preferences` and `PUT /api/preferences/{key}` endpoints.

### 4.2 Preferences to Expose

Check the current `preferences` table in the DB for all keys. At minimum, expose:

| Key | Label | Type | Notes |
|-----|-------|------|-------|
| `default_fidelity_tier` | Default fidelity tier | Select | 1 / 2 / 3 |
| `ocr_confidence_threshold` | OCR confidence threshold | Slider | 0–100, default 70 |
| `ocr_unattended_mode` | OCR unattended mode | Toggle | skip review, accept all flags |
| `max_file_size_mb` | Max upload file size (MB) | Number | 1–500 |
| `output_retention_days` | Keep output files for (days) | Number | 1–365, 0 = forever |
| `last_source_directory` | Last source directory | Text (read-only) | Set automatically by converter |

### 4.3 Backend

#### `api/routes/preferences.py` (modify)

`PUT /api/preferences/{key}` — add server-side validation per key:
- `default_fidelity_tier`: must be `1`, `2`, or `3`
- `ocr_confidence_threshold`: must be integer 0–100
- `max_file_size_mb`: must be integer 1–500
- `output_retention_days`: must be integer 0–365
- `ocr_unattended_mode`: must be `"true"` or `"false"` (string, stored as string in SQLite)

Return 422 with a descriptive error if validation fails. Do not silently clamp values — reject
and tell the client what the valid range is.

`GET /api/preferences` — add a `schema` field to the response that describes valid values for
each key. This lets the frontend build the form dynamically:
```json
{
  "preferences": {"default_fidelity_tier": "2", ...},
  "schema": {
    "default_fidelity_tier": {"type": "select", "options": ["1", "2", "3"], "label": "Default fidelity tier"},
    "ocr_confidence_threshold": {"type": "range", "min": 0, "max": 100, "label": "OCR confidence threshold"},
    ...
  }
}
```

### 4.4 Frontend — `static/settings.html` (new)

Layout:
```
┌────────────────────────────────────────────────┐
│  MarkFlow                            [Convert]  │
├────────────────────────────────────────────────┤
│  Settings                                       │
│                                                 │
│  Conversion                                     │
│  ─────────────────────────────────────────────  │
│  Default fidelity tier    [Tier 2 ▾]            │
│  Max upload file size     [100] MB              │
│  Output retention         [30] days             │
│                                                 │
│  OCR                                            │
│  ─────────────────────────────────────────────  │
│  Confidence threshold     ━━━━●━━━━  70%        │
│  Unattended mode          [ OFF ]               │
│                                                 │
│  Info                                           │
│  ─────────────────────────────────────────────  │
│  Last source directory    /mnt/documents (read-only) │
│                                                 │
│  [Save Changes]  [Reset to Defaults]            │
└────────────────────────────────────────────────┘
```

Behaviors:
- On load: `GET /api/preferences` — populate all inputs from `preferences` object.
- Changes are tracked locally — the form is not auto-saving (avoid surprising the user).
- "Save Changes" button:
  - Sends `PUT /api/preferences/{key}` for each changed preference (only changed keys).
  - Show a spinner on the button during save.
  - On success: show a green "Saved" inline confirmation that fades after 3 seconds.
  - On 422 validation error: show the server's error message inline next to the field
    (not a generic "save failed" toast).
- "Reset to Defaults" button:
  - Shows a confirmation dialog (`<dialog>` element — no `window.confirm()`).
  - On confirm: sends `PUT` for each key with its default value, then reloads form.
- Range slider: show current value as a text label that updates live as the slider moves
  (before save). Use `<input type="range">` with an adjacent `<output>` element.
- Toggle for `ocr_unattended_mode`: use a CSS toggle switch (not a checkbox). Clear ON/OFF
  label next to it.
- Fidelity tier select: show a brief description below the select when a tier is selected:
  - Tier 1: "Structure only — headings, paragraphs, tables. Fast."
  - Tier 2: "Structure + original styles from sidecar JSON. Recommended."
  - Tier 3: "Patch original file — near-perfect fidelity for unedited content."

### 4.5 Track C Done Criteria

- [ ] Settings page loads and populates all preferences correctly
- [ ] Changing a value and clicking Save sends only the changed keys
- [ ] Validation error from server shows inline next to the field
- [ ] Reset to Defaults requires confirmation and reloads form
- [ ] Slider shows live value update before save
- [ ] Toggle switch works for unattended mode
- [ ] Fidelity tier descriptions update on select change
- [ ] `PUT /api/preferences/ocr_confidence_threshold` with `value=999` returns 422

---

## 5. Track D — UI Cohesion Pass

### 5.1 Goal

All user-facing pages (`index.html`, `progress.html`, `history.html`, `settings.html`,
`review.html`, `results.html`) must share a consistent visual design — same colors, fonts,
component shapes, and navigation header. The debug dashboard (`debug.html`) keeps its own
developer aesthetic from Phase 5 and is deliberately excluded from this pass.

### 5.2 Shared CSS — `static/markflow.css` (new file)

Extract all shared styles into `markflow.css`. Every user-facing page imports it via:
```html
<link rel="stylesheet" href="/static/markflow.css">
```

Required contents:

**CSS variables (`:root`):**
```css
:root {
  --bg:          /* page background */
  --surface:     /* card / panel background */
  --surface-alt: /* alternate row, hover background */
  --border:      /* border color */
  --text:        /* primary text */
  --text-muted:  /* secondary / label text */
  --text-on-accent: /* text on colored backgrounds */
  --accent:      /* primary action color */
  --accent-hover:
  --ok:          /* success green */
  --warn:        /* warning amber */
  --error:       /* error red */
  --info:        /* info blue */
  --radius:      /* border-radius for cards/buttons */
  --radius-sm:   /* border-radius for pills/badges */
  --font-sans:   /* body font stack */
  --font-mono:   /* code/filename font stack */
  --shadow:      /* default card shadow */
  --transition:  /* default transition duration+easing */
}
```

**Format badge colors** — one CSS class per format:
```css
.badge-docx { background: ...; color: ...; }
.badge-pdf  { ... }
.badge-pptx { ... }
.badge-xlsx { ... }
.badge-csv  { ... }
```

**Shared components:**
- `.nav-bar` — top navigation bar (logo left, nav links right)
- `.btn` — base button style
- `.btn-primary` — accent fill button
- `.btn-ghost` — text-only button
- `.btn-danger` — destructive action button
- `.status-ok`, `.status-error`, `.status-warn` — status pill styles
- `.progress-bar` wrapper + `.progress-bar__fill` inner element
- `.spinner` — CSS-only spinner animation
- `.card` — surface container with border and shadow
- `.form-group` — label + input + helper text layout
- `.inline-error` — red validation message below a field
- `.toast` — brief success/info message (absolute positioned, fades out)
- `.dialog-backdrop` + `.dialog` — modal dialog styles

**Typography:**
- Pick ONE sans-serif font for the UI (load from Google Fonts or use a system font stack —
  but not `Arial`, `Roboto`, or `Inter`). Something that reads well in a tool context.
- Mono font for filenames, durations, IDs. `JetBrains Mono` or `IBM Plex Mono` (already in
  `debug.html` — stay consistent with it).
- Define `h1–h4` and `p` base styles. Navigation and button text inherit from body.

**Color theme:**
- Light mode by default. Include a `@media (prefers-color-scheme: dark)` block that overrides
  the CSS variables — the component code does not change, only the variable values.

### 5.3 Navigation Header

Every user-facing page has:
```html
<nav class="nav-bar">
  <a href="/" class="nav-logo">MarkFlow</a>
  <div class="nav-links">
    <a href="/" class="nav-link">Convert</a>
    <a href="/history.html" class="nav-link">History</a>
    <a href="/settings.html" class="nav-link">Settings</a>
  </div>
</nav>
```

The active page's nav link has class `nav-link--active`. Each page sets this via a small
inline `<script>` that adds the class based on `window.location.pathname`.

`review.html` and `debug.html` do NOT show the main nav. `review.html` has its own contextual
header ("OCR Review — back to progress"). `debug.html` is standalone.

### 5.4 `static/index.html` (modify)

Apply `markflow.css`. Use shared components for:
- Upload area — use `.card` wrapper
- Fidelity tier selector — use `.form-group` pattern
- Submit button — use `.btn.btn-primary`

Remove any inline CSS that is now covered by `markflow.css`. Keep page-specific styles in a
`<style>` block.

### 5.5 `static/results.html` (modify)

Apply `markflow.css`. This page currently exists as a download summary — update it to:
- Redirect to `history.html?highlight={batch_id}` for the relevant batch (the history page
  subsumes the results page's purpose).
- Keep `results.html` as a thin redirect page in case of bookmarks. It should auto-redirect
  after 1 second with a "Redirecting to history..." message.

Alternatively: keep `results.html` as a simple "Your files are ready" interstitial that also
links to the history entry. If `progress.html` now owns the download CTA, `results.html` may
be redundant — make the call and document it.

### 5.6 Track D Done Criteria

- [ ] `markflow.css` exists and is imported by all user-facing pages
- [ ] All CSS variable names are defined in `:root`
- [ ] Dark mode works via `prefers-color-scheme` without any JavaScript
- [ ] Format badges have distinct colors
- [ ] Navigation header appears on all user-facing pages (not review.html or debug.html)
- [ ] Active nav link is highlighted correctly on each page
- [ ] Button styles are consistent across all pages
- [ ] No inline `style=""` attributes for anything covered by `markflow.css`
- [ ] Page loads without FOUC (flash of unstyled content) — CSS is in `<head>`

---

## 6. Track E — Error UX

### 6.1 Goal

Every error state has a clear, specific message and a next action. No dead ends.

### 6.2 Error Inventory — Audit These States

Go through each page and verify these error states are handled:

**Upload / Convert (`index.html`):**
- [ ] File too large → "File exceeds 100 MB limit" (show the configured limit, not a hardcoded value)
- [ ] Unsupported format → "`.xyz` files are not supported. Supported: DOCX, PDF, PPTX, XLSX, CSV"
- [ ] No file selected → "Please select at least one file" (button stays disabled until file is selected)
- [ ] Upload fails (network error) → "Upload failed. Check your connection and try again." with retry button
- [ ] Server 500 on convert → "Conversion service error. Try again or check the debug dashboard."

**Progress (`progress.html`):**
- [ ] Individual file error → ✗ with truncated error, expandable full message
- [ ] All files errored → Final summary emphasizes this clearly, not just "0 of 5 succeeded"
- [ ] Connection lost → Reconnecting badge, then manual refresh fallback (see Track A)

**History (`history.html`):**
- [ ] Empty history → "No conversions yet. [Convert your first file →]"
- [ ] Empty filtered result → "No conversions match these filters. [Clear filters]"
- [ ] Download expired (410) → Inline "Output expired" message, not broken download
- [ ] Search returns nothing → "No files matching '{term}'" with clear button

**Settings (`settings.html`):**
- [ ] Validation error → Inline, field-specific error message
- [ ] Save fails (network) → "Save failed. Check your connection." inline, keep form state

**OCR Review (`review.html`):**
- [ ] No pending flags → "No pages need review. [Return to conversion →]"
- [ ] Flag already resolved → Soft message, skip to next flag automatically

### 6.3 Track E Done Criteria

- [ ] Every error state in the inventory above is implemented and tested manually
- [ ] No error state results in a blank page or console error
- [ ] Error messages reference actionable next steps (not just "an error occurred")
- [ ] Loading states are shown before data arrives (skeleton or spinner — no blank flash)

---

## 7. Backend Additions Summary

Only these backend changes are in scope for Phase 6:

| File | Change |
|------|--------|
| `api/routes/batch.py` | Add `GET /api/batch/{id}/stream` (SSE) |
| `api/routes/convert.py` | Return `stream_url` in convert response |
| `api/routes/history.py` | Add filter/sort/search params; add `/redownload` endpoint |
| `api/routes/preferences.py` | Add per-key validation; add `schema` to GET response |
| `core/converter.py` | Add progress queue; emit SSE events per file |
| `api/models.py` | Extend `HistoryListResponse`, add `PreferenceSchema` model |

No changes to: `core/converter.py` conversion logic, any format handler, `core/ocr.py`,
`core/database.py` schema (add columns only if absolutely required and documented).

---

## 8. Tests

### `tests/test_sse.py` (new)

- [ ] `GET /api/batch/{id}/stream` with valid batch_id → streams `file_start` and
  `batch_complete` events
- [ ] Events are valid SSE format (`event: ...\ndata: ...\n\n`)
- [ ] `data` field parses as valid JSON
- [ ] Stream closes after `event: done`
- [ ] `GET /api/batch/{id}/stream` with unknown batch_id → 404

### `tests/test_history.py` (new / extend existing)

- [ ] `GET /api/history?format=pdf` returns only PDF records
- [ ] `GET /api/history?status=error` returns only error records
- [ ] `GET /api/history?search=report` returns filename-matched records
- [ ] `GET /api/history?sort=duration_asc` returns sorted records
- [ ] `GET /api/history?page=2&per_page=10` returns correct slice
- [ ] `GET /api/history/{id}/redownload` → 200 if output exists
- [ ] `GET /api/history/{id}/redownload` → 410 if output deleted

### `tests/test_preferences.py` (new / extend existing)

- [ ] `PUT /api/preferences/ocr_confidence_threshold` with value `70` → 200
- [ ] `PUT /api/preferences/ocr_confidence_threshold` with value `999` → 422
- [ ] `PUT /api/preferences/default_fidelity_tier` with value `4` → 422
- [ ] `GET /api/preferences` response includes `schema` field

---

## 9. Static File Serving

Verify `main.py` mounts static files correctly for the new pages:
- `progress.html`, `history.html`, `settings.html` must be reachable at their root paths.
- If using `StaticFiles(directory="static", html=True)`, all `.html` files are served
  automatically — no per-page route needed.
- If individual routes exist for pages, add the new ones.

---

## 10. Done Criteria (Full Phase)

- [ ] Track A: Live SSE progress works end-to-end for multi-file batch
- [ ] Track B: History page loads, filters, paginates, and shows inline detail
- [ ] Track C: Settings page loads, saves, validates, resets
- [ ] Track D: `markflow.css` shared by all user-facing pages; dark mode works
- [ ] Track E: All error inventory states implemented
- [ ] `pytest` → all prior tests still passing + new Track A/B/C tests
- [ ] `docker-compose build && docker-compose up -d` → clean build
- [ ] Manual smoke: upload 3 files → watch progress → view history → download from history
- [ ] Manual smoke: set OCR threshold to 95 → verify it affects next conversion
- [ ] No `console.error` or unhandled promise rejections in browser devtools during normal use

---

## 11. CLAUDE.md Update

After all done criteria pass:

```markdown
**Phase 6 complete** — Full UI: live SSE batch progress, history page (filter/sort/search/
  redownload), settings page (preferences with validation), shared CSS design system,
  dark mode, comprehensive error UX. Tagged v0.6.0.
**Next: Phase 7** — Bulk conversion, Adobe indexing, Meilisearch search, Cowork integration.
```

Update phase checklist:
```
| 6 | Full UI, batch progress, history page, settings, polish | ✅ Done |
```

Add any new gotchas to the **Gotchas & Fixes Found** section. In particular, document any SSE
connection behavior quirks found during testing.

Then tag: `git tag v0.6.0 && git push origin v0.6.0`

---

## 12. Output Cap Warning

Suggested turn boundaries:

1. **Turn 1**: Track A backend — SSE endpoint, converter progress queue, convert response change
2. **Turn 2**: Track A frontend — `progress.html`
3. **Turn 3**: Track B backend — history filter/sort/search, redownload endpoint
4. **Turn 4**: Track B frontend — `history.html`
5. **Turn 5**: Track C — settings backend validation + schema, `settings.html`
6. **Turn 6**: Track D — `markflow.css`, nav header, update `index.html`/`results.html`
7. **Turn 7**: Track E + tests — error inventory audit, `test_sse.py`, `test_history.py`,
   `test_preferences.py`
8. **Turn 8**: Final integration — run full test suite, fix failures, update CLAUDE.md, tag

Update CLAUDE.md at the end of every session. Each turn should be committable independently.
