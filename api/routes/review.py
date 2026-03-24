"""
OCR review endpoints.

GET  /api/batch/{batch_id}/review                 — Retrieve OCR-flagged items.
GET  /api/batch/{batch_id}/review/counts          — Flag counts by status.
GET  /api/batch/{batch_id}/review/{flag_id}       — Single flag detail.
POST /api/batch/{batch_id}/review/{flag_id}       — Resolve an OCR flag.
POST /api/batch/{batch_id}/review/accept-all      — Accept all remaining flags.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path as FPath, Query

from core.auth import AuthenticatedUser, UserRole, require_role

from api.models import OCRFlagCounts, OCRFlagResponse, OCRReviewAction
from core.database import (
    get_flag_counts,
    get_flags_for_batch,
    resolve_all_pending,
    resolve_flag,
    upsert_batch_state,
    db_fetch_one,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/batch", tags=["review"])

_VALID_ACTIONS = {"accept", "edit", "skip"}
_ACTION_TO_STATUS = {
    "accept": "accepted",
    "edit": "edited",
    "skip": "skipped",
}


def _image_url(image_path: str | None) -> str:
    """Convert a filesystem image_path to the /ocr-images/ URL served by FastAPI."""
    if not image_path:
        return ""
    # Normalise to forward slashes
    path = image_path.replace("\\", "/")
    # Strip leading "output/" so the URL works under the /ocr-images mount
    if path.startswith("output/"):
        path = path[len("output/"):]
    return f"/ocr-images/{path}"


def _flag_row_to_response(row: dict) -> OCRFlagResponse:
    return OCRFlagResponse(
        flag_id=row["flag_id"],
        page_num=row["page_num"],
        ocr_text=row["ocr_text"],
        confidence=row["confidence"],
        status=row["status"],
        image_url=_image_url(row.get("image_path")),
        corrected_text=row.get("corrected_text"),
        region_bbox=row.get("region_bbox") or [],
    )


# ── List flags ────────────────────────────────────────────────────────────────

@router.get("/{batch_id}/review", response_model=list[OCRFlagResponse])
async def list_flags(
    batch_id: str = FPath(..., description="Batch identifier"),
    status: str | None = Query(None, description="Filter by status (pending/accepted/edited/skipped)"),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return OCR flags for a batch, optionally filtered by status."""
    rows = await get_flags_for_batch(batch_id, status=status)
    return [_flag_row_to_response(r) for r in rows]


# ── Counts ────────────────────────────────────────────────────────────────────

@router.get("/{batch_id}/review/counts", response_model=OCRFlagCounts)
async def flag_counts(
    batch_id: str = FPath(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return {pending, accepted, edited, skipped, total} counts for a batch."""
    counts = await get_flag_counts(batch_id)
    return OCRFlagCounts(**counts)


# ── Single flag detail ────────────────────────────────────────────────────────

@router.get("/{batch_id}/review/{flag_id}", response_model=OCRFlagResponse)
async def get_flag(
    batch_id: str,
    flag_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Return a single OCR flag by flag_id."""
    row = await db_fetch_one(
        "SELECT * FROM ocr_flags WHERE flag_id=? AND batch_id=?",
        (flag_id, batch_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Flag not found")
    # Deserialise region_bbox
    import json
    if isinstance(row.get("region_bbox"), str):
        row["region_bbox"] = json.loads(row["region_bbox"])
    return _flag_row_to_response(row)


# ── Accept all pending ────────────────────────────────────────────────────────
# IMPORTANT: This route must be registered BEFORE the /{flag_id} POST route so
# that FastAPI does not capture the literal "accept-all" as a flag_id parameter.

@router.post("/{batch_id}/review/accept-all")
async def accept_all_flags(
    batch_id: str = FPath(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Accept all remaining pending OCR flags for a batch."""
    count = await resolve_all_pending(batch_id)
    if count > 0:
        await _finalize_ocr_batch(batch_id)
    return {"accepted": count, "batch_id": batch_id}


# ── Resolve a single flag ─────────────────────────────────────────────────────

@router.post("/{batch_id}/review/{flag_id}", response_model=OCRFlagResponse)
async def resolve_one_flag(
    action: OCRReviewAction,
    batch_id: str = FPath(...),
    flag_id: str = FPath(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """
    Resolve a single OCR flag.

    action: "accept" | "edit" | "skip"
    corrected_text is required when action == "edit".
    """
    if action.action not in _VALID_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"action must be one of: {', '.join(sorted(_VALID_ACTIONS))}",
        )
    if action.action == "edit" and not action.corrected_text:
        raise HTTPException(
            status_code=422, detail="corrected_text is required when action is 'edit'"
        )

    # Verify flag exists
    row = await db_fetch_one(
        "SELECT * FROM ocr_flags WHERE flag_id=? AND batch_id=?",
        (flag_id, batch_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Flag not found")

    new_status = _ACTION_TO_STATUS[action.action]
    log.info("ocr_review_resolve", batch_id=batch_id, flag_id=flag_id, action=action.action)
    await resolve_flag(flag_id, new_status, action.corrected_text)

    # Check if all flags are now resolved — if so, finalize the batch
    counts = await get_flag_counts(batch_id)
    if counts["pending"] == 0 and counts["total"] > 0:
        await _finalize_ocr_batch(batch_id)

    # Return the updated flag
    import json
    updated = await db_fetch_one(
        "SELECT * FROM ocr_flags WHERE flag_id=?", (flag_id,)
    )
    if isinstance(updated.get("region_bbox"), str):
        updated["region_bbox"] = json.loads(updated["region_bbox"])
    return _flag_row_to_response(updated)


# ── Finalization helper ───────────────────────────────────────────────────────

async def _finalize_ocr_batch(batch_id: str) -> None:
    """
    Called when all OCR flags for a batch have been resolved.

    Updates the batch status to 'done' and logs the resolution summary.
    The actual markdown correction pass (replacing OCR placeholders with
    corrected_text, inserting OCR_UNRESOLVED comments for skipped regions)
    is handled by the PDF format handler in Phase 4 — this function
    updates DB state and signals that human review is complete.
    """
    counts = await get_flag_counts(batch_id)
    # Use total_files=0 as fallback — the row may not exist if review is
    # triggered before the batch conversion creates it.
    await upsert_batch_state(batch_id, status="done", ocr_flags_pending=0, total_files=0)

    log.info(
        "ocr.review_complete",
        batch_id=batch_id,
        accepted=counts["accepted"],
        edited=counts["edited"],
        skipped=counts["skipped"],
        total=counts["total"],
    )
