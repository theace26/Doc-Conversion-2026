"""
OCR review endpoints.

GET  /api/batch/{batch_id}/review                 — Retrieve OCR-flagged items.
GET  /api/batch/{batch_id}/review/{flag_id}       — Single flag with image crop + OCR text.
POST /api/batch/{batch_id}/review/{flag_id}       — Resolve an OCR flag (accept, edit, skip).
POST /api/batch/{batch_id}/review/accept-all      — Accept all remaining OCR flags.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/batch", tags=["review"])
