# MarkFlow: Document Search & Discovery Capabilities

**Prepared for:** Stakeholder Review
**Date:** April 6, 2026
**Version:** MarkFlow v0.22.0

---

## Executive Summary

MarkFlow is an enterprise document conversion and search system that transforms documents from 130+ file formats into searchable, indexed content. It combines four layers of search capability — from basic keyword matching through semantic vector search to AI-powered natural language queries — enabling staff to find information across thousands of documents without knowing exact filenames, locations, or search terms.

This document outlines each search capability, how it works, and provides practical examples relevant to day-to-day use.

---

## How MarkFlow Makes Documents Searchable

Before any search can happen, MarkFlow performs a critical step that most search tools skip: **it reads the actual content of every document**.

Traditional file search (Windows Explorer, network share search) only looks at filenames and basic metadata. MarkFlow opens each file — Word documents, PDFs, PowerPoints, Excel spreadsheets, scanned images, audio recordings, even password-protected files — extracts the full text content, and indexes it for search.

| What MarkFlow Does | What This Means |
|---------------------|-----------------|
| Converts 130+ file formats to text | Every document's content is searchable, not just its filename |
| OCR for scanned PDFs and images | Even paper documents that were scanned become searchable |
| Transcribes audio and video files | Meeting recordings, voicemails, and training videos become searchable text |
| Cracks password-protected files | Documents locked behind forgotten passwords are recovered and indexed |
| Extracts text from Adobe creative files | InDesign, Photoshop, and Illustrator files have their text layers indexed |
| Processes email attachments recursively | An Excel file inside a ZIP file attached to an email — all searchable |

---

## Search Capability Levels

### Level 1: Full-Text Keyword Search (Built In)

**What it is:** A search box in the MarkFlow web interface that searches across the full content of every converted document. Powered by Meilisearch, an enterprise-grade search engine.

**Key features:**
- **Typo tolerance** — Searching "conract" still finds "contract"
- **Instant results** — Results appear as you type, under 50 milliseconds
- **Format filtering** — Narrow results by file type (e.g., only PDFs, only Word docs)
- **Sort options** — By relevance, date, file size, or format
- **Hover preview** — See document content without opening the file
- **Batch download** — Select multiple results and download as a ZIP

**Practical examples:**

| You Search For | What MarkFlow Finds |
|---------------|---------------------|
| `collective bargaining agreement` | Every document containing that phrase — contracts, memos, emails, meeting notes |
| `Smith resignation` | HR letters, email threads, and board minutes mentioning Smith's resignation |
| `budget 2025 facilities` | Budget spreadsheets, planning documents, and approval emails related to 2025 facilities spending |
| `OSHA violation` | Incident reports, compliance documents, and correspondence mentioning OSHA violations |
| `insurance renewal` | Policy documents, broker correspondence, and budget items about insurance renewals |

**Who can use it:** Any authorized user through a web browser. No special software or training required.

---

### Level 2: Semantic Vector Search (Built In)

**What it is:** A second search engine that understands the *meaning* of your query, not just the words. Powered by a local AI model (all-MiniLM-L6-v2) and Qdrant vector database, it runs alongside keyword search and merges results automatically.

**How it works:**

1. Every converted document is split into contextual chunks (~400 tokens each)
2. Each chunk is converted into a mathematical vector representing its meaning
3. When you search, your query is also converted to a vector
4. The system finds chunks whose meaning is closest to your query
5. Results from both keyword search and vector search are merged using Reciprocal Rank Fusion (RRF)

**Key features:**
- **Meaning-based matching** — Searching "employee termination procedures" also finds documents about "dismissal process," "letting someone go," or "separation policy" even if they never use the word "termination"
- **Runs locally** — The embedding model runs entirely on the server. No documents or queries are sent to any external service.
- **Automatic fallback** — If the vector engine is unavailable, search seamlessly falls back to keyword-only mode
- **Time-aware queries** — Queries like "recent budget reports" automatically bias results toward newer documents

**Practical examples:**

| You Search For | What Keyword Search Finds | What Vector Search Also Finds |
|---------------|--------------------------|------------------------------|
| `workplace safety requirements` | Documents with those exact words | OSHA compliance docs, hazard assessments, and safety training materials that discuss the concept differently |
| `hiring process` | Documents mentioning "hiring process" | Recruitment guides, onboarding checklists, and job posting templates |
| `financial projections` | Exact matches only | Budget forecasts, revenue models, and capital planning documents |

**Who can use it:** Any authorized user. Vector search is automatic — it enhances every search without any extra steps.

---

### Level 3: API-Driven Programmatic Search

**What it is:** A REST API that allows other software systems to search MarkFlow's document index programmatically. Enables integration with existing internal tools, dashboards, and workflows.

**Key features:**
- **Standard REST API** with interactive documentation
- **API key authentication** for service accounts
- **Paginated results** with filtering and sorting
- **Structured JSON responses** for easy integration

**Practical examples:**

| Integration | What It Enables |
|-------------|-----------------|
| Intranet portal | Embed a "search all documents" box on the company intranet |
| Compliance dashboard | Automatically flag when new documents match regulatory keywords |
| HR onboarding system | Pull relevant policy documents based on new hire's department |
| Board packet preparation | Query for all documents tagged or containing specific agenda topics |

**Who can use it:** IT staff or developers building internal integrations.

---

### Level 4: AI-Assisted Search (Built In, Optional)

**What it is:** A toggle in the search bar activates a side panel that uses Claude to synthesize a plain-English answer from your search results. Think of it as having an analyst read through the matching documents and write you a summary.

**How it works:**

1. You search normally using the search bar
2. With the AI toggle enabled, a side drawer streams a synthesized answer
3. Each answer cites its source documents — click "Read full doc" for a deeper single-document analysis
4. The AI reads the actual converted content, not just titles or snippets

**Key features:**
- **Opt-in per search** — Toggle on/off at any time; state persists across sessions
- **Source citations** — Every claim links back to the specific document it came from
- **Document expansion** — Click any cited source for a deeper AI-driven analysis of that single document
- **Streaming responses** — Answers appear progressively, no waiting for the full response
- **Completely optional** — Only available when an Anthropic API key is configured; search works fully without it

**Who can use it:** Any authorized user. Requires the administrator to configure an Anthropic API key in settings.

---

### Level 5: AI-Powered Natural Language Search (via Claude Integration)

**What it is:** MarkFlow connects to Claude (Anthropic's AI assistant) through a protocol called MCP (Model Context Protocol). This allows users to ask questions about their documents in plain English — no search syntax, no exact keywords needed.

**How it works:**

1. A user asks Claude a question in natural language
2. Claude understands the intent and formulates one or more searches
3. Claude calls MarkFlow's search tools to find relevant documents
4. Claude reads the document content and synthesizes an answer
5. The user gets a direct answer with source references

**This is fundamentally different from keyword search.** The AI understands synonyms, context, abbreviations, and can reason across multiple documents.

**Practical examples:**

| You Ask Claude | What Happens Behind the Scenes |
|----------------|-------------------------------|
| "Find anything related to our union contracts" | Claude searches for "collective bargaining agreement," "CBA," "union contract," "labor agreement," "bargaining unit" — multiple queries covering all the ways people refer to this concept |
| "What's our policy on remote work?" | Claude searches across HR policies, employee handbooks, and memos to find and summarize the remote work policy |
| "Which contracts expire in the next 90 days?" | Claude searches for contracts, reads expiration dates from the content, and filters to those expiring soon |
| "Compare the benefits packages in our two most recent union agreements" | Claude finds both agreements, reads the benefits sections, and presents a side-by-side comparison |
| "Summarize the key points from last Tuesday's board meeting" | Claude finds the meeting minutes or recording transcript and produces a concise summary |
| "Are there any documents that reference asbestos in Building 7?" | Claude searches for "asbestos" combined with "Building 7" and reports what it finds with full context |
| "What did we pay Acme Corp last year?" | Claude searches invoices, purchase orders, and payment records, then totals the amounts |
| "Find the most recent version of our emergency evacuation plan" | Claude searches for the plan, identifies multiple versions by date, and returns the newest one |

**Key advantages over keyword search:**

| Capability | Keyword Search | AI-Powered Search |
|-----------|---------------|-------------------|
| Understands synonyms | No — you must guess the right word | Yes — knows "CBA" = "collective bargaining agreement" |
| Multi-step reasoning | No — one search at a time | Yes — can search, read, then search again based on what it found |
| Summarization | No — returns raw documents | Yes — can summarize findings in plain language |
| Cross-document analysis | No — each result is independent | Yes — can compare, contrast, and synthesize across documents |
| Conversational follow-up | No — each search starts fresh | Yes — "What about the previous version?" works naturally |
| Handles ambiguity | No — returns literal matches | Yes — can ask clarifying questions or infer intent |

**Who can use it:** Any user with access to Claude (via Claude.ai, Claude Desktop, or an internal deployment). No technical skills required — if you can type a question, you can use it.

---

## What MarkFlow Does NOT Do

Transparency about limitations is important for setting expectations:

| Limitation | Explanation |
|-----------|-------------|
| **Not real-time** | Documents must be scanned and converted before they are searchable. New files are picked up on the next scan cycle (configurable, typically minutes). The scanner automatically excludes non-document directories (media server metadata, OS indexing files, system binaries) via configurable exclusion paths and skip patterns in Settings. |
| **Not a document editor** | MarkFlow finds and displays documents. Editing happens in the original application (Word, Excel, etc.). |
| **No sentiment analysis** | Cannot search by tone or emotion (e.g., "find angry emails"). The AI layer helps but is limited to what the text says, not how it feels. |
| **Single-site deployment** | Searches documents on the connected file shares. Does not search the internet, email servers, or cloud services unless files are synced to the source share. |
| **AI answers depend on document quality** | If the original document is poorly written, scanned at low quality, or missing information, the AI cannot compensate. |

---

## Security & Privacy

| Concern | How MarkFlow Addresses It |
|---------|--------------------------|
| **Data stays on-premises** | MarkFlow runs entirely in Docker on your infrastructure. Documents never leave your network. |
| **Role-based access control** | Four roles (search user, operator, manager, admin) control who can search, convert, and administer. |
| **Password-protected files** | Recovered passwords are used only for conversion and are not stored or transmitted. |
| **AI integration is optional** | The Claude/MCP integration can be enabled or disabled. Without it, Levels 1 and 2 still function fully. |
| **Audit trail** | Every conversion, search, and administrative action is logged. |

---

## Deployment Summary

| Component | Details |
|-----------|---------|
| **Runs on** | Docker (any Linux server or VM) |
| **Storage** | Reads from existing network shares (SMB/CIFS or NFS) — no file migration required |
| **File types** | 130+ formats including Office, PDF, email, images, audio, video, archives, Adobe creative files |
| **Search engine** | Meilisearch (full-text keyword) + Qdrant (semantic vector), merged via Reciprocal Rank Fusion |
| **Embedding model** | all-MiniLM-L6-v2 (runs locally, no external API calls for search) |
| **AI integration** | In-app AI-assisted search (optional) + Claude via MCP (optional, enhances search with natural language) |
| **Users access via** | Web browser (no client software to install) |

---

## Recommendation

MarkFlow provides five progressively powerful ways to find information locked inside documents:

1. **Keyword search** for daily lookups — fast, familiar, works like any search box
2. **Semantic vector search** for meaning-based discovery — finds relevant documents even when wording differs
3. **API integration** for connecting document search to existing systems and workflows
4. **AI-assisted search** for in-app synthesized answers grounded in your documents
5. **AI-powered natural language search** for complex questions, cross-document analysis, and conversational exploration of your document repository

Background indexing (scan, conversion, and re-indexing) uses request-aware throttling to ensure search remains responsive at all times — when users are actively searching, background work automatically yields resources to keep queries fast.

The system is already built, tested, and running. Deployment requires connecting it to existing file shares — no data migration, no file reorganization, and no disruption to current workflows. Users access it through a web browser with no software installation.

The AI integration (Level 3) is the differentiator. It transforms a document repository from a passive filing cabinet into an active knowledge base that can answer questions, find patterns, and surface information that would otherwise require hours of manual searching.
