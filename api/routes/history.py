"""
Conversion history endpoints.

GET /api/history                — Paginated, filterable conversion history.
GET /api/history/{id}           — Single conversion record.
GET /api/history/{id}/redownload — Re-download output file(s) for a past conversion.
GET /api/history/stats          — Aggregate stats (totals, success rate, most-used format, OCR flags).
"""

import io
import json
import math
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from core.auth import AuthenticatedUser, UserRole, require_role

from api.models import (
    HistoryListResponse,
    HistoryRecord,
    OCROverallStats,
    OCRStatsBlock,
    StatsResponse,
)
from core.converter import OUTPUT_BASE
from core.database import db_fetch_all, db_fetch_one, get_preference

router = APIRouter(prefix="/api/history", tags=["history"])


def _parse_warnings(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return []


def _row_to_record(row: dict, threshold: float = 80.0) -> HistoryRecord:
    ocr_block = None
    if row.get("ocr_confidence_mean") is not None:
        ocr_block = OCRStatsBlock(
            ran=True,
            confidence_mean=row.get("ocr_confidence_mean"),
            confidence_min=row.get("ocr_confidence_min"),
            page_count=row.get("ocr_page_count"),
            pages_below_threshold=row.get("ocr_pages_below_threshold"),
            threshold=threshold,
        )
    elif bool(row.get("ocr_applied", False)):
        # OCR was detected as needed but no confidence was recorded
        ocr_block = OCRStatsBlock(ran=True, threshold=threshold)

    return HistoryRecord(
        id=row["id"],
        batch_id=row["batch_id"],
        source_filename=row["source_filename"],
        source_format=row["source_format"],
        output_filename=row["output_filename"],
        output_format=row["output_format"],
        direction=row["direction"],
        source_path=row.get("source_path"),
        output_path=row.get("output_path"),
        file_size_bytes=row.get("file_size_bytes"),
        ocr_applied=bool(row.get("ocr_applied", False)),
        ocr_flags_total=row.get("ocr_flags_total") or 0,
        ocr_flags_resolved=row.get("ocr_flags_resolved") or 0,
        status=row["status"],
        error_message=row.get("error_message"),
        duration_ms=row.get("duration_ms"),
        warnings=_parse_warnings(row.get("warnings")),
        created_at=str(row.get("created_at") or ""),
        ocr=ocr_block,
    )


# ── GET /api/history/stats  (must come before /{id} to avoid shadowing) ───────

@router.get("/stats", response_model=StatsResponse)
async def history_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Aggregate conversion statistics."""
    rows = await db_fetch_all(
        "SELECT status, source_format, duration_ms, ocr_flags_total, file_size_bytes, "
        "ocr_confidence_mean "
        "FROM conversion_history"
    )

    total = len(rows)
    success = sum(1 for r in rows if r["status"] == "success")
    errors = total - success
    rate = round(success / total * 100, 1) if total else 0.0

    format_counts: dict[str, int] = {}
    total_ocr = 0
    total_duration = 0
    total_size = 0
    ocr_confs: list[float] = []
    for r in rows:
        fmt = r.get("source_format") or "unknown"
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        total_ocr += r.get("ocr_flags_total") or 0
        total_duration += r.get("duration_ms") or 0
        total_size += r.get("file_size_bytes") or 0
        if r.get("ocr_confidence_mean") is not None:
            ocr_confs.append(r["ocr_confidence_mean"])

    most_used = max(format_counts, key=format_counts.get) if format_counts else None
    avg_duration = total_duration // total if total else 0

    # OCR aggregate stats
    threshold_str = await get_preference("ocr_confidence_threshold") or "80"
    threshold = float(threshold_str)
    ocr_overall = None
    if ocr_confs:
        ocr_overall = OCROverallStats(
            files_with_ocr=len(ocr_confs),
            mean_confidence_overall=round(sum(ocr_confs) / len(ocr_confs), 1),
            files_below_threshold=sum(1 for c in ocr_confs if c < threshold),
            threshold=threshold,
        )

    return StatsResponse(
        total_conversions=total,
        success_count=success,
        error_count=errors,
        success_rate_pct=rate,
        most_used_format=most_used,
        total_ocr_flags=total_ocr,
        total_duration_ms=total_duration,
        avg_duration_ms=avg_duration,
        total_size_bytes_processed=total_size,
        formats=format_counts,
        by_format=format_counts,
        ocr_stats=ocr_overall,
    )


# ── GET /api/history ──────────────────────────────────────────────────────────

@router.get("", response_model=HistoryListResponse)
async def list_history(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=200)] = 25,
    format: str | None = Query(default=None),
    status: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Paginated, filterable, sortable conversion history."""
    conditions = []
    params: list = []

    if format:
        conditions.append("source_format = ?")
        params.append(format)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if direction:
        conditions.append("direction = ?")
        params.append(direction)
    if search:
        conditions.append("(source_filename LIKE ? OR output_filename LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    if date_from:
        conditions.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("created_at <= ?")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Sort order
    sort_map = {
        "date_desc": "created_at DESC",
        "date_asc": "created_at ASC",
        "duration_asc": "duration_ms ASC",
        "duration_desc": "duration_ms DESC",
    }
    order_by = sort_map.get(sort or "date_desc", "created_at DESC")

    count_row = await db_fetch_one(
        f"SELECT COUNT(*) as n FROM conversion_history {where}", tuple(params)
    )
    total = count_row["n"] if count_row else 0

    # Calculate pagination (page/per_page take priority over offset/limit)
    effective_limit = per_page
    effective_offset = (page - 1) * per_page
    total_pages = max(1, math.ceil(total / per_page)) if total else 1

    rows = await db_fetch_all(
        f"SELECT * FROM conversion_history {where} ORDER BY {order_by} "
        f"LIMIT ? OFFSET ?",
        tuple(params + [effective_limit, effective_offset]),
    )

    # Get available formats and error status for filter UI
    fmt_rows = await db_fetch_all(
        "SELECT DISTINCT source_format FROM conversion_history ORDER BY source_format"
    )
    formats_available = [r["source_format"] for r in fmt_rows]

    err_row = await db_fetch_one(
        "SELECT COUNT(*) as n FROM conversion_history WHERE status = 'error'"
    )
    has_errors = (err_row["n"] if err_row else 0) > 0

    threshold_str = await get_preference("ocr_confidence_threshold") or "80"
    threshold = float(threshold_str)

    return HistoryListResponse(
        total=total,
        limit=effective_limit,
        offset=effective_offset,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        formats_available=formats_available,
        has_errors=has_errors,
        records=[_row_to_record(r, threshold) for r in rows],
    )


# ── GET /api/history/{id}/redownload ──────────────────────────────────────────

@router.get("/{record_id}/redownload")
async def redownload(
    record_id: int,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """
    Re-download the output file for a past conversion.

    Returns 410 Gone if the output files have been cleaned up.
    """
    row = await db_fetch_one(
        "SELECT * FROM conversion_history WHERE id = ?", (record_id,)
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found.")

    batch_id = row["batch_id"]
    output_filename = row.get("output_filename", "")

    if not output_filename:
        raise HTTPException(
            status_code=410,
            detail={"error": "output_expired", "message": "No output file was produced for this conversion."},
        )

    batch_dir = OUTPUT_BASE / batch_id
    output_path = batch_dir / output_filename

    if not output_path.exists():
        # Try returning the whole batch as zip
        if batch_dir.exists():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in batch_dir.rglob("*"):
                    if p.is_file() and "_originals" not in p.parts:
                        zf.write(p, p.relative_to(batch_dir))
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{batch_id}.zip"'},
            )
        raise HTTPException(
            status_code=410,
            detail={"error": "output_expired", "message": "Output files for this batch are no longer available."},
        )

    return FileResponse(
        path=str(output_path),
        filename=output_filename,
        media_type="application/octet-stream",
    )


# ── GET /api/history/{id} ─────────────────────────────────────────────────────

@router.get("/{record_id}", response_model=HistoryRecord)
async def get_history_record(
    record_id: int,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return a single conversion history record."""
    row = await db_fetch_one(
        "SELECT * FROM conversion_history WHERE id = ?", (record_id,)
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found.")
    threshold_str = await get_preference("ocr_confidence_threshold") or "80"
    return _row_to_record(row, float(threshold_str))
