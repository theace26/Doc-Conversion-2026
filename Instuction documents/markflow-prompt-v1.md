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

Build incrementally. Get one format working end-to-end before adding the next.

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

### Phase 5 — Batch & Polish
16. Batch upload + progress tracking
17. Zip download for batch results
18. Error handling hardening (corrupted files, unsupported encodings, Tesseract failures)
19. Tests for each format handler

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
