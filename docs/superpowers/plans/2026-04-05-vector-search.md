# Vector Search Augmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hybrid keyword + semantic vector search to MarkFlow, augmenting existing Meilisearch with Qdrant vector search merged via Reciprocal Rank Fusion.

**Architecture:** Documents are chunked with contextual headers, embedded via local `sentence-transformers` model, and stored in Qdrant alongside existing Meilisearch keyword index. At query time, both systems run in parallel and results merge via RRF. Graceful fallback to keyword-only when Qdrant is unavailable.

**Tech Stack:** Qdrant (Docker), sentence-transformers (all-MiniLM-L6-v2, 384d), qdrant-client, asyncio

**Branch:** `vector` (forked from `main` at v0.21.0)

---

## File Structure

### New files

```
core/vector/__init__.py            — Package init, re-exports
core/vector/chunker.py             — Markdown → contextual chunks
core/vector/embedder.py            — Pluggable embedding (local model)
core/vector/index_manager.py       — Qdrant collection lifecycle + doc indexing
core/vector/hybrid_search.py       — RRF merge of keyword + vector results
core/vector/query_preprocessor.py  — Temporal intent detection, query normalization
tests/test_vector/__init__.py      — Test package
tests/test_vector/test_chunker.py
tests/test_vector/test_embedder.py
tests/test_vector/test_hybrid_search.py
tests/test_vector/test_query_preprocessor.py
tests/test_vector/test_index_manager.py
```

### Modified files

```
requirements.txt                   — Add sentence-transformers, qdrant-client
docker-compose.yml                 — Add Qdrant service + volume
core/bulk_worker.py:773            — Add vector indexing call after Meilisearch
api/routes/search.py:218-270       — Use hybrid search in search_all()
core/pipeline_startup.py:24-27     — Add qdrant to PREFERRED_SERVICES
core/search_indexer.py             — Add rebuild hook for vector index
.env.example                       — Add QDRANT_HOST, EMBEDDING_MODEL vars
core/version.py                    — Bump to v0.22.0
CLAUDE.md                          — Version + feature log
docs/version-history.md            — Changelog entry
```

---

### Task 1: Dependencies + Docker Infrastructure

**Files:**
- Modify: `requirements.txt`
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add Python dependencies to requirements.txt**

Add at the end of `requirements.txt`:

```
# Vector search (v0.22.0)
sentence-transformers>=3.0.0
qdrant-client>=1.9.0
```

- [ ] **Step 2: Add Qdrant service to docker-compose.yml**

Add after the `meilisearch` service block (after line ~102):

```yaml
  # ── Qdrant vector search (v0.22.0) ────────────────────────────────────────
  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrant-data:/qdrant/storage
    deploy:
      resources:
        limits:
          memory: ${QDRANT_MEMORY_LIMIT:-512m}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
```

Add `qdrant-data:` to the `volumes:` section at the bottom of the file.

Add to the `markflow` service `environment:` block:

```yaml
      - QDRANT_HOST=${QDRANT_HOST:-http://qdrant:6333}
      - QDRANT_COLLECTION=${QDRANT_COLLECTION:-markflow_chunks}
      - EMBEDDING_MODEL=${EMBEDDING_MODEL:-all-MiniLM-L6-v2}
      - EMBEDDING_BATCH_SIZE=${EMBEDDING_BATCH_SIZE:-64}
```

Add `qdrant` to the `markflow` service `depends_on:` block:

```yaml
    depends_on:
      meilisearch:
        condition: service_healthy
      qdrant:
        condition: service_healthy
```

- [ ] **Step 3: Add env vars to .env.example**

```dotenv
# Vector search (optional — feature disabled when Qdrant is unreachable)
QDRANT_HOST=http://localhost:6333
QDRANT_COLLECTION=markflow_chunks
QDRANT_MEMORY_LIMIT=512m
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_BATCH_SIZE=64
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt docker-compose.yml .env.example
git commit -m "infra: add Qdrant service + vector search dependencies (v0.22.0)"
```

---

### Task 2: Chunker

**Files:**
- Create: `core/vector/__init__.py`
- Create: `core/vector/chunker.py`
- Create: `tests/test_vector/__init__.py`
- Create: `tests/test_vector/test_chunker.py`

- [ ] **Step 1: Create package init files**

`core/vector/__init__.py`:
```python
"""Vector search subsystem — chunking, embedding, indexing, hybrid search."""
```

`tests/test_vector/__init__.py`:
```python
```

- [ ] **Step 2: Write chunker tests**

`tests/test_vector/test_chunker.py`:
```python
"""Tests for the markdown chunker."""
import pytest
from core.vector.chunker import chunk_markdown, Chunk


SAMPLE_MD = """\
---
title: Test Document
markflow:
  source_file: test.docx
---

# Introduction

This is the introduction section with enough text to be meaningful.
It discusses the purpose and scope of the document.

## Section A

Section A has detailed content about the first topic.
It spans multiple lines and contains important information
that should be searchable by semantic meaning.

## Section B

### Subsection B.1

Short subsection.

### Subsection B.2

Another short subsection that should be merged with B.1.

# Appendix

Very long section. """ + ("This is filler text for the appendix section. " * 80)


def test_chunks_have_contextual_headers():
    chunks = chunk_markdown(SAMPLE_MD, doc_title="Test Document")
    assert len(chunks) > 0
    # Every chunk should start with [Document: ...] header
    for c in chunks:
        assert c.text.startswith("[Document: Test Document]")


def test_chunks_carry_metadata():
    chunks = chunk_markdown(SAMPLE_MD, doc_title="Test Document",
                            doc_id="abc123", source_path="/mnt/source/test.docx")
    for c in chunks:
        assert c.doc_id == "abc123"
        assert c.source_path == "/mnt/source/test.docx"
        assert isinstance(c.chunk_index, int)
        assert isinstance(c.heading_path, str)


def test_structural_splitting_on_headings():
    chunks = chunk_markdown(SAMPLE_MD, doc_title="Test Document")
    heading_paths = [c.heading_path for c in chunks]
    # Should have chunks from Introduction, Section A, Section B, Appendix
    assert any("Introduction" in h for h in heading_paths)
    assert any("Section A" in h for h in heading_paths)


def test_large_sections_get_subdivided():
    chunks = chunk_markdown(SAMPLE_MD, doc_title="Test Document")
    # The Appendix section has ~80 * 8 words = ~640 words = ~2500 chars
    # Should be subdivided into multiple chunks
    appendix_chunks = [c for c in chunks if "Appendix" in c.heading_path]
    assert len(appendix_chunks) > 1


def test_small_sections_get_merged():
    chunks = chunk_markdown(SAMPLE_MD, doc_title="Test Document")
    # Subsection B.1 and B.2 are both very short — should be merged
    b_chunks = [c for c in chunks if "Section B" in c.heading_path]
    # Both subsections should be in a single chunk (merged)
    assert len(b_chunks) <= 2


def test_empty_content_returns_single_chunk():
    chunks = chunk_markdown("Just a single line.", doc_title="Tiny")
    assert len(chunks) == 1
    assert "Tiny" in chunks[0].text


def test_chunk_index_is_sequential():
    chunks = chunk_markdown(SAMPLE_MD, doc_title="Test Document")
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_frontmatter_stripped():
    chunks = chunk_markdown(SAMPLE_MD, doc_title="Test Document")
    for c in chunks:
        assert "markflow:" not in c.text
        assert "source_file:" not in c.text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_chunker.py -v 2>&1 | head -30`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.vector.chunker'`

- [ ] **Step 4: Implement the chunker**

`core/vector/chunker.py`:
```python
"""
Markdown chunker for vector search.
Splits markdown into embeddable chunks with contextual headers.

Algorithm:
1. Strip YAML frontmatter
2. Split on H1/H2/H3 headings into sections
3. Large sections (>MAX_CHUNK_CHARS): subdivide with overlap
4. Small adjacent sections (<MIN_CHUNK_CHARS): merge together
5. Prepend contextual header to each chunk
"""
import re
from dataclasses import dataclass, field

MAX_CHUNK_CHARS = 1600   # ~400 tokens
MIN_CHUNK_CHARS = 200    # ~50 tokens — merge smaller sections
OVERLAP_CHARS = 200      # ~50 tokens overlap between subdivided chunks

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


@dataclass
class Chunk:
    text: str
    doc_id: str = ""
    doc_title: str = ""
    heading_path: str = ""
    chunk_index: int = 0
    source_path: str = ""


def chunk_markdown(
    markdown: str,
    doc_title: str = "Untitled",
    doc_id: str = "",
    source_path: str = "",
) -> list[Chunk]:
    """Split markdown into contextual chunks for embedding."""
    # Strip frontmatter
    body = _FRONTMATTER_RE.sub("", markdown).strip()
    if not body:
        body = markdown.strip()

    # Split into sections by headings
    sections = _split_by_headings(body)

    # Merge small adjacent sections
    sections = _merge_small_sections(sections)

    # Subdivide large sections
    raw_chunks = []
    for heading_path, text in sections:
        if len(text) > MAX_CHUNK_CHARS:
            for sub_text in _subdivide(text):
                raw_chunks.append((heading_path, sub_text))
        else:
            raw_chunks.append((heading_path, text))

    # If nothing was produced, make one chunk from the whole body
    if not raw_chunks:
        raw_chunks = [("", body[:MAX_CHUNK_CHARS])]

    # Build Chunk objects with contextual headers
    chunks = []
    for i, (heading_path, text) in enumerate(raw_chunks):
        header_lines = [f"[Document: {doc_title}]"]
        if heading_path:
            header_lines.append(f"[Section: {heading_path}]")
        header = "\n".join(header_lines) + "\n\n"

        chunks.append(Chunk(
            text=header + text.strip(),
            doc_id=doc_id,
            doc_title=doc_title,
            heading_path=heading_path or doc_title,
            chunk_index=i,
            source_path=source_path,
        ))

    return chunks


def _split_by_headings(body: str) -> list[tuple[str, str]]:
    """Split body into (heading_path, section_text) pairs."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return [("", body)]

    sections = []
    heading_stack: list[tuple[int, str]] = []

    # Text before first heading
    pre_text = body[:matches[0].start()].strip()
    if pre_text:
        sections.append(("", pre_text))

    for i, match in enumerate(matches):
        level = len(match.group(1))  # 1, 2, or 3
        title = match.group(2).strip()

        # Update heading stack
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))

        # Build heading path
        heading_path = " > ".join(h[1] for h in heading_stack)

        # Extract section text (from after this heading to next heading or end)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_text = body[start:end].strip()

        if section_text:
            sections.append((heading_path, section_text))

    return sections


def _merge_small_sections(
    sections: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Merge adjacent sections that are too small to embed meaningfully."""
    if len(sections) <= 1:
        return sections

    merged = [sections[0]]
    for heading_path, text in sections[1:]:
        prev_path, prev_text = merged[-1]
        if len(prev_text) < MIN_CHUNK_CHARS and len(text) < MIN_CHUNK_CHARS:
            # Merge into previous
            combined_path = prev_path if prev_path else heading_path
            merged[-1] = (combined_path, prev_text + "\n\n" + text)
        else:
            merged.append((heading_path, text))

    return merged


def _subdivide(text: str) -> list[str]:
    """Split a large text block into overlapping windows."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + MAX_CHUNK_CHARS
        # Try to break at a sentence or paragraph boundary
        if end < len(text):
            # Look for paragraph break near the boundary
            break_point = text.rfind("\n\n", start + MAX_CHUNK_CHARS // 2, end)
            if break_point == -1:
                # Fall back to sentence break
                break_point = text.rfind(". ", start + MAX_CHUNK_CHARS // 2, end)
                if break_point != -1:
                    break_point += 2  # include the period and space
            if break_point > start:
                end = break_point

        chunks.append(text[start:end])
        start = end - OVERLAP_CHARS if end < len(text) else end

    return chunks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_chunker.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add core/vector/__init__.py core/vector/chunker.py tests/test_vector/
git commit -m "feat(vector): markdown chunker with contextual headers"
```

---

### Task 3: Embedder

**Files:**
- Create: `core/vector/embedder.py`
- Create: `tests/test_vector/test_embedder.py`

- [ ] **Step 1: Write embedder tests**

`tests/test_vector/test_embedder.py`:
```python
"""Tests for the embedding provider."""
import pytest
from unittest.mock import patch, MagicMock
from core.vector.embedder import LocalEmbedder, get_embedder


def test_local_embedder_returns_vectors():
    embedder = LocalEmbedder(model_name="all-MiniLM-L6-v2")
    vectors = embedder.embed(["Hello world", "Test document"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 384  # all-MiniLM-L6-v2 dimension
    assert all(isinstance(v, float) for v in vectors[0])


def test_local_embedder_single_text():
    embedder = LocalEmbedder(model_name="all-MiniLM-L6-v2")
    vectors = embedder.embed(["Just one sentence."])
    assert len(vectors) == 1
    assert len(vectors[0]) == 384


def test_local_embedder_empty_list():
    embedder = LocalEmbedder(model_name="all-MiniLM-L6-v2")
    vectors = embedder.embed([])
    assert vectors == []


def test_local_embedder_dimension_property():
    embedder = LocalEmbedder(model_name="all-MiniLM-L6-v2")
    assert embedder.dimension == 384


def test_local_embedder_model_name_property():
    embedder = LocalEmbedder(model_name="all-MiniLM-L6-v2")
    assert embedder.model_name == "all-MiniLM-L6-v2"


def test_get_embedder_returns_local_by_default():
    embedder = get_embedder()
    assert isinstance(embedder, LocalEmbedder)


def test_similar_texts_have_higher_similarity():
    embedder = LocalEmbedder(model_name="all-MiniLM-L6-v2")
    vectors = embedder.embed([
        "Employee wage schedule for electricians",
        "Compensation rates for electrical workers",
        "How to bake chocolate chip cookies",
    ])
    # Cosine similarity: similar texts should be closer
    import math
    def cosine_sim(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    sim_related = cosine_sim(vectors[0], vectors[1])
    sim_unrelated = cosine_sim(vectors[0], vectors[2])
    assert sim_related > sim_unrelated
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_embedder.py -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the embedder**

`core/vector/embedder.py`:
```python
"""
Pluggable embedding provider for vector search.

Default: local sentence-transformers model (all-MiniLM-L6-v2).
Model loaded lazily on first use, cached for the process lifetime.
"""
import os
import structlog

log = structlog.get_logger()

_cached_embedder = None


class LocalEmbedder:
    """Local embedding using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dimension: int | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load_model()
        return self._dimension

    def _load_model(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        log.info("embedder.loading_model", model=self._model_name)
        self._model = SentenceTransformer(self._model_name)
        self._dimension = self._model.get_sentence_embedding_dimension()
        log.info("embedder.model_ready", model=self._model_name, dimension=self._dimension)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""
        if not texts:
            return []
        self._load_model()
        embeddings = self._model.encode(
            texts,
            batch_size=int(os.environ.get("EMBEDDING_BATCH_SIZE", "64")),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [vec.tolist() for vec in embeddings]


def get_embedder() -> LocalEmbedder:
    """Return the cached embedder instance."""
    global _cached_embedder
    if _cached_embedder is None:
        model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        _cached_embedder = LocalEmbedder(model_name=model_name)
    return _cached_embedder
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_embedder.py -v`
Expected: All 7 tests PASS (first run may be slow — model download ~80MB)

Note: If `sentence-transformers` is not installed in the host environment, these tests will only pass inside Docker. Run `pip install sentence-transformers qdrant-client` on the host if you want to run tests outside Docker.

- [ ] **Step 5: Commit**

```bash
git add core/vector/embedder.py tests/test_vector/test_embedder.py
git commit -m "feat(vector): local embedding provider with sentence-transformers"
```

---

### Task 4: Query Preprocessor

**Files:**
- Create: `core/vector/query_preprocessor.py`
- Create: `tests/test_vector/test_query_preprocessor.py`

- [ ] **Step 1: Write preprocessor tests**

`tests/test_vector/test_query_preprocessor.py`:
```python
"""Tests for query preprocessing."""
import pytest
from core.vector.query_preprocessor import preprocess_query, QueryIntent


def test_temporal_intent_detected():
    result = preprocess_query("most current wage sheets")
    assert result.has_temporal_intent is True


def test_temporal_words():
    for query in ["latest report", "recent invoices", "newest budget",
                  "most recent memo", "up to date policies", "this year plan"]:
        result = preprocess_query(query)
        assert result.has_temporal_intent is True, f"Failed for: {query}"


def test_non_temporal_query():
    result = preprocess_query("electrical wiring standards")
    assert result.has_temporal_intent is False


def test_question_words_stripped():
    result = preprocess_query("what are the most current wage sheets")
    assert result.normalized_query == "most current wage sheets"


def test_various_question_prefixes():
    assert preprocess_query("where is the budget report").normalized_query == "budget report"
    assert preprocess_query("find me the policy docs").normalized_query == "policy docs"
    assert preprocess_query("show me electrical specs").normalized_query == "electrical specs"


def test_plain_query_unchanged():
    result = preprocess_query("peninsula contract rates")
    assert result.normalized_query == "peninsula contract rates"


def test_whitespace_collapsed():
    result = preprocess_query("  wage   sheets   2025  ")
    assert result.normalized_query == "wage sheets 2025"


def test_empty_query():
    result = preprocess_query("")
    assert result.normalized_query == ""
    assert result.has_temporal_intent is False


def test_original_query_preserved():
    result = preprocess_query("what are the latest wage sheets")
    assert result.original_query == "what are the latest wage sheets"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_query_preprocessor.py -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the preprocessor**

`core/vector/query_preprocessor.py`:
```python
"""
Lightweight query preprocessing for hybrid search.
Detects temporal intent and normalizes queries.
"""
import re
from dataclasses import dataclass

_TEMPORAL_PATTERNS = re.compile(
    r"\b("
    r"current|latest|recent|newest|most recent|up to date|"
    r"up-to-date|this year|this month|last month|last year|"
    r"2024|2025|2026|2027"
    r")\b",
    re.IGNORECASE,
)

_QUESTION_PREFIXES = re.compile(
    r"^("
    r"what (?:are|is|were|was) (?:the )?|"
    r"where (?:are|is|were|was) (?:the )?|"
    r"how (?:do|does|did|can|to) (?:i |we |you )?|"
    r"find (?:me )?(?:the )?|"
    r"show (?:me )?(?:the )?|"
    r"get (?:me )?(?:the )?|"
    r"can (?:you )?(?:find |show |get )?"
    r")",
    re.IGNORECASE,
)


@dataclass
class QueryIntent:
    original_query: str
    normalized_query: str
    has_temporal_intent: bool


def preprocess_query(query: str) -> QueryIntent:
    """Preprocess a search query for hybrid search."""
    original = query
    has_temporal = bool(_TEMPORAL_PATTERNS.search(query))

    # Strip question prefixes
    normalized = _QUESTION_PREFIXES.sub("", query)

    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return QueryIntent(
        original_query=original,
        normalized_query=normalized,
        has_temporal_intent=has_temporal,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_query_preprocessor.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/vector/query_preprocessor.py tests/test_vector/test_query_preprocessor.py
git commit -m "feat(vector): query preprocessor with temporal intent detection"
```

---

### Task 5: Qdrant Index Manager

**Files:**
- Create: `core/vector/index_manager.py`
- Create: `tests/test_vector/test_index_manager.py`

- [ ] **Step 1: Write index manager tests**

`tests/test_vector/test_index_manager.py`:
```python
"""Tests for the Qdrant index manager."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.vector.index_manager import VectorIndexManager


@pytest.fixture
def mock_qdrant():
    """Mock qdrant_client.AsyncQdrantClient."""
    client = AsyncMock()
    client.collection_exists = AsyncMock(return_value=True)
    client.get_collection = AsyncMock(return_value=MagicMock(
        points_count=100,
        vectors_count=100,
        config=MagicMock(params=MagicMock(vectors=MagicMock(size=384))),
    ))
    client.upsert = AsyncMock()
    client.delete = AsyncMock()
    client.search = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.dimension = 384
    embedder.model_name = "all-MiniLM-L6-v2"
    embedder.embed = MagicMock(return_value=[[0.1] * 384, [0.2] * 384])
    return embedder


@pytest.fixture
def manager(mock_qdrant, mock_embedder):
    return VectorIndexManager(
        client=mock_qdrant,
        embedder=mock_embedder,
        collection_name="test_chunks",
    )


@pytest.mark.asyncio
async def test_index_document_upserts_chunks(manager, mock_qdrant, tmp_path):
    md_file = tmp_path / "test.md"
    md_file.write_text("# Title\n\nSome content about wages and rates.")

    await manager.index_document(
        md_path=md_file,
        doc_id="doc123",
        title="Test Doc",
        source_path="/mnt/source/test.docx",
        source_format="docx",
        source_index="documents",
    )

    mock_qdrant.upsert.assert_called_once()
    call_args = mock_qdrant.upsert.call_args
    assert call_args.kwargs["collection_name"] == "test_chunks"
    points = call_args.kwargs["points"]
    assert len(points) > 0


@pytest.mark.asyncio
async def test_delete_document_filters_by_doc_id(manager, mock_qdrant):
    await manager.delete_document("doc123")
    mock_qdrant.delete.assert_called_once()
    call_args = mock_qdrant.delete.call_args
    assert call_args.kwargs["collection_name"] == "test_chunks"


@pytest.mark.asyncio
async def test_search_returns_scored_results(manager, mock_qdrant, mock_embedder):
    mock_result = MagicMock()
    mock_result.id = "chunk_abc"
    mock_result.score = 0.85
    mock_result.payload = {
        "doc_id": "doc123",
        "title": "Test Doc",
        "source_index": "documents",
        "heading_path": "Introduction",
        "chunk_text": "Some content",
        "source_path": "/mnt/source/test.docx",
        "source_format": "docx",
    }
    mock_qdrant.search = AsyncMock(return_value=[mock_result])

    results = await manager.search("wages", limit=10)
    assert len(results) == 1
    assert results[0]["doc_id"] == "doc123"
    assert results[0]["score"] == 0.85


@pytest.mark.asyncio
async def test_get_status_returns_counts(manager, mock_qdrant):
    status = await manager.get_status()
    assert status["vectors"] == 100
    assert status["collection"] == "test_chunks"


@pytest.mark.asyncio
async def test_get_status_when_collection_missing(manager, mock_qdrant):
    mock_qdrant.collection_exists = AsyncMock(return_value=False)
    status = await manager.get_status()
    assert status["vectors"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_index_manager.py -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the index manager**

`core/vector/index_manager.py`:
```python
"""
Qdrant vector index manager.
Handles collection lifecycle, document indexing, search, and deletion.
"""
import hashlib
import os
from pathlib import Path

import structlog
from qdrant_client import AsyncQdrantClient, models

from core.vector.chunker import chunk_markdown
from core.vector.embedder import LocalEmbedder, get_embedder

log = structlog.get_logger()

_cached_manager = None


class VectorIndexManager:

    def __init__(
        self,
        client: AsyncQdrantClient,
        embedder: LocalEmbedder,
        collection_name: str = "markflow_chunks",
    ):
        self.client = client
        self.embedder = embedder
        self.collection_name = collection_name

    async def ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        exists = await self.client.collection_exists(self.collection_name)
        if exists:
            return

        await self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.embedder.dimension,
                distance=models.Distance.COSINE,
            ),
        )
        # Create payload indexes for filtering
        for field_name, field_type in [
            ("doc_id", models.PayloadSchemaType.KEYWORD),
            ("source_index", models.PayloadSchemaType.KEYWORD),
            ("source_format", models.PayloadSchemaType.KEYWORD),
            ("is_flagged", models.PayloadSchemaType.BOOL),
        ]:
            await self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=field_type,
            )

        log.info("vector.collection_created",
                 collection=self.collection_name,
                 dimension=self.embedder.dimension,
                 model=self.embedder.model_name)

    async def index_document(
        self,
        md_path: Path,
        doc_id: str,
        title: str = "",
        source_path: str = "",
        source_format: str = "",
        source_index: str = "documents",
        is_flagged: bool = False,
    ) -> int:
        """Chunk, embed, and upsert a document. Returns chunk count."""
        content = md_path.read_text(encoding="utf-8", errors="replace")
        doc_title = title or md_path.stem

        chunks = chunk_markdown(
            content,
            doc_title=doc_title,
            doc_id=doc_id,
            source_path=source_path,
        )

        if not chunks:
            return 0

        # Embed all chunk texts in one batch
        texts = [c.text for c in chunks]
        vectors = self.embedder.embed(texts)

        # Build Qdrant points
        points = []
        for chunk, vector in zip(chunks, vectors):
            point_id = _chunk_id(doc_id, chunk.chunk_index)
            points.append(models.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "doc_id": doc_id,
                    "title": doc_title,
                    "heading_path": chunk.heading_path,
                    "chunk_index": chunk.chunk_index,
                    "chunk_text": chunk.text,
                    "source_path": source_path,
                    "source_format": source_format,
                    "source_index": source_index,
                    "is_flagged": is_flagged,
                },
            ))

        await self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

        log.info("vector.document_indexed",
                 doc_id=doc_id, chunks=len(points), title=doc_title)
        return len(points)

    async def delete_document(self, doc_id: str) -> None:
        """Remove all chunks for a document."""
        await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doc_id",
                            match=models.MatchValue(value=doc_id),
                        )
                    ]
                )
            ),
        )
        log.info("vector.document_deleted", doc_id=doc_id)

    async def search(
        self,
        query: str,
        limit: int = 50,
        source_format: str = "",
        source_index: str = "",
    ) -> list[dict]:
        """Embed query and search Qdrant. Returns list of scored results."""
        vectors = self.embedder.embed([query])
        if not vectors:
            return []

        filters = []
        # Always exclude flagged content
        filters.append(
            models.FieldCondition(
                key="is_flagged", match=models.MatchValue(value=False)
            )
        )
        if source_format:
            filters.append(
                models.FieldCondition(
                    key="source_format", match=models.MatchValue(value=source_format)
                )
            )
        if source_index:
            filters.append(
                models.FieldCondition(
                    key="source_index", match=models.MatchValue(value=source_index)
                )
            )

        query_filter = models.Filter(must=filters) if filters else None

        results = await self.client.search(
            collection_name=self.collection_name,
            query_vector=vectors[0],
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )

        return [
            {
                "doc_id": r.payload.get("doc_id", ""),
                "title": r.payload.get("title", ""),
                "heading_path": r.payload.get("heading_path", ""),
                "chunk_text": r.payload.get("chunk_text", ""),
                "source_path": r.payload.get("source_path", ""),
                "source_format": r.payload.get("source_format", ""),
                "source_index": r.payload.get("source_index", ""),
                "score": r.score,
            }
            for r in results
        ]

    async def get_status(self) -> dict:
        """Return collection stats."""
        exists = await self.client.collection_exists(self.collection_name)
        if not exists:
            return {
                "collection": self.collection_name,
                "exists": False,
                "vectors": 0,
                "model": self.embedder.model_name,
            }

        info = await self.client.get_collection(self.collection_name)
        return {
            "collection": self.collection_name,
            "exists": True,
            "vectors": info.points_count or 0,
            "model": self.embedder.model_name,
        }


def _chunk_id(doc_id: str, chunk_index: int) -> str:
    """Deterministic chunk ID — same doc+index always produces same ID."""
    raw = f"{doc_id}:{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def get_vector_indexer() -> VectorIndexManager | None:
    """Return the cached vector index manager, or None if Qdrant is unavailable."""
    global _cached_manager
    if _cached_manager is not None:
        return _cached_manager

    host = os.environ.get("QDRANT_HOST", "").strip()
    if not host:
        return None

    collection = os.environ.get("QDRANT_COLLECTION", "markflow_chunks")

    try:
        client = AsyncQdrantClient(url=host, timeout=10)
        embedder = get_embedder()
        manager = VectorIndexManager(client, embedder, collection)
        await manager.ensure_collection()
        _cached_manager = manager
        log.info("vector.manager_ready", host=host, collection=collection)
        return manager
    except Exception as exc:
        log.warning("vector.manager_unavailable", host=host, error=str(exc))
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_index_manager.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/vector/index_manager.py tests/test_vector/test_index_manager.py
git commit -m "feat(vector): Qdrant index manager with document CRUD + search"
```

---

### Task 6: Hybrid Search (RRF)

**Files:**
- Create: `core/vector/hybrid_search.py`
- Create: `tests/test_vector/test_hybrid_search.py`

- [ ] **Step 1: Write hybrid search tests**

`tests/test_vector/test_hybrid_search.py`:
```python
"""Tests for hybrid search with Reciprocal Rank Fusion."""
import pytest
from core.vector.hybrid_search import rrf_merge, deduplicate_chunks

RRF_K = 60


def test_rrf_merge_combines_both_sources():
    keyword_hits = [
        {"id": "doc_a", "title": "Doc A"},
        {"id": "doc_b", "title": "Doc B"},
        {"id": "doc_c", "title": "Doc C"},
    ]
    vector_hits = [
        {"doc_id": "doc_b", "title": "Doc B", "score": 0.9},
        {"doc_id": "doc_d", "title": "Doc D", "score": 0.8},
        {"doc_id": "doc_a", "title": "Doc A", "score": 0.7},
    ]

    merged = rrf_merge(keyword_hits, vector_hits, k=RRF_K)
    ids = [h["id"] for h in merged]

    # doc_a and doc_b appear in both lists — should rank highest
    assert "doc_a" in ids
    assert "doc_b" in ids
    assert "doc_d" in ids
    assert "doc_c" in ids


def test_rrf_docs_in_both_rank_higher():
    keyword_hits = [
        {"id": "doc_a", "title": "Doc A"},
        {"id": "doc_b", "title": "Doc B"},
    ]
    vector_hits = [
        {"doc_id": "doc_a", "title": "Doc A", "score": 0.9},
        {"doc_id": "doc_c", "title": "Doc C", "score": 0.8},
    ]

    merged = rrf_merge(keyword_hits, vector_hits, k=RRF_K)
    # doc_a in both → should be first
    assert merged[0]["id"] == "doc_a"


def test_rrf_keyword_tiebreaker():
    # Two docs with same RRF score — keyword match should win
    keyword_hits = [
        {"id": "doc_a", "title": "Doc A"},
    ]
    vector_hits = [
        {"doc_id": "doc_b", "title": "Doc B", "score": 0.9},
    ]

    merged = rrf_merge(keyword_hits, vector_hits, k=RRF_K)
    # Both have score 1/(60+1) ≈ 0.0164 — doc_a from keyword should be first
    assert merged[0]["id"] == "doc_a"


def test_rrf_empty_vector_results():
    keyword_hits = [
        {"id": "doc_a", "title": "Doc A"},
        {"id": "doc_b", "title": "Doc B"},
    ]
    merged = rrf_merge(keyword_hits, [], k=RRF_K)
    assert len(merged) == 2
    assert merged[0]["id"] == "doc_a"


def test_rrf_empty_keyword_results():
    vector_hits = [
        {"doc_id": "doc_a", "title": "Doc A", "score": 0.9},
    ]
    merged = rrf_merge([], vector_hits, k=RRF_K)
    assert len(merged) == 1
    assert merged[0]["id"] == "doc_a"


def test_rrf_limit():
    keyword_hits = [{"id": f"doc_{i}", "title": f"Doc {i}"} for i in range(20)]
    vector_hits = [{"doc_id": f"doc_{i+10}", "title": f"Doc {i+10}", "score": 0.5}
                   for i in range(20)]
    merged = rrf_merge(keyword_hits, vector_hits, k=RRF_K, limit=5)
    assert len(merged) == 5


def test_deduplicate_chunks_keeps_best_score():
    chunks = [
        {"doc_id": "doc_a", "score": 0.8, "heading_path": "Intro"},
        {"doc_id": "doc_a", "score": 0.9, "heading_path": "Section 1"},
        {"doc_id": "doc_b", "score": 0.7, "heading_path": "Intro"},
    ]
    deduped = deduplicate_chunks(chunks)
    assert len(deduped) == 2
    doc_a = next(d for d in deduped if d["doc_id"] == "doc_a")
    assert doc_a["score"] == 0.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_hybrid_search.py -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement hybrid search**

`core/vector/hybrid_search.py`:
```python
"""
Hybrid search: merge Meilisearch keyword results with Qdrant vector results
via Reciprocal Rank Fusion (RRF).

RRF formula: score(doc) = sum(1 / (k + rank)) across all systems
k = 60 (standard constant, Cormack et al.)
"""
import asyncio
import structlog

log = structlog.get_logger()

RRF_K = 60


def deduplicate_chunks(vector_hits: list[dict]) -> list[dict]:
    """Multiple chunks from the same doc → keep the best-scoring one."""
    best_by_doc: dict[str, dict] = {}
    for hit in vector_hits:
        doc_id = hit.get("doc_id", "")
        if not doc_id:
            continue
        existing = best_by_doc.get(doc_id)
        if existing is None or hit.get("score", 0) > existing.get("score", 0):
            best_by_doc[doc_id] = hit
    return list(best_by_doc.values())


def rrf_merge(
    keyword_hits: list[dict],
    vector_hits: list[dict],
    k: int = RRF_K,
    limit: int = 0,
) -> list[dict]:
    """
    Merge keyword and vector results via Reciprocal Rank Fusion.

    keyword_hits: list of dicts with "id" field (from Meilisearch)
    vector_hits: list of dicts with "doc_id" field (from Qdrant, already deduped)

    Returns: merged list sorted by RRF score, using keyword hit metadata.
    """
    scores: dict[str, float] = {}
    keyword_flag: dict[str, bool] = {}
    metadata: dict[str, dict] = {}

    # Score keyword hits by rank position
    for rank, hit in enumerate(keyword_hits):
        doc_id = hit.get("id", "")
        if not doc_id:
            continue
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
        keyword_flag[doc_id] = True
        metadata[doc_id] = hit

    # Score vector hits by rank position
    deduped = deduplicate_chunks(vector_hits) if vector_hits else []
    # Sort by vector score descending to establish rank
    deduped.sort(key=lambda h: h.get("score", 0), reverse=True)

    for rank, hit in enumerate(deduped):
        doc_id = hit.get("doc_id", "")
        if not doc_id:
            continue
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
        if doc_id not in metadata:
            # Vector-only hit — build minimal metadata
            metadata[doc_id] = {
                "id": doc_id,
                "title": hit.get("title", ""),
                "source_index": hit.get("source_index", "documents"),
                "source_path": hit.get("source_path", ""),
                "source_format": hit.get("source_format", ""),
                "format": hit.get("source_format", ""),
                "path": hit.get("source_path", ""),
                "_vector_only": True,
            }

    # Sort by RRF score descending, keyword hits as tiebreaker
    sorted_ids = sorted(
        scores.keys(),
        key=lambda did: (scores[did], 1 if keyword_flag.get(did) else 0),
        reverse=True,
    )

    if limit > 0:
        sorted_ids = sorted_ids[:limit]

    return [metadata[did] for did in sorted_ids if did in metadata]


async def hybrid_search(
    query: str,
    keyword_results: list[dict],
    vector_manager,
    filters: dict | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Run vector search and merge with existing keyword results via RRF.

    keyword_results: already-fetched Meilisearch hits (from search_all).
    vector_manager: VectorIndexManager instance.
    """
    if vector_manager is None:
        return keyword_results

    try:
        source_format = (filters or {}).get("source_format", "")
        vector_hits = await vector_manager.search(
            query=query,
            limit=50,
            source_format=source_format,
        )
    except Exception as exc:
        log.warning("hybrid_search.vector_failed", error=str(exc))
        return keyword_results

    if not vector_hits:
        return keyword_results

    merged = rrf_merge(keyword_results, vector_hits, limit=limit)
    log.info("hybrid_search.merged",
             keyword_count=len(keyword_results),
             vector_count=len(vector_hits),
             merged_count=len(merged))
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_vector/test_hybrid_search.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/vector/hybrid_search.py tests/test_vector/test_hybrid_search.py
git commit -m "feat(vector): RRF hybrid search merging keyword + vector results"
```

---

### Task 7: Integrate Vector Indexing into Bulk Worker

**Files:**
- Modify: `core/bulk_worker.py:773`
- Modify: `core/search_indexer.py` (add rebuild hook)

- [ ] **Step 1: Read the exact integration point**

Read `core/bulk_worker.py` lines 768-800 to confirm the current state before editing.

- [ ] **Step 2: Add vector indexing after Meilisearch indexing**

In `core/bulk_worker.py`, after the existing Meilisearch `index_document` call (line 773), add a parallel vector indexing call inside the same try/except block. Find the line:

```python
        await indexer.index_document(actual_output, self.job_id)
```

And add immediately after it (still inside the same `try:` block, before the transcript indexing):

```python
                # Vector index (best-effort, parallel to Meilisearch)
                try:
                    from core.vector.index_manager import get_vector_indexer
                    vec_indexer = await get_vector_indexer()
                    if vec_indexer and actual_output and actual_output.exists():
                        _doc_id = _make_doc_id(str(actual_output))
                        await vec_indexer.index_document(
                            md_path=actual_output,
                            doc_id=_doc_id,
                            title=source_path.stem,
                            source_path=str(source_path),
                            source_format=source_path.suffix.lstrip("."),
                            source_index="documents",
                        )
                except Exception as vec_exc:
                    log.warning("bulk_vector_index_fail", file_id=file_id, error=str(vec_exc))
```

To get the `_make_doc_id` function, check how `search_indexer.py` generates doc IDs. It uses `_doc_id()` which is a SHA256 of the path. Import or replicate:

```python
from core.search_indexer import _doc_id as _make_doc_id
```

If `_doc_id` is not importable (private), inline the logic:

```python
import hashlib
def _make_doc_id(path_str: str) -> str:
    return hashlib.sha256(path_str.encode()).hexdigest()[:16]
```

- [ ] **Step 3: Add vector rebuild hook to search_indexer.py**

In `core/search_indexer.py`, find the `rebuild_all()` method (or wherever the full Meilisearch re-index is triggered). After the Meilisearch rebuild completes, add:

```python
        # Trigger vector re-index in parallel (best-effort)
        try:
            from core.vector.index_manager import get_vector_indexer
            vec_indexer = await get_vector_indexer()
            if vec_indexer:
                log.info("vector.rebuild_start")
                # Re-index happens via the same bulk_worker path
                # Just ensure the collection exists
                await vec_indexer.ensure_collection()
        except Exception as exc:
            log.warning("vector.rebuild_skip", error=str(exc))
```

- [ ] **Step 4: Verify no import errors**

Run: `cd /opt/doc-conversion-2026 && python -c "import ast; ast.parse(open('core/bulk_worker.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add core/bulk_worker.py core/search_indexer.py
git commit -m "feat(vector): integrate vector indexing into bulk conversion pipeline"
```

---

### Task 8: Integrate Hybrid Search into Search API

**Files:**
- Modify: `api/routes/search.py`

- [ ] **Step 1: Read the search_all endpoint**

Read `api/routes/search.py` lines 160-283 to understand the current fanout and merge pattern.

- [ ] **Step 2: Add hybrid search to search_all**

Find the section where `all_hits` is assembled from the three index results (around line 254-261). After the `all_hits` list is built but before the response is returned, add the hybrid merge:

```python
    # ── Hybrid search: blend with vector results if available ───────────
    try:
        from core.vector.index_manager import get_vector_indexer
        from core.vector.hybrid_search import hybrid_search as _hybrid_search
        from core.vector.query_preprocessor import preprocess_query

        vec_indexer = await get_vector_indexer()
        if vec_indexer and q:
            intent = preprocess_query(q)
            all_hits = await _hybrid_search(
                query=intent.normalized_query,
                keyword_results=all_hits,
                vector_manager=vec_indexer,
                filters={"source_format": format_filter} if format_filter else None,
                limit=per_page,
            )
            # If temporal intent detected, prefer date-sorted keyword ranking
            if intent.has_temporal_intent and sort_by == "relevance":
                sort_by = "date"
    except Exception as exc:
        log.warning("hybrid_search.skip", error=str(exc))
        # Fall through — use keyword-only results
```

This must be placed AFTER `all_hits` is populated and BEFORE the sorting/pagination logic.

- [ ] **Step 3: Verify no import errors**

Run: `cd /opt/doc-conversion-2026 && python -c "import ast; ast.parse(open('api/routes/search.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/routes/search.py
git commit -m "feat(vector): hybrid search in /api/search/all endpoint"
```

---

### Task 9: Pipeline Startup + Health Gate

**Files:**
- Modify: `core/pipeline_startup.py`

- [ ] **Step 1: Add qdrant to preferred services**

In `core/pipeline_startup.py`, find the `PREFERRED_SERVICES` set (line ~25):

```python
PREFERRED_SERVICES = {"meilisearch", "tesseract", "libreoffice"}
```

This does NOT need qdrant added — Qdrant health is checked by the vector index manager lazily when first used, not by the pipeline startup. The `get_vector_indexer()` function already handles unavailability gracefully.

However, add a startup log message. In `main.py` lifespan, after the Meilisearch init block (around line 127), add:

```python
    # Initialize vector search (best-effort — app starts without it)
    try:
        from core.vector.index_manager import get_vector_indexer
        vec_indexer = await get_vector_indexer()
        if vec_indexer:
            status = await vec_indexer.get_status()
            log.info("markflow.vector_search_ready", **status)
        else:
            log.info("markflow.vector_search_disabled", reason="Qdrant not configured or unreachable")
    except Exception as exc:
        log.warning("markflow.vector_search_init_skip", error=str(exc))
```

- [ ] **Step 2: Verify syntax**

Run: `cd /opt/doc-conversion-2026 && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(vector): vector search startup health check in lifespan"
```

---

### Task 10: Version Bump + Documentation

**Files:**
- Modify: `core/version.py`
- Modify: `CLAUDE.md`
- Modify: `docs/version-history.md`

- [ ] **Step 1: Bump version**

In `core/version.py`, change:

```python
__version__ = "0.22.0"
```

- [ ] **Step 2: Update CLAUDE.md current status**

Replace the current status section header and first block with:

```
## Current Status — v0.22.0

v0.22.0: Hybrid Vector Search — Qdrant vector DB augments Meilisearch keyword
search via Reciprocal Rank Fusion. Documents chunked with contextual headers,
embedded locally via sentence-transformers (all-MiniLM-L6-v2, 384d). Query
preprocessor detects temporal intent. Graceful fallback to keyword-only when
Qdrant is unavailable.
New: core/vector/ package (chunker, embedder, index_manager, hybrid_search,
     query_preprocessor). Qdrant container in docker-compose.yml.
```

Add gotcha:

```
- **Vector search is best-effort**: `get_vector_indexer()` returns `None` when Qdrant is unreachable. All call sites must handle `None`. Never make vector search a hard dependency.
- **Embedding model loaded lazily**: First embedding call loads ~80MB model into RAM. Lazy import `sentence_transformers` inside `_load_model()` to avoid slow lifespan. Same pattern as Whisper.
- **Chunk IDs are deterministic**: SHA256 of `doc_id:chunk_index`. Re-indexing the same document produces the same chunk IDs → idempotent upserts in Qdrant.
```

- [ ] **Step 3: Add version history entry**

Add to `docs/version-history.md` at the top (after the `---`):

```markdown
## v0.22.0 — Hybrid Vector Search (2026-04-05)

**Feature:** Semantic vector search augmenting existing Meilisearch keyword search.
Documents are chunked with contextual headers, embedded locally via sentence-transformers,
and stored in Qdrant. At query time, both systems run in parallel and results merge
via Reciprocal Rank Fusion (RRF). Graceful fallback to keyword-only when Qdrant is
unavailable.

**New files:**
- `core/vector/chunker.py` — Markdown → contextual chunks (heading-based + fixed-size fallback)
- `core/vector/embedder.py` — Pluggable embedding (local sentence-transformers default)
- `core/vector/index_manager.py` — Qdrant collection lifecycle, document indexing, search
- `core/vector/hybrid_search.py` — RRF merge of keyword + vector results
- `core/vector/query_preprocessor.py` — Temporal intent detection, query normalization

**Modified files:**
- `docker-compose.yml` — Qdrant container + volume
- `requirements.txt` — sentence-transformers, qdrant-client
- `core/bulk_worker.py` — Vector indexing parallel to Meilisearch (fire-and-forget)
- `api/routes/search.py` — Hybrid search in `/api/search/all`
- `main.py` — Vector search startup health check

**Infrastructure:**
- Qdrant container on port 6333 (internal only)
- Single collection `markflow_chunks` with payload filtering
- `all-MiniLM-L6-v2` embedding model (384 dimensions, ~80MB, CPU inference)
- Model version tracked in collection metadata for future upgrade path
```

- [ ] **Step 4: Commit**

```bash
git add core/version.py CLAUDE.md docs/version-history.md
git commit -m "docs: version bump to v0.22.0 — hybrid vector search"
```

---

### Task 11: Integration Smoke Test

This is a manual verification task after rebuilding the Docker stack.

- [ ] **Step 1: Rebuild and start the stack**

```bash
cd /opt/doc-conversion-2026
docker compose build && docker compose up -d
```

Wait for health checks to pass:
```bash
docker compose ps
```

Expected: `markflow`, `meilisearch`, `qdrant` all `Up (healthy)`

- [ ] **Step 2: Verify Qdrant is reachable**

```bash
curl http://localhost:6333/healthz
```

Expected: `{"title":"qdrant - vectorass search engine","version":"..."}`

- [ ] **Step 3: Check startup logs for vector search init**

```bash
docker compose logs markflow | grep vector
```

Expected: `markflow.vector_search_ready` with collection info, OR `markflow.vector_search_disabled` if Qdrant hasn't connected yet.

- [ ] **Step 4: Verify search still works (keyword-only fallback)**

```bash
curl http://localhost:8000/api/health
curl "http://localhost:8000/api/search/all?q=test&page=1&per_page=5"
```

Expected: Health check passes. Search returns results (keyword-only until documents are re-indexed with vectors).

- [ ] **Step 5: Trigger a re-index to populate vectors**

Use the existing rebuild endpoint:
```bash
curl -X POST http://localhost:8000/api/search/index/rebuild
```

Then check Qdrant has vectors:
```bash
curl http://localhost:6333/collections/markflow_chunks
```

Expected: `points_count` > 0 after re-index completes.

- [ ] **Step 6: Test hybrid search**

Search for something semantic:
```bash
curl "http://localhost:8000/api/search/all?q=compensation+rates&page=1&per_page=5"
```

Check logs for hybrid merge:
```bash
docker compose logs markflow | grep hybrid_search
```

Expected: `hybrid_search.merged` log entry showing keyword_count, vector_count, merged_count.
