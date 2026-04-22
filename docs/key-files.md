# MarkFlow Key Files Reference

Quick-reference for file purposes. Referenced from CLAUDE.md.

## Core

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, mounts all routers + `/ocr-images` static |
| `core/database.py` | Backward-compatible re-export wrapper for `core/db/` package |
| `core/db/connection.py` | DB_PATH, get_db(), db_fetch_one/all, db_execute (routes through pool when available), db_write_with_retry, now_iso |
| `core/db/pool.py` | Single-writer connection pool + async write queue (1 writer + 3 readers, WAL mode) (v0.23.0) |
| `core/db/migrations.py` | One-time startup migrations gated by preference flags (bulk dedup, heartbeat column, stale jobs) (v0.23.0) |
| `core/preferences_cache.py` | In-memory TTL cache (300s) for DB preferences, invalidated on PUT (v0.23.0) |
| `core/db/schema.py` | Schema DDL, versioned migrations, init_db(), cleanup_orphaned_jobs |
| `core/db/preferences.py` | DEFAULT_PREFERENCES, get/set/all preference helpers |
| `core/db/bulk.py` | Bulk jobs, bulk files, source file upsert/query helpers + `cleanup_stale_bulk_files()` self-correction (v0.22.7) |
| `core/db/conversions.py` | Conversion history, batch state, OCR flags, review queue, scene keyframes |
| `core/db/catalog.py` | Adobe index, locations, LLM providers, unrecognized files, archive members |
| `core/db/lifecycle.py` | Lifecycle queries, file versions, path issues, scan runs, maintenance log |
| `core/db/analysis.py` | Analysis queue: enqueue, dedup, claim batch, write results, token summary |
| `core/db/auth.py` | API key management (create, lookup, revoke, list, touch) |
| `core/validation/markitdown_compare.py` | CLI tool for comparing MarkFlow output against Microsoft markitdown (v0.23.0) |
| `core/health.py` | Startup checks for Tesseract, LibreOffice, Poppler, WeasyPrint, disk, DB |
| `core/logging_config.py` | structlog JSON logging, rotating file handler |
| `core/converter.py` | Pipeline orchestrator; `from_md` path detects sidecar + original → tier 1/2/3 |
| `core/ocr_models.py` | OCR dataclasses: OCRWord, OCRFlag, OCRPage, OCRConfig, OCRResult, OCRFlagStatus |
| `core/ocr.py` | OCR engine: `needs_ocr`, `preprocess_image`, `ocr_page`, `flag_low_confidence`, `run_ocr` |
| `core/bulk_scanner.py` | File discovery: walks source dir, upserts to bulk_files, adaptive parallel scan; serial path uses batched writes + async DB overlap |
| `core/storage_probe.py` | Storage latency probe: auto-detects SSD/HDD/NAS, recommends scan thread count |
| `core/scan_coordinator.py` | Scan priority coordinator: Bulk > Run Now > Lifecycle, cancel/pause signals |
| `core/bulk_worker.py` | Worker pool: BulkJob class, pause/resume/cancel, SSE events, job registry |
| `core/adobe_indexer.py` | Adobe Level 2 indexing: exiftool metadata + text extraction (.ai/.psd) |
| `core/search_client.py` | Thin async Meilisearch HTTP client via httpx, graceful degradation |
| `core/search_indexer.py` | Manages Meilisearch indexes, document/adobe indexing, rebuild, filename normalization |
| `core/crypto.py` | Fernet encryption/decryption for API keys stored at rest |
| `core/llm_providers.py` | PROVIDER_REGISTRY: known providers (Anthropic, OpenAI, Gemini, Ollama, custom) |
| `core/llm_client.py` | Unified async LLM client — routes to provider-specific API implementations |
| `core/llm_enhancer.py` | Enhancement tasks: OCR correction, summarization, heading inference |
| `core/path_utils.py` | Path safety: length check, collision detection, resolution strategies |
| `core/mime_classifier.py` | MIME detection (python-magic) + extension fallback file classification |
| `core/vision_adapter.py` | VisionAdapter: wraps active LLM provider for image/vision calls |
| `core/scene_detector.py` | PySceneDetect wrapper: scene boundary detection in video files |
| `core/keyframe_extractor.py` | ffmpeg keyframe extraction at scene midpoints |
| `core/visual_enrichment_engine.py` | Orchestrates scene detection + keyframe + frame description |
| `core/differ.py` | Unified diff engine + bullet summary generator |
| `core/lifecycle_manager.py` | Lifecycle state transitions: mark, restore, trash, purge, move, content change |
| `core/lifecycle_scanner.py` | Source share walker, change detection, move detection via content hash |
| `core/scheduler.py` | APScheduler setup: lifecycle scan, trash expiry, DB maintenance jobs |
| `core/db_maintenance.py` | VACUUM, integrity checks, stale data detection, health summary |
| `core/auth.py` | JWT validation, role hierarchy, API key verification, FastAPI dependencies |
| `core/resource_manager.py` | psutil wrapper: CPU affinity, process priority, live metrics |
| `core/stop_controller.py` | Global stop flag, task registry, should_stop() / request_stop() / reset_stop() |
| `core/metrics_collector.py` | System/disk metrics collection, activity events, 90-day purge, query helpers |
| `core/password_handler.py` | Password detection, restriction stripping, encryption cracking cascade |
| `core/gpu_detector.py` | Dual-path GPU detection: container NVIDIA + host worker capabilities |
| `core/auto_converter.py` | Auto-conversion decision engine: mode resolution, worker/batch sizing |
| `core/pipeline_startup.py` | Health-gated startup: waits for services before triggering initial scan+convert cycle |
| `core/cloud_detector.py` | Platform-agnostic cloud placeholder detection (disk blocks + read latency) |
| `core/cloud_prefetch.py` | Background prefetch worker pool with rate limiting, adaptive timeouts, retry with backoff |
| `core/flag_manager.py` | Flag business logic, blocklist checks, Meilisearch is_flagged sync, webhooks |
| `core/auto_metrics_aggregator.py` | Hourly rollup of system_metrics into auto_metrics |
| `core/progress_tracker.py` | RollingWindowETA, ProgressSnapshot, format_eta for scan/bulk jobs |
| `core/log_archiver.py` | Compress rotated logs to gzip archives, purge old archives |
| `core/archive_safety.py` | Zip-bomb protection: ratio, size, depth, quine checks |
| `core/media_probe.py` | ffprobe wrapper: codec detection, duration, transcode decision |
| `core/audio_extractor.py` | Extract audio from video, convert to Whisper-compatible WAV |
| `core/whisper_transcriber.py` | Local Whisper with GPU auto-detect, lazy model loading |
| `core/cloud_transcriber.py` | Cloud fallback: OpenAI Whisper API, Gemini audio |
| `core/transcription_engine.py` | Fallback orchestrator: caption → Whisper → cloud |
| `core/caption_ingestor.py` | SRT/VTT/SBV caption file parser |
| `core/transcript_formatter.py` | Output formatter: .md + .srt + .vtt generation |
| `core/media_orchestrator.py` | Top-level media conversion coordinator |
| `core/ai_assist.py` | Claude API streaming for AI-assisted search synthesis (v0.21.0) |
| `core/vector/chunker.py` | Markdown → contextual chunks for embedding (heading-based + fixed-size fallback) |
| `core/vector/embedder.py` | Pluggable embedding provider (local sentence-transformers, lazy model load) |
| `core/vector/index_manager.py` | Qdrant collection lifecycle, document indexing, semantic search, deletion |
| `core/vector/hybrid_search.py` | RRF merge of Meilisearch keyword + Qdrant vector results |
| `core/vector/query_preprocessor.py` | Temporal intent detection, question prefix stripping, query normalization |
| `core/db/ai_usage.py` | AI Assist org toggle + per-user usage logging (v0.21.0) |
| `core/host_detector.py` | Host OS detection from `/host/root` filesystem signatures + quick-access list builder (v0.28.0) |
| `core/credential_store.py` | Fernet+PBKDF2 encrypted SMB/NFS credentials at `/etc/markflow/credentials.enc` (v0.28.0) |
| `core/storage_manager.py` | Path validation, write-guard `is_write_allowed()`, output-path cache + persistence (v0.28.0) |
| `core/mount_manager.py` | Multi-mount manager with v2 `mounts.json` schema, named shares at `/mnt/shares/<name>`, SMB/NFS discovery, startup remount, 5-min health probe |

## Format Handlers

| File | Purpose |
|------|---------|
| `core/libreoffice_helper.py` | Shared LibreOffice headless conversion (.doc→.docx, .xls→.xlsx, .ppt→.pptx) |
| `formats/docx_handler.py` | DOCX/DOC/WBK/PUB/P65 ingest + export; legacy formats via LibreOffice |
| `formats/markdown_handler.py` | MD ingest + export; `_extract_formatted_text` for inline bold/italic/code |
| `formats/pdf_handler.py` | PDF ingest (pdfplumber + OCR) + export (WeasyPrint); font-size heading detection |
| `formats/pptx_handler.py` | PPTX/PPT/PPTM ingest (slides→H2 sections) + export; .ppt via LibreOffice |
| `formats/xlsx_handler.py` | XLSX/XLS ingest (sheets→H2+TABLE) + export; .xls preprocessed via LibreOffice |
| `formats/csv_handler.py` | CSV/TSV/TAB ingest (pandas + stdlib fallback) + export; delimiter/encoding preserved |
| `formats/json_handler.py` | JSON ingest/export with summary + structure outline + secret redaction |
| `formats/yaml_handler.py` | YAML/YML with multi-document support, comments preservation |
| `formats/ini_handler.py` | INI/CFG/CONF/properties with section-aware parsing, .conf plain-text fallback |
| `formats/rtf_handler.py` | RTF ingest/export with control-word parser |
| `formats/html_handler.py` | HTML/HTM ingest/export with BeautifulSoup, font extraction |
| `formats/odf_utils.py` | Shared ODF helpers: font extraction, text node traversal |
| `formats/odt_handler.py` | OpenDocument Text via odfpy |
| `formats/ods_handler.py` | OpenDocument Spreadsheet via odfpy |
| `formats/odp_handler.py` | OpenDocument Presentation via odfpy |
| `formats/xml_handler.py` | XML ingest/export with structure-aware parsing |
| `formats/epub_handler.py` | EPUB ingest/export |
| `formats/txt_handler.py` | Plain text / log / list / C++ / CSS ingest/export |
| `formats/eml_handler.py` | EML/MSG email with recursive attachment conversion |
| `formats/adobe_handler.py` | PSD/PSB/AI/INDD/AEP/PRPROJ/XD — unified Adobe handler |
| `formats/archive_handler.py` | ZIP/TAR/7z/RAR/CAB/ISO — recursive extraction + conversion |
| `formats/image_handler.py` | Image file handler (.jpg, .png, .tif, .bmp, .gif, .eps, .cr2) |
| `formats/audio_handler.py` | Audio file handler (.mp3, .wav, .flac, .ogg, .m4a, .wma, .aac) |
| `formats/media_handler.py` | Video file handler (.mp4, .mov, .avi, .mkv, .webm, .m4v, .wmv) |
| `formats/font_handler.py` | Font metadata handler (.otf, .ttf) via fonttools |
| `formats/shortcut_handler.py` | Windows shortcut (.lnk binary) and URL shortcut (.url INI) handler |
| `formats/vcf_handler.py` | vCard contact file handler (.vcf) |
| `formats/svg_handler.py` | SVG vector graphics handler — XML parsing, text/element extraction |
| `formats/sniff_handler.py` | Sniff-based handler (.tmp) — MIME-detects then delegates |
| `formats/binary_handler.py` | Binary metadata-only handler (.bin, .cl4) |
| `formats/database_handler.py` | Database file handler — schema + sample data extraction (.sqlite, .mdb, .accdb, .dbf, .qbb, .qbw) |
| `formats/database/engine.py` | DatabaseEngine ABC + dataclasses (TableInfo, ColumnInfo, RelationshipInfo, IndexInfo) |
| `formats/database/sqlite_engine.py` | SQLite engine — built-in sqlite3 module |
| `formats/database/access_engine.py` | Access engine — mdbtools/pyodbc/jackcess cascade |
| `formats/database/dbase_engine.py` | dBase/FoxPro engine — dbfread |
| `formats/database/quickbooks_engine.py` | QuickBooks engine — best-effort binary header parse |
| `formats/database/capability.py` | Database engine availability detection |

## API Routes

| File | Purpose |
|------|---------|
| `api/middleware.py` | Request ID injection, timing, debug headers |
| `api/routes/convert.py` | Upload + validate + start conversion |
| `api/routes/batch.py` | Batch status, download, manifest + SSE stream |
| `api/routes/history.py` | History list (filter/sort/search/paginate), stats, redownload |
| `api/routes/preferences.py` | Preferences CRUD with per-key validation + schema metadata |
| `api/routes/review.py` | OCR review endpoints: list, counts, single-flag, resolve, accept-all |
| `api/routes/debug.py` | Debug dashboard API |
| `api/routes/bulk.py` | Bulk job API: create, list, status, pause/resume/cancel, files, errors, SSE |
| `api/routes/search.py` | Search API: unified multi-index search, autocomplete, source file serving, batch download, rebuild |
| `api/routes/cowork.py` | AI assistant search: full .md content inline, token-budget-aware |
| `api/routes/locations.py` | Locations CRUD API + exclusions CRUD + path validation endpoint |
| `api/routes/browse.py` | Directory browser API with path traversal protection |
| `api/routes/llm_providers.py` | LLM provider CRUD, verify (auto-requeues failed analysis items), activate, Ollama model fetch |
| `api/routes/unrecognized.py` | Unrecognized files: list, stats, CSV export |
| `api/routes/lifecycle.py` | Version history and diff API endpoints |
| `api/routes/trash.py` | Trash management API: list, restore, purge, empty |
| `api/routes/scanner.py` | Scanner status, progress, trigger, run history API |
| `api/routes/db_health.py` | Database health and maintenance API |
| `api/routes/auth.py` | GET /api/auth/me — current user identity and role |
| `api/routes/admin.py` | API key CRUD, system info, resource controls, stats, disk usage |
| `api/routes/resources.py` | Resources API: metrics, disk history, events, summary, CSV export |
| `api/routes/help.py` | Help wiki API: index, article rendering (mistune), keyword search |
| `api/routes/auto_convert.py` | Auto-conversion API: status, mode override, run history, metrics |
| `api/routes/client_log.py` | POST /api/log/client-event — frontend action logging |
| `api/routes/logs.py` | GET /api/logs/download/{filename} — log file downloads + archive endpoints |
| `api/routes/mcp_info.py` | GET /api/mcp/connection-info — MCP server status for settings UI |
| `api/routes/media.py` | Media transcript API: get transcript, segments, download |
| `api/routes/flags.py` | Flag API: user flagging + admin triage (dismiss/extend/remove/blocklist) |
| `api/routes/pipeline.py` | Pipeline control: status, pause, resume, run-now, file browser (`/api/pipeline/files`) |
| `api/routes/ai_assist.py` | AI Assist: SSE search synthesis, doc expand, status, admin toggle + usage (v0.21.0) |
| `api/routes/storage.py` | Universal Storage Manager API: host-info, validate, sources/output/exclusions CRUD, shares + discovery + credentials, mount health, restart status, first-run wizard (v0.28.0) |

## Frontend

| File | Purpose |
|------|---------|
| `static/markflow.css` | Shared design system: CSS variables, dark mode, components |
| `static/app.js` | Shared JS: API helpers, formatters, toast, nav link highlighter |
| `static/index.html` | Upload UI: drag-and-drop, direction toggle, format badges |
| `static/search.html` | Search UI: unified multi-index search, format chips, per-page, multi-select, viewer links, rendered markdown preview |
| `static/viewer.html` | Document viewer: source/rendered/raw modes, in-document search, line numbers, markdown rendering (marked.js + DOMPurify) |
| `static/job-detail.html` | Job detail page: summary header, stats, files/errors/info tabs with search and filtering |
| `static/bulk.html` | Bulk job UI: location dropdowns, SSE progress, pause/cancel |
| `static/status.html` | Status page: per-job cards, STOP ALL, lifecycle scanner |
| `static/history.html` | History browser: filter, sort, search, pagination, inline detail |
| `static/settings.html` | Preferences form: range sliders, toggles, validation |
| `static/admin.html` | Admin panel: stats, disk usage, resource controls, API keys |
| `static/resources.html` | Resources page: Chart.js charts, activity log |
| `static/help.html` | Help wiki page: sidebar TOC + article content area |
| `static/providers.html` | LLM provider management |
| `static/trash.html` | Trash management page |
| `static/db-health.html` | Database health dashboard |
| `static/locations.html` | Locations management + exclusions |
| `static/unrecognized.html` | Unrecognized files UI |
| `static/review.html` | OCR review page (side-by-side image + editable text) |
| `static/bulk-review.html` | Post-job OCR review queue |
| `static/progress.html` | Live SSE batch progress |
| `static/debug.html` | Developer debug dashboard |
| `static/flagged.html` | Admin flagged files page with filters, sort, pagination |
| `static/pipeline-files.html` | Pipeline file browser: multi-status filter chips, search, paginated table with inline detail expansion |
| `static/js/global-status-bar.js` | Badge-only polling: updates nav badge with active-job count |
| `static/js/help-link.js` | Contextual "?" icon component |
| `static/js/folder-picker.js` | FolderPicker widget: modal directory browser |
| `static/js/lifecycle-badge.js` | Reusable lifecycle status badge component |
| `static/js/version-panel.js` | Version history timeline + compare modal |
| `static/storage.html` | Storage page: Quick Access, Sources, Output, Network Shares, Exclusions, first-run wizard overlay (v0.28.0) |
| `static/js/storage.js` | Storage page JS: vanilla fetch against `/api/storage/*`, all DOM via `createElement` (XSS-safe), wizard with per-step validation (v0.28.0) |
| `static/js/storage-restart-banner.js` | Amber sticky banner injected on every page; polls `/api/storage/restart-status` every 60s (v0.28.0) |
| `static/js/deletion-banner.js` | Dismissible banner for deleted files in search |

## MCP, Tools & Config

| File | Purpose |
|------|---------|
| `mcp_server/server.py` | MCP server entry point — tools exposed via SSE transport |
| `mcp_server/tools.py` | MCP tool implementations (10 tools) |
| `tools/markflow-hashcat-worker.py` | Host-side hashcat worker for AMD/Intel GPU |
| `docker-compose.yml` | Port 8000, MCP 8001, Meilisearch 7700, volumes |
| `docker-compose.gpu.yml` | NVIDIA GPU overlay |
| `docker-compose.yml.mac` | Mac compose template for VM/network share paths |
| `.env.example` | Template for per-machine host paths and config |
| `Dockerfile` | App image — pip + code copy on top of markflow-base |
| `Dockerfile.base` | Base image — all apt system deps (tesseract, ffmpeg, libreoffice, etc.) |
| `pytest.ini` | Test config: asyncio_mode, custom markers |

## Deployment Scripts

| File | Purpose |
|------|---------|
| `Scripts/proxmox/setup-markflow.sh` | Fresh Ubuntu VM setup (Docker, NAS mounts, repo clone) |
| `Scripts/proxmox/reset-markflow.sh` | Full teardown, git pull, docker-compose patch, rebuild |
| `Scripts/work/build-base.ps1` | One-time base image builder (PowerShell) |
| `Scripts/work/refresh-markflow.ps1` | Quick rebuild — git pull + build + restart, keeps volumes |
| `Scripts/work/reset-markflow.ps1` | Full reset — git pull + prune + rebuild (preserves base image) |
| `Scripts/work/pull-logs.ps1` | Extract logs from Docker container to local dir (PowerShell) |
| `Scripts/work/pull-logs.sh` | Extract logs from Docker container (bash, for VM use) |
