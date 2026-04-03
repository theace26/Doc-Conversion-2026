# Pipeline File Explorer — Design Spec

**Date:** 2026-04-03
**Status:** Draft
**Scope:** New `pipeline-files.html` page + clickable stat badges on status page

## Summary

Make the pipeline stats badges on the status page clickable. Each badge navigates to a new dedicated file explorer page (`pipeline-files.html`) with the clicked category pre-selected as a filter. The page uses toggle chip buttons for all 8 categories so users can view any single category or any combination. Inline row expansion shows file details, with action buttons to open the viewer or browse to the source location.

## Architecture

### Approach: Filter Bar + Table (Option A)

Single new page with:
- **Toggle chip bar** across the top — all 8 pipeline categories as clickable filter chips (multi-select)
- **Search box** — filters visible rows by path substring
- **File table** — full-width, paginated, sortable
- **Inline detail expansion** — click a row's expand arrow to reveal error messages, timestamps, skip reasons, job info
- **Row actions** — View (opens `viewer.html`), Browse (opens drive browser to file location)

### Categories

| Category | Badge ID | Data Source | Query |
|----------|----------|-------------|-------|
| Scanned | `scanned` | `source_files` | `WHERE lifecycle_status='active'` |
| Pending | `pending` | `bulk_files` | `WHERE status='pending'` |
| Failed | `failed` | `bulk_files` | `WHERE status='failed'` |
| Unrecognized | `unrecognized` | `bulk_files` | `WHERE status='unrecognized'` |
| Pending Analysis | `pending_analysis` | `analysis_queue` | `WHERE status='pending'` |
| Batched | `batched` | `analysis_queue` | `WHERE status='batched'` |
| Analysis Failed | `analysis_failed` | `analysis_queue` | `WHERE status='failed'` |
| Indexed | `indexed` | Meilisearch | Browse all 3 indexes |

**Default behavior:** Only the clicked category is active on page load. Scanned and indexed are available as filters but not pre-selected by default (they're large lists). Users can toggle them on deliberately.

## Frontend

### New file: `static/pipeline-files.html`

**URL pattern:** `pipeline-files.html?status=failed` (single category) or `pipeline-files.html?status=failed,pending` (multiple)

**Layout:**
1. Page header: "Pipeline Files"
2. Category chip bar — mirrors the stat pills from the status page, but each is a toggle button. Active chips have a highlighted border/background. Each shows its count (fetched from `/api/pipeline/stats`).
3. Search input with debounce (300ms)
4. Results count: "Showing X files"
5. Table columns:
   - Expand arrow (▶ / ▼)
   - File Path (truncated with tooltip for full path)
   - Extension
   - Size (human-readable)
   - Status (colored badge)
   - Actions (View icon, Browse icon)
6. Pagination: per-page buttons (10/30/50/100), page navigation

**Inline detail panel** (expands below row on ▶ click):
- Error message (for failed files)
- Skip reason (for skipped files)
- Last attempt timestamp
- Job ID (linked to job-detail page)
- Source mtime
- Content hash (if available)

**Row actions:**
- **View** (eye icon): Opens `viewer.html?path={source_path}` in a new tab — shows source file and converted markdown
- **Browse** (folder icon): Opens drive browser to the parent directory — constructs URL from the source path mapped to `/host/c/` or `/host/d/`

### Changes to `static/status.html`

Make each `.stat-pill` an anchor tag (or add click handler) that navigates to:
```
pipeline-files.html?status={category}
```

Add `cursor: pointer` and hover effect to stat pills.

## Backend

### New endpoint: `GET /api/pipeline/files`

**Location:** `api/routes/pipeline.py`

**Query parameters:**
- `status` (required, comma-separated): One or more of `scanned`, `pending`, `failed`, `unrecognized`, `pending_analysis`, `batched`, `analysis_failed`, `indexed`
- `search` (optional): Substring match on source_path
- `page` (default: 1)
- `per_page` (default: 50, max: 200)
- `sort` (default: `source_path`): `source_path`, `file_size_bytes`, `file_ext`, `status`
- `sort_dir` (default: `asc`): `asc` or `desc`

**Response:**
```json
{
  "files": [
    {
      "id": "abc123",
      "source_path": "/mnt/source/CONTRACTS/2024/bid-spec.xlsx",
      "file_ext": ".xlsx",
      "file_size_bytes": 2400000,
      "status": "failed",
      "error_msg": "openpyxl: Unsupported encryption method",
      "skip_reason": null,
      "source_mtime": 1712160000.0,
      "converted_at": null,
      "job_id": "0414f17...",
      "content_hash": "a1b2c3..."
    }
  ],
  "total": 42,
  "page": 1,
  "per_page": 50,
  "pages": 1
}
```

**Implementation details:**

For `scanned`: Query `source_files WHERE lifecycle_status='active'`, return file-intrinsic fields only (no job-specific data).

For `pending`, `failed`, `unrecognized`: Query `bulk_files` joined with `source_files` for file-intrinsic data. Use the most recent job's row for each file (in case of duplicates across jobs).

For `pending_analysis`, `batched`, `analysis_failed`: Query `analysis_queue` joined with `source_files`.

For `indexed`: Query Meilisearch browse endpoint across all 3 indexes (documents, adobe-files, transcripts). Map results to the same response shape. Pagination proxied to Meilisearch.

When multiple categories are selected, UNION the queries and apply search/pagination on the combined result.

### New DB helper: `get_pipeline_files()`

**Location:** `core/db/bulk.py`

Handles the SQL query construction for the SQLite-backed categories (scanned, pending, failed, unrecognized). Accepts status list, search term, pagination, sort params.

### Meilisearch browse helper

**Location:** `core/search_indexer.py` (or inline in the route)

For the `indexed` category, uses Meilisearch's document browse API to list indexed documents with pagination.

## Styling

Reuses existing MarkFlow design system:
- `.stat-pill` classes from `markflow.css` for category chips (add `.stat-pill--active` variant with border highlight)
- Table styling consistent with `job-detail.html` file list
- Inline detail panel styled like the search preview popup (dark background, subtle border)
- Action icons use the same icon approach as the search results page

## Error Handling

- If a category query fails (e.g., Meilisearch down for `indexed`), show the error inline and still display results from other active categories
- Empty results show "No files found" message with suggestion to toggle other categories
- Large result sets (scanned, indexed) show a warning banner: "Showing X of Y files — use search to narrow results"

## Navigation

- Status page stat pills become clickable links → `pipeline-files.html?status={category}`
- Pipeline files page header includes a back link → status page
- Pipeline files page is added to the nav bar (or accessible only via stat pill clicks — TBD based on nav bar space)

## Not In Scope

- Bulk actions on files (retry failed, re-index, etc.) — future enhancement
- CSV export — can be added later, same pattern as unrecognized.html
- Real-time updates via SSE — page loads data on demand, user refreshes manually
