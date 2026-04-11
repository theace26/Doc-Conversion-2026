# Auto-Conversion

Auto-conversion is MarkFlow's automatic decision engine for handling new and changed files. When the lifecycle scanner finds files that need converting, the auto-conversion engine decides **when** to run them, **how many** workers to use, and **how big** each batch should be — all based on the current mode, schedule, and system load.

This article explains the available modes, how scheduling works, and how to tune the engine for your environment.


## What Is Auto-Conversion?

The lifecycle scanner walks the source repository looking for new, modified, moved, and deleted files. When it finds work to do, it does **not** convert them itself — it hands them off to the auto-conversion engine.

The auto-conversion engine decides:

- **When** to start: immediately, only during business hours, or only during scheduled windows
- **How many workers** to use: a fixed count or auto-sized based on system pressure
- **How big** each batch should be: a fixed size or auto-sized

This separation lets the scanner run continuously without overloading the server during peak hours.

> **Tip:** Auto-conversion only fires for files the lifecycle scanner detects. To convert a known directory on demand, start a manual bulk job from the **Bulk Jobs** page instead.


## Mode

The mode controls **when** auto-conversion runs. Set it on the **Settings** page under "Auto-Conversion".

| Mode             | Behavior                                                                       |
|------------------|--------------------------------------------------------------------------------|
| **Immediate**    | Convert as soon as the scanner finds new files (default)                       |
| **Business Hours** | Only convert during the configured business-hours window                     |
| **Scheduled**    | Only convert during explicit schedule windows you define                       |
| **Manual**       | Never auto-convert — files wait until you start a job manually                 |

### Immediate Mode

The default. As soon as the lifecycle scanner finishes a scan and has new files to process, the auto-converter starts a bulk job.

Use this when:

- The server is dedicated to MarkFlow
- You want results as quickly as possible
- System load is not a concern

### Business Hours Mode

Auto-conversion only runs between the **Business Hours Start** and **Business Hours End** times set on the Settings page (defaults: 9:00 AM - 6:00 PM).

Files discovered outside business hours queue up and convert when the window opens.

Use this when:

- The server is shared with other workloads
- You want predictable conversion timing
- Off-hours should be reserved for backups or maintenance

### Scheduled Mode

Like Business Hours mode, but with multiple custom windows. Configure them in the **Schedule Windows** field on the Settings page.

Use this when:

- You have multiple maintenance windows per day
- Conversion should only run during specific time slots (e.g., overnight on weekends)
- Business hours are not a single contiguous block

### Manual Mode

Disables auto-conversion entirely. The lifecycle scanner still runs and tracks changes, but conversions only happen when you start a bulk job by hand.

Use this when:

- You want full control over every conversion
- You are testing or troubleshooting
- The pipeline is paused for an extended period

> **Tip:** Manual mode does not stop the scanner. The pending file count keeps growing as new files are discovered. Switch back to Immediate (or run a manual bulk job) to clear the backlog.


## Workers

The **Workers** setting controls how many files the auto-converter processes in parallel.

| Value         | What it means                                                          |
|---------------|------------------------------------------------------------------------|
| `auto`        | Sized based on CPU count and current system pressure (recommended)     |
| `1` - `16`    | Fixed worker count                                                     |

More workers means faster throughput but higher CPU and memory use. The `auto` setting watches system load and adjusts dynamically — it backs off when CPU/memory pressure climbs and ramps up when the system is idle.

> **Tip:** Start with `auto`. Only set a fixed value if you need predictable resource usage (for example, if MarkFlow shares the server with other applications).


## Batch Size

The **Batch Size** controls how many files each auto-conversion run processes in a single bulk job.

| Value     | What it means                                                                  |
|-----------|--------------------------------------------------------------------------------|
| `auto`    | Engine picks a size based on the pending count and recent throughput           |
| `1` - `N` | Fixed batch size                                                              |

A small batch finishes quickly but means more overhead (each batch starts a new bulk job). A large batch is more efficient but ties up workers longer.

The **Conservative Factor** (default 0.7) shrinks the auto-calculated batch size to leave headroom. Higher = smaller batches.


## The Pipeline Master Switch

Auto-conversion is part of the broader **Pipeline** — the umbrella system that includes the lifecycle scanner, auto-converter, and search indexer.

The **Pipeline Enabled** toggle on the Settings page is the master kill switch. When off:

- The lifecycle scanner does not run
- Auto-conversion does not fire
- Search indexing is paused

Use the Pipeline toggle to halt **all** background activity. Use the Auto-Conversion **Mode = Manual** setting to halt only conversions while keeping the scanner running.

> **Warning:** When the pipeline is disabled, MarkFlow logs a warning every hour and an error daily. After 3 days (configurable via `pipeline_auto_reset_days`), it auto-re-enables. This prevents accidentally leaving the pipeline off forever.


## Decision Logging

The auto-conversion engine logs every decision it makes — why it ran, why it skipped, what batch size it picked, and which workers it used. The verbosity is controlled by the **Decision Log Level** setting:

| Level       | What gets logged                                                             |
|-------------|------------------------------------------------------------------------------|
| `quiet`     | Only major events (job started, job failed)                                  |
| `normal`    | Decisions plus reasoning                                                     |
| `elevated`  | Everything in normal plus pressure metrics and timing (default)              |
| `verbose`   | Full diagnostic detail — useful when troubleshooting                         |

Decision logs are written to `logs/markflow.log` and tagged `auto_converter.*` for easy filtering.


## Run Now

The **Run Now** button on the Status page bypasses both the schedule and the pipeline pause flag. It immediately triggers a one-shot conversion of any pending files.

Use Run Now when:

- You want to flush the backlog without waiting for the next window
- Mode is set to Manual but you want to convert pending files anyway
- You just changed settings and want to verify they work

Run Now respects the current Workers and Batch Size settings.


## How It Interacts with Manual Bulk Jobs

Auto-conversion and manual bulk jobs share the same worker pool. The scan coordinator enforces priorities:

| Priority | Job type           | Behavior                                                       |
|----------|--------------------|----------------------------------------------------------------|
| 1        | Manual bulk job    | Highest priority — cancels in-progress lifecycle scans         |
| 2        | Run Now            | Bypasses pause flags, runs immediately                          |
| 3        | Auto-conversion    | Respects mode, schedule, and pressure metrics                  |
| 4        | Lifecycle scan     | Lowest — yields to all other activity                          |

If you start a manual bulk job while auto-conversion is running, the manual job takes priority. If you start a manual job during a lifecycle scan, the scan is cancelled (cleanly) so the manual job can begin.


## Troubleshooting

**Auto-conversion never runs even though files are pending.**
Check the Pipeline Enabled toggle on the Settings page. If it's off, no auto-conversions will fire. Also check the Mode — if it's Manual, files will queue indefinitely.

**Auto-conversion runs at unexpected times.**
Check the Mode and Business Hours / Schedule Window settings. If multiple machines share the same source share, only one MarkFlow instance should be running auto-conversion.

**Conversions are slow.**
Check the Workers setting. If it's `auto`, system pressure may be capping the worker count — open the Resources page to see CPU and memory utilization. If it's a fixed low number, raise it.

**Pipeline keeps re-enabling itself.**
This is intentional. After `pipeline_auto_reset_days` (default 3) of being disabled, the pipeline auto-re-enables to prevent accidental long-term shutdown. To disable it permanently, switch the Mode to Manual instead.


## Related

- [Bulk Conversion](/help.html#bulk-conversion)
- [File Lifecycle](/help.html#file-lifecycle)
- [Status & Active Jobs](/help.html#status-page)
- [Settings Reference](/help.html#settings-guide)
- [Resources & Monitoring](/help.html#resources-monitoring)
