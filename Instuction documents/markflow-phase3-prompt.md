# Phase 3 — OCR Pipeline

Read `CLAUDE.md` for project context, architecture, and gotchas before starting.

---

## Objective

Add OCR capability so MarkFlow can convert scanned/image-based PDFs (and image-heavy documents) to Markdown. The OCR pipeline should:

1. **Detect** whether a page/image needs OCR (not everything does)
2. **Process** with Tesseract, capturing per-word confidence scores
3. **Flag** low-confidence regions for interactive review
4. **Support unattended mode** for batch jobs where no human is available to review

Phase 3 focuses on the OCR engine, detection logic, confidence scoring, review API, and review UI. The actual PDF ↔ Markdown format handler comes in Phase 4 — but the OCR pipeline is built as a standalone module that Phase 4 will call.

---

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `core/ocr.py` | OCR engine — preprocessing, Tesseract invocation, confidence extraction, flagging |
| `core/ocr_models.py` | Dataclasses: `OCRPage`, `OCRWord`, `OCRFlag`, `OCRResult`, `OCRConfig` |
| `api/routes/review.py` | Review endpoints — list flags, resolve flags, accept-all |
| `static/review.html` | Interactive OCR review page |
| `tests/test_ocr.py` | OCR pipeline tests |
| `tests/fixtures/` | Add generated test images (clean text, noisy scan, skewed, mixed) |

### Modified Files

| File | Change |
|------|--------|
| `core/database.py` | Add `ocr_flags` table schema |
| `core/converter.py` | Wire OCR into pipeline — call OCR when image content detected |
| `api/models.py` | Add Pydantic models for OCR review request/response |
| `main.py` | Mount review router |

---

## Step 1 — OCR Data Models (`core/ocr_models.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

class OCRFlagStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"      # User accepted OCR output as-is
    EDITED = "edited"          # User corrected the text
    SKIPPED = "skipped"        # User skipped — placeholder left in markdown

@dataclass
class OCRWord:
    text: str
    confidence: float          # 0.0–100.0
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2) pixel coordinates
    line_num: int
    word_num: int

@dataclass
class OCRFlag:
    flag_id: str               # UUID
    batch_id: str
    file_name: str
    page_num: int
    region_bbox: tuple[int, int, int, int]  # bounding box of flagged region
    ocr_text: str              # Tesseract's best guess
    confidence: float          # average confidence of flagged words
    corrected_text: str | None = None
    status: OCRFlagStatus = OCRFlagStatus.PENDING
    image_path: str | None = None  # path to cropped region image for review UI

@dataclass
class OCRPage:
    page_num: int
    words: list[OCRWord] = field(default_factory=list)
    flags: list[OCRFlag] = field(default_factory=list)
    full_text: str = ""
    average_confidence: float = 0.0
    image_path: str | None = None  # path to the full page image

@dataclass
class OCRConfig:
    confidence_threshold: float = 80.0   # flag words below this
    language: str = "eng"
    psm: int = 6                         # page segmentation mode
    oem: int = 3                         # OCR engine mode (LSTM)
    preprocess: bool = True              # run deskew/denoise
    unattended: bool = False             # if True, auto-accept all flags

@dataclass
class OCRResult:
    pages: list[OCRPage] = field(default_factory=list)
    total_words: int = 0
    flagged_words: int = 0
    average_confidence: float = 0.0
    flags: list[OCRFlag] = field(default_factory=list)
```

---

## Step 2 — OCR Engine (`core/ocr.py`)

### Detection: Does This Need OCR?

```python
def needs_ocr(image: Image.Image) -> bool:
```

Multi-signal detection — don't just check "is there text?" Use multiple heuristics:

1. **Text density check**: Run Tesseract in fast mode (`--psm 0` or `--oem 0 --psm 3`) and check if output is mostly empty or garbled. If extractable text < 50 chars per page, it probably needs OCR.
2. **Image entropy check**: Compute image entropy. Very low entropy (solid color, blank) → skip OCR. Medium-to-high entropy with low text extraction → needs OCR.
3. **Edge density**: Use Pillow to detect edges. Documents have structured horizontal/vertical edges (text lines, table borders). Random images (photos) have scattered edges. High structured edge density + low text extraction = scanned document.

Return a simple boolean. Log the detection signals so debugging is straightforward.

### Preprocessing

```python
def preprocess_image(image: Image.Image) -> Image.Image:
```

1. **Convert to grayscale** if not already
2. **Deskew**: Detect rotation angle (use Pillow's `ImageFilter` or compute via projection profile). Rotate to straighten. Only deskew if angle > 0.5° and < 15° (avoid over-correcting).
3. **Denoise**: Apply gentle median filter (`ImageFilter.MedianFilter(3)`)
4. **Threshold**: Adaptive threshold for binarization. Use Pillow — convert to 1-bit with `Image.convert('1', dither=0)` or Otsu-style threshold via numpy if needed.
5. **Scale**: If DPI < 200, upscale to 300 DPI equivalent. Tesseract works best at 300 DPI.

Save debug artifacts:
- `<file>_page<N>_original.png` — raw input
- `<file>_page<N>_preprocessed.png` — after preprocessing

Only save these in debug mode (`DEBUG=true` env var).

### OCR Execution

```python
def ocr_page(image: Image.Image, config: OCRConfig, page_num: int, batch_id: str, file_name: str) -> OCRPage:
```

1. Preprocess if `config.preprocess` is True
2. Run Tesseract via `pytesseract.image_to_data()` with `output_type=Output.DICT`
   - Pass `--oem {config.oem} --psm {config.psm} -l {config.language}`
3. Parse the output dict — iterate `text`, `conf`, `left`, `top`, `width`, `height`, `line_num`, `word_num`
4. Build `OCRWord` objects, skipping empty strings
5. Compute `average_confidence` for the page
6. Build `full_text` by joining words with spaces, respecting line breaks

### Confidence Flagging

```python
def flag_low_confidence(page: OCRPage, config: OCRConfig, batch_id: str, file_name: str) -> list[OCRFlag]:
```

Walk the words. Group consecutive low-confidence words into regions:

- If a word's confidence < `config.confidence_threshold`, start or extend a flag region
- Group adjacent low-confidence words on the same line into a single flag (don't flag word-by-word — that's annoying for the reviewer)
- Each flag gets: the grouped text, average confidence of the group, bounding box that encompasses all words in the group, a UUID `flag_id`
- Generate a cropped image of each flagged region from the page image, save to `output/<batch_id>/_ocr_debug/<filename>_flag_<flag_id>.png`

### Unattended Mode

If `config.unattended` is True:
- Still detect and score confidence
- Still generate flags for logging/history
- Auto-set all flags to `OCRFlagStatus.ACCEPTED`
- Don't block the pipeline waiting for review
- Log a warning: "Unattended mode: {N} low-confidence regions auto-accepted"

### Top-Level OCR Function

```python
async def run_ocr(images: list[tuple[int, Image.Image]], config: OCRConfig, batch_id: str, file_name: str) -> OCRResult:
```

- Takes a list of `(page_num, PIL.Image)` tuples
- Runs `ocr_page` on each (use `asyncio.to_thread()` since Tesseract is CPU-bound)
- Collects all flags
- Stores flags in SQLite `ocr_flags` table
- Returns `OCRResult`

---

## Step 3 — Database Schema Update (`core/database.py`)

Add `ocr_flags` table:

```sql
CREATE TABLE IF NOT EXISTS ocr_flags (
    flag_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    page_num INTEGER NOT NULL,
    region_bbox TEXT NOT NULL,          -- JSON: [x1, y1, x2, y2]
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    corrected_text TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    image_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ocr_flags_batch ON ocr_flags(batch_id);
CREATE INDEX IF NOT EXISTS idx_ocr_flags_status ON ocr_flags(batch_id, status);
```

Add helper functions:
- `insert_ocr_flag(flag: OCRFlag)`
- `get_flags_for_batch(batch_id, status=None) -> list[OCRFlag]`
- `resolve_flag(flag_id, status, corrected_text=None)`
- `resolve_all_pending(batch_id)` — bulk accept-all
- `get_flag_counts(batch_id) -> dict` — returns `{pending: N, accepted: N, edited: N, skipped: N}`

---

## Step 4 — Review API (`api/routes/review.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/batch/{batch_id}/review` | GET | List all OCR flags for batch. Query param `?status=pending` to filter. Returns flags with `image_url` pointing to the cropped region image. |
| `/api/batch/{batch_id}/review/{flag_id}` | POST | Resolve a single flag. Body: `{"action": "accept" | "edit" | "skip", "corrected_text": "..."}` |
| `/api/batch/{batch_id}/review/accept-all` | POST | Accept all remaining pending flags. |
| `/api/batch/{batch_id}/review/counts` | GET | Return `{pending, accepted, edited, skipped, total}` |

**After all flags are resolved** (no more `pending`), the conversion pipeline should automatically finalize:
- Apply corrected text to the markdown output (replace OCR text with `corrected_text` where status is `edited`)
- Replace skipped regions with `<!-- OCR_UNRESOLVED: page {N}, region {bbox} -->` placeholder
- Mark the batch conversion as complete

Add Pydantic models to `api/models.py`:

```python
class OCRFlagResponse(BaseModel):
    flag_id: str
    page_num: int
    ocr_text: str
    confidence: float
    status: str
    image_url: str             # URL to serve the cropped region image
    corrected_text: str | None

class OCRReviewAction(BaseModel):
    action: Literal["accept", "edit", "skip"]
    corrected_text: str | None = None  # required if action == "edit"

class OCRFlagCounts(BaseModel):
    pending: int
    accepted: int
    edited: int
    skipped: int
    total: int
```

---

## Step 5 — Review UI (`static/review.html`)

Simple, functional page. Loaded when a batch has pending OCR flags.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  OCR Review — batch 20260323_143000                     │
│  Reviewing flag 3 of 17                    [Accept All] │
├──────────────────────┬──────────────────────────────────┤
│                      │                                  │
│   [Original Image]   │   OCR Text (editable)            │
│   Cropped region     │   ┌──────────────────────────┐   │
│   from source        │   │ Tesseract's best guess   │   │
│                      │   │ (contenteditable or       │   │
│                      │   │  textarea)                │   │
│                      │   └──────────────────────────┘   │
│                      │                                  │
│                      │   Confidence: 62.3%              │
│                      │   Page 4, region (120,340,480,   │
│                      │   390)                           │
│                      │                                  │
├──────────────────────┴──────────────────────────────────┤
│  [Accept]    [Edit & Accept]    [Skip]    [Accept All]  │
└─────────────────────────────────────────────────────────┘
```

### Behavior

- Load flags from `GET /api/batch/{batch_id}/review?status=pending`
- Display one flag at a time
- **Accept**: POST with `action: "accept"`, advance to next flag
- **Edit & Accept**: POST with `action: "edit"` + textarea content, advance to next flag
- **Skip**: POST with `action: "skip"`, advance to next flag
- **Accept All**: POST to `/accept-all`, redirect to results page
- Progress counter updates after each action
- When no more pending flags: auto-redirect to results page
- If batch has zero flags: skip review entirely (redirect straight from progress → results)

### Image Serving

The cropped flag images are static files in `output/<batch_id>/_ocr_debug/`. Configure FastAPI to serve them:

```python
# In the review router or main.py
app.mount("/ocr-images", StaticFiles(directory="output"), name="ocr-images")
```

The `image_url` in the API response should be something like:
`/ocr-images/<batch_id>/_ocr_debug/<filename>_flag_<flag_id>.png`

---

## Step 6 — Wire OCR into Converter (`core/converter.py`)

Update `ConversionOrchestrator.convert_file()`:

For the **to_md** direction, after format detection and before markdown generation:

1. If the format handler's `ingest()` returns a `DocumentModel` with image elements that might contain text → run OCR detection on those images
2. If the input is a PDF (Phase 4 will handle this, but build the hook now):
   - The PDF handler will pass page images to `run_ocr()`
   - The OCR result gets merged into the `DocumentModel` — OCR text becomes paragraph elements
3. Read `ocr_confidence_threshold` from user preferences to build `OCRConfig`
4. Read `unattended` from the conversion request (new optional field in `ConvertRequest`)
5. If OCR produces flags with `status == PENDING` and `unattended == False`:
   - Set batch status to `"ocr_review_needed"` (new status value)
   - The pipeline pauses — markdown output is generated with placeholder text
   - After review completes (all flags resolved), a finalization step applies corrections and marks batch complete
6. If `unattended == True` or no flags: continue normally

Add to `BatchStatus` enum or status field: `"ocr_review_needed"` alongside existing `"processing"`, `"complete"`, `"error"`.

Update `FileStatus` to include `ocr_flags_total` and `ocr_flags_pending`.

---

## Step 7 — Test Fixtures

Add to `tests/generate_fixtures.py`:

```python
def generate_ocr_fixtures(fixtures_dir: Path):
```

Generate test images programmatically using Pillow:

| Fixture | What it is |
|---------|------------|
| `clean_text.png` | Black text on white background, 300 DPI, clear font — should OCR perfectly (confidence > 95%) |
| `noisy_scan.png` | Same text but with added Gaussian noise, slight rotation (2°), reduced contrast — should OCR with some low-confidence words |
| `bad_scan.png` | Heavy noise, 5° skew, low resolution (150 DPI) — should trigger many flags |
| `mixed_content.png` | Half text, half photo/illustration — OCR should only extract from the text region |
| `blank_page.png` | Solid white or light gray — should detect as "no OCR needed" |
| `table_scan.png` | Scanned table with borders and cell text — stress test for table OCR |

Render text onto images using `Pillow.ImageDraw.text()` with a system font or bundled font.

---

## Step 8 — Tests (`tests/test_ocr.py`)

### Detection tests
- `clean_text.png` → `needs_ocr()` returns True (it's an image of text, needs OCR to extract)
- `blank_page.png` → `needs_ocr()` returns False
- High-entropy photo with no text structure → `needs_ocr()` returns False (or low priority)

### Preprocessing tests
- Skewed image → after `preprocess_image()`, rotation is corrected (within 1°)
- Low-res image → after preprocessing, effective resolution is ≥ 300 DPI equivalent
- Already clean image → preprocessing doesn't degrade quality

### OCR execution tests
- `clean_text.png` → `ocr_page()` returns words with average confidence > 90%
- `clean_text.png` → `full_text` contains the rendered text (substring match)
- `noisy_scan.png` → `ocr_page()` returns words with some below threshold

### Flagging tests
- `clean_text.png` with threshold 80 → zero flags
- `noisy_scan.png` with threshold 80 → at least 1 flag
- `bad_scan.png` with threshold 80 → multiple flags
- Adjacent low-confidence words grouped into single flag (not one flag per word)
- Each flag has a valid `image_path` pointing to an existing cropped image

### Unattended mode tests
- `noisy_scan.png` with `unattended=True` → flags exist but all have status `ACCEPTED`
- Pipeline doesn't block waiting for review

### Review API tests
- `GET /review` returns pending flags with valid image URLs
- `POST /review/{flag_id}` with `accept` → flag status changes to `ACCEPTED`
- `POST /review/{flag_id}` with `edit` + corrected text → status `EDITED`, `corrected_text` stored
- `POST /review/{flag_id}` with `skip` → status `SKIPPED`
- `POST /review/accept-all` → all pending flags become `ACCEPTED`
- `GET /review/counts` returns correct totals
- Resolving all flags triggers batch finalization

### Database tests
- Flags are persisted to `ocr_flags` table
- `resolve_flag()` updates status and `resolved_at` timestamp
- `resolve_all_pending()` bulk updates all pending flags
- `get_flag_counts()` returns correct counts by status

---

## Step 9 — Update CLAUDE.md

After all tests pass:

- Set Phase 3 status to ✅ Done
- Update "Current Status" — Phase 3 complete, next Phase 4
- Add new key files (`core/ocr.py`, `core/ocr_models.py`, `api/routes/review.py`, `static/review.html`)
- Add any gotchas discovered (Tesseract quirks, Pillow preprocessing issues, etc.)
- Update test count
- Tag as `v0.3.0`

---

## Phase 3 Done Criteria

- [ ] `needs_ocr()` correctly distinguishes images needing OCR from blank/photo images
- [ ] `preprocess_image()` deskews, denoises, and upscales low-res images
- [ ] `ocr_page()` extracts text with per-word confidence scores via Tesseract
- [ ] Low-confidence words are grouped into flags, not flagged individually
- [ ] Flags stored in SQLite `ocr_flags` table with all fields
- [ ] Cropped region images generated for each flag
- [ ] Review API: list flags, resolve individual, accept-all, counts
- [ ] Review UI: side-by-side original image + editable OCR text, accept/edit/skip/accept-all buttons, progress counter
- [ ] Unattended mode: auto-accepts all flags, doesn't block pipeline
- [ ] Batch status `"ocr_review_needed"` set when flags exist and not unattended
- [ ] After all flags resolved: corrections applied to markdown, batch marked complete
- [ ] All existing Phase 1 + Phase 2 tests still pass (no regressions)
- [ ] All new Phase 3 tests pass
- [ ] `CLAUDE.md` updated, tagged `v0.3.0`
