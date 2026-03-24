"""
Conversion history endpoints.

GET /api/history                — Paginated, filterable conversion history.
GET /api/history/{id}           — Single conversion record.
GET /api/history/stats          — Aggregate stats (totals, success rate, most-used format, OCR flags).
"""

import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from api.models import HistoryListResponse, HistoryRecord, StatsResponse
from core.database import db_fetch_all, db_fetch_one

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


def _row_to_record(row: dict) -> HistoryRecord:
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
    )


# ── GET /api/history/stats  (must come before /{id} to avoid shadowing) ───────

@router.get("/stats", response_model=StatsResponse)
async def history_stats():
    """Aggregate conversion statistics."""
    rows = await db_fetch_all(
        "SELECT status, source_format, duration_ms, ocr_flags_total FROM conversion_history"
    )

    total = len(rows)
    success = sum(1 for r in rows if r["status"] == "success")
    errors = total - success
    rate = round(success / total * 100, 1) if total else 0.0

    format_counts: dict[str, int] = {}
    total_ocr = 0
    total_duration = 0
    for r in rows:
        fmt = r.get("source_format") or "unknown"
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        total_ocr += r.get("ocr_flags_total") or 0
        total_duration += r.get("duration_ms") or 0

    most_used = max(format_counts, key=format_counts.get) if format_counts else None

    return StatsResponse(
        total_conversions=total,
        success_count=success,
        error_count=errors,
        success_rate_pct=rate,
        most_used_format=most_used,
        total_ocr_flags=total_ocr,
        total_duration_ms=total_duration,
        formats=format_counts,
    )


# ── GET /api/history ──────────────────────────────────────────────────────────

@router.get("", response_model=HistoryListResponse)
async def list_history(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    format: str | None = Query(default=None),
    status: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    search: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
):
    """Paginated, filterable conversion history."""
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

    count_row = await db_fetch_one(
        f"SELECT COUNT(*) as n FROM conversion_history {where}", tuple(params)
    )
    total = count_row["n"] if count_row else 0

    rows = await db_fetch_all(
        f"SELECT * FROM conversion_history {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params + [limit, offset]),
    )

    return HistoryListResponse(
        total=total,
        limit=limit,
        offset=offset,
        records=[_row_to_record(r) for r in rows],
    )


# ── GET /api/history/{id} ─────────────────────────────────────────────────────

@router.get("/{record_id}", response_model=HistoryRecord)
async def get_history_record(record_id: int):
    """Return a single conversion history record."""
    row = await db_fetch_one(
        "SELECT * FROM conversion_history WHERE id = ?", (record_id,)
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found.")
    return _row_to_record(row)
