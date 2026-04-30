"""
Lifecycle state machine for tracked files.

Transitions: active -> marked_for_deletion -> in_trash -> purged

Called by the lifecycle scanner (Sub-phase D) and maintenance jobs (Sub-phase F).
Does not run scans — only applies decisions the scanner has made.
"""

import asyncio
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

from core.database import (
    create_version_snapshot,
    get_next_version_number,
    update_bulk_file,
    update_source_file,
    db_fetch_one,
    db_fetch_all,
)
from core.db.connection import db_execute

log = structlog.get_logger(__name__)

GRACE_PERIOD_HOURS = 36
# v0.23.6 M4: this constant is only used in the trash README text below as
# a sensible default; the authoritative retention window is the
# `lifecycle_trash_retention_days` preference read by scheduler.run_trash_expiry
# and scheduler._purge_aged_trash.
TRASH_RETENTION_DAYS = 60
TRASH_DIR_NAME = ".trash"

# v0.34.1 BUG-007: replaced module-level frozen constant with a getter
# that re-resolves on every call. Pre-fix this captured a stale env-var
# value at import time, so the lifecycle scanner walked the wrong tree
# whenever Storage Manager's configured output diverged from
# OUTPUT_DIR / BULK_OUTPUT_PATH — leading to no soft-delete tracking
# and orphaned files in the actual output dir.
#
# v0.34.2 BUG-010: dropped the legacy `OUTPUT_REPO_ROOT` module-level
# alias (which itself froze `_output_root()`'s value at import time and
# poisoned `core/db_maintenance.py`'s dangling-trash health check). All
# remaining consumers now call `core.storage_paths.get_output_root()`
# directly — no in-module alias to re-introduce the frozen-snapshot bug.
def _output_root() -> Path:
    from core.storage_paths import get_output_root
    return get_output_root()


def get_trash_path(output_repo_root: Path, md_path: Path) -> Path:
    """Return .trash/ mirror of md_path relative to output_repo_root."""
    try:
        relative = md_path.relative_to(output_repo_root)
    except ValueError:
        relative = Path(md_path.name)
    trash_dir = output_repo_root / TRASH_DIR_NAME
    trash_file = trash_dir / relative

    # Create trash README on first use
    readme = trash_dir / "README.txt"
    if not readme.exists():
        trash_dir.mkdir(parents=True, exist_ok=True)
        try:
            readme.write_text(
                "MarkFlow Trash Directory\n"
                "========================\n\n"
                "Files here were removed from the source repository and moved to trash\n"
                "by the MarkFlow lifecycle scanner.\n\n"
                f"Retention policy: files are permanently deleted {TRASH_RETENTION_DAYS} days\n"
                "after being moved to trash (based on moved_to_trash_at timestamp).\n\n"
                "Do not manually modify files in this directory.\n"
            )
        except OSError:
            pass

    return trash_file


async def _get_bulk_file(bulk_file_id: str) -> dict | None:
    """Fetch a bulk_file row."""
    return await db_fetch_one(
        "SELECT * FROM bulk_files WHERE id=?", (bulk_file_id,)
    )


async def mark_file_for_deletion(bulk_file_id: str, scan_run_id: str) -> None:
    """Mark an active file for deletion (grace period begins)."""
    now = datetime.now(timezone.utc).isoformat()
    file_rec = await _get_bulk_file(bulk_file_id)

    await update_bulk_file(
        bulk_file_id,
        lifecycle_status="marked_for_deletion",
        marked_for_deletion_at=now,
    )

    sf_id = file_rec.get("source_file_id") if file_rec else None
    if sf_id:
        await update_source_file(sf_id, lifecycle_status="marked_for_deletion", marked_for_deletion_at=now)

    version_num = await get_next_version_number(bulk_file_id)
    await create_version_snapshot(bulk_file_id, {
        "version_number": version_num,
        "change_type": "marked_deleted",
        "path_at_version": file_rec["source_path"] if file_rec else "",
        "mtime_at_version": file_rec.get("source_mtime") if file_rec else None,
        "size_at_version": file_rec.get("file_size_bytes") if file_rec else None,
        "content_hash": file_rec.get("content_hash") if file_rec else None,
        "scan_run_id": scan_run_id,
        "notes": "File no longer found in source share",
    })

    log.info("lifecycle.marked_for_deletion", bulk_file_id=bulk_file_id)


async def restore_file(bulk_file_id: str, scan_run_id: str) -> None:
    """Restore a marked_for_deletion or in_trash file back to active."""
    file_rec = await _get_bulk_file(bulk_file_id)
    was_in_trash = file_rec and file_rec.get("lifecycle_status") == "in_trash"

    await update_bulk_file(
        bulk_file_id,
        lifecycle_status="active",
        marked_for_deletion_at=None,
    )

    sf_id = file_rec.get("source_file_id") if file_rec else None
    if sf_id:
        await update_source_file(sf_id, lifecycle_status="active", marked_for_deletion_at=None)

    # If was in trash, move .md back from .trash/ to original output path
    if was_in_trash and file_rec:
        output_path = file_rec.get("output_path")
        if output_path:
            trash_file = get_trash_path(_output_root(), Path(output_path))
            original = Path(output_path)
            if trash_file.exists() and not original.exists():
                try:
                    original.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(shutil.move, str(trash_file), str(original))
                    log.info("lifecycle.restored_from_trash", path=str(original))
                except OSError as exc:
                    log.warning("lifecycle.restore_move_failed", error=str(exc))

            # Re-index in Meilisearch
            try:
                from core.search_indexer import get_search_indexer
                indexer = get_search_indexer()
                if indexer and original.exists():
                    await indexer.index_document(original)
            except Exception as exc:
                log.warning("lifecycle.restore_reindex_failed", error=str(exc))

    version_num = await get_next_version_number(bulk_file_id)
    await create_version_snapshot(bulk_file_id, {
        "version_number": version_num,
        "change_type": "restored",
        "path_at_version": file_rec["source_path"] if file_rec else "",
        "mtime_at_version": file_rec.get("source_mtime") if file_rec else None,
        "size_at_version": file_rec.get("file_size_bytes") if file_rec else None,
        "content_hash": file_rec.get("content_hash") if file_rec else None,
        "scan_run_id": scan_run_id,
        "notes": "File reappeared in source share" + (" (restored from trash)" if was_in_trash else ""),
    })

    log.info("lifecycle.restored", bulk_file_id=bulk_file_id, was_in_trash=was_in_trash)


async def move_to_trash(bulk_file_id: str) -> None:
    """Move a marked_for_deletion file to .trash/ (grace period expired)."""
    now = datetime.now(timezone.utc).isoformat()
    file_rec = await _get_bulk_file(bulk_file_id)

    # Move .md to .trash/ if it exists
    if file_rec:
        output_path = file_rec.get("output_path")
        if output_path:
            original = Path(output_path)
            trash_dest = get_trash_path(_output_root(), original)
            if original.exists():
                try:
                    trash_dest.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(shutil.move, str(original), str(trash_dest))
                    log.info("lifecycle.moved_to_trash", path=str(original), trash=str(trash_dest))
                except OSError as exc:
                    log.warning("lifecycle.trash_move_failed", error=str(exc))

            # Remove from Meilisearch
            try:
                from core.search_indexer import get_search_indexer
                indexer = get_search_indexer()
                if indexer:
                    source_path = file_rec.get("source_path", "")
                    await indexer.remove_document(source_path)
            except Exception as exc:
                log.warning("lifecycle.trash_deindex_failed", error=str(exc))

    await update_bulk_file(
        bulk_file_id,
        lifecycle_status="in_trash",
        moved_to_trash_at=now,
    )

    sf_id = file_rec.get("source_file_id") if file_rec else None
    if sf_id:
        await update_source_file(sf_id, lifecycle_status="in_trash", moved_to_trash_at=now)

    version_num = await get_next_version_number(bulk_file_id)
    await create_version_snapshot(bulk_file_id, {
        "version_number": version_num,
        "change_type": "trashed",
        "path_at_version": file_rec["source_path"] if file_rec else "",
        "size_at_version": file_rec.get("file_size_bytes") if file_rec else None,
        "content_hash": file_rec.get("content_hash") if file_rec else None,
        "notes": "Grace period expired, moved to trash",
    })

    log.info("lifecycle.trashed", bulk_file_id=bulk_file_id)


async def purge_file(bulk_file_id: str) -> None:
    """Permanently delete a trashed file (retention expired)."""
    now = datetime.now(timezone.utc).isoformat()
    file_rec = await _get_bulk_file(bulk_file_id)

    # Delete .md from .trash/ if it exists
    if file_rec:
        output_path = file_rec.get("output_path")
        if output_path:
            trash_file = get_trash_path(_output_root(), Path(output_path))
            if trash_file.exists():
                try:
                    await asyncio.to_thread(trash_file.unlink)
                    log.info("lifecycle.purged_file", path=str(trash_file))
                except OSError as exc:
                    log.warning("lifecycle.purge_delete_failed", error=str(exc))

    await update_bulk_file(
        bulk_file_id,
        lifecycle_status="purged",
        purged_at=now,
    )

    sf_id = file_rec.get("source_file_id") if file_rec else None
    if sf_id:
        await update_source_file(sf_id, lifecycle_status="purged", purged_at=now)

    version_num = await get_next_version_number(bulk_file_id)
    await create_version_snapshot(bulk_file_id, {
        "version_number": version_num,
        "change_type": "purged",
        "path_at_version": file_rec["source_path"] if file_rec else "",
        "notes": "Trash retention expired, permanently deleted",
    })

    log.info("lifecycle.purged", bulk_file_id=bulk_file_id)


# ── In-memory progress for empty-trash background task ───────────────────────
#
# v0.32.6: status dict carries `started_at_epoch` and
# `last_progress_at_epoch` so the frontend can render elapsed time
# and "last update" relative to actual work, not relative to when
# the user happened to click into the page. Both are unix-epoch
# floats (seconds since 1970, server clock); the frontend
# multiplies by 1000 to compare against `Date.now()`.
# ── Active-ops registry-backed empty-trash state (Task 17, v0.35.0) ────────
# Replaces the legacy `_empty_trash_status` dict.  The op_id is the only
# in-process state tracked here; `get_empty_trash_status()` (now async)
# reads total/done/errors/timestamps from the registry via
# `active_ops.get_op()`.  The legacy GET /api/trash/empty/status route
# stays as a deprecated facade.
_empty_trash_op_id: str | None = None


async def get_empty_trash_status() -> dict:
    """Return the legacy progress dict for the running (or most-recent)
    empty-trash op.  Backed by the active-ops registry as of v0.35.0;
    served via the deprecated GET /api/trash/empty/status facade.
    """
    if _empty_trash_op_id is None:
        return {
            "running": False, "total": 0, "done": 0, "errors": 0,
            "started_at_epoch": 0.0, "last_progress_at_epoch": 0.0,
        }
    from core import active_ops as _active_ops
    op = await _active_ops.get_op(_empty_trash_op_id)
    if op is None:
        return {
            "running": False, "total": 0, "done": 0, "errors": 0,
            "started_at_epoch": 0.0, "last_progress_at_epoch": 0.0,
        }
    return {
        "running": op.finished_at_epoch is None,
        "total": op.total or 0,
        "done": op.done or 0,
        "errors": op.errors or 0,
        "started_at_epoch": op.started_at_epoch,
        "last_progress_at_epoch": op.last_progress_at_epoch,
    }


async def purge_all_trash() -> int:
    """Batch-purge all trashed files. Runs as a background task.

    Strategy: batch DB updates in chunks of 200 to keep the write-queue
    responsive, interleaving with asyncio.sleep(0) to yield to the event
    loop between batches. Disk deletions run in a thread pool.

    Active-ops registry (v0.35.0): registers a ``trash.empty`` op so
    progress is visible in /api/active-ops; cooperatively cancellable
    via ``active_ops.is_cancelled(op_id)`` polled at the top of each
    chunk loop iteration.  No second cancel surface is introduced
    (recon §D.1) — the registry's flag is the only signal.
    """
    global _empty_trash_op_id

    if _empty_trash_op_id is not None:
        log.warning("empty_trash.already_running")
        return 0

    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="trash.empty",
        label="Emptying trash",
        icon="\U0001F5D1",  # 🗑
        origin_url="/trash.html",
        started_by="operator",
        cancellable=True,
    )
    _empty_trash_op_id = op_id

    error_msg: str | None = None
    done = 0
    errors = 0

    try:
        from core.database import get_source_files_by_lifecycle_status

        # v0.32.3: pass limit=None so we get ALL in_trash rows in one
        # call. Previously the underlying helper defaulted to 500,
        # so a 60K-row trash pile required 120+ Empty-Trash clicks.
        source_files = await get_source_files_by_lifecycle_status(
            "in_trash", limit=None,
        )
        if not source_files:
            return 0

        # Collect all bulk_file IDs and their trash paths
        bf_ids: list[str] = []
        sf_ids: list[str] = []
        trash_paths: list[Path] = []

        for sf in source_files:
            sf_ids.append(sf["id"])
            bf_rows = await db_fetch_all(
                "SELECT id, output_path FROM bulk_files WHERE source_file_id = ?",
                (sf["id"],),
            )
            for bf in bf_rows:
                bf_ids.append(bf["id"])
                output_path = bf.get("output_path")
                if output_path:
                    tp = get_trash_path(_output_root(), Path(output_path))
                    if tp.exists():
                        trash_paths.append(tp)

        await active_ops.update_op(op_id, total=len(bf_ids))
        log.info("empty_trash.starting", total_bf=len(bf_ids), total_sf=len(sf_ids),
                 trash_files=len(trash_paths))

        # Phase 1: Delete disk files in thread pool (non-blocking)
        async def _delete_file(p: Path) -> None:
            try:
                await asyncio.to_thread(p.unlink)
            except OSError:
                pass

        # Delete in parallel batches of 50
        for i in range(0, len(trash_paths), 50):
            if active_ops.is_cancelled(op_id):
                error_msg = "Cancelled by operator"
                break
            batch = trash_paths[i:i + 50]
            await asyncio.gather(*[_delete_file(p) for p in batch])
            await asyncio.sleep(0)

        # Phase 2: Batch UPDATE bulk_files in chunks of 200
        if error_msg is None:
            now = datetime.now(timezone.utc).isoformat()
            chunk_size = 200
            for i in range(0, len(bf_ids), chunk_size):
                if active_ops.is_cancelled(op_id):
                    error_msg = "Cancelled by operator"
                    break
                chunk = bf_ids[i:i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                await db_execute(
                    f"UPDATE bulk_files SET lifecycle_status='purged', purged_at=? "
                    f"WHERE id IN ({placeholders})",
                    (now, *chunk),
                )
                done += len(chunk)
                await active_ops.update_op(op_id, done=done, errors=errors)
                await asyncio.sleep(0)  # yield to event loop

            # Phase 3: Batch UPDATE source_files in chunks of 200
            for i in range(0, len(sf_ids), chunk_size):
                if active_ops.is_cancelled(op_id):
                    error_msg = "Cancelled by operator"
                    break
                chunk = sf_ids[i:i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                await db_execute(
                    f"UPDATE source_files SET lifecycle_status='purged', purged_at=? "
                    f"WHERE id IN ({placeholders})",
                    (now, *chunk),
                )
                await asyncio.sleep(0)

        log.info("empty_trash.complete", purged=done,
                 cancelled=(error_msg is not None))
        return done

    except Exception as exc:
        errors += 1
        error_msg = f"{type(exc).__name__}: {exc}"
        log.error("empty_trash.failed", error=str(exc))
        return done
    finally:
        # Reflect any incremental error count we accumulated
        if errors > 0:
            try:
                await active_ops.update_op(op_id, errors=errors)
            except Exception:
                pass
        await active_ops.finish_op(op_id, error_msg=error_msg)
        _empty_trash_op_id = None


# ── Active-ops registry-backed restore-all state (Task 18, v0.35.0) ─────────
# Mirrors the empty-trash pattern in Task 17.  The op_id is the only
# in-process state tracked here; `get_restore_all_status()` (now async)
# reads total/done/errors/timestamps from the registry via
# `active_ops.get_op()`.  The legacy GET /api/trash/restore-all/status
# route stays as a deprecated facade.
_restore_all_op_id: str | None = None


async def get_restore_all_status() -> dict:
    """Return the legacy progress dict for the running (or most-recent)
    restore-all op.  Backed by the active-ops registry as of v0.35.0;
    served via the deprecated GET /api/trash/restore-all/status facade.
    """
    if _restore_all_op_id is None:
        return {
            "running": False, "total": 0, "done": 0, "errors": 0,
            "started_at_epoch": 0.0, "last_progress_at_epoch": 0.0,
        }
    from core import active_ops as _active_ops
    op = await _active_ops.get_op(_restore_all_op_id)
    if op is None:
        return {
            "running": False, "total": 0, "done": 0, "errors": 0,
            "started_at_epoch": 0.0, "last_progress_at_epoch": 0.0,
        }
    return {
        "running": op.finished_at_epoch is None,
        "total": op.total or 0,
        "done": op.done or 0,
        "errors": op.errors or 0,
        "started_at_epoch": op.started_at_epoch,
        "last_progress_at_epoch": op.last_progress_at_epoch,
    }


async def restore_all_trash() -> int:
    """Restore all trashed files back to active. Runs as background task.

    Active-ops registry (v0.35.0): registers a ``trash.restore_all`` op
    so progress is visible in /api/active-ops; cooperatively cancellable
    via ``active_ops.is_cancelled(op_id)`` polled at the top of each
    per-row loop iteration.  No second cancel surface is introduced
    (recon §D.2) — the registry's flag is the only signal.
    """
    global _restore_all_op_id

    if _restore_all_op_id is not None:
        log.warning("restore_all.already_running")
        return 0

    from core import active_ops

    op_id = await active_ops.register_op(
        op_type="trash.restore_all",
        label="Restoring all from trash",
        icon="♻",  # ♻
        origin_url="/trash.html",
        started_by="operator",
        cancellable=True,
    )
    _restore_all_op_id = op_id

    error_msg: str | None = None
    done = 0
    errors = 0

    try:
        from core.database import get_source_files_by_lifecycle_status
        # v0.32.3: ALL rows in one call (was capped at 500).
        source_files = await get_source_files_by_lifecycle_status(
            "in_trash", limit=None,
        )
        bf_ids: list[str] = []
        for sf in source_files:
            rows = await db_fetch_all(
                "SELECT id FROM bulk_files WHERE source_file_id = ?", (sf["id"],),
            )
            bf_ids.extend(r["id"] for r in rows)

        await active_ops.update_op(op_id, total=len(bf_ids))
        log.info("restore_all.starting", total=len(bf_ids))

        for i, bf_id in enumerate(bf_ids):
            if active_ops.is_cancelled(op_id):
                error_msg = "Cancelled by operator"
                break
            try:
                await restore_file(bf_id, scan_run_id="bulk_restore")
                done += 1
            except Exception:
                errors += 1
            await active_ops.update_op(op_id, done=done, errors=errors)
            if (i + 1) % 50 == 0:
                await asyncio.sleep(0)

        log.info("restore_all.complete", restored=done, errors=errors,
                 cancelled=(error_msg is not None))
        return done

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.error("restore_all.failed", error=str(exc))
        return done
    finally:
        await active_ops.finish_op(op_id, error_msg=error_msg)
        _restore_all_op_id = None


async def record_file_move(
    bulk_file_id: str, old_path: str, new_path: str, scan_run_id: str
) -> None:
    """Record that a file was moved (detected via content hash match)."""
    file_rec = await _get_bulk_file(bulk_file_id)

    await update_bulk_file(
        bulk_file_id,
        source_path=new_path,
        previous_path=old_path,
        lifecycle_status="active",
    )

    sf_id = file_rec.get("source_file_id") if file_rec else None
    if sf_id:
        await update_source_file(sf_id, source_path=str(new_path), previous_path=str(old_path), lifecycle_status="active")

    version_num = await get_next_version_number(bulk_file_id)
    await create_version_snapshot(bulk_file_id, {
        "version_number": version_num,
        "change_type": "moved",
        "path_at_version": new_path,
        "mtime_at_version": file_rec.get("source_mtime") if file_rec else None,
        "size_at_version": file_rec.get("file_size_bytes") if file_rec else None,
        "content_hash": file_rec.get("content_hash") if file_rec else None,
        "scan_run_id": scan_run_id,
        "notes": f"Moved from {old_path}",
    })

    log.info("lifecycle.moved", bulk_file_id=bulk_file_id, old=old_path, new=new_path)


async def record_content_change(
    bulk_file_id: str,
    old_md_path: Path | None,
    new_md_path: Path | None,
    scan_run_id: str,
) -> None:
    """Record a content change with diff summary and patch."""
    from core.differ import compute_diff

    old_text = ""
    new_text = ""

    if old_md_path and old_md_path.exists():
        try:
            old_text = old_md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    if new_md_path and new_md_path.exists():
        try:
            new_text = new_md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    diff = compute_diff(old_text, new_text)

    file_rec = await _get_bulk_file(bulk_file_id)
    version_num = await get_next_version_number(bulk_file_id)
    await create_version_snapshot(bulk_file_id, {
        "version_number": version_num,
        "change_type": "content_change",
        "path_at_version": file_rec["source_path"] if file_rec else "",
        "mtime_at_version": file_rec.get("source_mtime") if file_rec else None,
        "size_at_version": file_rec.get("file_size_bytes") if file_rec else None,
        "content_hash": file_rec.get("content_hash") if file_rec else None,
        "diff_summary": json.dumps(diff.summary),
        "diff_patch": diff.patch,
        "diff_truncated": 1 if diff.patch_truncated else 0,
        "scan_run_id": scan_run_id,
    })

    log.info(
        "lifecycle.content_change",
        bulk_file_id=bulk_file_id,
        lines_added=diff.lines_added,
        lines_removed=diff.lines_removed,
    )


async def recover_moving_files():
    """On startup, reset any files stuck in transitional states (crash recovery)."""
    from core.database import db_fetch_all, db_execute
    # Check for any source_files stuck in non-terminal transitional states
    # (This is a safety net — the current code doesn't use a 'moving' status,
    # but future refactors might. No-op if no rows match.)
    try:
        rows = await db_fetch_all(
            "SELECT id FROM source_files WHERE lifecycle_status = 'moving'"
        )
        for row in rows:
            log.warning("lifecycle.recovering_stuck_move", file_id=row["id"])
            await db_execute(
                "UPDATE source_files SET lifecycle_status = 'marked_for_deletion' WHERE id = ?",
                (row["id"],),
            )
        if rows:
            log.info("lifecycle.recovery_complete", count=len(rows))
    except Exception as e:
        log.warning("lifecycle.recovery_failed", error=str(e))
