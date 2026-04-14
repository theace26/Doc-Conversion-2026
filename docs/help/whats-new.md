# What's New

Running changelog of user-visible MarkFlow changes. Most recent
versions on top. For internal engineering detail see
[`docs/version-history.md`](../version-history.md) in the repo.

---

## v0.25.0 — EPS/vector files are now analyzed

Vector and layered image formats now work with LLM vision analysis
instead of silently failing with 400 errors:

- **`.eps` files get analyzed.** Previously, any `.eps` file queued
  for vision analysis would come back with "Could not process image"
  from Anthropic and land in the failed bucket. Now they're
  rasterized to PNG via Ghostscript (150 DPI) and analyzed normally.
  Cached renders under `/app/data/vector_cache/` so retries are
  instant.
- **`.bmp` and `.tif` / `.tiff` files get analyzed.** Same class of
  bug: small BMP/TIFF files slipped through the vision adapter's
  raw-passthrough fast path with a `image/bmp` or `image/tiff`
  MIME, which Anthropic doesn't accept. Now the adapter enforces
  an allow-list (`jpeg / png / gif / webp`) and re-encodes anything
  else via PIL before the API call.
- **Infrastructure for `.ai` and `.psd` vision analysis.** The new
  `core/vector_rasterizer.py` module supports Adobe Illustrator and
  Photoshop source files too. They're not enqueued for vision by
  default yet (the existing Adobe indexer handles them for text
  extraction), but the plumbing is in place if you want it later.

**If you had failed analysis rows**, they were flipped back to
pending automatically on upgrade and will be re-tried by the
analysis worker.

---

## v0.24.2 — Hardening pass

Mostly invisible work, but worth knowing about:

- **Database backup restore is safer.** Restoring a backup from a
  newer version of MarkFlow is now refused with a clear error
  ("schema version X is newer than this build") instead of silently
  corrupting the database. Older backups still restore and upgrade
  as before.
- **Audio/video transcription behaves better under timeout.** If a
  Whisper transcription exceeds its timeout, subsequent jobs now
  queue safely behind the still-running one rather than competing
  for the GPU. A warning is logged so you know the GPU is still busy.
- **DB diagnostic logging retired.** The temporary "DB Contention
  Logging" section on the Settings page is gone; its log files are
  no longer written. If you had it enabled, this is a nice quiet
  improvement to your log volume.

---

## v0.24.1 — AI Assist toggle feedback

Small but useful polish on the Search page AI Assist toggle.

- **Clearer on/off state.** When AI Assist is on, the button now
  fills solid with a bold **ON** pill. The previous faint-accent
  state was easy to miss.
- **Pre-search hint.** Flip the toggle on before searching and
  you'll see a one-line hint — *"AI synthesis will run on your
  next search."* — under the search box. No more wondering
  whether the toggle "took."
- **Synthesize on existing results.** Flip the toggle on after a
  search is already showing and a **Synthesize these results**
  button appears in the toolbar. Click it to run synthesis on
  what's on screen without a new search. Previously, flipping the
  toggle on after a search looked like a silent no-op.

---

## v0.24.0 — Inline file lists, DB backup/restore, batch management

A sizeable UX-focused release. Three things that previously required
leaving the page (or shelling into the server) are now one click away.

**Inline file lists on Bulk and Status pages.** The counter values
on the Bulk page and the Status page — converted, failed, skipped,
pending — are now clickable. Click any count to see the actual list
of files in that bucket right below the counters, paginated with
"Load more." No more leaving the page to pull up a search just to
figure out *which* 253 files got skipped. The list stays on the
page you scrolled to even when the Status page auto-refreshes in
the background.

**Back up and restore the database from the UI.** Admins can now
create and restore MarkFlow database backups directly from the
**DB Health** page (and there's a matching **Database Maintenance**
section on the Settings page for convenience). Restore is a
drag-and-drop modal — drop a previous backup file, confirm, and
MarkFlow swaps it in. Backups use SQLite's online backup API
under the hood, so they're safe to take while the app is under
load — you don't need to pause work first.

**Batch management page.** A new **Batch Management** page (linked
from the sidebar and from the pipeline pill on the Status page)
lists every image-analysis batch with its status and file count.
From here you can:

- **Pause new batch submissions** — the analysis worker stops
  picking up new batches while keeping in-flight work going.
  Useful for draining the queue before a restart.
- **Cancel pending batches** that haven't started yet.
- **Exclude specific files** that are crashing the worker, without
  nuking the whole batch.

**New Hardware specs help article.** The help drawer now includes a
dedicated **Hardware specs** article covering minimum and recommended
CPU / RAM / GPU / storage, plus estimated user capacity for various
deployment sizes. Useful when sizing a new deployment or deciding
whether to add a GPU.

---

## v0.23.8 — Better style fidelity, chart images, smarter OCR

**Style fidelity for duplicate content.** When the same paragraph
text appears multiple times in a document (e.g., repeated "N/A",
repeated disclaimers), MarkFlow now preserves each occurrence's
distinct formatting during round-trip conversion. Previously,
only the last occurrence's style was kept.

**PPTX chart rendering (opt-in).** Charts in PowerPoint files can
now be rendered as actual images instead of `[Chart: title]`
placeholders. Go to **Settings > Conversion Options** and set
**PPTX chart extraction** to "Render via LibreOffice." This
converts charts to PNG images using LibreOffice headless (adds
~5 seconds per chart). SmartArt shapes now produce a warning in
the conversion output.

**Smarter OCR detection.** Two new signals help MarkFlow identify
PDFs with garbage text layers — cases where text appears to exist
but is spatially corrupt or encoded incorrectly. These pages are
now automatically sent through OCR instead of producing garbled
output.

---

## v0.23.7 — Bulk vector indexing fix

A hotfix on top of v0.23.6 that restores **semantic search
coverage for files processed through a Bulk Conversion job**.

**What was broken.** In v0.23.6 every file converted through
a bulk job failed to be added to the vector index behind the
scenes. Keyword search on the Search page kept working normally
(it uses a different index), but **AI Assist**, hybrid re-ranking,
and any search that relies on meaning-based matching stopped
seeing newly-converted files from bulk jobs. Single-file
conversions on the Convert page were not affected.

The failure was silent — no error banner, no failed-job status —
because the vector indexing path runs as a background task after
each file finishes converting. The only symptom was that search
results for recently-converted content looked thinner than they
should.

**What changed in v0.23.7.** The bulk worker's concurrency
control for Qdrant upserts was rewritten to use the correct
asyncio pattern. It now correctly caps parallel vector writes at
20 at a time and waits for a free slot if the pool is saturated,
instead of crashing on every attempt.

**What you should do.** If you ran any bulk conversion jobs on
v0.23.6 and care about semantic search coverage for those files,
trigger a **Rebuild Index** from **Settings → Search** once
you're on v0.23.7. The rebuild walks every converted file and
re-indexes it to both Meilisearch and Qdrant, filling in the
vector entries that were missed. Ordinary usage from v0.23.7
forward does not need any manual action.

---

## v0.23.6 — Pre-flight checks, force-OCR, richer preview

A quality-of-life release focused on making the conversion
pipeline harder to misuse and giving operators better visibility
before a job starts.

**Pre-conversion disk-space check.** Bulk jobs and single-file
conversions now verify there is enough free space before touching
the disk. You'll see a clear error (including how much is free
and how much was needed) instead of a half-complete batch and a
cryptic IOError.

**Force OCR on every PDF page.** The Bulk page config modal gains
a new checkbox — **Force OCR on every PDF page**. Tick it when
you have PDFs with a bad or misleading text layer and you want
Tesseract to re-OCR every page regardless. There's also a
matching default in Settings under **OCR** → **Force OCR by
default** so you can set the behaviour project-wide.

**Configurable trash auto-purge.** The Settings page gains a new
toggle under **File Lifecycle** — **Auto-purge aged trash**. When
enabled (the default), a dedicated job runs daily at 04:00 local
time and permanently deletes trashed files older than the
retention window (still driven by **Trash retention (days)** in
the same section). Disable it to keep trash forever until an
admin empties it manually — useful when compliance or forensic
retention rules are involved.

**Richer preview.** The Preview button on the single-file Convert
page now returns a lot more information: estimated conversion
duration, element counts, file-size-limit and zip-bomb checks,
and a **Ready to convert** verdict. You can use it to sanity-check
a file before committing to the upload.

**Image dimensions in Markdown.** Converted Markdown now includes
image dimensions in the CommonMark attribute-list form
`![alt](src){width=640px height=480px}` when the source file
carries dimensions. Legacy `"WxH"` title syntax is still parsed
on ingest, so existing markdown files keep round-tripping
correctly.

See [Document Conversion](/help.html#document-conversion),
[Bulk Conversion](/help.html#bulk-conversion), and
[OCR Pipeline](/help.html#ocr-pipeline) for how to use the new
controls, and [Settings Guide](/help.html#settings-guide) for
where the new preferences live.

---

## v0.23.5 — Search shortcuts + startup crash fix

**Ten new keyboard shortcuts on the Search page** for faster batch
work and mouse-free navigation:

- `/` — jump focus to the search box from anywhere
- `Alt + Shift + A` — toggle **AI Assist**
- `Alt + A` — select every visible result for batch download
- `Alt + C` — clear the batch selection
- `Alt + Shift + D` — download the selection as a ZIP
- `Alt + B` — trigger **Browse All**
- `Alt + R` — re-run the current search
- `Esc` — contextual close (preview → AI drawer → modal → selection → blur)
- `Alt + Click` on a result — download the original source file directly
- `Shift + Click` on a checkbox — range-select rows

The fastest "grab everything" workflow is now three combos:
`Alt+A`, `Alt+Shift+D`. See [Keyboard
Shortcuts](/help.html#keyboard-shortcuts) and [Search](/help.html#search) for
the full writeup.

**Startup crash fix.** Fixed a pair of coupled bugs that caused
startup crash loops after upgrading from earlier releases: migration
27 (bulk_files rebuild) was running with foreign-key enforcement
on, rejecting historical orphan rows, and the MCP container was
racing the main container on migrations. Migrations now disable FK
enforcement (standard SQLite practice) and MCP no longer runs
migrations at all — it polls for DB readiness and then starts.

---

## v0.23.4 — Settings page reorganization

The Settings page is now grouped into logical clusters instead of a
flat list of 21 sections.

- **Files and Locations** now groups: Password Recovery, File Flagging,
  Info, Storage Connections
- **Conversion Options** now groups: OCR, Path Safety
- **AI Options** now groups: Vision & Frame Description, Claude
  Integration (MCP), Transcription, AI-Assisted Search

Section names: *Locations* became *Files and Locations*, *Conversion*
became *Conversion Options*, *AI Enhancement* became *AI Options*.

See the updated [Settings Reference](/help.html#settings-guide) for the
new layout.

---

## v0.23.3 — Faster heavy actions, bulk restore, extension exclude

**UX responsiveness.** Empty-trash, search-index rebuild, DB
compaction, integrity check, and stale-data check now show live
progress instead of freezing the page. Empty-trash batches deletes in
chunks of 200 so it returns immediately and shows "Purging X / Y..."
until finished.

**Bulk restore.** A new **Restore All** button on the Trash page
restores every trashed file in one action with a progress counter.

**Extension exclude list.** New **Settings → Conversion Options →
Skip file extensions** preference. Enter a list of extensions (without
dots) to exclude from scanning. Example: `tmp`, `bak`, `log`.

---

## v0.23.2 — Critical bug fixes

Background fixes to bulk upsert, the scheduler, and vision MIME
detection. No user-facing changes; listed here for completeness.

---

## v0.23.1 — Database file handler

MarkFlow now extracts and summarizes common **database files** as
Markdown, including schema, sample rows, foreign keys, and indexes.

Supported:

- **SQLite** — `.sqlite`, `.db`, `.sqlite3`, `.s3db`
- **Microsoft Access** — `.mdb`, `.accdb`
- **dBase / FoxPro** — `.dbf`
- **QuickBooks** — `.qbb`, `.qbw` (best-effort; open in QuickBooks
  Desktop and export to IIF / CSV for full extraction)

Tunable via **Settings → Conversion Options → Database sample rows
per table** (default 25, max 1000). See the
[Database Files](/help.html#database-files) article for full details.

---

## v0.23.0 — Audit remediation: pool, pipeline hardening, vision fix

Internal hardening pass: dedicated DB connection pool, pipeline
stability improvements, and a vision MIME-detection fix. No
user-visible feature changes.

---

## v0.22.19 — Scan-time junk-file filter

The scanner now skips common junk files at scan time (e.g. `.DS_Store`,
`Thumbs.db`, editor backups). They no longer clutter Pipeline Files
or consume conversion slots.

---

## v0.22.18 — Production readiness sweep

Lifecycle / vision / Qdrant / LibreOffice hardening. Background work;
nothing new visible in the UI.

---

## v0.22.17 — Overnight rebuild self-healing

New overnight rebuild script that restarts unhealthy services,
recovers from stuck scans, and leaves the container in a clean state
by morning. Useful for unattended overnight bulk jobs.

---

## v0.22.13 — Active Connections widget

The Resources page shows a live count of active connections
(SSE streams, WebSockets, AI Assist streams) so you can see at a
glance how many browsers are currently streaming from MarkFlow.

---

## v0.22.11 — Per-provider "Use for AI Assist" opt-in

You can now choose a **specific provider** for AI Assist independent
of the image-scanner provider. On **Settings → Providers**, tick
**Use for AI Assist** on any Anthropic provider you want AI Assist to
use. If nothing is ticked, AI Assist falls back to whichever provider
is currently active for the image scanner.

Today AI Assist only supports **Anthropic** providers — if your opted-in
or active provider is OpenAI / Gemini / Ollama you'll see a clear
error on the search page telling you to opt in an Anthropic provider.

---

## v0.22.2 — Toggle switch redesign

All on/off toggles across the Settings and Admin pages were redesigned
for clearer state: dimmed grey track + dot when off, lit accent track
+ dot when on, "Enabled/Disabled" label next to the switch. No
functional change — just visibly easier to read.

---

## v0.22.0 — Hybrid Vector Search ⭐

**Biggest change in this cycle.** Search now blends traditional
keyword matching (Meilisearch) with **semantic / vector search**
(Qdrant) using Reciprocal Rank Fusion.

What this means in practice:

- You can search for **concepts**, not just exact words. Searching
  "budget overrun" also finds documents that talk about "cost
  exceeded plan" or "went over the estimate."
- **Natural-language questions** work. "What is the latest safety
  policy?" is automatically normalized — the question prefix is
  stripped, temporal intent ("latest") is detected and boosts recent
  documents.
- Exact-keyword search still works the same. If you type a filename
  or a specific phrase, keyword match stays dominant.
- When vector search is down or disabled, search silently falls back
  to keyword-only — you don't see an error.

See the updated [Search](/help.html#search) article for examples and
guidance on crafting good queries.

---

## v0.21.0 — AI-Assisted Search

New **AI Assist** toggle button next to the search bar. When enabled,
every search opens a side drawer that streams a Claude-generated
answer synthesizing the top results, with inline citations `[1]`,
`[2]`, `[3]` linking back to the source documents.

- Requires an Anthropic provider (see v0.22.11 above)
- Only the top 8 search results are fed to Claude as context
- Answers are grounded in your documents — no fabricated content
- Click any citation to jump directly to the source document
- **Document Expand** — on any individual result, ask Claude for a
  deeper analysis of that single document in the context of your
  original query

See [Search](/help.html#search) for worked examples.

---

## v0.20.3 — Handwriting recognition via LLM vision

When Tesseract OCR returns very low confidence on a page (garbage
words, low word score), MarkFlow now falls back to the active
**LLM vision provider** (Claude, GPT-4V, Gemini, Ollama) to transcribe
the page directly from the image.

- Configurable threshold: **Settings → OCR → handwriting confidence
  threshold** (default 40%)
- In unattended mode, the LLM transcription automatically replaces
  Tesseract's garbled output
- In review mode, both outputs are shown side by side so you can
  accept either
- Requires an active LLM vision provider — without one, handwritten
  pages are flagged for manual review as before

---

## v0.20.2 — Binary handler expansion (30+ file types)

The binary-file handler now recognizes 30+ additional formats for
cataloging purposes (font files, CAD files, compiled binaries, etc.).
They appear in the Unrecognized Files catalog with MIME detection
instead of being ignored. Also fixes a bulk-scan gap where HEIC/HEIF
images weren't being discovered.

---

## v0.20.1 — 20 new file format handlers

MarkFlow added full conversion support for 20 additional file formats
in one release. Notable additions:

- **Rich Text**: `.rtf`
- **OpenDocument**: `.odt`, `.ods`, `.odp`
- **Web & Data**: `.html`, `.htm`, `.xml`, `.epub`
- **Data & Config**: `.json`, `.yaml`, `.yml`, `.ini`, `.cfg`, `.conf`, `.properties`
- **Email**: `.eml`, `.msg` (with recursive attachment conversion)
- **Archives**: `.zip`, `.tar`, `.tar.gz`, `.7z`, `.rar`, `.cab`, `.iso`
- **Legacy Office**: `.doc`, `.docm`, `.wpd`, `.xls`, `.ppt`

See the format table on the Convert page for the full list.

---

## v0.20.0 — NFS mount support

You can now add and manage **NFS mounts** directly from the
Settings page without editing `docker-compose.yml`. Go to
**Settings → Files and Locations → Storage Connections** and add a
new mount with the server address, export path, and local mount
point. MarkFlow handles `mount` and persistence on container restart.

---

## Related

- [Getting Started](/help.html#getting-started)
- [Search](/help.html#search)
- [Settings Reference](/help.html#settings-guide)
