# MarkFlow — Project Memory & Roadmap
**Doc-Conversion-2026 | GitHub: `github.com/theace26/Doc-Conversion-2026`**
*Last updated: 2026-03-26 | Session context: Claude.ai (claude-sonnet-4-6)*

---

## What MarkFlow Is

A Python/FastAPI web application that converts documents bidirectionally between their native formats (DOCX, PDF, PPTX, XLSX, CSV) and Markdown — with OCR, fidelity-preserving round-trips, bulk repository indexing, full-text search, and AI-assisted querying. Runs in Docker. Designed to eventually serve as a conversion microservice for external systems (e.g. UnionCore).

---

## Current State — v0.19.0

> **Always check CLAUDE.md in the repo for the real-time source of truth.** This memory.md lags significantly behind the codebase.

| Item | Status |
|------|--------|
| Phases 0–7 | ✅ Complete |
| Auth (Phase 9 analogue) | ✅ JWT auth, OPERATOR/MANAGER/ADMIN roles |
| Test suite | ✅ (runs inside Docker) |
| LLM providers | ✅ core/crypto.py, core/llm_providers.py, core/llm_client.py |
| SECRET_KEY (Fernet) | ✅ env var — NOT MARKFLOW_SECRET_KEY |
| MCP server | ✅ Port 8001 |
| Image analysis queue | ✅ migration 19, core/analysis_worker.py |
| Schema normalization | ✅ migration 20 — bulk_files UNIQUE(source_path), one row per file |
| Process Pending | ✅ POST /api/pipeline/process-pending, UI button on Status + Admin pages |

---

## Build Phase History

### Phase 0 — Foundation ✅
Docker scaffold, project structure, SQLite schema (aiosqlite), health check endpoint. Set the tone for the whole architecture.

### Phase 1 — DOCX → Markdown ✅
DocumentModel, DocxHandler, metadata extraction, basic upload UI. Established the format registry pattern and fidelity tier concept.

### Phase 2 — Markdown → DOCX Round-Trip ✅
Three fidelity tiers introduced:
- **Tier 1**: Structure from markdown alone
- **Tier 2**: Styles from `.styles.json` sidecar (keyed by SHA-256 content hash)
- **Tier 3**: Patch original file — only changed content is touched

Prompt: `markflow-phase2-prompt.md`

### Phase 3 — OCR Pipeline ✅
Multi-signal OCR detection, Tesseract integration, interactive review UI for low-confidence text, unattended mode for batch. Prompt: `markflow-phase3-prompt.md`

### Phase 4 — Remaining Formats ✅
PDF (pdfplumber + pdf2image + weasyprint), PPTX (python-pptx), XLSX/CSV (openpyxl + pandas) — both directions. Prompt: `markflow-phase4-prompt.md`

### Phase 5 — Testing & Debug Infrastructure ✅
Full pytest suite, pytest-asyncio, httpx for API testing, debug dashboard.

### Phase 6 — Full UI Polish ✅
Batch progress UI, history page, settings page, vanilla HTML/JS throughout (no SPA).

### Phase 7 — Bulk Conversion, Adobe, Search ✅
- Bulk converter: reads from network share (read-only), writes to mirrored local repo, incremental (path + mtime in SQLite), resume-capable
- Adobe indexing (Level 2): .ai (PDF stream), .psd (psd-tools), .indd/.aep/.prproj/.xd (metadata only via pyexiftool)
- Meilisearch integration: full-text search across markdown repo, results link to both original and .md versions
- Cowork integration pattern: Cowork → Meilisearch → top .md files → reasoning/synthesis
- Plan doc: `markflow-phase7-plan-v3.md`

### Phase 8 — Media & Visual Enrichment 🔨 IN PROGRESS

Split into two sub-phases:

**v0.8.0 — Media Transcription**
- Whisper (local) for audio/video → transcript
- Cloud provider fallback (reuses LLM provider infrastructure)
- Caption ingest (SRT/VTT)
- Transcripts indexed in Meilisearch (separate index)
- 2 new MCP tools
- Execution doc: v0.8.0-changeset

**v0.8.1 — Visual Enrichment**
- Scene detection on video
- Keyframe extraction
- VisionAdapter (`core/vision_adapter.py`) wraps active LLM provider for frame descriptions
- Active LLM provider = vision provider (no separate selector)
- Execution doc: v0.8.1-visual-enrichment-changeset

**Phase 8 architecture rules (hard constraints):**
- Do NOT create new provider infrastructure — reuse core/crypto.py, core/llm_providers.py, core/llm_client.py
- Media/vision preferences go in `_PREFERENCE_SCHEMA` (not a new DB table)
- Key file names: `core/database.py` (NOT core/db.py), `core/search_client.py` (NOT meilisearch_client.py)
- Append to `mcp_server/tools.py` — do NOT replace it

---

## Upcoming Phases (Planned)

### Phase 9 — Authentication & Multi-User 🔲
Not started. Will add:
- User accounts, sessions, JWT or cookie-based auth
- Per-user conversion history and settings
- Admin role for bulk job management
- This is a **significant architecture fork** — see Fork #1 below

### Phase 10 — Level 3 Adobe Enrichment 🔲
Enrichment pass against already-indexed Adobe files:
- OCR on rasterized text layers
- AI visual descriptions of design artifacts
- Runs as a background enrichment job, not a new ingestion program
- Reuses VisionAdapter from Phase 8

### Phase 11 — UnionCore Integration 🔲
MarkFlow exposed as a standalone HTTP microservice:
- Conversion endpoint, health check, capability manifest
- UnionCore calls MarkFlow's API; MarkFlow doesn't call back
- See `MarkFlow_Integration_Brief.md` for the cross-project context
- Decision point: embedded library vs. HTTP service (Fork #2 below)

---

## Project Documents Reference

| File | Purpose |
|------|---------|
| `CLAUDE.md` | **Source of truth** — auto-loaded by Claude Code. Phase checklist, current status, gotchas. Updated after every phase. |
| `markflow-prompt-v3.md` | Master build prompt — full spec for the entire project |
| `markflow-phase2-prompt.md` | Phase 2 build prompt |
| `markflow-phase3-prompt.md` | Phase 3 build prompt |
| `markflow-phase4-prompt.md` | Phase 4 build prompt |
| `markflow-phase7-plan-v3.md` | Phase 7 bulk/search/Cowork planning |
| `markflow-phase8-master-spec-revised.md` | Phase 8 spec (supersedes all prior Phase 8 docs) |
| `MarkFlow_Integration_Brief.md` | Summary for pasting into UnionCore project |
| `MarkFlow_Troubleshooting_Guide.md` | Debug and failure mode reference |
| `MarkFlow_Project_Instructions.md` | Claude.ai project instructions file |
| `memory.md` | This file |

---

## Architecture Rules (Non-Negotiable)

These were established early and have held through every phase. Any change requires explicit discussion.

| Rule | Rationale |
|------|-----------|
| **No Pandoc** | Black box — prevents metadata extraction and round-trip fidelity |
| **No SPA** | Vanilla HTML + fetch only. No React, Vue, Angular. |
| **Fail gracefully** | One bad file never crashes a batch. Log it, record in manifest, continue. |
| **Content-hash keying** | Sidecar JSON keyed by SHA-256 of normalized text. Survives element reorder. |
| **Format registry pattern** | Handlers register by extension. Converter looks up handler by extension. |
| **Fidelity tiers** | Tier 1/2/3 for progressively better round-trip quality. |
| **Read-only source** | Bulk conversion never touches the source network share. |
| **SQLite via aiosqlite** | Persistence layer. No Postgres/MySQL for this project scope. |
| **structlog JSON logging** | Structured logs throughout. No bare print() in production paths. |
| **SECRET_KEY env var** | Fernet encryption key. Variable is SECRET_KEY — not MARKFLOW_SECRET_KEY. |

---

## Key Technical Decisions Made

### LLM Provider Architecture (v0.7.4)
Providers (OpenAI, Anthropic, Ollama, etc.) are stored encrypted in SQLite using Fernet symmetric encryption. The SECRET_KEY env var is the encryption key. The `core/llm_client.py` module provides a unified interface. **This infrastructure must be reused by Phase 8 — do not create parallel provider code.**

### Cowork Integration Pattern
Cowork cannot hold the full markdown repository in context (~50K+ tokens for even a modest repo). Established pattern:
1. Cowork sends query to Meilisearch API
2. Meilisearch returns top N document references
3. Cowork reads the full `.md` files for those top results (~10 docs × 5K tokens ≈ 50K tokens — within budget)
4. Cowork reasons and synthesizes; Meilisearch does the narrowing

This pattern is load-bearing for the whole search/AI value prop. Don't break it.

### MCP Server
Runs on port 8001. Currently 7 tools. Phase 8 adds 2 more (transcription-related). Append to `mcp_server/tools.py` — never replace the file wholesale.

### Vision Provider
Single `core/vision_adapter.py` wraps the active LLM provider. No separate vision provider selector — whatever LLM provider is active is the vision provider. Established in Phase 8 planning.

---

## Future Ideas (Backlog)

These are not committed to any phase — just captured for later evaluation.

### Conversion & Format Enhancements
- **EPUB support** — bidirectional. Natural for document-heavy repositories.
- **RTF support** — legacy documents are common in union/labor environments.
- **Markdown flavors** — GitHub Flavored Markdown vs. standard vs. Obsidian-flavored. Currently outputs standard; GFM would improve GitHub usability.
- **Mermaid diagram round-trip** — PPTX shapes/SmartArt → Mermaid diagrams in markdown. Hard but high value.
- **LaTeX export** — for academic/technical documents.
- **Diff-aware conversion** — instead of re-converting a modified file from scratch, detect changed sections and patch only those. Would drastically speed up incremental bulk runs.

### Search & Retrieval
- **Semantic search** — add vector embeddings (pgvector or Meilisearch's built-in vector search) alongside keyword search. Hybrid retrieval for better AI query results.
- **Faceted search UI** — filter by file type, date range, author, fidelity tier, conversion status.
- **Search result previews** — snippet highlighting in the search UI.
- **Saved searches / alerts** — notify when new documents match a saved query.

### AI & Enrichment
- **Auto-tagging** — LLM-generated tags/topics for each converted document, stored in Meilisearch.
- **Summary generation** — auto-generate a 2–3 sentence summary for each converted document.
- **Entity extraction** — extract named entities (people, organizations, dates, dollar amounts) from converted docs. Particularly useful for labor/union document repositories.
- **Document clustering** — group similar documents automatically. Useful for large repositories with duplicates or near-duplicates.
- **Relationship graph** — detect cross-document references and build a document graph.

### Operations & Reliability
- **Webhook notifications** — notify an external URL when a bulk job completes or fails.
- **Retry queue** — failed files get queued for retry with exponential backoff, separate from the main batch flow.
- **Conversion queue priority** — high-priority single-file conversions jump the queue ahead of bulk jobs.
- **Health dashboard improvements** — live charts of conversion throughput, error rates, queue depth.
- **Backup/restore** — export/import the full SQLite DB + sidecar JSON store + Meilisearch index as a portable snapshot.

### Integration & Deployment
- **S3/object storage support** — output to S3 instead of (or in addition to) local NAS. Important if deployment moves to cloud.
- **Kubernetes/Helm chart** — for larger deployments. Currently docker-compose is sufficient.
- **CLI tool** — `markflow convert file.docx` as a standalone command separate from the web UI. Useful for scripting and automation.
- **Browser extension** — "Convert this page to Markdown" button. Stretch goal.

---

## Forks in the Road — Decision Points Coming

These are architectural decisions that will need to be made before or during their respective phases. Getting these wrong creates expensive rework.

---

### Fork #1 — Authentication Architecture (Before Phase 9)

**The question:** How much auth complexity does MarkFlow actually need?

**Option A — Single-user with API key auth**
- Simple Bearer token in requests
- No user accounts, no session management
- Appropriate if MarkFlow stays a personal/homelab tool or a backend service called by UnionCore
- Fast to implement, low surface area for bugs

**Option B — Multi-user with local accounts**
- User table in SQLite, JWT sessions, bcrypt passwords
- Each user sees their own conversion history
- Admin role for bulk job management
- Appropriate if multiple people use the MarkFlow UI directly

**Option C — SSO/OAuth only (no local passwords)**
- Delegate auth entirely to an identity provider (Google, Authelia, Authentik)
- No password storage, lower security burden
- Works well in homelab with existing Authelia/Authentik setup
- Requires the identity provider to always be available

**Recommendation when ready:** If MarkFlow is primarily a backend service for UnionCore (and your personal use), Option A is the right call. Option C is the right call if you deploy a homelab identity provider anyway (which you probably should for the broader home lab). Option B is only worth it if multiple non-technical people need their own MarkFlow accounts with no SSO available.

---

### Fork #2 — UnionCore Integration Mode (Before Phase 11)

**The question:** Does UnionCore embed MarkFlow as a library, or call it as an HTTP service?

**Option A — HTTP Microservice**
- MarkFlow runs as its own Docker container
- UnionCore calls `POST /api/v1/convert` over the network
- Clean separation of concerns, independent deployment, independent scaling
- Adds network latency and a dependency on MarkFlow being up
- Already how MarkFlow is architected — the natural path

**Option B — Embedded Python Library**
- UnionCore imports MarkFlow's converters directly as Python packages
- No network hop, no separate service to keep running
- Tight coupling — MarkFlow changes can break UnionCore
- Requires MarkFlow to be installable as a package (setup.py/pyproject.toml refactor needed)

**Option C — Shared Filesystem / File Drop**
- UnionCore writes files to a watched folder; MarkFlow picks them up and converts
- No API contract, just filesystem conventions
- Very fragile, hard to get status back to UnionCore
- Only viable as a quick integration prototype

**Recommendation when ready:** Option A. It's already the architecture. The `MarkFlow_Integration_Brief.md` was written with this in mind. Lock this in early so Phase 11 doesn't require rearchitecting MarkFlow.

---

### Fork #3 — Storage Backend (Before Phase 11 or if deployment grows)

**The question:** Does MarkFlow stay on SQLite + local filesystem, or does it need to grow?

**Current:** SQLite (aiosqlite) + local disk + Synology NAS mount. Fine for single-node, single-user, homelab scale.

**Triggers that would force a migration:**
- Multiple MarkFlow instances (horizontal scaling)
- Storing converted files in S3/object storage instead of local disk
- UnionCore needs to query MarkFlow's database directly (not via API)
- Conversion job volume exceeds SQLite write throughput (rough threshold: ~1,000 concurrent writes/second — unlikely for this use case)

**If migration is needed:** PostgreSQL (asyncpg) is the natural upgrade path. The aiosqlite interface is close enough that migration is mostly schema + connection string changes, not logic rewrites. Structure the ORM layer cleanly now so migration is surgical, not a full rewrite.

**Recommendation:** Don't migrate until a concrete trigger exists. SQLite is underrated and perfectly capable for this workload.

---

### Fork #4 — Adobe Level 3 Enrichment vs. External Tools (Before Phase 10)

**The question:** Should Level 3 Adobe enrichment (OCR + AI visual descriptions) be built into MarkFlow, or offloaded to purpose-built tools?

**Option A — Native in MarkFlow**
- OCR on rasterized frames using Tesseract (already integrated)
- Visual descriptions via VisionAdapter (established in Phase 8)
- Consistent with the existing architecture
- Works offline if using local Ollama models

**Option B — Delegate to external tools**
- Tools like Adobe Firefly API, Google Vision API, or Azure AI Vision
- Higher quality for design-specific content recognition
- Adds external API dependencies and cost
- Less consistent with the local-first, privacy-conscious homelab philosophy

**Recommendation when ready:** Option A first — it's already half-built via Phase 8's VisionAdapter. Add Option B as an opt-in enrichment provider through the existing LLM provider registry. No hard choice yet.

---

### Fork #5 — Meilisearch vs. Vector Search (Before or During semantic search backlog item)

**The question:** When/if semantic (AI-powered) search gets added, do we augment Meilisearch or replace it?

**Option A — Augment Meilisearch**
- Meilisearch 1.x has experimental vector search support
- Keep existing keyword search, add vector as a hybrid re-ranking layer
- Minimal disruption to current architecture

**Option B — Add a dedicated vector store**
- Qdrant, Chroma, or pgvector (if Postgres migration has happened)
- More capable vector operations, better scaling
- Another service to run and maintain

**Option C — Replace Meilisearch entirely**
- Use a single system that does both keyword + vector (e.g., Qdrant, Weaviate)
- Cleaner architecture long-term
- High migration cost for current search integrations

**Recommendation when ready:** Option A for now. Meilisearch's vector search has matured. Only revisit if Meilisearch's vector capabilities prove insufficient after real-world testing.

---

## Cross-Project Context

### UnionCore
A separate project. MarkFlow's relationship to it is as a **conversion service** — MarkFlow provides an API, UnionCore calls it. Do not redesign MarkFlow around UnionCore's internal needs. The `MarkFlow_Integration_Brief.md` file is the handoff document for that project's sessions.

### IP2A (Pre-Apprenticeship Database)
Completely separate project — IBEW Local 46 work. No technical overlap with MarkFlow unless IP2A eventually needs document conversion (possible, but not planned).

### Home Lab
The infrastructure MarkFlow runs on. Synology NAS is the target storage for the bulk-converted markdown repository. Network share (SMB/CIFS) is the source. If the home lab evolves (Proxmox, Kubernetes, Authelia/Authentik for SSO), some of the Forks above become easier to resolve.

---

## Session Management Notes

- **Each Claude Code session should target one phase or sub-phase.** Long sessions drift.
- **CLAUDE.md in the repo is the source of truth between sessions** — it survives session resets where this memory doc may not.
- **Phase 8 spec file (`markflow-phase8-master-spec-revised.md`) supersedes all prior Phase 8 planning docs.** If there's a conflict, the spec file wins.
- **When starting a new Claude Code session for a build phase:** paste the phase prompt, reference CLAUDE.md, and note the current version number.
- **When starting a new Claude.ai planning session:** attach CLAUDE.md and this memory.md to give the session immediate full context.

---

## Version History Snapshot

| Version | Milestone |
|---------|-----------|
| v0.1.0 | Phase 0 — Docker scaffold |
| v0.2.0 | Phase 1 — DOCX → MD |
| v0.3.0 | Phase 2 — Round-trip fidelity tiers |
| v0.4.0 | Phase 3 — OCR pipeline |
| v0.5.0 | Phase 4 — All formats |
| v0.6.0 | Phase 5 — Test suite |
| v0.7.0 | Phase 6 — Full UI |
| v0.7.1–v0.7.3 | Phase 7 — Bulk, Adobe, Meilisearch, Cowork |
| v0.7.4 | LLM providers + MCP server (7 tools) |
| v0.7.4b | Path safety (core/path_utils.py) |
| v0.8.0–v0.16.x | Media transcription, visual enrichment, auth, lifecycle management, multi-source |
| v0.17.x | Scan coordinator, scheduler yield guards, skip reason tracking, job detail |
| v0.18.0 | Image analysis queue (migration 19) + pipeline stats |
| v0.19.0 | bulk_files schema normalization (migration 20) + process-pending |
| v1.0.0 | Stable production release *(target)* |

---

*This document is a living record. Update it at the start of each planning session with any decisions made, forks resolved, or new ideas surfaced.*
