"""
Bulk job management API.

POST /api/bulk/jobs             — Create and start a bulk job
GET  /api/bulk/jobs             — List jobs (most recent 20)
GET  /api/bulk/jobs/{id}        — Job status and counters
GET  /api/bulk/jobs/{id}/stream — SSE stream for live progress
POST /api/bulk/jobs/{id}/pause  — Pause running job
POST /api/bulk/jobs/{id}/resume — Resume paused job
POST /api/bulk/jobs/{id}/cancel — Cancel running/paused job
GET  /api/bulk/jobs/{id}/files  — Paginated file list
GET  /api/bulk/jobs/{id}/errors — Failed files list
"""

import asyncio
import json
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth import AuthenticatedUser, UserRole, require_role
from core.stop_controller import reset_stop
from pydantic import BaseModel, Field

from core.bulk_worker import (
    BulkJob,
    BulkOcrGapFillJob,
    get_active_job,
    get_bulk_progress_queue,
    get_gap_fill_queue,
    _bulk_progress_queues,
    _gap_fill_queues,
)
from core.database import (
    create_bulk_job,
    get_bulk_files,
    now_iso,
    get_bulk_file_count,
    get_bulk_job,
    get_location,
    list_locations,
    get_ocr_gap_fill_count,
    get_path_issues,
    get_path_issue_summary,
    get_review_queue,
    get_review_queue_count,
    get_review_queue_entry,
    get_review_queue_summary,
    list_bulk_jobs,
    update_bulk_file,
    update_bulk_job_status,
    update_review_queue_entry,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/bulk", tags=["bulk"])


# ── Request/Response models ──────────────────────────────────────────────────

class CreateBulkJobRequest(BaseModel):
    source_path: str | None = Field(default=None)
    source_location_id: str | None = None
    scan_all_sources: bool = False
    output_path: str | None = Field(default=None)
    output_location_id: str | None = None
    worker_count: int = Field(default=4, ge=1, le=16)
    fidelity_tier: int = Field(default=2, ge=1, le=3)
    ocr_mode: str = Field(default="auto", pattern="^(auto|force|skip)$")
    include_adobe: bool = True


# ── POST /api/bulk/jobs ──────────────────────────────────────────────────────

@router.post("/jobs")
async def create_job(
    req: CreateBulkJobRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Create and start a new bulk conversion job."""
    # Resolve source path(s)
    source_paths: list[Path] = []
    if req.scan_all_sources:
        locs = await list_locations(type_filter="source")
        if not locs:
            raise HTTPException(status_code=422, detail="No source locations configured.")
        source_paths = [Path(loc["path"]) for loc in locs]
    elif req.source_location_id:
        loc = await get_location(req.source_location_id)
        if not loc:
            raise HTTPException(status_code=422, detail=f"Location not found: {req.source_location_id}")
        source_paths = [Path(loc["path"])]
    elif req.source_path:
        source_paths = [Path(req.source_path)]
    else:
        raise HTTPException(status_code=422, detail="Provide source_path, source_location_id, or scan_all_sources")

    # Resolve output path from location ID or raw path
    output_path = req.output_path
    if req.output_location_id:
        loc = await get_location(req.output_location_id)
        if not loc:
            raise HTTPException(status_code=422, detail=f"Location not found: {req.output_location_id}")
        output_path = loc["path"]
    if not output_path:
        raise HTTPException(status_code=422, detail="Provide either output_path or output_location_id")

    output = Path(output_path)

    # Validate paths
    for sp in source_paths:
        if not sp.exists() or not sp.is_dir():
            raise HTTPException(
                status_code=422,
                detail=f"Source path does not exist or is not a directory: {sp}",
            )
    if not output.parent.exists():
        raise HTTPException(
            status_code=422,
            detail=f"Output path parent does not exist: {output.parent}",
        )

    # Check for already-running job
    jobs = await list_bulk_jobs(limit=5)
    for job in jobs:
        if job["status"] in ("running", "scanning"):
            raise HTTPException(
                status_code=409,
                detail="A bulk job is already running. Wait for it to complete before starting a new one.",
            )

    # Create DB record (store first source path; job scans all)
    job_id = await create_bulk_job(
        source_path=str(source_paths[0]),
        output_path=output_path,
        worker_count=req.worker_count,
        include_adobe=req.include_adobe,
        fidelity_tier=req.fidelity_tier,
        ocr_mode=req.ocr_mode,
    )

    # Clear any previous stop flag before starting
    reset_stop()

    # Ensure output dir exists
    output.mkdir(parents=True, exist_ok=True)

    # Start job in background
    bulk_job = BulkJob(
        job_id=job_id,
        source_paths=source_paths,
        output_path=output,
        worker_count=req.worker_count,
        fidelity_tier=req.fidelity_tier,
        ocr_mode=req.ocr_mode,
        include_adobe=req.include_adobe,
    )
    asyncio.create_task(bulk_job.run())

    return {"job_id": job_id, "stream_url": f"/api/bulk/jobs/{job_id}/stream"}


# ── GET /api/bulk/jobs ───────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """List recent bulk jobs."""
    jobs = await list_bulk_jobs(limit=20)
    return {"jobs": jobs}


# ── GET /api/bulk/jobs/{job_id} ──────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def job_status(
    job_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Get bulk job status and counters, including progress/ETA."""
    from core.progress_tracker import format_eta

    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    # Build progress block from job fields
    completed = (job.get("converted") or 0) + (job.get("failed") or 0) + (job.get("skipped") or 0)
    total = job.get("total_files")
    pct = round(min(100.0, completed / total * 100), 1) if total and total > 0 else None
    job["progress"] = {
        "completed": completed,
        "total": total,
        "count_ready": True,
        "eta_seconds": job.get("eta_seconds"),
        "files_per_second": job.get("files_per_second"),
        "eta_human": format_eta(job.get("eta_seconds")),
        "percent": pct,
    }
    return job


# ── GET /api/bulk/jobs/{job_id}/stream ───────────────────────────────────────

@router.get("/jobs/{job_id}/stream")
async def job_stream(
    job_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """SSE stream for live bulk job progress."""
    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    async def event_generator():
        event_id = 0

        # If job already complete, emit summary and review queue state
        if job["status"] in ("completed", "cancelled", "failed"):
            event_id += 1
            yield _format_sse("job_complete", {
                "job_id": job_id,
                "converted": job.get("converted", 0),
                "skipped": job.get("skipped", 0),
                "failed": job.get("failed", 0),
                "adobe_indexed": job.get("adobe_indexed", 0),
                "review_queue_count": job.get("review_queue_count", 0),
                "duration_ms": 0,
            }, event_id)
            # Include review queue summary if there are review items
            rq_count = job.get("review_queue_count", 0)
            if rq_count and rq_count > 0:
                summary = await get_review_queue_summary(job_id)
                event_id += 1
                yield _format_sse("review_queue_summary", {
                    "job_id": job_id,
                    **summary,
                }, event_id)
            event_id += 1
            yield _format_sse("done", {}, event_id)
            return

        # Wait for queue to appear
        queue = get_bulk_progress_queue(job_id)
        if queue is None:
            for _ in range(20):
                await asyncio.sleep(0.3)
                queue = get_bulk_progress_queue(job_id)
                if queue is not None:
                    break
            if queue is None:
                yield _format_sse("done", {}, 0)
                return

        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            event_id += 1
            yield _format_sse(msg["event"], msg["data"], event_id)

            if msg["event"] == "done":
                break

        # Cleanup
        _bulk_progress_queues.pop(job_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(event: str, data: dict, event_id: int = 0) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


# ── POST /api/bulk/jobs/{job_id}/pause ───────────────────────────────────────

@router.post("/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Pause a running bulk job."""
    active = get_active_job(job_id)
    if not active:
        raise HTTPException(status_code=404, detail="Job not found or not running.")
    await active.pause()
    return {"status": "paused", "job_id": job_id}


# ── POST /api/bulk/jobs/{job_id}/resume ──────────────────────────────────────

@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Resume a paused bulk job."""
    active = get_active_job(job_id)
    if not active:
        raise HTTPException(status_code=404, detail="Job not found or not running.")
    await active.resume()
    return {"status": "running", "job_id": job_id}


# ── POST /api/bulk/jobs/{job_id}/cancel ──────────────────────────────────────

@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Cancel a running or paused bulk job."""
    active = get_active_job(job_id)
    if not active:
        raise HTTPException(status_code=404, detail="Job not found or not running.")
    await active.cancel()
    return {"status": "cancelled", "job_id": job_id}


# ── GET /api/bulk/jobs/{job_id}/files ────────────────────────────────────────

@router.get("/jobs/{job_id}/files")
async def job_files(
    job_id: str,
    status: str | None = None,
    ext: str | None = None,
    page: int = 1,
    per_page: int = 50,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Paginated file list for a bulk job."""
    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    offset = (max(1, page) - 1) * per_page
    files = await get_bulk_files(
        job_id, status=status, file_ext=ext, limit=per_page, offset=offset,
    )
    total = await get_bulk_file_count(job_id, status=status)

    return {
        "job_id": job_id,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "files": files,
    }


# ── GET /api/bulk/jobs/{job_id}/errors ───────────────────────────────────────

@router.get("/jobs/{job_id}/errors")
async def job_errors(
    job_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """All failed files for a bulk job (max 1000)."""
    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    failed = await get_bulk_files(job_id, status="failed", limit=1000)
    adobe_failed = await get_bulk_files(job_id, status="adobe_failed", limit=1000)
    all_errors = failed + adobe_failed

    return {
        "job_id": job_id,
        "total_errors": len(all_errors),
        "errors": all_errors,
    }


# ── OCR Gap-Fill endpoints ─────────────────────────────────────────────────

class OcrGapFillRequest(BaseModel):
    job_id: str | None = None
    worker_count: int = Field(default=2, ge=1, le=8)
    dry_run: bool = False


@router.get("/ocr-gap-fill/pending-count")
async def gap_fill_pending_count(
    job_id: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """How many PDFs need OCR (converted without OCR stats)."""
    result = await get_ocr_gap_fill_count(job_id)
    return result


@router.post("/ocr-gap-fill")
async def start_gap_fill(
    req: OcrGapFillRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Start an OCR gap-fill pass."""
    import uuid
    gap_fill_id = uuid.uuid4().hex

    gap_job = BulkOcrGapFillJob(
        gap_fill_id=gap_fill_id,
        job_id=req.job_id,
        worker_count=req.worker_count,
        dry_run=req.dry_run,
    )

    if req.dry_run:
        result = await gap_job.run()
        return result

    # Run in background
    asyncio.create_task(gap_job.run())

    # Get quick count for the response
    count_info = await get_ocr_gap_fill_count(req.job_id)

    return {
        "gap_fill_id": gap_fill_id,
        "files_found": count_info["count"],
        "stream_url": f"/api/bulk/ocr-gap-fill/{gap_fill_id}/stream",
        "dry_run": False,
    }


@router.get("/ocr-gap-fill/{gap_fill_id}/stream")
async def gap_fill_stream(
    gap_fill_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """SSE stream for live gap-fill progress."""

    async def event_generator():
        event_id = 0

        queue = get_gap_fill_queue(gap_fill_id)
        if queue is None:
            for _ in range(20):
                await asyncio.sleep(0.3)
                queue = get_gap_fill_queue(gap_fill_id)
                if queue is not None:
                    break
            if queue is None:
                yield _format_sse("done", {}, 0)
                return

        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            event_id += 1
            yield _format_sse(msg["event"], msg["data"], event_id)

            if msg["event"] == "done":
                break

        _gap_fill_queues.pop(gap_fill_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Path issues endpoints ──────────────────────────────────────────────────

@router.get("/jobs/{job_id}/path-issues")
async def job_path_issues(
    job_id: str,
    type: str | None = None,
    page: int = 1,
    per_page: int = 50,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Return path issues for a bulk job."""
    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    offset = (max(1, page) - 1) * per_page
    issues = await get_path_issues(job_id, issue_type=type, limit=per_page, offset=offset)
    summary = await get_path_issue_summary(job_id)

    return {
        "job_id": job_id,
        "summary": summary,
        "page": page,
        "per_page": per_page,
        "total": summary["total"],
        "issues": issues,
    }


@router.get("/jobs/{job_id}/path-issues/export")
async def export_path_issues(
    job_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Export path issues as downloadable CSV."""
    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    issues = await get_path_issues(job_id, limit=100000)

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["issue_type", "source_path", "output_path", "collision_peer", "resolution", "resolved_path"])
    for issue in issues:
        writer.writerow([
            issue.get("issue_type", ""),
            issue.get("source_path", ""),
            issue.get("output_path", ""),
            issue.get("collision_peer", ""),
            issue.get("resolution", ""),
            issue.get("resolved_path", ""),
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=path-issues-{job_id[:8]}.csv"},
    )


# ── Review queue models ────────────────────────────────────────────────────

class ReviewResolveRequest(BaseModel):
    action: str = Field(..., pattern="^(convert|skip|review)$")
    notes: str | None = None


class ReviewResolveAllRequest(BaseModel):
    action: str = Field(..., pattern="^(convert|skip)$")
    notes: str | None = None


# ── GET /api/bulk/jobs/{job_id}/review-queue ──────────────────────────────

@router.get("/jobs/{job_id}/review-queue")
async def get_job_review_queue(
    job_id: str,
    status: str | None = "pending",
    page: int = 1,
    per_page: int = 50,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Return review queue entries for a bulk job."""
    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    offset = (max(1, page) - 1) * per_page
    entries = await get_review_queue(job_id, status=status, limit=per_page, offset=offset)
    summary = await get_review_queue_summary(job_id)
    total = await get_review_queue_count(job_id, status=status)

    # Add relative_path for display
    source_root = job.get("source_path", "")
    for entry in entries:
        sp = entry.get("source_path", "")
        if source_root and sp.startswith(source_root):
            entry["relative_path"] = sp[len(source_root):].lstrip("/")
        else:
            entry["relative_path"] = sp

    return {
        "job_id": job_id,
        "summary": summary,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "entries": entries,
    }


# ── POST /api/bulk/jobs/{job_id}/review-queue/resolve-all ─────────────────
# NOTE: must come before the parametric /{entry_id}/resolve route

@router.post("/jobs/{job_id}/review-queue/resolve-all")
async def resolve_all_review(
    job_id: str,
    req: ReviewResolveAllRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Bulk resolve all pending review queue entries."""
    job = await get_bulk_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    pending = await get_review_queue(job_id, status="pending", limit=10000, offset=0)
    now = now_iso()

    if req.action == "skip":
        for entry in pending:
            await update_review_queue_entry(
                entry["id"],
                status="skipped_permanently",
                resolution="skipped",
                notes=req.notes,
                resolved_at=now,
            )
            await update_bulk_file(
                entry["bulk_file_id"],
                ocr_skipped_reason="permanently_skipped",
            )
        return {"queued": len(pending), "action": "skip"}

    elif req.action == "convert":
        # Queue all for conversion in background
        for entry in pending:
            await update_review_queue_entry(entry["id"], status="converting")
        asyncio.create_task(_convert_review_batch(job_id, pending))
        return {"queued": len(pending), "action": "convert"}

    raise HTTPException(status_code=422, detail="Invalid action")


# ── POST /api/bulk/jobs/{job_id}/review-queue/{entry_id}/resolve ──────────

@router.post("/jobs/{job_id}/review-queue/{entry_id}/resolve")
async def resolve_review_entry(
    job_id: str,
    entry_id: str,
    req: ReviewResolveRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
):
    """Resolve a single review queue entry."""
    entry = await get_review_queue_entry(entry_id)
    if not entry or entry["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Review queue entry not found.")

    now = now_iso()

    if req.action == "skip":
        await update_review_queue_entry(
            entry_id,
            status="skipped_permanently",
            resolution="skipped",
            notes=req.notes,
            resolved_at=now,
        )
        await update_bulk_file(
            entry["bulk_file_id"],
            ocr_skipped_reason="permanently_skipped",
        )
        return {"entry_id": entry_id, "action": "skip", "status": "skipped_permanently", "review_url": None}

    elif req.action == "convert":
        await update_review_queue_entry(entry_id, status="converting")
        asyncio.create_task(_convert_single_review_entry(job_id, entry))
        return {"entry_id": entry_id, "action": "convert", "status": "converting", "review_url": None}

    elif req.action == "review":
        await update_review_queue_entry(entry_id, status="converting")
        batch_id = await _convert_single_review_entry(job_id, entry)
        review_url = f"/review.html?batch_id={batch_id}" if batch_id else None
        if batch_id:
            await update_review_queue_entry(
                entry_id,
                status="review_requested",
                resolution="reviewed",
                resolved_at=now,
            )
        return {"entry_id": entry_id, "action": "review", "status": "review_requested", "review_url": review_url}

    raise HTTPException(status_code=422, detail="Invalid action")


# ── Internal helpers ──────────────────────────────────────────────────────


async def _convert_single_review_entry(job_id: str, entry: dict) -> str | None:
    """Convert a single review queue file. Returns batch_id or None on failure."""
    from core.converter import ConversionOrchestrator, new_batch_id

    source_path = Path(entry["source_path"])
    if not source_path.exists():
        await update_review_queue_entry(
            entry["id"],
            status="converted",
            resolution="converted",
            notes="Source file not found",
            resolved_at=now_iso(),
        )
        return None

    try:
        batch_id = new_batch_id()
        orch = ConversionOrchestrator()
        results = await orch.convert_batch([source_path], "to_md", batch_id)

        now = now_iso()
        if results and results[0].status == "success":
            await update_review_queue_entry(
                entry["id"],
                status="converted",
                resolution="converted",
                resolved_at=now,
            )
            await update_bulk_file(
                entry["bulk_file_id"],
                status="converted",
                output_path=results[0].output_path,
            )
            _emit_review_event(job_id, "review_item_converted", {
                "entry_id": entry["id"],
                "source_path": entry["source_path"],
                "status": "converted",
                "ocr_confidence_mean": None,
                "duration_ms": results[0].duration_ms,
            })
        else:
            error_msg = results[0].error_message if results else "Unknown error"
            await update_review_queue_entry(
                entry["id"],
                status="converted",
                resolution="converted",
                notes=f"Conversion error: {error_msg}",
                resolved_at=now,
            )
            _emit_review_event(job_id, "review_item_failed", {
                "entry_id": entry["id"],
                "source_path": entry["source_path"],
                "error": error_msg,
            })
        return batch_id
    except Exception as exc:
        log.error("review_convert_failed", entry_id=entry["id"], error=str(exc))
        await update_review_queue_entry(
            entry["id"],
            status="converted",
            resolution="converted",
            notes=f"Error: {exc}",
            resolved_at=now_iso(),
        )
        _emit_review_event(job_id, "review_item_failed", {
            "entry_id": entry["id"],
            "source_path": entry["source_path"],
            "error": str(exc),
        })
        return None


async def _convert_review_batch(job_id: str, entries: list[dict]) -> None:
    """Convert all review queue entries in sequence."""
    for entry in entries:
        await _convert_single_review_entry(job_id, entry)

    # Check if all resolved
    summary = await get_review_queue_summary(job_id)
    if summary["pending"] == 0 and summary["converting"] == 0:
        _emit_review_event(job_id, "review_queue_complete", {
            "job_id": job_id,
            "converted": summary["converted"],
            "skipped_permanently": summary["skipped_permanently"],
        })


def _emit_review_event(job_id: str, event: str, data: dict) -> None:
    """Emit SSE event to the bulk job's progress queue."""
    from core.bulk_worker import _emit_bulk_event
    _emit_bulk_event(job_id, event, data)
