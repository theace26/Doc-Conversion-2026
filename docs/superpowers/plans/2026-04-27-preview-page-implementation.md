# Implementation plan — `static/preview.html` (file preview page)

**Date drafted:** 2026-04-27
**Drafted by:** Claude at end of v0.31.5 ship session, written for execution in a fresh session
**Status:** Not started — ready to execute
**Estimated:** ~4-6 hours, ~700-900 LOC across 3-4 files
**Suggested release tag:** v0.32.0 (significant net-new feature; not tied to v0.31.x roadmap)

## Context recap (read this first)

The Pipeline Files page (`static/pipeline-files.html`) has a folder
icon `\u{1F4C2}` (📂) on every file row. Clicking it opens
`/static/preview.html?path=<container-path>` in a new tab. As of
v0.31.5, that page is a 19-line stub:

```html
<h1>MarkFlow — Preview</h1>
<p>This page is implemented in a later phase.</p>
<a href="/">← Back to Home</a>
```

A **separate** page `static/viewer.html` (~550 lines) already
implements the **converted-Markdown** viewer, accessed via the eye
icon `\u{1F441}` (👁️). It renders `marked` + `dompurify`-sanitized
Markdown output. **Don't touch viewer.html** — it's the
converted-output page.

`preview.html` is the **source-file inspection** page. It should
show the original file, its metadata, its conversion status, its
analysis status, and let operators navigate sibling files in the
same directory. Adjacent role to viewer.html, not a replacement.

### What clicking the folder icon should produce

The page receives `?path=<absolute container path>` (e.g.
`/host/c/11Audio Files to Transcribe/Meeting04/260324_1114.mp3`).
The `driveLink()` helper in `pipeline-files.html` already maps
`/mnt/source` → `/host/c` before navigating, so the path arriving
on `preview.html` is always under one of the host-mounted volumes
(`/host/c`, `/host/d`, `/host/root`, `/host/rw`, `/mnt/source`,
`/mnt/output-repo`, `/app/output`, `/app/logs`).

## Goal

Build a file-detail page that, given an absolute container path:

1. Renders **inline preview** of the content using the right
   browser primitive for the file's category (image / audio / video
   / PDF / text / archive listing / generic metadata).
2. Shows **metadata sidebar** — size, mtime, content hash, MIME,
   file category, conversion status, analysis status, flag status.
3. Provides **action buttons** — Download, Open in new tab, Copy
   path, Show in folder (Pipeline Files page filtered to parent
   dir), View converted Markdown (if exists, links to viewer.html),
   Re-convert, Re-analyze (if applicable).
4. Provides **sibling navigation** — Previous file / Next file in
   the parent directory, plus a collapsible list of all sibling
   files.
5. Stays **safe**: respects the path-traversal guard
   (`is_path_under_allowed_root`), refuses paths outside the
   allow-listed mount roots, never streams files larger than a
   sensible cap inline (use the existing thumbnail cache for big
   images; for huge videos use HTTP range requests via the
   browser).

## Architecture

### Backend — new router `api/routes/preview.py`

A new router because cross-cutting (touches source_files,
bulk_files, analysis_queue, flagged_files, lifecycle_events) and
keyed by absolute path rather than `source_file_id`. Don't add to
`api/routes/analysis.py` — that's analysis-specific; mixing
concerns muddies the routing layer.

Path-traversal guard reuse: `core.path_utils.is_path_under_allowed_root`
already exists. Every endpoint that accepts a `path` parameter must
call it; reject with 400 on failure.

#### `GET /api/preview/info?path=<abs>`

Single composite endpoint that returns everything the UI needs to
render. Returns `null` for absent fields rather than 404 unless the
path itself is invalid/missing (404 there).

```json
{
  "path": "/host/c/11Audio Files to Transcribe/Meeting04/260324_1114.mp3",
  "name": "260324_1114.mp3",
  "parent_dir": "/host/c/11Audio Files to Transcribe/Meeting04",
  "exists": true,
  "size_bytes": 150_000_000,
  "mtime_iso": "2026-03-24T11:14:00+00:00",
  "mime_type": "audio/mpeg",
  "extension": ".mp3",
  "category": "audio",                          // image|audio|video|document|archive|text|other
  "viewer_kind": "audio",                       // dispatch hint for the UI
  "source_file": {                              // null if not in source_files
    "id": "abc123…",
    "content_hash": "sha256:…",
    "file_size_bytes": 150000000,
    "first_scanned_at": "...",
    "last_seen_at": "...",
    "lifecycle_status": "active"
  },
  "conversion": {                               // null if no bulk_files row
    "status": "success",                        // success|failed|pending|skipped|...
    "output_path": "/app/output/...",
    "converted_at": "...",
    "error_msg": null,
    "fidelity_tier": 1,
    "skip_reason": null
  },
  "analysis": {                                 // null if no analysis_queue row
    "status": "completed",
    "description": "Recording of...",
    "extracted_text": "Speaker 1: ...",
    "provider_id": "anthropic",
    "model": "claude-opus-4-6",
    "tokens_used": 4321,
    "analyzed_at": "..."
  },
  "flags": [                                    // [] if not flagged
    {"flag_type": "ocr_review_needed", "raised_at": "...", "...": ...}
  ],
  "siblings": {                                 // first 200 entries
    "total": 47,
    "current_index": 12,
    "files": [
      {"name": "260324_1115.mp3", "path": "...", "is_dir": false,
       "size_bytes": 12345, "is_current": false}
    ]
  }
}
```

The `viewer_kind` field is a dispatch hint computed server-side so
the UI doesn't repeat the extension-classification logic. Possible
values: `"image"`, `"audio"`, `"video"`, `"pdf"`, `"text"`,
`"office_with_markdown"`, `"office_no_markdown"`, `"archive"`,
`"unknown"`.

**Performance note:** sibling listing on a directory with 100k+
files is expensive. Cap the listing at 200 entries (sorted
alphabetically), and return `total`. The UI can show
"showing 200 of 5,432" and offer pagination if needed (probably
not, this is a hover-detail page, not a full file browser).

#### `GET /api/preview/content?path=<abs>`

Streams the raw file bytes for inline display. Reuses
`FileResponse` so HTTP range requests work for video/audio (the
browser uses these for seeking). Adds correct `Content-Type` from
the file's MIME (use `python-magic` or extension-based detection,
already in `requirements.txt`).

**Caps:** if the file is > 500 MB and the requested range is
unbounded, return 413 with a "use download instead" message. The
browser sends a range header for video/audio so this only fires on
weird requests.

**Path-traversal guard:** strict. Path must resolve under one of
the mount roots.

#### `GET /api/preview/thumbnail?path=<abs>&size=400`

Same logic as the existing
`/api/analysis/files/:source_file_id/preview` thumbnail endpoint,
but path-keyed. Reuse the underlying `_generate_thumbnail_sync`
helper — refactor it out of `analysis.py` into a shared
`core/preview_thumbnails.py` module that both routes can call.
Keep the LRU cache shared too (key on path mtime + size).

#### `GET /api/preview/text-excerpt?path=<abs>&max_bytes=64KB`

For text-like files (`.txt`, `.md`, `.json`, `.csv`, `.log`, `.py`,
`.js`, `.html`, etc.). Returns the first N bytes UTF-8 decoded
(errors='replace'). Frontend renders in a `<pre>` block with
optional syntax highlighting via Prism.js (CDN, like marked is
loaded in viewer.html). Cap at 64 KB by default to keep the
response bounded; UI shows "showing first 64 KB of N MB" when
truncated.

#### `GET /api/preview/archive-listing?path=<abs>`

For archives (`.zip`, `.tar`, `.tar.gz`, `.7z`, `.rar`). Returns:

```json
{
  "format": "zip",
  "entry_count": 47,
  "uncompressed_total_bytes": 1234567,
  "entries": [
    {"name": "doc1.docx", "size_bytes": 12345, "is_dir": false,
     "modified_iso": "..."}
  ],
  "truncated": false
}
```

Cap entries at 500 to keep the response bounded. The existing
`core/archive_handler.py` and `core/archive_safety.py` modules can
do the heavy lifting; this route just exposes a read-only listing.

#### `GET /api/preview/markdown-output?path=<abs>`

Returns the converted Markdown content for the source file IF a
successful conversion exists. Looks up `bulk_files.output_path`
keyed on `source_path`, reads the file, returns
`{markdown: "...", output_path: "...", converted_at: "..."}`.
Returns 404 if no conversion exists. The frontend can use this to
render an inline "View converted output" panel without bouncing to
viewer.html — though the link to viewer.html should also be
prominent for the full Markdown experience.

### Frontend — `static/preview.html` (full rewrite)

Replace the 19-line stub with a real page (~600-800 lines). The
existing `static/viewer.html` is a great structural reference —
similar toolbar / sidebar / main-pane layout, same nav-bar
inclusion pattern, same dompurify import.

#### Page layout

```
┌──────────────────────────────────────────────────────────────┐
│ Nav bar (existing site nav)                                  │
├──────────────────────────────────────────────────────────────┤
│ Breadcrumb: /host/c › 11Audio Files to Transcribe › Meeting04│
│ Title: 260324_1114.mp3        [status pill]                  │
│ Actions: Download · Open · Copy path · Show in folder · …    │
├──────────────────────────────┬───────────────────────────────┤
│                              │ Metadata                      │
│                              │   size, mtime, hash, mime     │
│   ─── Content viewer ───     │   category, lifecycle status  │
│                              │ Conversion                    │
│   (image / audio /           │   status, output, error       │
│    video / pdf /             │   [View converted →]          │
│    text excerpt /            │ Analysis                      │
│    archive list)             │   description, ext text       │
│                              │   [Re-analyze]                │
│                              │ Flags                         │
│                              │   list                        │
│                              │ Siblings                      │
│                              │   ← prev · next →             │
│                              │   [list of files in folder]   │
└──────────────────────────────┴───────────────────────────────┘
```

#### JS structure

Wrap in an IIFE like the other admin pages. State:

```js
const state = {
  path: null,           // from ?path=
  info: null,           // /api/preview/info response
  textBuf: null,        // populated lazily for text viewer
  archiveBuf: null,     // populated lazily for archive viewer
};
```

On load:
1. Read `?path=` from URL.
2. Fetch `/api/preview/info?path=<path>`.
3. On 404 → render an error pane with "File not found at <path>".
4. On 400 → render "Path is outside allowed mount roots".
5. On success → call `renderInfoPanel(info)` and `renderViewer(info.viewer_kind)`.

#### Per-viewer dispatch (`renderViewer`)

```js
switch (info.viewer_kind) {
  case 'image':
    // <img src="/api/preview/content?path=..."> with max-width
    // For HEIC/RAW/SVG, use /api/preview/thumbnail?path=...
    // (server returns JPEG; browser renders cleanly)
  case 'audio':
    // <audio controls src="...">
  case 'video':
    // <video controls src="..."> with poster from thumbnail
  case 'pdf':
    // <iframe src="..." style="width:100%;height:80vh">
    // Browser's built-in PDF viewer
  case 'text':
    // fetch /api/preview/text-excerpt → <pre><code> with line numbers
    // Optional: Prism.js for syntax highlighting based on extension
  case 'office_with_markdown':
    // Fetch /api/preview/markdown-output → render via marked + dompurify
    // (same import block as viewer.html; copy that pattern)
  case 'office_no_markdown':
    // "This file hasn't been converted to Markdown yet."
    // [Convert now] button → POST to existing conversion endpoint
  case 'archive':
    // Fetch /api/preview/archive-listing → render as a sortable table
    // (file name / size / dir-or-not). Click a row to download just
    // that entry (separate /preview/archive-extract endpoint, future
    // enhancement).
  case 'unknown':
    // Just metadata + Download button
}
```

#### Sibling navigation

The metadata sidebar's Siblings panel:
- "← Previous: <prev-file>" link
- "Next → <next-file>" link
- Collapsible list of all siblings (capped at 200)
- Click a sibling → navigate to `?path=<sibling-path>`

Computed client-side from `info.siblings` so navigation is instant
(no extra round-trip per arrow click).

Keyboard shortcuts: `←` previous file, `→` next file, `Esc`
back to Pipeline Files page.

#### Actions panel

| Button | Action |
|--------|--------|
| Download | Direct download via Content-Disposition response |
| Open in new tab | `window.open(content_url, '_blank')` |
| Copy path | `navigator.clipboard.writeText(info.path)` |
| Show in folder | `/static/pipeline-files.html?folder=<parent_dir>` (need to teach pipeline-files.html to honor a `?folder=` filter — see "Pipeline Files folder filter" below) |
| View converted Markdown | Only enabled when `info.conversion.status == 'success'`. Opens viewer.html with the source path. |
| Re-convert | POST to existing conversion endpoint with the source path |
| Re-analyze | Only enabled if `info.analysis` is non-null. POST to `/api/analysis/queue/<id>/reanalyze` (uses the v0.31.0 delete-and-re-insert semantics). |

### Pipeline Files folder filter (small addition)

For the "Show in folder" action to work, `static/pipeline-files.html`
needs to honor a `?folder=<path>` query param that filters the
file list to entries where the `source_path` starts with `<path>`.
Small edit: ~20 LOC. Reuses the existing search box internally —
just pre-fill it with the folder path on page load.

This is genuinely useful beyond the preview page — operators
sometimes want to see "everything under this directory."

## Files to create / modify

### New files

- `api/routes/preview.py` — ~400 LOC, router with the 6 endpoints
  (`info`, `content`, `thumbnail`, `text-excerpt`,
  `archive-listing`, `markdown-output`)
- `core/preview_thumbnails.py` — refactor target. Move the
  `_generate_thumbnail_sync` / `_get_cached_thumbnail` /
  `_thumb_cache` machinery out of `api/routes/analysis.py` into
  this shared module. ~150 LOC moved + small additions for
  path-keyed cache key (currently keyed by `source_file_id`,
  needs to also support a path-only key).
- `core/preview_helpers.py` — small helper module:
  `classify_viewer_kind(path) -> str`, `get_mime_type(path) -> str`,
  `get_file_category(path) -> str`. ~80 LOC. Used by both the
  `info` endpoint and the per-content endpoints.

### Modified files

- `static/preview.html` — full rewrite, ~600-800 LOC
- `api/routes/analysis.py` — replace internal calls with the new
  shared `core/preview_thumbnails.py` module (compatibility-
  preserving — the public endpoint stays exactly as is)
- `static/pipeline-files.html` — `?folder=<path>` query param
  filter (~20 LOC)
- `main.py` — register the new `preview` router
- `core/version.py` — bump to v0.32.0
- `CLAUDE.md`, `docs/version-history.md`, `docs/help/whats-new.md`

## Implementation order

Suggested order so each step is independently testable:

1. **Refactor** the thumbnail machinery out of `analysis.py` into
   `core/preview_thumbnails.py`. Keep the existing
   `/api/analysis/files/:id/preview` endpoint working unchanged
   (verify with `curl`). This is a no-op refactor that prepares
   for path-keyed thumbnails.

2. **`core/preview_helpers.py`**: implement
   `classify_viewer_kind`, `get_mime_type`, `get_file_category`.
   Pure functions, easy to unit-test if you write tests.

3. **`/api/preview/info`** endpoint: composite metadata + status
   + siblings. This is the highest-value single endpoint. Test
   via `curl` against several known files (a converted .docx, an
   unconverted .mp3, a flagged image, a deleted file).

4. **`/api/preview/content`**: streaming bytes. Test by hitting
   it from a browser tab on an .mp3 — should get audio playback
   with seek.

5. **`/api/preview/thumbnail`**: path-keyed wrapper around the
   shared cache. Reuse all v0.31.5 dispatching (HEIC, RAW, SVG).

6. **`/api/preview/text-excerpt`** and
   **`/api/preview/archive-listing`**.

7. **`/api/preview/markdown-output`**: read the converted
   Markdown.

8. **Frontend rewrite** of `static/preview.html`. Implement
   `renderInfoPanel`, then per-viewer dispatch one type at a time
   (image first — easiest verification path). Add sibling nav
   last.

9. **Pipeline Files `?folder=` filter**: small change, but
   needed for the "Show in folder" action button to work.

10. **Doc + version bump**: CLAUDE.md, version-history.md,
    whats-new.md, admin-tools.md (if needed).

## Edge cases to handle

- **Symlinks**: resolve via `Path.resolve(strict=True)` before any
  read. Reject symlinks that resolve outside the allowed roots.
- **Permission denied**: file exists per directory listing but
  `os.stat` raises PermissionError. Show "File not readable
  (permission denied)" in the sidebar; don't 500.
- **Files modified mid-render**: the `info` response is a
  point-in-time snapshot; we don't try to keep it live. If the
  user clicks "Re-convert" and then refreshes, the new state is
  reflected.
- **Huge directories**: cap sibling listing at 200; show a
  "showing 200 of 5,432" indicator. Don't try to make the sibling
  listing a full file browser.
- **Files in archive subdirectories**: out of scope for the first
  pass. The archive listing shows entries but clicking one only
  works after a future `/preview/archive-extract` endpoint is
  added.
- **Network drives / SMB mounts**: should "just work" since the
  paths come through the same `/host/...` mounts. Performance
  may be slow for sibling listing on a big SMB share — add a
  10-second wall-clock cap on the sibling scan, return whatever
  was found if the cap fires.
- **Very large image files** (camera RAW can be 80+ MB): always
  use the thumbnail endpoint, never the content endpoint, for
  the inline `<img>`. Provide a separate "Open original" button
  that hits content.
- **Path normalization**: paths come URL-encoded. Decode once via
  `urllib.parse.unquote`, never twice. Strip trailing slashes.
- **Windows paths in the query string**: the user's machine is
  Windows but Docker passes Linux paths. The `driveLink` mapper
  already converts `/mnt/source` → `/host/c`. Should be no
  Windows path leakage, but be defensive — reject any path
  containing `\` or a drive-letter prefix (`C:`).

## Acceptance

- Click folder icon on a Pipeline Files row → preview.html opens
  in a new tab.
- An MP3 row shows an audio player that plays + seeks.
- An MP4 row shows a video player.
- A JPG / PNG row shows the thumbnail at full size (or up to
  viewport bounds).
- A HEIC / RAW / SVG row shows the v0.31.5 server-rasterized
  thumbnail.
- A PDF row shows the browser's built-in PDF viewer.
- A `.txt` / `.log` / `.py` row shows the first 64 KB in a `<pre>`.
- A `.docx` row that was successfully converted shows the
  rendered Markdown inline AND a link to viewer.html.
- A `.docx` row that hasn't been converted shows "Not converted
  yet" + a "Convert now" button.
- A `.zip` row shows the archive listing.
- Sidebar metadata accurately reflects size / hash / mime /
  conversion status / analysis status / flags.
- Action buttons work: Download streams the file, Copy path puts
  it on the clipboard, Show in folder navigates back to Pipeline
  Files filtered to the parent dir.
- Sibling nav: clicking next/prev navigates to neighbor; ←/→
  keys work.
- Path traversal: a `?path=/etc/passwd` query returns 400.

## Risks

- **Performance on huge folders**: the sibling listing is
  bounded but a big mounted SMB share still scans slowly. The
  10-second cap is the safety net.
- **Browser PDF viewer compatibility**: `<iframe>` PDF works on
  Chrome / Edge / Firefox / Safari. If a corp browser disables
  it, fall back to a download link. The frontend can detect by
  iframe load failure.
- **Office-doc rendered Markdown**: large converted docs (50 MB+
  of Markdown) may be slow to render. Same fix as viewer.html:
  cap rendered length, show "Open in viewer for full content."
- **Concurrent access**: a file being actively converted may have
  its `bulk_files.status = 'running'`. The UI should show the
  current status as of fetch time; a refresh button updates.
- **Auth**: every endpoint must be `OPERATOR+`-gated like the
  existing analysis preview / download endpoints. Don't ship an
  unauthed `/api/preview/content` — even though
  `is_path_under_allowed_root` blocks `/etc/passwd`, the
  authenticated audit trail is important.

## Out of scope (don't do these in this plan)

- Archive entry extraction / preview (clicking a file inside a
  ZIP listing). Future enhancement.
- Diff view between source and converted output. Different
  feature, would deserve its own page.
- Editing the source file in-browser. Definitely not.
- A full file-browser experience. The page is "detail for one
  file"; broader file browsing happens via the existing Pipeline
  Files / Storage pages.
- Mobile responsive layout. The page is desktop-only by design
  (operator workflow).

## Estimated effort breakdown

| Phase | LOC | Time |
|-------|-----|------|
| Refactor thumbnails into shared module | ~150 (moves) | 30 min |
| `core/preview_helpers.py` | ~80 | 20 min |
| `/api/preview/info` endpoint | ~150 | 60 min |
| `/api/preview/content` endpoint | ~80 | 30 min |
| `/api/preview/thumbnail` endpoint | ~30 (wrap) | 15 min |
| `/api/preview/text-excerpt` | ~50 | 20 min |
| `/api/preview/archive-listing` | ~80 | 30 min |
| `/api/preview/markdown-output` | ~40 | 15 min |
| Frontend `preview.html` rewrite | ~700 | 90 min |
| Pipeline Files `?folder=` filter | ~20 | 10 min |
| Docs + version bump + commit | (text) | 30 min |
| Build + verify in browser | — | 30 min |
| **Total** | **~1380** | **~6 h** |

## Pre-flight checks (run at start of execution session)

```bash
# Confirm git state
git status --short                  # should be clean
git log --oneline -3                # HEAD should be b44a7b6 or later (v0.31.5)
curl -sS http://localhost:8000/api/health | python -c "import sys,json;d=json.load(sys.stdin);print('status:',d.get('status'))"

# Confirm v0.31.5 is live (the existing /preview thumbnail endpoint
# should respond 401/403 without auth, NOT 404)
curl -sS -o /dev/null -w "%{http_code}\n" \
  http://localhost:8000/api/analysis/files/does-not-exist/preview
# Expect: 401 or 403 (auth required), NOT 404 (route missing)

# Confirm the stub preview.html still exists at the URL the
# folder icon hits
curl -sS http://localhost:8000/static/preview.html | grep -c "later phase"
# Expect: 1
```

If any pre-flight check fails, stop and investigate before
implementing — the assumptions in this plan won't hold.

## Where to test

After implementation, test against several known files on the
deployed instance:

| File type | Sample path | Expected viewer |
|-----------|-------------|-----------------|
| MP3 | `/host/c/11Audio Files to Transcribe/Meeting04/260324_1114.mp3` | Audio player |
| JPG | Pick any from the analysis_queue | Image (native) |
| HEIC | Find a phone photo in the source | Image (thumbnail) |
| MP4 | Pick any video | Video player |
| PDF | Pick any PDF | iframe |
| DOCX (converted) | Find one with `bulk_files.status='success'` | Inline Markdown + link to viewer.html |
| DOCX (not converted) | Find one with no bulk_files row | "Convert now" prompt |
| ZIP | Find a .zip in the source | Archive listing |
| TXT | Pick any plain-text file | Pre-formatted excerpt |
| Unknown | Pick a `.dat` / weird-extension file | Just metadata + Download |

## Reference: existing patterns to copy

- **viewer.html** — overall page structure, marked + dompurify
  import, sticky toolbar pattern. `static/viewer.html` lines
  1-100.
- **batch-management.html** — modal pattern (if you want one for
  per-row "View metadata" instead of a separate page; but the
  preview page is intentionally a separate page, not a modal).
- **api/routes/analysis.py** — the `_lookup_source_path` helper
  (line ~300) shows how to safely resolve a `source_file_id` to
  a Path. The new path-keyed endpoint reverses that: take a
  path, look up the source_files row by `source_path =`.
- **api/routes/log_management.py** — the `_safe_logs_path`
  function shows the path-traversal-guard pattern; do the
  same for the preview endpoints but with the broader allow-list
  of mount roots (use `core.path_utils.is_path_under_allowed_root`
  rather than rolling your own).
- **core/path_utils.py** — `is_path_under_allowed_root(path)`
  is the existing guard. Use it everywhere a `path` query param
  is accepted.
