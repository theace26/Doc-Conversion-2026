"""
Tests for the preferences API endpoints.

GET /api/preferences — returns preferences + schema
PUT /api/preferences/{key} — validated update
"""

import pytest

pytestmark = pytest.mark.asyncio


# ── GET /api/preferences ─────────────────────────────────────────────────────

async def test_get_preferences_includes_schema(client):
    """GET /api/preferences returns both preferences and schema."""
    resp = await client.get("/api/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert "preferences" in data
    assert "schema" in data
    assert isinstance(data["preferences"], dict)
    assert isinstance(data["schema"], dict)
    # Check a known schema entry
    assert "ocr_confidence_threshold" in data["schema"]
    assert data["schema"]["ocr_confidence_threshold"]["type"] == "range"


async def test_get_preferences_schema_has_labels(client):
    """Schema entries should have a label field."""
    resp = await client.get("/api/preferences")
    data = resp.json()
    for key, schema in data["schema"].items():
        assert "label" in schema, f"Schema for '{key}' missing label"


# ── PUT /api/preferences/{key} — valid updates ──────────────────────────────

async def test_update_valid_confidence_threshold(client):
    """PUT with valid threshold value succeeds."""
    resp = await client.put(
        "/api/preferences/ocr_confidence_threshold",
        json={"value": "70"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "ocr_confidence_threshold"
    assert data["value"] == "70"


async def test_update_valid_direction(client):
    """PUT with valid direction value succeeds."""
    resp = await client.put(
        "/api/preferences/default_direction",
        json={"value": "to_md"},
    )
    assert resp.status_code == 200


async def test_update_valid_toggle(client):
    """PUT with valid toggle value succeeds."""
    resp = await client.put(
        "/api/preferences/unattended_default",
        json={"value": "true"},
    )
    assert resp.status_code == 200

    # Reset
    await client.put(
        "/api/preferences/unattended_default",
        json={"value": "false"},
    )


# ── PUT /api/preferences/{key} — validation errors ──────────────────────────

async def test_update_threshold_out_of_range_returns_422(client):
    """PUT with value 999 for ocr_confidence_threshold returns 422."""
    resp = await client.put(
        "/api/preferences/ocr_confidence_threshold",
        json={"value": "999"},
    )
    assert resp.status_code == 422
    assert "must be between" in resp.json()["detail"]


async def test_update_threshold_negative_returns_422(client):
    """PUT with negative value returns 422."""
    resp = await client.put(
        "/api/preferences/ocr_confidence_threshold",
        json={"value": "-5"},
    )
    assert resp.status_code == 422


async def test_update_threshold_non_integer_returns_422(client):
    """PUT with non-integer value returns 422."""
    resp = await client.put(
        "/api/preferences/ocr_confidence_threshold",
        json={"value": "abc"},
    )
    assert resp.status_code == 422


async def test_update_invalid_direction_returns_422(client):
    """PUT with invalid direction returns 422."""
    resp = await client.put(
        "/api/preferences/default_direction",
        json={"value": "sideways"},
    )
    assert resp.status_code == 422
    assert "must be one of" in resp.json()["detail"]


async def test_update_invalid_toggle_returns_422(client):
    """PUT with invalid toggle value returns 422."""
    resp = await client.put(
        "/api/preferences/unattended_default",
        json={"value": "maybe"},
    )
    assert resp.status_code == 422


async def test_update_max_upload_size_too_large_returns_422(client):
    """PUT max_upload_size_mb with 999 returns 422."""
    resp = await client.put(
        "/api/preferences/max_upload_size_mb",
        json={"value": "999"},
    )
    assert resp.status_code == 422


async def test_update_unknown_key_returns_422(client):
    """PUT with unknown key returns 422."""
    resp = await client.put(
        "/api/preferences/nonexistent_key",
        json={"value": "hello"},
    )
    assert resp.status_code == 422


async def test_update_readonly_key_returns_403(client):
    """PUT to read-only key returns 403."""
    resp = await client.put(
        "/api/preferences/last_source_directory",
        json={"value": "/tmp"},
    )
    assert resp.status_code == 403
