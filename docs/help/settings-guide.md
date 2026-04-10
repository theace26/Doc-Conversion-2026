# Settings Reference

The Settings page lets you configure how MarkFlow behaves. Changes are saved when you click Save. Some settings require the Manager role to change.

## Conversion Options

Controls how documents are converted between formats.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Default direction | To Markdown | Whether uploads default to converting to or from Markdown |
| Max upload size | 100 MB | Largest single file you can upload |
| Max batch size | 500 MB | Total size limit for a multi-file upload |
| Retention days | 30 | How long conversion results are kept (0 = forever) |
| Max concurrent | 3 | How many files convert at the same time |
| PDF engine | pdfplumber | Which library reads PDF files |
| Collision strategy | rename | What to do when two files would produce the same output name |

## OCR Settings

Configure automatic text extraction from scanned documents.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Confidence threshold | 80% | Pages below this score are flagged for review |
| Unattended mode | Off | When on, accepts all OCR results without review |

> **Tip:** A threshold of 80% is a good balance. Lower it if too many pages are flagged. Raise it if you need higher accuracy.

## Bulk Conversion

Settings for large repository conversion jobs.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Worker count | 4 | How many files process in parallel. More = faster but more CPU |
| Show active files | On | Display which file each worker is currently processing |
| Max path length | 240 | Maximum output file path length (some systems have limits) |

## Password Recovery

Configure how MarkFlow handles password-protected documents.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Dictionary attack | On | Try common passwords from the bundled dictionary |
| Brute-force | Off | Try all character combinations (can be slow) |
| Brute-force max length | 6 | Longest password to try via brute-force |
| Brute-force charset | Alphanumeric | Which characters to try: numeric, alpha, alphanumeric, all |
| Recovery timeout | 300s | Max time to spend cracking a single file |
| Reuse found passwords | On | Try passwords that worked on other files in the same batch |
| Use hashcat | On | Enable GPU-accelerated cracking when available |
| Hashcat workload | 3 (High) | GPU intensity: 1=Low, 2=Default, 3=High, 4=Maximum |

## AI Options

AI-powered features that improve conversion quality. Requires an active provider.

| Setting | Default | What It Does |
|---------|---------|-------------|
| OCR correction | Off | Use AI to fix OCR errors |
| Summarize | Off | Generate a summary for each document |
| Heading inference | Off | Use AI to detect headings in PDFs that lack them |

## Vision & Enrichment

Configure visual content analysis for videos and image-heavy documents.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Enrichment level | 2 | How thorough: 1=basic, 2=standard, 3=comprehensive |
| Frame limit | 50 | Maximum keyframes to extract per video |
| Save keyframes | Off | Keep extracted frame images on disk |

## Logging

Control how much detail MarkFlow writes to its logs.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Log level | Normal | Normal = warnings only. Elevated = operational info. Developer = everything |

> **Note:** Developer mode also enables frontend action tracking, which logs every button click and page navigation. Disable when not actively debugging.

## Search Preview

Configure the hover preview that appears when you hover over search results.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Hover Preview | On | Show or hide the preview popup on hover |
| Preview size | Medium | Popup dimensions: Small (320x240), Medium (480x360), Large (640x480) |
| Hover delay | 400ms | How long to hover before the preview appears (100-2000ms) |

> **Tip:** If you find previews distracting, turn them off or increase the delay. If you want instant previews, set the delay to 100ms.

## File Lifecycle

Configure automatic change detection and file management.

| Setting | Default | What It Does |
|---------|---------|-------------|
| Scanner enabled | On | Periodic scanning of the source share |
| Scan interval | 15 min | How often to check for changes |
| Business hours | 06:00–18:00 | Scanner only runs during these hours (weekdays) |
| Grace period | 36 hours | Wait time before a missing file moves to trash |
| Trash retention | 60 days | How long trashed files are kept before permanent deletion |

## Related

- [Getting Started](/help#getting-started)
- [Bulk Repository Conversion](/help#bulk-conversion)
- [LLM Provider Setup](/help#llm-providers)
- [Password-Protected Documents](/help#password-recovery)
