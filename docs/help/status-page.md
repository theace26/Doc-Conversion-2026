# Status & Active Jobs

The Status page shows you everything that's currently happening in MarkFlow — running jobs, their progress, and controls to pause, resume, or stop them.

## The Status Page

Click **Status** in the navigation bar. You'll see a count badge showing the number of active jobs.

The page shows a card for each running or recently completed job:

- **Progress bar** — how far through the file list the job is
- **File counts** — converted, failed, skipped, and remaining
- **Active workers** — which files each worker is currently processing
- **Per-directory stats** — breakdown by top-level subdirectory in the source share
- **Duration** — how long the job has been running

## Job Controls

Each job card has controls:

| Button | What It Does |
|--------|-------------|
| **Pause** | Stops processing new files. Workers finish their current file then wait |
| **Resume** | Continues a paused job from where it left off |
| **Stop** | Cancels the job. Workers finish their current file then exit |

> **Tip:** Pause is useful when you need to free up system resources temporarily. The job picks up right where it left off.

## STOP ALL

At the top of the status page, there's a **STOP ALL** button. This:

1. Sets a global stop flag
2. Cancels all running bulk jobs
3. Stops the lifecycle scanner if it's running
4. Workers finish their current file (they don't abandon mid-conversion)

After stopping, you need to click **Reset** before starting new jobs.

> **Warning:** STOP ALL affects every running job. Use the per-job Stop button if you only want to cancel one.

## Pipeline Card (since v0.33.0)

Below the active jobs, the Status page shows a single **Pipeline** card —
the canonical view of the background scan + auto-conversion pipeline.
It replaces the old separate "Lifecycle Scanner" and "Pending" cards
that used to live here.

The card has a status pill (Running / Idle / Paused / Disabled) and six
cells:

| Cell | What it tells you |
|------|-------------------|
| **Mode** | Off / Immediate / Queued / Scheduled — what the pipeline does when new files appear. Hover for the scheduler's full reasoning |
| **Last Scan** | Time of the most recent scan + status pill (✓ Completed / ⚠ Interrupted / ✗ Failed / ⟳ Running) + scanned/new/modified counts |
| **Next Scan** | When the next scheduled scan fires + scan type (e.g. "Pipeline scan · every 45 min") |
| **Source Files** | Total files known on disk |
| **Pending** | Files awaiting conversion |
| **Interval** | Time between scheduled scans |

Three action buttons sit on the card:

- **Pause / Resume** — pause the scheduler (in-flight jobs continue)
- **Run Now** — kick off a manual scan + convert immediately
- **Rebuild Index** — rebuild the search index from scratch

> **Where did the old "Lifecycle Scanner" card go?**
> Its data is now in the Pipeline card's Last Scan cell.
> Same numbers, single source of truth, no drift between cards.

## Click the scan banner to enlarge it (since v0.33.0)

When a background scan is running, an orange banner shows at the top
of every page:

```
⟳ Background scan running — 21,529 / ~31,000 files (69%) · ~12 min remaining
```

**Click the banner** (or focus it with Tab and press Enter) to open
a detail modal with run-id, scanned-vs-total with progress bar,
ETA, elapsed time, current file path, last-update-age, and a link
to the scanner log. Press **Escape** or click outside the modal to
close.

## The Nav Badge

The Status link in the navigation bar shows a small number badge indicating how many jobs are currently active. When a stop is requested, the badge pulses red.

## Related

- [Bulk Repository Conversion](/help.html#bulk-conversion)
- [File Lifecycle & Versioning](/help.html#file-lifecycle)
- [Administration](/help.html#admin-tools)
