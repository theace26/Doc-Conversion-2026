# Phase 1 Instructions (Completed)

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

## Done Criteria
- Upload a `.docx` → get a `.md` with correct headings, paragraphs, tables, images
- YAML frontmatter in output `.md`
- Manifest JSON generated in output directory
- Style sidecar JSON with content-hash keys
- Original file preserved in `_originals/`
- Conversion recorded in SQLite `conversion_history`
- Upload UI works (drag-and-drop, preview, convert, download)
- All tests pass
