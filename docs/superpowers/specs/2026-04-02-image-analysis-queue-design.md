# Image Analysis Queue — Design Spec
**Date:** 2026-04-02
**Status:** Approved

## Overview

Add LLM vision analysis to standalone image files (JPG, PNG, TIFF, BMP, GIF, EPS) via a
decoupled analysis queue. Any scan source (bulk job, lifecycle scanner) enqueues image files
as it discovers them. A background worker drains the queue in batches, sending multiple images
per LLM API call. Results (description + extracted text) are stored in the DB and indexed in
Meilisearch. Pipeline stage counts are surfaced on the Status and Admin pages.

---

## Data Model

### New table: `analysis_queue`

```sql
CREATE TABLE IF NOT EXISTS analysis_queue (
    id             TEXT PRIMARY KEY,
    source_path    TEXT NOT NULL,
    file_category  TEXT NOT NULL DEFAULT 'image',
    job_id         TEXT,
    scan_run_id    TEXT,
    enqueued_at    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    batch_id       TEXT,
    batched_at     TEXT,
    analyzed_at    TEXT,
    description    TEXT,
    extracted_text TEXT,
    provider_id    TEXT,
    model          TEXT,
    error          TEXT,
    content_hash   TEXT,
    retry_count    INTEGER NOT NULL DEFAULT 0,
    tokens_used    INTEGER              -- v0.19.2: per-file token count from LLM call
);
CREATE INDEX IF NOT EXISTS idx_analysis_queue_status      ON analysis_queue(status);
CREATE INDEX IF NOT EXISTS idx_analysis_queue_source_path ON analysis_queue(source_path);
```

**Status lifecycle:** `pending` → `batched` → `completed` | `failed`

**Deduplication:** Files are keyed on `source_path`. Enqueueing skips a file that already
has a `completed` row with the same content hash. A `failed` file with `retry_count < 3`
is automatically returned to `pending` on the next drain cycle.

**New DB module:** `core/db/analysis.py` — all helpers for this table (enqueue, dedup check,
claim batch, write results, stats query).

---

## Analysis Worker

### `core/analysis_worker.py` (new)

Registered with APScheduler alongside existing jobs (lifecycle scan, trash expiry, DB
compaction). Runs every **5 minutes**.

**Drain cycle:**

1. Check active LLM provider supports vision — skip cycle silently if not.
2. Query `analysis_queue` for up to `batch_size` `pending` rows (preference key:
   `analysis_batch_size`, default `10`).
3. Mark selected rows `batched` with a shared `batch_id` UUID and `batched_at` timestamp.
4. Call `VisionAdapter.describe_batch()` — one API call for all images in the batch.
5. Write results per row: `description`, `extracted_text`, `status=completed`, `analyzed_at`,
   `provider_id`, `model`.
6. On API failure: set `status=failed`, increment `retry_count`. Rows with `retry_count < 3`
   are reset to `pending` on the next cycle. Rows at `retry_count = 3` remain `failed`
   permanently.
7. Trigger Meilisearch re-index for completed rows so description + extracted text are
   searchable.

---

## VisionAdapter Batching

### New method: `VisionAdapter.describe_batch(images, prompt)`

Sends N images in a **single API call**. Returns a list of `BatchImageResult` objects
(one per input image, indexed to match input order).

```python
@dataclass
class BatchImageResult:
    index: int
    description: str
    extracted_text: str
    error: str | None = None
    tokens_used: int | None = None  # v0.19.2: per-image token count
```

**Per-provider implementation:**

- **Anthropic** — single `/v1/messages` call with N `image` content blocks followed by a
  `text` block instructing JSON array output:
  `[{"index": 0, "description": "...", "extracted_text": "..."}, ...]`
- **OpenAI** — single `/v1/chat/completions` call with N `image_url` content blocks + text
  prompt, same JSON array format.
- **Gemini** — single `generateContent` call with N `inline_data` parts + text prompt.
- **Ollama** — multi-image if model supports it (e.g. LLaVA). Falls back to sequential
  `describe_frame()` calls if the model rejects multiple images. Ollama batching to be
  validated during testing.

**Response parsing:** Primary path expects a valid JSON array. Fallback parser handles
plain-text responses by splitting on image separators. If parsing fails entirely, all images
in the batch are marked `failed`.

---

## Feed Points

### 1. `core/bulk_worker.py`

After an image file is successfully converted, enqueue it. Dedup check skips files already
`completed` with matching content hash. Covers all bulk jobs and auto-conversion runs.

### 2. `core/lifecycle_scanner.py`

When the scanner discovers a new image file, or detects a content-hash change on an existing
one, enqueue it. This is the primary path for images on the NAS share that were never part
of a bulk job.

**Excluded:** Single-file uploads (`api/routes/convert.py`) — out of scope. Video keyframes
(`VisualEnrichmentEngine`) — separate system, separate optimization.

---

## Pipeline Stats

### New endpoint: `GET /api/pipeline/stats`

Concurrent queries, returns the following funnel:

| Stat | Source | Query |
|---|---|---|
| scanned | `source_files` | `lifecycle_status = 'active'` |
| pending_conversion | `bulk_files` | `status = 'pending'` |
| failed | `bulk_files` + `conversion_history` | conversion failures |
| unrecognized | `unrecognized_files` | all rows |
| pending_analysis | `analysis_queue` | `status = 'pending'` |
| batched_for_analysis | `analysis_queue` | `status = 'batched'` |
| analysis_failed | `analysis_queue` | `status = 'failed'` |
| in_search_index | Meilisearch | document count across all indexes |

Meilisearch count gracefully degrades to `null` if Meilisearch is unreachable.

### UI: Status page (`/status.html`)

Compact horizontal stat strip above the job cards. Uses existing status-pill visual language.
Polls on the same interval as job cards.

### UI: Admin page (`/admin.html`)

"Pipeline Funnel" section added to the repo stats dashboard. Same data, styled to match
existing stats cards.

---

## Files Changed

| File | Change |
|---|---|
| `core/db/schema.py` | Add `analysis_queue` table + indexes, new migration |
| `core/db/analysis.py` | New — all DB helpers for `analysis_queue` |
| `core/vision_adapter.py` | Add `describe_batch()` + `BatchImageResult` dataclass |
| `core/analysis_worker.py` | New — APScheduler drain job |
| `core/scheduler.py` | Register analysis worker job (5-min interval) |
| `core/bulk_worker.py` | Enqueue image files after successful conversion |
| `core/lifecycle_scanner.py` | Enqueue new/changed image files on discovery |
| `core/search_indexer.py` | Include `description` + `extracted_text` from `analysis_queue` when indexing |
| `api/routes/pipeline.py` | Add `GET /api/pipeline/stats` endpoint |
| `static/status.html` | Add pipeline stat strip above job cards |
| `static/admin.html` | Add Pipeline Funnel section to stats dashboard |

---

## Preferences

| Key | Default | Description |
|---|---|---|
| `analysis_batch_size` | `10` | Images per LLM batch call |
| `analysis_enabled` | `true` | Kill switch — disables enqueue + drain when false |

---

## Out of Scope

- Video keyframe batching (separate optimization)
- Single-file upload analysis
- Ollama multi-image validation (deferred to testing phase)
- Analysis results shown in file viewer (follow-on feature)
