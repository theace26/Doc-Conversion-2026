# Phase 2 — Round-Trip: Markdown → DOCX with Fidelity Tiers

Read `CLAUDE.md` for project context, architecture, and gotchas before starting.

---

## Objective

Implement the Markdown → DOCX export pipeline in `formats/docx_handler.py`. A user should be able to:

1. Upload a `.docx` → get a `.md` (Phase 1 — already works)
2. Upload that `.md` → get a `.docx` back that faithfully reconstructs the original

The quality of reconstruction depends on what metadata is available, expressed as **fidelity tiers**.

---

## Fidelity Tiers

### Tier 1 — Structure (always available)

Reconstruct from the markdown content alone. No sidecar needed.

- Headings → Word heading styles (Heading 1–6)
- Paragraphs → Normal style
- Bold, italic, code spans → character-level runs
- Tables → Word tables with auto-fit column widths
- Bulleted lists → Word list style
- Numbered lists → Word numbered list style
- Images → re-embed from `assets/` subfolder using relative paths in markdown image links
- Horizontal rules → page break or styled separator
- Code blocks → monospace font paragraph (Courier New or Consolas)
- Blockquotes → indented paragraph with left border style

This must produce a clean, readable `.docx` even with zero metadata. Think of it as "what you'd get if you wrote the doc from scratch based on the markdown."

### Tier 2 — Style Restoration (when sidecar exists)

If a `.styles.json` sidecar file exists (generated during Phase 1 ingest), apply the original styling on top of Tier 1 structure:

- **Font families and sizes** per element (keyed by content hash)
- **Paragraph spacing** (before/after, line spacing)
- **Table column widths** (exact widths from original)
- **Page settings** (margins, page size, orientation) from the document-level sidecar data
- **Header/footer content** if captured
- **Image dimensions** (original width/height)
- **Alignment** (left/center/right/justify per paragraph)
- **Colors** (font color, highlight) if captured in sidecar

Sidecar lookup: Match elements by **content hash** (SHA-256 of normalized text). If a hash doesn't match (content was edited in the markdown), fall back to Tier 1 defaults for that element.

### Tier 3 — Original File Patch (when original preserved)

If the original `.docx` is preserved in `output/<batch_id>/_originals/`, use it as a template:

- Open the original `.docx` with `python-docx`
- Walk the document in parallel with the `DocumentModel`
- For elements with **matching content hashes**: keep the original XML element untouched (perfect fidelity)
- For elements with **changed content**: replace the text content but preserve the original run formatting and paragraph properties
- For **new elements** (in markdown but not in original): append using Tier 2 or Tier 1 styling
- For **deleted elements** (in original but not in markdown): remove them

This gives near-perfect round-trip for unedited content and graceful degradation for edits.

---

## Implementation Plan

### Step 1 — Tier 1 Export in `DocxHandler.export()`

Update `formats/docx_handler.py`:

```python
def export(self, model: DocumentModel, output_path: Path, sidecar: dict | None = None) -> Path:
```

- Create a new `python-docx` `Document()`
- Walk `model.elements` in order
- Map each `ElementType` to the corresponding `python-docx` call:
  - `HEADING` → `doc.add_heading(text, level=element.level)`
  - `PARAGRAPH` → `doc.add_paragraph(text)` with inline formatting (bold/italic/code from element attributes)
  - `TABLE` → `doc.add_table(rows, cols)` with cell content from `element.rows`
  - `LIST_ITEM` → `doc.add_paragraph(text, style='List Bullet')` or `'List Number'` based on `element.list_type`
  - `IMAGE` → `doc.add_picture(image_path, width=Inches(6))` — load from `assets/` path in element
  - `CODE_BLOCK` → `doc.add_paragraph(text)` with monospace font run
  - `BLOCKQUOTE` → `doc.add_paragraph(text)` with left indent
  - `HORIZONTAL_RULE` → page break or thin-line paragraph
  - `FOOTNOTE` → handle if the DocumentModel captured them; otherwise skip gracefully
- Save to `output_path`
- Return the output path

### Step 2 — Tier 2 Style Application

After Tier 1 builds the structural document, apply sidecar styles if available:

```python
def _apply_sidecar_styles(self, doc: Document, model: DocumentModel, sidecar: dict) -> None:
```

- Read document-level settings from sidecar (page size, margins, orientation) → apply to `doc.sections[0]`
- Walk elements + paragraphs in parallel
- For each element, compute its content hash
- Look up `sidecar["elements"][content_hash]`
- If found, apply: font family, font size, bold/italic overrides, paragraph spacing, alignment, colors
- For tables: apply column widths from `sidecar["elements"][table_hash]["column_widths"]`
- For images: apply original dimensions from sidecar
- If hash not found (content was edited): skip, keep Tier 1 defaults

### Step 3 — Tier 3 Original Patch

```python
def _patch_from_original(self, model: DocumentModel, original_path: Path, sidecar: dict | None) -> Document:
```

- Open original `.docx` as the base document
- Build a map: `{content_hash: original_element_index}` from original
- Build a map: `{content_hash: model_element}` from the DocumentModel
- Walk the model elements:
  - **Unchanged** (hash exists in both): leave original element in place
  - **Changed** (same position, different hash): update text runs preserving formatting
  - **New**: insert at correct position using Tier 2/1 styling
  - **Deleted**: remove from document
- This is the hardest part. Start with a simpler approach: if ≥80% of hashes match, use patch mode. Otherwise fall back to Tier 2/1 full rebuild.

### Step 4 — Wire Into Converter

Update `core/converter.py` `ConversionOrchestrator`:

- Detect direction: if input is `.md` and requested output is `.docx`, use the markdown handler to ingest → `DocumentModel`, then docx handler to export
- Look for sidecar: check if frontmatter `style_ref` points to an existing `.styles.json`
- Look for original: check if `_originals/` contains the source file referenced in frontmatter
- Choose tier: Tier 3 if original exists + sidecar, Tier 2 if sidecar only, Tier 1 if neither
- Log which tier was used

### Step 5 — Update Upload UI

Update `static/index.html`:

- The direction toggle (`Original → Markdown` / `Markdown → Original`) should already exist or be easy to add
- When direction is `Markdown → Original`:
  - Accept `.md` file uploads
  - Show a note: "For best results, include the `.styles.json` sidecar file alongside the markdown"
  - Optionally allow uploading the sidecar alongside the `.md`
- Results page: show which fidelity tier was achieved

### Step 6 — Update API

- `POST /api/convert` should accept `.md` files and optional sidecar
- Response should include `fidelity_tier` (1, 2, or 3) in the result
- History record should store fidelity tier

### Step 7 — Tests

Add to `tests/`:

**`tests/test_roundtrip.py`:**
- Tier 1 test: Convert `simple.docx` → `.md` → `.docx`. Verify heading count, paragraph count, table count, image count match.
- Tier 2 test: Convert `simple.docx` → `.md` + sidecar → `.docx`. Verify structure matches AND font families, paragraph spacing, table column widths match original.
- Tier 3 test: Convert `simple.docx` → `.md` (with original preserved) → `.docx`. Verify near-identical structure.
- Edited content test: Convert `simple.docx` → `.md`, modify a paragraph in the markdown, convert back. Verify the edit appears in the output and unedited elements retain formatting.
- No-sidecar fallback: Convert a `.md` file with no sidecar → `.docx`. Should produce clean Tier 1 output without errors.

**`tests/test_docx_export.py`:**
- Each ElementType produces correct Word element
- Inline formatting (bold, italic, code) preserved in runs
- Images re-embedded from assets path
- Tables have correct row/column counts
- Code blocks use monospace font

**Update `tests/test_api.py`:**
- Upload `.md` file → get `.docx` back
- Upload `.md` + sidecar → get `.docx` with Tier 2
- Invalid `.md` (no frontmatter) still converts at Tier 1

### Step 8 — Update CLAUDE.md

After all tests pass:

- Set Phase 2 status to ✅ Done
- Update "Current Status" to reflect Phase 2 complete, next Phase 3
- Add any new gotchas discovered
- Add new key files if any were created
- Tag as `v0.2.0`

---

## Phase 2 Done Criteria

- [ ] Upload a `.md` → get a `.docx` with correct structure (Tier 1)
- [ ] Upload a `.md` + `.styles.json` sidecar → get a `.docx` with restored styling (Tier 2)
- [ ] Upload a `.md` with preserved original in `_originals/` → get near-identical `.docx` (Tier 3)
- [ ] Editing markdown content and converting back preserves edits + retains formatting on untouched elements
- [ ] Fidelity tier is logged, included in API response, and stored in conversion history
- [ ] Direction toggle works in the UI
- [ ] All existing Phase 1 tests still pass (no regressions)
- [ ] All new Phase 2 tests pass
- [ ] `CLAUDE.md` updated with Phase 2 status, new gotchas, new key files
- [ ] Tagged `v0.2.0`
