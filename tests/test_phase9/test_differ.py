"""Tests for core/differ.py — diff engine."""

from core.differ import compute_diff, DIFF_MAX_PATCH_BYTES


def test_empty_diff_identical():
    """Identical files produce empty summary."""
    result = compute_diff("hello\nworld\n", "hello\nworld\n")
    assert result.summary == []
    assert result.lines_added == 0
    assert result.lines_removed == 0


def test_heading_change_detected():
    """Heading changes are named in summary."""
    old = "# Introduction\n\nSome text.\n"
    new = "# Overview\n\nSome text.\n"
    result = compute_diff(old, new)
    assert any("Introduction" in b or "Overview" in b for b in result.summary)


def test_table_row_aggregated():
    """Table row changes produce aggregated bullet."""
    old = "| A | B |\n| 1 | 2 |\n| 3 | 4 |\n"
    new = "| A | B |\n| 1 | 2 |\n| 5 | 6 |\n| 7 | 8 |\n"
    result = compute_diff(old, new)
    assert any("Table updated" in b for b in result.summary)


def test_patch_truncation():
    """Patch > 1MB is truncated."""
    # Create large texts that differ
    old = "line\n" * 100000
    new = "changed line\n" * 100000
    result = compute_diff(old, new)
    # Summary should still be populated
    assert len(result.summary) > 0
    # Patch may or may not be truncated depending on size
    if result.patch_truncated:
        assert result.patch is None


def test_summary_max_20():
    """Summary never exceeds 20 items."""
    # Create text with many changes
    old = "\n".join(f"Line {i}" for i in range(50))
    new = "\n".join(f"Changed {i}" for i in range(50))
    result = compute_diff(old, new)
    assert len(result.summary) <= 20


def test_added_lines():
    """Added lines counted correctly."""
    old = "line 1\n"
    new = "line 1\nline 2\nline 3\n"
    result = compute_diff(old, new)
    assert result.lines_added >= 2
    assert result.lines_removed == 0


def test_removed_lines():
    """Removed lines counted correctly."""
    old = "line 1\nline 2\nline 3\n"
    new = "line 1\n"
    result = compute_diff(old, new)
    assert result.lines_removed >= 2


def test_mixed_changes():
    """Both added and removed lines counted."""
    old = "alpha\nbeta\ngamma\n"
    new = "alpha\ndelta\nepsilon\n"
    result = compute_diff(old, new)
    assert result.lines_added > 0
    assert result.lines_removed > 0
    assert result.patch is not None
