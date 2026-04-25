"""
Image analysis queue management API.

POST /api/analysis/pause                      — pause batch submission
POST /api/analysis/resume                     — resume batch submission
GET  /api/analysis/status                     — pause flag + per-status counts
POST /api/analysis/cancel-pending             — reset batched rows to pending
GET  /api/analysis/batches                    — list batches
GET  /api/analysis/batches/{batch_id}/files   — files in a batch
POST /api/analysis/exclude                    — mark rows excluded
GET  /api/analysis/files/{source_file_id}/download — stream the source file
GET  /api/analysis/files/{source_file_id}/preview  — serve image file inline

All endpoints require OPERATOR role (admin/manager also permitted via role
hierarchy).

Note: /files/* download + preview endpoints live here (rather than a separate
files router) for cohesion with the batch management UI, which is the sole
consumer. If additional file-serving endpoints accumulate outside the analysis
context, a dedicated `api/routes/files.py` would be the right place to split
them out.
"""

from __future__ import annotations

import asyncio
import mimetypes
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import get_preference, set_preference
from core.db.analysis import (
    cancel_all_batched,
    exclude_files,
    get_analysis_stats,
    get_batch_files,
    get_batches,
    get_pending_files,
    is_image_extension,
)

_VALID_STATUS_FILTERS = {"pending", "batched", "completed", "failed", "excluded"}


def _parse_status_filter(status: str | None) -> str | None:
    """Return a validated status filter or raise 400."""
    if status is None or status == "":
        return None
    if status not in _VALID_STATUS_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid status; must be one of {sorted(_VALID_STATUS_FILTERS)}",
        )
    return status
from core.db.connection import db_fetch_one, db_fetch_all
from core.path_utils import is_path_under_allowed_root

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── Pydantic bodies ──────────────────────────────────────────────────────────

class ExcludeRequest(BaseModel):
    file_ids: list[str]


class PauseRequest(BaseModel):
    """Pause duration options (v0.30.0).

    - `duration_hours`: positive number → pause until (now + duration_hours)
    - `until_off_hours`: true → pause until the next time we enter off-hours
      (based on the existing scanner_business_hours_* preferences)
    - None / empty body → indefinite pause (legacy behaviour)
    """
    duration_hours: float | None = None
    until_off_hours: bool | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────

async def _compute_off_hours_pause_until() -> "datetime | None":
    """Return a UTC datetime for the next business-hours end boundary,
    or None if the 'until off-hours' option can't be resolved. Uses
    the same scanner_business_hours_start / _end preferences that
    govern the scheduler's off-hours behavior.
    """
    from datetime import datetime, timedelta, timezone
    try:
        end_raw = await get_preference("scanner_business_hours_end") or "22:00"
        end_hour = int(end_raw.split(":")[0])
    except (AttributeError, ValueError, IndexError):
        return None
    # Build the next local-time boundary at end_hour on today (or tomorrow
    # if we're already past it). Use system-local time to match scheduler
    # semantics, then convert to UTC for storage.
    now_local = datetime.now().astimezone()
    boundary = now_local.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if boundary <= now_local:
        boundary = boundary + timedelta(days=1)
    return boundary.astimezone(timezone.utc)


@router.post("/pause")
async def pause_analysis(
    body: PauseRequest | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Pause analysis submission. v0.30.0: optional duration.

    - No body, or `{}`, or `duration_hours=None until_off_hours=None`
      → indefinite pause (backward compatible).
    - `duration_hours=N` → pause until now + N hours.
    - `until_off_hours=true` → pause until next off-hours boundary.
    """
    from datetime import datetime, timedelta, timezone

    body = body or PauseRequest()
    pause_until: datetime | None = None
    mode = "indefinite"

    if body.until_off_hours:
        pause_until = await _compute_off_hours_pause_until()
        mode = "until_off_hours"
    elif body.duration_hours is not None:
        if body.duration_hours <= 0 or body.duration_hours > 168:
            raise HTTPException(
                status_code=400,
                detail="duration_hours must be > 0 and <= 168 (1 week)",
            )
        pause_until = datetime.now(timezone.utc) + timedelta(hours=body.duration_hours)
        mode = f"{body.duration_hours}h"

    await set_preference("analysis_submission_paused", "true")
    await set_preference(
        "analysis_pause_until",
        pause_until.isoformat() if pause_until else "",
    )

    log.info(
        "analysis.paused",
        user=user.email,
        mode=mode,
        pause_until=pause_until.isoformat() if pause_until else None,
    )
    return {
        "status": "paused",
        "mode": mode,
        "pause_until": pause_until.isoformat() if pause_until else None,
    }


@router.post("/resume")
async def resume_analysis(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Resume analysis submission immediately. v0.30.0: also clears
    any timed-pause deadline so a future Pause click doesn't
    accidentally inherit an old pause_until value."""
    await set_preference("analysis_submission_paused", "false")
    await set_preference("analysis_pause_until", "")
    log.info("analysis.resumed", user=user.email)
    return {"status": "running"}


@router.get("/status")
async def analysis_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return pause flag + per-status counts (including excluded).
    v0.30.0: also returns pause_until + auto-resumes when expired."""
    from datetime import datetime, timezone

    paused = (await get_preference("analysis_submission_paused")) == "true"
    pause_until_raw = await get_preference("analysis_pause_until") or ""
    pause_until: datetime | None = None
    if paused and pause_until_raw:
        try:
            pause_until = datetime.fromisoformat(pause_until_raw)
            if pause_until.tzinfo is None:
                pause_until = pause_until.replace(tzinfo=timezone.utc)
        except ValueError:
            pause_until = None

    # Auto-resume if the deadline has passed. Do it here (a read path) so
    # the UI's next status poll always reflects the correct state even if
    # the worker hasn't polled in the meantime.
    if paused and pause_until is not None and datetime.now(timezone.utc) >= pause_until:
        await set_preference("analysis_submission_paused", "false")
        await set_preference("analysis_pause_until", "")
        paused = False
        pause_until = None
        log.info("analysis.auto_resumed", reason="pause_until_expired")

    stats = await get_analysis_stats()

    # get_analysis_stats only populates the 4 canonical statuses; query
    # excluded directly.
    excl_row = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM analysis_queue WHERE status = 'excluded'"
    )
    excluded_count = excl_row["cnt"] if excl_row else 0

    counts = {
        "pending": stats.get("pending", 0),
        "batched": stats.get("batched", 0),
        "completed": stats.get("completed", 0),
        "failed": stats.get("failed", 0),
        "excluded": excluded_count,
    }
    return {
        "paused": paused,
        "pause_until": pause_until.isoformat() if pause_until else None,
        "counts": counts,
    }


@router.post("/cancel-pending")
async def cancel_pending(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Reset all batched rows back to pending."""
    reset = await cancel_all_batched()
    log.info("analysis.cancel_pending", user=user.email, reset=reset)
    return {"reset": reset}


@router.get("/batches")
async def list_batches(
    status: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """List all analysis batches.

    Optional `?status=` filter restricts per-batch counts/sizes to
    rows with that status (v0.29.4). Batches with zero matching rows
    are omitted. Derived batch status is unaffected by the filter.
    """
    filt = _parse_status_filter(status)
    batches = await get_batches(status_filter=filt)
    return {"batches": batches}


@router.get("/batches/{batch_id}/files")
async def batch_files(
    batch_id: str,
    status: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return files in a batch.

    Optional `?status=` filter restricts to rows with that status.
    """
    filt = _parse_status_filter(status)
    files = await get_batch_files(batch_id, status_filter=filt)
    return {"files": files}


@router.get("/pending-files")
async def pending_files(
    limit: int = 100,
    offset: int = 0,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return unbatched pending files, paginated (v0.29.4).

    Pending rows have `batch_id IS NULL` so they're invisible to
    /batches. The batch-management page renders them as a synthetic
    "Pending (not yet batched)" pseudo-batch when the Pending counter
    is clicked.
    """
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400, detail="limit must be between 1 and 500"
        )
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    return await get_pending_files(limit=limit, offset=offset)


@router.post("/exclude")
async def exclude(
    body: ExcludeRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Mark the given analysis_queue ids as excluded."""
    count = await exclude_files(body.file_ids)
    log.info(
        "analysis.exclude",
        user=user.email,
        requested=len(body.file_ids),
        excluded=count,
    )
    return {"excluded": count}


@router.get("/circuit-breaker")
async def circuit_breaker_state(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return the vision-API circuit breaker state (v0.29.9).

    Used by the batch-management page to render a banner when the
    breaker is open. Status values: closed / open / half_open.
    """
    from core.vision_circuit_breaker import state_snapshot
    return state_snapshot()


@router.post("/circuit-breaker/reset")
async def circuit_breaker_reset(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Manually reset the vision-API circuit breaker to closed.

    Useful when an operator has fixed an upstream issue and wants to
    retry immediately without waiting out the cooldown.
    """
    from core.vision_circuit_breaker import reset as cb_reset
    cb_reset()
    log.info("analysis.circuit_breaker_manually_reset", user=user.email)
    return {"status": "closed"}


@router.post("/queue/{entry_id}/reanalyze")
async def reanalyze_queue_entry(
    entry_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Re-analyze one row by DELETE + re-INSERT (v0.31.0).

    The previous v0.30.4 implementation did UPDATE-in-place, which
    left the original row's id / enqueued_at intact and only cleared
    the result columns. The user wanted a true clean slate so we now:

      1. SELECT the row to capture (source_path, content_hash, job_id,
         scan_run_id, file_category) — the identity columns needed to
         re-enqueue it.
      2. DELETE the row entirely.
      3. INSERT a fresh row via the canonical
         `enqueue_for_analysis(...)` path. New id, fresh enqueued_at,
         retry_count=0, all output columns NULL.

    Why this is safer than UPDATE-in-place:
      - No risk of forgetting to clear a column that gets added in a
        future schema change — the row is brand-new.
      - Matches the operator's mental model ("treat as if scanned for
        the first time").
      - `enqueue_for_analysis` is the single canonical insertion path,
        so any future enqueue-time logic (validation, hashing, etc.)
        is automatically applied.

    Trade-off: external systems that cached `analysis_queue.id` lose
    those references. None known to do this currently — see
    `docs/gotchas.md` (Re-analyze section).
    """
    from core.database import get_db
    from core.db.connection import db_write_with_retry
    from core.db.analysis import enqueue_for_analysis

    row = await db_fetch_one(
        "SELECT id, source_path, content_hash, job_id, scan_run_id, file_category "
        "FROM analysis_queue WHERE id = ?",
        (entry_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Analysis entry not found")

    async def _delete_one():
        async with get_db() as conn:
            await conn.execute(
                "DELETE FROM analysis_queue WHERE id = ?", (entry_id,),
            )
            await conn.commit()
    await db_write_with_retry(_delete_one)

    new_id = await enqueue_for_analysis(
        source_path=row["source_path"],
        content_hash=row["content_hash"],
        job_id=row["job_id"],
        scan_run_id=row["scan_run_id"],
        file_category=row["file_category"] or "image",
    )
    log.info(
        "analysis.reanalyze_queued",
        user=user.email,
        old_entry_id=entry_id,
        new_entry_id=new_id,
    )
    return {
        "status": "queued",
        "old_entry_id": entry_id,
        "new_entry_id": new_id,
    }


# v0.31.0: bulk re-analyze.
class BulkReanalyzeRequest(BaseModel):
    """Filters for selecting which analysis_queue rows to re-analyze.

    At least one filter is required (the API refuses "match every
    row" requests). If no `status` is given, defaults to "completed".

    `dry_run` (default true) returns the count + a sample of the
    matched rows without modifying anything. The frontend should
    always preview first, then re-call with `dry_run=false` after the
    operator confirms.
    """
    analyzed_before_iso: str | None = None
    analyzed_after_iso: str | None = None
    provider_id: str | None = None
    model: str | None = None
    status: str | None = "completed"
    dry_run: bool = True


@router.post("/queue/reanalyze-bulk")
async def reanalyze_bulk(
    body: BulkReanalyzeRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Bulk re-analyze every row matching the given filter (v0.31.0).

    Same DELETE + re-INSERT semantics as the per-row endpoint —
    rows are deleted entirely and re-enqueued via the canonical
    `enqueue_for_analysis` path. Returns:

      - `dry_run=true`  → {matched, sample, exceeds_cap}
      - `dry_run=false` → {deleted, re_enqueued, new_entry_ids,
                          dropped (rows that re-enqueue declined to
                          re-insert because they were already
                          completed with the same hash)}

    Hard cap of 10,000 rows per call (`BULK_REANALYZE_CAP`). Above
    that, the endpoint refuses with 400 — split the date range and
    try again. Filters are AND'd together. Status defaults to
    `completed`. Exclusions: at least one filter (provider, model, a
    date bound, or a non-empty status) must be supplied — the API
    refuses an empty filter set.
    """
    from core.db.analysis import (
        BULK_REANALYZE_CAP,
        delete_rows_by_ids,
        enqueue_for_analysis,
        find_rows_for_bulk_reanalyze,
    )
    from core.db.connection import db_write_with_retry

    try:
        rows = await find_rows_for_bulk_reanalyze(
            analyzed_before_iso=body.analyzed_before_iso,
            analyzed_after_iso=body.analyzed_after_iso,
            provider_id=body.provider_id,
            model=body.model,
            status=body.status,
            limit=BULK_REANALYZE_CAP,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    exceeds_cap = len(rows) > BULK_REANALYZE_CAP
    if exceeds_cap:
        rows = rows[:BULK_REANALYZE_CAP]

    matched = len(rows)
    sample = [r["source_path"] for r in rows[:5]]

    if body.dry_run:
        return {
            "dry_run": True,
            "matched": matched,
            "sample": sample,
            "exceeds_cap": exceeds_cap,
            "cap": BULK_REANALYZE_CAP,
        }

    if exceeds_cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"matched > cap ({BULK_REANALYZE_CAP}); narrow the filter "
                f"(e.g. tighter date range) and retry"
            ),
        )

    if not rows:
        return {
            "dry_run": False,
            "matched": 0,
            "deleted": 0,
            "re_enqueued": 0,
            "new_entry_ids": [],
            "dropped": 0,
        }

    row_ids = [r["id"] for r in rows]

    async def _delete_all():
        return await delete_rows_by_ids(row_ids)
    deleted = await db_write_with_retry(_delete_all)

    # Re-enqueue resilience (v0.31.0 hardening): each row's enqueue is
    # wrapped in its own try so a single failure (e.g. a concurrent
    # scan racing the DELETE → INSERT window and re-inserting the same
    # source_path) doesn't abort the whole bulk pass. Counts and the
    # first ~5 failure reasons are surfaced in the response so
    # operators can investigate.
    new_entry_ids: list[str] = []
    dropped = 0
    failed = 0
    failure_samples: list[str] = []
    for r in rows:
        try:
            new_id = await enqueue_for_analysis(
                source_path=r["source_path"],
                content_hash=r["content_hash"],
                job_id=r["job_id"],
                scan_run_id=r["scan_run_id"],
                file_category=r["file_category"] or "image",
            )
        except Exception as exc:
            failed += 1
            if len(failure_samples) < 5:
                failure_samples.append(
                    f"{r['source_path']}: {type(exc).__name__}: {exc}"
                )
            log.warning(
                "analysis.reanalyze_bulk_enqueue_failed",
                source_path=r["source_path"],
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        if new_id is None:
            # `enqueue_for_analysis` returns None when the same content
            # is already completed elsewhere — shouldn't happen since
            # we just deleted the row, but be defensive.
            dropped += 1
        else:
            new_entry_ids.append(new_id)

    log.info(
        "analysis.reanalyze_bulk",
        user=user.email,
        matched=matched,
        deleted=deleted,
        re_enqueued=len(new_entry_ids),
        dropped=dropped,
        failed=failed,
        filters={
            "analyzed_before_iso": body.analyzed_before_iso,
            "analyzed_after_iso": body.analyzed_after_iso,
            "provider_id": body.provider_id,
            "model": body.model,
            "status": body.status,
        },
    )

    return {
        "dry_run": False,
        "matched": matched,
        "deleted": deleted,
        "re_enqueued": len(new_entry_ids),
        "new_entry_ids": new_entry_ids,
        "dropped": dropped,
        "failed": failed,
        "failure_samples": failure_samples,
    }


@router.get("/queue/reanalyze-filters")
async def reanalyze_filters(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return distinct provider_id + model values to populate the bulk
    re-analyze modal's dropdowns. Operators-only since the modal is
    operator-only."""
    from core.db.analysis import list_distinct_provider_models
    return await list_distinct_provider_models()


@router.get("/queue/{entry_id}")
async def queue_entry(
    entry_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return the full analysis_queue row for one id (v0.29.5).

    Powers the "View analysis result" context-menu item on the Batch
    Management page. `description` + `extracted_text` are populated for
    completed rows, `error` for failed rows; pending / batched rows
    return status-only info.
    """
    row = await db_fetch_one(
        """SELECT id, source_path, status, batch_id, content_hash,
                  enqueued_at, batched_at, analyzed_at,
                  description, extracted_text, error,
                  provider_id, model, tokens_used, retry_count
           FROM analysis_queue
           WHERE id = ?""",
        (entry_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Analysis entry not found")
    return dict(row)


async def _lookup_source_path(source_file_id: str) -> Path:
    """
    Return the absolute Path for a source_files.id, or raise 404.

    Confines the returned path to one of the configured mount roots
    (BULK_SOURCE_PATH, BULK_OUTPUT_PATH, /host/<drive>) via
    `is_path_under_allowed_root`. If the DB ever contains a crafted or
    symlinked path that resolves outside those roots, we raise 404
    (same response as "not found" — don't leak existence).
    """
    row = await db_fetch_one(
        "SELECT source_path FROM source_files WHERE id = ?", (source_file_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    p = Path(row["source_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    if not is_path_under_allowed_root(p):
        # Don't leak existence — mirror the "not found" response.
        log.warning(
            "analysis.file_access_denied",
            source_file_id=source_file_id,
            reason="path_outside_allowed_roots",
        )
        raise HTTPException(status_code=404, detail="File not found")
    return p


@router.get("/files/{source_file_id}/download")
async def download_file(
    source_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> FileResponse:
    """Stream the source file by source_files.id."""
    path = await _lookup_source_path(source_file_id)
    log.info(
        "analysis.file_access",
        user=user.email,
        source_file_id=source_file_id,
        mode="download",
    )
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type=media_type or "application/octet-stream",
    )


# ── Preview (browser-native + thumbnail fallback, v0.29.7+) ──────────────────
#
# v0.29.8: expanded both sets to cover every photo format PIL can decode in the
# current base image, plus every format mainstream Chromium/Firefox/Safari
# render natively. Source of truth: `python -c "from PIL import Image;
# Image.init(); print(Image.EXTENSION)"` inside the container. Must stay in
# sync with static/batch-management.html `_IMG_EXT`.

# Browser renders these natively — stream the raw bytes unchanged.
_NATIVE_PREVIEW_EXTS = {
    # JPEG family
    ".jpg", ".jpeg", ".jfif", ".jpe",
    # PNG family
    ".png", ".apng",
    # Other native formats
    ".gif", ".bmp", ".dib", ".webp",
    # Modern formats supported by all recent browsers
    ".avif", ".avifs",
    # Icon / cursor formats
    ".ico", ".cur",
}

# Browser CAN'T render these — generate a JPEG thumbnail via PIL.
# .eps / .ps use PIL's EpsImagePlugin which shells out to Ghostscript
# (/usr/bin/gs). .psd is read as the flat composite (good enough for preview).
_THUMBNAIL_PREVIEW_EXTS = {
    # TIFF family
    ".tif", ".tiff",
    # PostScript family (rasterized via Ghostscript)
    ".eps", ".ps",
    # JPEG 2000 family
    ".jp2", ".j2k", ".jpx", ".jpc", ".jpf", ".j2c",
    # Netpbm family
    ".ppm", ".pgm", ".pbm", ".pnm",
    # Targa family (TrueVision TGA)
    ".tga", ".icb", ".vda", ".vst",
    # SGI family
    ".sgi", ".rgb", ".rgba", ".bw",
    # Other photo/raster formats PIL decodes natively
    ".pcx", ".dds", ".icns", ".psd",
}
_ALL_PREVIEW_EXTS = _NATIVE_PREVIEW_EXTS | _THUMBNAIL_PREVIEW_EXTS

_THUMB_MAX_PX = 400
_THUMB_JPEG_QUALITY = 78
_THUMB_CACHE_SIZE = 64  # ~13 MB at 200 KB avg per thumb — bounded and small
_thumb_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


def _ext_lower(ext: str) -> str:
    return ("." + ext.lstrip(".")).lower()


def _is_previewable(ext: str) -> bool:
    return _ext_lower(ext) in _ALL_PREVIEW_EXTS


def _needs_thumbnail(ext: str) -> bool:
    return _ext_lower(ext) in _THUMBNAIL_PREVIEW_EXTS


def _generate_thumbnail_sync(path: Path) -> bytes:
    """Open `path` with PIL, thumbnail to _THUMB_MAX_PX on the longest edge,
    return JPEG bytes. Runs in a worker thread via asyncio.to_thread; must
    not touch async state."""
    # Import lazily so module load doesn't block on PIL for non-preview
    # requests (PIL pulls in C extensions and can be slow to first-import).
    from PIL import Image

    with Image.open(str(path)) as img:
        img.load()
        # Convert to a JPEG-safe mode. EPS can arrive as CMYK; TIFF may be
        # LA/P/I;16 etc. RGB is the safe common denominator for JPEG.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((_THUMB_MAX_PX, _THUMB_MAX_PX), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=_THUMB_JPEG_QUALITY, optimize=True)
        return buf.getvalue()


async def _get_cached_thumbnail(path: Path, source_file_id: str) -> bytes:
    """Return cached or freshly-rendered JPEG thumbnail bytes.

    Cache key = (source_file_id, st_mtime_ns, st_size). Any edit to the
    file changes the key so stale thumbs are never served. LRU eviction
    with _THUMB_CACHE_SIZE entries.
    """
    try:
        stat = path.stat()
    except OSError as exc:
        raise HTTPException(
            status_code=404, detail=f"File not accessible: {exc}"
        ) from exc

    cache_key = (source_file_id, stat.st_mtime_ns, stat.st_size)
    hit = _thumb_cache.get(cache_key)
    if hit is not None:
        _thumb_cache.move_to_end(cache_key)
        return hit

    try:
        thumb_bytes = await asyncio.to_thread(_generate_thumbnail_sync, path)
    except Exception as exc:
        # PIL errors bubble up as generic Exception; surface as 500 with
        # the error class + message so operators can diagnose from the
        # browser's network tab without log-diving.
        log.warning(
            "analysis.thumbnail_generation_failed",
            source_file_id=source_file_id,
            path=str(path),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Thumbnail generation failed: {type(exc).__name__}: {exc}",
        ) from exc

    _thumb_cache[cache_key] = thumb_bytes
    _thumb_cache.move_to_end(cache_key)
    while len(_thumb_cache) > _THUMB_CACHE_SIZE:
        _thumb_cache.popitem(last=False)
    return thumb_bytes


@router.get("/files/{source_file_id}/preview")
async def preview_file(
    source_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """
    Inline preview for image files, with automatic thumbnailing for
    formats browsers can't render natively.

    Native serve (raw bytes, correct Content-Type):
      .jpg / .jpeg / .png / .gif / .bmp / .webp

    Thumbnail generation (PIL → 400px JPEG, LRU-cached):
      .tif / .tiff   (PIL native)
      .eps           (PIL EpsImagePlugin → Ghostscript /usr/bin/gs)

    Any other extension returns 404. The (source_file_id, mtime, size)
    cache key means unchanged files serve instantly after the first hit
    and edits invalidate automatically.
    """
    path = await _lookup_source_path(source_file_id)
    if not _is_previewable(path.suffix):
        raise HTTPException(
            status_code=404,
            detail="Preview not available for this file type",
        )

    log.info(
        "analysis.file_access",
        user=user.email,
        source_file_id=source_file_id,
        mode="preview",
        needs_thumbnail=_needs_thumbnail(path.suffix),
    )

    if _needs_thumbnail(path.suffix):
        thumb_bytes = await _get_cached_thumbnail(path, source_file_id)
        return Response(
            content=thumb_bytes,
            media_type="image/jpeg",
            headers={
                # Tell the browser it can safely cache the thumbnail for
                # a short window — the server-side cache key already
                # accounts for mtime so there's no risk of stale data.
                "Cache-Control": "private, max-age=300",
            },
        )

    # Browser-native format: stream raw file.
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        media_type=media_type or "application/octet-stream",
    )
