# MarkFlow Security Audit -- v0.16.0

**Date:** 2026-04-01
**Scope:** Full codebase (core/, api/, formats/, static/, Docker config, MCP server)
**Status:** Findings only -- no corrections applied

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 10 |
| HIGH     | 18 |
| MEDIUM   | 22 |
| LOW/INFO | 12 |
| **Total** | **62** |

---

## CRITICAL

### SEC-C01: DEV_BYPASS_AUTH=true Is the Active Default
- **Files:** docker-compose.yml:33, core/auth.py:21,137-140, main.py:197-206
- **Category:** Authentication Bypass + CORS Misconfiguration
- **Description:** DEV_BYPASS_AUTH=true is hardcoded in docker-compose.yml (not an env var override). When active, every request is granted ADMIN role unconditionally with no token/key. Simultaneously, CORS is set to allow_origins=["*"] with allow_credentials=True. Any browser page on any origin can make full-admin API calls.
- **Impact:** Complete authentication bypass. Every endpoint (file downloads, bulk jobs, API key management, blocklist, pipeline control) is accessible to any unauthenticated caller from any origin.

### SEC-C02: Meilisearch Exposed Publicly With No Master Key Default
- **Files:** docker-compose.yml:24,83, .env.example:9
- **Category:** Exposed Service / Missing Authentication
- **Description:** MEILI_MASTER_KEY defaults to empty string. Meilisearch port 7700 is mapped to host. When key is empty, Meilisearch API is fully open -- anyone on the network can query, modify, or delete all search indexes.
- **Impact:** Full read/write access to all 3 indexes (documents, adobe-files, transcripts) including all content, metadata, and file paths.

### SEC-C03: MCP Server Auth Token Loaded But Never Enforced
- **Files:** mcp_server/server.py:28-29, mcp_server/tools.py
- **Category:** Broken Authentication
- **Description:** MCP_AUTH_TOKEN is read from env but never checked against incoming requests. No middleware, no token validation. Port 8001 is mapped to host. All 12 MCP tools are callable without credentials.
- **Impact:** Unauthenticated access to DB queries, file reads, conversion triggers, transcript search. Combined with host drive mounts, any file on C: or D: can be read via convert_document.

### SEC-C04: Containers Run as Root
- **Files:** Dockerfile, Dockerfile.base
- **Category:** Container Privilege Escalation
- **Description:** No USER directive in either Dockerfile. Containers run as root. Combined with host drive mounts (C:/ and D:/ read-only) and installed tools (john, hashcat), a container escape yields root-level host access.
- **Impact:** Any code execution vulnerability in format handlers (LibreOffice, ffmpeg, Ghostscript) runs as root with access to entire host drives.

### SEC-C05: Meilisearch Filter Injection via Unvalidated User Input
- **Files:** api/routes/search.py:123-126,199-203, api/routes/cowork.py:65-68
- **Category:** Filter/Query Injection
- **Description:** format and path_prefix query params are interpolated directly into Meilisearch filter strings without sanitization: f'source_format = "{format}"'. An attacker can escape the quoted string to bypass is_flagged != true filter.
- **Impact:** Non-admin users can view suppressed/flagged files, completely bypassing v0.16.0 content moderation.

### SEC-C06: SQL Injection via Dynamic Column Names in database.py
- **Files:** core/database.py:1090 (counter param), core/database.py:1071-1083,1251-1261,1409-1416,1700-1710,1980-1986,2155-2164,2235-2242 (kwargs keys)
- **Category:** SQL Injection
- **Description:** Multiple functions accept **fields/**kwargs and build column names directly into SQL via f-strings. increment_bulk_job_counter interpolates counter param directly. Column names are never validated against allowlists. SQLite parameterization only protects values, not identifiers.
- **Impact:** Currently callers use hardcoded keys, but any future caller passing user-derived input achieves SQL injection. The upsert_source_file path accepts **extra_fields from scanner code.

### SEC-C07: XXE / Billion Laughs in XML Parser
- **File:** formats/xml_handler.py:59
- **Category:** XML External Entity / Denial of Service
- **Description:** ET.fromstring(raw) uses stdlib xml.etree.ElementTree with no size limit. Python's ET blocks classic XXE but is vulnerable to billion-laughs entity expansion attacks that exhaust memory.
- **Impact:** A crafted .xml file in the source directory can OOM-crash the container.

### SEC-C08: ZIP Path Traversal -- extractall With No Path Sanitization
- **Files:** formats/archive_handler.py:259,462
- **Category:** Path Traversal
- **Description:** _batch_extract_zip calls zf.extractall() and _extract_zip calls zf.extract() with no member path filtering. Tar handler correctly checks for / and .. but ZIP handler does not. Python zipfile path sanitization is incomplete pre-3.12.
- **Impact:** A crafted .zip can write files outside the temp directory -- overwriting app code, config, or passwords file.

### SEC-C09: CAB Path Traversal via Unsanitized Member Paths
- **File:** formats/archive_handler.py:443-448
- **Category:** Path Traversal / Command Injection
- **Description:** member.path from CAB listings is passed directly to cabextract -F subprocess. No .. or absolute path checks applied (unlike tar handler). shell=False prevents shell injection but cabextract itself will write outside dest with traversal paths.
- **Impact:** Arbitrary file write via crafted .cab file.

### SEC-C10: Cowork Endpoint Missing Flag Filter Entirely
- **File:** api/routes/cowork.py:65-68
- **Category:** Authorization Bypass
- **Description:** The Cowork search endpoint does NOT apply the is_flagged != true filter at all. Any SEARCH_USER accessing /api/cowork/search can read flagged files' full markdown content, completely bypassing content moderation.
- **Impact:** Complete bypass of file flagging/suppression system via the Cowork route.

---

## HIGH

### SEC-H01: Path Traversal in view_markdown -- Output Directory Read
- **File:** api/routes/search.py:435-456
- **Category:** Path Traversal
- **Description:** GET /api/search/view/{index}/{doc_id} reads output_path from Meilisearch and calls Path(output_path).read_text() with no validation that path is within expected output directory. No flagging check.
- **Impact:** Authenticated search users could read arbitrary files (DB, logs, config, API keys).

### SEC-H02: Path Traversal in serve_source / download_source
- **File:** api/routes/search.py:43-71,356-430
- **Category:** Path Traversal
- **Description:** _resolve_source_path() falls back to LIKE '%/filename' DB match. Resolved source_path used directly as FileResponse path with no containment check against /mnt/source.
- **Impact:** Files outside /mnt/source could be served to authenticated users.

### SEC-H03: MCP Path Traversal -- read_document, list_directory, convert_document
- **File:** mcp_server/tools.py:72-192
- **Category:** Path Traversal / Unauthorized File Access
- **Description:** read_document accepts absolute paths with only .md extension check. list_directory doesn't resolve or validate paths. convert_document accepts any source_path with no restriction. Combined with unauthenticated MCP (SEC-C03) and host drive mounts.
- **Impact:** Read arbitrary .md files, list any directory, convert (and thus read) any file on mounted host drives.

### SEC-H04: SSRF via Webhook URL (flag_webhook_url)
- **Files:** core/flag_manager.py:88-135, api/routes/preferences.py:456-483
- **Category:** SSRF
- **Description:** flag_webhook_url preference accepts any URL. Used in httpx.AsyncClient.post() with no host validation. Accepts internal Docker names, metadata endpoints, RFC-1918 addresses.
- **Impact:** Operator-level users can probe internal infrastructure, access cloud metadata endpoints.

### SEC-H05: SSRF via LLM Provider api_base_url
- **Files:** core/llm_client.py:117-286, core/cloud_transcriber.py:131,225
- **Category:** SSRF
- **Description:** LLM provider api_base_url stored in DB, settable via Settings UI. Used as HTTP request base. Gemini client sends API key as query parameter -- key leaks if pointed at internal service.
- **Impact:** Internal network pivot, credential exfiltration.

### SEC-H06: SSRF via Ollama base_url Parameter
- **File:** api/routes/llm_providers.py:87-106
- **Category:** SSRF
- **Description:** GET /api/llm-providers/ollama-models?base_url=<anything> passes URL directly to httpx.AsyncClient.get(). Admin-only but no host/scheme validation.
- **Impact:** Server-side requests to arbitrary internal endpoints.

### SEC-H07: XSS -- Search Snippet DOM Injection
- **File:** static/search.html:438
- **Category:** Stored XSS
- **Description:** Meilisearch highlighted results include indexed file content. HTML/JS in source files survives indexing and is injected raw into DOM via unsafe DOM assignment.
- **Impact:** Stored XSS via any malicious file in source directory.

### SEC-H08: XSS -- Help Article HTML via Unsafe DOM Assignment
- **File:** static/help.html:92
- **Category:** Stored XSS
- **Description:** Mistune-rendered markdown injected directly into DOM. Help endpoint is public (no auth). Raw HTML in markdown files executes in browser.
- **Impact:** Persistent XSS against all help page visitors.

### SEC-H09: XSS -- History Page Unescaped Fields
- **File:** static/history.html:220,232,234-244
- **Category:** Stored XSS
- **Description:** Multiple fields (source_filename, output_filename, error_message, media_language, etc.) interpolated into DOM template literals without escaping. A file named with HTML tags executes on render.
- **Impact:** XSS via crafted filenames.

### SEC-H10: XSS -- Debug Dashboard Unescaped Fields
- **File:** static/debug.html:448
- **Category:** Stored XSS
- **Description:** r.filename and r.format injected into DOM template without escaping. escapeHtml() exists in file but not used here.
- **Impact:** XSS via crafted filenames in debug view.

### SEC-H11: XSS -- formatBadge() Unescaped in Multiple Pages
- **Files:** static/app.js:142-145, static/history.html:221, static/index.html:282, static/unrecognized.html:181
- **Category:** Stored XSS
- **Description:** formatBadge(fmt) places fmt unescaped into class attribute and inner text of a span, used inside DOM assignments on 3+ pages.
- **Impact:** Class attribute breakout XSS.

### SEC-H12: No Security Response Headers
- **Files:** api/middleware.py, main.py
- **Category:** Missing Security Headers
- **Description:** No Content-Security-Policy, X-Frame-Options, X-Content-Type-Options, Strict-Transport-Security, Referrer-Policy, or Permissions-Policy headers anywhere.
- **Impact:** All XSS vulns directly exploitable. Clickjacking possible. MIME sniffing attacks possible.

### SEC-H13: SECRET_KEY Has Weak Hardcoded Default
- **File:** docker-compose.yml:29,71
- **Category:** Hardcoded Secret
- **Description:** SECRET_KEY fallback is a known public string committed to the repo ("dev-secret-change-in-prod"). Used for JWT signing and API key encryption.
- **Impact:** Predictable secret invalidates all JWTs and encrypted API keys.

### SEC-H14: MCP_AUTH_TOKEN Exposed in API Response
- **File:** api/routes/mcp_info.py:19-54
- **Category:** Secret Disclosure
- **Description:** GET /api/mcp/connection-info returns URL with token as query param. Token persists in browser history, access logs (readable via /api/logs/download), and proxy logs.
- **Impact:** MCP auth token harvestable from HTTP logs.

### SEC-H15: Weak API Key Hashing (BLAKE2b Single-Pass, No KDF)
- **File:** core/auth.py:92-96
- **Category:** Insecure Cryptographic Practice
- **Description:** API keys hashed with single-pass BLAKE2b. Salt concatenated as bytes instead of using BLAKE2b's native key= parameter. A GPU can compute billions of BLAKE2b hashes/second.
- **Impact:** If DB is exfiltrated, all API keys recoverable quickly.

### SEC-H16: Dead Cleanup Condition -- Decrypted Files Never Deleted
- **File:** core/password_handler.py:871-879
- **Category:** Sensitive Data Persistence
- **Description:** cleanup_temp_file() has guard condition that is always False (compares object to itself). Function is a complete no-op. Decrypted password-protected documents accumulate in /tmp indefinitely.
- **Impact:** Sensitive plaintext documents persist on disk, readable by any container process.

### SEC-H17: Potential Password Logging via str(exc)
- **File:** core/password_handler.py:210
- **Category:** Logging Sensitive Data
- **Description:** Some pikepdf/msoffcrypto exceptions include attempted passwords in message. str(exc) logged at error level. John the Ripper output containing filename:password could also leak.
- **Impact:** Passwords may appear in log files.

### SEC-H18: Insecure Temp File Creation (mktemp)
- **File:** core/libreoffice_helper.py:62
- **Category:** Race Condition (TOCTOU)
- **Description:** tempfile.mktemp() is deprecated -- returns a name without creating the file, allowing race condition. Another process could pre-create the file with malicious content.
- **Impact:** In multi-process environments, LibreOffice output could be replaced before read.

---

## MEDIUM

### SEC-M01: Meilisearch Master Key Over Plaintext HTTP
- **File:** core/search_client.py:16-29
- **Description:** Master key sent as Bearer token over http://localhost:7700. If MEILI_HOST is remote, key exposed in cleartext.

### SEC-M02: No Rate Limiting on Auth Endpoints
- **Files:** core/auth.py, api/routes/auth.py
- **Description:** No throttling for failed auth attempts. API key verification includes DB write on every call.

### SEC-M03: Unvalidated index Path Parameter in Search Endpoints
- **File:** api/routes/search.py:310-456
- **Description:** doc_info, serve_source, download_source, view_markdown accept {index} path param with no pattern validation.

### SEC-M04: batch-download Accepts Unvalidated index/doc_id
- **File:** api/routes/search.py:461-532
- **Description:** POST body dicts with no Pydantic validation. Up to 500 Meilisearch queries per request.

### SEC-M05: Memory Exhaustion via Batch Download ZIP
- **Files:** api/routes/search.py:383-395, api/routes/batch.py:218-241
- **Description:** ZIP built in memory from entire batch directory with no size cap.

### SEC-M06: No CSRF Protection
- **Files:** main.py, api/middleware.py
- **Description:** No CSRF token mechanism. JSON content-type provides partial browser protection only.

### SEC-M07: Client Log Endpoint Unauthenticated
- **File:** api/routes/client_log.py:48-71
- **Description:** POST /api/log/client-event has no auth. In-memory rate limiter resets on restart. Log flooding vector.

### SEC-M08: Debug Dashboard HTML Served Without Auth
- **File:** api/routes/debug.py:33-39
- **Description:** /debug serves debug.html with no auth check. Exposes API paths, component names, debug structure.

### SEC-M09: Health/Version Endpoints Leak System Topology
- **Files:** main.py:303-313, core/health.py:222-302
- **Description:** /api/health returns DB path, disk usage, drive mounts, GPU info, Meilisearch host, service versions -- all unauthenticated.

### SEC-M10: Unbounded Pagination (scanner/runs, db/maintenance-log)
- **Files:** api/routes/scanner.py:97-106, api/routes/db_health.py:68-75
- **Description:** limit parameter has no upper bound. Large values cause memory exhaustion.

### SEC-M11: lookup-source Discloses Filesystem Paths
- **File:** api/routes/flags.py:72-83
- **Description:** Any SEARCH_USER can probe whether arbitrary filesystem paths exist in the index.

### SEC-M12: No ZIP Per-Entry Compression Ratio Check
- **File:** formats/archive_handler.py:456-525
- **Description:** check_compression_ratio is imported but never called. Single-entry zip bombs not caught before extraction.

### SEC-M13: EML Attachment No Size Limit Before Temp Write
- **File:** formats/eml_handler.py:283-301
- **Description:** No len(content) check before writing attachment to temp file. 4GB base64 blob exhausts disk.

### SEC-M14: XLSX No Size/Row Limit on Spreadsheet Load
- **File:** formats/xlsx_handler.py:62-65,95-106
- **Description:** openpyxl.load_workbook loads entire spreadsheet into memory. No file size or row count limit.

### SEC-M15: Archive Password File World-Readable
- **File:** formats/archive_handler.py:112-114
- **Description:** config/archive_passwords.txt opened with default umask (0o644). Contains plaintext working passwords.

### SEC-M16: Pillow/EPS No Size Limit + Ghostscript Execution
- **File:** formats/image_handler.py:58,134
- **Description:** No size check before Image.open(). For .eps files, Pillow invokes Ghostscript subprocess -- a known Pillow security concern.

### SEC-M17: EPUB No Size Limit, Internal HTML Not Sanitized
- **File:** formats/epub_handler.py:56,88
- **Description:** No size check before epub.read_epub(). Internal HTML chapters not stripped of script/iframe tags.

### SEC-M18: PSD No Size Limit, Unbounded Layer Recursion
- **File:** formats/adobe_handler.py:167,173-184
- **Description:** No size check before PSDImage.open(). _walk_psd_layers is recursive with no depth limit.

### SEC-M19: SECRET_KEY Not Validated at Startup
- **Files:** core/crypto.py:15-19, main.py
- **Description:** SECRET_KEY only checked when encrypt_value() called. App starts normally with it unset. LLM API keys become unencryptable.

### SEC-M20: Gemini API Key in URL Query Parameter
- **Files:** core/llm_client.py:181, core/cloud_transcriber.py:225
- **Description:** Gemini API key passed as ?key=... query param. Appears in access logs, proxy logs, browser history.

### SEC-M21: Untrusted Shared-Volume JSON in GPU Detector
- **File:** core/gpu_detector.py:101-116
- **Description:** worker_capabilities.json from shared /mnt/hashcat-queue volume is trusted without validation.

### SEC-M22: No Rate Limit on Flag Creation
- **File:** core/flag_manager.py
- **Description:** Any search_user can flag unlimited files. Each triggers webhook + Meilisearch update. Flood vector.

---

## LOW / INFO

### SEC-L01: XSS -- help.html Reflects Unescaped URL Hash Slug
- **File:** static/help.html:110
- **Description:** slug from window.location.hash concatenated into DOM assignment on 404.

### SEC-L02: admin.html key_id in onclick Without Escaping
- **File:** static/admin.html:924
- **Description:** key_id injected into onclick attribute. Safe while UUIDs but pattern is fragile.

### SEC-L03: Meilisearch Uses latest Tag
- **File:** docker-compose.yml:79
- **Description:** Unpinned image tag. Breaking or malicious update pulls automatically.

### SEC-L04: No Resource Limits on Containers
- **File:** docker-compose.yml
- **Description:** markflow and markflow-mcp have no CPU/memory limits. Only meilisearch is limited.

### SEC-L05: MEILI_ENV=development Hardcoded
- **File:** docker-compose.yml:84
- **Description:** Development mode enables search preview UI and may have weaker security posture.

### SEC-L06: Host Drive Mounts Overly Broad
- **File:** docker-compose.yml:14-15
- **Description:** Entire C: and D: drives mounted read-only. Combined with MCP traversal, all host files accessible.

### SEC-L07: Error Messages Disclose Internal IDs
- **File:** api/routes/flags.py:152-153,184
- **Description:** Error details include raw flag/blocklist IDs enabling enumeration.

### SEC-L08: Static Files Served Without Auth
- **File:** main.py:293
- **Description:** All HTML/JS/CSS served unauthenticated. Full client-side source visible.

### SEC-L09: .env.example Contains Real Machine Paths
- **File:** .env.example:2-3
- **Description:** Actual developer paths and username committed to repo.

### SEC-L10: Archive Entry Count Warning Doesn't Abort
- **File:** formats/archive_handler.py:651-653
- **Description:** check_entry_count error logged as warning but extraction continues. 200K+ files proceed.

### SEC-L11: odfpy Inherits Billion-Laughs Exposure
- **Files:** formats/odt_handler.py, ods_handler.py, odp_handler.py
- **Description:** odfpy uses xml.etree.ElementTree internally. Same entity expansion risk as SEC-C07.

### SEC-L12: RTF Regex Fallback ReDoS on Pathological Input
- **File:** formats/rtf_handler.py:54
- **Description:** Quadratic backtracking possible if striprtf is absent and file is malformed.
