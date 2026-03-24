"""Initial API tests for MarkFlow — upload, preview, batch, history, preferences."""

import io
from pathlib import Path

import pytest
import pytest_asyncio


pytestmark = pytest.mark.anyio


# ── Health ────────────────────────────────────────────────────────────────────

async def test_health_ok(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "database" in data


# ── Preferences ───────────────────────────────────────────────────────────────

async def test_get_preferences(client):
    resp = await client.get("/api/preferences")
    assert resp.status_code == 200
    prefs = resp.json()
    assert "default_direction" in prefs
    assert "max_upload_size_mb" in prefs


async def test_put_preference(client):
    resp = await client.put(
        "/api/preferences/ocr_confidence_threshold",
        json={"value": "75"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == "75"


async def test_put_preference_invalid_key(client):
    resp = await client.put(
        "/api/preferences/nonexistent_key",
        json={"value": "x"},
    )
    assert resp.status_code == 422


# ── Upload validation ─────────────────────────────────────────────────────────

async def test_convert_rejects_invalid_extension(client):
    content = b"not a docx"
    resp = await client.post(
        "/api/convert",
        files={"files": ("evil.exe", io.BytesIO(content), "application/octet-stream")},
        data={"direction": "to_md"},
    )
    assert resp.status_code == 422


async def test_convert_rejects_oversized_file(client):
    # Temporarily lower the limit and send a large payload
    await client.put("/api/preferences/max_upload_size_mb", json={"value": "1"})

    big_content = b"x" * (2 * 1024 * 1024)  # 2 MB
    resp = await client.post(
        "/api/convert",
        files={"files": ("big.docx", io.BytesIO(big_content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"direction": "to_md"},
    )
    assert resp.status_code in (413, 422)
    # Restore default
    await client.put("/api/preferences/max_upload_size_mb", json={"value": "100"})


async def test_convert_accepts_valid_docx(client, simple_docx):
    with open(simple_docx, "rb") as f:
        content = f.read()
    resp = await client.post(
        "/api/convert",
        files={"files": ("simple.docx", io.BytesIO(content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"direction": "to_md"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "batch_id" in body
    assert body["total_files"] == 1


# ── Preview ───────────────────────────────────────────────────────────────────

async def test_preview_rejects_invalid_extension(client):
    resp = await client.post(
        "/api/convert/preview",
        files={"file": ("evil.exe", io.BytesIO(b"bad"), "application/octet-stream")},
        data={"direction": "to_md"},
    )
    assert resp.status_code == 422


async def test_preview_returns_format_info(client, simple_docx):
    with open(simple_docx, "rb") as f:
        content = f.read()
    resp = await client.post(
        "/api/convert/preview",
        files={"file": ("simple.docx", io.BytesIO(content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"direction": "to_md"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "docx"
    assert body["filename"] == "simple.docx"
    assert body["file_size_bytes"] > 0
    assert "element_counts" in body


# ── Batch status ──────────────────────────────────────────────────────────────

async def test_batch_status_not_found(client):
    resp = await client.get("/api/batch/nonexistent_batch/status")
    assert resp.status_code == 404


async def test_batch_status_invalid_id(client):
    resp = await client.get("/api/batch/../etc/passwd/status")
    assert resp.status_code in (400, 404, 422)


# ── History ───────────────────────────────────────────────────────────────────

async def test_history_empty_returns_list(client):
    resp = await client.get("/api/history")
    assert resp.status_code == 200
    body = resp.json()
    assert "records" in body
    assert "total" in body


async def test_history_stats(client):
    resp = await client.get("/api/history/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "total_conversions" in body
    assert "success_rate_pct" in body


async def test_history_record_not_found(client):
    resp = await client.get("/api/history/999999")
    assert resp.status_code == 404


async def test_history_filters_by_format(client):
    resp = await client.get("/api/history?format=docx")
    assert resp.status_code == 200
    body = resp.json()
    # All returned records should be docx
    for rec in body["records"]:
        assert rec["source_format"] == "docx"


async def test_history_pagination(client):
    resp = await client.get("/api/history?limit=5&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 5
    assert body["offset"] == 0
    assert len(body["records"]) <= 5
