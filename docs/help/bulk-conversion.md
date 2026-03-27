# Bulk Conversion

Bulk conversion lets you convert entire folders of documents at once — hundreds or thousands of files in a single job. Instead of uploading files one at a time through the Convert page, you point MarkFlow at a directory and let it work through everything automatically.

This article covers how to set up locations, start a bulk job, monitor its progress, and manage running jobs.


## What Is Bulk Conversion?

Single-file conversion (the Convert page) is great for one or two documents. But when you have a shared drive with thousands of Word documents, PDFs, and spreadsheets that all need converting, you need bulk mode.

Bulk conversion:

- Scans an entire directory tree for supported files
- Queues all discovered files for conversion
- Processes multiple files at the same time using parallel workers
- Writes output to a structured output directory that mirrors the source folder layout
- Tracks progress with a live dashboard
- Lets you pause, resume, or cancel at any time

> **Tip:** Bulk conversion is designed for large jobs that might run for hours. You can start a job and come back later — it keeps running in the background even if you close your browser.


## Setting Up Locations

Before starting a bulk job, you need to tell MarkFlow where to find the source files and where to put the output. These are called **Locations**.

### What Is a Location?

A location is a friendly name for a directory path. Instead of typing `/mnt/source/department/finance` every time you start a job, you create a location called "Finance Documents" that points to that path.

### Creating a Location

1. Go to **Settings** and click the link to manage Locations. (You can also reach the Locations page from the Bulk page.)
2. Click **Add Location**.
3. Fill in the fields:

| Field        | What to enter                                                    |
|--------------|------------------------------------------------------------------|
| **Name**     | A friendly name (e.g., "Finance Documents" or "Marketing Share") |
| **Path**     | The directory path inside the container                          |
| **Type**     | Source, Output, or Both                                          |

4. Click **Save**.

### Using the Folder Picker

You do not need to type paths by hand. Click the folder icon next to the path field to open the **Folder Picker** — a visual directory browser that lets you navigate through available drives and folders.

The Folder Picker shows:

- Available drives (mounted from your Windows system)
- Folders you can navigate into by clicking
- An item count for each folder (when available)
- A **Select** button to choose the current folder

> **Warning:** Only directories that have been mounted into the MarkFlow container are browsable. If you do not see your drive, ask your administrator to add it to the Docker configuration. See your team's setup documentation for details.

### Location Types

| Type       | What it means                                                     |
|------------|-------------------------------------------------------------------|
| **Source** | A directory containing files you want to convert (read-only)      |
| **Output** | A directory where converted results will be written               |
| **Both**   | Can be used as either source or output                            |

> **Tip:** Source locations are read-only — MarkFlow never modifies or deletes files in your source directory. Originals are always safe.


## Starting a Bulk Job

Once your locations are set up:

1. Go to the **Bulk** page from the navigation bar.
2. Select a **Source Location** from the dropdown.
3. Select an **Output Location** from the dropdown.
4. Click **Start Job**.

MarkFlow immediately begins scanning the source directory.


## The Scan Phase

Before any files are converted, MarkFlow scans the source directory to discover what needs processing. This is the scan phase.

### What Happens During Scanning

1. MarkFlow walks through every folder and subfolder in the source location.
2. Each file is checked against the list of supported formats.
3. Supported files are added to the job queue.
4. Unsupported files are cataloged as "unrecognized" (not an error — they are just noted).
5. Path safety checks run to catch any issues before conversion starts.

### Scan Progress

The Bulk page shows a progress indicator during scanning:

| Element             | What it shows                                              |
|---------------------|------------------------------------------------------------|
| **File count**      | Number of files discovered so far                          |
| **Progress bar**    | Percentage of the estimated total scanned                  |
| **Current file**    | The file currently being examined                          |

> **Tip:** For very large directories (100,000+ files), the initial file count estimate may show as indeterminate. This is normal — the estimate resolves as scanning progresses.

### Path Safety Checks

After discovering files, MarkFlow runs safety checks:

- **Path length** — Catches files whose output path would exceed the system maximum (240 characters by default).
- **Name collisions** — Detects when two different source files would produce the same output filename (e.g., `report.docx` and `report.pdf` both become `report.md`).
- **Case collisions** — Finds files that differ only by uppercase/lowercase in their names.

If issues are found, MarkFlow resolves them automatically based on the configured strategy (usually by adding the original extension to the filename, like `report.pdf.md`). A summary of any issues is included in the job manifest.


## The Conversion Phase

Once scanning completes, the conversion phase begins. This is where the actual work happens.

### Parallel Workers

MarkFlow processes multiple files at the same time using **workers**. Think of workers as separate assistants who each handle one file at a time. When a worker finishes a file, it picks up the next one from the queue.

The number of workers is controlled by the **Worker Count** setting:

| Worker Count | What it means                                            |
|--------------|----------------------------------------------------------|
| 1            | One file at a time (slowest, uses least resources)       |
| 2 (default)  | Two files in parallel                                   |
| 4            | Four files in parallel (faster, uses more CPU and memory)|
| 8            | Eight files in parallel (fastest, resource-intensive)    |

> **Tip:** More workers means faster completion, but also more strain on the server. If the server is shared with other applications, keep the worker count low. Your administrator can adjust this in Settings or on the Admin page.

### Active Workers Display

During conversion, the Bulk page shows a panel with one row per active worker. Each row displays the filename that worker is currently processing. This lets you see at a glance what is happening.

### Per-Directory Stats

For bulk jobs that span many subdirectories, the progress display includes a breakdown of how many files have been processed in each top-level subdirectory. This helps you track which parts of the source tree are done.

### What Happens to Each File

Every file in the queue goes through the same pipeline as a single-file conversion:

1. Validate the file
2. Read its content
3. Build the internal model
4. Extract styles
5. Generate Markdown output
6. Save metadata and sidecar
7. Record in history and search index

Files that fail do not stop the job. The worker logs the error and moves on to the next file.


## Pause, Resume, and Cancel

You can control a running bulk job from the **Status** page (click "Status" in the navigation bar).

### Pause

Pausing a job stops workers from picking up new files. Any file currently being processed will finish first. The job stays in a paused state until you resume it.

Use pause when:

- The server needs resources for other work
- You want to check intermediate results before continuing
- You need to adjust settings (like worker count) mid-job

### Resume

Resuming a paused job tells workers to start picking up files again from where they left off. No work is lost — files that were already converted stay converted.

### Cancel

Canceling a job stops it permanently. Workers finish their current files and then stop. The job cannot be resumed after cancellation.

Already-converted files from the canceled job are kept in the output directory. You do not lose completed work.

> **Warning:** Canceling a large job means you would need to start a new job to convert the remaining files. MarkFlow tracks which files have already been converted, so a new job scanning the same source directory will only process files that have not been done yet.

### Stop All

The Status page also has a **Stop All** button that immediately signals every running job to stop. Use this if you need to free up the server urgently. The stop signal is cooperative — each worker finishes its current file before stopping.

After using Stop All, you must reset the stop flag before starting new jobs. The Status page shows a banner with a reset button when the stop flag is active.


## Monitoring from the Status Page

The Status page gives you a complete view of all running and recent jobs. Each job appears as a card showing:

| Element              | What it shows                                              |
|----------------------|------------------------------------------------------------|
| **Job name**         | Source and output locations                                 |
| **Progress bar**     | Files completed out of total                               |
| **Status**           | Scanning, Converting, Paused, Completed, Cancelled, Failed |
| **Active workers**   | Which files are currently being processed                  |
| **Directory stats**  | Per-subdirectory completion counts                         |
| **Controls**         | Pause, Resume, Stop buttons                                |

The Status link in the navigation bar shows a badge with the number of active jobs. If a stop has been requested, the badge pulses red.

> **Tip:** You can monitor jobs from any page — the badge in the navigation bar always shows the current count. Click it to go to the full Status page for details.


## Lifecycle Scanner

In addition to jobs you start manually, MarkFlow runs an automatic **lifecycle scanner** that periodically checks the source directory for changes. This is separate from bulk jobs — it detects new, modified, moved, and deleted files.

The lifecycle scanner status appears on the Status page as its own card, showing when the last scan ran and whether one is currently in progress.

For full details on what the lifecycle scanner does, see [File Lifecycle](/help#file-lifecycle).


## Bulk Job Settings

These settings affect bulk conversion behavior:

| Setting                        | What it controls                                     | Default | Where to change |
|--------------------------------|------------------------------------------------------|---------|-----------------|
| **Worker Count**               | Number of parallel conversion workers                | 2       | Settings or Admin |
| **OCR Confidence Threshold**   | Below this, PDFs are skipped to the review queue     | 60      | Settings        |
| **Unattended Mode**            | Accept all OCR text without review prompts           | Off     | Settings        |
| **Scanner Enabled**            | Whether the automatic lifecycle scanner runs         | On      | Settings        |
| **Scanner Interval (minutes)** | How often the lifecycle scanner checks for changes   | 15      | Settings        |

> **Tip:** If you are running a very large bulk job and want maximum speed, temporarily increase the worker count and enable unattended mode. Remember to restore your preferred settings afterward.


## After the Job Completes

When a bulk job finishes:

- **Output directory** — Converted files are organized in a structure mirroring the source. Each file has its Markdown, sidecar, and original alongside it.
- **History** — Every converted file appears in the History page, searchable and filterable.
- **Search index** — All converted content is indexed for full-text search (see [Search](/help#search)).
- **Review queue** — If any PDFs were skipped for OCR review, a link to the Bulk Review page appears.
- **Unrecognized files** — Files without a supported format are cataloged separately. You can view them on the Unrecognized Files page.

### The Manifest

Each bulk job produces a manifest file (JSON) summarizing the job: total files, successes, failures, skipped files, path issues resolved, and timing information.


## Common Questions

**Can I run multiple bulk jobs at the same time?**
Yes, but they share the same pool of workers. Two jobs with 2 workers each will effectively run 2 workers total, alternating between jobs. For best performance, run one large job at a time.

**What if the server restarts during a job?**
The job stops. Already-converted files are preserved. Start a new job pointing at the same source directory — MarkFlow will skip files that have already been converted.

**Can I convert the same source directory twice?**
Yes. MarkFlow detects previously converted files by tracking their modification times. Unchanged files are skipped. Modified files are re-converted.

**How long does a bulk job take?**
It depends on the number of files, their sizes, and whether OCR is needed. As a rough guide: a folder of 1,000 Word documents with 2 workers takes about 20-30 minutes. A folder of 1,000 scanned PDFs takes much longer due to OCR.


## Related

- [Getting Started](/help#getting-started)
- [Document Conversion](/help#document-conversion)
- [OCR Pipeline](/help#ocr-pipeline)
- [Search](/help#search)
- [File Lifecycle](/help#file-lifecycle)
