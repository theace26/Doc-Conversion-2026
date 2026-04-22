"""Storage Manager: path validation, write-guard enforcement, config persistence.

Three responsibilities, in order of security criticality:

1. **Write guard** (`is_write_allowed`) — the SOLE application-level restriction
   on the broad /host/rw Docker mount (v0.25.0). Every file write in
   converter.py / bulk_worker.py MUST gate on this. Missing coverage =
   container sandbox escape.

2. **Path validation** (`validate_path`) — user-facing validation surface for
   the Storage page. Returns plain-English errors and warnings.

3. **Config persistence** — load/save the configured output path through
   the preferences cache; flag a pending restart whenever output changes.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum

import structlog

log = structlog.get_logger(__name__)

_LOW_SPACE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB warn threshold
_LONG_PATH_CHARS = 240


class PathRole(Enum):
    SOURCE = "source"
    OUTPUT = "output"


@dataclass
class ValidationResult:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _warn_long_path(path: str) -> str | None:
    """Heads-up for paths near the Windows 260-char MAX_PATH limit."""
    if len(path) > _LONG_PATH_CHARS:
        return "Very long path — some files may fail on Windows (260-char limit)."
    return None


def check_source_output_conflict(source: str, output: str) -> list[str]:
    """Reject source==output and either-inside-the-other (conversion loop hazard)."""
    errors: list[str] = []
    if not source or not output:
        return errors
    try:
        s = os.path.realpath(source)
        o = os.path.realpath(output)
    except OSError:
        return errors
    if s == o:
        errors.append("Input and output can't be the same folder.")
    elif o.startswith(s + os.sep):
        errors.append("Output folder is inside the input folder — this can cause loops.")
    elif s.startswith(o + os.sep):
        errors.append("Input folder is inside the output folder — this can cause loops.")
    return errors


def _validate_sync(path: str, role: PathRole) -> ValidationResult:
    res = ValidationResult(ok=False)
    if not path:
        res.errors.append("No path provided.")
        return res
    if not os.path.exists(path):
        res.errors.append(f"This folder doesn't exist: {path}")
        return res
    if not os.path.isdir(path):
        res.errors.append("This path is a file, not a folder.")
        return res
    if not os.access(path, os.R_OK):
        res.errors.append("MarkFlow can't read this folder — check permissions.")
        return res

    warn = _warn_long_path(path)
    if warn:
        res.warnings.append(warn)

    try:
        entries = os.listdir(path)
        res.stats["item_count"] = len(entries)
        if role is PathRole.SOURCE and not entries:
            res.warnings.append("This folder is empty — are you sure?")
    except OSError as exc:
        res.errors.append(f"MarkFlow can't list this folder: {exc}")
        return res

    if role is PathRole.OUTPUT:
        if not os.access(path, os.W_OK):
            res.errors.append("MarkFlow can't write to this folder — check permissions.")
            return res
        try:
            du = shutil.disk_usage(path)
            res.stats["free_space_bytes"] = du.free
            if du.free < _LOW_SPACE_BYTES:
                mb = du.free // (1024 * 1024)
                res.warnings.append(f"Low disk space on output drive ({mb} MB free).")
        except OSError:
            pass

    res.ok = True
    return res


async def validate_path(path: str, role: PathRole) -> ValidationResult:
    """Validate `path` for its intended role. Wrapped in to_thread to tolerate slow NAS stat."""
    return await asyncio.to_thread(_validate_sync, path, role)
