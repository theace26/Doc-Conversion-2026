# Settings Reference

The Settings page lets you configure how MarkFlow behaves. Click
**Save** at the top of each section to commit changes. Some settings
require the **Manager** role.

As of v0.23.4 the 21 sections are grouped into logical clusters. The
three top-level groups are:

- **Files and Locations** — where MarkFlow reads files from and how
  it handles per-file concerns
- **Conversion Options** — how files get turned into Markdown
- **AI Options** — everything that touches an LLM provider

Use **Expand All / Collapse All** in the page header to open or
close every section at once. Only **Files and Locations** and
**Conversion Options** are open by default.

---

## Files and Locations

The starting point for every pipeline action.

| Setting | What It Does |
|---------|--------------|
| Source locations | Paths MarkFlow scans for files (add / edit / delete) |
| Output directory | Where converted Markdown is written |
| Excluded paths | Prefix-match directories to drop from the catalog — adding an exclusion will mark every existing file under it for deletion (36h grace → trash → 60d retention). See [File Lifecycle](/help.html#file-lifecycle) for the full cascade |
| Check access | Verify MarkFlow can read each configured source |

### Password Recovery

How MarkFlow handles password-protected documents and archives.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Dictionary attack | On | Try common passwords from the bundled wordlist |
| Brute-force | Off | Try all character combinations (can be slow) |
| Brute-force max length | 6 | Longest password to try |
| Brute-force charset | Alphanumeric | Numeric, alpha, alphanumeric, or all |
| Recovery timeout | 300s | Max seconds per file |
| Reuse found passwords | On | Try passwords that worked on other files in the batch |
| Use hashcat | On | GPU-accelerated cracking when available |
| Hashcat workload | 3 (High) | GPU intensity: 1=Low, 2=Default, 3=High, 4=Maximum |

### File Flagging

Self-service + admin content moderation.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Flag webhook URL | (empty) | Optional webhook fired on every flag event |
| Default expiry days | 30 | How long a flag stays active before auto-expiring |

### Info

Read-only view of system metadata: version, database path, build
info, container health. Useful for support tickets.

### Storage Connections

Mount remote filesystems (NFS, SMB, tiered NAS) without editing
`docker-compose.yml`. Add a mount with server address, export path,
and local mount point. MarkFlow handles `mount` and re-mounts on
container restart.

---

## Conversion Options

How files get turned into Markdown.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Default direction | To Markdown | Whether uploads default to → MD or ← MD |
| Max upload size | 100 MB | Largest single file you can upload |
| Max batch size | 500 MB | Total size limit for a multi-file upload |
| Retention days | 30 | How long conversion results are kept (0 = forever) |
| Max concurrent | 3 | How many files convert at the same time |
| PDF engine | pdfplumber | Which library reads PDF files |
| Database sample rows per table | 25 | First N rows extracted per table in database files (max 1000) |
| **Skip file extensions** *(v0.23.3)* | `[]` | JSON list of extensions (no dots) to exclude from scanning. Example: `["tmp", "bak", "log"]` |
| **PPTX chart extraction** *(v0.23.8)* | Placeholder | How to handle charts in PowerPoint files. `Placeholder` shows `[Chart: title]` text. `LibreOffice` renders charts as PNG images via LibreOffice headless (~5s per chart). SmartArt shapes always produce a warning regardless of this setting. |

### OCR

Automatic text extraction from scanned documents.

| Setting | Default | Range | What It Does |
|---------|---------|-------|--------------|
| Confidence threshold | 60 | 0–100 | Pages below this score are flagged for review |
| Unattended mode | Off | On/Off | Auto-accepts all OCR text without flagging |
| OCR preprocessing | On | On/Off | Deskew, contrast, noise reduction |
| **Handwriting confidence threshold** *(v0.20.3)* | 40 | 0–100 | Below this, MarkFlow sends the page image to the active LLM vision provider for handwriting transcription |
| **Force OCR by default** *(v0.23.6)* | Off | On/Off | When on, new bulk jobs default to re-OCRing every PDF page even if a text layer is present. Per-job override is in the Bulk page config modal. |

> **Tip:** 60-80% is a good balance for the main confidence threshold.
> Lower it if too many pages are flagged, raise it if accuracy is
> critical. For handwriting, 40% is aggressive; raise to 30% if too
> many clean-print pages are being sent to the LLM.

### Path Safety

How MarkFlow names output files and handles collisions.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Max path length | 240 | Max output path length — files longer are skipped with `skip_reason` |
| Collision strategy | rename | What to do when two files would produce the same output name: `rename`, `overwrite`, or `skip` |

---

## AI Options

Features that call out to an LLM provider. All require an active
provider configured on the **Providers** page.

| Setting | Default | What It Does |
|---------|---------|--------------|
| OCR correction | Off | Use AI to fix garbled OCR output |
| Summarize | Off | Generate a one-paragraph summary in every document's frontmatter |
| Heading inference | Off | Detect headings in PDFs that lack structure |

### Vision & Frame Description

Visual content analysis for videos and image-heavy documents.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Enrichment level | 2 | 1=basic, 2=standard, 3=comprehensive |
| Frame limit | 50 | Max keyframes extracted per video |
| Save keyframes | Off | Keep extracted frame images on disk |
| Vision provider | (uses active provider) | Provider used for image analysis |

### Claude Integration (MCP)

The Model Context Protocol server lets Claude (or any MCP client)
query your MarkFlow index directly. Runs on port 8001.

| Setting | What It Does |
|---------|--------------|
| Enable MCP server | Start/stop the MCP server |
| MCP auth token | Bearer token clients must supply |
| Setup Instructions | Expandable — copy-paste config for Claude Desktop |

### Transcription

Audio/video transcription pipeline.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Whisper model | base | Local Whisper model size: `tiny`, `base`, `small`, `medium`, `large` |
| Caption file extensions | `srt,vtt,sbv` | Caption files auto-ingested alongside media |
| Cloud fallback priority | (empty) | Fallback order if local Whisper unavailable: `openai,gemini`, etc. |

### AI-Assisted Search

The Claude-powered answer drawer on the Search page.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Enable AI Assist org-wide | On | Master switch; users can still toggle per-browser |
| Max output tokens | 700 | Response length cap (about 380 words) |
| Max snippets fed to Claude | 8 | How many top search results Claude sees |

> **Per-provider opt-in:** On the **Providers** page, tick **Use for
> AI Assist** on any Anthropic provider to route AI Assist to it
> independently of the image-scanner provider. See [What's
> New → v0.22.11](/help.html#whats-new) for details.

---

## Billing & Costs *(v0.33.2)*

| Setting | Default | What It Does |
|---------|---------|--------------|
| Billing cycle start day | 1 | Day-of-month (1-28) when your provider's invoice cycle starts. The Provider Spend card on the Admin page sums LLM costs from this day of the previous month through today. Match your actual invoice date for an accurate running total. |

> **Why does this exist?** Different providers close their bills on
> different days. If your Anthropic invoice closes on the 15th, set
> this to 15 so MarkFlow's "this cycle" total matches what you'll be
> charged. Capped at 28 to avoid February's edge case (no Feb 30/31).

> **Where do the rate values live?** The per-1M-token rates for each
> model are in `core/data/llm_costs.json` inside the container. To
> update without a restart: edit the file (it's host-mounted), then
> hit `POST /api/admin/llm-costs/reload` (admin only). View what's
> currently loaded at `/api/admin/llm-costs`.

---

## Logging

| Setting | Default | What It Does |
|---------|---------|--------------|
| Log level | Normal | Normal = warnings only. Elevated = operational info. Developer = everything |

> **Note:** Developer mode also enables frontend action tracking
> (every button click). Turn it off when not actively debugging.

---

## File Lifecycle

Automatic change detection and file management.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Scanner enabled | On | Periodic scanning of source locations |
| Scan interval | 15 min | How often to check for changes |
| Business hours | 06:00–18:00 | Scanner only runs during these hours (weekdays) |
| Incremental scan | On | Skip directories whose mtime has not changed |
| Full walk every N scans | 5 | Force a full walk every Nth scan |
| Grace period | 36 hours | Wait time before a missing file moves to trash |
| Trash retention | 60 days | How long trashed files are kept before auto-purge |
| **Auto-purge aged trash** *(v0.23.6)* | On | Master switch for the daily 04:00 job that permanently deletes trashed files older than the retention window. Turn off to keep trash indefinitely. |

> **Note:** Both the grace period and the trash retention are now
> production values. The daily auto-purge job runs at 04:00 local
> time, is gated on the **Auto-purge aged trash** toggle above, and
> yields automatically to active bulk jobs.

---

## Pipeline

Master switch for the automated conversion pipeline.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Pipeline enabled | On | Master switch — when off, no auto-conversion |
| Max files per run | 0 | Cap files per auto-conversion batch (0 = no cap) |
| Startup delay | 5 min | Wait this long before the first post-startup scan |
| Auto-reset days | 3 | If pipeline is disabled, auto re-enable after N days |

---

## Cloud Prefetch

Background prefetch for cloud-synced source directories (OneDrive,
Google Drive, Dropbox, iCloud, tiered NAS).

| Setting | Default | What It Does |
|---------|---------|--------------|
| Cloud prefetch enabled | Off | Enable background prefetch for cloud placeholders |
| Concurrency | 4 | How many prefetch workers run in parallel |
| Rate limit | 10/sec | Max files prefetched per second |
| Timeout | 120s | Max seconds to wait for a single file |
| Min size bytes | 0 | Skip files smaller than this |

---

## Search Preview

The hover popup on search results.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Hover Preview | On | Show or hide the preview popup on hover |
| Preview size | Medium | Small (320x240), Medium (480x360), Large (640x480) |
| Hover delay | 400ms | How long to hover before the preview appears (100–2000ms) |

> **Tip:** If you find previews distracting, turn them off or raise
> the delay. If you want instant previews, drop to 100 ms.

---

## Auto-Conversion

Decision engine for auto-converting newly scanned files. Works in
tandem with the Pipeline section above.

| Setting | Default | What It Does |
|---------|---------|--------------|
| Mode | Batch | `batch`, `immediate`, or `off` |
| Batch size | 500 | Files per auto-batch |
| Workers | 4 | Parallel conversion workers |
| OCR threshold for auto-skip | 50 | Files below this OCR confidence are skipped |

See the [Auto-Conversion](/help.html#auto-conversion) article for mode
details.

---

## Debug: DB Contention Logging

**Temporary diagnostic section** introduced in v0.19.6.5 to diagnose
"database is locked" errors. Produces three extra log files in
`logs/`. Turn off when contention issues are resolved — the logs
are high-volume.

| Setting | Default | What It Does |
|---------|---------|--------------|
| DB contention logging | Off | Enable the three diagnostic log files |

---

## Advanced

Seldom-needed options for experienced operators.

| Setting | What It Does |
|---------|--------------|
| Reset to defaults | Restore every setting on this page to its default value (irreversible) |
| Export settings | Download a JSON snapshot of the current configuration |
| Import settings | Upload a previously exported JSON snapshot |

---

## Related

- [What's New](/help.html#whats-new)
- [Getting Started](/help.html#getting-started)
- [Bulk Repository Conversion](/help.html#bulk-conversion)
- [Auto-Conversion](/help.html#auto-conversion)
- [LLM Provider Setup](/help.html#llm-providers)
- [Password-Protected Documents](/help.html#password-recovery)
- [Search](/help.html#search)
