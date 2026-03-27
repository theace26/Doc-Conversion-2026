# Resources & Monitoring

The Resources page is where you go to understand how MarkFlow is using your
server's hardware -- and whether it needs more or less. It tracks CPU, memory,
and disk usage over time and keeps a log of every significant event. You can
reach it from the navigation bar by clicking **Resources** (requires the
**Manager** role or higher).

The page is divided into six sections, each designed to answer a different
question.

---

## Executive Summary Card

At the very top of the page, the executive summary gives you four KPI cards
and a paragraph of plain-language description:

| Card | What It Shows |
|------|---------------|
| CPU | Average process CPU usage over the last 30 days, plus peak and idle baseline |
| Memory | Average RSS (resident set size) in MB or GB, plus percentage of system total |
| Disk | Current total MarkFlow footprint on disk, with daily growth rate and free space |
| Uptime | How long the container has been running since last restart |

### The Summary Description

Below the cards is an italicized paragraph that reads like something you could
paste into an email or a status report. For example:

> *MarkFlow averaged 12.3% CPU over 30 days with a peak of 74.1% during
> bulk jobs. Memory usage is stable at 380 MB (4.7% of 8 GB). Disk
> footprint is 2.4 GB, growing at 18 MB/day with 45.2 GB free.*

These sentences are generated from the actual metrics data. They are
designed for the "IT pitch" -- when you need to justify MarkFlow's resource
consumption to infrastructure or management teams, you can copy this text
directly.

> **Tip:** The summary looks at the last 30 days by default. If MarkFlow was
> recently deployed, the numbers will stabilize after a week or two of regular
> use.

### Self Governance

If the summary detects resource pressure (e.g., CPU consistently above 70%
or memory above 80%), a note appears below the description with a suggestion,
such as reducing worker count or scheduling heavy conversions overnight.

---

## Historical Charts -- CPU and Memory

The **Historical Metrics** section shows two side-by-side line charts:

### CPU Usage Chart

- **MarkFlow CPU %** (solid line) -- the process-level CPU usage.
- **System CPU %** (dashed line) -- the overall machine CPU usage.
- Lightly shaded vertical bands mark time periods when a bulk job was active,
  so you can see how conversions correlate with CPU spikes.

### Memory Usage Chart

- **MarkFlow RSS in MB** (solid line, left axis) -- how much physical memory
  the process is using.
- **System Memory %** (dashed line, right axis) -- how full the machine's
  total memory is.

### Time Range Selector

Both charts share a time range picker with six options:

| Button | Period |
|--------|--------|
| 1h | Last hour (finest granularity) |
| 6h | Last 6 hours |
| 24h | Last 24 hours (default) |
| 7d | Last 7 days |
| 30d | Last 30 days |
| 90d | Last 90 days |

Click a button to reload the charts for that range. Shorter ranges show more
data points, so you can zoom in on a specific event.

> **Tip:** If the charts say "No metrics data yet," wait about 30 seconds.
> MarkFlow begins collecting data points shortly after startup.

### Tooltip Details

Hover over any point on the CPU chart to see a tooltip that includes context
about what MarkFlow was doing at that moment -- for example, "Bulk job
active" or "3 conversion(s)."

---

## Disk Growth Chart

The **Disk Growth** section shows a stacked area chart tracking storage
consumption over time, broken into six layers:

| Layer | What It Represents |
|-------|--------------------|
| Output Repo | Bulk-converted Markdown knowledge base |
| Trash | Soft-deleted files waiting for purge |
| Database | SQLite database and WAL |
| Logs | Operational and debug log files |
| Meilisearch | Full-text search index data |
| Conv. Output | Single-file conversion results |

The chart has its own range selector: **7d**, **30d** (default), or **90d**.

Use this to spot trends. If the Trash layer is growing while Output Repo
stays flat, it means files are being deleted faster than they are being
purged. If the Database layer is ballooning, you may need a database
compaction.

> **Tip:** The first disk snapshot is taken at startup and then every 6 hours.
> On a fresh installation, you will see a single data point until the next
> snapshot is recorded.

---

## Live System Metrics

The **Live System Metrics** section provides a real-time view of what the
server is doing right now. Data refreshes automatically every 2 seconds and
pauses when the browser tab is in the background to save resources.

### CPU Panel

Shows a vertical bar for each logical CPU core. The bar height and color
indicate current usage:

- Green (under 50%)
- Yellow/orange (50--80%)
- Red (above 80%)

Below the bars, a note tells you whether MarkFlow is using all cores or is
pinned to specific ones. Core pinning is configured on the
[Admin page](/help#admin-tools).

### Memory Panel

A horizontal progress bar showing current memory usage as a percentage.
Below it you will see the raw numbers: used / total / available.

### Threads Panel

A single large number showing how many active threads the MarkFlow process
is running. This rises during bulk conversions (each worker uses a thread)
and during lifecycle scans.

---

## Activity Log

The **Activity Log** is a timestamped table of significant events in your
MarkFlow installation. Each row shows when something happened, what kind
of event it was, and a human-readable description.

### Event Types

| Badge Color | Event Types |
|-------------|-------------|
| Blue | `bulk_start`, `bulk_end` -- a bulk job started or finished |
| Yellow | `lifecycle_scan_start`, `lifecycle_scan_end` -- the file scanner ran |
| Indigo | `db_maintenance`, `index_rebuild` -- scheduled maintenance tasks |
| Purple | `startup`, `shutdown` -- container lifecycle events |
| Red | `error` -- something went wrong |

### Filtering

Use the **dropdown** above the table to filter by event category:

- All Events (default)
- Bulk Jobs
- Lifecycle
- Maintenance
- Errors
- System

The **time range selector** controls how far back the log reaches: 24 hours,
7 days (default), 30 days, or 90 days.

### Expanding Rows

Click any row to expand it and see the raw metadata for that event in a
monospaced block. This is useful for debugging -- for example, a `bulk_end`
event includes the final file counts and duration.

> **Tip:** If you are investigating a specific incident, filter to **Errors**
> and set the range to **24h** to quickly find what went wrong.

---

## Repository Overview

At the bottom of the Resources page is a compact copy of the Repository
Overview from the Admin page. It shows five KPI cards: Total Files,
Converted, Unrecognized, Failed, and Search Index count.

Click **Refresh** to reload these numbers. This section is included so that
managers who do not have Admin access can still see the headline repository
statistics.

---

## Exporting Data as CSV

In the top-right corner of the Executive Summary section, the **Export CSV**
dropdown lets you download raw data for further analysis. Three exports are
available:

| Export | Contents |
|--------|----------|
| System Metrics | Timestamped CPU and memory readings |
| Disk Metrics | Timestamped disk usage snapshots by component |
| Activity Events | The full activity log for the selected period |

Each export covers the last 30 days. The CSV files open in Excel,
Google Sheets, or any spreadsheet application.

> **Tip:** The CSV exports are useful for capacity planning reports. Download
> the disk metrics once a month to track growth trends over quarters.

---

## Related Articles

- [Administration](/help#admin-tools) -- API keys, database tools,
  resource controls
- [Status & Active Jobs](/help#status-page) -- monitoring running bulk jobs
- [Settings Reference](/help#settings-guide) -- adjusting worker count,
  scanner intervals, and log levels
- [Troubleshooting](/help#troubleshooting) -- common issues and fixes
