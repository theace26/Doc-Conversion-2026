# MarkFlow Changeset: LLM Providers, MCP Server & Auto-OCR Gap-Fill
# Selectable LLM providers in settings, Claude MCP server, auto-OCR on un-OCR'd PDFs

**Version:** v1.0
**Targets:** v0.7.4 tag
**Prerequisite:** v0.7.3 tagged and complete
**Scope:** Four independent tracks that ship together. No changes to conversion
logic, format handlers, or existing OCR engine math.

---

## 0. Read First

Load `CLAUDE.md` before writing anything. This changeset has four tracks:

| Track | What |
|-------|------|
| A | Auto-OCR gap-fill — find and OCR PDFs that were converted without OCR |
| B | LLM provider system — pluggable API-backed AI for enhancement tasks |
| C | Settings UI — provider selection, API key entry, connection verification |
| D | MCP server — expose MarkFlow tools to Claude.ai via Model Context Protocol |

Tracks A–C are internal to MarkFlow. Track D is a separate server process that runs
alongside MarkFlow and connects to Claude.ai. They share the same database and
output repository but are otherwise independent.

---

## 1. Track A — Auto-OCR Gap-Fill

### 1.1 What "needs OCR but hasn't had it" means

A converted PDF is considered un-OCR'd if ALL of the following are true:
- It has a record in `conversion_history` with `format = "pdf"`
- `ocr_page_count IS NULL` (OCR stats were never recorded)
- The output `.md` file exists on disk
- The original source PDF is still accessible

This covers two cases:
1. Files converted before Phase 3 (OCR pipeline didn't exist yet)
2. Files converted with `ocr_mode = "skip"` that the user now wants to OCR

### 1.2 On Upload — Single File Gap-Fill

#### `core/converter.py` (modify)

After a PDF conversion completes, check if OCR was skipped when it shouldn't have been.
Add a post-conversion OCR check:

```python
async def _check_and_run_deferred_ocr(self, history_id: str, source_path: Path,
                                       output_md_path: Path) -> None:
    """
    Called after a PDF conversion completes. If:
      - OCR was not run during conversion (ocr_page_count is null)
      - needs_ocr(source_path) returns True
      - ocr_mode preference is not 'skip'
    Then: run OCR now, update the .md file with OCR'd text, update history record.
    """
```

This runs automatically after every PDF conversion — the user never has to think about it.
Log at INFO level: `ocr_deferred_run` with `filename`, `reason` (was_skipped / pre_ocr_build).

### 1.3 Bulk Gap-Fill Pass

#### `core/bulk_worker.py` (modify)

Add a new job type: **OCR gap-fill pass**. This is a separate job mode, not part of the
normal conversion job. Triggered from the bulk UI or API.

```python
class BulkOcrGapFillJob:
    """
    Scans the output repository for .md files derived from PDFs that
    have no OCR record. Runs OCR on each and updates the .md + history.
    """

    async def run(self) -> None:
        """
        1. Query conversion_history for pdf records with ocr_page_count IS NULL
        2. For each: check source PDF still accessible + output .md exists
        3. Run OCR via existing pipeline
        4. Update .md file with OCR text (re-run export with OCR result merged)
        5. Update conversion_history ocr stats
        6. Emit SSE progress events
        """
```

#### `api/routes/bulk.py` (modify)

**`POST /api/bulk/ocr-gap-fill`** — start an OCR gap-fill pass

Request body:
```json
{
  "job_id": "...",          // optional — restrict to files from a specific bulk job
  "worker_count": 2,        // default 2 (OCR is CPU-heavy)
  "dry_run": false          // if true: just count and return, don't OCR anything
}
```

Response:
```json
{
  "gap_fill_id": "...",
  "files_found": 1243,
  "stream_url": "/api/bulk/ocr-gap-fill/{id}/stream",
  "dry_run": false
}
```

**`GET /api/bulk/ocr-gap-fill/pending-count`** — how many PDFs need OCR

Returns:
```json
{
  "count": 1243,
  "oldest_conversion": "2026-01-12T09:23:00Z"
}
```

Show this count prominently in the bulk UI — if > 0, display a banner:
```
⚠ 1,243 PDFs were converted without OCR. [Run OCR Gap-Fill →]
```

SSE events for gap-fill pass reuse the same event names as bulk conversion
(`file_converted` → `ocr_gap_filled`, `batch_complete` → `gap_fill_complete`).

### 1.4 Track A Done Criteria

- [ ] Single-file PDF upload runs deferred OCR if needed, updates history stats
- [ ] `GET /api/bulk/ocr-gap-fill/pending-count` returns accurate count
- [ ] `POST /api/bulk/ocr-gap-fill` with `dry_run: true` returns count without running OCR
- [ ] Gap-fill pass runs OCR and updates `.md` files and history records
- [ ] Gap-fill SSE stream emits progress events
- [ ] Bulk UI shows pending count banner when > 0
- [ ] Files with `ocr_mode = "skip"` preference are excluded from gap-fill

---

## 2. Track B — LLM Provider System

### 2.1 What LLMs are used for in MarkFlow

LLMs are NOT used for conversion (that stays library-only per architecture rules).
LLMs are used for **enhancement tasks** — optional passes that improve quality:

| Task | When Used |
|------|-----------|
| OCR text correction | After OCR, LLM cleans up garbled words using document context |
| Document summarization | Generates a 2–3 sentence summary stored in frontmatter |
| Heading inference | For PDFs with no font-size heading data, LLM infers heading hierarchy |
| Adobe text enrichment | For Level 3 Adobe indexing — AI description of visual content |

All enhancement tasks are **optional** and **non-blocking**. If no LLM is configured,
or if the LLM API call fails, conversion succeeds without enhancement. Log a warning.
Never fail a conversion because an LLM call failed.

### 2.2 Database

#### `core/database.py` (modify)

New table:

```sql
CREATE TABLE IF NOT EXISTS llm_providers (
    id              TEXT PRIMARY KEY,       -- UUID
    name            TEXT NOT NULL UNIQUE,   -- "My Claude", "Work OpenAI", etc.
    provider        TEXT NOT NULL,          -- 'anthropic' | 'openai' | 'gemini'
                                            -- | 'ollama' | 'custom'
    model           TEXT NOT NULL,          -- 'claude-sonnet-4-20250514', 'gpt-4o', etc.
    api_key         TEXT,                   -- encrypted at rest (see security note)
    api_base_url    TEXT,                   -- for custom/ollama: base URL
    is_active       INTEGER NOT NULL DEFAULT 0,  -- only one can be active at a time
    is_verified     INTEGER NOT NULL DEFAULT 0,  -- last verification passed
    last_verified   TEXT,                   -- ISO-8601 of last successful ping
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

**API key encryption** — keys are sensitive. Encrypt at rest using Fernet symmetric
encryption from the `cryptography` library. Encryption key derived from a
`SECRET_KEY` env var (required if any LLM provider is configured):

```python
# core/crypto.py (new small file)
from cryptography.fernet import Fernet
import base64, hashlib, os

def _get_fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise ValueError("SECRET_KEY env var required when storing API keys")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)

def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
```

Add `SECRET_KEY` to `.env.example` with a generation note:
```bash
# Required if you configure LLM providers (used to encrypt API keys at rest)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=
```

New DB helpers:
```python
async def create_llm_provider(name, provider, model, api_key=None,
                               api_base_url=None) -> str
async def get_llm_provider(provider_id) -> dict | None
    """Returns provider with api_key DECRYPTED."""
async def list_llm_providers() -> list[dict]
    """Returns providers with api_key MASKED ('sk-...****')."""
async def update_llm_provider(provider_id, **fields) -> None
async def delete_llm_provider(provider_id) -> None
async def set_active_provider(provider_id) -> None
    """Sets is_active=1 for this provider, is_active=0 for all others."""
async def get_active_provider() -> dict | None
    """Returns the currently active provider with api_key DECRYPTED, or None."""
```

### 2.3 Provider Definitions

#### `core/llm_providers.py` (new file)

```python
# Known providers with their models and API shapes
PROVIDER_REGISTRY = {
    "anthropic": {
        "display_name": "Claude (Anthropic)",
        "models": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
        "default_model": "claude-sonnet-4-6",
        "api_base_url": "https://api.anthropic.com",
        "requires_api_key": True,
        "docs_url": "https://console.anthropic.com/settings/keys"
    },
    "openai": {
        "display_name": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "default_model": "gpt-4o",
        "api_base_url": "https://api.openai.com",
        "requires_api_key": True,
        "docs_url": "https://platform.openai.com/api-keys"
    },
    "gemini": {
        "display_name": "Gemini (Google)",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
        "default_model": "gemini-1.5-flash",
        "api_base_url": "https://generativelanguage.googleapis.com",
        "requires_api_key": True,
        "docs_url": "https://aistudio.google.com/app/apikey"
    },
    "ollama": {
        "display_name": "Ollama (Local)",
        "models": [],           # populated dynamically by pinging /api/tags
        "default_model": "",    # user selects after fetch
        "api_base_url": "http://localhost:11434",
        "requires_api_key": False,
        "docs_url": "https://ollama.com/download"
    },
    "custom": {
        "display_name": "Custom (OpenAI-compatible)",
        "models": [],           # user enters manually
        "default_model": "",
        "api_base_url": "",     # user enters
        "requires_api_key": False,
        "docs_url": None
    }
}
```

#### `core/llm_client.py` (new file)

A unified async client that normalizes calls across providers. All providers receive
the same input and return the same output shape. This is the only file that knows
about provider-specific API differences.

```python
@dataclass
class LLMRequest:
    system_prompt: str
    user_message: str
    max_tokens: int = 1000
    temperature: float = 0.2       # low temp for correction tasks

@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    tokens_used: int | None
    duration_ms: int
    success: bool
    error: str | None = None

class LLMClient:
    def __init__(self, provider_config: dict):
        """provider_config is the decrypted row from llm_providers table."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route to the correct provider implementation."""

    async def ping(self) -> tuple[bool, str]:
        """
        Verify the provider is reachable and the API key works.
        Returns (success: bool, message: str).
        Sends a minimal test request: "Reply with the word OK."
        """

    # Private methods — one per provider
    async def _complete_anthropic(self, request) -> LLMResponse: ...
    async def _complete_openai(self, request) -> LLMResponse: ...
    async def _complete_gemini(self, request) -> LLMResponse: ...
    async def _complete_ollama(self, request) -> LLMResponse: ...
    async def _complete_custom(self, request) -> LLMResponse: ...
```

**Ollama special case** — `_complete_ollama` uses the OpenAI-compatible endpoint
(`/v1/chat/completions`) available in Ollama 0.1.24+. Fall back to native `/api/generate`
if the OpenAI endpoint returns 404.

**`ping()` implementation** — each provider uses the cheapest available verification:
- Anthropic: `POST /v1/messages` with `max_tokens: 5`
- OpenAI: `POST /v1/chat/completions` with `max_tokens: 5`
- Gemini: `POST /v1beta/models/{model}:generateContent` with minimal request
- Ollama: `GET /api/tags` (no test message needed — just check server is up and model exists)
- Custom: `POST {base_url}/v1/chat/completions` (assume OpenAI-compatible)

`ping()` never raises. Returns `(False, "error message")` on any failure.

#### `core/llm_enhancer.py` (new file)

Enhancement tasks that use the active LLM provider.

```python
class LLMEnhancer:
    def __init__(self, client: LLMClient | None):
        """client is None if no active provider configured."""

    async def correct_ocr_text(self, raw_text: str, context: str = "") -> str:
        """
        Given raw OCR output (possibly garbled), return corrected text.
        If client is None: return raw_text unchanged.
        If call fails: log warning, return raw_text unchanged.

        System prompt:
          "You are correcting OCR text from a scanned document. Fix spelling errors,
           garbled words, and formatting artifacts caused by OCR. Preserve all content,
           formatting markers (** for bold, # for headings), and line breaks.
           Return only the corrected text with no explanation."
        """

    async def summarize_document(self, markdown_text: str,
                                  title: str = "") -> str | None:
        """
        Generate a 2–3 sentence plain-text summary.
        Returns None if client is None or call fails.
        Stored in YAML frontmatter as 'summary:' field.
        """

    async def infer_headings(self, text_blocks: list[str]) -> list[str]:
        """
        Given a list of text blocks (paragraphs) from a PDF with no font data,
        return the same list with heading markers added where appropriate.
        Used only when PDF heading detection heuristics produce poor results.
        Returns input unchanged if client is None or call fails.
        """

    async def describe_image(self, image_data: bytes,
                              context: str = "") -> str | None:
        """
        Generate an alt-text description for an image.
        Used in Level 3 Adobe enrichment.
        Returns None if client is None, model lacks vision, or call fails.
        Only Anthropic and OpenAI support vision — Gemini and Ollama
        are checked for vision capability before attempting.
        """
```

All methods are **safe to call unconditionally**. The caller never needs to check
"is an LLM configured?" — the enhancer handles that internally.

### 2.4 Integration Points

The LLM enhancer hooks into existing pipeline stages:

**`core/ocr.py`** (modify) — after OCR extraction, if a flag has low confidence
and an LLM is active, call `correct_ocr_text()` on the flagged text. Store both
the raw OCR text and the LLM-corrected text in the `ocr_flags` record.
New column on `ocr_flags`:
```sql
ALTER TABLE ocr_flags ADD COLUMN llm_corrected_text TEXT;
ALTER TABLE ocr_flags ADD COLUMN llm_correction_model TEXT;
```

**`core/converter.py`** (modify) — after conversion, if LLM is active and
`llm_summarize` preference is true, call `summarize_document()` and write
the summary into the YAML frontmatter of the output `.md`.

**`formats/pdf_handler.py`** (modify) — in `ingest()`, if heading detection
heuristics produce < 3 headings in a document with > 20 paragraphs, call
`infer_headings()` as a fallback.

New preferences (add to `_PREFERENCE_SCHEMA` in `api/routes/preferences.py`):

| Key | Type | Default | Label |
|-----|------|---------|-------|
| `llm_ocr_correction` | toggle | false | Use LLM to correct low-confidence OCR text |
| `llm_summarize` | toggle | false | Generate document summaries |
| `llm_heading_inference` | toggle | false | Use LLM to infer headings in PDFs |

All three default to false — LLM enhancement is opt-in.

### 2.5 Track B Done Criteria

- [ ] `llm_providers` table created on startup
- [ ] API keys encrypted at rest using `SECRET_KEY` env var
- [ ] `LLMClient.ping()` works for Anthropic, OpenAI, Gemini, Ollama
- [ ] `LLMEnhancer.correct_ocr_text()` is called when `llm_ocr_correction = true`
  and a provider is active
- [ ] Enhancement failure never fails a conversion
- [ ] Three new preferences exposed in settings API
- [ ] LLM correction text stored in `ocr_flags.llm_corrected_text`

---

## 3. Track C — Settings UI

### `static/settings.html` (modify)

Add a new **AI Enhancement** section to the settings page.

#### Section: AI Enhancement

```
AI Enhancement
──────────────────────────────────────────────────────────
Configure an AI provider to enhance conversion quality.
AI is optional — conversions work without it.

Active Provider    [My Claude (claude-sonnet-4-6) ▾]
                   ✓ Connected · Last verified 2 min ago

[Manage Providers]                (links to providers.html)

Enhancement Options
───────────────────
OCR text correction       [ OFF ]   Fix garbled OCR words using AI
Document summaries        [ OFF ]   Add 2–3 sentence summary to each file
Heading inference         [ OFF ]   Infer PDF headings when font data is missing
```

The active provider dropdown is populated from `GET /api/llm-providers`.
Selecting a different provider calls `PUT /api/llm-providers/{id}/activate`.
The connection status badge is fetched from the provider's `is_verified` +
`last_verified` fields — not re-verified on every page load.

### `static/providers.html` (new page)

Dedicated LLM provider management page. Linked from Settings and the AI section.

Layout:
```
┌────────────────────────────────────────────────────────────┐
│  MarkFlow    [Convert][Bulk][Search][History][Settings]     │
├────────────────────────────────────────────────────────────┤
│  AI Providers                          [+ Add Provider]    │
│                                                            │
│  ● ACTIVE                                                  │
│  My Claude                          Anthropic              │
│  claude-sonnet-4-6                                         │
│  ✓ Verified 2 minutes ago          [Edit] [Verify] [Delete]│
│                                                            │
│  Work OpenAI                        OpenAI                 │
│  gpt-4o                                                    │
│  — Not verified                    [Edit] [Verify] [Activate] [Delete]│
│                                                            │
│  Local Ollama                       Ollama (Local)         │
│  llama3.2                                                  │
│  ✓ Verified 1 hour ago             [Edit] [Verify] [Activate] [Delete]│
└────────────────────────────────────────────────────────────┘
```

**Add / Edit provider form** — inline expansion:

```
Provider      [Claude (Anthropic) ▾]

Model         [claude-sonnet-4-6 ▾]
              (dropdown populated from PROVIDER_REGISTRY for known providers)

API Key       [sk-ant-•••••••••••••••••••••]    (masked, show/hide toggle)
              Get your key at console.anthropic.com/settings/keys ↗

              [Verify Connection]

              ┌─────────────────────────────────────────────┐
              │  ✓ Connected — claude-sonnet-4-6 responded  │
              │  "OK" in 430ms                              │
              └─────────────────────────────────────────────┘

[Save]  [Cancel]
```

**Ollama special behavior** — when Ollama is selected:
- API Key field is hidden (Ollama is local, no key needed)
- Base URL field shown instead (default `http://localhost:11434`)
- After entering base URL: "Fetch Available Models" button calls
  `GET /api/llm-providers/ollama-models?base_url=...` which pings Ollama's
  `/api/tags` endpoint and returns available model names
- Model dropdown populated from fetched list

**Custom provider** — both API Key and Base URL shown. Model is a free-text input.

**Verify Connection button:**
- Calls `POST /api/llm-providers/{id}/verify` (or `POST /api/llm-providers/verify-draft`
  for unsaved providers — sends current form values without saving first)
- Shows spinner while verifying
- Success: green checkmark + model response + latency
- Failure: red ✗ + error message (e.g., "Invalid API key", "Model not found",
  "Connection refused — is Ollama running?")

**Delete** — if the provider is active, show warning:
"This is your active provider. Deleting it will disable AI enhancement.
[Delete anyway] [Cancel]"

### LLM Provider API

#### `api/routes/llm_providers.py` (new file)

Router with prefix `/api/llm-providers`. Mount in `main.py`.

**`GET /api/llm-providers`** — list all providers (API keys masked)

**`GET /api/llm-providers/registry`** — return `PROVIDER_REGISTRY` dict so the
frontend can build the provider/model dropdowns without hardcoding them.

**`GET /api/llm-providers/ollama-models`**
Query param: `base_url` (default `http://localhost:11434`)
Fetches model list from Ollama. Returns `{"models": ["llama3.2", "mistral", ...]}`.
Returns `{"models": [], "error": "Cannot reach Ollama at ..."}` if unreachable.

**`POST /api/llm-providers`** — create provider

**`PUT /api/llm-providers/{id}`** — update provider

**`DELETE /api/llm-providers/{id}`** — delete provider. 409 if active and
`?force=true` not included.

**`POST /api/llm-providers/{id}/verify`** — verify saved provider
Runs `LLMClient.ping()`. Updates `is_verified` and `last_verified` in DB.
Returns:
```json
{
  "success": true,
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "response_preview": "OK",
  "latency_ms": 430,
  "verified_at": "ISO-8601"
}
```

**`POST /api/llm-providers/verify-draft`** — verify unsaved provider config
Same as above but takes the provider config in the request body (never saves).
Used by the "Verify Connection" button before the user clicks Save.

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "api_key": "sk-ant-...",
  "api_base_url": null
}
```

**`POST /api/llm-providers/{id}/activate`** — set as active provider

### Track C Done Criteria

- [ ] Settings page shows AI Enhancement section with active provider dropdown
- [ ] `providers.html` lists all providers with status badges
- [ ] Add/Edit form works for all five provider types
- [ ] Ollama model fetch works when Ollama is running locally
- [ ] Verify Connection works before saving (draft verify)
- [ ] Verify Connection updates is_verified + last_verified after save
- [ ] API keys are masked in UI and in `GET /api/llm-providers` response
- [ ] Activate/deactivate works — only one active provider at a time
- [ ] Delete active provider requires confirmation

---

## 4. Track D — MCP Server

### 4.1 What the MCP Server Does

The MarkFlow MCP server lets Claude.ai (or any MCP-compatible client) call MarkFlow
tools directly from a conversation. You connect it once in Claude.ai settings, and
from then on Claude can search your document repository, read files, check conversion
status, and trigger conversions — without leaving the conversation.

### 4.2 Architecture

The MCP server runs as a **separate process** alongside the main MarkFlow app.
It communicates with MarkFlow's internal services via direct function calls (shared
codebase) rather than HTTP — this keeps it fast and avoids auth complexity for the
internal connection.

It is exposed to Claude.ai via **SSE transport** (the MCP standard for remote servers).

```
Claude.ai ←→ MCP SSE transport ←→ markflow-mcp (port 8001)
                                        ↓
                               MarkFlow internals
                               (database, search, converter)
```

### 4.3 New Files

#### `mcp_server/server.py` (new file)

```python
"""
MarkFlow MCP Server
Exposes MarkFlow tools to Claude.ai and other MCP clients.
Run with: python -m mcp_server.server
Port: MCP_PORT env var (default 8001)
"""
```

Uses the `mcp` Python SDK (`pip install mcp`). Add to `requirements.txt`.

#### `mcp_server/__init__.py` (new file — empty)

#### `mcp_server/tools.py` (new file)

Defines the MCP tools. Each tool is a Python async function decorated with
`@mcp.tool()`. Tools must have clear docstrings — Claude.ai uses them to decide
when to call each tool.

---

### 4.4 MCP Tools

#### Tool: `search_documents`

```python
@mcp.tool()
async def search_documents(
    query: str,
    format: str | None = None,
    path_prefix: str | None = None,
    max_results: int = 10
) -> str:
    """
    Search the MarkFlow document index for files matching the query.
    Returns ranked results with document titles, paths, and content previews.

    Use this when the user asks to find documents, search for information
    across their file repository, or look up a specific topic.

    Args:
        query: Natural language search query
        format: Optional filter — 'docx', 'pdf', 'pptx', 'xlsx', or 'csv'
        path_prefix: Optional folder path prefix to restrict search scope
        max_results: Number of results to return (1-20, default 10)
    """
    # Calls core/search_indexer.py SearchIndexer.search()
    # Returns formatted markdown string with results
```

**Return format** (markdown string Claude can read directly):
```
Found 5 results for "Q4 financial results":

1. **Q4 Report** (docx)
   Path: dept/finance/Q4_Report.md
   Preview: The Q4 financial results show a 12% increase over Q3...

2. **Budget Summary Q4** (xlsx)
   Path: dept/finance/Q4_Budget.md
   Preview: Total expenditure across all departments...
```

#### Tool: `read_document`

```python
@mcp.tool()
async def read_document(
    path: str,
    max_tokens: int = 8000
) -> str:
    """
    Read the full content of a converted document from the repository.
    Returns the Markdown content of the document.

    Use this when the user asks to read, summarize, or analyze a specific
    document. The path should come from search_documents results.

    Args:
        path: Relative path to the .md file (e.g. 'dept/finance/Q4_Report.md')
        max_tokens: Maximum content length to return (default 8000)
    """
```

#### Tool: `list_directory`

```python
@mcp.tool()
async def list_directory(
    path: str = "",
    show_stats: bool = False
) -> str:
    """
    List documents and folders in the MarkFlow repository.
    Returns a directory tree of converted files.

    Use this when the user wants to browse what's in the repository,
    see what folders exist, or understand the structure.

    Args:
        path: Relative path within the repository (empty = root)
        show_stats: Include file count and last-modified date per folder
    """
```

#### Tool: `get_conversion_status`

```python
@mcp.tool()
async def get_conversion_status(
    batch_id: str | None = None
) -> str:
    """
    Get the status of document conversions.
    If batch_id provided: status of that specific batch.
    Otherwise: overall system status (recent conversions, active jobs).

    Use this when the user asks about conversion progress, recent activity,
    or whether a specific file has been converted.
    """
```

#### Tool: `convert_document`

```python
@mcp.tool()
async def convert_document(
    source_path: str,
    fidelity_tier: int = 2,
    ocr_mode: str = "auto"
) -> str:
    """
    Convert a single document to Markdown.
    The source_path must be accessible from within the MarkFlow container.

    Use this when the user asks to convert a specific file, or when
    read_document returns a 'not found' error for a file that exists
    on the source drive.

    Args:
        source_path: Container path to the source file (e.g. '/host/c/Users/.../file.docx')
        fidelity_tier: 1 (structure), 2 (styles), or 3 (patch original)
        ocr_mode: 'auto', 'force', or 'skip'
    """
```

#### Tool: `search_adobe_files`

```python
@mcp.tool()
async def search_adobe_files(
    query: str,
    file_type: str | None = None,
    max_results: int = 10
) -> str:
    """
    Search the Adobe creative file index for .ai, .psd, .indd, .aep,
    .prproj, and .xd files.

    Use this when the user asks about design files, creative assets,
    Photoshop files, Illustrator files, or InDesign documents.

    Args:
        query: Natural language search query
        file_type: Optional filter — 'ai', 'psd', 'indd', 'aep', 'prproj', 'xd'
        max_results: Number of results (1-20, default 10)
    """
```

#### Tool: `get_document_summary`

```python
@mcp.tool()
async def get_document_summary(
    path: str
) -> str:
    """
    Get the AI-generated summary for a document (if available) plus
    key metadata: title, format, conversion date, OCR confidence.

    Use this for a quick overview of a document without reading its
    full content. Faster than read_document for answering 'what is this
    file about?' questions.

    Args:
        path: Relative path to the .md file
    """
```

### 4.5 Docker Compose Integration

#### `docker-compose.yml` (modify)

Add MCP server service:

```yaml
  markflow-mcp:
    build: .
    command: python -m mcp_server.server
    ports:
      - "8001:8001"
    environment:
      - DB_PATH=/app/data/markflow.db
      - OUTPUT_DIR=/app/output
      - MCP_PORT=8001
      - MCP_AUTH_TOKEN=${MCP_AUTH_TOKEN:-}
      - MEILI_HOST=${MEILI_HOST:-http://meilisearch:7700}
      - MEILI_MASTER_KEY=${MEILI_MASTER_KEY:-}
    volumes:
      - markflow-db:/app/data
      - ./output:/app/output
      - C:/:/host/c:ro
      - D:/:/host/d:ro
      - C:/Users/${USERNAME:-user}/markflow-output:/mnt/output-repo
    depends_on:
      - app
      - meilisearch
```

Add to `.env.example`:
```bash
# MCP Server
MCP_PORT=8001
# Optional auth token — if set, Claude.ai must include this in the MCP connection URL
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
MCP_AUTH_TOKEN=
```

### 4.6 Authentication

The MCP server supports an optional bearer token (`MCP_AUTH_TOKEN` env var).
If set, all MCP connections must include it in the URL:
`http://localhost:8001/mcp?token=your-token-here`

If `MCP_AUTH_TOKEN` is empty: no auth (fine for local home lab use).

### 4.7 Settings UI — MCP Connection Info

#### `static/settings.html` (modify)

Add a **Claude Integration (MCP)** section at the bottom of settings:

```
Claude Integration (MCP)
──────────────────────────────────────────────────────────
Connect MarkFlow to Claude.ai so Claude can search and read
your documents directly from any conversation.

MCP Server URL    http://your-machine-ip:8001/mcp
                  (replace with your machine's IP address)

Status            ✓ MCP server running

Setup Instructions:
  1. Open Claude.ai → Settings → Integrations
  2. Click "Add Integration"
  3. Paste the URL above
  4. Click Connect

Once connected, Claude can:
  • Search your 56,200 converted documents
  • Read document content
  • Check conversion status
  • Trigger new conversions

[Copy URL]  [Test MCP Server →]
```

"Test MCP Server →" opens `http://localhost:8001/health` in a new tab.
"Copy URL" copies the MCP URL to clipboard.

The displayed IP is fetched from `GET /api/mcp/connection-info` (new endpoint):

```json
{
  "mcp_url": "http://192.168.1.45:8001/mcp",
  "mcp_running": true,
  "tool_count": 6,
  "auth_required": false
}
```

#### `api/routes/mcp_info.py` (new file)

```python
# GET /api/mcp/connection-info
# Returns MCP server connection details for the settings UI
```

Uses `socket.gethostbyname(socket.gethostname())` to get the machine's local IP.

### 4.8 Track D Done Criteria

- [ ] `python -m mcp_server.server` starts without error
- [ ] MCP server starts automatically via docker-compose
- [ ] `search_documents` tool returns ranked results
- [ ] `read_document` tool returns file content
- [ ] `list_directory` tool returns folder tree
- [ ] `get_conversion_status` tool returns accurate status
- [ ] `convert_document` tool triggers a conversion and returns batch_id
- [ ] `search_adobe_files` tool queries the adobe-files index
- [ ] `get_document_summary` tool returns summary + metadata
- [ ] Optional `MCP_AUTH_TOKEN` auth works
- [ ] Settings page shows MCP connection URL and running status
- [ ] Tool docstrings are clear and accurate (Claude uses these to decide when to call)

---

## 5. Tests

### `tests/test_auto_ocr.py` (new)

- [ ] Single-file PDF conversion records OCR stats in history
- [ ] PDF converted without OCR gets deferred OCR on re-upload if `needs_ocr()` is true
- [ ] `GET /api/bulk/ocr-gap-fill/pending-count` returns correct count
- [ ] Gap-fill dry run returns count without modifying any files
- [ ] Gap-fill pass updates `ocr_page_count` in history records
- [ ] Files with `ocr_mode=skip` preference excluded from gap-fill

### `tests/test_llm_providers.py` (new)

- [ ] API key is encrypted in DB and decrypted on read
- [ ] `GET /api/llm-providers` returns masked API key (`sk-...****`)
- [ ] `POST /api/llm-providers/verify-draft` with Anthropic config calls ping (mocked)
- [ ] `POST /api/llm-providers/{id}/verify` updates `is_verified` and `last_verified`
- [ ] `POST /api/llm-providers/{id}/activate` sets only that provider active
- [ ] `LLMEnhancer.correct_ocr_text()` returns input unchanged when no client configured
- [ ] `LLMEnhancer.correct_ocr_text()` returns input unchanged when LLM call fails
- [ ] Conversion does not fail when LLM enhancement raises an exception

### `tests/test_mcp_server.py` (new)

- [ ] MCP server starts and responds to health check
- [ ] `search_documents` tool returns formatted results
- [ ] `read_document` tool reads `.md` file content
- [ ] `convert_document` tool triggers conversion and returns batch_id
- [ ] Auth token rejection when `MCP_AUTH_TOKEN` is set and token is wrong
- [ ] All tools handle empty/missing data gracefully (no 500s)

---

## 6. Done Criteria (Full Changeset)

- [ ] Track A: Deferred OCR runs on PDFs that need it; gap-fill pass works
- [ ] Track B: LLM providers stored encrypted; ping/verify works for all providers;
  enhancement tasks are opt-in and never fail conversions
- [ ] Track C: Providers page manages providers; verify-before-save works;
  settings page shows AI section and MCP section
- [ ] Track D: MCP server runs, all 6 tools work, settings shows connection URL
- [ ] All prior tests still passing
- [ ] New tests: 30+ covering all four tracks
- [ ] `docker-compose up` starts app + mcp server + meilisearch cleanly
- [ ] Manual smoke: Add Claude API key → Verify → Enable OCR correction →
  Convert a scanned PDF → confirm LLM-corrected text appears in output

---

## 7. CLAUDE.md Update

```markdown
**v0.7.4** — LLM providers (Anthropic, OpenAI, Gemini, Ollama, custom), API key
  encryption, connection verification, opt-in OCR correction + summarization +
  heading inference. Auto-OCR gap-fill for PDFs converted without OCR.
  MCP server (port 8001) exposes 6 tools to Claude.ai: search, read, list,
  convert, adobe search, get summary.
```

Add to Gotchas:
```markdown
- **SECRET_KEY required for LLM providers**: If any LLM provider is configured,
  SECRET_KEY env var must be set or the app raises ValueError on startup.
  Generate with: python -c "import secrets; print(secrets.token_hex(32))"

- **MCP server is a separate process**: markflow-mcp runs independently of the
  main app. It shares the database and filesystem but has its own port (8001).
  If the main app is down, MCP tools that need live conversion will fail gracefully.

- **Ollama OpenAI-compat endpoint**: _complete_ollama() tries /v1/chat/completions
  first (available in Ollama 0.1.24+). Falls back to /api/generate if 404.
  The fallback uses a different request/response shape — both are handled.

- **LLM enhancement is always opt-in**: All three preference toggles default to
  false. An active provider with all toggles off does nothing to conversions.
  The verify/ping still works regardless of toggle state.

- **MCP tool docstrings are functional**: Claude.ai uses tool docstrings to decide
  when to call each tool. Do not simplify or shorten them without considering
  how that affects Claude's tool selection behavior.
```

Tag: `git tag v0.7.4 && git push origin v0.7.4`

---

## 8. Output Cap Note

Recommended turn boundaries:

1. **Turn 1**: Track A — deferred OCR in converter, gap-fill job, bulk API endpoints,
   `tests/test_auto_ocr.py`
2. **Turn 2**: Track B — `core/crypto.py`, `core/llm_providers.py`, `core/llm_client.py`,
   `core/llm_enhancer.py`, DB schema, integration hooks in ocr.py + converter.py
3. **Turn 3**: Track B tests + `api/routes/llm_providers.py`
4. **Turn 4**: Track C — `static/providers.html`, settings.html AI section,
   `tests/test_llm_providers.py`
5. **Turn 5**: Track D — `mcp_server/server.py`, `mcp_server/tools.py`,
   docker-compose update, `api/routes/mcp_info.py`, settings.html MCP section
6. **Turn 6**: Track D tests, final integration, CLAUDE.md update, tag
