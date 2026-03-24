# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Keep this up to date after each phase.

---

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — a Python/FastAPI web app that converts
documents bidirectionally between their original format and Markdown. Runs in Docker.
GitHub: `github.com/theace26/Doc-Conversion-2026`

---

## Current Status

**Phase 0 complete** — Docker scaffold running. All system deps verified.
**Phase 1 complete** — DOCX → Markdown pipeline fully implemented. 60 tests passing. Tagged v0.1.0.
**Phase 2 complete** — Markdown → DOCX round-trip with fidelity tiers. 96 tests passing. Tagged v0.2.0.
**Phase 3 complete** — OCR pipeline: multi-signal detection, preprocessing, Tesseract extraction,
  confidence flagging, review API + UI, unattended mode, SQLite persistence. Tagged v0.3.0.
**Phase 4 complete** — PDF, PPTX, XLSX/CSV format handlers (both directions). 231 tests passing. Tagged v0.4.0.
**Phase 5 complete** — Full test suite (350+ tests), structured JSON logging throughout all
  pipeline stages, debug dashboard at /debug. Tagged v0.5.0.
**Next: Phase 6** — Full UI, batch progress, history page, settings, polish.

---

## Phase Checklist

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Docker scaffold, project structure, DB schema, health check | ✅ Done |
| 1 | Foundation: DOCX → Markdown (DocumentModel, DocxHandler, metadata, upload UI) | ✅ Done |
| 2 | Round-trip: Markdown → DOCX with fidelity tiers | ✅ Done |
| 3 | OCR pipeline (multi-signal detection, review UI, unattended mode) | ✅ Done |
| 4 | Remaining formats: PDF, PPTX, XLSX/CSV (both directions) | ✅ Done |
| 5 | Testing & debug infrastructure (full test suite, structlog, debug dashboard) | ✅ Done |
| 6 | Full UI, batch progress, history page, settings, polish | ⬜ |

---

## Phase 1 Instructions

Implement the full DOCX → Markdown pipeline end-to-end:

1. **`core/document_model.py`** — All dataclasses: `DocumentModel`, `Element`, `ElementType`,
   `DocumentMetadata`, `ImageData`. Content hash (SHA-256 of normalized text). Serialize/deserialize
   to dict. Helpers: `add_element()`, `get_elements_by_type()`, `to_markdown()`, `from_markdown()`.

2. **`formats/base.py`** — Abstract `FormatHandler` with methods: `ingest(file_path) → DocumentModel`,
   `export(model, output_path, sidecar=None)`, `extract_styles(file_path) → dict`,
   `supports_format(extension) → bool` (classmethod). Registry pattern for lookup by extension.

3. **`formats/markdown_handler.py`** — `export(model) → str` (all ElementTypes → Markdown + YAML
   frontmatter). `ingest(md_string) → DocumentModel` (use mistune, not regex). Split frontmatter first.

4. **`formats/docx_handler.py`** — `ingest`: walk paragraphs + tables, map styles to ElementTypes,
   extract images (hash-named PNG), footnotes, nested tables. `extract_styles`: font/size/spacing
   per element + document-level page settings, keyed by content hash. `export`: Tier 1 structure always.

5. **`core/image_handler.py`** — `extract_image(data, fmt) → (hash_filename, png_data, metadata)`.
   Hash: `sha256(data).hexdigest()[:12] + ".png"`. Convert EMF/WMF/TIFF → PNG via Pillow.

6. **`core/metadata.py`** — `generate_frontmatter(model)`, `parse_frontmatter(md_text)`,
   `generate_manifest(batch_id, files)`, `generate_sidecar(model, style_data)`, `load_sidecar(path)`.

7. **`core/style_extractor.py`** — Wrapper with content-hash keying, `schema_version: "1.0.0"`.

8. **`core/converter.py`** — `ConversionOrchestrator.convert_file()`. Pipeline: validate → detect
   format → ingest → build model → extract styles → generate output → write metadata → record in DB.
   `asyncio.to_thread()` for CPU-bound work. Copy original to `output/<batch_id>/_originals/`.

9. **`api/models.py`** — Pydantic models: `ConvertRequest/Response`, `BatchStatus`, `FileStatus`,
   `PreviewRequest/Response`, `HistoryRecord`, `HistoryListResponse`, `StatsResponse`, `PreferenceUpdate`.

10. **`api/middleware.py`** — Already implemented (request ID + timing). No changes needed.

11. **`api/routes/convert.py`** — `POST /api/convert` (upload + validate + start conversion → batch_id).
    `POST /api/convert/preview` (analyze without converting). Validate: size limits, extension whitelist,
    zip bomb check. Update `last_source_directory` preference.

12. **`api/routes/batch.py`** — `GET /api/batch/{id}/status`, `GET /api/batch/{id}/download` (zip),
    `GET /api/batch/{id}/download/{filename}`, `GET /api/batch/{id}/manifest`.

13. **`api/routes/history.py`** — `GET /api/history` (paginated, filterable), `GET /api/history/{id}`,
    `GET /api/history/stats`.

14. **`api/routes/preferences.py`** — `GET /api/preferences`, `PUT /api/preferences/{key}`.

15. **`static/index.html`** — Already implemented. Minor updates if needed for new API shape.

16. **`static/results.html`** — Download links, "Download All" zip, manifest link, summary stats.

17. **Tests** — `tests/generate_fixtures.py`: create `simple.docx` and `complex.docx` programmatically.
    `tests/test_document_model.py`, `tests/test_docx.py`, `tests/test_api.py` (initial), `tests/conftest.py`.

### Phase 1 Done Criteria
- Upload a `.docx` → get a `.md` with correct headings, paragraphs, tables, images
- YAML frontmatter in output `.md`
- Manifest JSON generated in output directory
- Style sidecar JSON with content-hash keys
- Original file preserved in `_originals/`
- Conversion recorded in SQLite `conversion_history`
- Upload UI works (drag-and-drop, preview, convert, download)
- All tests pass

---

## Architecture Reminders

- **No Pandoc** — library-level only
- **No SPA** — vanilla HTML + fetch calls
- **Fail gracefully** — one bad file never crashes a batch
- **Fidelity tiers**: Tier 1 = structure (guaranteed), Tier 2 = styles (sidecar), Tier 3 = original file patch
- **Content-hash keying** — sidecar JSON keyed by SHA-256 of normalized paragraph/table content
- **Format registry** — handlers register by extension, converter looks up by extension

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, mounts all routers + `/ocr-images` static |
| `core/database.py` | SQLite connection, schema, preference + history + ocr_flags helpers |
| `core/health.py` | Startup checks for Tesseract, LibreOffice, Poppler, WeasyPrint, disk, DB |
| `core/logging_config.py` | structlog JSON logging, rotating file handler |
| `core/converter.py` | Pipeline orchestrator; `from_md` path detects sidecar + original → tier 1/2/3 |
| `core/ocr_models.py` | OCR dataclasses: OCRWord, OCRFlag, OCRPage, OCRConfig, OCRResult, OCRFlagStatus |
| `core/ocr.py` | OCR engine: `needs_ocr`, `preprocess_image`, `ocr_page`, `flag_low_confidence`, `run_ocr` |
| `formats/docx_handler.py` | DOCX ingest + export; `_add_inline_runs`, `_plain_text_hash`, `_patch_from_original` |
| `formats/markdown_handler.py` | MD ingest + export; `_extract_formatted_text` for inline bold/italic/code |
| `formats/pdf_handler.py` | PDF ingest (pdfplumber + OCR) + export (WeasyPrint); font-size heading detection |
| `formats/pptx_handler.py` | PPTX ingest (slides→H2 sections) + export; Tier 3 text patching |
| `formats/xlsx_handler.py` | XLSX ingest (sheets→H2+TABLE) + export; formula/merge/style restoration |
| `formats/csv_handler.py` | CSV/TSV ingest (pandas + stdlib fallback) + export; delimiter/encoding preserved |
| `api/middleware.py` | Request ID injection, timing, debug headers |
| `api/routes/review.py` | OCR review endpoints: list, counts, single-flag, resolve, accept-all |
| `api/routes/debug.py` | Debug dashboard API: /debug, /debug/api/health, /debug/api/activity, /debug/api/logs, /debug/api/ocr_distribution |
| `static/review.html` | Interactive OCR review page (side-by-side image + editable text) |
| `static/debug.html` | Developer debug dashboard — health pills, activity, OCR distribution, log viewer |
| `pytest.ini` | Test configuration: asyncio_mode, custom markers (slow, ocr, integration) |
| `docker-compose.yml` | Port 8000, volumes: input/output/logs + named volume for DB |

---

## Gotchas & Fixes Found

- **aiosqlite pattern**: Use `async with aiosqlite.connect(path) as conn` — never
  `conn = await aiosqlite.connect(path)` then `async with conn` (starts the thread twice → RuntimeError).
  All DB helpers use `@asynccontextmanager` + `async with aiosqlite.connect()`.

- **Debian trixie package name**: `libgdk-pixbuf-2.0-0` (not `libgdk-pixbuf2.0-0`).

- **structlog + stdlib**: Call `configure_logging()` once at module level in `main.py` before
  the app is created. The formatter must be set on `logging.root.handlers`.

- **DB path**: `DB_PATH` env var (default `markflow.db` locally, `/app/data/markflow.db` in container).
  The Docker volume `markflow-db` mounts to `/app/data`.

- **mistune v3 table plugin**: `create_markdown(renderer=None)` does NOT parse tables by default.
  Must pass `plugins=["table", "strikethrough", "footnotes"]` or tables silently become paragraphs.
  Discovered in Phase 2 round-trip testing.

- **Sidecar hash mismatch**: `extract_styles()` keys sidecar by `para.text` (plain text), but
  `_process_paragraph` stores element content with markdown markers (`**bold**`). Use `_plain_text_hash()`
  (strips markers before hashing) when looking up sidecar entries during export.

- **Tier 3 detection**: In `from_md` direction, converter looks for original `.docx` in the same
  directory as the `.md` file. If user uploads `report.md` + `report.styles.json` + `report.docx`
  together, all land in the same `tmp_dir` and tier is automatically promoted to 3.

- **`FormatHandler.export()` signature**: `original_path: Path | None = None` was added in Phase 2.
  All handlers must accept it (they can ignore it). `MarkdownHandler.export()` accepts but ignores it.

- **OCR deskew is slow**: `_detect_skew()` does 31 coarse + up to 9 fine-step rotations via Pillow.
  On large (A4@300 DPI) page images this can take several seconds per page. Keep page images at
  reasonable sizes for tests (< 1000 px wide) or disable preprocessing with `OCRConfig(preprocess=False)`.

- **Tesseract `-1` confidence**: `pytesseract.image_to_data()` returns `conf == -1` for rows that
  are not words (block/paragraph/line separators). These are clamped to `0.0` in `ocr_page()` and
  should not appear as actual words (the `text` field is empty for those rows so they are skipped).

- **review router route ordering**: The `accept-all` POST route (`/{batch_id}/review/accept-all`)
  must be registered **before** `/{batch_id}/review/{flag_id}` POST route. FastAPI matches routes
  in registration order — the parametric route would capture the literal "accept-all" string as a
  `flag_id` and the bulk-accept endpoint would never be reached. Fixed in `review.py` by ordering
  `accept-all` first in the file.

- **`/ocr-images` static mount**: Served from `OUTPUT_DIR` (default `output/`). If `output/` does
  not exist at startup, `os.makedirs` creates it before `StaticFiles` is mounted.

- **OCR flag image paths**: Stored in DB as forward-slash paths relative to CWD
  (e.g., `output/<batch_id>/_ocr_debug/stem_flag_<uuid>.png`). The review API strips the
  `output/` prefix to build `/ocr-images/…` URLs.

- **python-pptx `placeholder_format`**: Accessing `.placeholder_format` on non-placeholder
  shapes (e.g., `GraphicFrame` for tables) raises `ValueError`, not returns `None`. Must wrap
  in `try/except (ValueError, AttributeError)`. Same for `run.font.color.rgb` on `_NoneColor`.

- **pdfplumber text extraction**: Returns `\n`-separated lines, not `\n\n`-separated paragraphs.
  Heading detection uses char-level font sizes (larger than body font = heading). Without char
  data, falls back to heuristic (title case, ALL CAPS, short lines).

- **PDF export via WeasyPrint**: Always Tier 1 or Tier 2 — PDF internal structure is too complex
  for Tier 3 patching. Export path: DocumentModel → HTML → `weasyprint.HTML().write_pdf()`.

- **XLSX dual workbook open**: `openpyxl.load_workbook(data_only=True)` for computed values,
  `load_workbook(data_only=False)` for formulas. Both needed for full fidelity extraction.

- **XLSX merged cells**: Must unmerge and duplicate the top-left value into all cells of the
  merge range before building the TABLE element, or the table will have `None` holes.

- **CSV encoding detection**: Try `utf-8-sig` (handles BOM) → `utf-8` → `latin-1` → `cp1252`.
  pandas `read_csv` with `dtype=str, keep_default_na=False` prevents type coercion surprises.

- **fpdf2 `new_x`/`new_y` API**: fpdf2 v2.8+ uses `new_x="LMARGIN", new_y="NEXT"` instead of
  the deprecated `ln=True` parameter for `cell()` calls.

- **structlog + stdlib coexistence**: All `core/` and `formats/` modules must use
  `structlog.get_logger(__name__)`, not `logging.getLogger(__name__)`. The stdlib `logging`
  import is only allowed in `core/logging_config.py` (for configuring the underlying handlers).
  Format handlers were migrated from stdlib to structlog in Phase 5.

- **`/api/health` response envelope**: Phase 5 wrapped the health response in
  `{"status", "timestamp", "uptime_seconds", "components": {...}}`. Tests must check
  `data["components"]["database"]` not `data["database"]`.

- **XLSX `MergedCell.value` is read-only**: When patching values in Tier 3 export
  (`_try_tier3_export`), cells in merged ranges raise `AttributeError` on write. Must
  wrap in `try/except AttributeError` and skip merged cells.

- **`MarkdownHandler.ingest()` takes a file Path**: Use `ingest(path)` not `ingest(text)`.
  For string input, use `ingest_text(md_string)` or the internal `_ingest_text()`.

- **Log file is `markflow.json` not `markflow.log`**: Phase 5 changed the rotating file handler
  output to JSON format with `.json` extension for machine-parseable log tailing.

- **Debug dashboard always mounted**: `/debug` routes are no longer behind `DEBUG=true`.
  The dashboard is a developer tool and is always available at `/debug`.

---

## Running the App

```bash
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
