"""
Upload, preview, and conversion endpoints.

POST /api/convert        — Upload file(s), specify direction + output location. Returns batch ID.
POST /api/convert/preview — Quick analysis: format detection, page count, OCR likelihood, warnings.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/convert", tags=["convert"])
