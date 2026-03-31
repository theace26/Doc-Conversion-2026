"""
Media transcript API — read, download, and query transcript data.

GET /api/media/{history_id}/transcript  — Full transcript content + metadata
GET /api/media/{history_id}/segments    — Timestamped segments
GET /api/media/{history_id}/download/{format} — Download .md, .srt, or .vtt
"""

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import db_fetch_all, db_fetch_one

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{history_id}/transcript")
async def get_transcript(
    history_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Get the full transcript content for a media conversion."""
    row = await db_fetch_one(
        "SELECT * FROM conversion_history WHERE id = ?", (history_id,)
    )
    if not row:
        raise HTTPException(404, "Transcript not found")

    # Read the .md file content
    output_path = row.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(404, "Transcript file not found on disk")

    content = Path(output_path).read_text(encoding="utf-8")

    # Get segments from DB
    segments = await db_fetch_all(
        "SELECT * FROM transcript_segments WHERE history_id = ? ORDER BY segment_index",
        (history_id,),
    )

    return {
        "history_id": history_id,
        "content": content,
        "segments": segments,
        "duration_seconds": row.get("media_duration_seconds"),
        "engine": row.get("media_engine"),
        "language": row.get("media_language"),
        "word_count": row.get("media_word_count"),
    }


@router.get("/{history_id}/segments")
async def get_segments(
    history_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Get transcript segments with timestamps."""
    segments = await db_fetch_all(
        "SELECT * FROM transcript_segments WHERE history_id = ? ORDER BY segment_index",
        (history_id,),
    )
    return {"history_id": history_id, "segments": segments}


@router.get("/{history_id}/download/{fmt}")
async def download_transcript(
    history_id: str,
    fmt: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Download transcript in specified format (md, srt, vtt)."""
    if fmt not in ("md", "srt", "vtt"):
        raise HTTPException(400, "Format must be 'md', 'srt', or 'vtt'")

    row = await db_fetch_one(
        "SELECT * FROM conversion_history WHERE id = ?", (history_id,)
    )
    if not row:
        raise HTTPException(404, "Transcript not found")

    if fmt == "srt":
        path = row.get("media_caption_path")
    elif fmt == "vtt":
        path = row.get("media_vtt_path")
    else:
        path = row.get("output_path")

    if not path or not Path(path).exists():
        raise HTTPException(404, f"{fmt.upper()} file not found")

    return FileResponse(
        path,
        filename=f"{Path(path).stem}.{fmt}",
        media_type="text/plain",
    )
