"""
Batch status and download endpoints.

GET /api/batch/{batch_id}/status           — Batch progress (per-file status, OCR flags pending).
GET /api/batch/{batch_id}/download         — Download converted files (zip of all files).
GET /api/batch/{batch_id}/download/{filename} — Download single converted file.
GET /api/batch/{batch_id}/manifest         — Retrieve batch manifest JSON.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/batch", tags=["batch"])
