"""LLM cost estimation API.

Public surface (auth: OPERATOR+ for reads, ADMIN for the rate-table
mutations). All endpoints return JSON; the `/period.csv` variant in
Phase 3 will return CSV with the same data.

External integrators (e.g. IP2A) can hit these endpoints with the
same `X-API-Key` or JWT used elsewhere in MarkFlow:

    GET  /api/admin/llm-costs                    -> rate table
    POST /api/admin/llm-costs/reload              -> hot-reload from disk
    GET  /api/analysis/cost/file/{entry_id}       -> per-row CostEstimate
    GET  /api/analysis/cost/batch/{batch_id}      -> per-batch summary
    GET  /api/analysis/cost/period                -> current billing-cycle
    GET  /api/analysis/cost/period?days=30        -> arbitrary trailing window
    GET  /api/analysis/cost/staleness             -> {is_stale, age_days}
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import get_preference
from core.db.connection import db_fetch_all, db_fetch_one
from core.llm_costs import (
    aggregate_batch_cost,
    aggregate_period_cost,
    estimate_cost,
    get_costs,
    is_data_stale,
    reload_costs,
    to_dict,
)

log = structlog.get_logger(__name__)

router = APIRouter(tags=["llm_costs"])


# ── Admin-only: rate table read + hot reload ─────────────────────────────────


@router.get("/api/admin/llm-costs")
async def get_rate_table(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Serve the loaded rate table as JSON.

    OPERATOR-readable so external consumers (e.g. IP2A) can mirror
    the same source-of-truth rate data. ADMIN role is required to
    *change* the table (via /reload after editing the JSON file on
    disk), but reading is broadly available.
    """
    table = get_costs()
    return to_dict(table)


@router.post("/api/admin/llm-costs/reload")
async def reload_rate_table(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Re-read core/data/llm_costs.json from disk without container restart.

    Pattern: operator edits the JSON file (host-mounted into the
    container at /app/core/data/llm_costs.json), then POSTs here.
    No process restart, no schema migration.
    """
    table = reload_costs()
    log.info(
        "llm_cost.rate_table_reloaded",
        actor=user.email,
        schema_version=table.schema_version,
        updated_at=table.updated_at,
        provider_count=len(table.rates),
    )
    return {
        "ok": True,
        "schema_version": table.schema_version,
        "updated_at": table.updated_at,
        "providers": list(table.rates.keys()),
        "total_rates": sum(len(m) for m in table.rates.values()),
    }


# ── Operator: per-row + per-batch + period reads ─────────────────────────────


@router.get("/api/analysis/cost/file/{entry_id}")
async def get_file_cost(
    entry_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return CostEstimate for a single analysis_queue row."""
    row = await db_fetch_one(
        """SELECT id, source_path, provider_id, model, tokens_used, status,
                  analyzed_at
           FROM analysis_queue WHERE id = ?""",
        (entry_id,),
    )
    if not row:
        raise HTTPException(404, f"analysis_queue row not found: {entry_id}")

    est = estimate_cost(row["provider_id"], row["model"], row["tokens_used"])
    return {
        "entry_id": row["id"],
        "source_path": row["source_path"],
        "provider": row["provider_id"],
        "model": row["model"],
        "status": row["status"],
        "analyzed_at": row["analyzed_at"],
        **to_dict(est),
    }


@router.get("/api/analysis/cost/batch/{batch_id}")
async def get_batch_cost(
    batch_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return BatchCostSummary for a given batch_id."""
    rows = await db_fetch_all(
        """SELECT id, source_path, provider_id, model, tokens_used, status
           FROM analysis_queue WHERE batch_id = ?""",
        (batch_id,),
    )
    if not rows:
        raise HTTPException(404, f"no rows found for batch_id={batch_id}")
    summary = aggregate_batch_cost(batch_id, [dict(r) for r in rows])
    return to_dict(summary)


@router.get("/api/analysis/cost/period")
async def get_period_cost(
    days: int | None = Query(
        None,
        ge=1,
        le=365,
        description="If set, use a trailing N-day window instead of the billing cycle.",
    ),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return PeriodCostSummary.

    No `days` param -> use the current billing cycle as configured by
    `billing_cycle_start_day` preference (default 1 = calendar month).
    `days=N` -> use the trailing N-day window (useful for ad-hoc
    queries: "what did we spend in the last 7 days?").
    """
    if days is not None:
        # Trailing window: synthesize a window with cycle_start_day=1 (label),
        # but filter rows to the last N days.
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        rows = await db_fetch_all(
            """SELECT provider_id, model, tokens_used, analyzed_at
               FROM analysis_queue
               WHERE status = 'completed'
                 AND tokens_used IS NOT NULL
                 AND analyzed_at >= ?""",
            (start.isoformat(),),
        )
        # Build a transient summary with custom label for the window.
        from core.llm_costs import compute_billing_cycle_window
        # We'll use cycle_start_day=1 to satisfy the helper, then override.
        summary = aggregate_period_cost(
            [dict(r) for r in rows],
            cycle_start_day=1,
        )
        # Replace the label / window iso with the trailing-N representation.
        out = to_dict(summary)
        out["cycle_start_iso"] = start.isoformat()
        out["cycle_end_iso"] = end.isoformat()
        out["cycle_label"] = f"Trailing {days} days"
        out["days_into_cycle"] = days
        out["days_total"] = days
        out["days_remaining"] = 0
        # Projection over a fixed-window query is meaningless; null it out.
        out["projected_full_cycle_cost_usd"] = out["total_cost_usd"]
        return out

    cycle_start_day_pref = await get_preference("billing_cycle_start_day", "1")
    try:
        cycle_start_day = int(cycle_start_day_pref or "1")
    except (TypeError, ValueError):
        cycle_start_day = 1

    rows = await db_fetch_all(
        """SELECT provider_id, model, tokens_used, analyzed_at
           FROM analysis_queue
           WHERE status = 'completed'
             AND tokens_used IS NOT NULL"""
    )
    summary = aggregate_period_cost(
        [dict(r) for r in rows],
        cycle_start_day=cycle_start_day,
    )
    return to_dict(summary)


@router.get("/api/analysis/cost/period.csv")
async def get_period_cost_csv(
    days: int | None = Query(
        None,
        ge=1,
        le=365,
        description="If set, use a trailing N-day window instead of the billing cycle.",
    ),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """v0.33.3: CSV export of period cost data.

    Useful for handing to finance / pasting into a spreadsheet. Same
    underlying data as `GET /api/analysis/cost/period` but flattened
    into one row per provider/model/day. Honors the same `days` query
    parameter as the JSON endpoint.

    Returns Content-Type: text/csv with a Content-Disposition that
    suggests a filename based on the cycle window.
    """
    cycle_start_day_pref = await get_preference("billing_cycle_start_day", "1")
    try:
        cycle_start_day = int(cycle_start_day_pref or "1")
    except (TypeError, ValueError):
        cycle_start_day = 1

    # Reuse the same SQL fetch logic as the JSON endpoint
    if days is not None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        rows = await db_fetch_all(
            """SELECT provider_id, model, tokens_used, analyzed_at
               FROM analysis_queue
               WHERE status = 'completed'
                 AND tokens_used IS NOT NULL
                 AND analyzed_at >= ?
               ORDER BY analyzed_at""",
            (start.isoformat(),),
        )
        cycle_label = f"trailing-{days}d"
    else:
        rows = await db_fetch_all(
            """SELECT provider_id, model, tokens_used, analyzed_at
               FROM analysis_queue
               WHERE status = 'completed'
                 AND tokens_used IS NOT NULL
               ORDER BY analyzed_at"""
        )
        cycle_label = f"cycle-day{cycle_start_day}"

    # Aggregate by (provider, model, date) at the SQL-result level so
    # finance gets a clean per-day-per-model breakdown instead of one
    # row per analysis. Compute USD per row then sum.
    bucket: dict[tuple, dict] = {}
    for r in rows:
        provider = (r["provider_id"] or "unknown").lower()
        model = r["model"] or "unknown"
        analyzed_at = r["analyzed_at"] or ""
        # Normalize to YYYY-MM-DD
        try:
            ts = analyzed_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            day = dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            day = analyzed_at[:10] or "unknown"
        est = estimate_cost(provider, model, r["tokens_used"])
        if est.cost_usd is None:
            continue
        key = (day, provider, model)
        b = bucket.setdefault(key, {
            "day": day,
            "provider": provider,
            "model": model,
            "file_count": 0,
            "tokens": 0,
            "cost_usd": 0.0,
        })
        b["file_count"] += 1
        b["tokens"] += r["tokens_used"]
        b["cost_usd"] = round(b["cost_usd"] + est.cost_usd, 6)

    # Render CSV
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["date", "provider", "model", "files_analyzed",
                     "tokens", "cost_usd"])
    total_files = 0
    total_tokens = 0
    total_cost = 0.0
    # Sort by (day, provider, model) for deterministic output
    for key in sorted(bucket.keys()):
        b = bucket[key]
        writer.writerow([b["day"], b["provider"], b["model"],
                         b["file_count"], b["tokens"],
                         f"{b['cost_usd']:.6f}"])
        total_files += b["file_count"]
        total_tokens += b["tokens"]
        total_cost += b["cost_usd"]
    writer.writerow([])
    writer.writerow(["TOTAL", "", "", total_files, total_tokens,
                     f"{total_cost:.6f}"])

    log.info(
        "llm_cost.csv_exported",
        actor=user.email,
        cycle_label=cycle_label,
        row_count=len(bucket),
        total_cost_usd=round(total_cost, 6),
    )

    filename = f"markflow-llm-costs-{cycle_label}-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/api/analysis/cost/staleness")
async def get_rate_staleness(
    threshold_days: int = Query(90, ge=1, le=365),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Surface whether the rate table is older than `threshold_days`.

    Used by the admin-page card to show a warning banner reminding
    operators to verify provider pricing pages periodically. The
    Phase-3 scheduler job calls this same logic from `core.llm_costs`.
    """
    table = get_costs()
    stale = is_data_stale(threshold_days=threshold_days)
    age_days: int | None = None
    if table.updated_at:
        try:
            updated = datetime.fromisoformat(table.updated_at)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - updated).days
        except ValueError:
            age_days = None
    return {
        "is_stale": stale,
        "threshold_days": threshold_days,
        "updated_at": table.updated_at,
        "age_days": age_days,
        "source_url": table.source_url,
    }
