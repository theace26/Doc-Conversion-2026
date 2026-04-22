"""Unit tests for Storage Manager (path validation, write guard, config)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest


# ── Path validation ──────────────────────────────────────────────────────────


def test_validate_missing_path(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path(str(tmp_path / "nonexistent"), PathRole.SOURCE))
    assert not result.ok
    assert any("doesn't exist" in e for e in result.errors)


def test_validate_empty_string_rejected() -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path("", PathRole.SOURCE))
    assert not result.ok


def test_validate_file_not_directory(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    f = tmp_path / "not-a-dir.txt"
    f.write_text("hi")
    result = asyncio.run(validate_path(str(f), PathRole.SOURCE))
    assert not result.ok
    assert any("file, not a folder" in e for e in result.errors)


def test_validate_readable_source(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    # Add a child so the empty-folder warning doesn't fire (it's a separate test)
    (tmp_path / "child.txt").write_text("x")
    result = asyncio.run(validate_path(str(tmp_path), PathRole.SOURCE))
    assert result.ok


def test_validate_empty_folder_warns(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path(str(tmp_path), PathRole.SOURCE))
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)


def test_validate_writable_output(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path(str(tmp_path), PathRole.OUTPUT))
    assert result.ok
    assert "free_space_bytes" in result.stats


def test_validate_same_path_rejected() -> None:
    from core.storage_manager import check_source_output_conflict
    errors = check_source_output_conflict("/a/b", "/a/b")
    assert any("same folder" in e.lower() for e in errors)


def test_validate_nested_path_rejected() -> None:
    from core.storage_manager import check_source_output_conflict
    errors = check_source_output_conflict("/a", "/a/sub")
    assert any("inside" in e.lower() for e in errors)


def test_validate_reverse_nested_path_rejected() -> None:
    """Source inside output is also a loop hazard."""
    from core.storage_manager import check_source_output_conflict
    errors = check_source_output_conflict("/a/sub", "/a")
    assert any("inside" in e.lower() for e in errors)


def test_validate_unrelated_paths_ok() -> None:
    from core.storage_manager import check_source_output_conflict
    assert check_source_output_conflict("/a", "/b") == []


def test_long_path_warns() -> None:
    from core.storage_manager import _warn_long_path
    assert _warn_long_path("/a" * 200) is not None
    assert _warn_long_path("/short") is None


# ── Write guard ──────────────────────────────────────────────────────────────


def test_write_allowed_inside_output(monkeypatch, tmp_path: Path) -> None:
    from core import storage_manager as sm
    sm.set_output_path(str(tmp_path))
    assert sm.is_write_allowed(str(tmp_path / "sub" / "file.md"))


def test_write_allowed_at_output_root(monkeypatch, tmp_path: Path) -> None:
    from core import storage_manager as sm
    sm.set_output_path(str(tmp_path))
    assert sm.is_write_allowed(str(tmp_path))


def test_write_denied_outside_output(monkeypatch, tmp_path: Path) -> None:
    from core import storage_manager as sm
    sm.set_output_path(str(tmp_path))
    assert not sm.is_write_allowed("/etc/passwd")


def test_write_denied_when_no_output_configured() -> None:
    from core import storage_manager as sm
    sm.set_output_path(None)
    assert not sm.is_write_allowed("/anywhere/file")


def test_write_denied_for_empty_target(tmp_path) -> None:
    from core import storage_manager as sm
    sm.set_output_path(str(tmp_path))
    assert not sm.is_write_allowed("")


def test_write_denied_for_symlink_escape(tmp_path: Path) -> None:
    from core import storage_manager as sm
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    link = output / "escape"
    link.symlink_to(outside)
    sm.set_output_path(str(output))
    # Target that resolves outside output must be denied
    assert not sm.is_write_allowed(str(link / "file.md"))


def test_write_denied_for_sibling_with_shared_prefix(tmp_path: Path) -> None:
    """`/output-other/x` must NOT be allowed when output is `/output`."""
    from core import storage_manager as sm
    output = tmp_path / "output"
    output.mkdir()
    sibling = tmp_path / "output-other"
    sibling.mkdir()
    sm.set_output_path(str(output))
    assert not sm.is_write_allowed(str(sibling / "file.md"))


def test_get_output_path_roundtrip(tmp_path: Path) -> None:
    from core import storage_manager as sm
    sm.set_output_path(str(tmp_path))
    assert sm.get_output_path() == os.path.realpath(str(tmp_path))
    sm.set_output_path(None)
    assert sm.get_output_path() is None


# ── DB-backed config persistence ─────────────────────────────────────────────


def test_storage_defaults_present() -> None:
    """Task 12 sanity: the new prefs are registered in DEFAULT_PREFERENCES."""
    from core.db.preferences import DEFAULT_PREFERENCES
    for k in (
        "storage_output_path",
        "storage_sources_json",
        "storage_exclusions_json",
        "pending_restart_reason",
        "pending_restart_since",
        "pending_restart_dismissed_until",
        "setup_wizard_dismissed",
        "host_os_override",
    ):
        assert k in DEFAULT_PREFERENCES, f"missing default preference: {k}"
