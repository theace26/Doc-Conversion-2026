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
**Next: Phase 2** — Round-trip Markdown → DOCX with fidelity tiers.

---

## Phase Checklist

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Docker scaffold, project structure, DB schema, health check | ✅ Done |
| 1 | Foundation: DOCX → Markdown (DocumentModel, DocxHandler, metadata, upload UI) | ✅ Done |
| 2 | Round-trip: Markdown → DOCX with fidelity tiers | ⬜ |
| 3 | OCR pipeline (multi-signal detection, review UI, unattended mode) | ⬜ |
| 4 | Remaining formats: PDF, PPTX, XLSX/CSV (both directions) | ⬜ |
| 5 | Testing & debug infrastructure (full test suite, structlog, debug dashboard) | ⬜ |
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
| `main.py` | FastAPI app, lifespan, mounts all routers |
| `core/database.py` | SQLite connection, schema, preference + history helpers |
| `core/health.py` | Startup checks for Tesseract, LibreOffice, Poppler, WeasyPrint, disk, DB |
| `core/logging_config.py` | structlog JSON logging, rotating file handler |
| `api/middleware.py` | Request ID injection, timing, debug headers |
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

---

## Running the App

```bash
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
