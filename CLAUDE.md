# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Detailed references split into `docs/` files.

### When to read the reference docs

Read these files **on demand** — they are not loaded automatically. Use your judgement:

| File | Read it when... |
|------|-----------------|
| [`docs/gotchas.md`](docs/gotchas.md) | You're modifying or debugging a subsystem (check its section before writing code) |
| [`docs/key-files.md`](docs/key-files.md) | You need to locate a file by purpose, or understand what a file does |
| [`docs/version-history.md`](docs/version-history.md) | You need context on why something was built, what changed in a version, or feature scope |
| [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md) | Rarely — only if revisiting the original Phase 1 design spec |

**Rule of thumb:** If a task touches bulk/lifecycle/auth/password/GPU/OCR/search, read the
relevant gotchas section first. Most bugs in these areas have already been hit and documented.

---

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — a Python/FastAPI web app that converts
documents bidirectionally between their original format and Markdown. Runs in Docker.
GitHub: `github.com/theace26/Doc-Conversion-2026`

---

## Current Status — v0.12.10

All 10 phases complete + universal format support. v0.12.10: fixed MCP server crash
loop (FastMCP.run() kwargs unsupported — now uses uvicorn.run() directly), fixed MCP
info panel showing Docker-internal IP and wrong path, added /health endpoint to MCP
server. Docker compose paths now use .env variables for multi-machine support (Windows
workstation + MacBook). Settings page gains Claude Desktop config generator button.
PowerShell deployment scripts gain -GPU flag.

**Planned:** External log shipping to Grafana Loki / ELK stack. The current local log
archive system is an interim solution — once external aggregation is in place, local
retention can be reduced and the archive scheduler retired.

For full version-by-version changelog, see [`docs/version-history.md`](docs/version-history.md).

---

## Phase Checklist

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Docker scaffold, project structure, DB schema, health check | Done |
| 1 | Foundation: DOCX → Markdown (DocumentModel, DocxHandler, metadata, upload UI) | Done |
| 2 | Round-trip: Markdown → DOCX with fidelity tiers | Done |
| 3 | OCR pipeline (multi-signal detection, review UI, unattended mode) | Done |
| 4 | Remaining formats: PDF, PPTX, XLSX/CSV (both directions) | Done |
| 4b | Universal format support: RTF, ODT/ODS/ODP, TXT, HTML, EPUB, EML/MSG, XML, Adobe, media indexing | Done |
| 5 | Testing & debug infrastructure (full test suite, structlog, debug dashboard) | Done |
| 6 | Full UI, batch progress, history page, settings, polish | Done |
| 7 | Bulk conversion, Adobe indexing, Meilisearch search, Cowork integration | Done |
| 8b | Visual enrichment: scene detection, keyframe extraction, AI frame descriptions | Done |
| 8c | Unknown & unrecognized file cataloging with MIME detection | Done |
| 9 | File lifecycle management, version tracking, DB health | Done |
| 10 | Auth layer, role guards, API keys, UnionCore integration contract | Done |

Phase 1 implementation instructions (historical): [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md)

---

## Architecture Reminders

- **Per-machine paths via `.env`** — `docker-compose.yml` uses `${SOURCE_DIR}`, `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}` variables. Each machine gets its own `.env` (gitignored). See `.env.example` for the template.
- **No Pandoc** — library-level only
- **No SPA** — vanilla HTML + fetch calls
- **Fail gracefully** — one bad file never crashes a batch
- **Fidelity tiers**: Tier 1 = structure (guaranteed), Tier 2 = styles (sidecar), Tier 3 = original file patch
- **Content-hash keying** — sidecar JSON keyed by SHA-256 of normalized paragraph/table content
- **Format registry** — handlers register by extension, converter looks up by extension
- **Unified scanning** — no separate Adobe/convertible split; all formats go through same pipeline
- **Font recognition** — handlers extract font declarations in `extract_styles()` for Tier 2 reconstruction
- **Folder drop** — Convert page accepts entire folders via drag-and-drop, auto-scans for valid formats

---

## Key Files

Full file reference table: [`docs/key-files.md`](docs/key-files.md)

Critical files to know:

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, mounts all routers |
| `core/database.py` | SQLite connection, schema, all DB helpers |
| `core/converter.py` | Pipeline orchestrator (single-file conversion) |
| `core/bulk_worker.py` | Worker pool: BulkJob, pause/resume/cancel, SSE |
| `core/auth.py` | JWT validation, role hierarchy, API key verification |
| `core/scheduler.py` | APScheduler: lifecycle scan, trash expiry, DB maintenance, log archive |
| `core/progress_tracker.py` | RollingWindowETA, ProgressSnapshot, format_eta for all job types |
| `core/log_archiver.py` | Compress rotated logs to gzip archives, purge old archives |
| `core/auto_converter.py` | Auto-conversion decision engine |
| `formats/rtf_handler.py` | RTF ingest/export with control-word parser |
| `formats/html_handler.py` | HTML/HTM with BeautifulSoup, font extraction |
| `formats/odt_handler.py` | OpenDocument Text via odfpy |
| `formats/adobe_handler.py` | PSD/AI/INDD/AEP/PRPROJ/XD — unified Adobe handler |
| `formats/archive_handler.py` | ZIP/TAR/7z/RAR/CAB/ISO — recursive extraction + conversion |
| `core/archive_safety.py` | Zip-bomb protection: ratio, size, depth, quine checks |
| `formats/json_handler.py` | JSON ingest/export with summary + structure outline |
| `formats/yaml_handler.py` | YAML/YML with multi-document support |
| `formats/ini_handler.py` | INI/CFG/CONF/properties with section-aware parsing |
| `static/app.js` | Shared JS: API helpers, dynamic nav, toast |
| `static/markflow.css` | Design system: CSS variables, dark mode |
| `Dockerfile.base` | Base image: all apt system deps (build once, ~25 min on HDD) |
| `Dockerfile` | App image: pip + code copy on top of markflow-base (~3-5 min) |
| `docker-compose.yml` | Port 8000, MCP 8001, Meilisearch 7700 |

---

## Gotchas & Fixes

Full list (~90 items organized by subsystem): [`docs/gotchas.md`](docs/gotchas.md)

**Most commonly needed:**

- **aiosqlite**: Always `async with aiosqlite.connect(path) as conn` — never `await` then `async with`
- **structlog**: Use `structlog.get_logger(__name__)` everywhere, never `logging.getLogger()`. Must `import structlog` in every file that calls it.
- **pdfminer logging suppressed**: All `pdfminer.*` loggers set to WARNING in `configure_logging()`. Without this, debug log grows 500+ MB per bulk job.
- **mistune v3**: Must pass `plugins=["table", "strikethrough", "footnotes"]` or tables silently vanish
- **DEV_BYPASS_AUTH=true** is the default — production must set to `false`
- **`python-jose` not `PyJWT`** — they conflict
- **Source share is read-only**: `/mnt/source` mounted `:ro`, never write to it
- **Lifecycle scanner needs a `bulk_jobs` parent row**: Creates synthetic job if none exists
- **Stop is cooperative**: Workers finish current file before stopping
- **Password handling**: Preprocessing step before `handler.ingest()`, not a handler change
- **MCP server is separate**: Port 8001, own process, no JWT auth (uses `MCP_AUTH_TOKEN`)
- **MCP server binding**: `FastMCP.run()` does NOT accept `host` or `port` kwargs. Use `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)` directly. Without this, Uvicorn defaults to 127.0.0.1:8000 which is unreachable from outside the Docker container.
- **MCP display URL**: Always use `localhost:{port}/sse` — never `socket.gethostbyname()` (returns Docker-internal IP) and never `/mcp` (wrong path, endpoint is `/sse`).
- **MCP health endpoint**: `FastMCP.sse_app()` has no `/health` route. Must append a Starlette `Route("/health", handler)` manually before passing to uvicorn.
- **Log files**: Never use bare `FileHandler` or `TimedRotatingFileHandler` — always `RotatingFileHandler` (size-based). Defaults: 50 MB main, 100 MB debug. Configurable via `LOG_MAX_SIZE_MB` / `DEBUG_LOG_MAX_SIZE_MB` env vars.
- **Log archives**: Rotated files are auto-compressed to `logs/archive/*.gz` every 6 hours. 90-day retention (configurable via `LOG_ARCHIVE_RETENTION_DAYS`). Interim solution — planned migration to Grafana Loki / ELK.
- **File downloads**: Never use `fetch()` + blob for file downloads — use `window.location.href` or `<a>` tags. Backend must set explicit `Content-Length` header.
- **Archive handler**: Follows EML handler pattern — `ingest()` produces a DocumentModel with summary + recursive inner content. Temp dirs cleaned in `finally` blocks. Max depth 20 (env: `ARCHIVE_MAX_DEPTH`).
- **Compound extensions**: `.tar.gz`, `.tar.bz2`, `.tar.xz` require compound extension lookup in both `formats/base.py` and `core/bulk_scanner.py`. `Path.suffix` only returns `.gz` — use `_get_compound_extension()` / `_get_effective_extension()`.
- **Archive passwords**: Full cracking cascade — known passwords, dictionary + mutations, brute-force. Uses same user preferences as PDF/Office handler (`password_brute_force_enabled`, `password_brute_force_charset`, `password_brute_force_max_length`, `password_timeout_seconds`). Successful passwords saved to `config/archive_passwords.txt` and reused session-wide. Never log actual passwords.

---

## Supported Formats (v0.12.10)

| Category | Extensions | Handler |
|----------|-----------|---------|
| Office | .docx, .doc, .pdf, .pptx, .xlsx, .csv, .tsv | DocxHandler, PdfHandler, PptxHandler, XlsxHandler, CsvHandler |
| Rich Text | .rtf | RtfHandler |
| OpenDocument | .odt, .ods, .odp | OdtHandler, OdsHandler, OdpHandler |
| Markdown & Text | .md, .txt, .log, .text | MarkdownHandler, TxtHandler |
| Web & Data | .html, .htm, .xml, .epub | HtmlHandler, XmlHandler, EpubHandler |
| Data & Config | .json, .yaml, .yml, .ini, .cfg, .conf, .properties | JsonHandler, YamlHandler, IniHandler |
| Email | .eml, .msg | EmlHandler (with recursive attachment conversion) |
| Archives | .zip, .tar, .tar.gz, .tgz, .tar.bz2, .7z, .rar, .cab, .iso | ArchiveHandler |
| Adobe | .psd, .ai, .indd, .aep, .prproj, .xd | AdobeHandler |
| Media | .mp3, .mp4, .mov, .avi, .mkv, .wav, .flac, .ogg, .webm, .m4a, .m4v, .wmv, .aac, .wma | Indexed (metadata/scene detection); **TODO: add media conversion handlers** |

**Note:** Media files are currently recognized and indexed during bulk scans (metadata extraction,
scene detection for video). Full media-to-document conversion handlers (transcription, frame
extraction summaries) are the next planned addition.

---

## Running the App

```bash
# First time only -- build the base image (slow, ~25 min HDD / ~5 min SSD):
docker build -f Dockerfile.base -t markflow-base:latest .

# Normal operation:
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
(Only rebuilds pip + code layer -- base image is cached.)
