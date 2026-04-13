# Spec B: Analysis Batch Management Page

**Date:** 2026-04-13
**Status:** Approved
**Scope:** New page + backend for managing LLM analysis batch submissions.

---

## Problem

The analysis pipeline automatically batches image files for LLM vision
processing after scan completion. There is no way to:
- See what's in each batch before it's sent to the LLM
- Pause or cancel batch submission to conserve API credits
- Exclude individual files from batches
- Preview files before they're sent for analysis

Users who want to control API spend need a way to gate batch submissions.

## Terminology

- **Analysis queue:** The `analysis_queue` table tracking files pending
  LLM vision analysis (status: pending -> batched -> completed/failed)
- **Batch:** A group of files claimed together via `claim_pending_batch()`
  with a shared `batch_id`
- **Submission:** Sending a batch to the configured LLM provider for
  vision analysis

## Design

### New Page: `/batch-management.html`

Accessible from the "batched" pipeline stat pill on the bulk/status pages
(which currently links to `/pipeline-files.html?status=batched`).

#### Layout

**Top bar:**
- Pipeline submission status: "Submitting" / "Paused" / "Idle"
- **Pause Submissions** button (toggle — becomes "Resume" when paused)
- **Cancel All Pending** button (resets all `batched` rows back to
  `pending`, clears batch assignments)
- Stats: total pending, total batched, total completed, total failed

**Batch list (main content):**

Each batch displayed as a collapsible card:

```
[Batch abc123]  12 files  |  3.4 MB  |  Pending  |  2026-04-13 10:22
  > Click to expand file list
```

Card header shows:
- Batch ID (truncated)
- File count
- Total size
- Status: Pending / Submitting / Completed / Failed
- Timestamp (batched_at)

**Expanded batch → file table:**

| Column | Source | Notes |
|--------|--------|-------|
| | (checkbox) | For bulk selection |
| Preview | thumbnail on hover | Uses existing file preview mechanism |
| Filename | basename of source_path | Click triggers browser download |
| Path | dirname of source_path | Relative to source root |
| Size | file size | Human-readable |
| Date | file modified date | From source_files |
| Type | file extension | e.g., .png, .jpg, .psd |
| | Exclude button | Per-file exclude |

**File interactions:**

- **Hover:** Shows a preview tooltip of the file (reuse existing preview
  mechanism from search page hover preview)
- **Click filename:** Triggers a browser download of the source file via
  a proxy endpoint (since source share is read-only mounted, serve via API)
- **Exclude button:** Removes the file from the batch, marks it as excluded
  in the analysis queue
- **Bulk select:** Checkbox column + "Exclude Selected" action bar

#### Exclude & Recalculate

When files are excluded (individually or in bulk):

1. Mark excluded files in analysis_queue with `status='excluded'`
2. If the batch was not yet submitted:
   - Remove excluded files from the batch
   - If remaining files < minimum batch threshold, merge with next
     pending batch
3. If the batch is mid-submission:
   - Complete the current API call (don't interrupt)
   - Skip excluded files in subsequent calls within the batch
   - Log exclusion events
4. Recalculate batch assignments for remaining pending files:
   - Re-run the batching logic (`claim_pending_batch`) to repack
   - Update the UI via polling or WebSocket

### Backend: New API Endpoints

#### Submission Control

**`POST /api/analysis/pause`**
- Sets an in-memory flag `_analysis_paused = True`
- The batch submission loop checks this flag before each batch send
- Returns `{"status": "paused"}`

**`POST /api/analysis/resume`**
- Clears the pause flag
- Returns `{"status": "running"}`

**`GET /api/analysis/status`**
- Returns `{"status": "running"|"paused"|"idle", "pending": N,
  "batched": N, "completed": N, "failed": N, "excluded": N}`

**`POST /api/analysis/cancel-pending`**
- Resets all `batched` rows back to `pending`
- Clears batch_id assignments
- Returns `{"reset_count": N}`

#### Batch Listing

**`GET /api/analysis/batches`**
- Returns list of batches with metadata:
  ```json
  [
    {
      "batch_id": "abc123",
      "file_count": 12,
      "total_size_bytes": 3456789,
      "status": "pending",
      "batched_at": "2026-04-13T10:22:00Z",
      "submitted_at": null,
      "completed_at": null
    }
  ]
  ```
- Derived from `analysis_queue` grouped by `batch_id`

**`GET /api/analysis/batches/{batch_id}/files`**
- Returns file list for a specific batch with full metadata
- Joins `analysis_queue` with `source_files` for path, size, modified date

#### File Operations

**`POST /api/analysis/exclude`**
- Body: `{"file_ids": [1, 2, 3]}` or `{"batch_id": "abc123"}` (exclude
  entire batch)
- Sets `status='excluded'` on matching rows
- Triggers batch recalculation for affected batches
- Returns `{"excluded_count": N, "batches_affected": N}`

**`GET /api/files/{source_file_id}/preview`**
- Returns a thumbnail or preview of the source file
- For images: serve a resized version (max 480px wide)
- For other files: return file metadata + icon
- Reuse existing preview infrastructure if available

**`GET /api/files/{source_file_id}/download`**
- Streams the source file to the browser as a download
- Sets `Content-Disposition: attachment; filename="..."` header
- Guards: file must exist, user must have operator+ role

### Backend: Pause Mechanism

The analysis submission loop (wherever `claim_pending_batch` is called
in a scheduled job or worker) needs a pause gate:

```python
# In the analysis worker loop:
if _analysis_paused:
    log.info("analysis.paused", msg="Submission paused by user")
    return  # Skip this cycle, scheduler will retry next interval

# Also persist the pause state as a preference so it survives restarts:
# preference key: "analysis_submission_paused" (default: "false")
```

The pause flag should be both in-memory (for immediate effect) AND
persisted as a DB preference (to survive container restarts).

### Backend: Batch Recalculation

When files are excluded from a batch:

1. Query remaining non-excluded files in the affected batch
2. If count drops below a configurable minimum (e.g., 3), merge
   remaining files into the next pending batch
3. If no other pending batches exist, create a new batch from the
   remaining files
4. Update `batch_id` assignments in `analysis_queue`

This logic lives in a new function:
`core/db/analysis.py:recalculate_batches(affected_batch_ids: list[str])`

### Navigation

- The "batched" pill on the status page and bulk page becomes a link to
  `/batch-management.html` instead of `/pipeline-files.html?status=batched`
- Add "Batches" to the nav bar (between "Files" and "Bulk Jobs") with
  `minRole: "operator"`

### Files to Create/Modify

**Create:**
- `static/batch-management.html` — new page
- `api/routes/analysis.py` — new router with all analysis endpoints

**Modify:**
- `core/db/analysis.py` — add `recalculate_batches()`, `exclude_files()`,
  `get_batches()`, `get_batch_files()`
- `core/db/preferences.py` — add `analysis_submission_paused` preference
- `api/routes/preferences.py` — add schema entry for new preference
- `static/app.js` — add "Batches" to NAV_ITEMS
- `static/status.html` — change "batched" pill href to batch-management.html
- `static/bulk.html` — change "batched" pill href to batch-management.html
- `main.py` — mount new analysis router

### Edge Cases

- **Mid-submission exclude:** If a batch is currently being sent to the
  LLM and the user excludes a file, the current API call completes
  normally. The excluded file's result is discarded when it comes back.
- **All files excluded from a batch:** Delete the empty batch record
  (or mark as `cancelled`)
- **Pause during active submission:** Current in-flight API call
  completes. No new batches are submitted until resumed.
- **Container restart while paused:** Pause state persisted as DB
  preference, so it survives restarts.
- **No batches exist:** Page shows "No analysis batches. Batches are
  created automatically after bulk conversion scans complete."
