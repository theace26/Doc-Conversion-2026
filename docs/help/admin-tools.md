# Administration

The Admin panel is the control center for your MarkFlow installation. It gives you
a bird's-eye view of the entire repository, tools for database maintenance, API key
management for integrations, and resource controls that let you tune how MarkFlow
uses your server's hardware.

You can reach it from the navigation bar by clicking **Admin**. This page is only
visible to users with the **Admin** role.

---

## Repository Overview

The top of the Admin page is a live dashboard of your MarkFlow repository. It
opens with a row of large KPI cards that give you the numbers at a glance:

| Card | What It Shows |
|------|---------------|
| Total Files Scanned | Every file the bulk scanner has ever encountered |
| Successfully Converted | Files that produced a valid Markdown output |
| Unrecognized Files | Files MarkFlow found but has no handler for (e.g. `.exe`, `.mp4`) |
| Failed Conversions | Files where conversion was attempted but errored out |
| OCR Needs Review | Scanned PDFs whose OCR confidence fell below your threshold |
| Pending Conversion | Files queued but not yet processed |

Below the KPI cards you will find detail panels:

- **File Status Breakdown** -- a table with the same status categories and
  percentage bars so you can see proportions.
- **Lifecycle Status** -- how many files are active, marked for deletion, or
  sitting in the trash. Includes a link to the [Trash management page](/trash.html).
- **Conversion Activity** -- success rate, conversions in the last 24 hours and
  7 days, and your top converted formats (DOCX, PDF, etc.).
- **OCR Review Queue** -- pending vs. resolved flag counts, with a link to the
  [OCR Review page](/review.html).
- **Unrecognized File Types** -- breakdown by category (video, audio, archive, etc.).
- **Search Index (Meilisearch)** -- whether the search engine is online, plus
  document and Adobe file counts.
- **LLM Provider** -- which AI provider is active (if any), with a link to the
  [Providers page](/providers.html).
- **Scheduled Jobs** -- next run times for the lifecycle scan, trash expiry, and
  database compaction.
- **Recent Conversion Errors** -- the last 10 failures with filename, format,
  error message, and timestamp.

Click the **Refresh** button in the section header to reload the dashboard data.

> **Tip:** The Repository Overview is a great starting point when something seems
> wrong. If the Failed count is climbing, check the Recent Errors table first --
> it will usually point you to the root cause.

---

## Disk Usage

Below the Repository Overview you will find the **Disk Usage** section. It shows
how much storage MarkFlow is consuming, broken down by component:

| Component | Description |
|-----------|-------------|
| Output Repository | The converted Markdown knowledge base |
| Trash | Soft-deleted files awaiting purge |
| Conversion Output | Single-file conversion results from the Upload page |
| Database | The SQLite database file plus its write-ahead log (WAL) |
| Logs | Operational and debug log files |
| Meilisearch Data | The full-text search index |

At the top of the section, two progress bars show overall volume usage and what
share of that volume MarkFlow occupies. Each component gets its own card with
the size in human-readable units and a file count where applicable.

> **Warning:** The disk usage scan walks every directory and can take several
> seconds on large repositories. It does not refresh automatically -- click
> **Refresh** when you need an update.

Cards with a yellow border indicate a potential concern. For example, if the
Trash grows past 1 GB, its card is highlighted so you know it may be time to
empty it.

---

## Database Tools

The **Database Tools** section gives you three maintenance actions for the
MarkFlow SQLite database. For a more detailed dashboard, visit the
[DB Health page](/db-health.html).

### Health Check (fast)

Runs a quick structural check. It verifies the WAL file size, confirms the
schema is intact, and reports row counts for the major tables. This completes
in under a second and is safe to run at any time.

### Integrity Check (slow)

Performs a full content verification using SQLite's built-in `PRAGMA
integrity_check`. This reads every page of the database and can take 30 seconds
or longer on large files. Use it when you suspect data corruption -- for
example, after an unexpected container shutdown.

### Repair Database (destructive)

This is the nuclear option. It dumps the entire database to SQL, creates a
backup of the original (saved as `.db.bak`), and restores from the dump into
a fresh file. You must stop all running jobs before this will execute.

> **Warning:** The Repair action acquires an exclusive lock on the database.
> All in-flight API requests will wait until the repair finishes. Never run
> this during active conversions. The button will ask you to confirm before
> proceeding.

---

## API Key Management

API keys allow external systems -- primarily UnionCore -- to authenticate
with MarkFlow's API without using JWT tokens. Keys are service accounts that
always receive the `search_user` role, which means they can search and read
documents but cannot start conversions or change settings.

### Generating a Key

1. Type a descriptive label in the text field (e.g. `unioncore-prod` or
   `staging-cowork-bot`).
2. Click **Generate New Key**.
3. A green banner appears with the raw key. It starts with `mf_` followed by
   a long random string.

> **Warning:** The raw key is shown exactly once. Copy it immediately. If you
> lose it, there is no way to recover it -- you will need to generate a new
> one and revoke the old one.

### Copying and Distributing

Click the **Copy** button next to the key to put it on your clipboard. Paste
it into the consuming system's configuration (e.g., UnionCore's MarkFlow
connection settings).

### The Keys Table

The table below the generate form shows every key that has been created:

| Column | Meaning |
|--------|---------|
| Label | The friendly name you gave it |
| Key ID | A truncated identifier (not the key itself) |
| Created | When it was generated |
| Last Used | The most recent API call made with this key |
| Status | Active or Revoked |

### Revoking a Key

Click **Revoke** on any active key. You will be asked to confirm. Once
revoked, the key immediately stops working -- any system still using it
will start receiving `401 Unauthorized` responses.

Revocation is permanent. You cannot reactivate a revoked key.

---

## Resource Controls

The Resource Controls section (inside the Task Manager area) lets you tune
how MarkFlow uses your server's CPU and memory. These settings take effect
at different times:

### Worker Count

Sets how many files are converted in parallel during bulk jobs. The default
is 4. Increasing this speeds up large bulk runs but uses more CPU and
memory. The new value takes effect on the **next** bulk job start -- it does
not change a job that is already running.

Valid range: 1 to 32.

### Process Priority

Controls the OS-level scheduling priority of the MarkFlow process:

| Setting | Effect |
|---------|--------|
| Low | Yields CPU to other processes on the server |
| Normal | Default operating system scheduling |
| High | Prioritizes MarkFlow over other processes (may require root) |

This takes effect immediately.

> **Tip:** If MarkFlow shares its host with other services, set priority to
> **Low** during business hours and **Normal** overnight when conversions
> typically run unattended.

### CPU Core Pinning

Check or uncheck individual CPU cores to control which cores MarkFlow is
allowed to use. When "Use all available cores" is checked, MarkFlow can
run on any core. Pinning to specific cores is useful when you want to
reserve some cores for other applications.

This takes effect immediately, but note that core pinning is not supported
on all platforms. If it cannot be applied, MarkFlow will log a warning and
continue using all cores.

Click **Apply Changes** to save your selections. A confirmation message
appears briefly to let you know the settings were applied.

---

## Log Management

Two admin pages, linked from the Admin panel's **Log Management**
card, give you full control over MarkFlow's structured log files.

### Inventory page (`/log-management.html`)

A table of every log file currently on disk under `/app/logs`,
including the legacy `archive/` subdir. Each row shows:

- **File name** (active log, rotated backup, or compressed archive)
- **Size** in KB
- **Status pill** -- Active (currently being written), Rotated
  (numbered backup pending compression), or Compressed
  (`.gz` / `.tar.gz` / `.7z`)
- **Stream** -- Operational, Debug, or Other
- **Modified** timestamp

Top-bar actions:

- **Download** any file directly via its row link.
- **Multi-select + Download Selected (N)** bundles your picks
  into a single ZIP for offline review.
- **Download All** zips every log on disk.
- **Compress Rotated Now** triggers an immediate compression
  pass using your current Settings format. Useful right after a
  large bulk job rotates a debug log to dozens of MB.
- **Apply Retention Now** deletes compressed logs older than
  your retention window without waiting for the cron.

Settings card on the same page:

| Setting | Effect |
|---------|--------|
| Compression format | `gz` (default), `tar.gz`, or `7z`. As of v0.31.0 the cron honours this — earlier versions ignored it for the automated cycle. |
| Retention days | Compressed logs older than this are auto-purged on the cron. |
| Rotation max size MB | Active log file size at which the stdlib RotatingFileHandler triggers a rotation. Takes effect on next container restart. |

> **Tip:** The 6-hourly cron runs `compress_rotated_logs()` then
> `apply_retention()` automatically. If a rotated log is sitting
> uncompressed for hours and you can't wait, click **Compress
> Rotated Now**. That call is identical in effect to the cron
> body — same code path.

### Live viewer (`/log-viewer.html`) — v0.31.0 multi-tab edition

A power-user log inspector with **two modes** and **multiple
simultaneous tabs**.

#### Modes

- **Live tail** -- Server-Sent Events stream. Each new line
  appended to the file is pushed to the page in real time.
  Connection backfills the last ~200 lines so you don't open to
  a blank screen. The connection-state dot on each tab is green
  when connected, red when disconnected, grey while connecting.
  *Active uncompressed `.log` files only — compressed files
  return HTTP 400 (they don't grow, so tailing makes no sense).*
- **Search history** -- Server-side paginated search.
  Substring or regex query, level filter chips
  (DEBUG / INFO / WARNING / ERROR+CRITICAL), 200 lines per page,
  **Load older** for pagination.
  *Works on uncompressed AND `.gz` / `.tar.gz` AND `.7z` files
  (v0.31.0). Gzip streams are decompressed transparently via
  Python's stdlib; `.7z` archives are decompressed via the
  already-installed `7z` system binary streamed to stdout
  without writing a temp file. When opening a compressed file
  the viewer auto-switches to history mode (live tail can't
  follow a file that doesn't grow).*

##### Headless safety caps

The search request has a **triple-barrier defense** so an
unattended cron-style operation cannot hang on a malicious or
pathological log:

1. **Line cap** (500,000 lines) — bounds CPU on big files.
2. **Wall-clock cap** (60 seconds) — bounds time even when
   reads are cheap-per-line but the file is huge.
3. **`.7z` byte cap** (200 MB decompressed inside
   `_SevenZReader`) — bounds the worst-case worker-thread time
   on a deliberately huge archive. The 7z subprocess is launched
   in its own session so the cap-fire path can `SIGTERM` the
   whole process group cleanly.

When any cap fires, the response includes the partial results
plus a status line indicator. You'll see:

- `line cap hit` — narrow your search, tighten the filter chips,
  or shrink the time range.
- `time cap hit` — same advice; also consider opening the
  uncompressed counterpart if you're searching an archive.
- `7z stream truncated at 200 MB` — the archive is bigger than
  the in-process decompression budget; download it instead and
  use a desktop tool for full-file work. (A future release will
  let you tune this cap from the Settings card and add a live
  progress indicator while a search is in flight — see
  `docs/superpowers/plans/2026-04-25-v0.31.0-7z-safety-controls.md`.)

#### Tabbed view (new in v0.31.0)

The viewer now supports watching **multiple log streams
side-by-side** without losing state when you switch between them.

- The tab strip below the controls shows every open log, each
  with a connection-state dot, the file name, and a `×` close
  button.
- Click **+ Add tab** to open a popover listing all available
  logs. Click any one to open it in a new tab. Already-open logs
  are greyed out with a `✓ open` marker.
- Each tab keeps its own EventSource open in the background, so
  events don't get lost while you watch a different tab. (Body
  contents are capped at 1000 lines per tab so memory stays
  bounded — older lines drop off the head.)
- **Filters apply to the active tab only.** Switching tabs
  syncs the top control bar (mode, level chips, search box,
  time range, pause button) to that tab's stored state. So you
  can have a markflow.log tab filtered to ERROR only AND a
  markflow-debug.log tab showing everything — independently.
- Open tabs and per-tab filter state persist to `localStorage`.
  Refresh the page and your layout is restored.

##### Example workflow

1. Open `/log-viewer.html`. The most-recent log auto-opens in
   the first tab.
2. Click **+ Add tab**, pick `markflow-debug.log`. Two tabs
   now run in parallel.
3. Switch to the markflow.log tab, set mode → **Live tail**,
   uncheck DEBUG / INFO so you see only WARNING+.
4. Switch to markflow-debug.log, leave it on Live tail with
   all levels enabled.
5. Trigger the operation you're investigating. Both tabs
   accumulate events. Flip between them as needed — neither
   loses its state.

#### Time-range filter (history mode, new in v0.31.0)

When the active tab is in **Search history** mode, a second row
of controls appears with two `<input type="datetime-local">`
fields (From / To) plus four preset chips:

| Preset | Effect |
|--------|--------|
| Last hour | From = now − 1h, To = now |
| Last 24h | From = now − 24h, To = now |
| Last 7d | From = now − 7d, To = now |
| Clear range | Empties both inputs |

The inputs use your local timezone; values are converted to UTC
ISO before being sent to the server. The hint text next to the
chips shows the active From/To as ISO so you can verify exactly
what's being queried. Backend search supports flexible ISO
parsing — naive timestamps are treated as UTC.

#### Other features

- **Auto-scroll** chip auto-pins to the bottom on new lines.
  Uncheck to scroll freely without losing your place.
- **Pause** suspends new-line append on the active tab without
  closing the SSE stream. Resume picks up from where the buffer
  left off.
- **JSON-aware line parsing.** Structlog output (one JSON object
  per line) is rendered with colored timestamp / level / logger /
  event / k=v tail. Plain-text lines render verbatim.
- **Substring + regex search.** Toggle the **Regex** chip to
  switch from case-insensitive substring match to a regex.
  Invalid regex shows an error banner without breaking the page.

---

## System Info

At the bottom of the Admin page, the **System Info** card shows:

- **Version** -- the currently running MarkFlow version.
- **Auth Mode** -- either `JWT` (production) or `DEV_BYPASS` (local development).
- **Meilisearch** -- whether the search engine is reachable.
- **DB Size** -- the current database file size.
- **UnionCore Origin** -- the configured CORS origin for UnionCore integration.

If auth bypass is enabled, a yellow warning banner appears at the very top of
the Admin page as a reminder not to run in this mode in production.

---

## Related Articles

- [Resources & Monitoring](/help.html#resources-monitoring) -- CPU/memory charts
  and activity log
- [Status & Active Jobs](/help.html#status-page) -- monitoring running bulk jobs
- [Settings Reference](/help.html#settings-guide) -- every preference explained
- [Troubleshooting](/help.html#troubleshooting) -- common issues and fixes
