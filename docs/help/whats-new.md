# What's New

Running changelog of user-visible MarkFlow changes. Most recent
versions on top. For internal engineering detail see
[`docs/version-history.md`](../version-history.md) in the repo.

---

## v0.40.0 — Eight new-UX pages built in one release

**Operators now have a complete new-UX surface for the daily workflow.** Eight pages got new-UX twins in this release: Operations (the merged Active Jobs + Trends dashboard that replaces the separate Status and Activity pages), Pipeline Files (drill-down by state), Bulk (overview + tabbed detail consolidating bulk-review and job-detail), Viewer (dual-pane document reader with sidebar), Trash, Unrecognized, Review, Preview, plus Settings → Locations and Settings → Admin.

**Top-nav simplified for operators and admins.** The "Activity" link is replaced by "Operations". The new Operations page has two tabs: "Active now" (live in-flight jobs, the old Status content) and "Trends" (charts and weekly performance, the old Activity content). One page, two tabs, instead of two separate top-level surfaces.

**Bulk job pages consolidated from three to two in new UX.** `/bulk` shows the job list with filter/sort/pagination. Click a row → `/bulk/{id}` shows tabs for Overview (stats + pause/resume/cancel), Files, Errors, and Log (live SSE for active jobs). The original three-page split (`bulk.html` + `bulk-review.html` + `job-detail.html`) is preserved for original-UX users.

**Locations and Admin moved under Settings.** Source-location CRUD is now at Settings → Locations. Admin tools (API keys, system actions, database tools) are at Settings → Admin (admin role required). Original `/locations.html` and `/admin.html` URLs continue to work.

**New document Viewer.** Open a search result or history row → the new viewer shows the converted Markdown alongside the original file (PDF/image preview, audio/video player, or download link). Right rail shows metadata, fidelity tier (T1/T2/T3), and related files. One-click Force re-process and Flag for Review.

**Heads-up for users**

- Bookmarks to `/activity` and `/status` continue to work; new-UX users land on the same content under `/operations` tabs.
- Bookmarks to `/bulk-review.html` and `/job-detail.html` continue to work in original UX; new-UX users will see the consolidated `/bulk/{id}` page.
- Two new pages (Viewer, Preview) load Markdown rendering libraries from a CDN; if your environment blocks CDN scripts via Content Security Policy, those pages may fall back to plain-text rendering. A bundled-locally fix is queued for v0.40.1.

---

## v0.39.0 — Per-user New UI toggle + Search Results renders properly

**The "New interface" toggle in Display Preferences now actually switches the look.** Before this release, the toggle only changed local CSS classes — the served page itself was decided by an environment variable that only operators could change. Now every user can switch independently, and the choice persists across sessions and devices.

**Search Results page is no longer unstyled.** In the new interface, visiting `/search?q=...` previously showed an unstyled wall of HTML — search bar, results, and pagination all stripped of formatting. Fixed: the page now uses the full theme system, looks polished on every theme, and respects font and text-size choices.

**"Match system" theme option.** New control in the theme picker: pick one light theme and one dark theme, and MarkFlow follows your OS dark-mode preference between them in real time. Useful if you live in OS dark mode at night and don't want to flip themes manually.

**Help wiki improvements.** Category sidebar collapses by default and auto-opens for the page you're on. Anchor links survive being copied (GitHub-style slugs preserve consecutive dashes). Every section has a "back to top" link. Anchor jumps no longer land with the heading hidden under the sticky header — the page scrolls to leave breathing room above.

**Convert, Help, Log Viewer, Log Management, and Log Levels pages are now available in the new interface.** Pages that don't yet have a new look (Status, History, Locations, Bulk, Pipeline Files, Viewer) automatically fall back to the original interface, and the toggle stays honest about it instead of silently breaking.

**Heads-up for users**

- If you flipped the new UI on or off during v0.38.0, your last choice will be re-applied on next page load.
- The "match system" theme option requires both a light and a dark theme to be picked from the theme picker. Pick from any of the existing 28 themes.

---

## v0.37.1 — Themes now apply to every page

**Display Preferences finally works on the original-style pages.** In v0.37.0 the theme / font / text-size picker only changed the look of the new-style chrome and the picker itself -- pages like Index, Bulk, Storage, Admin, and Help kept their old colors regardless of what you selected. v0.37.1 fixes that. Every page now responds to your theme, font, and text-size choices.

**Page titles, section headings, and the drop-zone "click to browse" callout are now highlighted in your accent color.** The accent color shifts dramatically between themes -- purple on Classic Light, brighter purple on Classic Dark, orange on Cobalt, green on Sage, pink on Crimson. So switching themes is visible at a glance: titles change color along with backgrounds.

**Display Preferences drawer no longer breaks at X-Large text size.** The four size buttons (Small / Default / Large / X-Large) now reflow into a 2x2 grid when their content grows, instead of overflowing.

**Font list cleaned up.** Removed Inter, IBM Plex Sans, Poppins, and DM Sans -- at normal text sizes on Mac these all looked indistinguishable from System UI. Added **Comic Sans MS** as a fun, distinctive alternative. The drawer now lists 11 fonts down from 14, but every choice is now visibly different.

**Heads up -- OS dark-mode preference no longer overrides your theme choice.** Previously, if your operating system was set to dark mode, original-style pages would force-render dark regardless of which theme you'd selected. This was a bug -- your drawer choice should win. v0.37.1 removes the OS-preference shortcut. If you want dark on the original-style pages, pick **Classic Dark** in the drawer.

---

## v0.37.0 — Display Preferences & Theme System

**28 color themes.** Choose from Original UX, New UX, High Contrast, Pastel, and Seasonal palettes -- six groups in all. Themes apply instantly without a page reload.

**14 font choices.** System UI, Inter, IBM Plex Sans, Roboto, Source Sans 3, Lato, Merriweather, JetBrains Mono, Nunito, Playfair Display, Raleway, Poppins, DM Sans, Crimson Pro. Each is previewed in its own typeface inside the picker.

**Text size control.** Four steps -- Small (0.84x), Default (1x), Large (1.18x), X-Large (1.36x) -- independent of your browser zoom level.

**Per-user Display Preferences.** Open the drawer from the avatar menu in the top-right corner. All changes save automatically and sync across tabs.

**New UX toggle.** Switch between the original interface and the new search-as-home design at any time. Operators can set the system-wide default in Settings -> Appearance.

**Settings -> Appearance (operators).** New operator-only settings page to configure the system default for New UX and control whether users can override display settings.

---

## v0.36.0 — New Look & Feel (April 30, 2026)

> **Note for most users:** The new interface described below is not active by default. An administrator must turn on the new look before you will see it. If your MarkFlow looks the same as it always has, that is intentional — the update is ready and waiting, not missing.

### The first time you load the new look

When an administrator enables the new interface, the first person to visit MarkFlow after the update will see a short welcome walkthrough — three quick steps:

1. **Welcome screen** — introduces the new home page.
2. **Pick your layout** — choose how you want the home page to look (see below).
3. **Pin your folders** — pick up to six frequently used folders and they'll appear as quick-access tiles on your home page.

The walkthrough takes about 30 seconds. Once you finish it, it won't appear again. If you want to redo it later, you can restart it from Settings.

### Three ways to use the home page

The new home page puts the search bar front and center. You can choose the layout that suits your workflow:

- **Maximal** — a full grid of document cards fills the page, with the search bar above. Best if you browse by file.
- **Recent Activity** — the search bar sits at the top, with a row of file-type filters below it and your most recently touched files underneath. Best if you jump between a handful of active files.
- **Minimal** — just the search bar, large and centered. Everything else is hidden. Best if you almost always start with a search.

To switch layouts, click the layout icon in the top navigation bar, or press Ctrl+\ (Cmd+\ on Mac). Your choice is saved and will be the same next time you log in or open MarkFlow from a different browser.

### Document cards look different

Files now show as cards with a colored stripe across the top — blue for Word documents, orange for audio files, purple for PDFs, and so on — so you can spot file types at a glance without reading the extension. You can also switch how dense the list is: the full card view, a compact row view, or a flat list. The density setting is saved per user.

### Settings has a cleaner layout

The Settings area is reorganized. Instead of one long page with everything on it, each section (Storage, Pipeline, AI Providers, Notifications, and others) now has its own dedicated page. You can reach them from the Settings overview, which shows a card for each section.

### Cost tracking under AI Providers (administrators)

Under Settings, AI Providers now has a cost detail page. It shows how much your configured AI providers have been used this month and over the trailing 30 days, a day-by-day chart, and the option to set soft-warning and hard-cap thresholds. Administrators can also import a CSV file to set custom per-token rates if the built-in defaults do not match your contract pricing.

### Activity dashboard (operators and administrators)

There is a new Activity page that shows the health of the auto-conversion pipeline: how many files have been scanned, how many have been fully indexed, and the gap between the two — files that are in the system but not yet searchable. It also shows how the automatic conversion process has been performing over the past week.

---

## v0.35.0 — Active Operations Hub (April 28, 2026)

### What's new for you

**Force Transcribe and every other long-running action now show a progress bar where you started it AND on the Status page.** Click any active operation card on Status to jump back to where you started it (the corresponding progress widget pulses amber to confirm).

**Operations covered:** Force Transcribe / Convert Pending, Convert Selected, Pipeline scans, Empty Trash, Restore All from Trash, Rebuild Search Index, Bulk Re-analyze, Database Backup, Database Restore, Bulk Conversion jobs.

**Cancel button** on every cancellable operation's progress widget.

**Restart safety:** if MarkFlow restarts while operations are in flight, you'll see them marked "terminated by restart" on the Status page so you know what was lost (instead of operations silently disappearing).

### What's changed for you behind the scenes

The old Trash status banner (Empty Trash / Restore All progress) is now powered by the same registry that drives the new widgets. Same look, same behavior — just a unified system underneath.

### Known limitations

- Cancel for Database Backup / Restore is intentionally disabled (data integrity). Wait for completion or revert via a fresh restore from a different snapshot.
- Multi-tab: clicking Force Transcribe in two browser tabs creates two operations (the second errors out since one is already queued). A future release will deduplicate.

---

## v0.34.9 — Aborted jobs now actually look aborted

A small but operationally important fix. When the bulk worker's
"too many errors, abort the job" safeguard fires, the
`bulk_jobs.cancellation_reason` field now updates immediately so
operators (and the UI) see the abort. Pre-v0.34.9, the abort fired
in-process correctly but the database write that made it visible
happened only after **all** workers had exited — which a single
slow or stuck worker could prevent indefinitely. Net effect: an
aborted job could keep showing as `running` with no abort signal
until either (a) the stuck worker finally finished or (b) the
container restarted and the startup reaper cleaned it up.

This was the visible artifact of BUG-016 in the v0.34.7
verification run — 31 instant Whisper failures hit the abort
threshold inside the first 30 seconds, the abort decision was
made correctly in memory, but the DB never reflected it because
one worker remained blocked on a slow Whisper transcription that
the (then-broken) lock had let through. v0.34.8 fixed the lock so
this scenario shouldn't recur often, but the visibility issue was
a separate bug and is fixed here.

### What changed

- The abort safeguard now writes `status='cancelled'` and
  `cancellation_reason` to the DB at the moment it decides to
  abort, not after every worker has drained the queue.
- A one-shot guard prevents the abort log line and SSE event from
  firing once per worker per pull — they now fire exactly once per
  aborted job. (Previous behavior produced thousands of duplicate
  log lines for a single aborted job, inflating `markflow.log`.)

### What you should see going forward

- If the bulk worker ever needs to abort a job (e.g. mass mount
  failure or another systemic-error scenario), the Bulk Jobs page
  shows the cancellation reason within the same heartbeat tick
  rather than only after the queue fully drains.
- The `markflow.log` size growth from aborted jobs drops
  dramatically — from "once per worker per pull after abort" to
  "once per aborted job".

### What you should do

- Nothing. Deploy normally.

---

## v0.34.8 — Whisper transcription works again (and the actually actually converting kind)

The first run-now after v0.34.7 deployed surfaced two more
conversion blockers that the v0.34.6 / v0.34.7 fixes had been
masking:

1. **Whisper crashed every audio/video file** with a cryptic
   "asyncio Lock is bound to a different event loop" error,
   freezing the bulk-worker pool and producing 0 conversions across
   ~5 min of convert phase.
2. **macOS resource-fork sidecar files** (the `._FILENAME.pdf` files
   that pile up on SMB shares whenever a Mac copies a file in)
   were leaking into the conversion pipeline and failing every
   PDF handler call with "Cannot open PDF: No /Root object!" —
   producing a constant trickle of false positives.

Both fixed.

### What was broken

- **Whisper concurrency model.** The transcription module created
  a single shared lock at import time. The format handlers run
  each media file's conversion inside its own short-lived event
  loop (a thread-pool pattern that bridges sync handler code to
  async transcription). Python's asyncio.Lock binds to the first
  event loop that touches it — every subsequent loop hit the
  "different event loop" error. Net effect: only the very first
  media file per process could even attempt Whisper; everything
  after that failed instantly.
- **Resource-fork sidecars.** macOS writes one of these
  (`._FILENAME.ext`) any time you copy a file to a non-Mac volume.
  The bytes are metadata, not the file format the extension
  claims. The scanner already skipped the `.appledouble` directory
  but missed the per-file sibling, so they were entering the
  conversion pipeline and triggering "Cannot open PDF" on every
  one.

### What changed

- The Whisper module now uses one lock per event loop instead of
  one shared one, cached lazily. Cross-loop CPU serialization is
  still in place via the underlying thread lock, so the "only one
  Whisper inference at a time" guarantee is unchanged — only the
  binding bug is fixed.
- The bulk scanner's junk-filename filter now skips files starting
  with `._`. They're caught at scan time and never enter the
  conversion pipeline.

### What you should see going forward

- Audio/video files actually getting transcribed instead of
  failing instantly. Throughput per file depends on duration and
  CPU — the "base" Whisper model on this CPU-only VM runs at
  roughly 0.5–1× realtime, so a 10-minute video takes 10–20
  minutes of CPU.
- The `Cannot open PDF: No /Root object!` rate against `._*` files
  drops to zero as those files stop reaching the PDF handler.
- The Activity / Pipeline page's indexed counter should finally
  start climbing on its own as the auto-converter actually
  succeeds.

### What's still pending

- **Cloud audio fallback.** The current setup has no audio-capable
  cloud provider configured (only Anthropic, which doesn't support
  audio). If you want offload for large media batches or faster
  throughput, add an OpenAI or Gemini API key in Settings → AI
  Providers. Local Whisper on CPU works fine for everyday volume
  but is slow for many-hour archives.
- **The 20-error abort safeguard didn't fire** on the broken run
  — logged as BUG-018 in the bug-log for follow-up. Not blocking
  now that BUG-016 is fixed; the safeguard simply won't need to
  fire when conversions are actually working.

### What you should do

- **Restart the MarkFlow container once after this release lands.**
  Deploy normally (`docker-compose up -d` after build). The next
  scheduled run-now will pick up both fixes.

---

## v0.34.7 — Auto-conversion is unblocked (the actually-converting kind)

The previous three releases each fixed a layer of the
auto-conversion pipeline:

- **v0.34.3** stopped the disk-space pre-check from rejecting every
  job (BUG-011).
- **v0.34.4** stopped the auto-converter slot from staying stuck
  forever after a failed run (BUG-012).
- **v0.34.5** verified those two were holding under live load.

But none of that translated into actually-converted files. A
post-v0.34.6 log audit found two bugs that were silently failing
**every** worker attempt within the first 20 files of every cycle,
which then tripped the bulk worker's "abort if first 20 attempts all
fail" safeguard. Net effect: the scheduler was firing, jobs were
starting, workers were pulling files — and zero files were actually
being converted.

### What was broken

1. **The write guard was denying every write.** The internal
   "is this path inside the configured output directory?" check
   compared against a Storage-Manager-only cache that had never been
   populated on this VM. Whenever the cache was empty, the answer
   was always "no" — including for paths that were clearly inside
   `BULK_OUTPUT_PATH`. Hundreds of `write denied — outside output
   dir: /mnt/output-repo/...` rows were piling up in the bulk-files
   table even though those paths were demonstrably inside
   `/mnt/output-repo`.
2. **Excel files containing chart-only sheets crashed the handler.**
   `openpyxl` exposes those sheets as a different object type
   (`Chartsheet` instead of `Worksheet`) which doesn't have the
   methods the handler was calling. 11 files hit this in production.

### What changed

- The write guard now resolves the output directory through the
  same priority chain as the rest of the pipeline (Storage Manager
  configured value > `BULK_OUTPUT_PATH` env > `OUTPUT_DIR` env).
  No more all-deny mode just because the Storage page was never
  visited.
- The Excel handler skips Chartsheets cleanly with a log line
  (`xlsx_chartsheet_skipped`) so you can see which sheets were
  omitted. Chartsheets contain only an embedded chart, so there's
  no Markdown content to lose.

### What you should see going forward

- The Activity / Pipeline page's **indexed** counter should start
  climbing as the auto-converter actually succeeds for the first
  time in days. Expected throughput at the observed scan rate is
  ~250 files/min once it's actively converting.
- `bulk_files` rows with status `failed` and `error_msg` starting
  with `write denied` should stop accumulating. (Existing rows from
  before this release still reflect the bug.)
- The 20-error abort threshold was a real safeguard, not the bug —
  it was tripping because the two bugs above were turning every
  attempt into an error. Genuine sources of error (corrupt PDFs,
  LibreOffice flakes) still exist in the long tail, but should now
  be a small fraction of attempts rather than 100% of them.

### What you should do

- **Restart the MarkFlow container once after this release lands**
  (deploy normally — `docker-compose up -d` after build). The next
  scheduled auto-conversion cycle will fire with both fixes in
  effect. If you want to verify immediately, hit "Run Now" on the
  Bulk Jobs page.

---

## v0.34.6 — Disk card no longer double-counts the output share

The Resources page **Disk** card was at risk of overstating
MarkFlow's footprint by up to 2× whenever the underlying disk-usage
snapshot completed cleanly. Two separate code paths (the every-6h
metrics snapshot that powers the card, and the admin breakdown
endpoint behind the Disk Usage panel) summed the "Conversion Output"
component on top of "Output Repository" and "Trash" — but post-v0.34.1
all three walk the same NAS share, so the total counted the share
twice.

On this VM the bug had been masked: the latest snapshot's conv-walk
returned 0 (a quiet CIFS hiccup), so the card happened to land on
the right number (~2.05 TB). Next clean snapshot would have flipped
it to ~4 TB without any actual change on disk.

### What changed

- The Resources page Disk card and the admin Disk Usage panel now
  show the genuine MarkFlow footprint: Output Repository (excluding
  trash) + Trash + Database + Logs + Meilisearch index.
- The "Conversion Output" row in the admin breakdown is retained
  for operator clarity (different workflow label) but no longer
  contributes to the total.

### What you should do

- Nothing on the operations side. The next 6-hour disk snapshot will
  write a corrected row to the time-series; existing historical rows
  in the chart still reflect the old (potentially-inflated) totals,
  so a step-down in the chart line on the day v0.34.6 deployed is
  expected and benign.

### Bonus: version display now correct again

`/api/version`, `/api/health`, and the dev version chip were
displaying `0.34.1` on every release from v0.34.2 through v0.34.5.
The `core/version.py` constant had been missed in those release
commits. v0.34.6 includes the catch-up bump and a release-discipline
checklist update so this can't recur silently.

---

## v0.34.5 — Verification milestone

This is a docs-only release that records proof the v0.34.3 + v0.34.4
fixes are working in production. No new behavior; no setup steps to
take. If you've already deployed v0.34.4 and restarted the container
once, you don't need to do anything for v0.34.5.

### What we verified

After deploying v0.34.4, we triggered an immediate auto-conversion
cycle and watched the logs:

- The bulk-worker pre-flight passed (no more "× 3 buffer" rejection).
- A bulk_job moved to `running` status — the first one to reach that
  state on this machine since April 7.
- The scanner started enumerating files at 130–360 files per second.
- Both fixes confirmed end-to-end.

### What you should see going forward

- The Activity / Pipeline page's indexed counter should climb steadily
  as the 92k-pending backlog drains. At the observed rate, expect
  ~250 files per minute when actively working.
- No need to keep manually triggering "Run now" — the scheduled
  45-minute cycles will now actually do work.
- If indexing stalls again in the future, the most likely causes are
  (a) genuine disk-space pressure on the output volume, or (b) a
  repeat of the orphan-stuck pattern on a different table that doesn't
  have a startup reaper yet. Both are now detectable via the
  `startup.orphan_cleanup` log line on container restart.

---

## v0.34.4 — Auto-converter no longer wedges itself

Companion patch to v0.34.3. Discovered while verifying that fix: the
auto-converter wasn't actually starting any new runs even after the
disk-space check was repaired. Investigation showed a separate
long-running issue: any time a conversion run failed (or the container
was restarted mid-run), an internal "this run is in progress" record
was left behind permanently. The auto-converter's "don't start two
runs at once" guard then quietly skipped every subsequent cycle.

We found 38 of these stale records going back to April 7. Once they
accumulate, the only way out was either manual database cleanup or
shipping this fix. v0.34.4 ships the fix.

### What's fixed

- **The startup cleanup that recovers from "the container was killed
  mid-job" now also handles auto-conversion runs.** Any time MarkFlow
  starts up, stale records are reaped automatically.
- Combined with v0.34.3, the path is now end-to-end clear: scans find
  files, auto-conversion creates a job, the disk-space check passes
  with the new sane multiplier, and workers actually convert.

### What you should do

- **Restart the MarkFlow container once after this release lands.** The
  startup cleanup runs automatically on every boot — no manual cleanup
  needed.
- Watch the Activity / Pipeline page over the next few cycles. The
  "indexed" counter should start climbing as the 92k-pending backlog
  drains.

### Why this took so long to catch

The compound bug between "disk-space check rejects every job" and
"failed jobs don't release their auto-converter slot" was completely
silent — no banner, no badge, no notification. Both were logged at
"info" level. Building an operator-facing alert when the auto-converter
hasn't successfully completed a run in N hours is on the upcoming UX
overhaul list.

---

## v0.34.3 — Auto-conversion unblocked on large shares

If you have a source share larger than roughly one-third of your output
volume's free space (e.g., a 250 GB K-drive feeding into a 500 GB
output disk), auto-conversion has been silently failing every job
since v0.23.6 — and there was no obvious signal on the operator-facing
surfaces. This release fixes the pre-flight check that was rejecting
every job and makes the threshold tunable.

### What was broken

Auto-conversion ran a pre-flight check that demanded **3× the source
size** as free output space ("3× buffer for markdown + sidecars +
temp"). For doc-to-markdown work that ratio is wrong by an order of
magnitude — markdown is text and sidecars are tiny JSON, so actual
output runs well under 50% of input. The check kept failing every job
silently while scans continued to discover and queue more files.

### What you'll see now

- **Auto-conversion completes again**. The pile of `pending` files in
  the catalog drains on the next scheduled run (or click "Run scan
  now" from the Activity / Pipeline page to trigger immediately).
- **The "indexed" counter climbs**. Previously stuck at the count from
  before the share grew, it now rises as conversion catches up.
- **No setup change required**. The default multiplier (0.5) is
  appropriate for typical doc workloads.

### If you want to tune

Add `DISK_SPACE_MULTIPLIER=<float>` to your `.env`. Default is `0.5`.
Tune higher (e.g., `1.0`) only if your specific workload produces
unusually large output — extracted-image flows, dense vector indexing
of huge PDFs. Most operators should leave it alone.

### Lesson under the hood

The auto-conversion failure was logged but never surfaced as an
operator alert — no banner, no badge, no notification. Looking at this
gap is on the upcoming UX overhaul list under Notifications trigger
rules.

---

## v0.34.2 — Disk Usage / health summary path consistency

Quick follow-up to v0.34.1. Five more places in MarkFlow were still
reading the old environment-variable defaults instead of your Storage
Manager configured output path. None of them broke conversion, but
they reported wrong information to you in subtle ways.

### What's fixed

1. **Admin Disk Usage panel shows the right path** — after you change
   the output directory on the Storage page, the Disk Usage breakdown
   now reflects the new location on the very next refresh, with no
   container restart needed.
2. **Disk-usage time-series stops drifting** — the 6-hour disk
   snapshot job persists byte counts for the actually-configured
   output directory, so dashboards / historical charts stop showing
   ghost data for the old path.
3. **Health summary `dangling trash` count is accurate** — the
   nightly maintenance check was previously walking a stale path,
   producing wrong counts. Now agrees with reality.
4. **New auto-pipeline + lifecycle job records show the right
   output path** — `bulk_jobs` rows you inspect after the fact
   record where the worker actually wrote, not where the legacy
   env var pointed.

### Why this matters

Nothing on the operator-facing path was broken — conversion, batch
download, history, and trash all already worked correctly after
v0.34.1. v0.34.2 is purely about the **observability surfaces** —
admin panels, metrics, health checks, and forensic job records —
agreeing with where files are actually being written. If you're
running with the default env (which keeps everything coincidentally
aligned) you'll see no behavior change. If you've reconfigured the
output via the Storage page, the admin / metrics surfaces will start
showing the truth on the next refresh.

### What you should know

- No setup changes required — the resolver was already there, this
  release just routes the last few stragglers through it.
- No DB migration. No restart needed for the runtime fixes
  (admin panel, health check, lifecycle scanner). The 6-hour
  metrics job picks up the change on its next scheduled run.
- Disk-usage metrics rows persisted between v0.34.1 and v0.34.2
  under a divergent Storage Manager config will continue to point
  at the old path — they're historical records, not retroactively
  rewritten. New rows are correct.

---

## v0.34.1 — Convert-page write-guard + folder-picker fix

Single bug-fix release closing 9 entangled bugs (BUG-001..009 in the
[Bug Log](/help.html#bug-log)) tied together by `OUTPUT_BASE` having
been captured as a stale module-level constant across 6 consumers.

### What's fixed

1. **Convert page actually works** — drop a PDF → conversion runs to
   completion instead of getting rejected by the v0.25.0 write guard.
2. **Folder picker no longer strands you in an empty modal** — the
   drives sidebar always populates from a known-good fetch, even when
   the requested initial path is invalid. Output-mode auto-fallback
   to `/mnt/output-repo` when given a non-browsable initial path.
3. **Output Directory defaults sensibly** — Convert page now seeds
   the field from your Storage Manager configured path instead of
   the legacy `/app/output` placeholder.
4. **Download Batch / History download / Lifecycle scanner / MCP all
   agree** — pre-fix these 5 consumers silently drifted from the
   Storage Manager output path whenever it diverged from `OUTPUT_DIR`.
   All 6 consumers now go through one shared resolver.

### Why this matters

This was the second-most-frustrating UX failure on the list (after
the v0.32.x trash empty), and it had a critical silent-failure tail:
the lifecycle scanner walked the wrong tree when output diverged,
producing **no soft-delete tracking**. Files removed from the source
share never entered the trash because the scanner couldn't find
their corresponding output. v0.34.1 fixes all of it in one cut.

### What you should know

- API consumers calling `/api/convert` with `output_dir` outside the
  allow-list now get a clear HTTP 422 instead of a silent write to
  somewhere unexpected.
- If neither Storage Manager nor any env var is configured, Convert
  returns 422 with a "configure the Storage page" message instead
  of falling through to a default that the write guard would reject
  anyway.

---

## v0.34.0 — Deep handler for Adobe Premiere project files (`.prproj`)

Premiere Pro project files used to get the same metadata-only treatment
as `.indd` and `.aep` -- filename, file type, modify date, that's it.
v0.34.0 makes them genuinely useful: every project is parsed into a
structured Markdown summary that lists every clip path it references,
every sequence, and the full bin tree. And there's a cross-reference
table + API so you can answer **"which Premiere projects use this
clip?"** in one click.

### What you can do now

**1. Search across Premiere projects by clip filename.** Drop a folder
of `.prproj` files into your source share, run a bulk pass, and
search for any referenced clip's filename. Every project that imports
that clip surfaces in results -- because the rendered Markdown lists
every clip path.

**2. See "Used in Premiere projects" on every clip's preview page.**
Open the [preview page](/help.html#preview-page) for a video, audio,
image, or graphic file. The right sidebar now has a **Used in Premiere
projects** card listing every indexed Premiere project that references
that file. Click any project to open its preview page.

**3. Operators triaging shared NAS storage** can finally answer the
classic question:

> *"Is this clip safe to delete?"*

Just check the cross-ref card. If 5 projects reference it, deleting
breaks 5 deliverables -- you'll know before the editor does.

### What gets extracted

Each project's Markdown output now contains:

- **Project metadata** -- name, Premiere version, frame rate, dimensions,
  schema confidence (high / medium / low).
- **Sequences** -- one row per timeline with name, duration, resolution,
  clip count, marker count.
- **Media** -- every master clip path, grouped by type (video / audio /
  image / graphic / unknown). Listed with full path + basename.
- **Bin tree** -- the project's folder organisation as ASCII art.
- **Parse warnings** -- anything ambiguous flagged for the operator.

### Cross-reference API

Three new endpoints (OPERATOR+ role):

```bash
GET /api/prproj/references?path=<clip_path>
GET /api/prproj/{project_id}/media
GET /api/prproj/stats
```

Full curl / Python / JavaScript samples are documented in
[Administration -> Premiere project cross-reference](/help.html#admin-tools)
and the [Developer Reference](/help.html#developer-reference). Same
JWT / X-API-Key auth as everywhere else.

### Defensive parsing

Premiere has shipped multiple XML schemas across versions. Encrypted
projects, truncated files, and non-standard schemas all degrade
gracefully -- the handler falls back to AdobeHandler-style metadata-
only output if the deep parse fails. Every outcome is traceable in
the Log Viewer with `?q=prproj`.

### New developer-reference help page

While we were at it, we wrote a new [Developer Reference](/help.html#developer-reference)
help article -- a deep-dive on every API endpoint, the full database
schema, the structured-log event taxonomy, format-handler
architecture, Docker / CLI workflows, environment variables, and an
operational runbook. Bookmark it.

### Limitations

- Sequence-clip linkage isn't recorded yet ("clip X used in sequence
  Y"). Reserved for a Phase 1.5 walk.
- Title text and marker comments aren't extracted yet -- the schema is
  denser than time allowed for v0.34.0.
- Phase 0 fixtures are still wanted: drop a real `.prproj` into
  `tests/fixtures/prproj/` and the test suite will sweep it
  automatically.

---

## v0.33.3 — Token + cost estimation: CSV export, stale-rate warning, audit trail

The third and final phase of the cost-estimation subsystem. Adds the
operational pieces you'd need for actually running this in
production: CSV export for finance, automatic warning when your
rate data goes stale, and a documented audit trail.

### What you can do now

**1. Export your cost data as CSV.** Click the new **↓ Export CSV**
link in the footer of the Provider Spend card on the Admin page.
You get a file like:

```csv
date,provider,model,files_analyzed,tokens,cost_usd
2026-04-15,anthropic,claude-opus-4-6,42,178452,8.030340
2026-04-16,anthropic,claude-opus-4-6,38,162001,7.290045
...

TOTAL,,,1199,1602202,72.099090
```

Open it in Excel, Google Sheets, or hand it to your accountant.
One row per (date, provider, model), with a TOTAL footer.

**2. Get warned when your rate table goes stale.** MarkFlow now
runs a daily check at **03:30** to see if your loaded
`llm_costs.json` file is older than **90 days**. If it is, you
get:

- An **amber warning** at the bottom of the Provider Spend card
  on the Admin page (already there since v0.33.2, but now driven
  by the same backend signal).
- A **log warning event** (`llm_costs.stale`) so admins can grep
  for it without having to open the UI.

The warning includes the file's `updated_at` field, the threshold
(90 days), the source URLs to check, and a hint telling you
exactly which file to edit and which endpoint to hit.

**3. Audit-trail every cost calculation.** Every time MarkFlow
estimates a cost — whether you opened a batch, pulled the period
endpoint, or an external program hit the API — it writes a
`llm_cost.computed` event to the log. To see them all from the
last hour:

Open the [Log Viewer](/log-viewer.html?q=llm_cost.computed) with
`q=llm_cost.computed` pre-filled. Or hit the API:

```bash
curl -H "X-API-Key: <key>" \
  "http://localhost:8000/api/logs/search?q=llm_cost&hours=1"
```

### Why we don't auto-refresh the rate table

You might wonder: "if MarkFlow knows the rate data is stale, why
doesn't it just go fetch the latest rates from the providers?"

Two reasons:

- **Pricing pages change schema.** A scrape that worked last
  quarter might silently start producing wrong values when
  Anthropic, OpenAI, etc. redesign their pricing tables.
- **Wrong rates are worse than stale rates.** A 6-month-old rate
  table is usually correct (providers don't change pricing
  often), and the warning tells you exactly when to refresh.
  Auto-fetched-and-wrong is dangerous.

So the design is: MarkFlow nags you when it's been too long;
you check the source URLs (linked in the warning); you edit
`llm_costs.json` yourself; you POST to
`/api/admin/llm-costs/reload` to apply without restart.

### Subsystem status: complete

That wraps the three-phase cost-estimation rollout:

- **v0.33.1** — backend foundation (rate table + 6 API
  endpoints + 22 tests)
- **v0.33.2** — UI surfaces (per-batch panel, Provider Spend
  card, Settings entry, comprehensive API integrator docs)
- **v0.33.3** — operational hardening (CSV export, stale-rate
  warning, daily check, audit trail)

You now have everything you need to: see what each batch costs,
track monthly running totals, project month-end, hand CSVs to
finance, get warned before your rate data goes too stale, and
trace every calculation via the log. External integrators like
IP2A can hook in via the documented X-API-Key + JWT API at
[`docs/help/admin-tools.md`](admin-tools.md).

---

## v0.33.2 — Token + cost estimation: now visible in the UI

The backend that v0.33.1 shipped is now wired up to three operator-
facing surfaces. You no longer need to curl JSON to see what your LLM
analysis is costing you.

### What you'll notice

**1. A new card on the Admin page — "Provider Spend (LLM costs)":**

```
Provider Spend (LLM costs)

$72.10  total this cycle
1.6M tokens · 1,199 files analyzed

By provider
  anthropic: $72.10 (100%)

April 2026 (cycle starts day 1) · day 27 of 30 · 3 days remaining
Projected at current pace: $80.11 by cycle end

[Set cycle start day →] [Edit rate table →]
```

The **Projected** figure is a live extrapolation. If you're three
days into the cycle and you've already burned through what you
expected to spend in two weeks, you'll see the projection blow past
your usual monthly cost — and you can act before the bill arrives.

**2. A "Cost Estimate" panel on every batch on the Batch Management
page.** Click a batch to expand it and you'll now see this above the
file table:

```
Cost Estimate                10 files · 8 analyzed · 2 estimated

TOKENS                       COST (USD)
  Actual:    34,021            Actual:    $1.23
  Estimated:  8,505            Estimated: $0.31
  Total:     42,526            Total:     $1.54

Per-file average: 4,253 tokens · $0.154
Rate used: anthropic/claude-opus-4-7 ($15.00 in / $75.00 out per 1M)

[Show per-file breakdown ▼]
```

The "Estimated" rows are extrapolated from the batch's per-file
average — they're files that haven't been analyzed yet. The
breakdown table marks them with an "estimated" pill so you can tell
actuals from extrapolations at a glance.

**3. A new Settings section — "Billing & Costs"** — with one knob:
**Billing cycle start day** (1-28). Set this to your actual
provider invoice date. Example: if your Anthropic bill closes on
the 15th, set this to 15, and the Provider Spend card will sum
costs from the 16th of last month through today instead of from
calendar-month-start.

### Plugging in another program (IP2A, dashboards, etc.)

The help wiki's [Administration](admin-tools.md) article now has a
full **"Programmatic API access"** section with both:

- **A simple operator version**: the four steps to get an API key
  and hand it to your other program.
- **A developer technical version**: complete curl, Python, and
  JavaScript code samples plus the response-shape JSON for every
  cost endpoint.

Open the help drawer and search "programmatic" or "IP2A" to find
it.

### What's still coming (v0.33.3)

- **CSV export** of period cost data — for handing to finance.
- **"Rate data is X days old" warning banner** when your loaded
  rates haven't been refreshed in over 90 days.
- **Daily staleness check** that emits a warning to the log so
  admins can grep for it.

---

## v0.33.1 — Token + cost estimation: backend foundation

This is the **first of three releases** that build out a full
"how much am I spending on LLM analysis?" subsystem. v0.33.1
ships the backend only — there's no UI yet (that's v0.33.2),
but if you're API-savvy you can already pull cost data with
curl. v0.33.3 adds CSV export + stale-rate warning + audit
trail.

### What you can do today

If you're comfortable with the command line, three new
endpoints work right now:

```bash
# Show the rate table MarkFlow uses (Anthropic, OpenAI,
# Gemini, Ollama)
curl -H "X-API-Key: <your-key>" \
  http://localhost:8000/api/admin/llm-costs

# Show your spend so far this month (using the "calendar
# month" default — Phase 2 lets you set the cycle start day)
curl -H "X-API-Key: <your-key>" \
  http://localhost:8000/api/analysis/cost/period

# Show the cost of one specific batch
curl -H "X-API-Key: <your-key>" \
  http://localhost:8000/api/analysis/cost/batch/<batch-id>
```

The response is plain JSON with `total_cost_usd`, a
`by_provider` breakdown, and a `projected_full_cycle_cost_usd`
estimate so you can budget for month-end before it arrives.

### What's coming

- **v0.33.2 (next)**: clickable cost panel on every batch
  card on the Batch Management page; "Provider spend" card on
  the Admin page with a monthly running total + by-provider
  breakdown + month-end projection; Settings entry for your
  billing-cycle start day; full operator + developer
  documentation in the help wiki.
- **v0.33.3**: CSV export for finance, "rate data is X days
  old — check provider pricing pages" warning, daily
  staleness check.

### How rates are kept current

The rate table lives in a single editable JSON file in the
container at `/app/core/data/llm_costs.json`. To update
rates without a container restart:

1. Edit the file (host-mounted)
2. `curl -X POST -H "X-API-Key: <admin-key>" http://localhost:8000/api/admin/llm-costs/reload`

The file ships with current rates for 11 models across 4
providers. Providers update their pricing periodically (some
quarterly, some yearly) — Phase 3 surfaces a banner when
your loaded rates are >90 days old to remind you to verify.

### For external integrators (IP2A, dashboards, finance
pipelines)

Every cost endpoint respects the existing API-key /
JWT auth. Pull the rate table directly to mirror MarkFlow's
source-of-truth pricing into your own system. Full curl +
Python + JavaScript snippets land in
[`docs/help/admin-tools.md`](admin-tools.md) with v0.33.2.

---

## v0.33.0 — One status card to rule them all + click-to-enlarge scan banner

Two-part UX cleanup.

### Part 1 — Status page: 3 cards → 1 card

Until now, the **Status** page tried to tell you about
background scanning in three different boxes:

1. **Pipeline strip** at the top (chip counts)
2. **Lifecycle Scanner** card (idle / scanning, last-scan time)
3. **Pending** card (last scan, total pending, mode, hours)

All three pulled overlapping pieces of the same data from
different places. The fix in v0.32.11 only patched one of them.
Drift was inevitable.

This release replaces all three with **one Pipeline card** —
the same rich one you already saw on the Bulk Jobs page, with
its full row of cells:

```
[ STATUS PILL — RUNNING / IDLE / PAUSED / DISABLED ]

Mode          Last Scan          Next Scan          Source Files   Pending   Interval
Immediate     2:22 PM (28m ago)  3:07 PM (in 5m)    28,504         1,493     45 min
              ⚠ Interrupted      Pipeline scan
              28,504 scanned     · every 45 min
```

…with all the v0.32.10 sub-lines, status pill, and tooltips
intact. Pause / Resume, Run Now, and Rebuild Index buttons sit
right on the card.

Same data, one place, no drift.

### Part 2 — Bulk Jobs: compact summary instead of duplication

The **Bulk Jobs** page used to show its own full Pipeline
header. Now it shows a one-line summary:

```
🟢 Pipeline running · Immediate · last scan 28m ago · 1,493 pending — view full status →
```

The "view full status →" link jumps to the new full card on
Status. This keeps Bulk Jobs visually focused on actual jobs
while still giving you scanner state at a glance.

### Part 3 — Click the scan banner to enlarge it

When a background scan is running, the orange banner at the top
of every page says:

```
⟳ Background scan running — 21,529 / ~31,000 files (69%) · ~12 min remaining
```

Now it's clickable. **Click the banner** (or focus it with Tab
and press Enter) to open a detail modal showing:

- Run-id of the current scan
- Files scanned vs. total estimated, with a real progress bar
- ETA (estimated time remaining)
- Elapsed time since the scan started
- Current file being processed (full path)
- "Last update X seconds ago" (so you can tell if the scan is
  actually moving)
- A short "What's a background scan?" educational box for new
  operators
- A direct link to the scanner log (for the curious)

Press **Escape** or click outside the modal to close.

### Why we did this

> "I look at three boxes and they all say slightly different
> things about the same scan." — actual Status-page experience
> before this release.

Promoting the rich Pipeline card to be the canonical card and
folding the Lifecycle + Pending data into it gives you one
trustworthy view. Making the scan banner clickable means the
"is this actually moving?" question is one click away from
every page in the app, not buried under a couple of nav clicks.

### Heads-up

Page CSS was bumped to `?v=0.33.0` so your browser will fetch
fresh styles on first load — no action needed on your end.

---

## v0.32.11 — "Last scan: never" no longer lies after a restart

Small but irritating bug: every time you restarted the
container, the **Lifecycle Scanner** card on the Status page
read **"Last scan: never"** — even when the system had run
dozens of scans before. The scan history was always there in
the database; the card just wasn't reading from it.

### What you saw before

After `docker-compose up -d`, open Status →

```
LIFECYCLE SCANNER  idle
Last scan: never
```

…even though the Pending card right below was showing
`Last scan: 28,504 files (0 new, 0 modified) — interrupted`.
Same scan, two cards, contradictory reads.

### What you see now

```
LIFECYCLE SCANNER  idle
Last scan: 2026-04-28 02:22 PM (28m ago)
```

Card matches what every other card on the page already knew.
Data was always correct in the DB; this release hooks the
in-memory cache up to it on container startup.

### Heads-up: the two-card display is on the cleanup list

The Status page currently shows three places with
overlapping pieces of the same scan data:

1. The **Pipeline strip** at the top (chip counts).
2. The **Lifecycle Scanner** card (just fixed).
3. The **Pending** card (also shows `Last scan: …`).

A future release will consolidate them. The plan is to
promote the rich Pipeline card from the home page (with
Mode / Last Scan / Next Scan / Source Files / Pending /
Interval and Pause / Run Now buttons) to be **the** canonical
status card on the Status page, and drop the standalone
Lifecycle Scanner card. The home page will gain a small
summary that deep-links to Status. Single source of truth,
no drift.

That's not in this release — only the data-source bug.

---

## v0.32.10 — Pipeline header on Bulk Jobs is now self-explanatory

The Pipeline header at the top of the **Bulk Jobs** page used
to show six bare values:

```
Mode         Last Scan      Next Scan      Source Files   Pending   Interval
Immediate    7:22:56 PM     8:27:38 PM     1,493          1,493     45 min
```

Helpful, but only if you already knew what each value meant.
v0.32.10 adds a small descriptive sub-line under each value
plus a tooltip on hover, so a glance at the row tells you:

```
Mode                       Last Scan            ⚠ Interrupted
Immediate                  7:22:56 PM (8 min ago)
Convert on every           28,504 scanned · 0 new · 0 modified
new-file detection
                           Next Scan
                           8:27:38 PM (in 5 min)
                           Pipeline scan · every 45 min

Source Files               Pending              Interval
1,493                      1,493                45 min
on disk                    awaiting conversion  between scheduled scans
```

### What you'll notice

- **Last Scan** shows a colored status pill — ✓ Completed /
  ⟳ Running / ⚠ Interrupted / ✗ Failed / ⊘ Cancelled — plus
  files-scanned / new / modified counts. The scan that
  finished at 7:22 wasn't just a time — you can see at a
  glance it was Interrupted (probably by a container
  restart) and processed 28,504 files before it stopped.
- **Next Scan** describes what kind of scan is coming —
  "Pipeline scan · every 45 min" by default, or "Pipeline
  paused — Resume to enable" if you've paused it, or
  "Mode is Off — use Run Now to scan manually" if you've
  set the mode to Off.
- **Times have a relative qualifier**: "7:22:56 PM (8 min
  ago)" / "8:27:38 PM (in 5 min)". You don't have to
  mentally subtract from the wall clock.
- **Hover any cell** for a one-line tooltip explaining what
  it is. Hover the **Mode** cell to see the scheduler's
  most recent decision-reason — the full string MarkFlow
  emits when it picks workers/batch-size, e.g.:

  > Mode=immediate | 113354 files discovered | CPU now=4.9%
  > | CPU historical avg=7.1% | Mon 20:00 | off hours |
  > workers=8 | batch=175

  Useful for understanding why a particular run picked the
  parameters it did.

### Nothing renamed, nothing moved

All six existing cells stay in the same positions. The only
visual change is the small grey sub-line under each value
and the wider minimum cell width (170px → was 140px) to keep
the row readable.

---

## v0.32.9 — Status page card now shows scan progress + jumps to Bulk Jobs

The active-job card on the **Status** page used to show
`[spinner] Enumerating source files… 33s elapsed` and an empty
bar — fine for confirming the scan exists, useless for knowing
whether it's at 100 files or 100,000. The same job on the
**Bulk Jobs** page showed `Scanning source files / 10,696
files scanned / IMG_1979.jpg` with a filled animated bar. The
mismatch was odd because **Status is the page operators
default to**, and the rich view was hidden behind a navigation.

**v0.32.9 makes the Status card match.** During a bulk scan,
you now see:

```
SCANNING ▸ fb326506…       [↗ Open]   [Pause]  [Stop]
/host/d/k_drv_test → /host/d/Doc-Conv_Test

[████░░░░░░░░░░░░░░░░░░ animated sliding sweep ░░░░░░░░░]
⚙ Scanning source files — 10,696 / 51,684 files scanned — 33s elapsed
JOB SITE VISITS/2023 JOBSITE VISIT PHOTOS/.../IMG_1979.jpg

✓ 0 converted   ✗ 0 failed   ⏭ 0 skipped
```

Same `scanned` count, same `current_file`, same indeterminate
animated bar. The two views are now equivalent in information
density.

### Click-through to Bulk Jobs

Clicking the **progress bar** OR the new **↗ Open** button next
to the job-id chip jumps you straight to **Bulk Jobs** filtered
to that specific job:

- The page scrolls the active-job section into view smoothly
- The card flashes briefly with a blue highlight so you don't
  lose your eye

So the standard workflow is: notice a scan on Status → click
the bar → land on Bulk Jobs at exactly the right card → see
the worker breakdown, file list, controls. No hunting.

### Why bother

When 50K+ files are being scanned on an HDD, the difference
between "we've enumerated 1,000 files" and "we've enumerated
10,696 files" tells you whether the scan is making progress
or genuinely stuck. Without the count, your only signal is
"elapsed time grew" — which is also true for a stuck job.

The current-file path is also a tell: if the same path stays
on screen for many seconds, the scanner is hung on that file.
If it cycles every poll, the scanner is moving.

---

## v0.32.8 — Storage page verifies all your paths on every load

The **Storage** page used to verify the **Output Directory**
on page load (since v0.29.1) but never verified your
**Sources**. The green ✓ that occasionally appeared next to
a source was a leftover from a recent **Add** action — it
didn't survive a page refresh, and it only ever showed the
most-recently-added path.

**v0.32.8 closes the gap.** Every configured source is now
verified on every page load:

```
KDrive Test DOCS    /host/d/k_drv_test
                    ⟳ Verifying…
                    /host/d/k_drv_test
```

then a beat later, resolved:

```
KDrive Test DOCS    /host/d/k_drv_test
                    ✓ /host/d/k_drv_test
                    Readable · 223 items
```

Or in the failure case:

```
Old USB             /mnt/shares/old-usb
                    ✗ /mnt/shares/old-usb
                    Path is not accessible (mount missing or unreadable)
```

### New ↻ Re-verify buttons

Each section now has a small **↻ Re-verify** button next to
its content header. One click re-runs validation for every
path in that section without a full page reload. Useful when
you've just plugged in a new drive or fixed a permission
issue and want immediate feedback.

### Auto-re-verify when you come back to the tab

If you switch away from MarkFlow for **more than 30 seconds**
and come back, the Storage page automatically re-verifies
every path. Catches:

- USB drives you unplugged while you were away
- Network shares that dropped because of a Wi-Fi hiccup
- Permission changes on a folder

If everything's still good, you'll see a brief ⟳ flash then
the same green checks. If something changed, you'll see the
new state without having to refresh.

The 30-second threshold means quick tab-flicks (clicking from
Storage to Status and right back) don't trigger unnecessary
re-validation.

---

## v0.32.7 — Status page now actually shows "Enumerating source files…" during a scan

A user reported on v0.32.6: clicked Force Bulk Scan against an
HDD, and the Status page card showed **"0 / ? files — ?%"**
for 20+ minutes with no indication of whether the scanner was
working or stuck. The "Enumerating source files…" UI we
shipped in v0.32.1 was supposed to handle this exact case —
it just had a wrong condition and never rendered.

**Fix shipped.** Whenever a bulk job is in the **SCANNING**
state, the Status page card now shows:

```
[spinner] Enumerating source files… 1m 30s elapsed
```

and after **2 minutes** of no transition, automatically flips
to a yellow warning:

```
⚠ Enumerating — stuck? No progress for 2m 15s.
Stop the job and retry, or check the log viewer.
```

(The "log viewer" link is the clickable status pill at the
top of the card — it opens the Log Viewer filtered to that
job's ID, so you can see exactly what the scanner is doing.)

### Why this matters

Big drives walk slowly. The bulk scanner runs incremental
scanning (skips directories whose modification time hasn't
changed), but on a fresh HDD or a deep tree it still takes
real time. Without the Enumerating display, you're guessing
whether to wait or hit Stop. Now you have a clear signal —
**the job IS doing something**, with elapsed-time count-up,
and a 2-minute escape hatch if it's actually stuck.

---

## v0.32.6 — Trash progress timer no longer resets when you navigate away

**Reported by an operator on v0.32.4:** clicked **Empty Trash**
on a 51K-row pile, opened the Status tab to keep an eye on
other things, came back to Trash a few minutes later. The
progress card said **"elapsed 12s"** — implying the operation
had barely started. In reality the worker had been busy the
whole time; the timer just reset to zero every time the page
mounted.

**v0.32.6 fixes the timer to reflect the actual operation.**
The backend now stamps `started_at` when the worker enters
its run and `last_progress_at` whenever a batch completes.
The frontend reads both on every poll and renders elapsed
time and "last update" against those server timestamps —
not against the user's page session.

### What changes for you

- **Elapsed time is honest now.** Click Empty Trash, leave
  for 10 minutes, come back. Card shows `elapsed 10m 0s`
  (give or take), not `elapsed 0s`.
- **"Last update" reflects real progress.** It tells you
  when the worker last stamped a batch — not when your
  browser last polled. So if the worker is mid-enumeration
  (silent for 30s while it counts rows), you'll see the
  "last update" timer growing — a true signal of "no
  movement", not a misleading "polling is fine".
- **Done count survives navigation correctly.** This was
  already true in v0.32.4 since `done` was always
  server-authoritative. v0.32.6 just adds the timer
  honesty to match.

### Why this matters

Long operations (Empty Trash on 50K+ rows, Restore All on
similar) take minutes. Operators leave the tab, do other
things, come back. They need to trust that the displayed
elapsed time matches reality — otherwise every navigation
makes them suspect the operation reset.

### Try it out

After upgrading + rebuilding:

1. Click **Empty Trash** on the Trash page
2. Wait ~30 seconds
3. Click into **Status** or **Pipeline Files**, do some
   browsing
4. Come back to **Trash** — card shows the true elapsed
   time, e.g. `elapsed 1m 12s`, not `elapsed 0s`

---

## v0.32.5 — Browser cache no longer holds onto old live-banner code

**Tiny operator-quality-of-life fix.** When MarkFlow ships an
update to the global sticky banner (the one that follows you
between pages during long operations like Empty Trash), your
browser's cache used to hold onto the old version until you
manually did a hard refresh (Ctrl+F5). On v0.32.5+, the
`<script>` tag carries a version query string, so a fresh
release means a fresh fetch automatically. No more "I
deployed the new version but my browser is still running
the old one" head-scratching.

This affects the three pages where the global banner appears:

- **Trash** (`/static/trash.html`)
- **Status** (`/static/status.html`)
- **Pipeline Files** (`/static/pipeline-files.html`)

Nothing about how the banner *behaves* changed in v0.32.5 —
this release is purely a cache-hygiene fix. If the v0.32.3
banner improvements never materialised for you (banner not
appearing during Empty Trash, or appearing in the wrong
position), v0.32.5 should fix it on the very next page load
without you needing to hit Ctrl+F5.

---

## v0.32.4 — Empty Trash now shows real progress in-page

When you click **Empty Trash** (or **Restore All**), a
**prominent progress card** now appears right under the action
buttons. You can't miss it — it's bigger than the global Live
Banner from v0.32.3 and it lives directly on the Trash page,
so it can't be hidden by browser caching, scrolling, or
z-index quirks.

### What the card shows

- **🗑 Emptying trash** with a pulsing dot showing the
  worker is alive
- **Progress bar** — animated left-to-right while the worker
  is still enumerating the trash pile, then fills as deletes
  happen
- **Counter** — `12,047 / 51,684 files (23%)`
- **Rate** — `437 files/s`, smoothed so a momentary stall
  doesn't make the number jump around
- **ETA** — `ETA 1m 30s`, computed from the rate
- **Elapsed timer** — ticks `elapsed 27s` so you can see
  exactly how long it's been working
- **Last update** — `last update just now` / `last update 4s
  ago` — tells you whether polling is actually getting
  through, even if the deletion count is stuck

### The "stuck at 0" hint

Big trash piles take time. With 50,000+ rows, the backend
needs to count the rows before it can start deleting — and
during that 30-60 second window, you'll see `0 / 51,684`
with no progress. **That's normal.**

After 30 seconds of no movement, the card automatically shows
a hint:

> Backend may still be enumerating the trash pile — large
> counts (50K+) can take 30-60s before progress numbers
> appear. The worker is alive as long as "last update" is
> recent.

So you know not to panic and click Empty Trash again.

### Mid-operation page refresh

If you accidentally refresh the Trash page while Empty Trash
is running, the card now reappears with the current progress
— no need to re-trigger or wait. Same for Restore All.

### Why this exists

A v0.32.3 user reported: "I clicked on empty trash... and I
don't know if the markflow is executing my command. I want a
progress bar or some kind of status bar to be visible to tell
the user what is happening."

The disabled-button text "Purging 0 / 51684..." was too
subtle, and the global Live Banner across the top of the
page wasn't reliably appearing for them. v0.32.4 puts the
feedback directly on the Trash page, big and obvious.

### Try it out

After upgrading + rebuilding:

1. Navigate to **Trash**
2. Click **Empty Trash** (or **Restore All**)
3. The card appears immediately, between the buttons and the
   file table
4. Watch elapsed time tick, animated bar move, counter
   update — and after ~30 s if `done` is still 0, the
   enumeration hint kicks in to explain why

---

## v0.32.3 — Trash actually empties; banner sits below the nav

Three small but irritating bugs from the v0.32.1 Empty Trash +
Live Banner work, all fixed in one cut.

### Empty Trash now clears the whole pile in one click

Before: clicking **Empty Trash** only cleared the first 500
files. The Trash header would tell you "500 files in trash"
even when the database had 60,000+ in the trash pile, and you'd
have to click Empty Trash 100+ times to clear the whole thing.

Now: one click runs through the entire trash. Wall-clock time
on this hardware: ~30 seconds for 50K rows. Header shows the
real number (e.g., "51,684 files in trash") so you know what
you're dealing with before you click.

The Live Banner shows the true scale during the operation:

```
🗑 Emptying trash · 12,047 / 51,684 files · 437 files/s · ETA 1m 30s
```

The same fix applies to **Restore All from Trash** — one click
restores everything, not just the first 500.

### Live banner sits below the nav bar (not on top of it)

Before: while a long-running operation was in flight, the live
banner painted over the top nav bar — covering Storage,
Settings, Flagged, Admin links. You couldn't navigate without
dismissing the banner.

Now: nav bar stays at the very top, banner pins directly below
it. Both stay visible as you scroll. The page content gets a
small top spacer added automatically when the banner is
visible, so titles and headers right under the nav don't get
hidden behind the banner.

### Banner shows "Starting…" while the worker spins up

Before: clicking Empty Trash showed "0 / 0 files · — files/s ·
ETA —" for about half a second before the real numbers came in.
Looked broken — like the operation hadn't actually started.

Now: that half-second window shows "Starting…" instead. Rate
and ETA hide until the count is known. Once the worker has
counted the rows, the banner switches to the normal "X / Y"
format.

### Try it out

After upgrading + rebuilding:

1. Navigate to **Trash** — header now reflects true total
   (might be much bigger than what you remember, especially on
   instances that ran lifecycle scans recently).
2. Click **Empty Trash** — banner pops up below the nav, shows
   "Starting…" for a tick, then the real progress.
3. Watch it count down to zero in one shot. You can navigate
   to Status / Pipeline Files while it runs — the banner
   follows you.

If you'd previously been clicking Empty Trash repeatedly to
chip away at the pile, you can stop doing that.

---

## v0.32.2 — Recovery for `.tmk` files and browser-download suffixes

Two specific classes of file used to get stuck in the
**Unrecognized** bucket on Pipeline Files. As of v0.32.2, both
classes flow through normal conversion automatically.

### Browser-download suffixes (`.download`, `.crdownload`, `.part`, `.partial`)

If you've ever used a browser's **"Save Page As — Complete"**
mode, you've seen this: the saved page is a `.html` file plus
a `_files/` folder full of CSS / JS / image assets that the
browser saved with names like `add-to-cart.min.js.download`.
Same thing happens with **interrupted downloads** — Chrome /
Edge leave a `.crdownload` partial, Firefox and Safari leave
`.part` or `.partial`.

MarkFlow now strips the trailing suffix and re-checks the
**inner extension**. If the inner extension has a registered
handler, the file is routed through it directly. Examples:

| Filename in your repo | Recovered as | What MarkFlow does |
|---|---|---|
| `add-to-cart.min.js.download` | `.js` | Indexed as JavaScript text |
| `report.pdf.crdownload` | `.pdf` | Full PDF conversion |
| `archive.zip.part` | `.zip` | Archive listing + extraction |
| `slides.pptx.partial` | `.pptx` | Office conversion |

This works even when the inner extension is itself unfamiliar
(e.g., a `.tmk.download` falls through to the `.tmk` handler
described next), so nothing gets stuck.

### `.tmk` files

These are small marker files seen alongside `.mp3` recordings
in audio-transcribe folders. MarkFlow now runs them through a
**three-layer recovery** chain:

1. **MIME detection** on the bytes — if libmagic recognises
   the format (e.g., it's actually a JSON manifest), MarkFlow
   uses the matched handler.
2. **UTF-8 text fallback** — if it's mostly printable text,
   MarkFlow indexes it as plain text so its contents are
   searchable.
3. **Metadata-only stub** — last resort. MarkFlow emits a
   short Markdown record with the filename, size, and first
   16 bytes as hex, so the file shows up in conversion
   counts rather than getting stuck in Unrecognized.

The same chain runs for any `.tmp` file (which has worked this
way since v0.20.x).

### What you should see after the next bulk scan

Open `/static/pipeline-files.html` and switch to the
**Unrecognized** filter. The chip count should drop by the
sum of `.tmk` + `.download` + `.crdownload` + `.part` +
`.partial` files across the source. The recovered files now
show up under **Scanned** / **Indexed** instead, and their
content is searchable.

> **What's still deferred**: the broader plan to **sniff
> every unrecognized file by content** (regardless of
> extension) and surface the discovered format in the search
> results / preview page is a follow-up release. v0.32.2
> handles the two specific cases your repo had — the general
> case will land later.

---

## v0.32.1 — Pages stay fresh, pills click through, lists shrink

The v0.32.0 preview page surfaced three things operators wanted:
pages that auto-refresh, lists that don't include trashed-but-not-
purged files, and clickable pills on the Status page that drill
into what the system is actually doing.

### Pipeline Files now hides trashed-but-not-purged files

Before: the page listed every `bulk_files` row regardless of
whether the file still existed on disk. On the production
instance that was 113K rows when only ~2K were actually present.

Now: the page filters by `lifecycle_status='active'` (i.e.,
"file is on disk") by default. A new **"Include trashed /
marked-for-deletion files"** checkbox below the search bar lets
you toggle the filter off when you want to see what the registry
knows even after disk-state divergence. Counters and list
refresh together.

### Lists auto-refresh

Pages that show server-side state that changes outside of user
interaction now refresh themselves while the tab is visible:

| Page | Cadence |
|---|---|
| Pipeline Files | every 30 seconds |
| Batch Management | every 60 seconds (status counters still tick at 5 s) |
| Flagged Files | every 30 seconds |
| Unrecognized Files | every 60 seconds |

Polling **pauses while the tab is hidden** so backgrounded tabs
don't burn API calls. When you switch back, the page fires one
immediate refresh and resumes.

### Live Status Banner across pages

When you trigger a long-running operation (Empty Trash, Restore
All from Trash, etc.), a **mirrored status banner** now appears
at the top of every page that includes the script:

```
🗑 Emptying trash · [bar 25%] · 127/500 files · 2.4 files/s · ETA 2m 35s · ×
```

So you can kick off Empty Trash, navigate to Status to watch
other things, and the banner follows you. Auto-dismisses 4 seconds
after the operation finishes (so you see the green "Done" state).
Click the × to hide it for the current operation.

Wired this release: Trash, Status, Pipeline Files. More pages can
opt in by including `<script src="/static/js/live-banner.js"></script>`.

### Clickable status pills on the Status page

The pills on Active Jobs cards are now hyperlinks:

| Pill | Click destination |
|------|-------------------|
| **SCANNING `<id>…`** | Log viewer, filtered to this job's ID |
| **PENDING** (header card) | Pipeline Files filtered to `status=pending` |
| **LIFECYCLE SCAN** (running) | Log viewer, filtered to lifecycle scan events |
| **LIFECYCLE SCANNER** (idle) | Log viewer (same — see prior runs) |

The Log Viewer also gained `?q=<text>` and `?mode=history` URL
parameters, so deep-linking from the Status page jumps straight
to the right tab with the right search query already running.

### Scanning-card UX fix

Active scanning jobs in their first few seconds have not yet
finished walking the source tree, so `total_files` is unknown.
The card used to show "0 / ? files — ?%" which looked broken.

Now: while the scanner is enumerating, you see *"Enumerating
source files… 12s elapsed"* with a spinner. If a scan has been
in this state for more than 2 minutes with no heartbeat, the
card switches to a warning: *"⚠ Enumerating — stuck? No progress
for 3m 24s. Stop the job and retry, or check the log viewer."*
Click the now-clickable **SCANNING** pill to jump to the log.

### Trash purged on demand

The 60K+ in-trash rows on this instance weren't going to
auto-purge for ~42 days under the default 60-day retention.
v0.32.1 included a one-shot purge cycle that cleared ~7,500
rows immediately; the rest age out on the existing schedule.

### Plan written: `.tmk` handler + `.download` recognition

A planning document was written for two related improvements
operators have been waiting on: a handler for the `.tmk` files
that show up in audio-transcribe folders, and a generic
format-sniffing recovery pass for `.download` /
`.crdownload` / `.part` files (browser-saved files where the OS
appended its own suffix). Implementation will land in a future
release.

---

## v0.32.0 — File preview page + Batch Management page-size + collapse-all

### File preview page (replaces the old "later phase" stub)

Click the **folder icon** (📂) on any Pipeline Files row and
you now get a real **file-detail page** instead of the
19-line stub that was there before. The page shows the
**source file**, not the converted Markdown — that's still on
the eye-icon (👁️) viewer page.

#### What you see

- **Inline preview** — sized to the file type:
  - **Image** (JPG/PNG/HEIC/RAW/SVG/TIFF/PSD/EPS): rendered
    inline, server-thumbnailed when the browser can't decode
    the format directly.
  - **Audio** (MP3/M4A/WAV/OGG/Opus/FLAC): playable in-page
    with a seekable timeline.
  - **Video** (MP4/M4V/MOV/WebM/MKV): playable in-page,
    seekable.
  - **PDF**: opens in the browser's built-in PDF viewer
    (iframe).
  - **Text / code / config / log** (.txt, .md, .json, .csv,
    .py, .js, .yaml, etc.): first 64 KB shown in a `<pre>`
    block.
  - **Office docs that were converted** (DOCX/XLSX/PPTX/ODT
    etc. with a successful conversion): the rendered Markdown
    is shown inline, with a "→ View converted" link to the
    full viewer.
  - **Office docs not yet converted**: a clear "Not yet
    converted" panel that tells you the current pipeline
    status (pending / failed / skipped) and what to do.
  - **Archives** (.zip, .tar, .tar.gz, .7z, .rar, plus
    Office-doc internals): table of entries with names,
    sizes, and modified times (capped at 500 entries).
  - **Anything else**: metadata + a Download button.

- **Sidebar metadata cards**:
  - **File stats**: size, mtime, MIME, extension, category
  - **Conversion**: status pill, output path, error message
    if it failed, timestamp
  - **Analysis**: image-analysis description / extracted text
    / provider / model / tokens (when relevant)
  - **Flags**: any active operator-raised flags on the file
  - **Siblings**: list of files in the same folder, with a
    `← Prev` / `Next →` button pair to jump between them.
    Capped at 200 entries with a "showing N of M" indicator
    on bigger folders.

- **Action buttons**:
  - **Download** — straight file download
  - **Open in new tab** — same content URL in a new tab
  - **Copy path** — puts the absolute container path on the
    clipboard
  - **Show in folder** — jumps to Pipeline Files filtered to
    the parent directory
  - **View converted →** (when applicable) — opens the
    converted-Markdown viewer for the full experience
  - **Re-analyze** (when an analysis row exists) — DELETEs
    the existing analysis row and re-enqueues a fresh one
    (uses LLM tokens on the next batch)

- **Keyboard shortcuts**: `←` and `→` jump to the previous /
  next file in the same folder. `Esc` jumps back to Pipeline
  Files filtered to the parent.

#### Example workflow

You see a row in Pipeline Files for
`/host/c/2026 Audits/JulyAudit/page17.tif` flagged as
"failed conversion." Click the 📂 icon, the preview page
opens. The inline image viewer shows the actual TIFF page (so
you can see what's on it). The Conversion sidebar shows the
error message. Press `→` to step to `page18.tif`. Press `Esc`
to jump back to Pipeline Files filtered to `JulyAudit/` so
you can see all of that audit's files together.

### Batch Management — page size + Collapse / Expand all

The Batch Management page used to render every batch card on
load. With hundreds of batches, that meant scrolling forever
or playing whack-a-mole opening cards. v0.32.0 adds:

- A **page-size dropdown** (10 / 30 / 50 / 100 / All —
  default 30). Your choice persists across page loads.
- A **Pagination footer** below the cards: `← Prev`,
  `Next →`, and "Showing 1-30 of 247 batches".
- An **Expand all / Collapse all** toggle button that flips
  every card on the current page open or shut. Click once to
  expand all collapsed cards (which fires the existing
  lazy-load of each card's file list); click again to
  collapse them all.

If you usually want to see all batches at once on a fast
machine, set page size to **All** once and you're set. If you
want to scan recent activity quickly, **30** keeps the page
snappy.

### Force-process this file (file-aware Transcribe / Process / Analyze)

The preview page now has a **single button** that runs the full
pipeline on whatever file you're looking at — without waiting
for the next pipeline tick. The label changes to match the
file:

| Your file is… | Button reads | What it does |
|---|---|---|
| Audio (`.mp3`, `.m4a`, `.wav`, …) or video (`.mp4`, `.mov`, …) | **🎙 Transcribe** | Runs Whisper, writes the transcript Markdown to the output dir, and indexes it. |
| Office doc, PDF, text/code, archive | **⚙ Process** | Converts to Markdown using the right handler, writes output, and indexes. |
| Image (`.jpg`, `.png`, `.heic`, RAW, etc.) | **🔍 Analyze** | Sends the image through the LLM vision pipeline (description + extracted text) and writes results to the analysis queue. |
| Anything else (binary blobs, executables, etc.) | *button hidden* | No applicable action. |

Click it and a **live progress card** slides in below the
action buttons:

- Spinner + phase label ("Transcribing (Whisper)…",
  "Converting…", "Analyzing (LLM vision)…")
- Live elapsed-time ticker (`12.3s`, then `1m 23.4s` …)
- On success: green card, output path, **Dismiss** button.
  The page **refreshes its sidebar in place** so you don't
  lose your scroll position — the Conversion / Analysis
  cards repopulate, and audio files get a transcript pane
  added below the player.
- On failure: red card with the error message and **Dismiss**.

#### Example — transcribe a meeting recording

1. Browse to `/static/pipeline-files.html?folder=/host/c/Audio`
2. Click the 📂 icon on `meeting04.mp3`. The preview page opens.
3. Click **🎙 Transcribe** in the toolbar.
4. The progress card appears: *"Transcribing (Whisper)… 0.5s"* …
   *14.2s* … *2m 11.0s*. (Whisper is single-threaded per call;
   for a 1-hour recording expect ~10–20 min on the GTX 1660 Ti.)
5. When it completes, the **Transcript** pane appears below
   the audio player with the speaker dialog, and the
   **Conversion** sidebar card flips to ✅ Success with the
   output path. The **Related Files** sidebar card re-runs
   with the new transcript content as the query — files with
   similar text content show up at the top.

#### Example — analyze a phone photo

1. Open a `.heic` file from a phone backup folder.
2. Click **🔍 Analyze**. Progress card shows
   *"Analyzing (LLM vision)… 8.4s"*.
3. The Analysis sidebar card populates with the LLM's
   description ("A close-up of a hand-written meeting agenda
   with bullet points listing…") and any extracted text.
4. Related Files re-runs using the new description as the
   query — other photos of agendas / handwritten notes show up.

#### Example — convert a single Office doc that's stuck pending

1. Open a `.docx` whose Conversion sidebar shows "pending."
2. Click **⚙ Process**. The conversion runs in foreground
   (you see the elapsed timer); when it finishes, the
   Office-with-Markdown viewer takes over the main pane,
   showing the rendered Markdown inline with a "→ View
   converted" link to the full viewer.

The button is **hidden** entirely when the file extension
isn't supported by any pipeline (e.g., a `.exe` or stripped
binary blob — there's nothing for MarkFlow to do with it).
It's **disabled** with a tooltip when the file is recognized
by type but missing on disk (deleted between scans, NAS
hiccup, etc.) — once the file's bytes come back the button
re-enables on the next page load.

### Related Files + typed search + highlight-to-search

The preview page now has three new ways to find context-similar
files **without leaving the page**:

#### 1. Auto-populated Related Files card

Every preview page load fires a similar-file search keyed off
the file's own content (transcript text → analysis description
→ filename + folder name, in that order). Two tabs at the top
of the card:

- **Semantic** (default) — vector search via Qdrant. Finds
  files with similar meaning, even if the words are different.
- **Keyword** — Meilisearch full-text. Faster, but matches
  literal terms.

Click any result to open it in a new tab — your current
preview stays in place.

#### 2. Sidebar Search panel

Type your own query into the search box, pick a mode
(Semantic / Keyword), and hit **Search** (or just press
Enter). Results render directly below.

For deeper synthesis, click **🤖 AI Assist ↗** — that opens
the full search page in a new tab with AI Assist enabled.
(AI Assist isn't auto-fired here because every preview-page
open would burn LLM tokens — it's an explicit click.)

#### 3. Highlight-to-search chip

Highlight any text inside the file viewer, transcript,
analysis description, or any related-files list. A floating
chip pops up at your cursor with three options:

- **🧠 Semantic** — searches the same panel for files with
  similar meaning.
- **🔎 Keyword** — searches for files containing those
  literal words.
- **🤖 AI ↗** — opens the full AI Assist page in a new tab
  with your highlighted text as the query.

This is the fastest way to chase a phrase you just noticed
in a transcript — highlight, click, results appear in the
sidebar.

#### Example workflow — pull on a thread in a transcript

1. You're reading the transcript of a board meeting in the
   audio file viewer.
2. You highlight the phrase "*resolution for trans
   healthcare*."
3. The chip appears. Click **🧠 Semantic**.
4. The Search panel below populates with other files
   discussing similar topics — meeting minutes, draft
   resolutions, related correspondence.
5. Click any result; it opens in a new tab. Your transcript
   stays exactly where you left it.

#### "Find related ↗" full-page handoff

In the action toolbar at the top of the preview page, the
**Find related ↗** button opens the full
`/static/search.html` page in a new tab, seeded with the
current file's content as the query. Use this when you need
the bigger search experience (filters, AI Assist, batch
download) without sacrificing your preview-page context.

### "Page refreshed" banner when you come back

If you're looking at a preview page, switch tabs / Alt-Tab
to another app, and a force-action / pipeline tick changes
the underlying file's state in the meantime — when you come
back, the page detects it on focus and:

- **Re-fetches** the file info,
- **Re-renders** the sidebar / viewer with the latest data,
- **Shows a blue banner** at the top: *"This file changed
  while you were away — page refreshed with the latest
  data."*

The banner auto-dismisses after 12 seconds, or you can click
the × to close it sooner. This way you never read stale info
without realizing it. The banner is suppressed during your
own in-progress force-action so it doesn't show up for your
own work.

### Better error UX on missing files

Click "Open in new tab" or "Download" on a file that the
registry remembers but the disk has lost? Two improvements:

- **In the preview page**, those buttons now render
  **disabled** with a tooltip that says *"File not found on
  disk — cannot serve content."* You won't accidentally land
  on a JSON error page.
- **If you do hit the URL directly** (bookmarked link, copied
  URL, shared in Slack), you now get a friendly HTML page
  instead of `{"detail":"file not found"}`. The page shows
  the path, the reason, and links back to the preview view
  + Pipeline Files.

The **🎙 Transcribe / ⚙ Process / 🔍 Analyze** force-action
button on a missing file: it stays visible (so you know what
the right action would be) but is disabled with a tooltip.
Once the file's bytes come back, the button re-enables.

### Side fixes shipped in this release

- **Lifecycle scan no longer logs a noisy traceback on
  shutdown.** Container restarts used to leave a
  `CancelledError` traceback in `markflow.log` because the
  scheduled lifecycle scan was mid-await on a DB write when
  SIGTERM landed. Now it logs `scheduler.scan_cancelled_on_shutdown`
  cleanly and exits.
- **662 MB of stale `db-*.log` files removed.** The DB
  contention logger was retired back in v0.24.2 but its
  three temp files (`db-contention.log` 375 MB,
  `db-queries.log` 272 MB, `db-active.log` 15 MB) were never
  cleaned up. Reclaimed automatically as part of this
  release.

---

## v0.31.6 — Test-convert a hand-picked subset of pending files

The History page's **Pending Files** card lists every file
queued for conversion (currently 113,354 on this instance). The
existing **Force Transcribe / Convert Pending** button kicks off
the whole list — fine when you want everything processed, but
heavy when you just want to test 3 specific MP3s before
committing.

v0.31.6 adds **per-row checkboxes + a bulk action bar**. Pick
the files you want, the bar at the top of the card shows what
you've got selected ("3× .mp3, 1× .pdf · 287 MB total"), and
clicking **Convert Selected (3)** schedules just those for
immediate conversion.

### What changed

- New checkbox column on every row in the Pending Files table.
- Header has a "select all on this page" checkbox.
- Selection survives pagination — pick rows on page 1, navigate
  to page 2 to pick more, the page-1 picks stay selected.
- Switching the status filter (Pending ↔ Failed) clears the
  selection (different eligibility rules).
- The action button text adapts: **Convert Selected (N)** when
  filtering by Pending, **Retry Selected (N)** when filtering by
  Failed.
- Hard cap of 100 files per click. Above that, the button shows
  a warning and disables — use Force Transcribe for the full set.
- Confirmation dialog warns about audio/video files taking
  minutes each.
- Up to 4 files convert in parallel server-side (matches the
  default bulk worker count).
- The pending list auto-refreshes every 30 seconds, so you'll
  see your selected files transition out of pending as each
  finishes.

---

## v0.31.5 — Hover preview now covers HEIC / RAW / SVG, plus log searches show an ETA

### Phone photos and RAW camera files now preview

The hover preview on Batch Management used to cover JPEG, PNG,
TIFF, PSD, and a few dozen other PIL-readable formats — but
not the formats most modern cameras and phones produce by
default:

- **HEIC / HEIF** — the iOS default and many Android phones'
  high-quality mode. Hover-preview now works on these.
- **RAW camera files** — `.cr2`, `.cr3`, `.crw`, `.nef`,
  `.nrw`, `.arw`, `.srf`, `.sr2`, `.raf`, `.orf`, `.rw2`,
  `.pef`, `.srw`, `.dng`, plus another dozen vendor-specific
  extensions. We pull the embedded JPEG thumbnail when the
  RAW file has one (most do, ~50× faster than full
  decoding); fall back to a fast half-size decode otherwise.
- **SVG / SVGZ** — vector graphics, rasterized server-side
  on the way to the browser. The browser sees a JPEG, never
  the SVG document, so any embedded scripts in the SVG are
  inert. Operators don't need to worry about XSS in SVG
  files dropped into the source repo.

### Log searches now show an ETA

The Log Viewer's history-search mode now shows an estimate
above the search controls: "ETA: estimated 1.4s (12 prior
obs)" — or "expected 12s" once the estimator has seen 50+
prior runs on this archive's format bucket (gzip / 7z /
plain `.log`).

The number is based on actual throughput observed on YOUR
hardware over recent searches. After a few searches the
estimator settles in; before then, the hint just doesn't
appear. If you upgrade the host's RAM or move the data to an
SSD, the estimate adapts automatically over the next handful
of searches.

Searches that bail at the line cap (500k lines) or the
wall-clock cap (60s) are NOT counted toward the estimate —
those would skew the math toward "infinitely slow" because
they ran out of budget before finishing the work they would
have done.

### Behind the scenes

- New scheduler job: every 24 hours we capture a snapshot of
  the host's CPU model, RAM, and load average. 90 entries
  retained — a three-month rolling history that future
  releases can use to detect hardware drift.
- New diagnostic endpoint: `GET /api/logs/eta/stats` returns
  observation counts and EWMA throughput per operation key
  for admin debugging.

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
