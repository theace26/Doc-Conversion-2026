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

## Lifecycle Scanner Card

The status page also shows the lifecycle scanner status:

- Whether it's currently running
- How many files it has scanned
- Progress percentage and estimated time remaining
- When the last scan completed

## The Nav Badge

The Status link in the navigation bar shows a small number badge indicating how many jobs are currently active. When a stop is requested, the badge pulses red.

## Related

- [Bulk Repository Conversion](/help#bulk-conversion)
- [File Lifecycle & Versioning](/help#file-lifecycle)
- [Administration](/help#admin-tools)
