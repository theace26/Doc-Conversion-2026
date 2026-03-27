# Phase 4 — Remaining Formats: PDF, PPTX, XLSX/CSV

Read `CLAUDE.md` for project context, architecture, and gotchas before starting.

---

## Objective

Implement four new format handlers, all following the same `FormatHandler` pattern from `formats/base.py`. Each handler supports **ingest** (→ DocumentModel → Markdown) and **export** (Markdown → DocumentModel → original format). The OCR pipeline from Phase 3 is integrated into PDF ingest for scanned pages.

**This is the largest phase.** Build one handler at a time. Get each working end-to-end with tests before starting the next. Suggested order: PDF → PPTX → XLSX → CSV.

---

## Shared Patterns (All Handlers)

Every handler must:

1. **Register in the format registry** via `FormatHandler.register()` or the existing registry pattern in `formats/base.py`
2. **Implement `ingest(file_path) → DocumentModel`** — extract content into the standard element model
3. **Implement `export(model, output_path, sidecar=None, original_path=None) → Path`** — rebuild the file from a DocumentModel. Apply sidecar styles (Tier 2) if available. Accept `original_path` kwarg (Tier 3 where feasible).
4. **Implement `extract_styles(file_path) → dict`** — capture format-specific styling/layout info keyed by content hash
5. **Implement `supports_format(extension) → bool`**
6. **Produce images** in `assets/` via `core/image_handler.py` during ingest
7. **Write tests** in `tests/test_<format>.py` — structural ingest, export, and round-trip

---

## Handler 1: PDF (`formats/pdf_handler.py`)

### Dependencies
- `pdfplumber` — text extraction from text-layer PDFs
- `pdf2image` — convert PDF pages to PIL Images (requires `poppler-utils`)
- `pytesseract` via `core/ocr.py` — OCR for scanned pages
- `weasyprint` — Markdown → HTML → PDF for export

### Extensions
- `.pdf`

### Ingest (`pdf → DocumentModel`)

Process page by page:

1. Open with `pdfplumber`
2. For each page:
   a. **Try text extraction** via `page.extract_text()` and `page.extract_tables()`
   b. **Evaluate text quality**: If extracted text length < 50 chars and page has content (not blank), classify as scanned
   c. **Text pages**: Extract text → paragraphs. Extract tables → table elements. Extract images via `page.images` metadata.
   d. **Scanned pages**: Convert to PIL Image via `pdf2image.convert_from_path(pdf_path, first_page=N, last_page=N, dpi=300)`. Run through `core/ocr.run_ocr()`. OCR result text → paragraph elements. OCR flags persisted per Phase 3.
   e. **Mixed documents**: Handle page-by-page — some pages text, some scanned. This is common in real-world PDFs.
3. Add a `PAGE_BREAK` element (or `HORIZONTAL_RULE`) between pages so the markdown reflects page boundaries
4. Extract embedded images where possible — `pdfplumber` exposes image bounding boxes; use `pdf2image` to crop specific regions if needed, or extract raw image data from the PDF stream

### Style Extraction

Capture per page:
- Page dimensions (width, height, rotation)
- Margins (estimate from text bounding boxes — leftmost text x, topmost text y, etc.)
- Font info if available from `pdfplumber` char-level data (font name, size per text block)

Store in sidecar keyed by content hash of each text block.

### Export (`DocumentModel → pdf`)

Use `weasyprint`:

1. Generate HTML from the DocumentModel:
   - Headings → `<h1>`–`<h6>`
   - Paragraphs → `<p>` with inline formatting
   - Tables → `<table>` with `<thead>` and `<tbody>`
   - Images → `<img>` tags with base64-encoded or file-referenced images
   - Code blocks → `<pre><code>`
   - Lists → `<ul>` / `<ol>`
   - Page breaks → `<div style="page-break-before: always">`
2. Apply sidecar styles if available:
   - Page size and margins → `@page` CSS rule
   - Font families and sizes → inline styles or CSS classes
3. Render HTML → PDF via `weasyprint.HTML(string=html).write_pdf(output_path)`

**Tier 3 is not practical for PDF** — PDF internal structure is too complex to patch. Export is always Tier 1 or Tier 2.

### OCR Integration

This is the primary consumer of Phase 3's OCR pipeline:

- When a scanned page is detected, build `OCRConfig` from user preferences (`ocr_confidence_threshold`)
- Pass page image(s) to `run_ocr()`
- If flags are generated and `unattended == False`, the converter sets batch status to `"ocr_review_needed"` (already wired in Phase 3)
- After review, finalized text is used in the DocumentModel

### Edge Cases
- **Encrypted/password-protected PDFs**: `pdfplumber` will raise an error. Catch it, log it, mark file as `error` in manifest.
- **Very large PDFs (50+ pages)**: Process page-by-page, don't load all pages into memory. Use `pdf2image`'s `first_page`/`last_page` params.
- **PDFs with no content** (blank pages only): Detect and produce empty markdown with a note.
- **Rotated pages**: Check `page.rotation` in pdfplumber, rotate the image before OCR.

---

## Handler 2: PPTX (`formats/pptx_handler.py`)

### Dependencies
- `python-pptx` — read and write PowerPoint files

### Extensions
- `.pptx`

### Ingest (`pptx → DocumentModel`)

1. Open with `python-pptx.Presentation(file_path)`
2. For each slide (in order):
   a. Add a `HEADING` element (level 2) with the slide title (from title placeholder). If no title placeholder, use `"Slide {N}"`.
   b. Walk all shapes on the slide:
      - **Text frames** (`shape.has_text_frame`): Each paragraph → `PARAGRAPH` element. Preserve bold/italic/underline from runs.
      - **Tables** (`shape.has_table`): → `TABLE` element. Extract cell text row by row.
      - **Images** (`shape.shape_type == MSO_SHAPE_TYPE.PICTURE`): Extract image via `shape.image.blob` → `core/image_handler.py`. → `IMAGE` element.
      - **Charts**: Extract chart title + data summary as a paragraph (chart image extraction is optional stretch goal).
      - **Grouped shapes**: Attempt to recurse into `shape.shapes` if available. If not accessible, skip with warning.
   c. **Speaker notes**: If `slide.notes_slide` exists and has text, add as a `BLOCKQUOTE` element after the slide's content, prefixed with "Speaker Notes:".
   d. Add a `HORIZONTAL_RULE` between slides

### Style Extraction

- Slide dimensions (`presentation.slide_width`, `presentation.slide_height`)
- Slide layout name per slide (`slide.slide_layout.name`)
- Per-shape: position (left, top), dimensions (width, height), placeholder index
- Per-text-run: font name, size, bold, italic, color
- Theme colors if accessible

### Export (`DocumentModel → pptx`)

1. Create new `Presentation()`
2. Parse markdown: each H2 boundary = new slide
3. For each slide section:
   - Use the default slide layout (Title and Content) or match layout name from sidecar
   - Set title from H2 text
   - Add body content: paragraphs → text frame content, tables → add table shape, images → add picture shape
   - Apply speaker notes: if a blockquote starts with "Speaker Notes:", put it in `slide.notes_slide`
4. **Sidecar Tier 2**: Apply slide dimensions, shape positions, font properties from sidecar
5. **Tier 3**: If original `.pptx` exists and hash match ≥ 80%, clone the original presentation and patch text content in-place (similar strategy to DOCX Tier 3). Text runs can be updated while preserving formatting.

### Edge Cases
- **Slides with only images** (no text shapes): Create a slide with just the image, no body text frame.
- **Master slides / templates**: Don't modify or export master slide content. Only process actual slides.
- **SmartArt / grouped shapes**: Log a warning, skip, or extract visible text if possible. Don't crash.
- **Embedded media (audio/video)**: Skip with a note in the markdown: `<!-- Embedded media: {filename} -->`

---

## Handler 3: XLSX (`formats/xlsx_handler.py`)

### Dependencies
- `openpyxl` — read and write Excel files

### Extensions
- `.xlsx`

### Ingest (`xlsx → DocumentModel`)

1. Open with `openpyxl.load_workbook(file_path, data_only=True)` (resolve formulas to values)
2. Also open with `openpyxl.load_workbook(file_path, data_only=False)` to capture formula text
3. For each sheet:
   a. Add a `HEADING` element (level 2) with the sheet name
   b. Build a table from the used range (`ws.min_row` to `ws.max_row`, `ws.min_col` to `ws.max_col`)
   c. First row → table headers (if it looks like a header row — heuristic: all cells are strings, or first row has different formatting). If ambiguous, treat first row as header anyway.
   d. Add as a `TABLE` element with `rows` containing all data
   e. **Merged cells**: Unmerge and duplicate the value into all cells of the merge range (so the table is rectangular)
   f. **Formulas**: Store formula text as an annotation. In markdown, show the computed value. In the sidecar, store `{cell_ref: {value: X, formula: "=SUM(A1:A10)"}}` so export can restore formulas.
   g. **Empty rows/columns**: Trim trailing empty rows and columns, but preserve internal empty cells as empty table cells.
4. Extract images from each sheet via `ws._images` → IMAGE elements

### Style Extraction

- Per-cell: number format, font, fill color, alignment, border style
- Per-column: width
- Per-row: height
- Sheet-level: freeze panes, auto-filter ranges, print area
- Per-cell formulas (from the non-data_only workbook)

### Export (`DocumentModel → xlsx`)

1. Create new `openpyxl.Workbook()`
2. Parse markdown: each H2 boundary = new sheet
3. For each sheet section:
   - Create/rename worksheet
   - Parse the markdown table → write cell values
   - If sidecar exists:
     - Restore column widths
     - Restore number formats per cell
     - Restore formulas (replace computed values with formula text from sidecar)
     - Restore cell styles (font, fill, alignment)
     - Restore merged cell ranges
4. **Tier 3**: If original `.xlsx` exists and hash match ≥ 80%, open the original and patch cell values in-place. This preserves charts, conditional formatting, pivot tables, and everything else openpyxl doesn't easily create from scratch.

### Edge Cases
- **Multiple sheets**: Each sheet is an H2 section. Markdown → XLSX creates one sheet per H2.
- **Very large sheets (10k+ rows)**: Use `openpyxl`'s read-only mode (`load_workbook(read_only=True)`) for ingest. Switch to write-only mode for export of large datasets.
- **Charts**: Cannot reliably extract or recreate. Log chart presence in sidecar metadata. On Tier 3 export, charts survive because the original file is patched.
- **Conditional formatting**: Store rules in sidecar. On Tier 2 export, attempt to restore. On Tier 1, skip.
- **Cell types**: Preserve int/float/date/string typing. Don't stringify everything.

---

## Handler 4: CSV (`formats/csv_handler.py`)

### Dependencies
- `pandas` — read and write CSV/TSV
- Python stdlib `csv` — fallback

### Extensions
- `.csv`, `.tsv`

### Ingest (`csv → DocumentModel`)

1. Read with `pandas.read_csv(file_path)` (auto-detect delimiter for `.csv`, use `\t` for `.tsv`)
   - Handle encoding detection: try UTF-8 first, fall back to `latin-1`, then `cp1252`
   - If pandas chokes (malformed CSV), fall back to stdlib `csv.reader` with error handling
2. First row → headers (column names)
3. All rows → single `TABLE` element
4. If the CSV is very large (> 1000 rows), still ingest it all — markdown tables will be long but correct

### Style Extraction

Minimal — CSV has no styling. Store:
- Delimiter used (`,` or `\t` or other)
- Encoding detected
- Column dtypes (so export can preserve int/float/date typing)
- Whether the file had a header row

### Export (`DocumentModel → csv`)

1. Parse the markdown table → DataFrame
2. Write with `pandas.to_csv(output_path, index=False)`
3. If sidecar exists, use stored delimiter and encoding
4. Preserve column order from markdown

**No Tier 2/3 for CSV** — there are no styles to restore.

### Edge Cases
- **TSV detection**: If extension is `.tsv`, use `sep='\t'`. If `.csv` but tab-delimited, pandas auto-detect should handle it.
- **Quoted fields with newlines**: Pandas handles this. Stdlib `csv` handles this. Don't break on multiline cells.
- **BOM markers**: UTF-8 BOM (`\xef\xbb\xbf`) — use `encoding='utf-8-sig'` to handle transparently.
- **Empty CSV**: Produce empty markdown with a note. Don't crash.

---

## Extension Whitelist Update

Update the extension validation in `api/routes/convert.py` to accept the new formats:

```python
ALLOWED_EXTENSIONS = {
    # Existing
    ".docx", ".doc", ".md",
    # Phase 4
    ".pdf", ".pptx", ".xlsx", ".csv", ".tsv",
}
```

Also update the format preview/detection logic in `core/converter.py` if it checks extensions.

---

## Test Fixtures (`tests/generate_fixtures.py`)

Add fixture generators:

```python
def generate_pdf_fixtures(fixtures_dir: Path):
    """Generate simple.pdf (text-layer) and scanned.pdf (image-based)"""

def generate_pptx_fixtures(fixtures_dir: Path):
    """Generate simple.pptx (5 slides, titles, body, notes, table, image)"""

def generate_xlsx_fixtures(fixtures_dir: Path):
    """Generate simple.xlsx (2 sheets, headers, data, formulas, merged cells)"""

def generate_csv_fixtures(fixtures_dir: Path):
    """Generate simple.csv and simple.tsv"""
```

**PDF fixtures** — Use `fpdf2` (already in the Docker image via `weasyprint` deps, or add `fpdf2` to requirements):
- `simple_text.pdf` — 3 pages of clean text with headings and a table
- `scanned.pdf` — Render text to image, embed image in PDF (simulates a scan). Should trigger OCR.
- `mixed.pdf` — Page 1 text-layer, page 2 scanned. Tests mixed-mode handling.

**PPTX fixtures** — Use `python-pptx`:
- `simple.pptx` — 5 slides: title slide, text slide, slide with table, slide with image, slide with speaker notes

**XLSX fixtures** — Use `openpyxl`:
- `simple.xlsx` — 2 sheets: Sheet1 has headers + 10 rows of mixed types (strings, ints, floats, dates) + a SUM formula; Sheet2 has 5 rows with a merged cell range
- `complex.xlsx` — Conditional formatting, multiple number formats, wider column widths, freeze panes

**CSV fixtures** — Write directly:
- `simple.csv` — 5 columns, 10 rows, UTF-8
- `unicode.csv` — Contains non-ASCII characters (accents, CJK, emoji)
- `simple.tsv` — Tab-delimited version

---

## Tests

### `tests/test_pdf.py`

**Ingest:**
- `simple_text.pdf` → DocumentModel has correct heading count, paragraph content
- `simple_text.pdf` → tables extracted correctly
- `scanned.pdf` → OCR triggered, text extracted (substring match against known rendered text)
- `scanned.pdf` → OCR flags generated (if bad quality regions exist)
- `mixed.pdf` → text pages extracted directly, scanned pages OCR'd
- Encrypted PDF → raises/returns error, doesn't crash

**Export:**
- DocumentModel with headings, paragraphs, tables, images → valid PDF file
- Output PDF is readable (can be opened with pdfplumber without errors)
- Sidecar Tier 2: page size and margins applied

**Round-trip:**
- `simple_text.pdf` → `.md` → `.pdf` — structure survives (heading count, table count)
- Content is approximately equivalent (exact formatting will differ since export uses weasyprint)

### `tests/test_pptx.py`

**Ingest:**
- `simple.pptx` → DocumentModel has 5 H2 sections (one per slide)
- Slide titles extracted correctly
- Body text, table, image, speaker notes all present
- Speaker notes appear as blockquotes

**Export:**
- DocumentModel → `.pptx` with correct slide count
- Slide titles match H2 headings
- Tables have correct row/column counts
- Images embedded and visible
- Speaker notes restored

**Round-trip:**
- `simple.pptx` → `.md` → `.pptx` — 5 slides, titles match, content present

### `tests/test_xlsx.py`

**Ingest:**
- `simple.xlsx` → DocumentModel has 2 H2 sections (one per sheet)
- Table dimensions match (row count, column count)
- Cell values preserved (spot-check specific cells)
- Merged cells unmerged with duplicated values
- Formulas captured in sidecar (verify `formula` key exists)

**Export:**
- DocumentModel → `.xlsx` with correct sheet count
- Cell values match
- Sidecar Tier 2: column widths restored, number formats applied
- Formulas restored from sidecar (verify formula text in non-data_only read)

**Round-trip:**
- `simple.xlsx` → `.md` → `.xlsx` — 2 sheets, row/column counts match, values match

### `tests/test_csv.py`

**Ingest:**
- `simple.csv` → DocumentModel with single TABLE element
- Column count and row count correct
- Header row detected
- `unicode.csv` → non-ASCII characters preserved
- `simple.tsv` → parsed correctly with tab delimiter

**Export:**
- DocumentModel → `.csv` — row/column counts match, values match
- Delimiter preserved from sidecar (TSV stays TSV)

**Round-trip:**
- `simple.csv` → `.md` → `.csv` — values match, column order preserved

---

## Build Order Within Phase 4

**Do these sequentially. Get each handler passing tests before starting the next.**

### 4a — PDF Handler
1. `formats/pdf_handler.py` — `ingest()` with text extraction + OCR integration
2. `formats/pdf_handler.py` — `export()` via weasyprint
3. `formats/pdf_handler.py` — `extract_styles()`
4. Register in format registry
5. Test fixtures: `simple_text.pdf`, `scanned.pdf`, `mixed.pdf`
6. `tests/test_pdf.py` — all ingest, export, round-trip, OCR integration tests
7. Update extension whitelist

### 4b — PPTX Handler
8. `formats/pptx_handler.py` — `ingest()` with shapes, tables, images, notes
9. `formats/pptx_handler.py` — `export()` with slide reconstruction
10. `formats/pptx_handler.py` — `extract_styles()`
11. Register in format registry
12. Test fixture: `simple.pptx`
13. `tests/test_pptx.py`

### 4c — XLSX Handler
14. `formats/xlsx_handler.py` — `ingest()` with sheets, tables, formulas, merged cells
15. `formats/xlsx_handler.py` — `export()` with style/formula restoration
16. `formats/xlsx_handler.py` — `extract_styles()`
17. Register in format registry
18. Test fixtures: `simple.xlsx`, `complex.xlsx`
19. `tests/test_xlsx.py`

### 4d — CSV Handler
20. `formats/csv_handler.py` — `ingest()` with encoding detection + delimiter handling
21. `formats/csv_handler.py` — `export()` with delimiter/encoding preservation
22. Register in format registry
23. Test fixtures: `simple.csv`, `unicode.csv`, `simple.tsv`
24. `tests/test_csv.py`

### 4e — Integration
25. Update `api/routes/convert.py` extension whitelist
26. Verify all four handlers work through the full API (upload → convert → download)
27. Run entire test suite — all phases, no regressions

---

## Update CLAUDE.md

After all tests pass:

- Set Phase 4 status to ✅ Done
- Update "Current Status" — Phase 4 complete, next Phase 5
- Add new key files (`formats/pdf_handler.py`, `formats/pptx_handler.py`, `formats/xlsx_handler.py`, `formats/csv_handler.py`)
- Add any gotchas (weasyprint quirks, pdfplumber limitations, openpyxl formula handling, etc.)
- Update test count
- Tag as `v0.4.0`

---

## Phase 4 Done Criteria

- [ ] **PDF**: Text-layer PDFs extract text directly. Scanned PDFs trigger OCR. Mixed PDFs handle page-by-page. Export via weasyprint produces valid PDF.
- [ ] **PPTX**: Slides ingest with titles, body, tables, images, speaker notes. Export reconstructs slides with correct structure.
- [ ] **XLSX**: Sheets ingest with tables, merged cells, formulas. Export restores styles and formulas from sidecar. Tier 3 patches original file.
- [ ] **CSV/TSV**: Ingest with encoding/delimiter detection. Export preserves delimiter and encoding. Unicode survives round-trip.
- [ ] All four handlers registered in format registry
- [ ] Extension whitelist updated in convert API
- [ ] Upload any supported format via the web UI → convert → download works end-to-end
- [ ] All new format tests pass
- [ ] All existing Phase 1–3 tests still pass (no regressions)
- [ ] `CLAUDE.md` updated, tagged `v0.4.0`
