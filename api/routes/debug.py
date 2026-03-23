"""
Debug dashboard endpoints — only registered when DEBUG=true.

GET /debug                                     — Debug dashboard HTML.
GET /api/debug/recent                          — Last 20 conversions with debug file links.
GET /api/debug/logs                            — Tail last 100 log lines, filterable.
GET /api/debug/pipeline/{batch_id}/{filename}  — Step-through pipeline view per stage.
GET /api/debug/ocr/{batch_id}/{filename}       — OCR overlay with bounding boxes + confidence.
GET /api/debug/health                          — System health: Tesseract, LibreOffice, disk, DB.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/debug", tags=["debug"])
