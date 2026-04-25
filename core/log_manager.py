"""Log file management — compression, retention, and inventory (v0.30.0).

Works alongside the stdlib RotatingFileHandler configured in
`core/logging_config.py`. The handler does the rotation itself
(markflow.log → markflow.log.1 → ... → markflow.log.N); this module
handles the post-rotation concerns the stdlib handler doesn't:

- **Compression**: scan for rotated backups (markflow.log.1 etc.) and
  compress them to .gz / .tar.gz / .7z based on a DB preference. Runs
  off the hot log write path via a scheduler job, not inline.
- **Retention**: delete compressed logs older than N days.
- **Inventory**: return a structured listing for the Admin UI.

Why scheduler-driven instead of subclassing RotatingFileHandler:
compression of a 100+ MB log would stall the logger thread for
seconds. Decoupling compression into a periodic job keeps the hot
path fast and makes the feature easy to disable (just stop the job).

Security: all file access is confined to the configured `LOGS_DIR`
(`/app/logs` in Docker). Path-traversal guards on every filename
parameter. ADMIN role required for all API endpoints.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

LOGS_DIR = Path(os.getenv("LOGS_DIR", "/app/logs"))

# Extensions we manage. `.log` (active + rotated numbered backups) plus
# known compressed variants.
_LOG_SUFFIXES = {".log"}
_COMPRESSED_SUFFIXES = {".gz", ".7z"}
_TAR_COMPRESSED_SUFFIXES = {".tar.gz", ".tgz"}

# Preference keys (read via core.database.get_preference)
PREF_COMPRESSION_FORMAT = "log_compression_format"        # 'gz' | 'tar.gz' | '7z'
PREF_RETENTION_DAYS = "log_retention_days"                # int
PREF_ROTATION_MAX_SIZE_MB = "log_rotation_max_size_mb"    # int (takes effect on restart)

DEFAULT_COMPRESSION_FORMAT = "gz"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_ROTATION_MAX_SIZE_MB = 100

_VALID_COMPRESSION_FORMATS = {"gz", "tar.gz", "7z"}


@dataclass(frozen=True)
class LogEntry:
    """One log file's metadata for the inventory view."""
    name: str
    path: str
    size_bytes: int
    modified_iso: str
    status: str          # 'active' | 'rotated' | 'compressed'
    stream: str          # 'operational' | 'debug' | 'other'
    compression: str | None  # 'gz' | '7z' | 'tar.gz' | None if uncompressed


def _safe_logs_path(name: str) -> Path:
    """Resolve `name` to an absolute path INSIDE LOGS_DIR.

    Accepts either a bare filename (for top-level logs) or an
    `archive/<filename>` relative path (for archived logs). Rejects
    any `..`, absolute paths, or paths that resolve outside LOGS_DIR.
    """
    # Normalize `archive/foo.gz` but reject any `..` traversal
    if "\\" in name or name.startswith("/") or ".." in name.split("/"):
        raise PermissionError(f"invalid path: {name}")
    candidate = (LOGS_DIR / name).resolve()
    root = LOGS_DIR.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"path outside logs dir: {name}") from exc
    return candidate


def _classify_stream(filename: str) -> str:
    lower = filename.lower()
    if lower.startswith("markflow-debug"):
        return "debug"
    if lower.startswith("markflow."):
        return "operational"
    return "other"


def _classify_status(path: Path) -> tuple[str, str | None]:
    """Return (status, compression) for a log file.

    - `markflow.log` / `markflow-debug.log` → ('active', None)
    - `markflow.log.1` / `.log.5` → ('rotated', None)
    - `markflow.log.1.gz` / `.log.5.7z` → ('compressed', 'gz' | '7z')
    - `markflow.log.1.tar.gz` → ('compressed', 'tar.gz')
    """
    name = path.name
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return "compressed", "tar.gz"
    if name.endswith(".gz"):
        return "compressed", "gz"
    if name.endswith(".7z"):
        return "compressed", "7z"
    # Strip any trailing `.N` index to detect rotated-but-uncompressed
    stem = name
    parts = name.rsplit(".", 1)
    if len(parts) == 2 and parts[1].isdigit():
        stem = parts[0]
    if stem.endswith(".log"):
        # Numbered → rotated; unnumbered → active
        return ("rotated" if stem != name else "active"), None
    return "other", None


def list_logs() -> list[LogEntry]:
    """Return every log file currently on disk under LOGS_DIR (including
    the legacy `archive/` subdir, retained for backwards-compat after
    the v0.31.0 log_archiver consolidation), sorted by modification
    time descending.

    `LogEntry.name` is either the bare filename for files directly under
    LOGS_DIR, or `archive/<filename>` for files in the archive subdir.
    The inventory API and download endpoint both use this relative path
    as the identifier so the UI can uniquely reference either location.
    """
    if not LOGS_DIR.exists():
        return []
    entries: list[LogEntry] = []

    def _consider(p: Path, rel_name: str):
        lower = p.name.lower()
        # Skip hidden / non-log files (.gitkeep, LOG-INVENTORY.md, etc.)
        if p.name.startswith("."):
            return
        is_log_like = (
            ".log" in lower
            or lower.endswith(".gz")
            or lower.endswith(".7z")
            or lower.endswith(".tar.gz")
            or lower.endswith(".tgz")
        )
        if not is_log_like:
            return
        try:
            stat = p.stat()
        except OSError:
            return
        status, compression = _classify_status(p)
        entries.append(LogEntry(
            name=rel_name,
            path=str(p),
            size_bytes=stat.st_size,
            modified_iso=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                .isoformat(),
            status=status,
            stream=_classify_stream(p.name),
            compression=compression,
        ))

    # Top-level logs dir
    for p in LOGS_DIR.iterdir():
        if p.is_file():
            _consider(p, p.name)

    # Legacy archive/ subdir from pre-v0.31.0 log_archiver. Still
    # discovered for read access to historical files.
    archive_dir = LOGS_DIR / "archive"
    if archive_dir.exists() and archive_dir.is_dir():
        for p in archive_dir.iterdir():
            if p.is_file():
                _consider(p, f"archive/{p.name}")

    entries.sort(key=lambda e: e.modified_iso, reverse=True)
    return entries


def _is_rotated_uncompressed(p: Path) -> bool:
    """True if `p` is a numbered rotated log (e.g. markflow.log.1) that
    is not yet compressed. The active `.log` files are excluded —
    they're still being written to."""
    parts = p.name.rsplit(".", 1)
    if len(parts) != 2:
        return False
    stem, idx = parts
    if not idx.isdigit():
        return False
    return stem.endswith(".log")


async def compress_rotated_logs(format_override: str | None = None) -> dict:
    """Find every rotated uncompressed log under LOGS_DIR and compress
    it using the DB-configured format (or the override).

    Returns a summary dict with counts + reclaimed bytes. Idempotent:
    already-compressed files are skipped.
    """
    from core.database import get_preference
    fmt = format_override or await get_preference(PREF_COMPRESSION_FORMAT) or DEFAULT_COMPRESSION_FORMAT
    if fmt not in _VALID_COMPRESSION_FORMATS:
        log.warning("log_manager.invalid_compression_format", format=fmt, fallback=DEFAULT_COMPRESSION_FORMAT)
        fmt = DEFAULT_COMPRESSION_FORMAT

    if not LOGS_DIR.exists():
        return {"compressed": 0, "skipped": 0, "failed": 0, "bytes_reclaimed": 0}

    targets = [p for p in LOGS_DIR.iterdir() if p.is_file() and _is_rotated_uncompressed(p)]
    if not targets:
        return {"compressed": 0, "skipped": 0, "failed": 0, "bytes_reclaimed": 0}

    compressed = 0
    failed = 0
    bytes_reclaimed = 0

    for src in targets:
        try:
            # Pre-flight: source must still exist (a concurrent rotation
            # could have rolled .1 → .2 underneath us).
            if not src.exists():
                continue
            original_size = src.stat().st_size
            out_bytes = await asyncio.to_thread(_compress_one, src, fmt)
            if out_bytes is None:
                failed += 1
                continue
            bytes_reclaimed += max(0, original_size - out_bytes)
            compressed += 1
        except Exception as exc:
            failed += 1
            log.warning("log_manager.compress_failed", path=str(src),
                        error=f"{type(exc).__name__}: {exc}")

    if compressed or failed:
        log.info("log_manager.compression_complete",
                 compressed=compressed, failed=failed,
                 bytes_reclaimed=bytes_reclaimed, format=fmt)
    return {"compressed": compressed, "skipped": 0, "failed": failed,
            "bytes_reclaimed": bytes_reclaimed, "format": fmt}


def _compress_one(src: Path, fmt: str) -> int | None:
    """Synchronous compression of one log file. Returns the output size
    in bytes on success, None on failure. Intended to run in a worker
    thread via asyncio.to_thread."""
    if fmt == "gz":
        out = src.with_name(src.name + ".gz")
        with src.open("rb") as fin, gzip.open(out, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout, length=1024 * 1024)
    elif fmt == "tar.gz":
        out = src.with_name(src.name + ".tar.gz")
        with tarfile.open(out, "w:gz", compresslevel=6) as tar:
            tar.add(src, arcname=src.name)
    elif fmt == "7z":
        out = src.with_name(src.name + ".7z")
        # Use the system 7z binary — faster + more memory-efficient
        # than a pure-Python implementation for large files.
        result = subprocess.run(
            ["/usr/bin/7z", "a", "-bso0", "-bsp0", "-y", str(out), str(src)],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            log.warning("log_manager.7z_failed", path=str(src),
                        returncode=result.returncode, stderr=result.stderr[:500])
            if out.exists():
                out.unlink(missing_ok=True)
            return None
    else:
        log.warning("log_manager.unknown_format", format=fmt)
        return None

    out_size = out.stat().st_size
    src.unlink()  # remove the uncompressed source only after compression succeeded
    return out_size


async def apply_retention(days_override: int | None = None) -> dict:
    """Delete compressed logs older than the configured retention
    window. Uncompressed `.log` and numbered rotated `.log.N` files are
    NEVER deleted by this (they're either live or pending-compression).
    Only files with one of the compressed suffixes qualify."""
    from core.database import get_preference
    if days_override is not None:
        days = days_override
    else:
        raw = await get_preference(PREF_RETENTION_DAYS)
        try:
            days = int(raw) if raw else DEFAULT_RETENTION_DAYS
        except (TypeError, ValueError):
            days = DEFAULT_RETENTION_DAYS
    if days <= 0:
        return {"deleted": 0, "bytes_reclaimed": 0, "retention_days": days}

    if not LOGS_DIR.exists():
        return {"deleted": 0, "bytes_reclaimed": 0, "retention_days": days}

    cutoff = time.time() - days * 86400
    deleted = 0
    bytes_reclaimed = 0

    for p in LOGS_DIR.iterdir():
        if not p.is_file():
            continue
        name = p.name
        # Only delete compressed files (safety)
        if not (name.endswith(".gz") or name.endswith(".7z")
                or name.endswith(".tgz")):
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        if stat.st_mtime > cutoff:
            continue
        try:
            size = stat.st_size
            p.unlink()
            deleted += 1
            bytes_reclaimed += size
        except OSError as exc:
            log.warning("log_manager.retention_delete_failed",
                        path=str(p), error=str(exc))

    if deleted:
        log.info("log_manager.retention_complete",
                 deleted=deleted, bytes_reclaimed=bytes_reclaimed,
                 retention_days=days)
    return {"deleted": deleted, "bytes_reclaimed": bytes_reclaimed,
            "retention_days": days}


async def get_archive_stats() -> dict:
    """Compatibility shim for the legacy `/api/logs/archives/stats`
    endpoint (v0.12.2). Returns counts + sizes for the existing
    `archive/` subdir AND any in-place compressed logs under LOGS_DIR.

    Replaces the original `core/log_archiver.get_archive_stats` (which
    only saw the `archive/` subdir and used an env-var retention).
    Retention is now read from DB prefs (Settings page).
    """
    from core.database import get_preference
    raw = await get_preference(PREF_RETENTION_DAYS)
    try:
        retention_days = int(raw) if raw else DEFAULT_RETENTION_DAYS
    except (TypeError, ValueError):
        retention_days = DEFAULT_RETENTION_DAYS

    if not LOGS_DIR.exists():
        return {
            "archive_dir": str(LOGS_DIR / "archive"),
            "file_count": 0, "total_bytes": 0, "total_mb": 0,
            "retention_days": retention_days, "oldest_archive": None,
        }

    files: list[Path] = []
    for p in LOGS_DIR.iterdir():
        if p.is_file() and (
            p.name.endswith(".gz") or p.name.endswith(".7z")
            or p.name.endswith(".tar.gz") or p.name.endswith(".tgz")
        ):
            files.append(p)
    archive_subdir = LOGS_DIR / "archive"
    if archive_subdir.exists() and archive_subdir.is_dir():
        for p in archive_subdir.iterdir():
            if p.is_file() and (
                p.name.endswith(".gz") or p.name.endswith(".7z")
                or p.name.endswith(".tar.gz") or p.name.endswith(".tgz")
            ):
                files.append(p)

    total_bytes = sum(f.stat().st_size for f in files)
    oldest = min((f.stat().st_mtime for f in files), default=None)
    return {
        "archive_dir": str(archive_subdir),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 1),
        "retention_days": retention_days,
        "oldest_archive": datetime.fromtimestamp(oldest, tz=timezone.utc).isoformat()
            if oldest else None,
    }


async def get_settings() -> dict:
    """Fetch current log management settings from DB prefs (with defaults)."""
    from core.database import get_preference
    fmt = await get_preference(PREF_COMPRESSION_FORMAT) or DEFAULT_COMPRESSION_FORMAT
    retention_raw = await get_preference(PREF_RETENTION_DAYS)
    max_size_raw = await get_preference(PREF_ROTATION_MAX_SIZE_MB)
    try:
        retention_days = int(retention_raw) if retention_raw else DEFAULT_RETENTION_DAYS
    except (TypeError, ValueError):
        retention_days = DEFAULT_RETENTION_DAYS
    try:
        max_size_mb = int(max_size_raw) if max_size_raw else DEFAULT_ROTATION_MAX_SIZE_MB
    except (TypeError, ValueError):
        max_size_mb = DEFAULT_ROTATION_MAX_SIZE_MB
    return {
        "compression_format": fmt if fmt in _VALID_COMPRESSION_FORMATS else DEFAULT_COMPRESSION_FORMAT,
        "retention_days": retention_days,
        "rotation_max_size_mb": max_size_mb,
        "valid_formats": sorted(_VALID_COMPRESSION_FORMATS),
    }


async def set_settings(
    compression_format: str | None = None,
    retention_days: int | None = None,
    rotation_max_size_mb: int | None = None,
) -> dict:
    """Update log management settings. Caller is responsible for auth
    (ADMIN-gated at the route layer). Returns the new settings dict.

    Note: `rotation_max_size_mb` takes effect on the next container
    restart — the RotatingFileHandler's `maxBytes` is set once at
    handler construction in logging_config. The other two apply on the
    next scheduler run.
    """
    from core.database import set_preference
    if compression_format is not None:
        if compression_format not in _VALID_COMPRESSION_FORMATS:
            raise ValueError(
                f"compression_format must be one of {sorted(_VALID_COMPRESSION_FORMATS)}"
            )
        await set_preference(PREF_COMPRESSION_FORMAT, compression_format)
    if retention_days is not None:
        if retention_days < 1 or retention_days > 3650:
            raise ValueError("retention_days must be between 1 and 3650")
        await set_preference(PREF_RETENTION_DAYS, str(retention_days))
    if rotation_max_size_mb is not None:
        if rotation_max_size_mb < 10 or rotation_max_size_mb > 10240:
            raise ValueError("rotation_max_size_mb must be between 10 and 10240")
        await set_preference(PREF_ROTATION_MAX_SIZE_MB, str(rotation_max_size_mb))
    return await get_settings()
