# MarkFlow — Enterprise Document Conversion

**MarkFlow** converts documents bidirectionally between their original format and Markdown.
Drop in files — or point it at an entire repository — and MarkFlow handles the rest:
format detection, OCR, password recovery, media transcription, full-text search,
and version tracking. Everything runs inside Docker with a browser-based UI.

**Current version:** v0.14.1

---

## What It Does

- **60+ file types in, Markdown out** — Office, PDF, email, archives, Adobe creative files, images, audio, video, config files, and more. Round-trip back to the original format when needed.
- **Bulk conversion at scale** — Point MarkFlow at a network share with tens of thousands of files. It scans, classifies, and converts in parallel with adaptive throttling that adjusts to your storage (SSD, HDD, or NAS).
- **OCR built in** — Scanned PDFs are automatically detected and OCR'd with per-page confidence scoring. Low-confidence pages get flagged for human review — or run fully unattended.
- **Password-protected files handled automatically** — PDF encryption, Office passwords, and archive passwords are cracked via a cascade: known passwords, dictionary, brute-force, and GPU-accelerated hashcat (NVIDIA, AMD, Intel, Apple Silicon).
- **Media transcription** — Audio and video files become timestamped Markdown transcripts. Local Whisper (GPU-accelerated) with cloud fallback (OpenAI, Gemini). Existing caption files (SRT/VTT/SBV) are detected and used automatically.
- **Full-text search** — Meilisearch indexes every converted document and transcript. Search from the UI, the API, or via MCP tools in Claude.ai.
- **File lifecycle management** — Tracks new, modified, moved, and deleted files across scans. Soft-delete pipeline with grace periods. Full version history with diffs.
- **Visual enrichment** — Video conversions include scene detection, keyframe extraction, and AI-generated frame descriptions interleaved into transcripts.
- **Role-based access** — JWT auth with four roles (search_user, operator, manager, admin). API key service accounts for system integrations. UnionCore-compatible.

---

## Supported Formats

| Category | Formats |
|----------|---------|
| Office | .docx, .doc, .docm, .pdf, .pptx, .ppt, .xlsx, .xls, .csv, .tsv, .wpd |
| Rich Text | .rtf |
| OpenDocument | .odt, .ods, .odp |
| Markdown & Text | .md, .txt, .log |
| Web | .html, .htm, .xml, .epub |
| Data & Config | .json, .yaml, .yml, .ini, .cfg, .conf, .properties |
| Email | .eml, .msg (with recursive attachment conversion) |
| Archives | .zip, .tar, .tar.gz, .7z, .rar, .cab, .iso |
| Adobe Creative | .psd, .ai, .indd, .aep, .prproj, .xd, .ait, .indt |
| Images | .jpg, .jpeg, .png, .tif, .tiff, .bmp, .gif, .eps |
| Audio | .mp3, .wav, .m4a, .flac, .ogg, .aac, .wma |
| Video | .mp4, .mov, .avi, .mkv, .webm, .m4v, .wmv |
| Captions | .srt, .vtt, .sbv |

All document formats support bidirectional conversion (original → Markdown → original).
Media files produce timestamped transcripts. Archives are recursively extracted and each inner file is converted.

---

## Key Features

### Automated Pipeline
- Fully automated scan-convert-index cycle — lifecycle scanner detects new/modified files and triggers bulk conversion automatically
- Pipeline API for status, pause, resume, and on-demand runs
- Configurable scan interval, worker count, and per-cycle file caps
- Health-gated startup — waits for services before first scan, self-heals if pipeline is accidentally disabled
- Designed for headless deployment — runs unattended with self-healing DB maintenance

### Intelligent Bulk Processing
- Adaptive scan parallelism — auto-detects storage type and adjusts thread count
- Feedback-loop throttling — dynamically parks/restores workers based on real-time I/O latency
- Error-rate monitoring — auto-aborts gracefully on NAS disconnects or cascading failures
- Pause, resume, and cancel jobs at any time
- Per-worker active file display with real-time SSE progress

### OCR Pipeline
- Multi-signal scanned-page detection (image-only pages, low text density, embedded font analysis)
- Per-page confidence scoring with configurable thresholds
- Batch review UI for bulk jobs — skip, convert anyway, or review page-by-page
- Unattended mode for fully automated processing

### Password Recovery
- PDF owner/user passwords (pikepdf)
- Office encryption — OOXML and legacy formats (msoffcrypto-tool)
- Archive passwords — ZIP, 7z, RAR
- Edit/print restrictions stripped automatically
- GPU-accelerated hashcat cracking (NVIDIA CUDA, AMD ROCm, Intel OpenCL, Apple Metal)
- Successful passwords cached and reused across the session

### Media Transcription
- Local Whisper with GPU auto-detect (CUDA when available, CPU fallback)
- Cloud fallback chain: OpenAI Whisper API → Gemini audio
- Three output formats per file: .md (timestamped), .srt, .vtt
- Existing caption files detected and used without transcription cost
- Full-text transcript search via Meilisearch

### Search & Integration
- Meilisearch full-text search across all documents, Adobe metadata, and transcripts
- Search autocomplete with keyboard navigation
- MCP server (port 8001) exposes 10 tools to Claude.ai / Cowork
- REST API with interactive docs at `/docs`
- API key service accounts for programmatic access

### Admin & Monitoring
- Status page with per-job cards, progress bars, and controls
- Resources dashboard: CPU/memory charts, disk growth, activity log, OCR quality metrics
- Admin panel: disk usage, DB health, integrity checks, resource controls
- Configurable structured logging (three levels: Normal, Elevated, Developer)
- Log rotation with automatic gzip archiving (90-day retention)
- In-app help wiki with 19 searchable articles and contextual help links

### File Lifecycle
- Scheduled scans detect new, modified, moved, and deleted source files
- Soft-delete pipeline: marked → trash (60-day hold) → purge
- Full version history with unified diffs and change summaries
- Unrecognized file cataloging with MIME detection and category breakdown

---

## Architecture

MarkFlow uses a **format-agnostic intermediate representation** (`DocumentModel`).
All format handlers convert to/from this model, reducing N x M format combinations to N + M handlers.

```
Source file (.docx / .pdf / .pptx / .xlsx / ...)
         ↓  ingest()
    DocumentModel
         ↓  export()
    Output file (.md / .docx / .pdf / .pptx / ...)
```

**Fidelity tiers** ensure nothing is silently lost:
- **Tier 1** (guaranteed) — Headings, paragraphs, lists, tables, images. Structure always survives.
- **Tier 2** (sidecar) — Fonts, spacing, colors. Restored from `.styles.json` when converting back.
- **Tier 3** (original) — Complex layouts. Restored by patching against the preserved original file.

---

## Quick Start

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)

```bash
git clone https://github.com/theace26/Doc-Conversion-2026.git
cd Doc-Conversion-2026
cp .env.example .env   # edit paths for your machine
docker-compose up -d
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### First-time build

The base image includes all system dependencies (Tesseract, LibreOffice, Poppler, WeasyPrint, ffmpeg, Whisper, hashcat). Build it once:

```bash
docker build -f Dockerfile.base -t markflow-base:latest .
```

After that, code changes only rebuild the lightweight app layer (~3-5 min).

---

## Usage

### Web UI

1. Drop files or folders onto the upload zone (or click to browse).
2. Select direction: **Document → Markdown** or **Markdown → Document**.
3. Click **Convert** — a batch progress page opens automatically.
4. Review any OCR-flagged items, then download results.

For bulk repositories, use the **Bulk** page to point at a source directory. MarkFlow scans, classifies, and converts everything it finds.

### API

Full interactive API docs at [http://localhost:8000/docs](http://localhost:8000/docs).

```bash
# Convert a file to Markdown
curl -X POST http://localhost:8000/api/convert \
  -F "files=@report.docx" \
  -F "direction=to_md"

# Check batch status
curl http://localhost:8000/api/batch/<batch_id>/status

# Search across all converted content
curl "http://localhost:8000/api/search?q=quarterly+report"

# Health check
curl http://localhost:8000/api/health
```

### MCP Integration

MarkFlow exposes 10 MCP tools on port 8001 for use with Claude.ai, Cowork, or any MCP-compatible client:

| Tool | Description |
|------|-------------|
| `search_documents` | Full-text search across converted documents |
| `read_document` | Retrieve a specific converted document |
| `list_documents` | Browse the document catalog |
| `convert_document` | Trigger a conversion |
| `search_adobe` | Search Adobe file metadata |
| `get_summary` | Get document summary |
| `conversion_status` | Check job status |
| `list_unrecognized` | Browse unrecognized files |
| `search_transcripts` | Search across media transcripts |
| `read_transcript` | Retrieve a specific transcript |

---

## Configuration

### Environment Variables

Paths are configured per-machine in `.env` (see `.env.example`):

| Variable | Container Mount | Purpose |
|----------|----------------|---------|
| `SOURCE_DIR` | `/mnt/source` (read-only) | Source files for bulk processing |
| `OUTPUT_DIR` | `/mnt/output-repo` | Bulk conversion output |
| `./output` | `/app/output` | Single-file conversion results |
| `./logs` | `/app/logs` | Application logs (JSON structured) |

### User Preferences

Adjust in **Settings** (`/settings.html`) or via the API. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `auto_convert_mode` | `immediate` | Auto-convert after scan (off / immediate / queued / scheduled) |
| `auto_convert_workers` | `10` | Parallel workers for auto-conversion |
| `ocr_confidence_threshold` | `70` | Flag OCR words below this % confidence |
| `pdf_engine` | `pymupdf` | PDF extraction engine (pymupdf / pdfplumber) |
| `scan_max_threads` | `auto` | Scan parallelism (auto-detected or manual) |
| `retention_days` | `30` | Days before auto-cleanup of output files |
| `log_level` | `normal` | Logging verbosity (normal / elevated / developer) |

GPU acceleration, password recovery, transcription, and visual enrichment each have dedicated settings sections.

---

## System Requirements

Runs entirely in Docker. For non-Docker development:

- Python 3.12+
- Tesseract OCR 5.x
- LibreOffice headless
- Poppler utilities
- WeasyPrint C libraries
- ffmpeg + ffprobe
- hashcat (optional, for GPU password cracking)

---

## License

MIT
