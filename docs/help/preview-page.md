# File Preview Page

The Preview page (`/static/preview.html`) is MarkFlow's
single-file inspection surface. It is a peer of the converted-
Markdown viewer at `/static/viewer.html` — where the viewer
shows the **OUTPUT** (rendered Markdown), the preview page
shows the **INPUT** (the original file) along with everything
MarkFlow's pipeline knows about it.

> **TL;DR**
>
> Click the 📂 (folder) icon on any Pipeline Files row. The page
> opens with the file rendered inline, all DB-recorded state in
> the sidebar, and a single button — **🎙 Transcribe**, **⚙ Process**,
> or **🔍 Analyze** depending on the file type — that runs the full
> pipeline on this one file without waiting for the next tick.

---

## How to get there

| From | Action |
|------|--------|
| **Pipeline Files** (`/static/pipeline-files.html`) | Click the 📂 icon on any row's Actions column. |
| **Direct URL** | `/static/preview.html?path=<absolute container path>` — e.g., `/static/preview.html?path=/host/c/Audio/meeting04.mp3`. The path must be percent-encoded if it contains spaces or special characters. |
| **Sibling navigation** | Once on the page, press `←` / `→` to jump to the previous / next file in the same folder. |
| **Related Files / Search** | Click any result inside the Related Files or Search sidebar cards — they all open in a new tab so your current preview stays put. |

If you load the page without a `?path=` query parameter, you
get a "No file selected" placeholder with a link to Pipeline
Files. The page expects an absolute container path under one
of the allowed mount roots (`/host/c`, `/host/d`, `/mnt/source`,
`/mnt/output-repo`, `/host/rw`, `/host/root` — see your Storage
Manager configuration). Paths outside those roots return HTTP
400 from the API.

---

## Page layout at a glance

```
┌─────────────────────────────────────────────────────────────┐
│ Stale-banner (only when info changed while you were away)   │
├─────────────────────────────────────────────────────────────┤
│ Toolbar                                                      │
│   /host > c > Audio > meeting04.mp3                         │
│   meeting04.mp3       [pending]  [flagged]                  │
│   [Download] [Open in new tab] [Copy path] [Show in folder] │
│   [🎙 Transcribe] [Find related ↗]                           │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ ⚙ Transcribing (Whisper)…   12.3s              [×] │   │ ← progress card,
│   └─────────────────────────────────────────────────────┘   │   visible during
├──────────────────────────────────────┬──────────────────────┤   force-action
│                                      │ ┌──────────────────┐ │
│           Viewer pane                │ │ METADATA          │ │
│                                      │ ├──────────────────┤ │
│           (per-format render —       │ │ CONVERSION        │ │
│            <audio>, <img>, PDF       │ ├──────────────────┤ │
│            iframe, archive table,    │ │ ANALYSIS          │ │
│            rendered Markdown, etc.)  │ ├──────────────────┤ │
│                                      │ │ FLAGS (if any)   │ │
│                                      │ ├──────────────────┤ │
│                                      │ │ RELATED FILES    │ │
│                                      │ │  [Sem] [Keyword] │ │
│                                      │ ├──────────────────┤ │
│                                      │ │ SEARCH           │ │
│                                      │ │  [input]  [Sem▾] │ │
│                                      │ │  [Search] [🤖↗]  │ │
│                                      │ ├──────────────────┤ │
│                                      │ │ SIBLINGS         │ │
│                                      │ │  ← Prev   Next → │ │
│                                      │ └──────────────────┘ │
└──────────────────────────────────────┴──────────────────────┘
```

---

## Toolbar actions

The button row above the viewer renders dynamically — only the
buttons that make sense for the current file appear.

| Button | When you'll see it | What it does |
|--------|--------------------|--------------|
| **Download** | Always (disabled if file is missing on disk) | Direct file download via `Content-Disposition`. |
| **Open in new tab** | Always (disabled if file missing) | Same content URL in a new browser tab. Native browser preview if the format is recognized; download fallback otherwise. |
| **Copy path** | Always | Copies the absolute container path to the clipboard. Falls back to `document.execCommand('copy')` in non-secure contexts. |
| **Show in folder** | Always | Jumps to Pipeline Files filtered to the parent directory via `?folder=<path>`. |
| **View converted →** | Only when a successful Markdown conversion exists | Opens `/static/viewer.html` for the full converted-output experience (TOC, page-up/down, etc.). |
| **Re-analyze** | Only when an analysis row exists | DELETEs the current `analysis_queue` row and re-INSERTs a fresh one. Uses LLM tokens on the next batch. Confirmation prompt before firing. |
| **🎙 Transcribe / ⚙ Process / 🔍 Analyze** | On any recognized file type. Disabled when file is missing. | **The force-action button.** Runs the full pipeline for this one file — see "Force-process" below. |
| **Find related ↗** | Always | Opens `/search.html?q=<seed>` in a **new tab** with the file's content as the query, so your preview context stays put. |

> **Tip:** The button label tells you what's about to happen.
> If you see **🎙 Transcribe**, MarkFlow is going to run Whisper.
> If you see **⚙ Process**, it's going to run the standard
> converter (LibreOffice / PyMuPDF / etc.). If you see
> **🔍 Analyze**, it's going to send the image to the LLM
> vision pipeline. Hover the button for a tooltip with the full
> action description.

---

## Force-process this file (the file-aware button)

This is the headline feature of the v0.32.0 preview page.

### What it does

A single button kicks off the full pipeline on whatever file
you're looking at:

1. **Removes the file from `pending` / `failed` / `batched`**
   state in the relevant DB table (`bulk_files` for transcribe
   / convert, `analysis_queue` for analyze).
2. **Runs the appropriate engine** — Whisper, the converter,
   or the LLM vision pipeline.
3. **Writes the output** to the configured output directory
   (`Storage` page → Output Directory).
4. **Adds the result to the index** so it shows up in search.

You don't have to wait for the next pipeline tick (which can
be up to 5–15 minutes depending on what's queued).

### Button labels by file type

| File extension(s) | Button reads | Engine used |
|---|---|---|
| `.mp3` `.m4a` `.aac` `.ogg` `.opus` `.flac` `.wav` `.aif` `.aiff` `.wma` `.amr` etc. | **🎙 Transcribe** | Whisper (CUDA when available) |
| `.mp4` `.m4v` `.mov` `.webm` `.mkv` `.avi` `.wmv` `.flv` `.3gp` `.mpg` etc. | **🎙 Transcribe** | Whisper (extracts audio first) |
| `.docx` `.doc` `.dotx` `.xlsx` `.xls` `.pptx` `.ppt` `.odt` `.ods` `.odp` `.rtf` `.epub` | **⚙ Process** | LibreOffice + handler |
| `.pdf` | **⚙ Process** | PyMuPDF + OCR fallback |
| `.txt` `.md` `.csv` `.json` `.yaml` `.py` `.js` `.html` and ~50 other text/code/config types | **⚙ Process** | text handler |
| `.zip` `.tar` `.tar.gz` `.7z` `.rar` etc. | **⚙ Process** | archive walker |
| `.jpg` `.png` `.heic` `.tif` `.psd` `.eps` `.svg` plus ~30 RAW formats | **🔍 Analyze** | LLM vision (active provider) |
| `.exe`, `.dll`, unknown blobs | *button hidden* | none |

The dispatcher is a single function in
`core/preview_helpers.py:pick_action_for_path()`. You can edit
that file to remap an extension if your operator preference is
different (e.g., send `.psd` to analyze instead of process).

### Live progress card

Click the button → a card slides in below the action buttons:

```
┌─────────────────────────────────────────────────┐
│ ◐  Transcribing (Whisper)…              12.3s  │
└─────────────────────────────────────────────────┘
```

- **Spinner + phase label** — `Queued → Preparing the row →
  Transcribing (Whisper)… → Indexing the result → Transcribed ✓`
- **Live elapsed-time ticker** — updates every 100 ms,
  decoupled from the 2 s HTTP poll interval, so the timer
  feels real-time.
- **On success** — card turns green, shows the output path,
  Dismiss button. The page **re-fetches `/info`** so the
  sidebar Conversion / Analysis cards repopulate. For audio /
  video, a **transcript pane is appended below the audio
  player** with the converted Markdown.
- **On failure** — card turns red with the error message and
  a Dismiss button. The action button re-enables for retry.

### Re-entrancy

If you click the button while a prior run for the same file
is still in-flight, the backend returns HTTP 409 with the
current state. The error UI tells you why; the original
progress card stays visible. This protects against
accidentally double-firing an expensive operation (Whisper
on a 1-hour meeting recording costs real time).

### Example workflows

#### Transcribe a stuck audio file

1. Pipeline Files shows `meeting04.mp3` with status **PENDING**
   for hours — the bulk pipeline hasn't gotten to it because
   the queue is huge.
2. Click the 📂 icon. Preview page opens.
3. Click **🎙 Transcribe**. Progress card appears:
   *"Transcribing (Whisper)… 0.5s"* → *14.2s* → *2m 11.0s*.
4. (1-hour meeting on a GTX 1660 Ti runs ~10–20 min.)
5. When done: green card, output path
   `/mnt/output-repo/Audio/meeting04.md`. The Conversion
   sidebar card shows ✅ Success.
6. Below the audio player, a Transcript pane appears with the
   speaker dialog. Highlight any phrase to search related
   files.

#### Force-analyze a phone photo

1. Open a `.heic` from a phone backup folder.
2. Click **🔍 Analyze**. Card shows
   *"Analyzing (LLM vision)… 8.4s"*.
3. The Analysis sidebar card populates with the LLM
   description ("A close-up of a hand-written meeting agenda
   with bullet points listing…") and any extracted text.
4. Related Files re-runs using the new description as the
   query — other photos of agendas / handwritten notes
   surface in the list.

#### Force-process a single Office doc

1. Open a `.docx` whose Conversion sidebar shows **pending**.
2. Click **⚙ Process**. Card runs for ~5 s (~30 s for
   complex docs with tables/images).
3. The viewer pane flips from "Not yet converted" to the
   rendered Markdown inline. The "View converted →" toolbar
   button appears.

### When the button is hidden vs. disabled

| Situation | Button state |
|-----------|--------------|
| File extension recognized AND file exists on disk | **Enabled** with `🎙 Transcribe` / `⚙ Process` / `🔍 Analyze` label. |
| File extension recognized AND file is missing on disk | **Disabled**, tooltip: *"File not found on disk — cannot transcribe until the file is restored."* |
| File extension NOT mapped to any pipeline (e.g. `.exe`) | **Hidden**. Nothing actionable for MarkFlow to do. |

---

## Sidebar — what each card shows

### Metadata
- **Size** — file size in bytes (prettified).
- **Modified** — `mtime` from the filesystem.
- **MIME** — best-effort MIME detection (extension overrides
  for HEIC, AVIF, Opus, etc.).
- **Extension** — the file extension, lowercased.
- **Category** — coarse bucket: `image / audio / video /
  document / archive / text / other`.
- **Viewer** — viewer dispatch hint that drove the main pane:
  `image / audio / video / pdf / text / office_with_markdown
  / office_no_markdown / archive / unknown`.
- **Lifecycle** — `active / marked_for_deletion / in_trash /
  purged` (from `source_files`).
- **Hash** — first 16 chars of the content SHA-256.

### Conversion
Pulled from the most-recent `bulk_files` row for this path:
status pill, `converted_at`, output filename (hover for full
path), error message if it failed.

### Analysis
Pulled from the latest `analysis_queue` row: status,
`analyzed_at`, provider, model, tokens used, the LLM-generated
description, and any extracted text. Empty for non-image files
(image-class only).

### Flags
Active operator-raised file flags (file_flags table). Card
hidden when there are no active flags. Each entry shows the
reason, optional note, who flagged it, and when.

### Related Files (auto-populated)
Tab-switchable similar-file list:

- **Semantic** (default) — vector search via Qdrant. Finds
  files with similar **meaning** even when the words differ.
- **Keyword** — Meilisearch full-text. Faster, but matches
  literal terms.

The query is **derived from the file's own content** in this
priority order:

1. Converted Markdown excerpt (first 1000 chars) — works for
   audio/video transcripts and Office docs.
2. Analysis description — for images, the LLM-generated
   summary captures the semantic content.
3. Filename stem + parent directory name — fallback for
   unprocessed files.

Each result shows:
- File name (clickable; opens that file's preview in a new
  tab so your current view stays put)
- Source format
- File size
- Score (semantic only — typically 0.30 ≤ score ≤ 0.70)
- Full path on hover

The card shows up to 10 results. For more, click **Full
search ↗** in the card header — it opens `/search.html` in a
new tab seeded with the same query.

### Search (typed query)
Free-form similarity search:

- **Search input** — type any phrase or sentence. Supports
  natural-language ("contracts mentioning union dues") for
  Semantic mode and term-based ("union dues 2024") for
  Keyword mode.
- **Mode dropdown** — Semantic (Qdrant) or Keyword (Meili).
- **Search** button — runs the query (or just press Enter).
- **🤖 AI Assist ↗** — opens `/search.html?q=<seed>&ai=1` in
  a new tab. AI Assist *deliberately* does NOT auto-fire
  here — every preview-page open would burn LLM tokens. The
  synthesize action is operator-initiated.

### Siblings
Files in the same folder, sorted alphabetically. **← Prev**
and **Next →** buttons jump to the previous/next file (also
bound to the `←` / `→` keyboard shortcuts). Clickable list
of all siblings (capped at 200 entries; bigger folders show
a "showing 200 of 1,247" note). Directory entries appear
with a 📁 prefix and link to Pipeline Files filtered to that
folder.

---

## Selection-driven search (highlight chip)

Highlight any text in the file viewer / transcript pane /
analysis description / any related-files list. A small
floating chip appears at the cursor with three options:

| Chip option | What it does |
|---|---|
| **🧠 Semantic** | Sets the Search panel input to your highlighted text and runs a semantic search. Results render in the Search card below. |
| **🔎 Keyword** | Same, but Meilisearch keyword. |
| **🤖 AI ↗** | Opens `/search.html?q=<selection>&ai=1` in a new tab with AI Assist enabled. |

The chip auto-hides on `Escape`, click outside, scroll, or
window resize. Position is computed from the selection's
bounding rect; the chip flips below the selection if it would
otherwise be clipped at the top of the viewport.

### Example — pull on a thread in a transcript

1. You're reading the transcript of a board meeting in the
   audio file viewer.
2. You highlight the phrase *"resolution for trans
   healthcare."*
3. The chip appears. Click **🧠 Semantic**.
4. The Search panel below populates with other files
   discussing similar topics — meeting minutes, draft
   resolutions, related correspondence.
5. Click any result; it opens in a new tab. Your transcript
   stays exactly where you left it.

---

## "Page refreshed" banner

If you switch away from a preview tab and a force-action /
pipeline tick changes the underlying file's state in the
meantime, the page detects it on focus and:

1. **Re-fetches** the file info,
2. **Re-renders** the sidebar / viewer,
3. **Shows a blue banner** at the top:
   *"This file changed while you were away — page refreshed
   with the latest data."*

The banner auto-dismisses after 12 seconds, or you can click
the × to close it sooner. The banner is suppressed during
your own in-progress force-action so it doesn't show up for
your own work.

How it works under the hood: `/api/preview/info` returns an
`info_version` field — a 16-char hash of the fields an
operator would notice changing (status, output path,
description, flags). The frontend stores it on initial load
and compares on `visibilitychange`.

---

## Keyboard shortcuts (Preview Page only)

| Key | Action |
|-----|--------|
| `←` (Left Arrow) | Jump to previous file in same folder |
| `→` (Right Arrow) | Jump to next file in same folder |
| `Esc` | Jump back to Pipeline Files filtered to the parent folder |
| `Enter` (focused on Search input) | Run the typed search |
| `Ctrl+Shift+R` | Hard reload (bypasses cache; useful after a MarkFlow update) |

The `←` / `→` shortcuts work from anywhere on the page
(except inside an `<input>` / `<textarea>` / `<select>` —
those eat the keystroke for cursor movement).

---

## API reference (curl examples)

All endpoints are **OPERATOR+ gated** and require either a
session cookie or an `X-API-Key` header.

### Preview info (composite metadata)

```bash
curl -sX GET 'http://localhost:8000/api/preview/info?path=/host/c/Audio/meeting04.mp3' \
  -H "X-API-Key: $MARKFLOW_API_KEY" | jq
```

Response includes: file stats, `source_files` row, latest
`bulk_files` row, latest `analysis_queue` row, active flags,
sibling listing, `viewer_kind`, `action`, `info_version`.

### Stream raw bytes

```bash
# Direct download (saves to local file)
curl -sX GET 'http://localhost:8000/api/preview/content?path=/host/c/Audio/meeting04.mp3' \
  -H "X-API-Key: $MARKFLOW_API_KEY" -o meeting04.mp3

# Range request (browsers send this automatically for <audio> seeking)
curl -sX GET 'http://localhost:8000/api/preview/content?path=/host/c/Audio/meeting04.mp3' \
  -H "X-API-Key: $MARKFLOW_API_KEY" \
  -H "Range: bytes=0-1023" -o first-1k.bin
```

### Server-rendered thumbnail (for non-browser-native images)

```bash
curl -sX GET 'http://localhost:8000/api/preview/thumbnail?path=/host/c/Photos/scan001.tif' \
  -H "X-API-Key: $MARKFLOW_API_KEY" -o scan001.jpg
```

### Text excerpt (first 64 KB by default; max 512 KB)

```bash
curl -sX GET 'http://localhost:8000/api/preview/text-excerpt?path=/host/c/Logs/app.log&max_bytes=131072' \
  -H "X-API-Key: $MARKFLOW_API_KEY"
```

### Archive listing (zip / tar / 7z; capped at 500 entries)

```bash
curl -sX GET 'http://localhost:8000/api/preview/archive-listing?path=/host/c/Backups/2024.zip' \
  -H "X-API-Key: $MARKFLOW_API_KEY" | jq
```

### Force-process a file (file-aware action)

```bash
curl -sX POST 'http://localhost:8000/api/preview/force-action' \
  -H "X-API-Key: $MARKFLOW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"path": "/host/c/Audio/meeting04.mp3"}'
```

Response:
```json
{
  "path": "/host/c/Audio/meeting04.mp3",
  "action": "transcribe",
  "state": "queued",
  "message": "Scheduled transcribe for meeting04.mp3"
}
```

### Poll force-action status

```bash
# Poll every ~2 s while in-flight
curl -sX GET 'http://localhost:8000/api/preview/force-action-status?path=/host/c/Audio/meeting04.mp3' \
  -H "X-API-Key: $MARKFLOW_API_KEY" | jq
```

Response (mid-run):
```json
{
  "path": "/host/c/Audio/meeting04.mp3",
  "state": "running",
  "phase": "running",
  "action": "transcribe",
  "started_at": "2026-04-27T19:52:14.123456+00:00",
  "updated_at": "2026-04-27T19:54:33.987654+00:00",
  "elapsed_ms": 139864
}
```

Response (after success):
```json
{
  "path": "/host/c/Audio/meeting04.mp3",
  "state": "success",
  "phase": "success",
  "action": "transcribe",
  "started_at": "2026-04-27T19:52:14.123456+00:00",
  "finished_at": "2026-04-27T19:58:42.111111+00:00",
  "elapsed_ms": 388000,
  "output_path": "/mnt/output-repo/Audio/meeting04.md"
}
```

### Find related files (semantic)

```bash
curl -sX GET 'http://localhost:8000/api/preview/related?path=/host/c/Audio/meeting04.mp3&mode=semantic&limit=10' \
  -H "X-API-Key: $MARKFLOW_API_KEY" | jq
```

Response (snippet):
```json
{
  "path": "/host/c/Audio/meeting04.mp3",
  "mode": "semantic",
  "query_used": "Meeting opened at 7:02 PM. Brother Jones moved to approve...",
  "derived": true,
  "results": [
    {
      "path": "/host/c/Audio/meeting03.mp3",
      "name": "meeting03.mp3",
      "score": 0.521,
      "snippet": "Meeting opened at 7:00 PM. Brother Smith moved..."
    },
    ...
  ],
  "warning": null
}
```

### Find related files (keyword override)

```bash
curl -sX GET 'http://localhost:8000/api/preview/related?path=/host/c/Audio/meeting04.mp3&mode=keyword&q=union+resolution&limit=5' \
  -H "X-API-Key: $MARKFLOW_API_KEY" | jq
```

### Converted Markdown for a file (404 if no successful conversion)

```bash
curl -sX GET 'http://localhost:8000/api/preview/markdown-output?path=/host/c/Documents/contract.docx' \
  -H "X-API-Key: $MARKFLOW_API_KEY"
```

---

## Common workflows

### Triaging a flagged file

1. Open the file from the Pipeline Files page.
2. Read the **Flags** card to see the reason (e.g.,
   "low OCR confidence").
3. Use the **viewer pane** to see the actual contents.
4. Decide:
   - If the file is actionable, click **🎙 Transcribe / ⚙ Process**
     to retry conversion.
   - If the file should be deleted from MarkFlow's tracking,
     use the trash workflow on the search page.

### Comparing similar transcripts

1. Open a meeting transcript from `/static/preview.html?path=…`.
2. The **Related Files** card auto-populates with semantically
   similar files (other meeting transcripts).
3. Open 2–3 of the top hits in new tabs (each click opens a
   new tab automatically).
4. Compare side-by-side using your browser's tab switcher.

### Verifying a re-conversion worked

1. Open a file whose Conversion sidebar shows **failed**.
2. Click **⚙ Process**. Watch the progress card.
3. On success, the **Conversion** card flips to ✅ green.
4. Click **View converted →** to see the rendered Markdown
   in the full viewer.

### Finding context for a phrase you noticed

1. While reading a transcript or description, **highlight**
   a phrase that catches your eye.
2. The selection chip appears.
3. Click **🧠 Semantic** to find files with similar meaning
   (or **🔎 Keyword** for literal-term matches).
4. Results render inline in the **Search** card.
5. Click any result — opens in a new tab.

---

## Troubleshooting

### "I don't see the 🎙 Transcribe button"

Possible causes (in order of likelihood):

1. **Frontend is cached** — try `Ctrl+Shift+R` to hard-reload
   the page.
2. **Backend hasn't been restarted** with the v0.32.0 force-
   action support. The frontend has a client-side fallback
   that derives the action from the file extension, but if
   neither side has the change you'll see the old layout.
   Restart with `docker-compose build && docker-compose up -d`.
3. **The file extension isn't mapped to any pipeline** —
   e.g., a `.exe` or unknown blob. By design the button is
   hidden because there's nothing actionable for MarkFlow to
   do. Check `core/preview_helpers.py:pick_action_for_path()`
   if you think your extension *should* be supported.

### "I see the button but it's disabled"

The file is **missing on disk**. The registry has a row for
it but MarkFlow can't read the bytes. Common causes:

- The file was moved or renamed since the last source scan.
- A network share was unmounted.
- The file was deleted out-of-band.

Once the file is restored on disk, the button re-enables on
the next page load.

### "I clicked Transcribe and nothing happens"

If the progress card doesn't appear, open the browser
DevTools console (F12 → Console). Common errors:

- **404 on `/api/preview/force-action`** — the backend is
  running an older version. Rebuild:
  `docker-compose build && docker-compose up -d`.
- **403 / 401** — your session expired. Refresh the page.
- **409** — a prior force-action for this path is still in
  flight. Wait for it to complete; the existing progress
  card should still be visible (try scrolling up).

### "Transcribe completes but the audio viewer doesn't show a transcript"

Two likely causes:

1. The conversion **status** isn't `success` — check the
   Conversion sidebar card for an error message.
2. The **output file path** in `bulk_files` doesn't exist on
   disk. The transcript pane endpoint
   (`/api/preview/markdown-output`) returns 404 in that case.
   Look at the Conversion card; if `output_path` is set but
   the file is gone, something deleted it after conversion.

### "Related Files shows 'Search index is unavailable'"

Meilisearch isn't running or isn't reachable. Check:

```bash
docker ps | grep meilisearch
curl http://localhost:7700/health
```

Restart with `docker-compose up -d meilisearch` if needed.

### "Related Files (semantic mode) shows 'Vector backend is offline'"

Qdrant isn't running. Check:

```bash
docker ps | grep qdrant
curl http://localhost:6333/healthz
```

Vector search is **best-effort** by design — the rest of the
preview page works fine without Qdrant; you just lose the
semantic search mode. Use Keyword mode as a fallback.

---

## Related Articles

- [Searching Your Documents](/help.html#search) — full search
  page guide
- [Bulk Repository Conversion](/help.html#bulk-conversion) —
  full pipeline that this page lets you trigger one-at-a-time
- [Auto-Conversion](/help.html#auto-conversion) — the
  background pipeline this page bypasses
- [Keyboard Shortcuts](/help.html#keyboard-shortcuts) — full
  shortcut reference including this page
- [Troubleshooting](/help.html#troubleshooting) — general
  troubleshooting
