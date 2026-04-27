# What's New

Running changelog of user-visible MarkFlow changes. Most recent
versions on top. For internal engineering detail see
[`docs/version-history.md`](../version-history.md) in the repo.

---

## v0.31.4 — One-click bulk download as a single ZIP bundle

The Batch Management page's multi-file download used to fire off
one synthetic anchor click per file with a 120 ms gap between
each. Browsers prompted you to "allow multiple downloads" the
first time, then dumped N items into the download manager. Above
100 files the UI refused entirely.

v0.31.4 replaces that with **one POST to a new bundle endpoint**.
The server packages every selected file into a ZIP in a worker
thread, streams it back, and you get a single `markflow-files-<TS>.zip`
in your downloads. No more "allow multiple downloads" prompt, no
more 30+ items in the download manager.

### What changed for you

- Cap raised from **100 to 500 files** per click.
- New ~2 GiB **uncompressed-bytes ceiling**. If your selection
  totals more than that on disk, the server returns a 413 with a
  "split into smaller batches" hint. Pick a tighter slice and try
  again.
- **Smart compression**: already-compressed files (JPEG, MP3, MP4,
  ZIP, PDF, DOCX, etc.) are stored uncompressed inside the ZIP
  so we don't burn CPU re-compressing entropy-saturated bytes.
  Other files use deflate.
- **Duplicate names** in your selection (two files named
  `report.pdf` from different folders) get auto-suffixed inside
  the ZIP so nothing gets silently overwritten.
- **Partial bundle**: if a file in your selection has been deleted
  or moved since you scrolled past it, the bundle still
  completes — that file is skipped, and the toast reads
  "Downloaded bundle of N files (1 skipped — missing or
  unreadable)".
- **Single-file fast path**: if you select exactly 1 file, the
  download skips the bundle endpoint entirely and uses the direct
  URL — same speed as before for the one-file case.

---

## v0.31.2 — OpenAI / Gemini / Ollama get full vision-API resilience

If you're using **OpenAI**, **Gemini**, or **Ollama** as your
active vision provider, the same five-layer safety net that
**Anthropic** users have had since v0.29.9 now applies to your
batches too. You don't need to do anything — switching to any
of these three providers automatically picks it up.

### What it protects against

| Failure mode | Before | After |
|---|---|---|
| One corrupt JPG in a batch of 10 | All 10 fail with HTTP 400 | The corrupt one fails; other 9 succeed |
| Provider hits a temporary rate-limit (429) | Whole batch fails | Each call is retried up to 4 times with exponential backoff (1, 2, 4, 8 s) |
| Provider returns 500/502/503/504 transiently | Whole batch fails | Same retry loop, with `Retry-After` honored when present |
| Provider has an outage | Every batch wastes API spend on doomed calls | After 5 consecutive upstream failures the **circuit breaker** opens for 60s+; subsequent calls short-circuit until the cooldown elapses |
| File on disk is corrupt or wrong format | Round-trip to provider, 400 back, no useful info | Pre-flight check rejects it locally with a `[preflight]` reason in the analysis row |

### Concrete example

Imagine you're using **OpenAI** to analyze a batch of 8 images,
and a transient OpenAI outage causes 429 responses for 30
seconds:

- **Before v0.31.2**: All 8 images fail. The analysis worker
  records `[HTTP 429: ...]` for each row. You retry manually
  later.
- **After v0.31.2**: The first call returns 429. The retry
  loop waits 1 second (or whatever `Retry-After` says, if
  OpenAI sent one), then tries again. If it 429s again, wait
  2 seconds. After up to 4 attempts, success or failure is
  recorded. Meanwhile the circuit breaker is counting
  consecutive failures — if you somehow hit 5 in a row,
  subsequent batches short-circuit so you don't burn a quota
  budget on 30 more failed calls.

### The operator banner

If the breaker opens, a red banner appears at the top of the
**Batch Management** page — same banner that's been there
since v0.29.9 for Anthropic outages. It shows the consecutive
failure count, the cooldown remaining, and a **Reset breaker**
button (Manager+ role required). Click Reset after you've
manually verified the upstream issue is fixed if you don't
want to wait out the cooldown.

### Cross-provider note

The breaker is **process-wide**. If you're mid-experiment
switching from OpenAI (which just had an outage) to Anthropic,
the first Anthropic call may short-circuit because the breaker
hasn't reset yet. Click **Reset breaker** on the banner to
bypass the cooldown immediately. (Or wait — the cooldown is
60 seconds the first time it opens, doubling on each
re-trigger up to 15 minutes.)

---

## v0.31.1 — `.7z` viewer safety controls: tunable cap, host snapshot, live search spinner

### Operator-tunable `.7z` byte cap

The 200 MB safety cap on `.7z` log search (introduced in v0.31.0)
is now configurable from the Log Management → Settings card.
Default still 200 MB; you can set it anywhere from **1 MB up to
4096 MB**. This bounds how much of a `.7z` archive the search
actually decompresses before truncating, which keeps a runaway
search from pinning a worker thread for hours on a giant archive.

**Why change it?** Two scenarios drive this:

- **You routinely search `.7z` archives bigger than 200 MB** —
  raise the cap so the search returns full results instead of
  the truncation warning. Useful when investigating an incident
  that spans a long time window the archive covers.
- **You have a tight-RAM host and want a smaller blast radius**
  — lower the cap to 50 or 100 MB.

**Examples:**

| Host | Typical archive | Suggested cap |
|------|-----------------|---------------|
| Workstation with 64 GB RAM, archives < 200 MB | leave at default | 200 MB |
| Same host but archives are 500-800 MB compressed | bump up | 1024 MB |
| VM with 8 GB RAM, mostly small/medium archives | conservative | 200 MB |
| VM with 4 GB RAM and the search worker is competing with the bulk worker | tighten | 100 MB |
| Investigating a single huge archive once (one-shot) | crank, search, then drop back | 4096 MB → re-run → 200 MB |

The UI shows an **amber warning** above 1024 MB OR if your cap
would consume more than 50% of currently-free RAM, and a **red
error** above 4096 MB (the backend hard limit). When the search
truncates because the cap fired, the status line reads
`reader: 7z stream truncated at NNN MB` with the cap value, so
you know exactly what knob to turn next.

### Host system snapshot in Log Management Settings

A new row below the settings inputs shows your **host's actual
specs** at page-load time:

`Host: Intel Xeon Silver 4214R (24 cores) — 32.0 GB total / 14.7 GB free — load 0.42 / 0.51 / 0.48`

This is a one-shot read — refresh the page to refresh the
numbers. It exists specifically so you can size the byte cap
above sensibly: if "free" RAM looks tight, you'll see it before
you accidentally set the cap to 4 GB. The CPU/load fields are
informational; we use the same readings to ground the cap
warning thresholds. (A future release will sample the snapshot
periodically and use it to estimate ETA on long-running searches
and bulk jobs — see roadmap v0.31.5.)

### Live search spinner on the Log Viewer

When you click **Apply** in **Search history** mode, the status
line now shows a spinning indicator + ticking elapsed time:

`⟳ Searching markflow.log.5.7z ... 3.2s`

Once the response lands, the spinner clears and the existing
`200 returned · scanned 50000 · 3.4s` summary takes over.

This matters most for `.7z` archives — they can take 10+ seconds
on multi-hundred-megabyte archives because every byte has to flow
through the `7z e -so` subprocess before the search even begins
its filter pass. Before this release, operators saw a static
"Searching..." with no way to tell whether the page was working
or stuck.

---

## v0.31.0 — Five-item bundle: provider parity, log-viewer polish, bulk re-analyze, multi-log tabs, log subsystem consolidation, .7z viewing

### Filenames now help OpenAI / Gemini / Ollama too

Since v0.29.8 the **Anthropic** vision provider has used image
filenames as grounding context — so a file named
`Benaroya_Hall_Seattle.jpg` returns "Benaroya Hall, a concert
venue in Seattle" rather than a generic "a large modern
building." That advantage is now extended to **OpenAI**,
**Gemini**, and **Ollama**.

You don't need to do anything — switch your active provider on
the Providers page and the next analysis batch automatically
benefits. The base prompt instructs the model to USE the
filename when image content agrees, but FALL BACK to a generic
description when filename and content disagree, so misnamed
files don't pollute results.

### Bulk Re-analyze on the Batch Management page

The per-row Re-analyze button (added v0.30.4) is great for one
file at a time, but refreshing thousands of stale rows by hand
isn't practical. **A new "Bulk re-analyze..." button** appears
in the Batch Management top bar, opening a modal where you can:

- Pick rows analyzed BEFORE / AFTER specific dates (use case:
  "all files analyzed before v0.29.8 shipped on April 22nd")
- Filter by provider (e.g. `anthropic`) and / or model (e.g.
  `claude-sonnet-4-20250514`)
- Choose status — defaults to `completed` for the canonical
  refresh-stale use case, but can target `failed` for
  retry-everything

**Click Preview first.** It runs a dry-run that returns the
matched count + the first 5 sample paths without modifying
anything. Then click **Re-analyze matched rows** to actually
delete and re-submit them. There is a hard cap of 10,000 rows
per call — if your filter matches more, narrow it (tighter date
range typically does it).

### What "re-analyze" now means: DELETE then re-INSERT

Per-row AND bulk re-analyze now use **delete-and-re-insert
semantics**. The row in the analysis queue is deleted entirely
and a fresh row is created via the same code path scanning a
new file uses. Effect:

- New `analysis_queue.id`, fresh `enqueued_at`, `retry_count = 0`
- All output columns (description, extracted_text, error,
  analyzed_at, provider, model, tokens_used) start NULL because
  the row is BRAND NEW — not because we explicitly cleared them
- Matches the operator's mental model ("treat this as if
  scanned for the first time")

The previous v0.30.4 behavior was UPDATE-in-place, which
preserved the id. **If anything you have caches the old id
between re-analyze invocations, it will get a 404 lookup
afterwards.** Currently nothing in MarkFlow does this, but
external integrations (UnionCore, custom scripts) should look up
by `source_path` instead of caching ids.

### Multi-log tabs on the Log Viewer

The Log Viewer at `/log-viewer.html` now supports watching
**multiple log files at the same time**. Open `markflow.log`
and `markflow-debug.log` in separate tabs and flip between them
without losing live-tail state, search history, or filters.

- Each tab keeps its own SSE connection in the background, so
  events don't get lost when you switch.
- Each tab has its own filter state — DEBUG/INFO/WARNING/ERROR
  chips, search string, regex toggle, time range, mode (live or
  history). Filtering tab A doesn't affect tab B.
- Click `+ Add tab` to open a popover with all available logs.
- Memory bound: each tab body is capped at 1000 lines (older
  lines drop off the head as new ones arrive).
- Open tabs + per-tab settings persist to your browser's
  `localStorage` — refresh the page and your layout is
  restored.

### Time-range filter for log history search

The Search history mode of the log viewer now has a row of
**From / To** datetime pickers plus four preset chips:
**Last hour**, **Last 24h**, **Last 7d**, **Clear range**.
Clicking a preset fills the inputs to (now − Δ) and (now), then
re-runs the search. The row only appears in history mode (live
tail mode hides it). Local-time inputs are converted to UTC ISO
before being sent to the server.

### `.7z` archives now searchable in-place

Previously you could download `.7z` log archives but couldn't
open them in the viewer — only `.gz` and `.tar.gz` were
readable inline. v0.31.0 wires `.7z` through the same search
code path by streaming `7z e -so` to stdout (the `7z` binary is
already in the container for hashcat — no new dependencies).

When you open a compressed file the viewer auto-switches to
history mode since live tail makes no sense for files that
don't grow.

**Headless safety caps:** because `.7z` decompression can be
heavy, the search request now has three layers of protection
against hangs in unattended operation: a 500,000-line cap, a
60-second wall-clock cap, and (for `.7z` only) a 200 MB
decompressed-byte cap. The 7z subprocess runs in its own
process group so the cap-fire path can cleanly terminate it
along with any helpers.

### Log retention / format settings now actually drive the cron

The Log Management Settings card has had **Compression format**
(gz / tar.gz / 7z) and **Retention days** options since v0.30.1,
but until now the **automated 6-hourly compression cycle ignored
them** — only the manual "Compress Rotated Now" / "Apply
Retention Now" admin clicks honored the prefs. v0.31.0 unifies
the subsystem: there is now one log manager driving both manual
triggers AND the cron, so what you set in Settings actually
applies. **If you set retention to something different from 90
days, expect a one-time purge on the next cron tick to bring the
on-disk state in line with your preference.**

---

## v0.27.0 — Search is dramatically faster on repeat queries

Without a GPU, MarkFlow's semantic (vector) search layer has to
do a ~10-second CPU-heavy computation the first time it sees a
query. That cost is now paid only once per unique query — all
later identical queries return in ~200ms. A few related fixes:

- **Query cache.** The last 256 distinct query strings have
  their semantic vectors cached in memory. Re-searching for
  "photos from union picnics" the second time is near-instant.
- **Background-threaded embedding.** The slow embed now runs on
  a worker thread, so other parts of the app (health checks,
  AI Assist streaming, status bars) stay responsive instead of
  freezing while one search is in flight.
- **Keyword-confident skip.** When you search for a single
  obvious word (like a name) and the keyword index already
  returns plenty of matches, the vector layer is skipped —
  saving ~10s for no loss in ranking quality. You can also
  add `&hybrid=0` to any search URL to force keyword-only.

No action needed; cached queries just work. To warm the cache,
run a representative batch of searches once.

---

## v0.26.0 — AI Assist answers are grounded in real content

Before this release AI Assist often said things like "no preview
text is available for any of the matched documents" even when
your files were full of relevant content. Two wiring bugs were
silently stripping document text before it reached Claude.

Now:

- **Vector matches carry their chunk text.** When MarkFlow finds
  a document via semantic (vector) search, the actual passage
  that matched your query is now passed through to AI Assist
  instead of being dropped.
- **AI Assist reads previews correctly.** The prompt builder now
  looks for document snippets under the field names the search
  API actually uses. Every result that has content in the index
  will surface it in Claude's answer.
- **Source list in the drawer** shows correct file types and
  paths for the "Read full doc" button.

Concretely: a search like *"pictures of business cards"* should
now rank image files whose vision-analysis content describes a
business card (e.g. contact card JPGs) much higher, because that
description actually reaches the ranker and the AI.

No action needed on your side — old searches get the new
behavior automatically.

---

## v0.25.3 — AI Assist clicks feel responsive

The **Synthesize these results** button and **AI Assist** toggle
now give clear visual feedback when clicked:

- Synthesize button: pulses and shows "Opening…" so you know the
  click registered, even before the drawer slides in from the
  right edge.
- Toggle: briefly rings out when switched on or off.
- Drawer: flashes an accent-colored edge when it first opens.

If you have "reduce motion" turned on at the OS level, all of
these are disabled automatically.

---

## v0.25.2 — AI Assist buttons now actually work

The **AI Assist** toggle (top-right of the search bar) and the
**Synthesize these results** button (appears in the results
toolbar when AI Assist is turned on) were silently broken —
clicking them did nothing. A DOM-ordering bug in the search page
meant the click handlers never got attached. Fixed.

If you tried AI Assist earlier today and thought it was disabled
or misconfigured, try again — it should work now.

---

## v0.25.1 — Search now shows you it's working

Small but noticeable fix: when you hit Enter on a search, you
should now *see* that MarkFlow is searching.

- **Progress bar.** A thin accent-colored bar slides across the
  top of the results area while the query is in flight. It
  disappears the instant results land.
- **Previous results stay visible.** If you're refining a search
  ("photos" → "photos 2020"), the old results dim to 50% opacity
  instead of blanking out. No more blink-and-you-miss-it jumps.
- **Fast double-Enter no longer flashes stale results.** If you
  hit Enter twice quickly, only the latest response renders —
  the older in-flight request is discarded on arrival.

No change to AI Assist: it still only fires if you have the
toggle on (top-right of the search bar, `Alt + Shift + A`).
Plain keyword searches never trigger an LLM call unless you ask.

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
