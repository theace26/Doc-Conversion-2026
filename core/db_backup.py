"""
Database backup / restore / list-backups operations.

Three async functions:

- ``backup_database(download=False)`` — WAL-checkpoint + copy the live DB to
  ``BACKUPS_DIR/markflow-{ts}.db``.  If ``download=True``, stream the copy
  as a ``FileResponse`` for browser download.

- ``restore_database(source_path=... | uploaded_bytes=...)`` — validate via
  ``PRAGMA integrity_check``, shut down the pool, rotate the live DB to
  ``markflow.db.pre-restore-{ts}.bak`` (and .shm/.wal siblings), copy the
  backup into place, reinitialize the pool.

- ``list_backups()`` — enumerate ``markflow-*.db`` files in the backups dir,
  newest-first.

All three refuse when an active bulk job is ``running`` or ``scanning``.
Follows the response shape / async conventions from ``core/db_maintenance.py``.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi.responses import FileResponse

from core.db.connection import DB_PATH
from core.db.pool import init_pool, shutdown_pool

log = structlog.get_logger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BACKUPS_DIR = Path(os.getenv("BACKUPS_DIR", "backups"))

# Read pool size used at restore-time reinit (mirror the app-wide default).
_READ_POOL_SIZE = int(os.getenv("DB_READ_POOL_SIZE", "3"))


# ── Bulk-job guard ────────────────────────────────────────────────────────────
async def _active_bulk_jobs() -> list[dict]:
    """Return active bulk jobs (imported lazily to avoid circular imports)."""
    from core.bulk_worker import get_all_active_jobs
    return await get_all_active_jobs()


# Re-exported name so tests can monkeypatch ``core.db_backup.get_all_active_jobs``.
async def get_all_active_jobs() -> list[dict]:
    return await _active_bulk_jobs()


def _has_blocking_job(jobs: list[dict]) -> bool:
    return any(j.get("status") in ("running", "scanning") for j in jobs)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _ensure_backups_dir() -> None:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


# ── 1. Backup ─────────────────────────────────────────────────────────────────
async def backup_database(download: bool = False):
    """
    Checkpoint WAL and copy the live DB to a timestamped backup file.

    If ``download=True``, return a ``FileResponse`` streaming the copied file
    as an attachment.  Otherwise return a ``dict`` with ``ok``, ``path``,
    ``size_bytes``, ``generated_at``.

    Refuses with ``{"ok": False, "error": "Bulk jobs active"}`` if any bulk
    job is currently ``running`` or ``scanning``.
    """
    jobs = await get_all_active_jobs()
    if _has_blocking_job(jobs):
        log.warning("db_backup.refused_bulk_active", jobs=len(jobs))
        return {
            "ok": False,
            "error": "Bulk jobs active — pause or wait for completion before backing up",
            "generated_at": _now_iso(),
        }

    _ensure_backups_dir()
    ts = _ts_slug()
    filename = f"markflow-{ts}.db"
    dest = BACKUPS_DIR / filename

    log.info("db_backup.started", dest=str(dest))

    # 1. Checkpoint WAL so the copy is self-contained.
    try:
        def _checkpoint() -> None:
            conn = sqlite3.connect(str(DB_PATH))
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_checkpoint)
    except Exception as exc:
        # Non-fatal — a copy is still likely recoverable, but warn.
        log.warning("db_backup.wal_checkpoint_failed", error=str(exc))

    # 2. Copy the live DB file off-thread.
    try:
        await asyncio.to_thread(shutil.copy2, str(DB_PATH), str(dest))
    except Exception as exc:
        log.error("db_backup.copy_failed", error=str(exc))
        return {"ok": False, "error": f"Copy failed: {exc}", "generated_at": _now_iso()}

    size = dest.stat().st_size
    log.info("db_backup.completed", dest=str(dest), size_bytes=size)

    if download:
        return FileResponse(
            path=str(dest),
            filename=filename,
            media_type="application/octet-stream",
        )

    return {
        "ok": True,
        "path": str(dest),
        "size_bytes": size,
        "generated_at": _now_iso(),
    }


# ── 2. Restore ────────────────────────────────────────────────────────────────
def _integrity_check_sync(path: Path) -> tuple[bool, list[str]]:
    """Run PRAGMA integrity_check on a candidate file. Returns (ok, findings)."""
    try:
        conn = sqlite3.connect(str(path))
        try:
            cur = conn.execute("PRAGMA integrity_check")
            findings = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as exc:
        return False, [f"open failed: {exc}"]
    ok = findings == ["ok"]
    return ok, findings


def _resolve_and_validate_source(source_path: Path) -> Path:
    """Resolve ``source_path`` and ensure it sits under ``BACKUPS_DIR``.

    Prevents path traversal when an API caller supplies a filename.
    """
    resolved = Path(source_path).expanduser().resolve()
    backups_root = BACKUPS_DIR.expanduser().resolve()
    try:
        resolved.relative_to(backups_root)
    except ValueError:
        raise ValueError(
            f"source_path must resolve inside BACKUPS_DIR ({backups_root}); got {resolved}"
        )
    return resolved


async def restore_database(
    source_path: Path | None = None,
    uploaded_bytes: bytes | None = None,
) -> dict:
    """
    Replace the live DB with a validated backup.

    Exactly one of ``source_path`` or ``uploaded_bytes`` must be provided.
    The candidate is integrity-checked BEFORE the live DB is touched.
    On success the live DB (and .shm/.wal siblings) is rotated aside to
    ``markflow.db.pre-restore-{ts}.bak`` and the backup is copied in.
    The connection pool is shut down for the swap and reinitialized after.
    """
    if (source_path is None) == (uploaded_bytes is None):
        raise ValueError("Provide exactly one of source_path or uploaded_bytes")

    jobs = await get_all_active_jobs()
    if _has_blocking_job(jobs):
        log.warning("db_restore.refused_bulk_active", jobs=len(jobs))
        return {
            "ok": False,
            "error": "Bulk jobs active — pause or wait for completion before restoring",
            "generated_at": _now_iso(),
        }

    # Materialize the candidate to a concrete filesystem path we can pragma-check.
    temp_upload: Path | None = None
    if uploaded_bytes is not None:
        _ensure_backups_dir()
        fd, tmpname = tempfile.mkstemp(prefix="markflow-upload-", suffix=".db")
        os.close(fd)
        temp_upload = Path(tmpname)
        try:
            await asyncio.to_thread(temp_upload.write_bytes, uploaded_bytes)
        except Exception as exc:
            log.error("db_restore.upload_write_failed", error=str(exc))
            return {"ok": False, "error": f"Upload write failed: {exc}", "generated_at": _now_iso()}
        candidate = temp_upload
    else:
        try:
            candidate = _resolve_and_validate_source(source_path)  # type: ignore[arg-type]
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "generated_at": _now_iso()}
        if not candidate.exists():
            return {
                "ok": False,
                "error": f"Backup file not found: {candidate}",
                "generated_at": _now_iso(),
            }

    # Integrity check BEFORE touching the live DB.
    try:
        ok, findings = await asyncio.to_thread(_integrity_check_sync, candidate)
    except Exception as exc:
        ok, findings = False, [f"integrity check raised: {exc}"]

    if not ok:
        log.error("db_restore.integrity_failed", findings=findings, candidate=str(candidate))
        # Clean up the temp upload
        if temp_upload is not None:
            try:
                temp_upload.unlink(missing_ok=True)
            except Exception:
                pass
        return {
            "ok": False,
            "error": "Backup failed integrity check",
            "findings": findings,
            "generated_at": _now_iso(),
        }

    log.info("db_restore.started", candidate=str(candidate))

    # Shut pool down so we can swap files.
    try:
        await shutdown_pool()
    except Exception as exc:
        log.warning("db_restore.shutdown_pool_failed", error=str(exc))

    ts = _ts_slug()
    live = Path(DB_PATH)
    rotated = live.with_name(f"{live.name}.pre-restore-{ts}.bak")

    def _rotate_and_swap() -> Path:
        # Rotate the main DB + WAL/SHM siblings (if present).
        if live.exists():
            shutil.move(str(live), str(rotated))
        for sib_suffix in ("-wal", "-shm"):
            sib = live.with_name(live.name + sib_suffix)
            if sib.exists():
                sib_rot = rotated.with_name(rotated.name + sib_suffix)
                try:
                    shutil.move(str(sib), str(sib_rot))
                except Exception as exc:
                    log.warning("db_restore.sibling_rotate_failed",
                                sibling=str(sib), error=str(exc))
        # Copy the (validated) backup into the live path.
        shutil.copy2(str(candidate), str(live))
        return rotated

    try:
        rotated_path = await asyncio.to_thread(_rotate_and_swap)
    except Exception as exc:
        log.error("db_restore.swap_failed", error=str(exc))
        # Try to bring pool back up against whatever's at the live path.
        try:
            await init_pool(DB_PATH, read_pool_size=_READ_POOL_SIZE)
        except Exception:
            pass
        return {"ok": False, "error": f"Swap failed: {exc}", "generated_at": _now_iso()}
    finally:
        if temp_upload is not None:
            try:
                temp_upload.unlink(missing_ok=True)
            except Exception:
                pass

    # Reopen the pool on the freshly-restored file.
    try:
        await init_pool(DB_PATH, read_pool_size=_READ_POOL_SIZE)
    except Exception as exc:
        log.error("db_restore.pool_reinit_failed", error=str(exc))
        return {
            "ok": False,
            "error": f"Restore copied but pool reinit failed: {exc}",
            "rotated_to": str(rotated_path),
            "generated_at": _now_iso(),
        }

    log.info("db_restore.completed", rotated_to=str(rotated_path))
    return {
        "ok": True,
        "rotated_to": str(rotated_path),
        "generated_at": _now_iso(),
    }


# ── 3. List ───────────────────────────────────────────────────────────────────
async def list_backups() -> list[dict]:
    """List ``markflow-*.db`` files in the backups dir, newest-first.

    Returns empty list if the directory doesn't exist (no error).
    """
    def _scan() -> list[dict]:
        if not BACKUPS_DIR.exists():
            return []
        entries: list[dict] = []
        for p in BACKUPS_DIR.glob("markflow-*.db"):
            if not p.is_file():
                continue
            try:
                stat = p.stat()
            except OSError:
                continue
            entries.append({
                "filename": p.name,
                "path": str(p),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "_mtime": stat.st_mtime,
            })
        entries.sort(key=lambda e: e["_mtime"], reverse=True)
        for e in entries:
            e.pop("_mtime", None)
        return entries

    return await asyncio.to_thread(_scan)
