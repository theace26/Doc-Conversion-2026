# MarkFlow Phase 7 — Bulk Conversion, Adobe Indexing & Search (Planning Document)

**Status**: Planning. Build after Phase 5–6 are complete.
**Last updated**: 2026-03-23

---

## Problem Statement

Convert a ~1TB company document repository (hundreds of thousands of files, various formats) from a network drive (SMB/CIFS) to Markdown. Output goes to a **separate mirrored repository** on local storage — the source share is read-only and untouched. This includes standard document formats (docx, pdf, pptx, xlsx, csv) AND Adobe creative files (ai, psd, indd, aep, prproj, xd). Index the markdown repository for full-text search with links back to originals. Enable AI-assisted querying via Cowork against the search index.

---

## Four Subsystems

### 1. Bulk Crawler & Converter

**What it does**: Walk a directory tree on a mounted network share, convert every supported file to `.md`, place the markdown alongside the original file, preserve folder structure and naming.

**Key requirements**:
- **Resume capability**: Track what's been converted. If the job is interrupted (crash, reboot, network drop), restart without re-converting already-processed files.
- **Incremental mode**: On subsequent runs, detect new or modified files (by mtime or content hash) and convert only those. Skip unchanged files.
- **Parallel processing**: Convert multiple files concurrently. OCR is CPU-bound — use a process pool, not just async. Target: saturate available CPU cores without overwhelming memory.
- **Memory-safe**: Never load the full file list into memory. Stream the directory walk. Process files one at a time (or in small parallel batches).
- **Network-aware**: SMB/CIFS mounts can be slow and flaky. Handle timeouts, disconnections, and permission errors gracefully. Log and skip problem files, don't crash.
- **Mirrored repository output**: Source share is **read-only** — MarkFlow never writes to it. All output goes to a separate local repository that mirrors the source folder hierarchy. For `report.docx` at `/mnt/company-share/dept/2024/report.docx`, produce `/mnt/markflow-repo/dept/2024/report.md` + `report.styles.json`. The original share stays clean and untouched.
- **Unattended OCR**: All OCR runs in unattended mode (auto-accept flags). Interactive review is impractical at this scale. Low-confidence regions get logged for optional post-processing review.
- **Progress tracking**: Persistent state in SQLite — total files found, files processed, files skipped (already done), files errored. Expose via API endpoint and/or CLI output.
- **Logging**: Per-file log entry with path, format, conversion time, OCR triggered (y/n), flag count, status. Structured JSON logs for machine parsing.

**Architecture**:
- New CLI entrypoint: `python -m markflow.bulk` or `markflow bulk /mnt/company-share --output-dir /mnt/markflow-repo --workers 4`
- Source path and output path are always separate. The crawler reads from source, writes to output. Directory structure is mirrored automatically.
- Reuses existing format handlers from Phases 1–4 (no rewrite)
- New `core/crawler.py` — async directory walker with filtering (by extension, by mtime, by already-processed status)
- New `core/job_queue.py` — file processing queue with configurable concurrency. Use `multiprocessing.Pool` or `concurrent.futures.ProcessPoolExecutor` for OCR-heavy work, `asyncio` for I/O-bound work (file reads, DB writes).
- New SQLite table: `bulk_jobs` (job ID, source_root, output_root, status, started_at, files_total, files_processed, files_errored) and `bulk_files` (job_id, source_path, output_md_path, status, converted_at, error_message, file_hash, mtime, index_level)

**Estimated conversion time** (rough):
- Text-based documents (docx, xlsx, csv, text-layer PDF): ~1–5 seconds each
- Scanned PDFs (OCR): ~10–30 seconds per page
- Adobe files (metadata + text layer extraction): ~1–3 seconds each
- If 50% of files are text-based (avg 2s), 30% need OCR (avg 30s), 20% Adobe (avg 2s): mixed average ~10s/file
- With 8 workers: ~2–3 days for 100K files
- With 16 workers (Ryzen 5950X 16c/32t): ~1–2 days
- These are rough estimates — actual time depends on file sizes, OCR page counts, and network speed

### 2. Adobe File Indexing (Level 2 — Metadata + Text Layers)

**Scope**: Extract metadata and editable text content from Adobe creative files. No visual/pixel analysis. No round-trip conversion (index-only — you never convert a `.md` back to a `.psd`).

#### New Handler: `formats/adobe_handler.py`

A single handler that registers for all Adobe extensions. Two extraction strategies depending on format.

**Strategy A — PDF-compatible formats (`.ai`)**

Illustrator files contain an embedded PDF compatibility stream. Route them through the existing `PdfHandler.ingest()` to extract text content, then supplement with XMP metadata via `exiftool`.

Registered extensions: `.ai`

**Strategy B — Native parsing (`.psd`)**

Use `psd-tools` library to parse Photoshop files:
- Extract text layer content (editable type layers have actual strings)
- Extract layer names (often descriptive: "Header Text", "CTA Button", "Background")
- Extract XMP/EXIF metadata via `exiftool`

Registered extensions: `.psd`

**Strategy C — Metadata-only (`.indd`, `.aep`, `.prproj`, `.xd`, and other Adobe formats)**

InDesign, After Effects, Premiere, and XD files don't have reliable open-source parsers for content extraction. Extract XMP metadata only via `exiftool`. Still valuable for search — keywords, author, title, dates, software version.

Registered extensions: `.indd`, `.aep`, `.prproj`, `.xd`

**Note on `.indd`**: If users export InDesign files as `.idml` (XML-based InDesign Markup Language), a future enhancement could parse the XML to extract story text. But `.indd` binary format requires Adobe's SDK and is out of scope.

#### Markdown Output Format (Adobe files)

```markdown
---
markflow:
  source_file: "brand_refresh_logo.ai"
  source_format: "ai"
  content_type: "adobe_level2"
  converted_at: "2026-03-25T10:00:00Z"
  index_level: 2
---

# brand_refresh_logo.ai

## File Metadata

| Field | Value |
|---|---|
| Format | Adobe Illustrator |
| Title | Q4 Brand Refresh - Primary Logo |
| Author | Jane Smith |
| Keywords | brand, logo, refresh, 2024, primary |
| Created | 2024-08-12 |
| Modified | 2024-09-03 |
| Software | Adobe Illustrator 28.1 |
| Color Mode | CMYK |
| Dimensions | 3000 × 2400 px |
| Pages/Artboards | 3 |

## Extracted Text Content

IBEW LOCAL 46
SAFETY FIRST — ELECTRICAL HAZARD
Authorized Personnel Only
Terminal 86 — Louis Dreyfus Company

## Layer Structure

- Background
- Logo Group
  - Icon
  - Wordmark
- Safety Text
- Border Elements
```

#### Dependencies

- **`exiftool`** — system binary, handles XMP/EXIF for all Adobe formats. Install in Docker: `apt-get install libimage-exiftool-perl`
- **`pyexiftool`** — Python wrapper. `pip install PyExifTool`
- **`psd-tools`** — PSD parser. `pip install psd-tools`

#### Why Not a Separate Handler Per Format?

All Adobe formats share the same metadata extraction pipeline (exiftool). Only `.ai` and `.psd` have additional content extraction. A single handler with internal strategy routing keeps the codebase clean and the format registry simple.

### 3. Search Index (Meilisearch)

**Why Meilisearch over SQLite FTS5**: At hundreds of thousands of documents, you need typo-tolerant search, faceted filtering, sub-50ms query times, and the ability to index while serving queries. Meilisearch is purpose-built for this, runs as a single binary, tiny footprint.

**What gets indexed** (per document):

```json
{
  "id": "sha256_of_source_path",
  "title": "Quarterly Report Q3 2024",
  "content": "full markdown text (or first 50K chars for very large docs)",
  "source_path": "/mnt/company-share/dept/2024/quarterly_report.docx",
  "md_path": "/mnt/markflow-repo/dept/2024/quarterly_report.md",
  "relative_path": "dept/2024/quarterly_report.docx",
  "format": "docx",
  "content_type": "document",
  "index_level": 2,
  "directory": "dept/2024",
  "file_size_bytes": 245000,
  "created_date": "2024-09-15",
  "modified_date": "2024-10-01",
  "converted_date": "2026-03-25",
  "ocr_applied": false,
  "ocr_confidence_avg": null,
  "author": "Jane Smith",
  "keywords": ["quarterly", "report", "Q3"],
  "software": null,
  "tags": []
}
```

**Dual paths**: Every search result carries both `source_path` (link to original on the network share) and `md_path` (link to the markdown in the local repository). The search UI shows both — "View Original" and "View Markdown". The `relative_path` field enables re-mapping if either the source share or the markdown repo moves to a new mount point.

**Content types**: `"document"` (docx, pdf, pptx, xlsx, csv), `"adobe_full"` (ai, psd — metadata + text), `"adobe_metadata"` (indd, aep, prproj, xd — metadata only).

**Facets for filtering**: format, content_type, directory (hierarchical), date ranges, author, keywords, OCR status, index_level.

**Deployment**: Docker container alongside MarkFlow:

```yaml
meilisearch:
  image: getmeili/meilisearch:v1.12
  ports:
    - "7700:7700"
  volumes:
    - meilisearch-data:/meili_data
  environment:
    - MEILI_MASTER_KEY=your-key-here
```

**Indexing pipeline**: `core/indexer.py` reads each `.md` file after conversion, extracts metadata from frontmatter + content, pushes to Meilisearch in batches of 1000 documents.

**Search UI**: New page `static/search.html` — search bar, facet sidebar (format, directory, date, author), results with snippet highlights and links to both `.md` and original file.

### 4. AI-Assisted Querying (Cowork Integration)

**The pattern**: Cowork queries the Meilisearch API → retrieves relevant documents → reads the full `.md` files for the top results → reasons across them.

**Context window budget**: 10 documents × ~5K tokens each = ~50K tokens. Well within Cowork's capacity.

**Integration options** (in order of simplicity):
1. MarkFlow's FastAPI adds `GET /api/search?q=...` that proxies to Meilisearch — Cowork reads results via a script
2. A shell script that curls Meilisearch directly — Cowork calls it via filesystem MCP
3. A custom MCP server wrapping Meilisearch (most elegant, most build work)

---

## Level 3 Enrichment (Future — Not Part of Phase 7 Build)

Level 3 adds OCR on rasterized text and AI visual descriptions to Adobe files. Designed as an **enrichment pass** that runs against already-indexed files — not a separate program.

### How It Works

- New CLI flag: `markflow bulk /path --enrich-level-3` or `markflow enrich /path --level 3`
- Crawler's incremental mode identifies files where `index_level < 3` in `bulk_files` table
- For each file:
  - Generate a preview render (flatten to image)
  - Run OCR on the rendered image (catches rasterized text)
  - Optionally: call Claude Vision API or similar to generate a visual description
  - Update the existing `.md` file with new sections (Extracted OCR Text, Visual Description)
  - Update the Meilisearch document with enriched content
  - Set `index_level = 3` in `bulk_files`
- Can target subsets: `markflow enrich /mnt/markflow-repo/marketing --level 3 --format psd`

### Why This Is a Later Addition, Not Phase 7

- Level 2 covers 90%+ of search value
- Level 3 requires API credits (Claude Vision) that scale with file count — need cost estimation first
- OCR on design files is unreliable without tuning — needs experimentation
- The infrastructure (crawler, indexer, Meilisearch) must exist first anyway

### What's Needed When You Build It

- Preview rendering: `Pillow` for PSD, `pdf2image` for AI, generic thumbnail for others
- OCR: existing `core/ocr.py` pipeline
- AI Vision (optional): Anthropic API call with image input, structured output prompt
- Update logic: modify existing `.md` files in-place (append sections), re-index in Meilisearch
- Cost tracking: log API calls and estimated cost per file, running total per job

---

## Network Drive & Repository Layout

### Source Share (Read-Only)
- Mount the SMB share: `sudo mount -t cifs //server/share /mnt/company-share -o username=...,password=...,uid=1000,gid=1000,ro`
- The `ro` (read-only) flag is intentional — MarkFlow never writes to the source share
- Add to `/etc/fstab` for persistence

### Markdown Repository (Local, Read-Write)
- Lives on local storage — your Synology NAS is ideal (`/volume1/markflow-repo/` or similar)
- Mirrors the source share's folder hierarchy exactly
- Contains: `.md` files, `.styles.json` sidecars, `assets/` folders for extracted images
- This is the directory Meilisearch indexes
- Back this up independently — it's your searchable knowledge base

### Recommended Layout

```
/mnt/company-share/          ← SMB mount, read-only, source of truth
├── dept-a/
│   ├── 2024/
│   │   ├── report.docx
│   │   ├── budget.xlsx
│   │   └── logo.ai
│   └── 2025/
│       └── proposal.pdf

/mnt/markflow-repo/          ← local (Synology), read-write, MarkFlow output
├── dept-a/
│   ├── 2024/
│   │   ├── report.md
│   │   ├── report.styles.json
│   │   ├── budget.md
│   │   ├── budget.styles.json
│   │   ├── logo.md
│   │   └── assets/
│   │       └── a3f8c2e1b9d4.png
│   └── 2025/
│       ├── proposal.md
│       └── proposal.styles.json

/app/data/                   ← MarkFlow internal (Docker volume)
├── markflow.db              ← SQLite: conversion history, bulk jobs, preferences
└── meilisearch/             ← search index data
```

### Performance Strategy
- **Option A (fastest)**: rsync the entire source share to Synology first (`rsync -avz /mnt/company-share/ /volume1/company-mirror/`), run bulk conversion against the local copy, then the markdown repo is already on fast local storage. Re-run rsync periodically to catch new files.
- **Option B (simpler)**: Read directly from SMB mount during conversion. Slower due to SMB latency on small files, but no sync step needed. Write output to local Synology repo.
- Recommendation: **Option A** for the initial 1TB conversion. **Option B** for ongoing incremental runs (fewer files, latency matters less).

### Permissions
- Source share: read-only access is sufficient
- Markdown repo: MarkFlow needs read-write
- No write access to the company share needed — ever

### File Locking
- Never lock source files during conversion — other users need access
- Write `.md` files atomically (temp file → rename) in the markdown repo

---

## Build Order (Phase 7)

### 7a — Crawler & Bulk Runner
1. `core/crawler.py` — async directory walker with extension filtering
2. `core/bulk_runner.py` — job orchestration, process pool, progress tracking
3. SQLite schema: `bulk_jobs` + `bulk_files` tables
4. CLI entrypoint: `markflow bulk /mnt/company-share --output-dir /mnt/markflow-repo --workers N`
5. Resume logic: check `bulk_files` status before re-processing
6. Incremental mode: compare mtime/hash against last run
7. Progress API endpoint: `GET /api/bulk/{job_id}/progress`

### 7b — Adobe Handler
8. `formats/adobe_handler.py` — Strategy A (AI via PDF), Strategy B (PSD via psd-tools), Strategy C (metadata-only via exiftool)
9. Docker: add `exiftool` system dep, `pyexiftool` + `psd-tools` pip deps
10. Register all Adobe extensions in format registry
11. Test fixtures + `tests/test_adobe.py`

### 7c — Search Index
12. Meilisearch Docker setup in `docker-compose.yml`
13. `core/indexer.py` — batch indexing pipeline, reads `.md` files, pushes to Meilisearch
14. Search API: `GET /api/search?q=...&format=...&directory=...&author=...`
15. Search UI: `static/search.html`
16. Incremental indexing: only index new/modified `.md` files

### 7d — Integration & Polish
17. End-to-end test: bulk convert a sample directory → verify all files indexed → search returns results
18. Cowork integration: search wrapper script or API proxy
19. Progress dashboard in web UI for bulk jobs
20. Documentation: README update with bulk mode usage

---

## Dependencies (New for Phase 7)

**Python packages:**
```
pyexiftool
psd-tools
meilisearch          # Python client for Meilisearch API
```

**System packages (Docker):**
```
libimage-exiftool-perl    # exiftool binary
```

**Docker services:**
```
getmeili/meilisearch:v1.12
```

---

## Open Questions (Resolve Before Building)

1. ~~**Write access**~~ — **Resolved**: Separate mirrored repository on local storage. Source share is read-only.
2. **File types distribution**: What percentage of the 1TB is each format? (Ratio of scanned PDFs to text docs vs. Adobe files is critical for time estimation.)
3. **Deduplication**: Are there duplicate files across the repository? Should the indexer detect and flag duplicates?
4. **Retention**: How long to keep the markdown repo? Rebuild periodically, or maintain indefinitely?
5. **Access control**: Who will have access to the search UI? Does it need to respect source share permissions?
6. **Update frequency**: One-time conversion, or does the repository get new files regularly?
7. **InDesign exports**: Are `.idml` exports available for InDesign files, or only `.indd`?
8. **Meilisearch hosting**: Run on same machine as MarkFlow (Docker), or separate server?
9. **Markdown repo location**: Synology NAS, local disk on the conversion machine, or somewhere else?
10. **Source share mount**: Can Docker containers mount the SMB share directly, or does it need to be host-mounted and bind-mounted into the container?
