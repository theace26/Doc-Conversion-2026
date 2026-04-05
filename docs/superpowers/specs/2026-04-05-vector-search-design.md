# Vector Search Augmentation — Design Spec

**Branch:** `vector`
**Baseline:** v0.21.0 (AI-Assisted Search + amendment-1)
**Date:** 2026-04-05

---

## 1. Goal

Add semantic vector search to MarkFlow, augmenting the existing Meilisearch keyword
search. Users should find documents by meaning, not just keywords. "Current wage sheets"
should find compensation schedules even if those exact words don't appear. Cross-document
discovery ("everything related to Q1 budget") should surface topically related documents
across formats. Results should be better ranked by combining keyword relevance with
semantic similarity.

The LLM API layer (AI Assist) stays where it is — handling synthesis and reasoning.
Vectors handle retrieval.

---

## 2. Architecture Overview

```
Document converted → Markdown
    ├─→ Meilisearch (keyword index, existing, unchanged)
    └─→ Chunker → Embedder → Qdrant (vector index, new)

User searches
    ├─→ Query preprocessor (temporal intent, normalization)
    ├─→ Meilisearch keyword search → ranked hits
    └─→ Embed query → Qdrant ANN search → ranked hits
    ↓
    RRF merge → unified ranked results
    ↓
    Search page + AI Assist drawer (existing, unchanged)
```

**Key principle:** Vector search is an enhancement, not a dependency. If Qdrant is
down, embeddings don't exist yet, or the model isn't loaded, search falls back to
keyword-only. No errors, no broken UI.

---

## 3. New Infrastructure

### 3.1 Qdrant Container

Added to `docker-compose.yml` alongside Meilisearch.

- Image: `qdrant/qdrant:latest`
- Port: 6333 (internal only, not exposed to host)
- Volume: `qdrant-data:/qdrant/storage`
- Health check: `GET /healthz`
- Memory: ~100-200MB depending on corpus size
- Startup: included in pipeline health gate (`pipeline_startup.py`)

### 3.2 Single Collection Design

One Qdrant collection named `markflow_chunks` with payload fields:

| Payload field | Type | Purpose |
|--------------|------|---------|
| `doc_id` | string | SHA256-based ID matching Meilisearch doc ID |
| `source_index` | string | `documents`, `adobe-files`, or `transcripts` |
| `source_format` | string | File format for filtering |
| `chunk_index` | integer | Position within document |
| `heading_path` | string | e.g. "Wage Policy > Section 3.2 > Electrician Rates" |
| `title` | string | Document title |
| `source_path` | string | Original file path |
| `is_flagged` | bool | Content moderation flag |
| `chunk_text` | string | Raw chunk text (for AI Assist context) |

**Why one collection:** Simpler than three. The `source_index` payload field enables
per-index filtering when needed. RRF doesn't care about source — it just needs
ranked results. Mirrors how `/api/search/all` already fans out to multiple indexes
and merges.

Collection config:
- Distance: Cosine
- HNSW index: default params (ef_construct=100, m=16)
- Vector size: 384 (for `all-MiniLM-L6-v2`) — changes with model swap
- Quantization: not needed under 500k vectors

---

## 4. New Modules

### 4.1 Chunker — `core/vector/chunker.py`

Splits markdown into embeddable chunks with contextual headers.

**Algorithm:**

1. Parse markdown, extract heading hierarchy (H1/H2/H3)
2. Split on headings — each section becomes a candidate chunk
3. Large sections (>500 tokens): subdivide into ~400 token windows with ~50 token overlap
4. Small adjacent sections (<100 tokens): merge together to reach minimum viable size
5. **Contextual header prepend:** Each chunk gets a prefix:
   ```
   [Document: Peninsula Small Works Contract]
   [Section: Wage Schedule > Electrician Rates]

   The standard rate is $45/hr effective January 2025...
   ```
   This dramatically improves embedding quality for chunks that lack standalone context.
6. Each chunk carries metadata: `doc_id`, `heading_path`, `chunk_index`, `title`, `source_path`

**Token counting:** Use a fast character-based estimate (chars / 4) for splitting
decisions. Exact token counts aren't needed — the overlap handles boundary cases.

**Input:** Markdown file path + doc metadata
**Output:** List of `Chunk` dataclasses with `text`, `metadata` dict

### 4.2 Embedder — `core/vector/embedder.py`

Pluggable embedding interface following the LLM provider pattern.

**Local provider (default):**
- Model: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, ~80MB)
- Loaded once at first use (lazy init, same pattern as Whisper model loading)
- Cached as module-level state
- Batch inference: 32-128 chunks per call for throughput
- CPU inference: ~5-15ms per chunk

**API provider (optional, future):**
- Interface: `async embed(texts: list[str]) -> list[list[float]]`
- Providers: Voyage AI, OpenAI `text-embedding-3-small`, others
- Configured via Settings page, stored in `user_preferences`
- Rate limiting and retry logic

**Model version tracking:**
The embedding model name and version are stored as collection metadata in Qdrant.
When the configured model changes, the system detects the mismatch and flags that
a re-index is needed. This is documented here so that future model upgrades trigger
targeted re-embedding rather than requiring manual intervention.

> **Future note:** When upgrading embedding models (e.g., `all-MiniLM-L6-v2` →
> `nomic-embed-text`), the system should: (1) detect model mismatch from collection
> metadata, (2) offer admin a "re-embed all" action in Settings, (3) re-embed
> incrementally in background without disrupting search. The pluggable provider
> interface and collection metadata are designed to support this path.

### 4.3 Index Manager — `core/vector/index_manager.py`

Mirrors `SearchIndexer` responsibilities for the vector side.

**Methods:**

- `index_document(markdown_path, doc_id, metadata)` — chunk, embed, upsert to Qdrant
- `delete_document(doc_id)` — remove all chunks by `doc_id` payload filter
- `rebuild_index()` — drop collection, recreate, re-index all converted documents
- `ensure_collection()` — create collection if missing (called at startup)
- `get_status()` — collection stats (vector count, indexed status)

**Chunk ID strategy:** Deterministic hash of `doc_id + chunk_index`. Same document
indexed twice produces the same chunk IDs → idempotent upserts.

**Error handling:** Best-effort, same as Meilisearch indexing. Failures logged via
structlog but never block the conversion pipeline.

### 4.4 Hybrid Search — `core/vector/hybrid_search.py`

Combines keyword and vector results via Reciprocal Rank Fusion.

**`hybrid_search(query, filters, limit)` flow:**

1. **Query preprocessor** (see Section 5)
2. **Parallel execution** via `asyncio.gather`:
   - Meilisearch keyword search → top 50 hits
   - Embed query → Qdrant ANN search → top 50 chunks
3. **Chunk-to-document mapping:** Multiple chunks from the same doc → keep the
   best-scoring chunk per doc_id
4. **RRF merge:**
   ```
   score(doc) = Σ 1/(k + rank_in_system)
   ```
   where k=60 (standard constant from Cormack et al.)
   A doc found by both systems gets scores from both. A doc found by only one
   system still appears — RRF naturally handles asymmetric results.
5. **Tiebreaker:** Equal RRF scores → prefer keyword match (users expect exact
   matches to rank high)
6. **Return** unified result list in existing search response format

**Over-fetch strategy:** Fetch 50 from each system, merge, return top `limit` (default
10-20). Wider net catches docs that one system ranks low but the other ranks high.

### 4.5 Query Preprocessor — `core/vector/query_preprocessor.py`

Lightweight query processing before search execution.

**Temporal intent detection:**
Detect words/phrases: "current", "latest", "recent", "most recent", "newest",
"up to date", "this year", "2026", "last month", etc.
When detected: add `sort: converted_at:desc` bias to keyword search, and boost
recent documents in RRF scoring (small multiplier, not an override).

**Query normalization:**
- Strip leading question words ("what are the", "where is the", "find me")
- Collapse whitespace
- Pass normalized query to both keyword and vector search

**What this does NOT do:**
- No full HyDE (hypothetical document generation) — too slow for every query
- No LLM-based query expansion on the critical path — latency budget is <200ms
- No spell correction — Meilisearch already handles typo tolerance

---

## 5. Integration with Existing Code

### 5.1 Indexing Pipeline

Vector indexing runs as **fire-and-forget parallel** to Meilisearch, same pattern as
Adobe indexing.

In `core/bulk_worker.py`, after the existing Meilisearch `index_document()` call:

```python
# Existing
await indexer.index_document(actual_output, self.job_id)

# New — fire-and-forget, failure doesn't block conversion
try:
    from core.vector.index_manager import get_vector_indexer
    vector_indexer = get_vector_indexer()
    if vector_indexer:
        await vector_indexer.index_document(actual_output, doc_id, metadata)
except Exception as exc:
    log.warning("vector_index.skip", error=str(exc))
```

The `get_vector_indexer()` returns `None` if Qdrant is unavailable or not configured.

### 5.2 Search API

In `api/routes/search.py`, the `/api/search/all` endpoint currently fans out to
three Meilisearch indexes. Modified to optionally include vector search:

```python
# Existing: keyword results from 3 indexes
keyword_results = await _search_all_indexes(query, filters, ...)

# New: if vector search available, run hybrid
vector_indexer = get_vector_indexer()
if vector_indexer:
    results = await hybrid_search(query, keyword_results, filters, limit)
else:
    results = keyword_results  # graceful fallback
```

**Response format unchanged.** The frontend receives the same shape — hits with
`id`, `title`, `source_index`, `highlight`, etc. The only difference is ranking.

### 5.3 Search Rebuild

The existing `POST /api/search/index/rebuild` endpoint triggers Meilisearch rebuild.
Extended to also trigger vector re-index (in parallel, non-blocking).

### 5.4 Document Deletion

When documents are deleted (lifecycle manager, trash), vector chunks are deleted
alongside Meilisearch entries. Qdrant delete by payload filter: `doc_id == X`.

---

## 6. Configuration

### 6.1 Environment Variables

```dotenv
# Vector search (optional — feature disabled when Qdrant is unreachable)
QDRANT_HOST=http://qdrant:6333
QDRANT_COLLECTION=markflow_chunks
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_BATCH_SIZE=64
```

### 6.2 User Preferences (Settings UI)

| Preference | Default | Description |
|-----------|---------|-------------|
| `vector_search_enabled` | `true` | Master switch (if Qdrant is available) |
| `embedding_provider` | `local` | `local` or future API provider name |
| `hybrid_search_weight` | `balanced` | RRF bias: `keyword_heavy`, `balanced`, `semantic_heavy` |

### 6.3 Docker Compose Addition

```yaml
qdrant:
  image: qdrant/qdrant:latest
  volumes:
    - qdrant-data:/qdrant/storage
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
    interval: 15s
    timeout: 5s
    retries: 3
  restart: unless-stopped
  # Not exposed to host — internal only
```

---

## 7. New Dependencies

Added to `requirements.txt`:

| Package | Purpose | Size |
|---------|---------|------|
| `sentence-transformers` | Local embedding model inference | ~50MB (pulls torch if not present) |
| `qdrant-client` | Qdrant REST client | ~5MB |

**Note:** `torch` is already installed for Whisper transcription (`Dockerfile.base`
installs CPU-only torch). `sentence-transformers` will use the existing torch install.

---

## 8. Anti-Pattern Checklist

Verified the design does NOT:

| Anti-pattern | Status |
|-------------|--------|
| Replace keyword search with vector | **Clear** — keyword is unchanged, vector augments |
| Embed entire documents as single vectors | **Clear** — structural chunking with 400-token windows |
| Use cosine similarity thresholds as cutoffs | **Clear** — using rank-based RRF, not score thresholds |
| Re-embed documents on every query | **Clear** — only the query is embedded at search time |
| Skip evaluation | **Deferred** — evaluation framework planned as follow-up step after implementation |

---

## 9. Graceful Degradation

| Scenario | Behaviour |
|----------|-----------|
| Qdrant not running | Keyword-only search, no errors |
| Qdrant running but empty (no embeddings yet) | Keyword-only, admin sees "0 vectors" in Settings |
| Embedding model fails to load | Vector indexing skipped, keyword search works |
| Single document fails to embed | That doc is keyword-only, others have vectors |
| API embedding provider down | Falls back to local model (if configured) or keyword-only |

---

## 10. File Structure

```
core/vector/
    __init__.py
    chunker.py           — Markdown → contextual chunks
    embedder.py          — Pluggable embedding (local + API providers)
    index_manager.py     — Qdrant collection lifecycle + document indexing
    hybrid_search.py     — RRF merge of keyword + vector results
    query_preprocessor.py — Temporal intent detection, query normalization
```

---

## 11. What Stays Unchanged

- Meilisearch keyword search — untouched, still the primary index
- AI Assist synthesis — receives merged results, its interface doesn't change
- All existing search UI — facets, filters, autocomplete, pagination, viewer
- Indexing pipeline — vector indexing added in parallel, never blocks
- Document conversion — completely unaffected
- Database schema — no changes to existing tables

---

## 12. Future Considerations (documented, not in scope)

- **Embedding model upgrades:** Collection metadata tracks model version. Model swap
  triggers admin-initiated re-embedding. Pluggable provider interface supports this.
- **API embedding providers:** Same interface as local, configured via Settings.
  Voyage AI, OpenAI, etc.
- **Query expansion via LLM:** For short/ambiguous queries when AI Assist is active.
  Not on the critical search path — latency budget is <200ms.
- **Evaluation framework:** Golden test set of 20-50 queries, recall@10 measurement,
  before/after comparison. Build after implementation, before merging to main.
