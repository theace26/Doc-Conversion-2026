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
    assert "components" in data
    assert "database" in data["components"]
    assert "status" in data


# ── Preferences ───────────────────────────────────────────────────────────────

async def test_get_preferences(client):
    resp = await client.get("/api/preferences")
    assert resp.status_code == 200
    data = resp.json()
    # Phase 6: response is now {preferences: {}, schema: {}}
    prefs = data.get("preferences", data)
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
    resp = await client.get("/api/history?page=1&per_page=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["per_page"] == 5
    assert body["page"] == 1
    assert len(body["records"]) <= 5


# ── from_md direction ─────────────────────────────────────────────────────────

async def test_convert_accepts_md_file(client):
    """Upload a .md file with direction=from_md → batch_id returned."""
    md_content = b"# Hello\n\nA simple paragraph.\n"
    resp = await client.post(
        "/api/convert",
        files={"files": ("hello.md", io.BytesIO(md_content), "text/markdown")},
        data={"direction": "from_md", "target_format": "docx"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "batch_id" in body
    assert body["total_files"] == 1


async def test_convert_md_invalid_direction_rejected(client):
    """direction must be 'to_md' or 'from_md'."""
    resp = await client.post(
        "/api/convert",
        files={"files": ("doc.md", io.BytesIO(b"# Hi"), "text/markdown")},
        data={"direction": "sideways"},
    )
    assert resp.status_code == 422


async def test_preview_md_file(client):
    """Preview a .md file — format is detected as 'md'."""
    md_content = b"# Heading\n\nParagraph text.\n\n- item 1\n- item 2\n"
    resp = await client.post(
        "/api/convert/preview",
        files={"file": ("doc.md", io.BytesIO(md_content), "text/markdown")},
        data={"direction": "from_md"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "md"
    assert "element_counts" in body


async def test_convert_md_no_frontmatter_still_succeeds(client):
    """A .md file without YAML frontmatter converts without errors (Tier 1)."""
    md_content = b"# Plain heading\n\nNo frontmatter here.\n"
    resp = await client.post(
        "/api/convert",
        files={"files": ("nofm.md", io.BytesIO(md_content), "text/markdown")},
        data={"direction": "from_md", "target_format": "docx"},
    )
    assert resp.status_code == 200
    assert "batch_id" in resp.json()


# ── Phase 5 additions ───────────────────────────────────────────────────────

async def test_convert_multiple_files(client, simple_docx):
    """Upload multiple files in one request."""
    content = simple_docx.read_bytes()
    resp = await client.post(
        "/api/convert",
        files=[
            ("files", ("file1.docx", io.BytesIO(content), "application/octet-stream")),
            ("files", ("file2.docx", io.BytesIO(content), "application/octet-stream")),
        ],
        data={"direction": "to_md"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_files"] == 2


async def test_preview_returns_element_counts(client, simple_docx):
    """Preview response includes element counts by type."""
    content = simple_docx.read_bytes()
    resp = await client.post(
        "/api/convert/preview",
        files={"file": ("test.docx", io.BytesIO(content), "application/octet-stream")},
        data={"direction": "to_md"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "element_counts" in body
    assert isinstance(body["element_counts"], dict)
    # Should have at least heading and paragraph counts
    assert len(body["element_counts"]) >= 1
