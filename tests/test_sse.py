"""
Tests for the SSE batch progress streaming endpoint.

GET /api/batch/{batch_id}/stream
"""

import json

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


async def test_stream_unknown_batch_returns_404(client):
    """GET /api/batch/{id}/stream with unknown batch_id returns 404."""
    resp = await client.get("/api/batch/nonexistent_batch/stream")
    assert resp.status_code == 404


async def test_stream_invalid_batch_id_returns_error(client):
    """GET /api/batch/{id}/stream with path-traversal batch_id returns 400 or 404."""
    resp = await client.get("/api/batch/../../etc/stream")
    assert resp.status_code in (400, 404, 422)


async def test_stream_completed_batch_replays_events(client, simple_docx):
    """
    If a batch is already complete, the SSE endpoint should replay
    file_complete/file_error events and close with batch_complete + done.
    """
    # First, run a real conversion to create a completed batch
    with open(simple_docx, "rb") as f:
        resp = await client.post(
            "/api/convert",
            files={"files": ("simple.docx", f, "application/octet-stream")},
            data={"direction": "to_md"},
        )
    assert resp.status_code == 200
    batch_id = resp.json()["batch_id"]

    # Wait for conversion to complete
    import asyncio
    for _ in range(40):
        status_resp = await client.get(f"/api/batch/{batch_id}/status")
        if status_resp.status_code == 200:
            if status_resp.json().get("status") in ("done", "partial", "failed"):
                break
        await asyncio.sleep(0.5)

    # Now stream — should replay and close
    async with client.stream("GET", f"/api/batch/{batch_id}/stream") as stream:
        events = []
        async for line in stream.aiter_lines():
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("event:"):
                events.append({"event": line.split(":", 1)[1].strip()})
            elif line.startswith("data:") and events:
                events[-1]["data"] = json.loads(line.split(":", 1)[1].strip())

    # Should have at least file_complete (or file_error), batch_complete, done
    event_types = [e["event"] for e in events]
    assert "batch_complete" in event_types
    assert "done" in event_types
    assert any(t in event_types for t in ("file_complete", "file_error"))


async def test_stream_events_are_valid_sse_format(client, simple_docx):
    """Events should follow SSE format: id, event, data lines."""
    with open(simple_docx, "rb") as f:
        resp = await client.post(
            "/api/convert",
            files={"files": ("simple.docx", f, "application/octet-stream")},
            data={"direction": "to_md"},
        )
    batch_id = resp.json()["batch_id"]

    import asyncio
    for _ in range(40):
        status_resp = await client.get(f"/api/batch/{batch_id}/status")
        if status_resp.status_code == 200:
            if status_resp.json().get("status") in ("done", "partial", "failed"):
                break
        await asyncio.sleep(0.5)

    async with client.stream("GET", f"/api/batch/{batch_id}/stream") as stream:
        raw_lines = []
        async for line in stream.aiter_lines():
            raw_lines.append(line)

    # Check that data lines parse as JSON
    for line in raw_lines:
        if line.startswith("data:"):
            data_str = line.split(":", 1)[1].strip()
            parsed = json.loads(data_str)  # should not raise
            assert isinstance(parsed, dict)


async def test_convert_response_includes_stream_url(client, simple_docx):
    """POST /api/convert should return a stream_url field."""
    with open(simple_docx, "rb") as f:
        resp = await client.post(
            "/api/convert",
            files={"files": ("simple.docx", f, "application/octet-stream")},
            data={"direction": "to_md"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "stream_url" in body
    assert body["batch_id"] in body["stream_url"]
