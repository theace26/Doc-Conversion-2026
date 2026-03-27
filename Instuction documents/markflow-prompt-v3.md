# MarkFlow — Bidirectional Markdown Converter

## Project Summary

Build **MarkFlow**, a lightweight Python web application that converts documents bidirectionally between their original format and Markdown (`.md`). It runs OCR automatically on image-based content, surfaces OCR uncertainties interactively, and supports batch processing. All conversion history and user preferences persist across restarts via SQLite.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | **FastAPI** (async, auto-generated OpenAPI docs) |
| Frontend | Simple browser UI — vanilla HTML/CSS/JS or minimal framework (Alpine.js, htmx, or plain fetch). No React/Vue/heavy SPA. |
| OCR | **Tesseract** via `pytesseract` |
| Task queue | **FastAPI `BackgroundTasks`** or `asyncio`. No Celery unless batch sizes exceed ~50 files. |
| File storage | Local filesystem. Converted files go into an `output/` directory organized by batch. |
| Persistence | **SQLite** via `aiosqlite` — conversion history, user preferences. Zero config, file-based. DB file: `markflow.db` in project root. |
| Logging | **`structlog`** — JSON-formatted structured logs with request ID propagation. |
| Testing | **`pytest`** + `pytest-asyncio` + `httpx` (async test client for FastAPI) |

---

## Supported Formats

### Ingest (→ Markdown)

| Format | Primary Library | Notes |
|---|---|---|
| `.docx` / `.doc` | `python-docx`, `mammoth` | Extract headings, tables, lists, images, footnotes. Use `mammoth` for HTML intermediate → MD. For `.doc` (legacy), convert to `.docx` first via `libreoffice --headless --convert-to docx`. |
| `.pdf` | `pdfplumber` (text), `pdf2image` + `pytesseract` (scanned) | Detect if page is text-based or image-based per page. Text pages: extract directly. Image pages: OCR. |
| `.pptx` | `python-pptx` | Extract slide titles, body text, speaker notes, tables, images. Each slide → H2 section in markdown. |
| `.xlsx` / `.csv` | `openpyxl`, `pandas` | Each sheet → markdown table (H2-delimited). CSV is direct parse. Preserve formulas as text annotations. |

### Export (Markdown →)

| Target | Library | Fidelity Goal |
|---|---|---|
| `.docx` | `python-docx` | **Best-effort pixel-perfect.** Restore headings, tables, lists, images, fonts, spacing from stored metadata. Fall back to clean defaults where metadata is missing. |
| `.pdf` | `weasyprint` or `fpdf2` | Markdown → styled HTML → PDF. Use stored metadata for page size, margins, fonts. |
| `.pptx` | `python-pptx` | Rebuild slides from H2-delimited sections. Restore layouts, images, speaker notes from metadata. |
| `.xlsx` | `openpyxl` | Rebuild sheets from markdown tables. Restore column widths, number formats, formulas from metadata. |

---

## Metadata System (Critical for Round-Trip Fidelity)

Every conversion stores metadata in **three places**:

### 1. YAML Frontmatter (per `.md` file)

```yaml
---
markflow:
  source_file: "quarterly_report.docx"
  source_format: "docx"
  converted_at: "2026-03-07T14:30:00Z"
  markflow_version: "0.1.0"
  ocr_applied: false
  style_ref: "quarterly_report.styles.json"
---
```

### 2. Batch Manifest (per conversion batch)

`output/<batch_id>/manifest.json`:

```json
{
  "batch_id": "20260307_143000",
  "created_at": "2026-03-07T14:30:00Z",
  "source_directory": "/path/to/input",
  "files": [
    {
      "source": "quarterly_report.docx",
      "output": "quarterly_report.md",
      "format": "docx",
      "ocr_applied": false,
      "ocr_flags": 0,
      "style_ref": "quarterly_report.styles.json",
      "status": "success"
    }
  ]
}
```

### 3. Style Metadata (per file, sidecar)

`output/<batch_id>/<filename>.styles.json` — format-specific styling info:

- **docx**: Font families, sizes, paragraph spacing, table column widths, page margins, header/footer content, image positions/dimensions
- **pdf**: Page size, margins, font info, layout zones
- **pptx**: Slide dimensions, layout names, placeholder positions, theme colors, font schemes
- **xlsx**: Column widths, row heights, number formats, cell styles, merged cells, formula text, sheet names

**Extract as much style metadata as possible during ingest. During export, apply it back.** This is the key to round-trip fidelity.

---

## Persistence Layer (SQLite)

MarkFlow uses `markflow.db` to store conversion history and user preferences. Data persists across restarts indefinitely.

### Schema

#### `conversion_history`

```sql
CREATE TABLE conversion_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_format TEXT NOT NULL,
    output_filename TEXT NOT NULL,
    output_format TEXT NOT NULL,
    direction TEXT NOT NULL,                -- 'to_md' or 'from_md'
    source_path TEXT,
    output_path TEXT,
    file_size_bytes INTEGER,
    ocr_applied BOOLEAN DEFAULT FALSE,
    ocr_flags_total INTEGER DEFAULT 0,
    ocr_flags_resolved INTEGER DEFAULT 0,
    status TEXT NOT NULL,                    -- 'success', 'error', 'partial'
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_history_created ON conversion_history(created_at DESC);
CREATE INDEX idx_history_batch ON conversion_history(batch_id);
CREATE INDEX idx_history_format ON conversion_history(source_format);
CREATE INDEX idx_history_status ON conversion_history(status);
```

#### `user_preferences`

```sql
CREATE TABLE user_preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Default keys (initialize on first run):**

| Key | Default | Purpose |
|---|---|---|
| `last_save_directory` | `""` | Pre-fills save location on next conversion |
| `last_source_directory` | `""` | Pre-fills source folder on upload page |
| `ocr_confidence_threshold` | `80` | Default OCR confidence threshold |
| `default_direction` | `to_md` | Default direction toggle on upload page |

### Behavior

- Write a row to `conversion_history` on every file conversion (success or failure), at the per-file level — partial batch failures still get recorded.
- When user specifies an output folder or source folder in the UI, update the corresponding preference immediately (write-through).
- On startup, read all preferences into memory. If a key doesn't exist, insert it with the default.

---

## OCR Pipeline

### Detection

- PDFs: Check each page for extractable text. Empty/minimal text layer → OCR.
- Images in `.docx` / `.pptx`: OCR any image that appears to contain text (heuristic: large, inline, or has alt text suggesting content).

### Processing

1. Extract image (full page for PDF, embedded image for docx/pptx)
2. Pre-process: deskew, threshold, denoise (`Pillow`)
3. Run Tesseract (`--oem 3 --psm 6`, or appropriate PSM per context)
4. Capture per-word/line confidence scores from Tesseract `Output.DICT` or HOCR

### Interactive Review

**Confidence threshold**: Flag any word/line below the threshold (default 80%, configurable via preferences).

**Review UI** (browser page):

- Show flagged items one at a time
- **Left panel**: Original image crop of the flagged region
- **Right panel**: OCR best guess text, editable
- **Below**: Confidence score, position in document
- **Action buttons**:
  - `Accept` — keep as-is
  - `Edit & Accept` — user corrects, then accepts
  - `Accept All Remaining` — batch-accept all remaining flags
  - `Skip` — leave `<!-- OCR_UNRESOLVED: page X, region Y -->` placeholder in markdown
- **Progress**: "Reviewing 3 of 17 flagged items"

If no items flagged, skip review entirely and notify.

---

## Web UI

### Pages

1. **Home / Upload**
   - Drag-and-drop zone (single or batch)
   - Or: folder path input — **pre-filled from `last_source_directory`**
   - Direction toggle — **defaults to `default_direction`**
   - Output location field — **pre-filled from `last_save_directory`**. Updating this writes to preferences immediately.
   - "Convert" button

2. **Batch Progress**
   - File list with per-file status: queued → processing → OCR review needed → complete / error
   - Overall progress bar

3. **OCR Review** (described above)

4. **Results / Download**
   - Converted files with download links (individual + zip-all)
   - Batch manifest link
   - Summary: X converted, Y OCR flags resolved, Z errors

5. **History**
   - Sortable/filterable table from `conversion_history`
   - Columns: Date, Source File, Source Format, Output Format, Direction, Status, Duration, OCR Flags
   - Filters: format, direction, status, date range, filename search
   - Per-row actions: Download (if file exists on disk), Re-convert (if source exists), View manifest
   - Stats bar: total conversions, success rate, most-used format, total OCR flags resolved
   - Pagination: 50 per page
   - Missing files show dimmed row — "File unavailable" — record preserved

6. **Settings**
   - Default save/source locations (editable)
   - Default conversion direction
   - OCR confidence threshold slider (50–99)
   - All changes save immediately (write-through to SQLite)

### UI Principles

- Clean, minimal, functional. Not a design showcase.
- Desktop-first. Mobile-responsive is optional.
- Use a simple CSS framework (Pico CSS, Simple.css, or classless).

---

## API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/convert` | POST | Upload file(s), specify direction + output location. Returns job/batch ID |
| `/api/batch/{batch_id}/status` | GET | Batch progress (per-file status, OCR flags pending) |
| `/api/batch/{batch_id}/review` | GET | Retrieve OCR-flagged items |
| `/api/batch/{batch_id}/review/{flag_id}` | POST | Resolve an OCR flag (accept, edit, skip) |
| `/api/batch/{batch_id}/review/accept-all` | POST | Accept all remaining OCR flags |
| `/api/batch/{batch_id}/download` | GET | Download converted files (individual or zip) |
| `/api/batch/{batch_id}/manifest` | GET | Retrieve batch manifest JSON |
| `/api/history` | GET | Conversion history. Params: `limit`, `offset`, `format`, `status`, `direction`, `search` |
| `/api/history/{id}` | GET | Single conversion record |
| `/api/history/stats` | GET | Aggregate stats |
| `/api/preferences` | GET | All user preferences |
| `/api/preferences/{key}` | PUT | Update a preference |

---

## Testing

### Test Fixtures

Auto-generate `tests/fixtures/` via `tests/generate_fixtures.py`:

| File | Purpose |
|---|---|
| `simple.docx` | 3 headings, 2 paragraphs, 1 table (3×3), 1 inline image |
| `complex.docx` | Nested tables, footnotes, headers/footers, multiple fonts, TOC, embedded images |
| `text_layer.pdf` | Clean text-based PDF, 3 pages |
| `scanned.pdf` | Image-based PDF (render text to image, save as PDF) |
| `bad_scan.pdf` | Skewed, low-res image PDF to stress OCR |
| `simple.pptx` | 5 slides with titles, body text, speaker notes |
| `complex.pptx` | Slides with tables, images, charts, multiple layouts |
| `simple.xlsx` | 2 sheets, basic data, headers, number formatting |
| `complex.xlsx` | Merged cells, formulas, conditional formatting, multiple sheets |
| `simple.csv` | Clean CSV with headers |

Generate programmatically using `python-docx`, `fpdf2`, `python-pptx`, `openpyxl` — no manually created files.

### Automated Tests (pytest)

**Conversion tests** (per format):
- Produces valid markdown with correct heading/table/image counts
- YAML frontmatter contains required fields
- Manifest JSON is valid

**Round-trip tests**:
- `.docx` → `.md` → `.docx` structural comparison (headings, tables, images, paragraphs)
- Style sidecar JSON generated with expected keys
- Round-trip with metadata produces better fidelity than without

**OCR tests**:
- Text-layer PDF extracts without triggering OCR
- Scanned PDF triggers OCR
- Confidence scoring flags words below threshold
- Bad scan produces flags, not crashes
- Review endpoints (accept/edit/skip/accept-all) work correctly

**API tests**:
- Upload accepts valid files, rejects invalid
- Download returns files
- Batch status updates correctly
- History endpoint returns records, supports filtering
- Preferences read/write correctly, persist across test client restarts

**Batch tests**:
- Mixed formats process all files
- One corrupt file doesn't crash the batch
- Manifest reflects partial failures

---

## Debug Infrastructure

### Structured Logging

`structlog` with JSON format. Every log entry includes:

- `request_id` — unique per API request, propagated through pipeline
- `batch_id`, `file_name`, `stage` (`upload`, `detect_format`, `extract_text`, `extract_styles`, `ocr_preprocess`, `ocr_extract`, `ocr_score`, `generate_markdown`, `export`, `round_trip_verify`)
- `duration_ms`, `status` (`success`, `warning`, `error`)

Levels: `INFO` (normal), `WARNING` (non-fatal), `ERROR` (failures), `DEBUG` (verbose, only in debug mode).

Logs write to `logs/markflow.log` (rotating, 10MB, 5 backups) AND stdout.

### Debug Mode

Enable with `DEBUG=true` env var or `--debug` flag:

- `DEBUG`-level logging
- **Intermediate file preservation** in `output/<batch_id>/_debug/`:
  - `<file>.raw_extract.txt` — raw text before markdown conversion
  - `<file>.styles.debug.json` — verbose style dump
  - `<file>.ocr_preprocess.png` — image after deskew/threshold/denoise
  - `<file>.ocr_raw.txt` — raw Tesseract output pre-filtering
  - `<file>.ocr_confidence.json` — per-word confidence scores
  - `<file>.round_trip_diff.txt` — structural diff original vs. round-tripped
  - `<file>.ocr_hocr.html` — HOCR with bounding boxes
- **API debug headers**: `X-MarkFlow-Request-Id`, `X-MarkFlow-Duration-Ms`, `X-MarkFlow-Pipeline-Stages`, `X-MarkFlow-Warnings`

### Debug Dashboard (`/debug` — only visible in debug mode)

- **Recent conversions**: last 20, with links to debug files
- **Log viewer**: tail last 100 lines, filterable by level and batch_id
- **Pipeline inspector**: step-through view per file — click a stage to see input, output, duration, warnings
- **OCR debug view**: original image + OCR overlay with bounding boxes + confidence color-coding (green ≥90%, yellow 80-89%, red <80%)
- **System health**: Tesseract version, LibreOffice status, disk space, active batch jobs, SQLite DB size

### Swagger UI

FastAPI auto-generates at `/docs`. Ensure every endpoint has docstrings and example request/response bodies in Pydantic models.

---

## Project Structure

```
markflow/
├── main.py                    # FastAPI app entry point, lifespan (DB init)
├── requirements.txt
├── README.md
├── markflow.db                # SQLite (auto-created on first run, gitignored)
│
├── api/
│   ├── routes/
│   │   ├── convert.py         # Upload & conversion endpoints
│   │   ├── review.py          # OCR review endpoints
│   │   ├── batch.py           # Batch status & download endpoints
│   │   ├── history.py         # Conversion history endpoints
│   │   ├── preferences.py     # User preferences endpoints
│   │   └── debug.py           # Debug dashboard endpoints (conditional)
│   ├── models.py              # Pydantic request/response models
│   └── middleware.py          # Request ID injection, timing, debug headers
│
├── core/
│   ├── converter.py           # Conversion orchestration
│   ├── ocr.py                 # OCR pipeline
│   ├── metadata.py            # Frontmatter & manifest generation/parsing
│   ├── style_extractor.py     # Format-specific style metadata extraction
│   ├── database.py            # SQLite connection, schema init, query helpers
│   ├── logging.py             # structlog setup, request_id middleware
│   └── debug.py               # Debug mode helpers, intermediate file writer
│
├── formats/
│   ├── docx_handler.py        # .docx/.doc ↔ .md
│   ├── pdf_handler.py         # .pdf ↔ .md
│   ├── pptx_handler.py        # .pptx ↔ .md
│   └── xlsx_handler.py        # .xlsx/.csv ↔ .md
│
├── static/
│   ├── index.html             # Upload (pre-filled paths from preferences)
│   ├── review.html            # OCR review
│   ├── results.html           # Results/download
│   ├── history.html           # Conversion history
│   ├── settings.html          # Preferences
│   ├── debug.html             # Debug dashboard
│   └── style.css              # Minimal styling
│
├── logs/                      # Log files (gitignored)
├── output/                    # Converted files (gitignored)
│
└── tests/
    ├── generate_fixtures.py   # Programmatic test file generator
    ├── conftest.py            # Shared fixtures, test client setup
    ├── test_docx.py
    ├── test_pdf.py
    ├── test_pptx.py
    ├── test_xlsx.py
    ├── test_api.py            # Endpoint tests
    ├── test_ocr.py            # OCR pipeline tests
    ├── test_roundtrip.py      # Round-trip structural comparisons
    ├── test_history.py        # History + preferences persistence
    └── fixtures/              # Auto-generated by generate_fixtures.py
```

---

## Build Order

Build incrementally. One format end-to-end before adding the next.

### Phase 1 — Foundation
1. FastAPI skeleton + static file serving
2. SQLite setup — `core/database.py`, schema init, auto-create DB + tables on first run
3. User preferences — read/write, initialize defaults, API endpoints
4. Upload endpoint — pre-fill source path from `last_source_directory` preference
5. Basic conversion: `.docx` → `.md` (text + headings + tables)
6. Metadata: YAML frontmatter + manifest generation
7. Write conversion record to `conversion_history` on completion
8. Download endpoint — update `last_save_directory` on output location change

### Phase 2 — Round-Trip
9. `.md` → `.docx` export with style metadata restoration
10. Style extractor for `.docx` (fonts, spacing, table widths)
11. Verify round-trip: docx → md → docx structural fidelity

### Phase 3 — OCR
12. PDF text extraction (text-layer)
13. PDF OCR pipeline (image-based pages)
14. OCR confidence scoring + flagging (threshold from preferences)
15. Interactive review UI

### Phase 4 — Remaining Formats
16. `.pdf` ↔ `.md` (both directions)
17. `.pptx` ↔ `.md`
18. `.xlsx` / `.csv` ↔ `.md`

### Phase 5 — Testing & Debug
19. `generate_fixtures.py` — auto-generate all test fixtures
20. Structured logging with `structlog` + request ID middleware
21. Debug mode flag + intermediate file preservation
22. Debug dashboard at `/debug`
23. Full `pytest` suite — all phases including history/preferences

### Phase 6 — History, Batch & Polish
24. History page UI — sortable, filterable, paginated, re-download/re-convert
25. Settings page UI — preference editor with live save
26. Batch upload + progress tracking
27. Zip download for batch results
28. Error handling hardening (corrupt files, bad encodings, Tesseract failures)
29. Pipeline inspector on debug dashboard
30. Final pass: run all tests, fix failures, verify debug output

---

## Key Dependencies

```
fastapi
uvicorn[standard]
python-multipart
python-docx
mammoth
pdfplumber
pdf2image
pytesseract
Pillow
python-pptx
openpyxl
pandas
weasyprint
pyyaml
aiofiles
aiosqlite
structlog
pytest
pytest-asyncio
httpx
```

System dependencies (install separately):
- `tesseract-ocr`
- `poppler-utils` (for `pdf2image`)
- `libreoffice` (for legacy `.doc` conversion)

---

## Constraints & Guardrails

- **No Pandoc.** Library-level access required for metadata extraction and round-trip fidelity.
- **No SPA.** Simple server-rendered HTML or minimal JS with fetch calls.
- **Fail gracefully.** One bad file never crashes the batch. Log the error, mark it in the manifest and history, continue.
- **Image handling**: Extract images to `assets/` subfolder with relative markdown links on ingest. Re-embed on export.
- **Large files**: PDFs over 50 pages process page-by-page with progress. Don't load entire document into memory.
- **Security**: Validate file types. Don't execute uploaded content. Sanitize filenames.
- **Persistence**: Never lose history. DB writes happen at per-file granularity, not per-batch — if the app crashes mid-batch, completed files are still recorded.
