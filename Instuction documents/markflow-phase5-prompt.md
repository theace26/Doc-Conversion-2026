# MarkFlow Phase 5 Build Prompt
# Testing & Debug Infrastructure

**Version:** v1.0  
**Targets:** v0.5.0 tag  
**Prerequisite:** Phase 4 complete — 231 tests passing, tagged v0.4.0

---

## 0. Read First

Load `CLAUDE.md` before writing a single line. It is the source of truth for current file locations,
gotchas discovered in earlier phases, and the exact state of the codebase entering Phase 5.

This phase has **three parallel tracks** that must all complete before the phase is done:

| Track | Scope |
|-------|-------|
| A | Structured logging — `structlog` JSON pipeline throughout all stages |
| B | Full test suite — expand to 350+ tests covering all Phase 4 format handlers |
| C | Debug dashboard — `/debug` endpoint, live system state, log tailing |

Do not skip tracks. Do not mark the phase done until all three tracks pass their done criteria.

---

## 1. Track A — Structured Logging

### 1.1 Goal

Every conversion pipeline stage, OCR event, batch operation, and API request must emit
a structured JSON log event via `structlog`. No ad-hoc `print()` or bare `logging.info()` calls.
Logs must be queryable — consistent field names, no freeform concatenated strings.

### 1.2 Files to Create / Modify

#### `core/logging_config.py` (modify — extend existing)

The file already exists. Extend it with:

- **Context var binding**: a `contextvars.ContextVar` for `request_id`, `batch_id`, `file_id`.
  Bind these at the start of each request / batch job so every downstream log event carries them
  without callers having to pass them explicitly.

- **Processor chain** (in order):
  1. `structlog.contextvars.merge_contextvars` — inject bound context vars
  2. `structlog.stdlib.add_log_level`
  3. `structlog.stdlib.add_logger_name`
  4. `structlog.processors.TimeStamper(fmt="iso")`
  5. `structlog.processors.StackInfoRenderer()`
  6. `structlog.processors.format_exc_info`
  7. `structlog.processors.JSONRenderer()` — all output is JSON

- **File handler**: rotating JSON log to `logs/markflow.json` (10 MB max, 5 backups).
  Keep the existing console handler for dev mode.

- **`configure_logging(log_level: str = "INFO", json_console: bool = False)`**: accepts
  `LOG_LEVEL` env var (default `INFO`). In Docker, `json_console=True` — write JSON to stdout
  so the container log collector can ingest it. Locally, pretty-print to console.

- **`bind_request_context(request_id, path, method)`**: call from middleware, binds to contextvars.
- **`bind_batch_context(batch_id, file_count)`**: call from `ConversionOrchestrator`.
- **`bind_file_context(file_id, filename, format)`**: call per-file inside batch loop.
- **`clear_context()`**: call at end of request in middleware finally block.

#### `api/middleware.py` (modify)

- On request start: call `bind_request_context(request_id, path, method)`.
- On request end (finally): call `clear_context()`.
- Replace any existing `logger.info(f"...")` calls with structured calls:
  ```python
  log.info("request_complete", status_code=response.status_code, duration_ms=elapsed)
  ```

#### `core/converter.py` (modify)

Add structured log events at every pipeline stage. Required event names and fields:

| Event | Fields |
|-------|--------|
| `conversion_start` | `batch_id`, `file_count`, `fidelity_tier` |
| `file_ingest_start` | `filename`, `format`, `size_bytes` |
| `file_ingest_complete` | `filename`, `element_count`, `image_count`, `duration_ms` |
| `style_extraction_complete` | `filename`, `entry_count` |
| `export_start` | `filename`, `target_format`, `tier` |
| `export_complete` | `filename`, `output_size_bytes`, `duration_ms` |
| `file_conversion_error` | `filename`, `error_type`, `error_msg`, `duration_ms` — log level `error` |
| `batch_complete` | `batch_id`, `success_count`, `error_count`, `total_duration_ms` |

Use `log.warning` (not `log.error`) for recoverable per-file issues (OCR confidence below threshold,
missing sidecar, unsupported element type). Use `log.error` only for failures that record the file
as failed in the manifest.

#### `core/ocr.py` (modify)

Add structured events:

| Event | Fields |
|-------|--------|
| `ocr_detection` | `filename`, `signal` (text_density / image_ratio / font_program), `needs_ocr` |
| `ocr_page_start` | `filename`, `page_num`, `image_size_px` |
| `ocr_page_complete` | `filename`, `page_num`, `word_count`, `mean_confidence`, `duration_ms` |
| `ocr_low_confidence` | `filename`, `page_num`, `flag_count`, `min_confidence` |
| `ocr_complete` | `filename`, `page_count`, `flagged_count`, `overall_confidence` |

#### `formats/pdf_handler.py`, `formats/pptx_handler.py`, `formats/xlsx_handler.py`, `formats/csv_handler.py`, `formats/docx_handler.py` (modify)

Each handler logs:

- `handler_ingest_start` — `filename`, `format`
- `handler_ingest_complete` — `filename`, `element_count`, `duration_ms`
- `handler_export_start` — `filename`, `target_format`, `tier`
- `handler_export_complete` — `filename`, `output_path`, `duration_ms`
- `handler_error` — `filename`, `stage` (ingest/export), `error_type`, `error_msg`

All handlers must use `structlog.get_logger(__name__)` — not `logging.getLogger`.

#### `api/routes/convert.py`, `api/routes/batch.py`, `api/routes/history.py`, `api/routes/review.py` (modify)

Replace any bare `logging` calls with structured calls. Add events:

- `convert_request` — `filename`, `size_bytes`, `content_type`
- `batch_status_request` — `batch_id`
- `ocr_review_resolve` — `batch_id`, `flag_id`, `action` (accept/correct)

### 1.3 Track A Done Criteria

- [ ] `docker-compose logs -f` shows JSON-formatted log lines with `request_id`, `batch_id`, `filename`
  fields on relevant events
- [ ] Log file written to `logs/markflow.json` inside the container
- [ ] No `print()` calls remain in any `core/` or `formats/` file
- [ ] No bare `logging.info(f"...")` calls remain — all go through structlog
- [ ] `LOG_LEVEL=DEBUG` env var enables debug-level events without code changes
- [ ] Request ID threads from middleware through converter through handler events in the same request

---

## 2. Track B — Full Test Suite

### 2.1 Goal

Expand from 231 tests to **350+ tests** covering all Phase 4 format handlers in both directions,
error/edge cases, and integration flows. All tests must be deterministic (no disk side effects,
no network calls, no real Tesseract invocations unless marked `@pytest.mark.ocr`).

### 2.2 Test Infrastructure

#### `tests/conftest.py` (modify — extend)

Add fixtures:

```python
@pytest.fixture
def simple_pdf_path(tmp_path) -> Path:
    """Generates a minimal text-native PDF using reportlab or fpdf2."""

@pytest.fixture
def scanned_pdf_path(tmp_path) -> Path:
    """PDF that is image-only — no text layer. Forces OCR path."""

@pytest.fixture
def simple_pptx_path(tmp_path) -> Path:
    """3-slide PPTX: title slide, content slide with bullet list, slide with table."""

@pytest.fixture
def simple_xlsx_path(tmp_path) -> Path:
    """Workbook: Sheet1 = simple table, Sheet2 = merged cells, Sheet3 = formula cells."""

@pytest.fixture
def simple_csv_path(tmp_path) -> Path:
    """UTF-8 CSV, 5 columns, 20 rows. Header row."""

@pytest.fixture
def tsv_path(tmp_path) -> Path:
    """Tab-separated file."""

@pytest.fixture
def latin1_csv_path(tmp_path) -> Path:
    """CSV encoded in latin-1 to test encoding detection."""

@pytest.fixture
def document_model_with_all_elements() -> DocumentModel:
    """DocumentModel containing every ElementType — used to test round-trip completeness."""
```

All fixtures generate files programmatically using the same libraries MarkFlow uses for export
(`fpdf2` or `reportlab` for PDF, `python-pptx` for PPTX, `openpyxl` for XLSX). Never depend on
checked-in binary fixture files for format-specific tests.

#### `tests/generate_fixtures.py` (modify — extend)

Add `generate_all_fixtures()` that creates the full fixture set to `tests/fixtures/` for manual
inspection during development. This is not run during CI — it's a development convenience.

### 2.3 New Test Files

#### `tests/test_pdf_handler.py`

Tests for `formats/pdf_handler.py`:

**Ingest — text-native PDF:**
- [ ] Extracts paragraphs as `PARAGRAPH` elements
- [ ] Detects headings by font size relative to body font
- [ ] Extracts tables to `TABLE` elements
- [ ] `DocumentMetadata.page_count` matches actual page count
- [ ] YAML frontmatter contains `source_format: pdf`
- [ ] Images embedded in PDF are extracted and referenced in `IMAGE` elements
- [ ] Multi-page PDF produces elements in page order

**Ingest — OCR path:**
- [ ] Image-only PDF triggers OCR pipeline (mock `run_ocr`, assert called)
- [ ] OCR result is included in `DocumentModel` elements
- [ ] Low-confidence pages produce OCR flags in the database

**Ingest — edge cases:**
- [ ] Empty PDF (0 pages) raises `ConversionError` with clear message
- [ ] Password-protected PDF raises `ConversionError` (not unhandled exception)
- [ ] Corrupt PDF bytes raises `ConversionError`
- [ ] PDF with no extractable text and OCR disabled returns model with `ocr_skipped` flag in metadata

**Export — Markdown → PDF:**
- [ ] All `ElementType`s survive export without raising
- [ ] H1 renders as large heading, H2 as subheading (inspect HTML intermediate)
- [ ] Tables render in HTML intermediate
- [ ] Output is valid PDF bytes (starts with `%PDF-`)
- [ ] Export is always Tier 1 (PDF cannot be patched)

#### `tests/test_pptx_handler.py`

**Ingest:**
- [ ] Each slide becomes an `H2` element (slide title) followed by content elements
- [ ] Bullet list items become `LIST_ITEM` elements
- [ ] Tables on slides become `TABLE` elements
- [ ] Speaker notes become `BLOCKQUOTE` elements
- [ ] Slide images extracted as `IMAGE` elements with alt text from shape name
- [ ] Hidden slides are skipped (or flagged — document the decision)
- [ ] `DocumentMetadata.page_count` == slide count

**Ingest — edge cases:**
- [ ] Empty presentation (0 slides) raises `ConversionError`
- [ ] Slide with no title placeholder: use slide index as fallback heading
- [ ] Shape with no text (e.g., decorative line) does not produce empty element
- [ ] `ValueError` from `placeholder_format` on non-placeholder shapes is caught (see CLAUDE.md gotcha)
- [ ] `_NoneColor` on `run.font.color.rgb` is handled without raising

**Export — Markdown → PPTX:**
- [ ] H2 sections become slides
- [ ] List items render in content placeholder
- [ ] Tables render in table shape
- [ ] Tier 3 patching: when original PPTX provided, unchanged slides are bit-identical

**Export — edge cases:**
- [ ] Markdown with no H2 headings produces a single slide
- [ ] Table wider than slide width is exported without crashing (content may truncate — log warning)

#### `tests/test_xlsx_handler.py`

**Ingest:**
- [ ] Each sheet becomes an `H2` element followed by a `TABLE` element
- [ ] Merged cells are unmerged and top-left value duplicated (see CLAUDE.md gotcha)
- [ ] Computed cell values (data_only=True) are used, not formula strings
- [ ] Formula strings preserved in sidecar JSON when `data_only=False` workbook is opened
- [ ] `DocumentMetadata.page_count` == sheet count
- [ ] Empty sheet produces `H2` element and no `TABLE` (or empty table — document decision)

**Ingest — edge cases:**
- [ ] Corrupt XLSX raises `ConversionError`
- [ ] XLSX with chart-only sheet does not crash — logs warning, skips sheet
- [ ] Very wide table (50+ columns) ingests without hanging

**Export:**
- [ ] TABLE elements round-trip to correct column count and row count
- [ ] Tier 2: column widths from sidecar are applied
- [ ] Tier 3: formula cells from sidecar are written back (formula strings, not values)
- [ ] Multiple sheets (H2 sections) produce multiple sheets in output workbook

#### `tests/test_csv_handler.py`

**Ingest:**
- [ ] UTF-8 CSV → single `TABLE` element with correct row and column count
- [ ] UTF-8-BOM CSV (`utf-8-sig`) is read correctly (no BOM artifact in first column name)
- [ ] Latin-1 encoded CSV is read correctly via encoding fallback chain
- [ ] TSV (tab-separated) is detected and read correctly
- [ ] Header row becomes table headers
- [ ] Empty CSV raises `ConversionError`
- [ ] Single-column CSV (no delimiter) ingests as single-column table
- [ ] `DocumentMetadata.page_count` == 1 (CSV has no concept of pages)

**Export:**
- [ ] TABLE element round-trips to CSV with same row/column count
- [ ] Original delimiter is preserved (TSV exports as TSV, not CSV)
- [ ] UTF-8 output unless original encoding is preserved in sidecar

#### `tests/test_round_trip.py` (new file)

Cross-format round-trip tests. These test the full pipeline: ingest → DocumentModel → export → re-ingest → compare.

- [ ] DOCX → MD → DOCX: heading hierarchy preserved, table cell count preserved
- [ ] PDF → MD → PDF: paragraph count within ±10% (OCR noise tolerance)
- [ ] PPTX → MD → PPTX: slide count preserved, table count preserved
- [ ] XLSX → MD → XLSX: sheet count preserved, row count preserved per sheet
- [ ] CSV → MD → CSV: row count and column count exact match

Round-trip tests are allowed to use `@pytest.mark.slow` and be excluded from fast test runs.

#### `tests/test_logging.py` (new file)

Verify structured logging behavior:

- [ ] A conversion request emits `conversion_start` event with `batch_id` field
- [ ] A conversion error emits `file_conversion_error` at `error` level
- [ ] `LOG_LEVEL=DEBUG` enables debug events
- [ ] `request_id` appears in all log events during a request (use caplog + contextvars)
- [ ] No event uses `f-string` concatenation as the message (message is always a static string,
  data in fields)
- [ ] Log output is valid JSON when `json_console=True`

#### `tests/test_api_integration.py` (new file)

End-to-end API tests using `httpx.AsyncClient` against the full FastAPI app (no mocks except for
Tesseract):

- [ ] `POST /api/convert` with DOCX → 200, returns `batch_id`
- [ ] `POST /api/convert` with PDF (text-native) → 200
- [ ] `POST /api/convert` with PPTX → 200
- [ ] `POST /api/convert` with XLSX → 200
- [ ] `POST /api/convert` with CSV → 200
- [ ] `POST /api/convert` with oversized file → 413
- [ ] `POST /api/convert` with disallowed extension → 422
- [ ] `GET /api/batch/{id}/status` → 200 with correct `file_count`
- [ ] `GET /api/batch/{id}/download` → 200, content-type zip
- [ ] `GET /api/batch/{id}/manifest` → 200, valid JSON manifest
- [ ] `GET /api/health` → 200, all components reported
- [ ] `GET /api/history` → 200, paginated response
- [ ] `GET /debug` → 200, HTML response (smoke test only)

### 2.4 Expand Existing Tests

#### `tests/test_api.py` (modify)

Add tests for:
- [ ] `POST /api/convert` with multiple files in one request
- [ ] `POST /api/convert/preview` returns format, estimated element count, OCR flag

#### `tests/test_docx.py` (modify)

Add edge-case tests that were deferred from Phase 1/2:
- [ ] DOCX with embedded OLE object (non-image) — element is skipped, warning logged
- [ ] DOCX with extremely long paragraph (10,000+ chars) — no truncation, no crash
- [ ] DOCX with all three fidelity tiers explicitly: fixture generates DOCX + sidecar + original

### 2.5 Test Markers

Register these markers in `pytest.ini` (or `pyproject.toml`):

```ini
[pytest]
markers =
    slow: marks tests that take > 2 seconds (deselect with -m "not slow")
    ocr: marks tests that invoke real Tesseract (deselect with -m "not ocr")
    integration: marks end-to-end API tests (deselect with -m "not integration")
```

The CI fast path runs `pytest -m "not slow and not ocr"`. Full suite runs `pytest`.

### 2.6 Track B Done Criteria

- [ ] `pytest` passes with 350+ tests
- [ ] `pytest -m "not slow and not ocr"` completes in under 60 seconds
- [ ] Zero tests depend on network access or external services (mock everything)
- [ ] All fixtures are generated programmatically — no binary files checked into `tests/`
- [ ] Coverage report: `pytest --cov=core --cov=formats --cov=api` shows ≥ 80% line coverage
- [ ] No test uses `assert "error" not in response.text` — all assertions are specific

---

## 3. Track C — Debug Dashboard

### 3.1 Goal

A single-page `/debug` endpoint that gives a live view of system health, recent activity, and
internal state. This is a developer/operator tool — not a user-facing page. It does not need to
be beautiful, but it must be functional, readable, and update without a full page reload.

### 3.2 Backend

#### `api/routes/debug.py` (new file)

Router with prefix `/debug`. Mount in `main.py`.

**`GET /debug`** — serves `static/debug.html`

**`GET /debug/api/health`** — returns JSON health snapshot:
```json
{
  "status": "ok",
  "timestamp": "ISO-8601",
  "uptime_seconds": 3600,
  "components": {
    "database": {"status": "ok", "path": "/app/data/markflow.db", "size_bytes": 12345},
    "tesseract": {"status": "ok", "version": "5.3.0"},
    "poppler": {"status": "ok"},
    "weasyprint": {"status": "ok"},
    "meilisearch": {"status": "not_configured"},
    "disk": {"status": "ok", "free_gb": 45.2, "used_gb": 12.1}
  }
}
```

**`GET /debug/api/activity`** — returns recent conversion activity:
```json
{
  "active_batches": [
    {"batch_id": "...", "file_count": 12, "completed": 7, "started_at": "ISO-8601"}
  ],
  "recent_history": [
    {"batch_id": "...", "filename": "report.docx", "status": "success",
     "format": "docx", "duration_ms": 840, "completed_at": "ISO-8601"}
  ],
  "ocr_flags": {
    "pending": 3,
    "accepted": 145,
    "corrected": 12
  },
  "stats": {
    "total_conversions": 312,
    "success_rate_pct": 98.4,
    "avg_duration_ms": 720
  }
}
```

**`GET /debug/api/logs`** — returns last N lines from `logs/markflow.json`, parsed as JSON array.
Query param: `?lines=100` (default 100, max 500). Returns the raw JSON objects, not strings.

```json
{
  "lines": 100,
  "log_file": "logs/markflow.json",
  "events": [ { ...structlog event... }, ... ]
}
```

If the log file doesn't exist (e.g., first run), return `{"events": [], "lines": 0}` — do not 404.

**`GET /debug/api/ocr_distribution`** — returns confidence score distribution for OCR'd files:
```json
{
  "buckets": [
    {"range": "0-10", "count": 2},
    {"range": "10-20", "count": 0},
    ...
    {"range": "90-100", "count": 89}
  ],
  "mean_confidence": 87.3,
  "total_pages": 412
}
```
Pull from the `ocr_flags` table in SQLite — group by confidence range.

#### `core/health.py` (modify)

Extract the startup health check logic into a reusable `run_health_check() -> dict` function that
returns the JSON structure above. Both the startup lifespan check and the `/debug/api/health`
endpoint call this function. Do not duplicate the check logic.

### 3.3 Frontend — `static/debug.html`

A single HTML file. No external CSS framework (vanilla CSS only, per architecture rules).
Auto-refreshes every 10 seconds via `setInterval` + `fetch`. No full page reload.

**Layout — four sections, stacked vertically:**

---

**Section 1: System Health**
- Row of component status pills: `database ✓`, `tesseract ✓`, `weasyprint ✓`, `meilisearch —`, etc.
- Each pill: green for `ok`, yellow for `warning`, red for `error`, gray for `not_configured`
- Uptime and timestamp updated each refresh

**Section 2: Activity**
- Left column: **Active Batches** — table with `batch_id`, `progress (7/12)`, `started`
- Right column: **Recent Conversions** — last 20 rows from history: filename, format, status
  (✓ / ✗), duration, timestamp
- Stats bar: total conversions, success rate %, avg duration

**Section 3: OCR Confidence Distribution**
- Horizontal bar chart (pure CSS — no canvas, no JS charting library)
- 10 bars representing 0-10%, 10-20%, ..., 90-100% confidence buckets
- Each bar's width proportional to its count
- Mean confidence score shown as text
- Only shown if OCR data exists, otherwise: "No OCR data yet"

**Section 4: Log Viewer**
- Scrollable `<pre>` block, max height 400px, overflow-y scroll
- Shows last 50 log events as pretty-printed JSON (2-space indent)
- Color-coding via CSS: `"level":"error"` lines in red, `"level":"warning"` in yellow,
  `"level":"info"` in default
- "Refresh" button to manually fetch latest lines
- "Lines: 50 / 100 / 200" toggle buttons to change how many lines are shown
- Auto-refresh respects the current line count setting

**Top bar:**
- App name + version (from `/api/health`)
- Last refreshed timestamp
- "Auto-refresh: ON / OFF" toggle button

**Styling:**
- Dark background (`#0f1117`), monospace font throughout (use `JetBrains Mono` or `IBM Plex Mono`
  from Google Fonts — this is a developer tool, mono is appropriate)
- Use CSS variables for the color palette — at minimum: `--bg`, `--surface`, `--border`,
  `--text`, `--accent`, `--ok`, `--warn`, `--error`, `--muted`
- No generic `Arial`/`Inter`/`Roboto` — pick something that says "developer tool"
- Component status pills use border + background, not just text color — readable at a glance

### 3.4 Track C Done Criteria

- [ ] `GET /debug` returns 200 with the dashboard HTML
- [ ] `GET /debug/api/health` returns JSON with all components reported
- [ ] `GET /debug/api/activity` returns JSON with recent history and OCR flag counts
- [ ] `GET /debug/api/logs` returns the last 100 log events as parsed JSON objects
- [ ] `GET /debug/api/ocr_distribution` returns confidence bucket data
- [ ] Dashboard auto-refreshes every 10 seconds without full page reload
- [ ] Status pills are color-coded (green/yellow/red/gray)
- [ ] OCR bar chart renders purely in CSS (no canvas, no chart.js)
- [ ] Log viewer highlights error/warning lines in color
- [ ] Health check logic is not duplicated between startup and debug endpoint

---

## 4. Final Integration Checks

After all three tracks are complete:

- [ ] `docker-compose build && docker-compose up -d` succeeds cleanly
- [ ] `curl localhost:8000/api/health` → 200
- [ ] `curl localhost:8000/debug` → 200
- [ ] Upload a DOCX, PDF, PPTX, XLSX, and CSV through the UI — all convert successfully
- [ ] Check `docker-compose logs -f` — all events are structured JSON with `request_id` and
  `batch_id` where expected
- [ ] `pytest` → 350+ tests, all passing
- [ ] `pytest -m "not slow and not ocr"` → completes in under 60 seconds
- [ ] No Python warnings in test output (fix DeprecationWarnings if present)

---

## 5. CLAUDE.md Update

After all done criteria pass, update `CLAUDE.md`:

```markdown
**Phase 5 complete** — Full test suite (350+ tests), structured JSON logging throughout all
  pipeline stages, debug dashboard at /debug. Tagged v0.5.0.
**Next: Phase 6** — Full UI, batch progress, history page, settings, polish.
```

Update the phase checklist table:
```
| 5 | Testing & debug infrastructure (full test suite, structlog, debug dashboard) | ✅ Done |
```

Add any new gotchas discovered during Phase 5 to the **Gotchas & Fixes Found** section.

Then tag: `git tag v0.5.0 && git push origin v0.5.0`

---

## 6. Output Cap Warning

Phase 5 spans three tracks across many files. Claude Code will likely need multiple turns to
complete it. Suggested turn boundaries:

1. **Turn 1**: Track A — all logging changes (`logging_config.py`, middleware, converter, handlers)
2. **Turn 2**: Track B part 1 — `conftest.py` extensions, `test_pdf_handler.py`, `test_pptx_handler.py`
3. **Turn 3**: Track B part 2 — `test_xlsx_handler.py`, `test_csv_handler.py`, `test_round_trip.py`,
   `test_logging.py`, `test_api_integration.py`, `pytest.ini` markers
4. **Turn 4**: Track C — `api/routes/debug.py`, `core/health.py` refactor, `static/debug.html`
5. **Turn 5**: Final integration — run tests, fix failures, update CLAUDE.md, tag

If approaching context limits mid-turn, complete the current file, commit, and continue in a
fresh session. CLAUDE.md is the handoff — update it before ending any session.
