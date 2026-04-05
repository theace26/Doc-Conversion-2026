"""
Tests for core.vector.chunker — markdown chunker with contextual headers.

Coverage
--------
- Contextual headers present (document title + section path) on every chunk
- Metadata (doc_id, doc_title, source_path) carried through to each chunk
- Structural splitting on H1 / H2 / H3 headings
- Large sections (>1600 chars) are subdivided
- Small adjacent sections (<200 chars) are merged
- Empty / frontmatter-only content returns empty list
- Sequential chunk_index values starting at 0
- YAML frontmatter stripped before processing
- Heading hierarchy is reflected in heading_path (parent > child)
"""

import pytest

from core.vector.chunker import Chunk, chunk_markdown, LARGE_SECTION_CHARS, SMALL_SECTION_CHARS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_large_text(n_chars: int = LARGE_SECTION_CHARS + 200) -> str:
    """Return a blob of prose exceeding *n_chars* characters."""
    sentence = "The quick brown fox jumps over the lazy dog. "
    repeats = (n_chars // len(sentence)) + 2
    return (sentence * repeats)[:n_chars]


# ---------------------------------------------------------------------------
# Basic smoke test
# ---------------------------------------------------------------------------

class TestBasicChunking:
    def test_returns_list_of_chunks(self):
        md = "# Title\n\nSome content here."
        result = chunk_markdown(md, doc_title="My Doc")
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(c, Chunk) for c in result)

    def test_empty_string_returns_empty_list(self):
        assert chunk_markdown("", doc_title="Empty") == []

    def test_whitespace_only_returns_empty_list(self):
        assert chunk_markdown("   \n\n  ", doc_title="Blank") == []


# ---------------------------------------------------------------------------
# YAML frontmatter stripping
# ---------------------------------------------------------------------------

class TestFrontmatterStripping:
    def test_frontmatter_stripped(self):
        md = "---\ntitle: Test Doc\nauthor: Alice\ndate: 2026-01-01\n---\n\n# Intro\n\nHello world."
        chunks = chunk_markdown(md, doc_title="Test Doc")
        assert chunks, "Expected at least one chunk"
        # Frontmatter keys should not appear in any chunk text
        for chunk in chunks:
            assert "author: Alice" not in chunk.text
            assert "date: 2026-01-01" not in chunk.text

    def test_frontmatter_with_dotdotdot_terminator(self):
        md = "---\ntitle: Doc\n...\n\n# Body\n\nContent here."
        chunks = chunk_markdown(md, doc_title="Doc")
        assert chunks
        for chunk in chunks:
            assert "title: Doc" not in chunk.text

    def test_no_frontmatter_still_works(self):
        md = "# Just a heading\n\nPlain content."
        chunks = chunk_markdown(md, doc_title="Plain")
        assert len(chunks) >= 1

    def test_frontmatter_only_returns_empty_list(self):
        md = "---\ntitle: Nothing\n---\n"
        result = chunk_markdown(md, doc_title="Nothing")
        assert result == []


# ---------------------------------------------------------------------------
# Contextual headers
# ---------------------------------------------------------------------------

class TestContextualHeaders:
    def test_document_title_in_every_chunk(self):
        md = "# Section One\n\nContent A.\n\n## Section Two\n\nContent B."
        chunks = chunk_markdown(md, doc_title="My Report")
        assert chunks
        for chunk in chunks:
            assert "[Document: My Report]" in chunk.text

    def test_section_heading_in_chunk(self):
        md = "# Introduction\n\nSome introductory text here."
        chunks = chunk_markdown(md, doc_title="Report")
        assert chunks
        # The heading should appear in the Section line
        assert any("[Section: Introduction]" in c.text for c in chunks)

    def test_header_format(self):
        """Header must follow: [Document: X]\n[Section: Y]\n\n{content}"""
        md = "# Alpha\n\nBody text."
        chunks = chunk_markdown(md, doc_title="Test")
        c = chunks[0]
        assert c.text.startswith("[Document: Test]\n[Section:")
        assert "\n\n" in c.text  # blank line between header and body

    def test_no_section_header_when_no_heading(self):
        """Text before any heading should not get a [Section: ] line."""
        md = "Preamble text with no heading above it."
        chunks = chunk_markdown(md, doc_title="Doc")
        assert chunks
        preamble_chunk = chunks[0]
        assert "[Document: Doc]" in preamble_chunk.text
        assert "[Section:]" not in preamble_chunk.text

    def test_heading_hierarchy_in_path(self):
        """H3 under H2 under H1 must produce 'H1 > H2 > H3' path."""
        # Use content large enough to avoid small-section merging
        body = "A" * 250
        md = (
            f"# Chapter One\n\n{body}\n\n"
            f"## Overview\n\n{body}\n\n"
            f"### Details\n\n{body}"
        )
        chunks = chunk_markdown(md, doc_title="Book")
        paths = [c.heading_path for c in chunks]
        assert any("Chapter One > Overview > Details" in p for p in paths)

    def test_h2_path_does_not_include_sibling_h1(self):
        """An H2 after an H1 should include the H1 in its path."""
        body = "A" * 250
        md = f"# Parent\n\n{body}\n\n## Child\n\n{body}"
        chunks = chunk_markdown(md, doc_title="Doc")
        child_chunks = [c for c in chunks if "Child" in c.heading_path]
        assert child_chunks
        assert all("Parent > Child" in c.heading_path for c in child_chunks)


# ---------------------------------------------------------------------------
# Metadata propagation
# ---------------------------------------------------------------------------

class TestMetadataPropagation:
    def test_doc_id_on_all_chunks(self):
        md = "# A\n\nText A.\n\n# B\n\nText B."
        chunks = chunk_markdown(md, doc_title="Doc", doc_id="abc-123")
        assert all(c.doc_id == "abc-123" for c in chunks)

    def test_doc_title_on_all_chunks(self):
        md = "# Section\n\nContent."
        chunks = chunk_markdown(md, doc_title="Peninsula Contract", doc_id="x")
        assert all(c.doc_title == "Peninsula Contract" for c in chunks)

    def test_source_path_on_all_chunks(self):
        md = "# Wage Schedule\n\nRates here."
        chunks = chunk_markdown(
            md, doc_title="Contract", doc_id="y", source_path="/mnt/source/contract.md"
        )
        assert all(c.source_path == "/mnt/source/contract.md" for c in chunks)

    def test_heading_path_field_matches_section_line(self):
        md = "# Rates\n\nSome rate info."
        chunks = chunk_markdown(md, doc_title="Doc")
        for chunk in chunks:
            if chunk.heading_path:
                assert f"[Section: {chunk.heading_path}]" in chunk.text


# ---------------------------------------------------------------------------
# Sequential chunk_index
# ---------------------------------------------------------------------------

class TestChunkIndex:
    def test_indices_sequential_from_zero(self):
        md = "\n\n".join(f"# Section {i}\n\nContent {i}." for i in range(5))
        chunks = chunk_markdown(md, doc_title="Doc")
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_single_chunk_index_is_zero(self):
        md = "# Only\n\nJust one section."
        chunks = chunk_markdown(md, doc_title="Doc")
        assert chunks[0].chunk_index == 0


# ---------------------------------------------------------------------------
# Structural splitting on headings
# ---------------------------------------------------------------------------

class TestHeadingSplit:
    def test_two_h1_sections_produce_separate_chunks(self):
        # Body content must exceed SMALL_SECTION_CHARS to prevent merging
        body = "A" * 250
        md = f"# Alpha\n\n{body}\n\n# Beta\n\n{body}"
        chunks = chunk_markdown(md, doc_title="Doc")
        paths = [c.heading_path for c in chunks]
        assert any("Alpha" in p for p in paths)
        assert any("Beta" in p for p in paths)

    def test_h2_splits_within_h1(self):
        body = "A" * 250
        md = (
            f"# Chapter\n\n{body}\n\n"
            f"## Part One\n\n{body}\n\n"
            f"## Part Two\n\n{body}"
        )
        chunks = chunk_markdown(md, doc_title="Book")
        paths = [c.heading_path for c in chunks]
        assert any("Part One" in p for p in paths)
        assert any("Part Two" in p for p in paths)

    def test_h3_splits_within_h2(self):
        body = "A" * 250
        md = (
            f"## Overview\n\n{body}\n\n"
            f"### Sub A\n\n{body}\n\n"
            f"### Sub B\n\n{body}"
        )
        chunks = chunk_markdown(md, doc_title="Spec")
        paths = [c.heading_path for c in chunks]
        assert any("Sub A" in p for p in paths)
        assert any("Sub B" in p for p in paths)


# ---------------------------------------------------------------------------
# Large section subdivision
# ---------------------------------------------------------------------------

class TestLargeSectionSubdivision:
    def test_large_section_produces_multiple_chunks(self):
        large_body = _make_large_text(LARGE_SECTION_CHARS * 3)
        md = f"# Big Section\n\n{large_body}"
        chunks = chunk_markdown(md, doc_title="Doc")
        big_section_chunks = [c for c in chunks if "Big Section" in c.heading_path]
        assert len(big_section_chunks) > 1

    def test_sub_chunks_all_have_same_heading_path(self):
        large_body = _make_large_text(LARGE_SECTION_CHARS * 2)
        md = f"# Wages\n\n{large_body}"
        chunks = chunk_markdown(md, doc_title="Contract")
        wage_chunks = [c for c in chunks if "Wages" in c.heading_path]
        assert all(c.heading_path == "Wages" for c in wage_chunks)

    def test_sub_chunks_contain_document_header(self):
        large_body = _make_large_text(LARGE_SECTION_CHARS * 2)
        md = f"# Rates\n\n{large_body}"
        chunks = chunk_markdown(md, doc_title="Schedule")
        rate_chunks = [c for c in chunks if "Rates" in c.heading_path]
        for c in rate_chunks:
            assert "[Document: Schedule]" in c.text

    def test_no_chunk_body_exceeds_double_target(self):
        """No chunk content should be excessively large."""
        large_body = _make_large_text(LARGE_SECTION_CHARS * 4)
        md = f"# Section\n\n{large_body}"
        chunks = chunk_markdown(md, doc_title="Doc")
        for c in chunks:
            # Allow for header overhead; body itself should be bounded
            assert len(c.text) < LARGE_SECTION_CHARS * 2 + 300


# ---------------------------------------------------------------------------
# Small section merging
# ---------------------------------------------------------------------------

class TestSmallSectionMerging:
    def test_two_small_sections_merged(self):
        # Each section body < SMALL_SECTION_CHARS
        small_a = "Short text A."
        small_b = "Short text B."
        assert len(small_a) < SMALL_SECTION_CHARS
        assert len(small_b) < SMALL_SECTION_CHARS

        md = f"# Alpha\n\n{small_a}\n\n# Beta\n\n{small_b}"
        chunks = chunk_markdown(md, doc_title="Doc")
        # Both small bodies should end up in a single chunk
        all_text = " ".join(c.text for c in chunks)
        assert "Short text A" in all_text
        assert "Short text B" in all_text
        # After merging, we expect fewer chunks than headings
        assert len(chunks) < 3

    def test_large_section_not_merged_with_small(self):
        large_body = _make_large_text(LARGE_SECTION_CHARS + 100)
        small_body = "Tiny text."
        md = f"# Big\n\n{large_body}\n\n# Tiny\n\n{small_body}"
        chunks = chunk_markdown(md, doc_title="Doc")
        # Big section should be present (possibly split), tiny may be standalone
        big_chunks = [c for c in chunks if "Big" in c.heading_path]
        assert big_chunks

    def test_merged_chunk_contains_both_bodies(self):
        md = "# X\n\nFoo bar.\n\n# Y\n\nBaz qux."
        chunks = chunk_markdown(md, doc_title="Doc")
        combined = " ".join(c.text for c in chunks)
        assert "Foo bar" in combined
        assert "Baz qux" in combined


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_document_with_only_headings_no_body(self):
        md = "# Heading One\n\n## Heading Two\n\n### Heading Three"
        # Should not raise; result may be empty or contain empty sections
        result = chunk_markdown(md, doc_title="Outline")
        assert isinstance(result, list)

    def test_content_before_first_heading(self):
        md = "Preamble paragraph.\n\n# First Section\n\nSection body."
        chunks = chunk_markdown(md, doc_title="Doc")
        texts = " ".join(c.text for c in chunks)
        assert "Preamble paragraph" in texts

    def test_empty_doc_id_and_source_path_defaults(self):
        md = "# Test\n\nContent."
        chunks = chunk_markdown(md, doc_title="Doc")
        assert all(c.doc_id == "" for c in chunks)
        assert all(c.source_path == "" for c in chunks)

    def test_special_characters_in_title(self):
        md = "# Section\n\nContent with special chars: $45/hr & more."
        chunks = chunk_markdown(md, doc_title="Peninsula Contract (2026)")
        assert chunks
        assert all("[Document: Peninsula Contract (2026)]" in c.text for c in chunks)

    def test_real_world_contextual_example(self):
        """Reproduce the motivating example from the task description."""
        # Pad Electrician Rates section beyond SMALL_SECTION_CHARS so it is
        # not merged with its sibling, ensuring it keeps its own heading path.
        rates_body = "The rate is $45/hr for journeyman electricians. " * 6
        md = (
            "# Wage Schedule\n\n"
            "This schedule covers all trade classifications.\n\n"
            f"## Electrician Rates\n\n{rates_body}"
        )
        chunks = chunk_markdown(md, doc_title="Peninsula Contract", doc_id="pen-001")
        assert chunks
        rate_chunks = [c for c in chunks if "Electrician Rates" in c.heading_path]
        assert rate_chunks, "Expected a chunk with Electrician Rates in heading_path"
        c = rate_chunks[0]
        assert "[Document: Peninsula Contract]" in c.text
        assert "Wage Schedule" in c.heading_path
        assert "Electrician Rates" in c.heading_path
        assert "$45/hr" in c.text
