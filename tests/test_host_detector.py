"""Unit tests for host OS detection."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.host_detector import HostOS, detect_host, _detect_os_from_root


def _mkdir(root: Path, rel: str) -> None:
    (root / rel).mkdir(parents=True, exist_ok=True)


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


def test_detect_windows_native(tmp_path: Path) -> None:
    _mkdir(tmp_path, "Windows/System32")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.WINDOWS_NATIVE


def test_detect_wsl_beats_linux(tmp_path: Path) -> None:
    _mkdir(tmp_path, "mnt/c/Windows/System32")
    _touch(tmp_path, "etc/os-release")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.WSL


def test_detect_macos(tmp_path: Path) -> None:
    _mkdir(tmp_path, "Users")
    _mkdir(tmp_path, "Volumes")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.MACOS


def test_detect_linux(tmp_path: Path) -> None:
    _touch(tmp_path, "etc/os-release")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.LINUX


def test_detect_unknown(tmp_path: Path) -> None:
    assert _detect_os_from_root(str(tmp_path)) is HostOS.UNKNOWN


def test_detect_host_caches(monkeypatch, tmp_path: Path) -> None:
    _touch(tmp_path, "etc/os-release")
    monkeypatch.setattr("core.host_detector.HOST_ROOT", str(tmp_path))
    import core.host_detector as hd
    hd._cache = None  # reset
    a = detect_host()
    b = detect_host()
    assert a is b  # same cached object


def test_quick_access_windows(tmp_path: Path, monkeypatch) -> None:
    _mkdir(tmp_path, "Windows/System32")
    _mkdir(tmp_path, "Users/Alice/Documents")
    _mkdir(tmp_path, "Users/Bob")
    monkeypatch.setattr("core.host_detector.HOST_ROOT", str(tmp_path))
    import core.host_detector as hd
    hd._cache = None
    info = detect_host()
    assert info.os is HostOS.WINDOWS_NATIVE
    paths = [q.path for q in info.quick_access]
    assert any("Alice" in p for p in paths)
    assert any("Bob" in p for p in paths)
