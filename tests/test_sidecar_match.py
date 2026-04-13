"""Tests for core.sidecar_match — occurrence-aware sidecar lookup with fuzzy fallback."""

import json

import pytest

from core.document_model import DocumentModel, DocumentMetadata, compute_content_hash
from core.metadata import (
    generate_sidecar,
    load_sidecar,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
)
from core.sidecar_match import (
    OccurrenceTracker,
    _normalize,
    _strip_md_markers,
    resolve_sidecar_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(**kwargs) -> dict:
    """Build a minimal sidecar element dict."""
    return {"font_name": "Arial", "font_size": 12, **kwargs}


def _hash(text: str) -> str:
    """Compute the content hash the same way the module does (strip md, then hash)."""
    plain = _strip_md_markers(text)
    return compute_content_hash(plain)


# ===========================================================================
# TestExactMatch — v2 keyed lookups ({hash}:{n})
# ===========================================================================

class TestExactMatch:
    """v2 occurrence-keyed lookups."""

    def test_first_occurrence_matches_hash_0(self):
        text = "Hello World"
        h = _hash(text)
        entry = _make_entry(bold=True)
        elements = {f"{h}:0": entry}

        tracker = OccurrenceTracker()
        result = resolve_sidecar_entry(elements, text, tracker)
        assert result is entry

    def test_second_occurrence_matches_hash_1(self):
        text = "Repeated paragraph"
        h = _hash(text)
        entry0 = _make_entry(bold=False)
        entry1 = _make_entry(bold=True)
        elements = {f"{h}:0": entry0, f"{h}:1": entry1}

        tracker = OccurrenceTracker()
        # First call consumes occurrence 0
        r0 = resolve_sidecar_entry(elements, text, tracker)
        assert r0 is entry0
        # Second call consumes occurrence 1
        r1 = resolve_sidecar_entry(elements, text, tracker)
        assert r1 is entry1

    def test_different_hashes_tracked_independently(self):
        text_a = "Alpha paragraph"
        text_b = "Beta paragraph"
        h_a = _hash(text_a)
        h_b = _hash(text_b)
        entry_a = _make_entry(italic=True)
        entry_b = _make_entry(italic=False)
        elements = {f"{h_a}:0": entry_a, f"{h_b}:0": entry_b}

        tracker = OccurrenceTracker()
        assert resolve_sidecar_entry(elements, text_a, tracker) is entry_a
        assert resolve_sidecar_entry(elements, text_b, tracker) is entry_b

    def test_overflow_returns_last_stored_entry(self):
        """More occurrences in doc than entries in sidecar -> fall back to last stored."""
        text = "Overflow text"
        h = _hash(text)
        entry0 = _make_entry(font_size=10)
        elements = {f"{h}:0": entry0}  # only one entry stored

        tracker = OccurrenceTracker()
        # First call -> :0, exact hit
        assert resolve_sidecar_entry(elements, text, tracker) is entry0
        # Second call -> :1, overflow -> should fall back to :0
        assert resolve_sidecar_entry(elements, text, tracker) is entry0

    def test_no_match_returns_none(self):
        elements = {}
        tracker = OccurrenceTracker()
        assert resolve_sidecar_entry(elements, "No such content", tracker) is None


# ===========================================================================
# TestV1Compat — bare hash fallback
# ===========================================================================

class TestV1Compat:
    """Bare hash (no :N suffix) backward compatibility."""

    def test_bare_hash_matches(self):
        text = "Legacy paragraph"
        h = _hash(text)
        entry = _make_entry(underline=True)
        elements = {h: entry}  # v1 style — no occurrence suffix

        tracker = OccurrenceTracker()
        assert resolve_sidecar_entry(elements, text, tracker) is entry

    def test_v2_preferred_over_bare_hash(self):
        text = "Dual keyed"
        h = _hash(text)
        entry_v1 = _make_entry(font_size=11)
        entry_v2 = _make_entry(font_size=14)
        elements = {h: entry_v1, f"{h}:0": entry_v2}

        tracker = OccurrenceTracker()
        result = resolve_sidecar_entry(elements, text, tracker)
        assert result is entry_v2, "v2 key should take priority over bare hash"


# ===========================================================================
# TestFuzzyMatch — normalized Levenshtein ratio >= 0.90
# ===========================================================================

class TestFuzzyMatch:
    """Fuzzy text fallback via _text field."""

    def test_minor_edit_matches(self):
        original = "The quick brown fox jumps over the lazy dog"
        # ~5% edit: "jumps" -> "leaps" (5 chars changed out of 43)
        similar = "The quick brown fox leaps over the lazy dog"
        entry = _make_entry(_text=_normalize(original))
        elements = {"unrelated_key": entry}

        tracker = OccurrenceTracker()
        result = resolve_sidecar_entry(elements, similar, tracker)
        assert result is entry

    def test_major_edit_returns_none(self):
        original = "Hello World"
        very_different = "Completely unrelated sentence about nothing"
        entry = _make_entry(_text=_normalize(original))
        elements = {"some_key": entry}

        tracker = OccurrenceTracker()
        result = resolve_sidecar_entry(elements, very_different, tracker)
        assert result is None

    def test_entries_without_text_skipped(self):
        entry_no_text = _make_entry()  # no _text field
        elements = {"k1": entry_no_text}

        tracker = OccurrenceTracker()
        result = resolve_sidecar_entry(elements, "Anything", tracker)
        assert result is None

    def test_best_match_wins(self):
        target = "The quick brown fox jumps over the lazy dog"
        # "distant" differs by many chars -> lower ratio
        distant = _make_entry(_text=_normalize("The slow brown fox leaps across a lazy dog"))
        # "close" differs by only one word -> higher ratio
        close = _make_entry(_text=_normalize("The quick brown fox jumps over the lazy cat"))
        elements = {"k1": distant, "k2": close}

        tracker = OccurrenceTracker()
        result = resolve_sidecar_entry(elements, target, tracker)
        assert result is close


# ===========================================================================
# TestMarkdownStripping — inline marker removal before hashing
# ===========================================================================

class TestMarkdownStripping:
    """Markdown markers are stripped before content hashing."""

    def test_bold_markers_stripped(self):
        plain = "Important text"
        marked = "**Important text**"
        # Both should produce the same hash
        assert _hash(marked) == compute_content_hash(plain)

        h = _hash(plain)
        entry = _make_entry(bold=True)
        elements = {f"{h}:0": entry}

        tracker = OccurrenceTracker()
        # Lookup with markdown-marked text should still find the entry
        assert resolve_sidecar_entry(elements, marked, tracker) is entry

    def test_italic_markers_stripped(self):
        plain = "Emphasized text"
        marked = "*Emphasized text*"
        assert _hash(marked) == compute_content_hash(plain)

        h = _hash(plain)
        entry = _make_entry(italic=True)
        elements = {f"{h}:0": entry}

        tracker = OccurrenceTracker()
        assert resolve_sidecar_entry(elements, marked, tracker) is entry

    def test_code_markers_stripped(self):
        plain = "some_function()"
        marked = "`some_function()`"
        assert _hash(marked) == compute_content_hash(plain)

        h = _hash(plain)
        entry = _make_entry(monospace=True)
        elements = {f"{h}:0": entry}

        tracker = OccurrenceTracker()
        assert resolve_sidecar_entry(elements, marked, tracker) is entry

    def test_mixed_markers_stripped(self):
        plain = "Bold and code mixed"
        marked = "**Bold** and `code` mixed"
        # After stripping: "Bold and code mixed"
        assert _hash(marked) == compute_content_hash(plain)


# ===========================================================================
# TestOccurrenceTracker — unit tests for the counter
# ===========================================================================

class TestOccurrenceTracker:
    """OccurrenceTracker counts per-hash independently."""

    def test_starts_at_zero(self):
        tracker = OccurrenceTracker()
        assert tracker.next("abc") == 0

    def test_increments(self):
        tracker = OccurrenceTracker()
        assert tracker.next("abc") == 0
        assert tracker.next("abc") == 1
        assert tracker.next("abc") == 2

    def test_independent_keys(self):
        tracker = OccurrenceTracker()
        assert tracker.next("a") == 0
        assert tracker.next("b") == 0
        assert tracker.next("a") == 1
        assert tracker.next("b") == 1


# ===========================================================================
# TestNormalize and TestStripMdMarkers — internal helpers
# ===========================================================================

class TestNormalize:
    def test_collapses_whitespace(self):
        assert _normalize("  hello   world  ") == "hello world"

    def test_lowercases(self):
        assert _normalize("Hello WORLD") == "hello world"

    def test_handles_newlines(self):
        assert _normalize("line1\n  line2\tline3") == "line1 line2 line3"


class TestStripMdMarkers:
    def test_bold(self):
        assert _strip_md_markers("**bold**") == "bold"

    def test_italic(self):
        assert _strip_md_markers("*italic*") == "italic"

    def test_bold_italic(self):
        assert _strip_md_markers("***both***") == "both"

    def test_code(self):
        assert _strip_md_markers("`code`") == "code"

    def test_no_markers(self):
        assert _strip_md_markers("plain text") == "plain text"

    def test_mixed(self):
        assert _strip_md_markers("**bold** and *italic* and `code`") == "bold and italic and code"


# ===========================================================================
# TestSchemaMigration — v1 → v2 sidecar auto-migration
# ===========================================================================


class TestSchemaMigration:
    def test_schema_version_is_2(self):
        assert SCHEMA_VERSION == "2.0.0"

    def test_v1_supported(self):
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
        assert "abc123" not in loaded["elements"]
        assert "xyz789" not in loaded["elements"]
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
        """generate_sidecar produces v2 schema version."""
        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file="test.docx",
            source_format="docx",
        )
        style_data = {
            "document_level": {"margin_top_pt": 72.0},
            "abc123:0": {"type": "paragraph", "bold": True},
            "abc123:1": {"type": "paragraph", "bold": False},
        }
        sidecar = generate_sidecar(model, style_data)
        assert sidecar["schema_version"] == "2.0.0"
        assert "abc123:0" in sidecar["elements"]
        assert "abc123:1" in sidecar["elements"]
