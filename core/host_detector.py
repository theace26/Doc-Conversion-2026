"""Host OS detection from /host/root filesystem signatures.

Runs once at startup; cached. Used by Storage Manager to build OS-appropriate
quick-access lists and drive-letter mappings.
"""
from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

HOST_ROOT = "/host/root"


class HostOS(Enum):
    WINDOWS_NATIVE = "windows"
    WSL = "wsl"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"


@dataclass
class QuickAccessEntry:
    name: str
    path: str
    icon: str = "folder"
    item_count: int | None = None


@dataclass
class HostInfo:
    os: HostOS
    quick_access: list[QuickAccessEntry] = field(default_factory=list)
    drive_letters: list[str] = field(default_factory=list)
    home_dirs: list[str] = field(default_factory=list)
    external_drives: list[str] = field(default_factory=list)


_cache: HostInfo | None = None


def _detect_os_from_root(root: str) -> HostOS:
    """Detect OS from filesystem signatures under `root`. Priority matters."""
    if os.path.isdir(os.path.join(root, "Windows", "System32")):
        return HostOS.WINDOWS_NATIVE
    if os.path.isdir(os.path.join(root, "mnt", "c", "Windows", "System32")):
        return HostOS.WSL
    if os.path.isdir(os.path.join(root, "Users")) and os.path.isdir(os.path.join(root, "Volumes")):
        return HostOS.MACOS
    if os.path.isfile(os.path.join(root, "etc", "os-release")):
        return HostOS.LINUX
    return HostOS.UNKNOWN


def _safe_listdir(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except (OSError, PermissionError):
        return []


def _count_items(path: str) -> int | None:
    try:
        return len(os.listdir(path))
    except (OSError, PermissionError):
        return None


def _drive_letters(root: str) -> list[str]:
    """Windows drive letters exposed via `/host/root/<letter>` (container shim) or `/mnt/<letter>` (WSL)."""
    letters: list[str] = []
    for letter in string.ascii_uppercase:
        for candidate in (os.path.join(root, letter.lower()), os.path.join(root, "mnt", letter.lower())):
            if os.path.isdir(candidate):
                letters.append(letter)
                break
    return letters


def _build_quick_access(host_os: HostOS, root: str) -> tuple[list[QuickAccessEntry], list[str], list[str], list[str]]:
    qa: list[QuickAccessEntry] = []
    drive_letters: list[str] = []
    home_dirs: list[str] = []
    external_drives: list[str] = []

    if host_os is HostOS.WINDOWS_NATIVE:
        drive_letters = _drive_letters(root)
        for letter in drive_letters:
            drive_path = os.path.join(root, letter.lower())
            qa.append(QuickAccessEntry(name=f"{letter}:", path=drive_path, icon="drive"))
        users_dir = os.path.join(root, "Users")
        for user in _safe_listdir(users_dir):
            home = os.path.join(users_dir, user)
            if os.path.isdir(home) and not user.startswith("."):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user", item_count=_count_items(home)))
    elif host_os is HostOS.WSL:
        drive_letters = _drive_letters(root)
        for letter in drive_letters:
            qa.append(QuickAccessEntry(name=f"{letter}:", path=os.path.join(root, "mnt", letter.lower()), icon="drive"))
        home_root = os.path.join(root, "home")
        for user in _safe_listdir(home_root):
            home = os.path.join(home_root, user)
            if os.path.isdir(home):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user"))
    elif host_os is HostOS.MACOS:
        users_dir = os.path.join(root, "Users")
        for user in _safe_listdir(users_dir):
            home = os.path.join(users_dir, user)
            if os.path.isdir(home) and user not in ("Shared",) and not user.startswith("."):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user"))
        volumes_dir = os.path.join(root, "Volumes")
        for vol in _safe_listdir(volumes_dir):
            vpath = os.path.join(volumes_dir, vol)
            if os.path.isdir(vpath):
                external_drives.append(vpath)
                qa.append(QuickAccessEntry(name=vol, path=vpath, icon="external"))
    elif host_os is HostOS.LINUX:
        home_root = os.path.join(root, "home")
        for user in _safe_listdir(home_root):
            home = os.path.join(home_root, user)
            if os.path.isdir(home):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user"))
        for base in ("mnt", "media", "srv"):
            bpath = os.path.join(root, base)
            for entry in _safe_listdir(bpath):
                epath = os.path.join(bpath, entry)
                if os.path.isdir(epath):
                    external_drives.append(epath)
                    qa.append(QuickAccessEntry(name=f"/{base}/{entry}", path=epath, icon="external"))

    return qa, drive_letters, home_dirs, external_drives


def detect_host() -> HostInfo:
    """Detect host OS and build quick-access list. Cached after first call."""
    global _cache
    if _cache is not None:
        return _cache
    if not os.path.isdir(HOST_ROOT):
        log.warning("host_root_missing", path=HOST_ROOT)
        _cache = HostInfo(os=HostOS.UNKNOWN)
        return _cache
    host_os = _detect_os_from_root(HOST_ROOT)
    qa, drives, homes, externals = _build_quick_access(host_os, HOST_ROOT)
    _cache = HostInfo(os=host_os, quick_access=qa, drive_letters=drives, home_dirs=homes, external_drives=externals)
    log.info("host_detected", os=host_os.value, drives=drives, home_count=len(homes))
    return _cache


def reset_cache() -> None:
    """Test hook to force re-detection."""
    global _cache
    _cache = None
