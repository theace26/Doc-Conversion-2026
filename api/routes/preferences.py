"""
User preferences endpoints.

GET /api/preferences         — All user preferences.
PUT /api/preferences/{key}   — Update a single preference (write-through to SQLite).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/preferences", tags=["preferences"])
