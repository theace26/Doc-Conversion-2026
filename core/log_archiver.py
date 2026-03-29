"""
Log archive manager — compresses rotated log files for long-term retention.

When RotatingFileHandler rotates markflow-debug.log, it produces numbered backups
like markflow-debug.log.1, .2, .3. This module:

  1. Finds any rotated backup files (*.log.N)
  2. Compresses each to logs/archive/markflow-debug-<timestamp>.log.gz (~10:1 ratio)
  3. Deletes the uncompressed rotated file
  4. Purges archives older than LOG_ARCHIVE_RETENTION_DAYS (default: 90)

Runs as a scheduled job (every 6 hours by default). Also archives operational logs.

This is an interim solution — the planned direction is shipping logs to an external
aggregator (Grafana Loki / ELK) where retention is handled externally.

Environment variables:
  - LOG_ARCHIVE_RETENTION_DAYS (default: 90)
  - LOGS_DIR (default: logs)
"""

import gzip
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_logs_dir = Path(os.getenv("LOGS_DIR", "logs"))
_archive_dir = _logs_dir / "archive"
LOG_ARCHIVE_RETENTION_DAYS = int(os.environ.get("LOG_ARCHIVE_RETENTION_DAYS", "90"))

# Patterns for rotated backup files produced by RotatingFileHandler
_ROTATED_PATTERNS = ["markflow.log.*", "markflow-debug.log.*"]


async def archive_rotated_logs() -> None:
    """Compress rotated log files into the archive directory, then purge old archives."""
    try:
        _archive_dir.mkdir(parents=True, exist_ok=True)

        archived = 0
        for pattern in _ROTATED_PATTERNS:
            for rotated_file in sorted(_logs_dir.glob(pattern)):
                # Skip the archive directory itself and any .gz files
                if rotated_file.suffix == ".gz" or _archive_dir in rotated_file.parents:
                    continue
                # Only process numbered backups (e.g. markflow-debug.log.1)
                try:
                    int(rotated_file.suffix.lstrip("."))
                except ValueError:
                    continue

                try:
                    _compress_and_archive(rotated_file)
                    archived += 1
                except Exception as exc:
                    log.error("log_archive.compress_failed",
                              file=str(rotated_file), error=str(exc))

        purged = _purge_old_archives()

        if archived > 0 or purged > 0:
            log.info("log_archive.complete",
                     archived=archived,
                     purged=purged,
                     retention_days=LOG_ARCHIVE_RETENTION_DAYS)

    except Exception as exc:
        log.error("log_archive.failed", error=str(exc))


def _compress_and_archive(rotated_file: Path) -> None:
    """Gzip a single rotated log file into the archive directory, then delete the original."""
    # Build archive filename: markflow-debug-2026-03-27T14-30-00.log.gz
    stem = rotated_file.name.rsplit(".", 1)[0]  # e.g. "markflow-debug.log"
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    # Include the rotation number to avoid collisions within the same second
    rotation_num = rotated_file.suffix.lstrip(".")
    archive_name = f"{stem}-{timestamp}-r{rotation_num}.gz"
    archive_path = _archive_dir / archive_name

    original_size = rotated_file.stat().st_size
    if original_size == 0:
        rotated_file.unlink()
        return

    with open(rotated_file, "rb") as f_in:
        with gzip.open(archive_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)

    compressed_size = archive_path.stat().st_size
    ratio = round(original_size / compressed_size, 1) if compressed_size > 0 else 0

    # Delete the uncompressed rotated file
    rotated_file.unlink()

    log.debug("log_archive.compressed",
              source=rotated_file.name,
              archive=archive_name,
              original_mb=round(original_size / (1024 * 1024), 1),
              compressed_mb=round(compressed_size / (1024 * 1024), 1),
              ratio=ratio)


def _purge_old_archives() -> int:
    """Delete archive files older than LOG_ARCHIVE_RETENTION_DAYS. Returns count purged."""
    if not _archive_dir.exists():
        return 0

    cutoff = time.time() - (LOG_ARCHIVE_RETENTION_DAYS * 86400)
    purged = 0

    for gz_file in _archive_dir.glob("*.gz"):
        try:
            if gz_file.stat().st_mtime < cutoff:
                gz_file.unlink()
                purged += 1
                log.debug("log_archive.purged", file=gz_file.name)
        except Exception as exc:
            log.error("log_archive.purge_failed", file=gz_file.name, error=str(exc))

    return purged


def get_archive_stats() -> dict:
    """Return summary stats about the log archive (for admin/status endpoints)."""
    if not _archive_dir.exists():
        return {"archive_dir": str(_archive_dir), "file_count": 0,
                "total_bytes": 0, "retention_days": LOG_ARCHIVE_RETENTION_DAYS}

    files = list(_archive_dir.glob("*.gz"))
    total_bytes = sum(f.stat().st_size for f in files)
    oldest = min((f.stat().st_mtime for f in files), default=None)

    return {
        "archive_dir": str(_archive_dir),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 1),
        "retention_days": LOG_ARCHIVE_RETENTION_DAYS,
        "oldest_archive": datetime.fromtimestamp(oldest).isoformat() if oldest else None,
    }
