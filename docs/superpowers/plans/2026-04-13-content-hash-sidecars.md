# C1-a: Content-Hash-Keyed Style Sidecars Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicate-content collisions in style sidecars by keying entries with `{hash}:{occurrence}` instead of bare `{hash}`, add fuzzy-match fallback for lightly edited paragraphs, and migrate existing v1 sidecars automatically.

**Architecture:** Sidecar element keys change from bare content hashes (`a1b2c3d4e5f6g7h8`) to occurrence-indexed hashes (`a1b2c3d4e5f6g7h8:0`, `a1b2c3d4e5f6g7h8:1`). Each entry gains a `_text` field storing the normalized source text, enabling fuzzy matching when the hash doesn't match (user edited the paragraph). A new `core/sidecar_match.py` module centralizes the lookup logic: exact hash+occurrence → bare hash fallback (v1 compat) → fuzzy text match (Levenshtein ≤ 10%). Schema version bumps from `1.0.0` to `2.0.0`; `load_sidecar()` auto-migrates v1 by appending `:0` to bare-hash keys.

**Tech Stack:** Python stdlib only (`hashlib`, `difflib.SequenceMatcher`, `collections.Counter`). No new dependencies.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `core/sidecar_match.py` | Occurrence-aware lookup + fuzzy-match fallback |
| Create | `tests/test_sidecar_match.py` | Unit tests for sidecar_match module |
| Modify | `core/metadata.py:22-24,98-128` | Schema version bump, v1→v2 migration, `_text` field in `generate_sidecar` |
| Modify | `formats/docx_handler.py:505-528,562-585,767-836` | Occurrence counting in extraction + use sidecar_match for lookup |
| Modify | `formats/pptx_handler.py:516-581` | Occurrence counting in extraction |
| Modify | `tests/test_roundtrip.py` | New tests: duplicate content, fuzzy match, v1 compat |

---

### Task 1: Sidecar Matching Module — Failing Tests

**Files:**
- Create: `tests/test_sidecar_match.py`
- Create: `core/sidecar_match.py` (empty stub)

This task writes all the unit tests for the matching logic before implementing it.

- [ ] **Step 1: Create empty module stub**

```python
# core/sidecar_match.py
"""
Occurrence-aware sidecar element lookup with fuzzy-match fallback.

Used by format handlers during round-trip (MD → DOCX) to resolve which
sidecar style entry applies to each document element.
"""
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_sidecar_match.py
"""Unit tests for core.sidecar_match — occurrence lookup + fuzzy matching."""

import pytest
from core.sidecar_match import resolve_sidecar_entry, OccurrenceTracker


# ── Exact match (v2 keying) ──────────────────────────────────────────────────

class TestExactMatch:
    def test_first_occurrence_matches(self):
        """First element with hash 'abc' resolves to 'abc:0'."""
        elements = {
            "abc:0": {"type": "paragraph", "bold": True},
            "abc:1": {"type": "paragraph", "bold": False},
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(elements, "Hello world", tracker)
        assert entry is not None
        assert entry["bold"] is True

    def test_second_occurrence_matches(self):
        """Second element with same hash resolves to 'abc:1'."""
        elements = {
            "abc:0": {"type": "paragraph", "bold": True},
            "abc:1": {"type": "paragraph", "bold": False},
        }
        tracker = OccurrenceTracker()
        # First call consumes :0
        resolve_sidecar_entry(elements, "Hello world", tracker)
        # Second call with same text gets :1
        entry = resolve_sidecar_entry(elements, "Hello world", tracker)
        assert entry is not None
        assert entry["bold"] is False

    def test_different_hashes_independent(self):
        """Different content hashes track occurrences independently."""
        elements = {
            "abc:0": {"type": "paragraph", "font_family": "Arial"},
            "xyz:0": {"type": "paragraph", "font_family": "Times"},
        }
        tracker = OccurrenceTracker()
        e1 = resolve_sidecar_entry(elements, "Hello world", tracker)
        e2 = resolve_sidecar_entry(elements, "Different text", tracker)
        assert e1["font_family"] == "Arial"
        assert e2["font_family"] == "Times"

    def test_overflow_occurrence_returns_last(self):
        """When occurrences exceed stored entries, return the last one."""
        elements = {
            "abc:0": {"type": "paragraph", "bold": True},
            "abc:1": {"type": "paragraph", "bold": False},
        }
        tracker = OccurrenceTracker()
        resolve_sidecar_entry(elements, "Hello world", tracker)  # :0
        resolve_sidecar_entry(elements, "Hello world", tracker)  # :1
        entry = resolve_sidecar_entry(elements, "Hello world", tracker)  # :2 → fallback to :1
        assert entry is not None
        assert entry["bold"] is False

    def test_no_match_returns_none(self):
        """Content with no matching hash returns None."""
        elements = {"xyz:0": {"type": "paragraph"}}
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(elements, "Unmatched content", tracker)
        assert entry is None


# ── v1 backward compatibility ────────────────────────────────────────────────

class TestV1Compat:
    def test_bare_hash_fallback(self):
        """v1 sidecar with bare hash keys still matches."""
        elements = {
            "abc": {"type": "paragraph", "bold": True},  # v1: no :N suffix
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(elements, "Hello world", tracker)
        assert entry is not None
        assert entry["bold"] is True

    def test_v2_preferred_over_v1(self):
        """If both 'abc:0' and 'abc' exist, v2 key wins."""
        elements = {
            "abc:0": {"type": "paragraph", "bold": True},
            "abc": {"type": "paragraph", "bold": False},
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(elements, "Hello world", tracker)
        assert entry["bold"] is True  # v2 key wins


# ── Fuzzy match fallback ─────────────────────────────────────────────────────

class TestFuzzyMatch:
    def test_minor_edit_matches(self):
        """Text edited by ≤10% matches the closest sidecar entry."""
        elements = {
            "abc:0": {
                "type": "paragraph",
                "bold": True,
                "_text": "this is the first paragraph of the document",
            },
        }
        tracker = OccurrenceTracker()
        # ~7% edit distance (changed "first" to "1st")
        entry = resolve_sidecar_entry(
            elements,
            "This is the 1st paragraph of the document",
            tracker,
        )
        assert entry is not None
        assert entry["bold"] is True

    def test_major_edit_no_match(self):
        """Text edited by >10% does not fuzzy-match."""
        elements = {
            "abc:0": {
                "type": "paragraph",
                "bold": True,
                "_text": "this is the first paragraph of the document",
            },
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(
            elements,
            "Completely rewritten content that shares nothing",
            tracker,
        )
        assert entry is None

    def test_fuzzy_skips_entries_without_text(self):
        """Entries without _text field are skipped during fuzzy matching."""
        elements = {
            "abc:0": {"type": "paragraph", "bold": True},  # no _text
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(
            elements,
            "This is the 1st paragraph of the document",
            tracker,
        )
        assert entry is None

    def test_fuzzy_picks_best_match(self):
        """When multiple entries could fuzzy-match, the closest wins."""
        elements = {
            "aaa:0": {
                "type": "paragraph",
                "bold": True,
                "_text": "the quick brown fox jumps over the lazy dog",
            },
            "bbb:0": {
                "type": "paragraph",
                "bold": False,
                "_text": "the quick brown cat jumps over the lazy dog",
            },
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(
            elements,
            "The quick brown cat jumps over the lazy dog!",
            tracker,
        )
        assert entry is not None
        assert entry["bold"] is False  # closer to "cat" entry


# ── Markdown-marker stripping ────────────────────────────────────────────────

class TestMarkdownStripping:
    def test_bold_markers_stripped(self):
        """**bold** markers are stripped before hashing."""
        elements = {"abc:0": {"type": "paragraph", "bold": True}}
        tracker = OccurrenceTracker()
        # "Hello world" and "**Hello** world" should produce the same hash
        e1 = resolve_sidecar_entry(elements, "Hello world", tracker)
        tracker2 = OccurrenceTracker()
        e2 = resolve_sidecar_entry(elements, "**Hello** world", tracker2)
        # At least one should match (depends on hash of "hello world")
        # This test validates the stripping logic works — actual hash match
        # depends on the test content aligning with "abc"
        # Better: use real hashes
        pass  # Covered by integration test in test_roundtrip.py
```

Note: The `TestMarkdownStripping` test uses synthetic hash keys (`"abc"`) that won't match real content hashes. The real markdown-stripping behavior is validated in `test_roundtrip.py` integration tests (Task 6). Remove the `pass` placeholder class and replace with:

```python
class TestMarkdownStripping:
    def test_bold_markers_stripped_for_lookup(self):
        """Bold markers in content are stripped before hash lookup."""
        from core.document_model import compute_content_hash
        plain_hash = compute_content_hash("hello world")
        elements = {
            f"{plain_hash}:0": {"type": "paragraph", "bold": True},
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(elements, "**Hello** world", tracker)
        assert entry is not None
        assert entry["bold"] is True

    def test_italic_markers_stripped(self):
        from core.document_model import compute_content_hash
        plain_hash = compute_content_hash("italic text here")
        elements = {
            f"{plain_hash}:0": {"type": "paragraph", "italic": True},
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(elements, "*italic text here*", tracker)
        assert entry is not None

    def test_code_markers_stripped(self):
        from core.document_model import compute_content_hash
        plain_hash = compute_content_hash("use the foo function")
        elements = {
            f"{plain_hash}:0": {"type": "paragraph", "font_family": "Consolas"},
        }
        tracker = OccurrenceTracker()
        entry = resolve_sidecar_entry(elements, "use the `foo` function", tracker)
        assert entry is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec markflow-app python -m pytest tests/test_sidecar_match.py -v 2>&1 | head -40`
Expected: ERRORS — `ImportError: cannot import name 'resolve_sidecar_entry' from 'core.sidecar_match'`

- [ ] **Step 4: Commit**

```bash
git add tests/test_sidecar_match.py core/sidecar_match.py
git commit -m "test: add failing tests for occurrence-aware sidecar matching (C1-a)"
```

---

### Task 2: Sidecar Matching Module — Implementation

**Files:**
- Modify: `core/sidecar_match.py`

Implement the matching logic to make all Task 1 tests pass.

- [ ] **Step 1: Implement the module**

```python
# core/sidecar_match.py
"""
Occurrence-aware sidecar element lookup with fuzzy-match fallback.

Used by format handlers during round-trip (MD → DOCX) to resolve which
sidecar style entry applies to each document element.

Lookup cascade:
  1. Exact hash+occurrence: "{hash}:{n}" where n = nth time this hash seen
  2. Bare hash fallback:   "{hash}" (v1 sidecar backward compat)
  3. Fuzzy text match:      normalized Levenshtein ratio ≥ 0.90 against _text fields

The caller must pass the same OccurrenceTracker instance across all calls
within a single export operation to maintain correct counting.
"""

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from core.document_model import compute_content_hash

import structlog

log = structlog.get_logger(__name__)

_FUZZY_THRESHOLD = 0.90  # SequenceMatcher ratio; 0.90 ≈ ≤10% edit distance

# Regex to strip markdown inline markers (same as docx_handler._plain_text_hash)
_MD_BOLD_ITALIC = re.compile(r"\*{1,3}(.+?)\*{1,3}", re.DOTALL)
_MD_CODE = re.compile(r"`(.+?)`", re.DOTALL)


class OccurrenceTracker:
    """Counts how many times each content hash has been seen during a single
    export pass. Thread-safe is NOT required — one tracker per export call."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def next(self, content_hash: str) -> int:
        """Return the current occurrence index for *content_hash*, then increment."""
        n = self._counts[content_hash]
        self._counts[content_hash] += 1
        return n


def _strip_md_markers(text: str) -> str:
    """Strip inline markdown markers (**bold**, *italic*, `code`)."""
    plain = _MD_BOLD_ITALIC.sub(r"\1", str(text))
    plain = _MD_CODE.sub(r"\1", plain)
    return plain


def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase for comparison."""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def resolve_sidecar_entry(
    elements_map: dict[str, Any],
    content_text: str,
    tracker: OccurrenceTracker,
) -> dict[str, Any] | None:
    """Look up the sidecar style entry for *content_text*.

    Args:
        elements_map: The ``"elements"`` dict from a loaded sidecar.
        content_text: The element's text content (may include markdown markers).
        tracker: Shared occurrence tracker for this export pass.

    Returns:
        The matching style entry dict, or ``None`` if no match found.
    """
    # Hash the plain text (strip markdown markers first)
    plain = _strip_md_markers(content_text)
    h = compute_content_hash(plain)
    n = tracker.next(h)

    # 1. Exact v2 key: "{hash}:{n}"
    v2_key = f"{h}:{n}"
    entry = elements_map.get(v2_key)
    if entry is not None:
        return entry

    # 1b. Overflow: occurrence exceeds stored entries → try last stored
    if n > 0:
        for fallback_n in range(n - 1, -1, -1):
            entry = elements_map.get(f"{h}:{fallback_n}")
            if entry is not None:
                return entry

    # 2. Bare hash fallback (v1 compat)
    entry = elements_map.get(h)
    if entry is not None:
        return entry

    # 3. Also try hashing with markers intact (in case content has no markers
    #    but the sidecar was keyed from marked-up text — shouldn't happen in
    #    practice but costs nothing)
    h_raw = compute_content_hash(content_text)
    if h_raw != h:
        for key_candidate in [f"{h_raw}:{n}", h_raw]:
            entry = elements_map.get(key_candidate)
            if entry is not None:
                return entry

    # 4. Fuzzy match — compare normalized text against all _text fields
    normalized = _normalize(plain)
    if not normalized:
        return None

    best_entry: dict[str, Any] | None = None
    best_ratio = _FUZZY_THRESHOLD

    for _key, candidate in elements_map.items():
        if not isinstance(candidate, dict):
            continue
        stored_text = candidate.get("_text")
        if not stored_text:
            continue
        ratio = SequenceMatcher(None, normalized, str(stored_text)).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_entry = candidate

    if best_entry is not None:
        log.debug(
            "sidecar.fuzzy_match",
            content=content_text[:40],
            ratio=round(best_ratio, 3),
        )

    return best_entry
```

- [ ] **Step 2: Run tests**

Run: `docker exec markflow-app python -m pytest tests/test_sidecar_match.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add core/sidecar_match.py
git commit -m "feat(C1-a): implement occurrence-aware sidecar matching with fuzzy fallback"
```

---

### Task 3: Schema Migration — Failing Tests

**Files:**
- Modify: `tests/test_sidecar_match.py` (append migration tests)

- [ ] **Step 1: Append migration tests to test_sidecar_match.py**

```python
# Append to tests/test_sidecar_match.py

from core.metadata import (
    generate_sidecar,
    load_sidecar,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
)
from core.document_model import DocumentModel, DocumentMetadata, Element, ElementType
import json


class TestSchemaMigration:
    def test_schema_version_is_2(self):
        """Current schema version is 2.0.0."""
        assert SCHEMA_VERSION == "2.0.0"

    def test_v1_supported(self):
        """v1 sidecars are still loadable."""
        assert "1.0.0" in SUPPORTED_SCHEMA_VERSIONS

    def test_v2_supported(self):
        assert "2.0.0" in SUPPORTED_SCHEMA_VERSIONS

    def test_load_v1_migrates_keys(self, tmp_path):
        """Loading a v1 sidecar auto-migrates bare hash keys to :0 suffix."""
        v1_sidecar = {
            "schema_version": "1.0.0",
            "source_format": "docx",
            "source_file": "test.docx",
            "converted_at": "2026-01-01T00:00:00Z",
            "document_level": {"margin_top_pt": 72.0},
            "elements": {
                "abc123": {"type": "paragraph", "bold": True},
                "xyz789": {"type": "table", "column_widths_pt": [100]},
            },
        }
        path = tmp_path / "test.styles.json"
        path.write_text(json.dumps(v1_sidecar), encoding="utf-8")

        loaded = load_sidecar(path)
        assert loaded["schema_version"] == "2.0.0"
        assert "abc123:0" in loaded["elements"]
        assert "xyz789:0" in loaded["elements"]
        # Bare keys removed after migration
        assert "abc123" not in loaded["elements"]
        assert "xyz789" not in loaded["elements"]
        # Values preserved
        assert loaded["elements"]["abc123:0"]["bold"] is True

    def test_load_v2_no_migration(self, tmp_path):
        """Loading a v2 sidecar does not re-migrate."""
        v2_sidecar = {
            "schema_version": "2.0.0",
            "source_format": "docx",
            "source_file": "test.docx",
            "converted_at": "2026-01-01T00:00:00Z",
            "document_level": {},
            "elements": {
                "abc123:0": {"type": "paragraph", "bold": True},
                "abc123:1": {"type": "paragraph", "bold": False},
            },
        }
        path = tmp_path / "test.styles.json"
        path.write_text(json.dumps(v2_sidecar), encoding="utf-8")

        loaded = load_sidecar(path)
        assert "abc123:0" in loaded["elements"]
        assert "abc123:1" in loaded["elements"]

    def test_generate_sidecar_v2_keys(self):
        """generate_sidecar produces v2 occurrence-indexed keys."""
        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file="test.docx",
            source_format="docx",
        )
        # Simulate style_data with occurrence-indexed keys (as handlers will produce)
        style_data = {
            "document_level": {"margin_top_pt": 72.0},
            "abc123:0": {"type": "paragraph", "bold": True},
            "abc123:1": {"type": "paragraph", "bold": False},
        }
        sidecar = generate_sidecar(model, style_data)
        assert sidecar["schema_version"] == "2.0.0"
        assert "abc123:0" in sidecar["elements"]
        assert "abc123:1" in sidecar["elements"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec markflow-app python -m pytest tests/test_sidecar_match.py::TestSchemaMigration -v`
Expected: FAIL — `assert SCHEMA_VERSION == "2.0.0"` (still `"1.0.0"`)

- [ ] **Step 3: Commit**

```bash
git add tests/test_sidecar_match.py
git commit -m "test: add failing schema migration tests for sidecar v1→v2 (C1-a)"
```

---

### Task 4: Schema Migration — Implementation

**Files:**
- Modify: `core/metadata.py:22-24,98-128`

- [ ] **Step 1: Update metadata.py**

Apply these changes to `core/metadata.py`:

**a)** Change schema version constants (lines 22-24):

```python
# Old:
SCHEMA_VERSION = "1.0.0"
MARKFLOW_VERSION = "0.1.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0"}

# New:
SCHEMA_VERSION = "2.0.0"
MARKFLOW_VERSION = "0.1.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0", "2.0.0"}
```

**b)** Add migration function after the `load_sidecar` function (after line 128):

```python
def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v1 sidecar to v2 by appending :0 to bare-hash element keys.

    v1 keys are bare 16-char hex hashes (e.g., "a1b2c3d4e5f6g7h8").
    v2 keys are "{hash}:{occurrence}" (e.g., "a1b2c3d4e5f6g7h8:0").
    """
    elements = data.get("elements", {})
    migrated: dict[str, Any] = {}
    for key, value in elements.items():
        if ":" not in key:
            # Bare hash → append :0
            migrated[f"{key}:0"] = value
        else:
            migrated[key] = value
    data["elements"] = migrated
    data["schema_version"] = SCHEMA_VERSION
    return data
```

**c)** Update `load_sidecar` to call migration (replace lines 116-128):

```python
def load_sidecar(path: Path) -> dict[str, Any]:
    """Load and validate a style sidecar JSON file.

    Auto-migrates v1 sidecars (bare hash keys) to v2 (occurrence-indexed).
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("schema_version", "unknown")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        data["_migration_warning"] = (
            f"Sidecar schema version '{version}' is not supported. "
            f"Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    elif version == "1.0.0":
        data = _migrate_v1_to_v2(data)

    return data
```

- [ ] **Step 2: Run migration tests**

Run: `docker exec markflow-app python -m pytest tests/test_sidecar_match.py::TestSchemaMigration -v`
Expected: ALL PASS

- [ ] **Step 3: Run ALL existing tests to verify nothing broke**

Run: `docker exec markflow-app python -m pytest tests/test_roundtrip.py tests/test_sidecar_match.py -v`
Expected: ALL PASS (existing roundtrip tests still work because v1 sidecars are auto-migrated)

- [ ] **Step 4: Commit**

```bash
git add core/metadata.py
git commit -m "feat(C1-a): bump sidecar schema to v2, auto-migrate v1 bare-hash keys"
```

---

### Task 5: Docx Handler — Extraction with Occurrence Counting

**Files:**
- Modify: `formats/docx_handler.py:505-528,562-585`
- Modify: `tests/test_roundtrip.py` (add duplicate-content test)

This task adds `{hash}:{n}` keying and the `_text` field to `extract_styles()` and `_table_styles()`.

- [ ] **Step 1: Write failing roundtrip test for duplicate content**

Append to `tests/test_roundtrip.py`:

```python
def test_duplicate_paragraphs_preserve_distinct_styles(tmp_path, docx_handler, md_handler):
    """Two identical paragraphs with different styles both survive the sidecar round-trip.

    Regression test for C1-a: before occurrence-indexed keys, the second
    paragraph's style overwrote the first (same hash = same dict key).
    """
    # Build a DOCX with two identical paragraphs, different formatting
    from docx import Document as _Doc
    from docx.shared import Pt

    doc = _Doc()
    p1 = doc.add_paragraph()
    run1 = p1.add_run("Repeated paragraph text")
    run1.font.bold = True
    run1.font.size = Pt(14)

    p2 = doc.add_paragraph()
    run2 = p2.add_run("Repeated paragraph text")
    run2.font.italic = True
    run2.font.size = Pt(10)

    docx_path = tmp_path / "dupes.docx"
    doc.save(str(docx_path))

    # Extract styles — should produce two entries, not one
    style_data = docx_handler.extract_styles(docx_path)
    sidecar = generate_sidecar(docx_handler.ingest(docx_path), style_data)
    elements = sidecar["elements"]

    h = compute_content_hash("Repeated paragraph text")
    assert f"{h}:0" in elements, "First occurrence missing from sidecar"
    assert f"{h}:1" in elements, "Second occurrence missing from sidecar"

    # Styles should differ
    assert elements[f"{h}:0"]["bold"] is True
    assert elements[f"{h}:1"].get("italic") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec markflow-app python -m pytest tests/test_roundtrip.py::test_duplicate_paragraphs_preserve_distinct_styles -v`
Expected: FAIL — `KeyError: '{hash}:0'` (v1 uses bare hash)

- [ ] **Step 3: Update `extract_styles()` in docx_handler.py**

Replace the per-paragraph extraction block (lines 506-521) with occurrence counting:

```python
        # ── Per-paragraph styles ──────────────────────────────────────────
        from docx.oxml.ns import qn
        from collections import Counter

        _hash_counter: Counter[str] = Counter()

        for child in doc.element.body:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag == "p":
                from docx.text.paragraph import Paragraph
                para = Paragraph(child, doc)
                text = para.text.strip()
                if not text:
                    continue
                h = compute_content_hash(text)
                entry = self._para_style_entry(para)
                if entry:
                    n = _hash_counter[h]
                    _hash_counter[h] += 1
                    entry["_text"] = re.sub(r"\s+", " ", text).strip().lower()
                    style_data[f"{h}:{n}"] = entry

            elif tag == "tbl":
                from docx.table import Table
                table = Table(child, doc)
                self._table_styles(table, style_data, _hash_counter)

        return style_data
```

- [ ] **Step 4: Update `_table_styles()` signature and keying**

Change `_table_styles` (lines 562-587) to accept and use the counter:

```python
    def _table_styles(self, table, style_data: dict[str, Any],
                      hash_counter: "Counter[str] | None" = None) -> None:
        """Extract and store style info for a table."""
        from collections import Counter
        if hash_counter is None:
            hash_counter = Counter()
        try:
            rows_text = [
                [cell.text.strip() for cell in row.cells]
                for row in table.rows
            ]
            h = compute_content_hash(rows_text)
            entry: dict[str, Any] = {"type": "table"}
            # Column widths in points
            col_widths = []
            for col in table.columns:
                try:
                    col_widths.append(_emu_to_pt(col.width))
                except Exception:
                    col_widths.append(None)
            if col_widths:
                entry["column_widths_pt"] = col_widths
            # Table style name
            try:
                entry["table_style"] = table.style.name if table.style else ""
            except Exception:
                pass
            n = hash_counter[h]
            hash_counter[h] += 1
            style_data[f"{h}:{n}"] = entry
        except Exception as exc:
            log.debug("docx.table_style_skip", reason=str(exc))
```

Note: add `import re` at the top of the extraction block if not already imported (it is — line 762 has `import re` but that's inside the export method; check the top-of-file imports). The `re` module is already imported at the top of `docx_handler.py`.

- [ ] **Step 5: Run test**

Run: `docker exec markflow-app python -m pytest tests/test_roundtrip.py::test_duplicate_paragraphs_preserve_distinct_styles -v`
Expected: PASS

- [ ] **Step 6: Run all roundtrip tests**

Run: `docker exec markflow-app python -m pytest tests/test_roundtrip.py -v`
Expected: ALL PASS (existing tests use auto-migrated v1→v2 flow internally)

- [ ] **Step 7: Commit**

```bash
git add formats/docx_handler.py tests/test_roundtrip.py
git commit -m "feat(C1-a): occurrence-indexed keys + _text field in docx style extraction"
```

---

### Task 6: Docx Handler — Occurrence-Aware Lookup

**Files:**
- Modify: `formats/docx_handler.py:767-836` (`_apply_sidecar_style`)
- Modify: `formats/docx_handler.py` (export method — initialize tracker)

Wire the export path to use `resolve_sidecar_entry` from `core/sidecar_match.py`.

- [ ] **Step 1: Write failing roundtrip test for Tier 2 with duplicates**

Append to `tests/test_roundtrip.py`:

```python
def test_tier2_duplicate_styles_applied(tmp_path, docx_handler, md_handler):
    """Full round-trip: duplicate paragraphs get their distinct styles back via Tier 2."""
    from docx import Document as _Doc
    from docx.shared import Pt, RGBColor

    # Build source DOCX with two identical paragraphs, different styles
    doc = _Doc()
    doc.add_heading("Test Document", level=1)

    p1 = doc.add_paragraph()
    r1 = p1.add_run("Same text here")
    r1.font.bold = True
    r1.font.size = Pt(14)

    p2 = doc.add_paragraph()
    r2 = p2.add_run("Same text here")
    r2.font.italic = True
    r2.font.size = Pt(10)

    docx_path = tmp_path / "src.docx"
    doc.save(str(docx_path))

    # DOCX → MD + sidecar
    model = docx_handler.ingest(docx_path)
    style_data = docx_handler.extract_styles(docx_path)
    sidecar = generate_sidecar(model, style_data)

    md_path = tmp_path / "rt.md"
    md_handler.export(model, md_path)

    # MD → DOCX (Tier 2)
    model2 = md_handler.ingest(md_path)
    out = tmp_path / "rt_out.docx"
    docx_handler.export(model2, out, sidecar=sidecar)

    # Verify both paragraphs exist and have distinct formatting
    out_doc = _Doc(str(out))
    same_text_paras = [
        p for p in out_doc.paragraphs
        if "Same text here" in p.text
    ]
    assert len(same_text_paras) >= 2, "Both duplicate paragraphs should survive round-trip"

    # First should be bold 14pt, second italic 10pt
    first_run = same_text_paras[0].runs[0] if same_text_paras[0].runs else None
    second_run = same_text_paras[1].runs[0] if same_text_paras[1].runs else None
    assert first_run is not None and second_run is not None

    assert first_run.font.bold is True
    assert second_run.font.italic is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec markflow-app python -m pytest tests/test_roundtrip.py::test_tier2_duplicate_styles_applied -v`
Expected: FAIL — both paragraphs get the same style (last-one-wins from v1 lookup)

- [ ] **Step 3: Add OccurrenceTracker to docx export**

In `formats/docx_handler.py`, add import at the top of the file (after existing imports):

```python
from core.sidecar_match import OccurrenceTracker, resolve_sidecar_entry
```

In the `export` method (around line 591), initialize the tracker at the start of the method body, right after the docstring:

```python
    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        # ... existing docstring ...

        # Track sidecar occurrence counts for this export pass
        self._sidecar_tracker = OccurrenceTracker()

        # ... rest of existing export code ...
```

- [ ] **Step 4: Rewrite `_apply_sidecar_style` to use `resolve_sidecar_entry`**

Replace the entire `_apply_sidecar_style` method (lines 767-836):

```python
    def _apply_sidecar_style(self, para, content: str, sidecar: dict | None) -> None:
        """
        Apply Tier 2 style from sidecar to a paragraph (best-effort).

        Uses occurrence-aware lookup from core.sidecar_match to handle
        duplicate paragraphs with distinct styles. Falls back to fuzzy
        matching for lightly edited content.
        """
        if not sidecar:
            return
        elements_map = sidecar.get("elements", {})
        tracker = getattr(self, "_sidecar_tracker", None)
        if tracker is None:
            tracker = OccurrenceTracker()
            self._sidecar_tracker = tracker

        entry = resolve_sidecar_entry(elements_map, content, tracker)
        if not entry:
            return

        try:
            from docx.shared import Pt, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            # Apply run-level formatting to ALL runs
            for run in para.runs:
                if entry.get("font_family"):
                    run.font.name = entry["font_family"]
                if entry.get("font_size_pt"):
                    run.font.size = Pt(entry["font_size_pt"])
                if entry.get("bold") is True:
                    run.font.bold = True
                if entry.get("italic") is True:
                    run.font.italic = True
                if entry.get("color"):
                    hex_color = str(entry["color"]).lstrip("#")
                    if len(hex_color) == 6:
                        r, g, b = (
                            int(hex_color[0:2], 16),
                            int(hex_color[2:4], 16),
                            int(hex_color[4:6], 16),
                        )
                        run.font.color.rgb = RGBColor(r, g, b)

            # Apply paragraph-level formatting
            fmt = para.paragraph_format
            if entry.get("space_before_pt") is not None:
                fmt.space_before = Pt(entry["space_before_pt"])
            if entry.get("space_after_pt") is not None:
                fmt.space_after = Pt(entry["space_after_pt"])
            if entry.get("line_spacing") is not None:
                try:
                    fmt.line_spacing = float(entry["line_spacing"])
                except (TypeError, ValueError):
                    pass

            align_str = str(entry.get("alignment") or "")
            _align_map = {
                "WD_ALIGN_PARAGRAPH.LEFT": WD_ALIGN_PARAGRAPH.LEFT,
                "WD_ALIGN_PARAGRAPH.CENTER": WD_ALIGN_PARAGRAPH.CENTER,
                "WD_ALIGN_PARAGRAPH.RIGHT": WD_ALIGN_PARAGRAPH.RIGHT,
                "WD_ALIGN_PARAGRAPH.JUSTIFY": WD_ALIGN_PARAGRAPH.JUSTIFY,
                "left": WD_ALIGN_PARAGRAPH.LEFT,
                "center": WD_ALIGN_PARAGRAPH.CENTER,
                "right": WD_ALIGN_PARAGRAPH.RIGHT,
                "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
            }
            if align_str in _align_map:
                fmt.alignment = _align_map[align_str]

        except Exception as exc:
            log.debug("docx.apply_sidecar_style_failed", content=content[:40], reason=str(exc))
```

- [ ] **Step 5: Update table style lookup similarly**

Find the table export section in docx_handler that uses `elem.content_hash` for sidecar lookup (around lines 714-727). Update it to use the occurrence tracker:

```python
        # In the TABLE branch of the export loop:
        if sidecar:
            elements_map = sidecar.get("elements", {})
            tracker = getattr(self, "_sidecar_tracker", None)
            if tracker is None:
                tracker = OccurrenceTracker()
                self._sidecar_tracker = tracker
            entry = resolve_sidecar_entry(elements_map, elem.content, tracker)
            if entry and entry.get("type") == "table":
                col_widths = entry.get("column_widths_pt", [])
                # ... existing column width application code ...
```

Note: `resolve_sidecar_entry` expects a string for `content_text`. For tables, `elem.content` is a list. The `_strip_md_markers` function will `str()` it, and `compute_content_hash` handles lists natively. This works because the table hash in the sidecar was computed from the same list representation.

- [ ] **Step 6: Remove the now-unused `_plain_text_hash` function**

The `_plain_text_hash` function at lines 124-135 is now replaced by `sidecar_match._strip_md_markers` + `compute_content_hash`. Check if anything else uses it:

Run: `grep -n "_plain_text_hash" formats/docx_handler.py`

If only used in `_apply_sidecar_style` (which we just replaced), delete the function. If used elsewhere, keep it.

- [ ] **Step 7: Run tests**

Run: `docker exec markflow-app python -m pytest tests/test_roundtrip.py tests/test_sidecar_match.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add formats/docx_handler.py
git commit -m "feat(C1-a): wire docx export to occurrence-aware sidecar lookup"
```

---

### Task 7: PPTX Handler — Occurrence Counting

**Files:**
- Modify: `formats/pptx_handler.py:516-581`

The PPTX handler also uses `compute_content_hash` for slide-title keying. Apply the same occurrence-counting pattern.

- [ ] **Step 1: Update `_extract_styles_impl` in pptx_handler.py**

Replace the hash-keying block (around lines 576-579):

```python
        # Before (old):
        #     h = compute_content_hash(title)
        #     styles[h] = {"layout_index": slide_style.get("layout_index", 1)}

        # After (new) — add at the top of _extract_styles_impl, after line 517:
        from collections import Counter
        _hash_counter: Counter[str] = Counter()

        # Then replace lines 576-579:
            title = self._get_slide_title(slide, idx + 1)
            h = compute_content_hash(title)
            n = _hash_counter[h]
            _hash_counter[h] += 1
            styles[f"{h}:{n}"] = {"layout_index": slide_style.get("layout_index", 1)}
```

- [ ] **Step 2: Run PPTX tests**

Run: `docker exec markflow-app python -m pytest tests/test_pptx_handler.py tests/test_pptx.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add formats/pptx_handler.py
git commit -m "feat(C1-a): occurrence-indexed keys in PPTX style extraction"
```

---

### Task 8: Integration Roundtrip Tests

**Files:**
- Modify: `tests/test_roundtrip.py`

Add the remaining integration tests: v1 backward compatibility and fuzzy-match round-trip.

- [ ] **Step 1: Add v1 backward compatibility roundtrip test**

Append to `tests/test_roundtrip.py`:

```python
def test_v1_sidecar_backward_compat(tmp_path, md_handler, docx_handler):
    """A v1 sidecar (bare hash keys) still applies styles after auto-migration."""
    from core.document_model import compute_content_hash

    md_text = "# Title\n\nHello world paragraph.\n\nAnother paragraph.\n"
    md_path = tmp_path / "v1test.md"
    md_path.write_text(md_text, encoding="utf-8")

    h = compute_content_hash("Hello world paragraph.")
    v1_sidecar = {
        "schema_version": "1.0.0",
        "source_format": "docx",
        "source_file": "test.docx",
        "converted_at": "2026-01-01T00:00:00Z",
        "document_level": {},
        "elements": {
            h: {"type": "paragraph", "bold": True, "font_size_pt": 16},
        },
    }

    # Write v1 sidecar, load it (triggers migration), pass to export
    sidecar_path = tmp_path / "v1test.styles.json"
    sidecar_path.write_text(json.dumps(v1_sidecar), encoding="utf-8")

    from core.metadata import load_sidecar
    sidecar = load_sidecar(sidecar_path)

    model = md_handler.ingest(md_path)
    out = tmp_path / "v1test_out.docx"
    docx_handler.export(model, out, sidecar=sidecar)

    from docx import Document as _Doc
    doc = _Doc(str(out))
    hello_paras = [p for p in doc.paragraphs if "Hello world" in p.text]
    assert len(hello_paras) >= 1
    assert hello_paras[0].runs[0].font.bold is True


def test_fuzzy_match_on_minor_edit(tmp_path, docx_handler, md_handler):
    """Lightly editing a paragraph in markdown still picks up the sidecar style."""
    from docx import Document as _Doc
    from docx.shared import Pt

    # Build source DOCX
    doc = _Doc()
    doc.add_heading("Report", level=1)
    p = doc.add_paragraph()
    r = p.add_run("The quarterly results show a significant improvement over last year")
    r.font.bold = True
    r.font.size = Pt(12)

    docx_path = tmp_path / "fuzzy_src.docx"
    doc.save(str(docx_path))

    # Extract styles
    model = docx_handler.ingest(docx_path)
    style_data = docx_handler.extract_styles(docx_path)
    sidecar = generate_sidecar(model, style_data)

    # Convert to markdown, then lightly edit (~8% change)
    md_path = tmp_path / "fuzzy.md"
    md_handler.export(model, md_path)
    md_text = md_path.read_text(encoding="utf-8")
    edited = md_text.replace(
        "significant improvement",
        "notable improvement",
    )
    md_path.write_text(edited, encoding="utf-8")

    # Round-trip back to DOCX
    model2 = md_handler.ingest(md_path)
    out = tmp_path / "fuzzy_out.docx"
    docx_handler.export(model2, out, sidecar=sidecar)

    # The edited paragraph should still get bold from fuzzy match
    out_doc = _Doc(str(out))
    result_paras = [p for p in out_doc.paragraphs if "notable improvement" in p.text]
    assert len(result_paras) >= 1
    if result_paras[0].runs:
        assert result_paras[0].runs[0].font.bold is True
```

- [ ] **Step 2: Run all tests**

Run: `docker exec markflow-app python -m pytest tests/test_roundtrip.py tests/test_sidecar_match.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_roundtrip.py
git commit -m "test(C1-a): integration tests for v1 compat and fuzzy-match round-trip"
```

---

### Task 9: Cleanup and Final Verification

**Files:**
- Verify: all modified files
- Run: full test suite

- [ ] **Step 1: Run the full test suite**

Run: `docker exec markflow-app python -m pytest tests/ -v --timeout=120 -x 2>&1 | tail -30`
Expected: ALL PASS, no regressions

- [ ] **Step 2: Verify sidecar structure manually**

Run a quick smoke test to see the actual sidecar output:

```bash
docker exec markflow-app python -c "
from formats.docx_handler import DocxHandler
from core.metadata import generate_sidecar
import json

h = DocxHandler()
# Use any existing test fixture
from pathlib import Path
p = Path('tests/fixtures/simple.docx')
if p.exists():
    model = h.ingest(p)
    styles = h.extract_styles(p)
    sidecar = generate_sidecar(model, styles)
    print(json.dumps(sidecar, indent=2, default=str)[:2000])
"
```

Verify:
- `schema_version` is `"2.0.0"`
- Element keys have `:{n}` suffix
- Paragraph entries have `_text` field
- `document_level` is unchanged

- [ ] **Step 3: Commit any final fixes**

If Step 1 or 2 revealed issues, fix and commit.

---

## STOP: Human Checkpoint Required

**Before proceeding to M5 (PPTX chart extraction) or C5 (OCR signals):**

C1-a rewrites the sidecar schema. Review the changes above, especially:
1. The `_text` field in sidecar entries (storage impact)
2. The fuzzy-match threshold (0.90 ratio ≈ ≤10% edit distance)
3. The v1→v2 migration path
4. That existing sidecars on disk will be auto-migrated on load (not rewritten)

Confirm before continuing with the rest of Batch 2.
