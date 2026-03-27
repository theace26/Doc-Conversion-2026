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

- [Resources & Monitoring](/help#resources-monitoring) -- CPU/memory charts
  and activity log
- [Status & Active Jobs](/help#status-page) -- monitoring running bulk jobs
- [Settings Reference](/help#settings-guide) -- every preference explained
- [Troubleshooting](/help#troubleshooting) -- common issues and fixes
