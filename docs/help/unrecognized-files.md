# Unrecognized Files

When MarkFlow scans a directory for bulk conversion, it encounters every type
of file -- not just the ones it can convert. Files that MarkFlow cannot handle
are cataloged as **unrecognized** so you have a complete picture of what is in
your repository.

This article explains how unrecognized files are detected, classified, and
presented.

---

## What Makes a File "Unrecognized"?

A file is marked unrecognized when the bulk scanner finds it and no format
handler is registered for its extension. MarkFlow supports 130+ extensions
across documents, images, media, archives, code, fonts, shortcuts, contacts,
binaries, and more. Everything else is unrecognized.

As of v0.20.2, common binary files (executables, DLLs, databases, disk images,
compiled bytecode, object files) are handled by the binary metadata handler and
will no longer appear as unrecognized.

Common examples of files that remain unrecognized:

- Game ROMs (NES, GBA)
- Proprietary formats without public specs
- Uncommon or vendor-specific file types

> **Tip:** Unrecognized does not mean "broken." These files are perfectly
> valid -- MarkFlow simply does not have a conversion handler for them yet.
> They are cataloged so you know they exist.

---

## How MIME Classification Works

When the scanner encounters an unrecognized file, it identifies the file type
using a two-step detection process:

### Step 1: Content-Based Detection (libmagic)

MarkFlow uses the `python-magic` library (a wrapper around libmagic) to read
the first bytes of the file and determine its MIME type based on its actual
content, not just its extension. This correctly identifies files even if they
have the wrong extension.

For example, a JPEG image renamed to `.dat` will still be detected as
`image/jpeg`.

### Step 2: Extension Fallback

If libmagic cannot determine the type (returns `application/octet-stream`),
MarkFlow falls back to a built-in extension mapping. The file extension is
matched against a table of known extensions to assign a category.

If both steps fail, the file is classified as `application/octet-stream` with
category **unknown**.

> **Warning:** MIME detection never crashes the scanner. If something goes
> wrong during detection (permissions error, corrupted file header), the file
> is still cataloged with a fallback type. No file is skipped due to a
> detection failure.

---

## File Categories

Every unrecognized file is assigned to one of these categories based on its
detected MIME type or extension:

| Category | Examples | Description |
|----------|----------|-------------|
| `disk_image` | .iso, .vmdk, .vhd, .img, .dmg | Virtual disk and disk image files |
| `raster_image` | .jpg, .png, .tiff, .bmp, .gif, .webp, .heic | Bitmap image files |
| `vector_image` | .svg, .eps | Vector graphic files |
| `video` | .mp4, .mkv, .mov, .avi, .wmv, .webm | Video files |
| `audio` | .mp3, .wav, .flac, .aac, .ogg, .wma | Audio files |
| `archive` | .zip, .tar, .gz, .7z, .rar, .cab | Compressed archive files |
| `executable` | .exe, .msi, .dll, .so | Binary executables and libraries (now handled by binary handler as of v0.20.2) |
| `database` | .sqlite, .db, .mdb, .accdb | Database files (now handled by binary handler as of v0.20.2) |
| `font` | .ttf, .otf, .woff, .woff2 | Font files |
| `code` | .py, .js, .ts, .cpp, .java, .html, .css, .json, .xml, .sql | Source code and configuration files |
| `unknown` | Anything unmatched | Files that could not be classified |

Categories are used for filtering and reporting. They do not change how the
file is handled -- all unrecognized files are cataloged the same way regardless
of category.

---

## What MarkFlow Records

For each unrecognized file, the database stores:

| Field | Description |
|-------|-------------|
| Source path | Full path on the source share |
| File extension | The original extension (e.g., `.mp4`) |
| MIME type | Detected MIME type (e.g., `video/mp4`) |
| Category | One of the categories listed above |
| File size | Size in bytes |
| Job ID | Which bulk job discovered this file |
| Status | Always `unrecognized` |

No Markdown output is created. No Meilisearch entry is added. The file
exists only as a database record for inventory purposes.

> **Tip:** Unrecognized files are cataloged once and then excluded from
> future conversion queues. If MarkFlow adds a handler for a new format
> in the future, you would need to reset those files' status to `pending`
> to include them in a new conversion run.

---

## The Unrecognized Files Page

Navigate to **/unrecognized.html** to view all cataloged unrecognized files.
This page is available to users with the **Manager** role or higher.

### Category Cards

At the top of the page, a row of cards shows each category with its file
count and total size. Click a card to filter the table below to just that
category.

### Filter Bar

Below the category cards, three dropdown filters let you narrow the list:

| Filter | Options |
|--------|---------|
| **Category** | All categories, or select a specific one |
| **Format** | All formats, or select a specific extension |
| **Job** | All jobs, or select a specific bulk job |

Filters combine with each other. For example, you can show only `.mp4` video
files from a specific job.

### File Table

The main table shows:

- **File Path** -- the full source path
- **Format** -- the file extension
- **Category** -- the assigned category
- **Size** -- human-readable file size
- **Job** -- which bulk job found this file

The table is paginated. Use the controls at the bottom to navigate pages.

### Stats Row

A summary bar above the category cards shows the total count of unrecognized
files and the total size across all categories.

---

## CSV Export

Click the **Export CSV** button in the filter bar to download a spreadsheet
of all matching files. The CSV includes:

- `source_path`
- `source_format`
- `mime_type`
- `file_category`
- `file_size_bytes`
- `job_id`

The export respects your current filters. If you have a category or format
filter active, only matching files appear in the CSV.

The downloaded file is named `markflow-unrecognized-YYYYMMDD.csv` with
today's date.

> **Tip:** The CSV export is useful for handing off to another team. If your
> video team needs to know which MP4 files are in the repository, filter by
> category "video," export, and send the CSV.

---

## Bulk Progress Integration

During a bulk job, the progress display on the **Bulk** page shows an
**Unrecognized** count pill alongside the Converted, Failed, and Skipped
counts. This tells you at a glance how many files in the source directory
are outside MarkFlow's conversion scope.

---

## API Endpoints

The unrecognized files system exposes three API endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/unrecognized` | GET | Paginated list with `job_id`, `category`, `source_format`, `page`, `per_page` query params |
| `/api/unrecognized/stats` | GET | Summary counts and sizes grouped by category |
| `/api/unrecognized/export` | GET | CSV download with the same filter params |

All endpoints require the **Manager** role.

### MCP Tool

If you use the Claude integration, the `list_unrecognized` MCP tool lets
Claude query unrecognized files on your behalf. Claude can filter by category
and format, making it easy to ask questions like "How many video files are in
the marketing share?"

---

## Frequently Asked Questions

### Can I convert unrecognized files manually?

Not through MarkFlow. These files need their native application or a
specialized tool. MarkFlow's role is to tell you they exist so nothing
falls through the cracks.

### Will future MarkFlow versions convert more formats?

Possibly. When a new format handler is added, files of that type will need
their status reset from `unrecognized` to `pending` before the next bulk
job picks them up.

### Why are code files (`.py`, `.js`) listed as unrecognized?

MarkFlow converts documents, not source code. While a `.py` file is plain
text, it is not a document format that benefits from the Markdown conversion
pipeline. Code files are cataloged so you know they are present in your
repository.

### Do unrecognized files count against disk usage?

The files themselves stay on the source share and are not copied anywhere by
MarkFlow. Only the small database record counts toward MarkFlow's own
storage. The disk usage dashboard on the Admin page does not include
unrecognized files in its totals.

---

## Related

- [Adobe Files](/help#adobe-files) -- how creative files are indexed at Level 2
- [Settings Guide](/help#settings-guide) -- configuring bulk jobs and the scanner
- [Status Page](/help#status-page) -- monitoring active jobs and their unrecognized counts
