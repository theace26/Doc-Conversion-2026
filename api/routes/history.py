"""
Conversion history endpoints.

GET /api/history                — Paginated, filterable conversion history.
GET /api/history/{id}           — Single conversion record.
GET /api/history/stats          — Aggregate stats (totals, success rate, most-used format, OCR flags).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/history", tags=["history"])
