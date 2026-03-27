# MarkFlow — Bidirectional Markdown Converter

## Project Summary

Build **MarkFlow**, a lightweight Python web application that converts documents bidirectionally between their original format and Markdown (`.md`). It runs OCR automatically on image-based content, surfaces OCR uncertainties interactively, and supports batch processing.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | **FastAPI** (async, auto-generated OpenAPI docs) |
| Frontend | Simple browser UI — vanilla HTML/CSS/JS or minimal framework (Alpine.js, htmx, or plain fetch). No React/Vue/heavy SPA. |
| OCR | **Tesseract** via `pytesseract`. Install Tesseract system dependency. |
| Task queue | For batch jobs, use **background tasks** (FastAPI `BackgroundTasks` or `asyncio`). No Celery unless batch sizes exceed ~50 files. |
| Storage | Local filesystem. Converted files go into an `output/` directory mirroring input structure. |

---

## Supported Formats

### Ingest (→ Markdown)

| Format | Primary Library | Notes |
|---|---|---|
| `.docx` / `.doc` | `python-docx`, `mammoth` | Extract headings, tables, lists, images, footnotes. Use `mammoth` for HTML intermediate → MD. For `.doc` (legacy), convert to `.docx` first via `libreoffice --headless --convert-to docx`. |
| `.pdf` | `pdfplumber` (text), `pdf2image` + `pytesseract` (scanned) | Detect if page is text-based or image-based. Text pages: extract directly. Image pages: OCR. Mixed documents: handle page-by-page. |
| `.pptx` | `python-pptx` | Extract slide titles, body text, speaker notes, tables, and images. Each slide → H2 section in markdown. Preserve slide order. |
| `.xlsx` / `.csv` | `openpyxl`, `pandas` | Each sheet → separate markdown table (or H2-delimited section). CSV is a direct parse. Preserve formulas as text annotation where possible. |

### Export (Markdown →)

| Target | Library | Fidelity Goal |
|---|---|---|
| `.docx` | `python-docx` | **Best-effort pixel-perfect.** Restore headings, tables, lists, images, fonts, and spacing from stored metadata. Apply original styles where metadata exists; fall back to clean defaults. |
| `.pdf` | `weasyprint` or `fpdf2` | Render markdown → styled HTML → PDF. Use stored metadata for page size, margins, fonts. |
| `.pptx` | `python-pptx` | Rebuild slides from H2-delimited sections. Restore layouts, images, speaker notes from metadata. |
| `.xlsx` | `openpyxl` | Rebuild sheets from markdown tables. Restore column widths, number formats, formulas from metadata. |

---

## Metadata System (Critical for Round-Trip Fidelity)

Every conversion stores metadata in **two places**:

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

`output/<batch_id>/<filename>.styles.json` — stores format-specific styling info:

- **docx**: Font families, sizes, paragraph spacing, table column widths, page margins, header/footer content, image positions/dimensions
- **pdf**: Page size, margins, font info, layout zones
- **pptx**: Slide dimensions, layout names, placeholder positions, theme colors, font schemes
- **xlsx**: Column widths, row heights, number formats, cell styles, merged cells, formula text, sheet names

This is the key to pixel-perfect round-trip. **Extract as much style metadata as possible during ingest.** During export, apply it back.

---

## OCR Pipeline

### Detection

- For PDFs: Check each page for extractable text. If text layer is empty/minimal, treat as image-based → OCR.
- For images embedded in `.docx` / `.pptx`: OCR any image that appears to contain text (heuristic: image is large, positioned inline, or has alt text suggesting content).

### Processing

1. Extract image (full page for PDF, embedded image for docx/pptx)
2. Pre-process: deskew, threshold, denoise (use `Pillow` for basic preprocessing)
3. Run Tesseract with `--oem 3 --psm 6` (or appropriate PSM per context)
4. Capture confidence scores per word/line from Tesseract's `Output.DICT` or HOCR output

### Error Handling & Interactive Review

**Confidence threshold**: Flag any word/line with confidence < 80%.

**Review UI** (in browser):

- Show flagged items one at a time
- **Left panel**: Original image crop of the flagged region (highlight the uncertain area)
- **Right panel**: OCR's best guess text, editable by the user
- **Below**: Confidence score, position in document, suggested corrections if available
- **Action buttons**:
  - `Accept` — keep OCR output as-is
  - `Edit & Accept` — user corrects the text, then accepts
  - `Accept All Remaining` — apply OCR output for all remaining flags without review (the "apply to all" escape hatch)
  - `Skip` — leave placeholder marker in the markdown (`<!-- OCR_UNRESOLVED: page X, region Y -->`)
- **Progress indicator**: "Reviewing 3 of 17 flagged items"

If no items are flagged (all confidence ≥ 80%), skip review entirely and notify the user.

---

## Web UI

### Pages / Views

1. **Home / Upload**
   - Drag-and-drop zone for files (single or batch)
   - Or: specify a folder path on the local filesystem
   - Direction toggle: `Original → Markdown` or `Markdown → Original`
   - "Convert" button

2. **Batch Progress**
   - Show list of files being processed
   - Per-file status: queued → processing → OCR review needed → complete / error
   - Overall progress bar

3. **OCR Review** (described above)
   - Only appears if OCR flagged items exist
   - After review, conversion completes automatically

4. **Results / Download**
   - List of converted files with download links (individual or zip-all)
   - Link to batch manifest
   - Summary: X files converted, Y OCR flags resolved, Z errors

5. **History** (optional/stretch goal)
   - List of past batches
   - Re-download or re-run conversions

### UI Principles

- Clean, minimal, functional. Not a design showcase.
- Mobile-responsive is nice but not required — this is a desktop tool.
- Use a simple CSS framework (Pico CSS, Simple.css, or classless) to avoid writing custom styles.

---

## Project Structure

```
markflow/
├── main.py                    # FastAPI app entry point
├── requirements.txt
├── README.md
│
├── api/
│   ├── routes/
│   │   ├── convert.py         # Upload & conversion endpoints
│   │   ├── review.py          # OCR review endpoints
│   │   └── batch.py           # Batch status & download endpoints
│   └── models.py              # Pydantic request/response models
│
├── core/
│   ├── converter.py           # Conversion orchestration
│   ├── ocr.py                 # OCR pipeline (detection, processing, flagging)
│   ├── metadata.py            # Frontmatter & manifest generation/parsing
│   └── style_extractor.py     # Format-specific style metadata extraction
│
├── formats/
│   ├── docx_handler.py        # .docx/.doc ↔ .md
│   ├── pdf_handler.py         # .pdf ↔ .md
│   ├── pptx_handler.py        # .pptx ↔ .md
│   └── xlsx_handler.py        # .xlsx/.csv ↔ .md
│
├── static/
│   ├── index.html             # Upload UI
│   ├── review.html            # OCR review UI
│   ├── results.html           # Results/download UI
│   └── style.css              # Minimal styling
│
├── output/                    # Converted files land here (gitignored)
└── tests/
    ├── test_docx.py
    ├── test_pdf.py
    ├── test_pptx.py
    ├── test_xlsx.py
    └── fixtures/              # Sample test files for each format
```

---

## Build Order (Suggested)

Build incrementally. Get one format working end-to-end before adding the next. Each phase includes its corresponding tests.

### Phase 1 — Foundation
1. FastAPI skeleton + static file serving
2. Upload endpoint (accept files, store to temp dir)
3. Basic conversion: `.docx` → `.md` (text + headings + tables only)
4. Metadata: YAML frontmatter + manifest generation
5. Download endpoint

### Phase 2 — Round-Trip
6. `.md` → `.docx` export with style metadata restoration
7. Style extractor for `.docx` (fonts, spacing, table widths)
8. Verify round-trip: docx → md → docx produces structurally faithful output

### Phase 3 — OCR
9. PDF text extraction (text-layer PDFs)
10. PDF OCR pipeline (image-based pages)
11. OCR confidence scoring + flagging
12. Interactive review UI in browser

### Phase 4 — Remaining Formats
13. `.pdf` ↔ `.md` (both directions)
14. `.pptx` ↔ `.md`
15. `.xlsx` / `.csv` ↔ `.md`

### Phase 5 — Testing & Debug Infrastructure
16. `generate_fixtures.py` — auto-generate all test fixture files
17. Structured logging with `structlog` + request ID middleware
18. Debug mode flag + intermediate file preservation
19. Debug dashboard UI at `/debug`
20. `pytest` suite — all tests for Phases 1-4

### Phase 6 — Batch & Polish
21. Batch upload + progress tracking
22. Zip download for batch results
23. Error handling hardening (corrupted files, unsupported encodings, Tesseract failures)
24. Pipeline inspector on debug dashboard
25. Final pass: run all tests, fix failures, verify debug output is useful

---

## Testing & Debug Infrastructure

Build testing and debug tooling **alongside the app, not after it.** Each phase should include its corresponding tests and debug capabilities.

### Test Fixtures (Build in Phase 1)

Auto-generate a `tests/fixtures/` folder containing:

| File | Purpose |
|---|---|
| `simple.docx` | 3 headings, 2 paragraphs, 1 table (3×3), 1 inline image |
| `complex.docx` | Nested tables, footnotes, headers/footers, multiple fonts, TOC, embedded images |
| `text_layer.pdf` | Clean text-based PDF, 3 pages |
| `scanned.pdf` | Image-based PDF (render text to image, save as PDF — simulates a scan) |
| `bad_scan.pdf` | Skewed, low-res image PDF to stress OCR |
| `simple.pptx` | 5 slides with titles, body text, speaker notes |
| `complex.pptx` | Slides with tables, images, charts, multiple layouts |
| `simple.xlsx` | 2 sheets, basic data, headers, number formatting |
| `complex.xlsx` | Merged cells, formulas, conditional formatting, multiple sheets |
| `simple.csv` | Clean CSV with headers |

Use `python-docx`, `fpdf2`, `python-pptx`, `openpyxl` to generate these programmatically in a `tests/generate_fixtures.py` script — don't rely on manually created files.

### Automated Tests (pytest — build per phase)

**Phase 1 tests:**
- Upload endpoint accepts valid files, rejects invalid types
- `.docx` → `.md` produces valid markdown with correct heading count, table count, image references
- YAML frontmatter contains all required fields
- Manifest JSON is valid and lists correct files/statuses
- Download endpoint returns the file

**Phase 2 tests:**
- Round-trip: `.docx` → `.md` → `.docx` structural comparison (heading count, table dimensions, image count, paragraph count)
- Style sidecar JSON is generated and contains expected keys
- Round-trip with style metadata produces closer fidelity than without

**Phase 3 tests:**
- Text-layer PDF extracts text without triggering OCR
- Scanned PDF triggers OCR pipeline
- OCR confidence scoring flags words below 80% threshold
- Bad scan produces flags (not crashes)
- Review endpoints accept/edit/skip/accept-all work correctly

**Phase 4 tests:**
- Per-format round-trip structural comparisons (same pattern as Phase 2)
- CSV → `.md` → CSV preserves row/column counts and header names

**Phase 5 tests:**
- Batch upload of mixed formats processes all files
- One corrupt file in a batch doesn't crash the rest
- Manifest accurately reflects partial batch failures

### Debug Tooling (Built into the app)

#### 1. Structured Logging

Use Python's `logging` module with `structlog` for JSON-formatted logs. Every log entry must include:

- `request_id` — unique per API request, propagated through all conversion steps
- `batch_id` — for batch operations
- `file_name` — which file is being processed
- `stage` — which step in the pipeline (`upload`, `detect_format`, `extract_text`, `extract_styles`, `ocr_preprocess`, `ocr_extract`, `ocr_score`, `generate_markdown`, `export`, `round_trip_verify`)
- `duration_ms` — how long the step took
- `status` — `success`, `warning`, `error`

Log levels:
- `INFO` — normal operation (file converted, batch started/completed)
- `WARNING` — non-fatal issues (OCR low confidence, missing style metadata, fallback used)
- `ERROR` — failures (file couldn't be converted, Tesseract crash, corrupt input)
- `DEBUG` — verbose pipeline internals (only when debug mode is on)

Logs write to `logs/markflow.log` (rotating, 10MB max, 5 backups) AND stdout for development.

#### 2. Debug Mode

Add a `--debug` flag to the uvicorn startup command (or `DEBUG=true` env var) that enables:

- `DEBUG`-level logging
- **Intermediate file preservation** — save every stage's output to `output/<batch_id>/_debug/`:
  - `<filename>.raw_extract.txt` — raw text before markdown conversion
  - `<filename>.styles.debug.json` — full style dump (verbose version of the sidecar)
  - `<filename>.ocr_preprocess.png` — the image after deskew/threshold/denoise (per page for PDFs)
  - `<filename>.ocr_raw.txt` — raw Tesseract output before confidence filtering
  - `<filename>.ocr_confidence.json` — per-word confidence scores
  - `<filename>.round_trip_diff.txt` — structural comparison between original and round-tripped file
- **Slower but more informative OCR** — run Tesseract in HOCR mode to get bounding boxes alongside text, save as `<filename>.ocr_hocr.html`

#### 3. Debug Dashboard (UI page — `/debug`)

A simple page in the browser UI (only visible when debug mode is on) that shows:

- **Recent conversions**: table of last 20 conversions with file name, format, direction, status, duration, OCR flag count, link to debug files
- **Log viewer**: tail the last 100 log lines, filterable by level (INFO/WARNING/ERROR) and by batch_id
- **Pipeline inspector**: for a specific file, show each pipeline stage as a step-through — click a stage to see its input, output, duration, and any warnings. This is the single most useful debug tool for conversion failures.
- **OCR debug view**: for a specific file, show original image side-by-side with OCR overlay (bounding boxes + text + confidence color-coding: green ≥ 90%, yellow 80-89%, red < 80%)
- **System health**: Tesseract version/status, LibreOffice available (y/n), disk space in output directory, active batch jobs

#### 4. API Debug Headers

When debug mode is on, every API response includes extra headers:

- `X-MarkFlow-Request-Id` — the request ID for log correlation
- `X-MarkFlow-Duration-Ms` — total request processing time
- `X-MarkFlow-Pipeline-Stages` — comma-separated list of stages executed
- `X-MarkFlow-Warnings` — count of warnings generated during processing

#### 5. FastAPI Swagger UI

FastAPI auto-generates interactive API docs at `/docs`. This is the primary tool for testing API endpoints independently of the browser UI. No extra build work needed — just make sure every endpoint has clear docstrings and example request/response bodies in the Pydantic models.

### Updated Project Structure (with testing/debug additions)

Add these to the project tree:

```
markflow/
├── ...existing structure...
│
├── core/
│   ├── ...existing...
│   ├── logging.py             # Structured logging setup, request_id middleware
│   └── debug.py               # Debug mode helpers, intermediate file writer
│
├── api/
│   ├── routes/
│   │   ├── ...existing...
│   │   └── debug.py           # Debug dashboard endpoints (conditionally loaded)
│   └── middleware.py           # Request ID injection, timing, debug headers
│
├── static/
│   ├── ...existing...
│   └── debug.html             # Debug dashboard UI
│
├── logs/                      # Log files (gitignored)
│
├── tests/
│   ├── generate_fixtures.py   # Programmatic test file generator
│   ├── conftest.py            # Shared pytest fixtures, test client setup
│   ├── test_docx.py
│   ├── test_pdf.py
│   ├── test_pptx.py
│   ├── test_xlsx.py
│   ├── test_api.py            # Endpoint tests (status codes, responses)
│   ├── test_ocr.py            # OCR pipeline tests
│   ├── test_roundtrip.py      # Round-trip structural comparison tests
│   └── fixtures/              # Auto-generated by generate_fixtures.py
```

### Updated Build Order (with testing integrated)

Revise Phase 5 and add Phase 6:

**Phase 5 — Testing & Debug Infrastructure**
16. `generate_fixtures.py` — auto-generate all test fixture files
17. Structured logging with `structlog` + request ID middleware
18. Debug mode flag + intermediate file preservation
19. Debug dashboard UI at `/debug`
20. `pytest` suite — all tests for Phases 1-4

**Phase 6 — Batch & Polish**
21. Batch upload + progress tracking
22. Zip download for batch results
23. Error handling hardening (corrupted files, unsupported encodings, Tesseract failures)
24. Pipeline inspector on debug dashboard
25. Final pass: run all tests, fix failures, verify debug output is useful

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
structlog
pytest
pytest-asyncio
httpx
```

System dependencies (must be installed separately):
- `tesseract-ocr`
- `poppler-utils` (for `pdf2image`)
- `libreoffice` (for legacy `.doc` conversion)

---

## Constraints & Guardrails

- **Do not use Pandoc** as the conversion engine. We want fine-grained control over metadata extraction and round-trip fidelity. Library-level access is required.
- **Do not build a SPA.** Keep the frontend simple — server-rendered HTML or minimal JS with fetch calls.
- **Fail gracefully.** If a file can't be converted, log the error, mark it in the manifest, and continue the batch. Never crash the whole batch for one bad file.
- **Image handling**: During docx/pptx → md, extract images to an `assets/` subfolder and reference them with relative markdown image links. During md → docx/pptx, re-embed them.
- **Large files**: For PDFs over 50 pages, process page-by-page with progress updates. Don't load the entire document into memory at once.
- **Security**: Validate uploaded file types. Don't execute anything from uploaded content. Sanitize filenames.
