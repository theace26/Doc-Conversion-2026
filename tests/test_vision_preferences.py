"""Tests for vision preferences via the existing /api/preferences system."""

import pytest


class TestVisionPreferences:
    async def test_get_preferences_includes_vision_keys(self, client):
        resp = await client.get("/api/preferences")
        assert resp.status_code == 200
        data = resp.json()
        prefs = data.get("preferences", data)
        assert "vision_enrichment_level" in prefs
        assert "vision_frame_limit" in prefs
        assert "vision_save_keyframes" in prefs
        assert "vision_frame_prompt" in prefs

    async def test_schema_includes_vision_keys(self, client):
        resp = await client.get("/api/preferences")
        data = resp.json()
        schema = data.get("schema", {})
        assert "vision_enrichment_level" in schema
        assert schema["vision_enrichment_level"]["type"] == "select"
        assert "1" in schema["vision_enrichment_level"]["options"]
        assert "vision_frame_limit" in schema
        assert schema["vision_frame_limit"]["type"] == "number"
        assert schema["vision_frame_limit"]["min"] == 1
        assert schema["vision_frame_limit"]["max"] == 200

    async def test_set_enrichment_level_valid(self, client):
        resp = await client.put(
            "/api/preferences/vision_enrichment_level",
            json={"value": "3"},
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == "3"

    async def test_set_enrichment_level_invalid(self, client):
        resp = await client.put(
            "/api/preferences/vision_enrichment_level",
            json={"value": "5"},
        )
        assert resp.status_code == 422

    async def test_set_frame_limit_valid(self, client):
        resp = await client.put(
            "/api/preferences/vision_frame_limit",
            json={"value": "100"},
        )
        assert resp.status_code == 200

    async def test_set_frame_limit_out_of_range(self, client):
        resp = await client.put(
            "/api/preferences/vision_frame_limit",
            json={"value": "500"},
        )
        assert resp.status_code == 422

    async def test_set_save_keyframes_toggle(self, client):
        resp = await client.put(
            "/api/preferences/vision_save_keyframes",
            json={"value": "true"},
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == "true"

    async def test_set_save_keyframes_invalid(self, client):
        resp = await client.put(
            "/api/preferences/vision_save_keyframes",
            json={"value": "yes"},
        )
        assert resp.status_code == 422

    async def test_set_frame_prompt_text(self, client):
        resp = await client.put(
            "/api/preferences/vision_frame_prompt",
            json={"value": "Describe what you see."},
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == "Describe what you see."

    async def test_defaults_are_reasonable(self, client):
        resp = await client.get("/api/preferences")
        prefs = resp.json().get("preferences", resp.json())
        # Defaults should be set
        assert prefs.get("vision_enrichment_level") in ("1", "2", "3")
        assert int(prefs.get("vision_frame_limit", "0")) > 0
