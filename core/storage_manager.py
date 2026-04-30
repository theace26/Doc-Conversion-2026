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


# ── Write guard ──────────────────────────────────────────────────────────────

_cached_output_path: str | None = None


class StorageWriteDenied(PermissionError):
    """Raised when a write target falls outside the configured output directory."""


def set_output_path(path: str | None) -> None:
    """Update the configured output directory (cached in-process). Called by config layer."""
    global _cached_output_path
    _cached_output_path = os.path.realpath(path) if path else None
    log.info("output_path_updated", path=_cached_output_path)


def get_output_path() -> str | None:
    """Return the currently configured output path (real-resolved) or None."""
    return _cached_output_path


def is_write_allowed(target_path: str) -> bool:
    """True iff target resolves inside the configured output directory.

    SECURITY: This is the SOLE application-level restriction on the broad
    /host/rw Docker mount (v0.25.0). Must be called before every file
    write in converter.py, bulk_worker.py, and any new write path.
    Coverage is enforced by tests/test_write_guard_coverage.py -- keep
    it green.

    v0.34.7 BUG-014: previously consulted only the
    ``_cached_output_path`` sentinel populated from the
    ``storage_output_path`` DB preference. Whenever that pref was unset
    (fresh deploy, post-reset, or any container running before an
    operator visited the Storage page), the cache stayed ``None`` and
    this function returned ``False`` for every path -- silently denying
    every conversion in the bulk pipeline even though
    ``BULK_OUTPUT_PATH`` env was correctly set and the converter was
    writing inside it. The on-disk symptom was hundreds of
    ``write denied -- outside output dir: /mnt/output-repo/...`` errors
    in ``bulk_files.error_msg`` against paths that were demonstrably
    inside the configured root.

    The guard now resolves through
    :func:`core.storage_paths.resolve_output_root_or_raise`, which uses
    the same priority chain as v0.34.1's runtime path resolution
    (Storage Manager > BULK_OUTPUT_PATH > OUTPUT_DIR) and refuses to
    silently fall back to the legacy ``output/`` default. If the
    resolver raises, the guard returns ``False`` -- preserving the
    v0.25.0 intent that absent configuration means "deny everything",
    not "allow /app/output".
    """
    if not target_path:
        return False
    try:
        from core.storage_paths import resolve_output_root_or_raise
        base_path = resolve_output_root_or_raise(label="is_write_allowed")
    except RuntimeError:
        return False
    try:
        target_real = os.path.realpath(target_path)
    except OSError:
        return False
    base = str(base_path).rstrip(os.sep)
    return target_real == base or target_real.startswith(base + os.sep)


# ── Config persistence (DB-backed) ───────────────────────────────────────────


async def load_config_from_db() -> None:
    """Populate in-process write-guard cache from DB prefs. Call from lifespan startup."""
    from core.preferences_cache import get_cached_preference
    output = await get_cached_preference("storage_output_path", default=None)
    set_output_path(output)
    log.info("storage_config_loaded", output=output)


async def save_output_path(path: str) -> None:
    """Persist output path to DB prefs + update in-process cache + flag pending restart.

    The pending-restart flag is only set when the output actually CHANGES
    (not on first write), so the initial wizard configuration doesn't pop a
    misleading restart banner.
    """
    from datetime import datetime, timezone
    from core.db.preferences import set_preference
    from core.preferences_cache import invalidate_preference

    old = _cached_output_path
    new_real = os.path.realpath(path) if path else None

    await set_preference("storage_output_path", path)
    invalidate_preference("storage_output_path")
    set_output_path(path)

    if old is not None and old != new_real:
        await set_preference(
            "pending_restart_reason", f"Output directory changed to {path}"
        )
        await set_preference(
            "pending_restart_since", datetime.now(timezone.utc).isoformat()
        )
        await set_preference("pending_restart_dismissed_until", "")
        invalidate_preference("pending_restart_reason")
        invalidate_preference("pending_restart_since")
        invalidate_preference("pending_restart_dismissed_until")
