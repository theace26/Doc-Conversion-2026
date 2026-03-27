# MarkFlow Changeset: OCR Confidence Visibility & Bulk Skip-and-Review
# Show confidence scores in history/logs. Skip low-confidence files in bulk.
# Queue them for post-job human review instead of failing them.

**Version:** v1.0
**Targets:** v0.7.3 tag
**Prerequisite:** v0.7.2 tagged and complete
**Scope:** Focused changeset. Database, bulk worker, history API, history UI,
a new review queue UI. No changes to the OCR engine itself.

---

## 0. Read First

Load `CLAUDE.md` before writing anything. Pay attention to the existing OCR pipeline:
- `core/ocr.py` already computes per-page confidence scores
- `ocr_flags` table already stores low-confidence pages
- `ocr_confidence_threshold` preference already exists (default 70)
- The existing single-file review UI (`review.html`) handles per-page word-level review

This changeset builds on top of all of that. It does not replace or modify the OCR
engine, the confidence scoring math, or the existing review UI.

---

## 1. What This Changeset Does

**Problem 1 — Confidence is invisible:**
History and logs show a file as "success" or "error" but give no indication of OCR
quality. A file that converted at 40% confidence looks identical to one at 99%.

**Problem 2 — Bulk fails on low confidence:**
In bulk/unattended mode, a file below the confidence threshold currently either errors
out or gets flagged and stalls waiting for review that never comes. Neither is right
for a batch of hundreds of thousands of files.

**The fix:**

1. Record mean OCR confidence per file in the database. Surface it everywhere a file
   appears — history, logs, debug dashboard, bulk progress.

2. In bulk mode, files where the pre-scan confidence estimate is below threshold are
   **skipped** before conversion is attempted — not failed, not partially converted.
   They go into a `skipped_for_review` bucket.

3. After the bulk job completes, the UI shows a **Post-Job Review Queue** — a list of
   all skipped files with a preview, the estimated confidence, and three options per file:
   - **Convert anyway** — run conversion on this file, accept whatever quality comes out
   - **Skip permanently** — mark this file as intentionally excluded
   - **Open in OCR Review** — run conversion, then open the existing per-page word-level
     review UI for fine-grained correction

---

## 2. Database Changes

### `core/database.py` (modify)

**Extend `conversion_history` table** — add columns if they don't exist:

```sql
ALTER TABLE conversion_history ADD COLUMN IF NOT EXISTS
    ocr_confidence_mean REAL;          -- 0.0–100.0, null if no OCR was run

ALTER TABLE conversion_history ADD COLUMN IF NOT EXISTS
    ocr_confidence_min REAL;           -- lowest page confidence, null if no OCR

ALTER TABLE conversion_history ADD COLUMN IF NOT EXISTS
    ocr_page_count INTEGER;            -- pages that went through OCR, null if no OCR

ALTER TABLE conversion_history ADD COLUMN IF NOT EXISTS
    ocr_pages_below_threshold INTEGER; -- count of pages below threshold, null if no OCR
```

Note: SQLite `ALTER TABLE ADD COLUMN IF NOT EXISTS` requires SQLite 3.37+. If the target
environment may have an older SQLite, use a migration helper instead:
```python
async def _add_column_if_missing(conn, table, column, coltype):
    cols = [row[1] for row in await conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
```
Use this helper for all four new columns.

**Extend `bulk_files` table** — add columns:

```sql
-- Add to bulk_files
ocr_confidence_mean REAL        -- null if no OCR or not yet converted
ocr_skipped_reason  TEXT        -- null | 'below_threshold' | 'permanently_skipped'
```

Add `_add_column_if_missing` calls for these in the DB init path.

**New table: `bulk_review_queue`**

```sql
CREATE TABLE IF NOT EXISTS bulk_review_queue (
    id                  TEXT PRIMARY KEY,       -- UUID
    job_id              TEXT NOT NULL REFERENCES bulk_jobs(id),
    bulk_file_id        TEXT NOT NULL REFERENCES bulk_files(id),
    source_path         TEXT NOT NULL,
    file_ext            TEXT NOT NULL,
    estimated_confidence REAL,                  -- pre-scan estimate, null if unknown
    skip_reason         TEXT NOT NULL DEFAULT 'below_threshold',
                                                -- 'below_threshold' | 'scan_error'
    status              TEXT NOT NULL DEFAULT 'pending',
                                                -- pending | converted | skipped_permanently
                                                -- | converting | review_requested
    resolution          TEXT,                   -- null | 'converted' | 'skipped' | 'reviewed'
    resolved_at         TEXT,
    notes               TEXT                    -- optional user note at resolve time
);

CREATE INDEX IF NOT EXISTS idx_review_queue_job ON bulk_review_queue(job_id, status);
```

**New DB helpers:**

```python
async def add_to_review_queue(job_id, bulk_file_id, source_path,
                               file_ext, estimated_confidence, skip_reason) -> str
    """Insert into bulk_review_queue. Returns id."""

async def get_review_queue(job_id, status=None) -> list[dict]
    """Return review queue entries for a job, optionally filtered by status."""

async def update_review_queue_entry(entry_id, status, resolution=None,
                                     notes=None, resolved_at=None) -> None

async def get_review_queue_summary(job_id) -> dict
    """Returns {pending: N, converted: N, skipped_permanently: N, total: N}"""

async def update_bulk_file_confidence(file_id, ocr_confidence_mean) -> None

async def update_history_ocr_stats(history_id, mean, min_conf,
                                    page_count, pages_below) -> None
```

---

## 3. OCR Confidence Pre-Scan

### `core/bulk_worker.py` (modify)

Add a **confidence pre-scan** step before attempting conversion on PDF files in bulk mode.
The pre-scan is a lightweight check — it does not run full OCR. It estimates whether a
file is worth attempting based on a quick signal.

```python
async def _estimate_ocr_confidence(source_path: Path) -> float | None:
    """
    Quick pre-scan estimate for PDF files.
    Uses pdfplumber to check text density on the first 3 pages only.
    Returns estimated confidence 0.0–100.0, or None if not a PDF or cannot read.

    Logic:
    - If pdfplumber extracts text (chars_per_page > threshold): return 95.0
      (it's a text-native PDF, OCR probably won't be needed or will be high confidence)
    - If pdfplumber finds no text (image-only PDF):
        Run Tesseract OSD (orientation/script detection only — fast, not full OCR)
        on the first page image to get a rough script confidence.
        Return the OSD confidence value.
    - If pdfplumber fails to open: return None (unknown)

    For non-PDF files (DOCX, PPTX, XLSX, CSV): return None
    (these don't use OCR, confidence is not applicable)
    """
```

**In `BulkJob._worker()`**, before processing each file:

```python
# Only pre-scan if:
# 1. File is a PDF
# 2. OCR mode is not 'force' (force means always OCR regardless)
# 3. We're in bulk mode (single-file conversions skip this check)

if file.file_ext == ".pdf" and self.ocr_mode != "force":
    estimated_conf = await _estimate_ocr_confidence(Path(file.source_path))

    threshold = await get_preference("ocr_confidence_threshold")  # default 70

    if estimated_conf is not None and estimated_conf < float(threshold):
        # Skip this file — add to review queue instead
        await add_to_review_queue(
            job_id=self.job_id,
            bulk_file_id=file.id,
            source_path=file.source_path,
            file_ext=file.file_ext,
            estimated_confidence=estimated_conf,
            skip_reason="below_threshold"
        )
        await update_bulk_file(file.id,
            status="skipped",
            ocr_skipped_reason="below_threshold",
            ocr_confidence_mean=estimated_conf
        )
        await update_bulk_job_status(self.job_id,
            skipped=increment_by(1)  # increment counter
        )
        # Emit SSE event
        await self._emit("file_skipped_for_review", {
            "file_id": file.id,
            "source_path": relative_path(file.source_path),
            "estimated_confidence": estimated_conf,
            "threshold": threshold,
            "review_queue_total": await count_pending_review(self.job_id)
        })
        continue  # move to next file
```

For files that DO get converted, after conversion completes: if OCR was run, extract
the mean confidence from the OCR result and store it:

```python
if ocr_result:
    mean_conf = statistics.mean(
        p.confidence for p in ocr_result.pages if p.confidence > 0
    )
    await update_bulk_file_confidence(file.id, mean_conf)
    await update_history_ocr_stats(
        history_id,
        mean=mean_conf,
        min_conf=min(p.confidence for p in ocr_result.pages),
        page_count=len(ocr_result.pages),
        pages_below=sum(1 for p in ocr_result.pages
                        if p.confidence < float(threshold))
    )
```

**`bulk_jobs` table** — add a `review_queue_count` counter (use `_add_column_if_missing`):
```sql
review_queue_count INTEGER NOT NULL DEFAULT 0
```
Increment when a file is added to the review queue. Used for the "N files need review"
badge shown after job completion.

---

## 4. Single-File Conversion — Confidence Recording

### `core/converter.py` (modify)

After a single-file conversion completes and OCR was run: update the `conversion_history`
record with OCR stats. The history record is already being written — extend it.

```python
if result.ocr_result:
    pages = result.ocr_result.pages
    if pages:
        mean_conf = statistics.mean(p.confidence for p in pages if p.confidence >= 0)
        min_conf  = min(p.confidence for p in pages)
        await update_history_ocr_stats(
            history_id=history_id,
            mean=round(mean_conf, 1),
            min_conf=round(min_conf, 1),
            page_count=len(pages),
            pages_below=sum(1 for p in pages
                            if p.confidence < float(await get_preference("ocr_confidence_threshold")))
        )
```

---

## 5. History API

### `api/routes/history.py` (modify)

**`GET /api/history`** — extend each record in the response:

```json
{
  "id": "...",
  "filename": "scan.pdf",
  "status": "success",
  "format": "pdf",
  "duration_ms": 2100,
  "completed_at": "...",
  "ocr": {
    "ran": true,
    "confidence_mean": 74.3,
    "confidence_min": 41.2,
    "page_count": 12,
    "pages_below_threshold": 3,
    "threshold": 70
  }
}
```

If no OCR was run: `"ocr": null`.

Include the current `ocr_confidence_threshold` preference in the `ocr` block so the UI
can show "3 pages below threshold (70%)" without a separate API call.

**`GET /api/history/stats`** — extend:

```json
{
  "total_conversions": 312,
  "success_count": 307,
  "error_count": 5,
  "ocr_stats": {
    "files_with_ocr": 98,
    "mean_confidence_overall": 81.4,
    "files_below_threshold": 14,
    "threshold": 70
  }
}
```

---

## 6. Bulk Job API

### `api/routes/bulk.py` (modify)

**`GET /api/bulk/jobs/{job_id}`** — extend response:

```json
{
  "job_id": "...",
  "status": "completed",
  "converted": 56200,
  "skipped": 22000,
  "failed": 250,
  "review_queue_count": 847,
  "adobe_indexed": 4821,
  ...
}
```

**New endpoints:**

**`GET /api/bulk/jobs/{job_id}/review-queue`**

Returns all pending review queue entries for a job.

Query params: `status` (default `pending`), `page`, `per_page` (default 50)

```json
{
  "job_id": "...",
  "summary": {
    "pending": 847,
    "converted": 12,
    "skipped_permanently": 5,
    "total": 864
  },
  "entries": [
    {
      "id": "...",
      "source_path": "/host/c/Users/Xerxes/T86_Work/k_drv_test/scan001.pdf",
      "relative_path": "k_drv_test/scan001.pdf",
      "file_ext": ".pdf",
      "estimated_confidence": 38.4,
      "skip_reason": "below_threshold",
      "status": "pending"
    }
  ]
}
```

**`POST /api/bulk/jobs/{job_id}/review-queue/{entry_id}/resolve`**

Resolve a single review queue entry.

Request body:
```json
{
  "action": "convert" | "skip" | "review",
  "notes": "Optional note"
}
```

- `convert`: Run conversion on this file immediately (in background). Set status to
  `converting`, then `converted` when done. Use existing `ConversionOrchestrator`.
- `skip`: Set status to `skipped_permanently`. File will not appear in future job runs
  (set `bulk_files.ocr_skipped_reason = "permanently_skipped"`).
- `review`: Run conversion, then return the `review_url` for the OCR review UI
  (`/review.html?batch_id=...`). Set status to `review_requested`.

Response:
```json
{
  "entry_id": "...",
  "action": "convert",
  "status": "converting",
  "review_url": null
}
```

**`POST /api/bulk/jobs/{job_id}/review-queue/resolve-all`**

Bulk resolve all pending entries with one action.

Request body:
```json
{
  "action": "convert" | "skip",
  "notes": "Optional note"
}
```

`review` is not allowed for bulk resolve (each file needs individual review).
Returns immediately with a task count:
```json
{"queued": 847, "action": "convert"}
```
Conversions run in background. The client can poll
`GET /api/bulk/jobs/{job_id}/review-queue?status=pending` to track progress.

---

## 7. SSE — New Bulk Events

### `core/bulk_worker.py` (modify)

Add new SSE event for when review queue conversions complete (triggered from the
`resolve` endpoint, not the main job run):

```
event: review_item_converted
data: {"entry_id": "...", "source_path": "...", "status": "converted",
       "ocr_confidence_mean": 67.2, "duration_ms": 3400}

event: review_item_failed
data: {"entry_id": "...", "source_path": "...", "error": "..."}
```

After all pending review items are resolved:
```
event: review_queue_complete
data: {"job_id": "...", "converted": 830, "skipped_permanently": 17}
```

The bulk job's SSE stream (`/api/bulk/jobs/{id}/stream`) stays open after
`job_complete` until the review queue is also fully resolved. The `done` event
is only sent after both the main job and the review queue reach terminal state.

If the client disconnects and reconnects after `job_complete`, replay the
`job_complete` event and the current `review_queue_summary` immediately.

---

## 8. Frontend

### `static/history.html` (modify)

**Confidence badge on each row** — shown only for files that used OCR:

```
📄 scan.pdf     PDF    ✓    2.1s    Today    OCR 74%
📄 clean.docx   DOCX   ✓    0.8s    Today
📄 scan2.pdf    PDF    ✓    3.4s    Today    OCR 41% ⚠
```

The badge color:
- ≥ threshold: green (`--ok`)
- 60% to threshold: amber (`--warn`)
- < 60%: red (`--error`)

**Inline detail panel** — extend with OCR section when `ocr` is not null:

```
OCR
  Mean confidence:      74.3%    ████████████░░░░  [threshold: 70%]
  Lowest page:          41.2%
  Pages below threshold: 3 of 12
```

The mini progress bar is pure CSS — width proportional to confidence percentage.
Color follows the same green/amber/red rules.

**Stats bar** — extend:

```
312 conversions  ·  98.4% success  ·  avg 720ms  ·  OCR avg 81.4%  ·  14 below threshold
```

### `static/bulk.html` (modify)

**During job run — review queue counter:**

Add a line to the live stats display that appears as soon as the first file is
skipped for review:

```
Converted: 21,200  Failed: 250  Skipped: 22,000  Adobe: 1,200
⚠ Review queue: 47 files need attention after job completes
```

The review queue counter updates on every `file_skipped_for_review` SSE event.

**After job_complete — review queue prompt:**

When the main job finishes and `review_queue_count > 0`, show a prominent banner
below the job summary instead of just the "Download All" button:

```
┌─────────────────────────────────────────────────────────┐
│  ✓ Job complete — 56,200 files converted                 │
│                                                          │
│  ⚠ 847 files were skipped during conversion because      │
│  their estimated OCR confidence was below your           │
│  threshold (70%).                                        │
│                                                          │
│  These files have not been converted yet. Review them    │
│  now to decide what to do with each one.                 │
│                                                          │
│  [Review Skipped Files →]   [Convert All Anyway]        │
│  [Skip All Permanently]                                  │
└─────────────────────────────────────────────────────────┘
```

- "Review Skipped Files →" navigates to the review queue section below (or scrolls to it)
- "Convert All Anyway" calls `POST /review-queue/resolve-all` with `action: "convert"`
  (confirmation dialog first: "Convert all 847 files regardless of confidence?")
- "Skip All Permanently" calls `POST /review-queue/resolve-all` with `action: "skip"`
  (confirmation dialog: "Mark all 847 files as permanently skipped? They won't be
  converted in future runs either.")

If `review_queue_count == 0`: show normal completion summary with just "Download All".

### `static/bulk-review.html` (new page)

A dedicated page for post-job OCR review queue. Linked from the bulk job completion
banner and from the bulk job history list.

URL: `bulk-review.html?job_id=...`

Layout:
```
┌──────────────────────────────────────────────────────────┐
│  MarkFlow       [Convert] [Bulk] [Search] [History] [Settings] │
├──────────────────────────────────────────────────────────┤
│  ← Back to Bulk Jobs                                     │
│                                                          │
│  Review Queue — Job started 2026-03-21                   │
│  847 pending  ·  12 converted  ·  5 skipped permanently  │
│                                                          │
│  [Convert All Anyway]  [Skip All Permanently]            │
├──────────────────────────────────────────────────────────┤
│  Filter: [Pending ▾]                 Sort: [Confidence ▾]│
│                                                          │
│  scan001.pdf                                             │
│  Estimated confidence: 38%  ████░░░░░░░░  (threshold 70%)│
│  [Convert Anyway]  [Skip]  [Open in OCR Review]         │
│  ─────────────────────────────────────────────────────  │
│  scan002.pdf                                             │
│  Estimated confidence: 52%  █████░░░░░░░                 │
│  [Convert Anyway]  [Skip]  [Open in OCR Review]         │
│  ─────────────────────────────────────────────────────  │
│  ...                                                     │
│  ← 1 2 3 ... 17 →   (50 per page)                       │
└──────────────────────────────────────────────────────────┘
```

**Per-file actions:**

- **[Convert Anyway]**: POST to `/resolve` with `action: "convert"`. Row updates
  to show a spinner then "✓ Converted" or "✗ Failed". No page reload.
- **[Skip]**: POST to `/resolve` with `action: "skip"`. Inline confirmation:
  "Skip permanently? This file won't be processed in future runs. [Confirm] [Cancel]"
  Row updates to "Skipped permanently" and grays out.
- **[Open in OCR Review]**: POST to `/resolve` with `action: "review"`. Response
  includes `review_url`. Open that URL in a new tab.

**Confidence bar**: pure CSS, same component as history page. Color-coded.
Width = `estimated_confidence`%. Show threshold marker as a vertical tick on the bar:

```css
/* Threshold marker — positioned via CSS custom property */
.conf-bar-track::after {
    content: "";
    position: absolute;
    left: calc(var(--threshold) * 1%);
    top: 0; bottom: 0;
    width: 2px;
    background: var(--text-muted);
}
```

**Bulk actions** (top of page):
- "Convert All Anyway" — confirmation dialog, then `resolve-all` with `action: "convert"`.
  After confirming, replace the button with a progress counter: "Converting... 0 / 847".
  Update count as SSE `review_item_converted` events come in.
- "Skip All Permanently" — confirmation dialog, then `resolve-all` with `action: "skip"`.

**Empty state** (all resolved):
```
✓ All files reviewed.
  847 converted  ·  0 skipped permanently
  [Back to Bulk Jobs]
```

**SSE connection**: open `EventSource` to `/api/bulk/jobs/{id}/stream` on page load.
Listen for `review_item_converted`, `review_item_failed`, `review_queue_complete`.
Update counters and row states without reloading.

### `static/bulk.html` (modify — job history rows)

In the completed job history list, add a review queue indicator:

```
✓ COMPLETED  2026-03-21  56,200 converted  ⚠ 847 need review  [Details] [Review →]
```

"Review →" links to `bulk-review.html?job_id=...`. Only shown when `review_queue_count > 0`
and there are pending entries.

---

## 9. Navigation

Add `bulk-review.html` to the static file serving. No nav bar entry needed — it's accessed
from bulk.html, not directly. It has a "← Back to Bulk Jobs" link at the top.

---

## 10. Tests

### `tests/test_ocr_confidence_history.py` (new)

- [ ] After single-file PDF conversion with OCR, `conversion_history` record has non-null
  `ocr_confidence_mean` and `ocr_page_count`
- [ ] `GET /api/history` response includes `ocr` object for OCR'd files
- [ ] `GET /api/history` response has `ocr: null` for DOCX files (no OCR)
- [ ] `GET /api/history/stats` includes `ocr_stats` block
- [ ] `ocr_confidence_threshold` appears in each file's `ocr` block

### `tests/test_bulk_review_queue.py` (new)

- [ ] File with estimated confidence below threshold is added to `bulk_review_queue`,
  not to conversion queue
- [ ] File with estimated confidence above threshold proceeds to conversion normally
- [ ] `GET /api/bulk/jobs/{id}/review-queue` returns correct entries
- [ ] `POST /api/bulk/jobs/{id}/review-queue/{entry_id}/resolve` with `action: "convert"`
  starts conversion and updates entry status
- [ ] `POST /api/bulk/jobs/{id}/review-queue/{entry_id}/resolve` with `action: "skip"`
  sets status to `skipped_permanently`
- [ ] `POST /api/bulk/jobs/{id}/review-queue/resolve-all` with `action: "convert"`
  queues all pending entries
- [ ] `resolve-all` with `action: "review"` returns 422
- [ ] `bulk_jobs.review_queue_count` increments when files are skipped for review
- [ ] SSE stream emits `file_skipped_for_review` event with confidence and threshold
- [ ] SSE stream emits `review_queue_complete` after all entries resolved

### `tests/test_confidence_prescan.py` (new)

- [ ] Text-native PDF returns estimated confidence ≥ 95.0
- [ ] Image-only PDF returns estimated confidence from OSD (mocked Tesseract)
- [ ] Unreadable PDF returns `None` (not an error)
- [ ] Non-PDF file (DOCX) returns `None`
- [ ] Pre-scan only examines first 3 pages (assert pdfplumber not called beyond page 3)

---

## 11. Done Criteria

- [ ] `conversion_history` records include OCR stats for files that used OCR
- [ ] `GET /api/history` returns `ocr` block with mean confidence, min, page count
- [ ] History page shows confidence badge (color-coded) on OCR'd file rows
- [ ] History inline detail shows confidence bar with threshold marker
- [ ] Bulk worker skips PDFs below threshold, adds them to review queue
- [ ] `bulk_jobs.review_queue_count` is accurate after job completes
- [ ] Bulk page shows review queue counter during job run
- [ ] Bulk completion banner shows review prompt when queue count > 0
- [ ] `bulk-review.html` loads, paginates, and shows correct entries
- [ ] Per-file Convert / Skip / Open in OCR Review actions work
- [ ] Convert All Anyway and Skip All Permanently bulk actions work with confirmation
- [ ] SSE updates review queue page without reload
- [ ] Permanently skipped files are not re-queued in future job runs
- [ ] All prior tests still passing
- [ ] New tests: 25+ covering confidence recording and review queue

---

## 12. CLAUDE.md Update

After done criteria pass:

```markdown
**v0.7.3** — OCR confidence visibility and bulk skip-and-review. Confidence scores
  (mean, min, pages below threshold) recorded per file and shown in history with
  color-coded badges. Bulk mode skips PDFs below confidence threshold into a review
  queue instead of failing them. Post-job review UI (bulk-review.html) lets user
  convert anyway, skip permanently, or open per-page OCR review per file.
```

Add to Gotchas:
```markdown
- **Confidence pre-scan is an estimate**: _estimate_ocr_confidence() uses pdfplumber
  text density and Tesseract OSD — not a full OCR pass. The actual post-conversion
  confidence may differ. The pre-scan is a cheap filter, not a guarantee.

- **OSD vs full OCR confidence scales differ**: Tesseract OSD confidence is 0–100 but
  measures script/orientation detection confidence, not text recognition quality.
  It's used as a rough proxy only. Document this clearly in the review queue UI
  ("estimated" not "measured").

- **review_queue_count in bulk_jobs**: Incremented by bulk_worker when files are
  skipped for review. Not decremented when resolved — it's a total count, not a
  pending count. Use get_review_queue_summary(job_id) for current pending count.

- **SSE done event deferred until review queue resolved**: The bulk job SSE stream
  does not send the done event until both the main job and review queue are fully
  resolved. Clients that close the EventSource on job_complete will miss review
  queue events. bulk-review.html opens its own EventSource connection.

- **Permanently skipped files**: bulk_files.ocr_skipped_reason = 'permanently_skipped'
  causes get_unprocessed_bulk_files() to exclude the file on future runs. This is
  intentional — permanently skipped files never re-enter the conversion queue.
```

Tag: `git tag v0.7.3 && git push origin v0.7.3`

---

## 13. Output Cap Note

Fits in 3 turns:

1. **Turn 1**: DB schema changes + helpers, `_estimate_ocr_confidence()`,
   bulk worker skip logic, `core/converter.py` confidence recording,
   `tests/test_confidence_prescan.py`
2. **Turn 2**: History API extensions, bulk review queue API endpoints,
   SSE events, `tests/test_ocr_confidence_history.py`,
   `tests/test_bulk_review_queue.py`
3. **Turn 3**: `history.html` confidence badges, `bulk.html` review queue
   counter and completion banner, `static/bulk-review.html`,
   CLAUDE.md update, tag
