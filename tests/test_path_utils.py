"""
Tests for core/path_utils.py — path safety utilities.

Covers:
  - map_output_path / map_output_path_renamed
  - check_path_length
  - detect_collisions / detect_case_collisions
  - resolve_collision (all strategies)
  - run_path_safety_pass
"""

import pytest
from pathlib import Path, PurePosixPath

from core.path_utils import (
    check_path_length,
    detect_case_collisions,
    detect_collisions,
    map_output_path,
    map_output_path_renamed,
    resolve_collision,
    run_path_safety_pass,
    truncate_path_diagnosis,
)


# ── map_output_path ──────────────────────────────────────────────────────────

class TestMapOutputPath:
    def test_simple_path(self):
        src = Path("/mnt/source/report.docx")
        result = map_output_path(src, Path("/mnt/source"), Path("/mnt/output"))
        assert result == Path("/mnt/output/report.md")

    def test_deeply_nested(self):
        src = Path("/mnt/source/a/b/c/d/e/f/g/h/i/j/report.pdf")
        result = map_output_path(src, Path("/mnt/source"), Path("/mnt/output"))
        assert result == Path("/mnt/output/a/b/c/d/e/f/g/h/i/j/report.md")

    def test_special_characters(self):
        src = Path("/mnt/source/dept (2)/my report [final].docx")
        result = map_output_path(src, Path("/mnt/source"), Path("/mnt/output"))
        assert result == Path("/mnt/output/dept (2)/my report [final].md")

    def test_raises_if_not_under_root(self):
        src = Path("/other/path/report.docx")
        with pytest.raises(ValueError):
            map_output_path(src, Path("/mnt/source"), Path("/mnt/output"))


# ── map_output_path_renamed ──────────────────────────────────────────────────

class TestMapOutputPathRenamed:
    def test_pdf_renamed(self):
        src = Path("/mnt/source/report.pdf")
        result = map_output_path_renamed(src, Path("/mnt/source"), Path("/mnt/output"))
        assert result == Path("/mnt/output/report.pdf.md")

    def test_docx_renamed(self):
        src = Path("/mnt/source/report.docx")
        result = map_output_path_renamed(src, Path("/mnt/source"), Path("/mnt/output"))
        assert result == Path("/mnt/output/report.docx.md")

    def test_nested_preserves_structure(self):
        src = Path("/mnt/source/dept/finance/report.xlsx")
        result = map_output_path_renamed(src, Path("/mnt/source"), Path("/mnt/output"))
        assert result == Path("/mnt/output/dept/finance/report.xlsx.md")


# ── check_path_length ────────────────────────────────────────────────────────

class TestCheckPathLength:
    def test_within_limit(self):
        path = Path("/mnt/output/" + "a" * 220 + ".md")
        assert check_path_length(path, 240) is True

    def test_at_limit(self):
        # Create a path of exactly 240 chars
        base = "/mnt/output/"
        name = "x" * (240 - len(base) - 3) + ".md"
        path = Path(base + name)
        assert len(str(path)) == 240
        assert check_path_length(path, 240) is True

    def test_over_limit(self):
        path = Path("/mnt/output/" + "a" * 230 + ".md")
        assert check_path_length(path, 240) is False

    def test_truncate_diagnosis(self):
        src = Path("/src/file.docx")
        out = Path("/output/" + "x" * 250 + ".md")
        diag = truncate_path_diagnosis(src, out, 240)
        assert diag["overage"] > 0
        assert "fewer chars" in diag["suggestion"]


# ── detect_collisions ────────────────────────────────────────────────────────

class TestDetectCollisions:
    def test_same_stem_different_ext(self):
        files = [
            Path("/src/report.docx"),
            Path("/src/report.pdf"),
        ]
        result = detect_collisions(files, Path("/src"), Path("/out"))
        assert len(result) == 1
        key = str(Path("/out/report.md"))
        assert key in result
        assert len(result[key]) == 2

    def test_different_stems_no_collision(self):
        files = [
            Path("/src/report.docx"),
            Path("/src/summary.pdf"),
        ]
        result = detect_collisions(files, Path("/src"), Path("/out"))
        assert len(result) == 0

    def test_three_files_same_stem(self):
        files = [
            Path("/src/report.docx"),
            Path("/src/report.pdf"),
            Path("/src/report.xlsx"),
        ]
        result = detect_collisions(files, Path("/src"), Path("/out"))
        assert len(result) == 1
        key = str(Path("/out/report.md"))
        assert len(result[key]) == 3

    def test_different_dirs_same_name_no_collision(self):
        files = [
            Path("/src/dept1/report.docx"),
            Path("/src/dept2/report.docx"),
        ]
        result = detect_collisions(files, Path("/src"), Path("/out"))
        assert len(result) == 0


# ── detect_case_collisions ───────────────────────────────────────────────────

class TestDetectCaseCollisions:
    def test_case_collision(self):
        files = [
            Path("/src/Report.docx"),
            Path("/src/report.docx"),
        ]
        result = detect_case_collisions(files, Path("/src"), Path("/out"))
        assert len(result) == 1

    def test_standard_collision_not_case(self):
        # Same stem different ext — standard collision, not case
        files = [
            Path("/src/Report.docx"),
            Path("/src/Report.pdf"),
        ]
        result = detect_case_collisions(files, Path("/src"), Path("/out"))
        # These produce different output paths (Report.md for both → standard collision)
        # detect_case_collisions looks for same lowercased path but different originals
        assert len(result) == 0

    def test_dir_case_collision(self):
        files = [
            Path("/src/DEPT/report.docx"),
            Path("/src/dept/report.docx"),
        ]
        result = detect_case_collisions(files, Path("/src"), Path("/out"))
        assert len(result) == 1


# ── resolve_collision ────────────────────────────────────────────────────────

class TestResolveCollision:
    def _group(self):
        return [
            Path("/src/report.docx"),
            Path("/src/report.pdf"),
        ]

    def test_rename_all_get_paths(self):
        result = resolve_collision(self._group(), Path("/src"), Path("/out"), "rename")
        assert len(result) == 2
        for src, (resolution, path) in result.items():
            assert resolution == "renamed"
            assert path is not None
            assert str(path).endswith(".md")
            # e.g. report.docx.md, report.pdf.md
            assert src.suffix + ".md" in str(path)

    def test_skip_first_kept(self):
        result = resolve_collision(self._group(), Path("/src"), Path("/out"), "skip")
        sorted_group = sorted(self._group(), key=lambda p: str(p))
        first = sorted_group[0]
        assert result[first][0] == "skipped_kept"
        assert result[first][1] is not None
        for f in sorted_group[1:]:
            assert result[f][0] == "skipped"
            assert result[f][1] is None

    def test_error_all_none(self):
        result = resolve_collision(self._group(), Path("/src"), Path("/out"), "error")
        for src, (resolution, path) in result.items():
            assert resolution == "errored"
            assert path is None

    def test_deterministic(self):
        """Same input always produces same output."""
        r1 = resolve_collision(self._group(), Path("/src"), Path("/out"), "rename")
        r2 = resolve_collision(list(reversed(self._group())), Path("/src"), Path("/out"), "rename")
        assert r1 == r2


# ── run_path_safety_pass ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_safety_pass_all_safe():
    files = [
        Path("/src/report.docx"),
        Path("/src/summary.pdf"),
    ]
    result = await run_path_safety_pass(files, Path("/src"), Path("/out"))
    assert result.safe_count == 2
    assert result.too_long_count == 0
    assert result.collision_count == 0


@pytest.mark.asyncio
async def test_safety_pass_with_collision():
    files = [
        Path("/src/report.docx"),
        Path("/src/report.pdf"),
        Path("/src/other.docx"),
    ]
    result = await run_path_safety_pass(files, Path("/src"), Path("/out"), collision_strategy="rename")
    assert result.collision_count == 2  # both files in collision group
    assert result.safe_count == 1  # other.docx


@pytest.mark.asyncio
async def test_safety_pass_with_too_long():
    long_name = "x" * 250 + ".docx"
    files = [
        Path(f"/src/{long_name}"),
        Path("/src/ok.docx"),
    ]
    result = await run_path_safety_pass(files, Path("/src"), Path("/out"), max_path_length=240)
    assert result.too_long_count == 1
    assert result.safe_count == 1


@pytest.mark.asyncio
async def test_safety_pass_resolved_paths_complete():
    """Every input file should have an entry in resolved_paths."""
    files = [
        Path("/src/a.docx"),
        Path("/src/a.pdf"),
        Path("/src/b.docx"),
    ]
    result = await run_path_safety_pass(files, Path("/src"), Path("/out"))
    assert len(result.resolved_paths) == 3
    for f in files:
        assert str(f) in result.resolved_paths
