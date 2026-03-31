"""
Tests for api/routes/media.py — media transcript API endpoints.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


# ── GET /api/media/{id}/transcript ───────────────────────────────────────────


async def test_get_transcript_not_found(client):
    """GET /api/media/nonexistent/transcript should return 404."""
    resp = await client.get("/api/media/nonexistent_id_999/transcript")
    assert resp.status_code == 404


async def test_get_transcript_returns_content(client, tmp_path):
    """GET /api/media/{id}/transcript should return content when record exists."""
    # Create a temp .md file
    md_file = tmp_path / "test_transcript.md"
    md_file.write_text("# Test\n\n[00:00:00] Hello world\n", encoding="utf-8")

    # Insert a conversion_history record
    from core.database import get_db

    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO conversion_history
               (id, batch_id, source_filename, source_format, output_filename,
                output_format, direction, status, output_path, media_engine)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                999999, "test_batch", "test.mp3", "mp3", "test_transcript.md",
                "md", "to_md", "success", str(md_file), "whisper_local",
            ),
        )
        await conn.commit()

    resp = await client.get("/api/media/999999/transcript")
    assert resp.status_code == 200
    data = resp.json()
    assert data["history_id"] == "999999"
    assert "Hello world" in data["content"]
    assert data["engine"] == "whisper_local"


# ── GET /api/media/{id}/segments ─────────────────────────────────────────────


async def test_get_segments_returns_empty(client):
    """GET /api/media/{id}/segments should return empty for ID with no segments."""
    resp = await client.get("/api/media/nonexistent_id_999/segments")
    assert resp.status_code == 200
    data = resp.json()
    assert data["segments"] == []


async def test_get_segments_with_data(client):
    """GET /api/media/{id}/segments returns segment data."""
    from core.database import get_db
    import uuid

    seg_id = str(uuid.uuid4())

    # Insert a segment for an existing history record
    async with get_db() as conn:
        await conn.execute(
            """INSERT OR IGNORE INTO conversion_history
               (id, batch_id, source_filename, source_format, output_filename,
                output_format, direction, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (888888, "test_batch", "test.mp4", "mp4", "test.md", "md", "to_md", "success"),
        )
        await conn.execute(
            """INSERT INTO transcript_segments
               (id, history_id, segment_index, start_seconds, end_seconds, text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (seg_id, "888888", 0, 0.0, 3.5, "Hello from segment"),
        )
        await conn.commit()

    resp = await client.get("/api/media/888888/segments")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["segments"]) >= 1
    assert data["segments"][0]["text"] == "Hello from segment"


# ── GET /api/media/{id}/download/{format} ────────────────────────────────────


async def test_download_invalid_format(client):
    """GET /api/media/{id}/download/pdf should return 400."""
    resp = await client.get("/api/media/999/download/pdf")
    assert resp.status_code == 400


async def test_download_transcript_not_found(client):
    """GET /api/media/nonexistent/download/md should return 404."""
    resp = await client.get("/api/media/nonexistent_id/download/md")
    assert resp.status_code == 404


async def test_download_md_returns_file(client, tmp_path):
    """GET /api/media/{id}/download/md should return the file."""
    md_file = tmp_path / "download_test.md"
    md_file.write_text("# Download Test\n", encoding="utf-8")

    from core.database import get_db

    async with get_db() as conn:
        await conn.execute(
            """INSERT OR IGNORE INTO conversion_history
               (id, batch_id, source_filename, source_format, output_filename,
                output_format, direction, status, output_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                777777, "test_batch", "test.mp3", "mp3", "download_test.md",
                "md", "to_md", "success", str(md_file),
            ),
        )
        await conn.commit()

    resp = await client.get("/api/media/777777/download/md")
    assert resp.status_code == 200
