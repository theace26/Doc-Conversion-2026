# MarkFlow Phase 7 — Bulk Conversion & Search Index (Planning Document)

**Status**: Planning. Build after Phase 5–6 are complete.
**Last updated**: 2026-03-23

---

## Problem Statement

Convert a ~1TB company document repository (hundreds of thousands of files, various formats) from a network drive (SMB/CIFS) to Markdown. Index the converted files for full-text search with links back to originals. Enable AI-assisted querying via Cowork against the search index.

---

## Three Subsystems

### 1. Bulk Crawler & Converter

**What it does**: Walk a directory tree on a mounted network share, convert every supported file to `.md`, place the markdown alongside the original file, preserve folder structure and naming.

**Key requirements**:
- **Resume capability**: Track what's been converted. If the job is interrupted (crash, reboot, network drop), restart without re-converting already-processed files.
- **Incremental mode**: On subsequent runs, detect new or modified files (by mtime or content hash) and convert only those. Skip unchanged files.
- **Parallel processing**: Convert multiple files concurrently. OCR is CPU-bound — use a process pool, not just async. Target: saturate available CPU cores without overwhelming memory.
- **Memory-safe**: Never load the full file list into memory. Stream the directory walk. Process files one at a time (or in small parallel batches).
- **Network-aware**: SMB/CIFS mounts can be slow and flaky. Handle timeouts, disconnections, and permission errors gracefully. Log and skip problem files, don't crash.
- **Output placement**: For `report.docx` at `/mnt/share/dept/2024/report.docx`, produce `/mnt/share/dept/2024/report.md` (alongside) plus `/mnt/share/dept/2024/report.styles.json` (sidecar).
- **Unattended OCR**: All OCR runs in unattended mode (auto-accept flags). Interactive review is impractical at this scale. Low-confidence regions get logged for optional post-processing review.
- **Progress tracking**: Persistent state in SQLite — total files found, files processed, files skipped (already done), files errored. Expose via API endpoint and/or CLI output.
- **Logging**: Per-file log entry with path, format, conversion time, OCR triggered (y/n), flag count, status. Structured JSON logs for machine parsing.

**Architecture**:
- New CLI entrypoint: `python -m markflow.bulk` or `markflow bulk /mnt/share --workers 4`
- Reuses existing format handlers from Phases 1–4 (no rewrite)
- New `core/crawler.py` — async directory walker with filtering (by extension, by mtime, by already-processed status)
- New `core/job_queue.py` — file processing queue with configurable concurrency. Use `multiprocessing.Pool` or `concurrent.futures.ProcessPoolExecutor` for OCR-heavy work, `asyncio` for I/O-bound work (file reads, DB writes).
- New SQLite table: `bulk_jobs` (job ID, source root, status, started_at, files_total, files_processed, files_errored) and `bulk_files` (job_id, file_path, status, converted_at, md_path, error_message, file_hash, mtime)

**Estimated conversion time** (rough):
- Text-based documents (docx, xlsx, csv, text-layer PDF): ~1–5 seconds each
- Scanned PDFs (OCR): ~10–30 seconds per page
- If 50% of files are text-based (avg 2s) and 50% need OCR (avg 30s): ~100K files × 16s avg = ~18 days single-threaded
- With 8 workers: ~2–3 days
- With 16 workers (your Ryzen 5950X has 16c/32t): ~1–2 days
- These are rough estimates — actual time depends heavily on file sizes and OCR page counts

### 2. Search Index (Meilisearch)

**Why Meilisearch over SQLite FTS5**: At hundreds of thousands of documents, you need typo-tolerant search, faceted filtering, sub-50ms query times, and the ability to index while serving queries. SQLite FTS5 technically works at this scale but gets painful for anything beyond exact keyword matching. Meilisearch is purpose-built for this, runs as a single binary, and has a tiny footprint.

**Alternative considered**: Typesense is comparable. Meilisearch is easier to self-host and has better defaults for document search. Either works.

**What gets indexed** (per document):

```json
{
  "id": "sha256_of_path",
  "title": "Quarterly Report Q3 2024",
  "content": "full markdown text (or first 50K chars for very large docs)",
  "source_path": "/mnt/share/dept/2024/quarterly_report.docx",
  "md_path": "/mnt/share/dept/2024/quarterly_report.md",
  "format": "docx",
  "directory": "dept/2024",
  "file_size_bytes": 245000,
  "created_date": "2024-09-15",
  "modified_date": "2024-10-01",
  "converted_date": "2026-03-25",
  "ocr_applied": false,
  "ocr_confidence_avg": null,
  "tags": []
}
```

**Facets for filtering**: format, directory (hierarchical), date ranges, OCR status, file size ranges.

**Deployment**: Run Meilisearch as a Docker container alongside MarkFlow. Add to `docker-compose.yml`:

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

**Indexing pipeline**: After bulk conversion completes (or incrementally during conversion), a new `core/indexer.py` reads each `.md` file, extracts metadata from frontmatter, and pushes documents to Meilisearch in batches of 1000.

**Search UI**: New page in MarkFlow web UI — search bar, facet filters, results with snippet highlights and links to both the `.md` and original file.

### 3. AI-Assisted Querying (Cowork Integration)

**The problem**: Cowork's context window (~200K tokens) can't hold hundreds of thousands of documents. But it doesn't need to.

**The pattern**: Cowork queries the Meilisearch API, retrieves relevant documents, and works with those.

**How it works in practice**:
1. You open a Cowork session with a prompt like: "Search the company document repository for all contracts mentioning Terminal 86, summarize the key terms, and identify any conflicts."
2. Cowork calls the Meilisearch API (via MCP filesystem access to a search script, or via a custom MCP connector): `GET /indexes/documents/search?q=Terminal 86 contract`
3. Meilisearch returns the top 20 results with snippets
4. Cowork reads the full `.md` files for the most relevant results (maybe 5–10 documents)
5. Cowork synthesizes, summarizes, answers

**What's needed**:
- A search script or API endpoint that Cowork can call (simple curl/fetch wrapper)
- Or: a custom MCP server that wraps Meilisearch (more elegant, but more build work)
- Or: MarkFlow's existing FastAPI backend adds a `/api/search` endpoint that proxies to Meilisearch — Cowork can use this via the filesystem MCP by reading a results file

**Context window budget**: 10 full markdown documents × ~5K tokens each = ~50K tokens, well within Cowork's budget. The search index does the heavy lifting of narrowing hundreds of thousands of files down to the relevant few.

---

## Network Drive Considerations

### Mounting
- Mount the SMB share to a local path: `sudo mount -t cifs //server/share /mnt/company -o username=...,password=...,uid=1000,gid=1000`
- Add to `/etc/fstab` for persistence across reboots
- Or: mount inside the Docker container via a volume bind

### Performance
- SMB over gigabit LAN: ~100 MB/s sequential read. Adequate for document conversion.
- Random access (many small files): SMB has high per-operation latency. The crawler should batch file reads and minimize metadata calls.
- **Recommendation**: If possible, do a one-time rsync of the repository to local storage (your Synology has 40+ TB free), run the bulk conversion locally, then sync the `.md` files back. This avoids SMB latency during the CPU-intensive conversion phase.

### Permissions
- Read access is sufficient for conversion. Write access is needed to place `.md` files alongside originals.
- If write access to the network share is restricted, output to a parallel local directory structure instead (mirror the folder hierarchy but on local disk).

### File Locking
- Don't lock source files during conversion — other users may need access.
- Write `.md` files atomically (write to temp file, then rename) to avoid partial files if interrupted.

---

## Rough Build Order (Phase 7)

1. `core/crawler.py` — async directory walker with extension filtering
2. `core/bulk_runner.py` — job orchestration, process pool, progress tracking
3. SQLite schema: `bulk_jobs` + `bulk_files` tables
4. CLI entrypoint: `markflow bulk /path --workers N`
5. Resume logic: check `bulk_files` status before re-processing
6. Incremental mode: compare mtime/hash against last run
7. Progress API endpoint: `GET /api/bulk/{job_id}/progress`
8. Meilisearch Docker setup + `core/indexer.py`
9. Search API: `GET /api/search?q=...&format=...&directory=...`
10. Search UI page: `static/search.html`
11. Cowork integration: search wrapper script or MCP connector

---

## Open Questions (Resolve Before Building)

1. **Write access**: Can you write `.md` files directly to the network share, or do you need a local mirror?
2. **File types distribution**: What percentage of the 1TB is each format? (Knowing the ratio of scanned PDFs to text docs is critical for time estimation.)
3. **Deduplication**: Are there duplicate files across the repository? Should the indexer detect and flag duplicates?
4. **Retention**: Should the markdown files persist permanently alongside originals, or is the index the primary artifact?
5. **Access control**: Does the search index need to respect the same permissions as the network share? (i.e., should users only see search results for files they have access to?)
6. **Update frequency**: Is this a one-time conversion, or does the repository get new files regularly (needing ongoing incremental conversion)?
