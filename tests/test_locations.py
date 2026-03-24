"""Tests for the Named Locations API and bulk job integration."""

import pytest

from core.database import (
    init_db,
    create_location,
    get_location,
    list_locations,
    update_location,
    delete_location,
    create_bulk_job,
)


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


# ── Database helper tests ──────────────────────────────────────────────────


class TestDatabaseHelpers:
    async def test_create_location_returns_id(self):
        loc_id = await create_location("Test Source", "/mnt/source", "source")
        assert loc_id
        loc = await get_location(loc_id)
        assert loc["name"] == "Test Source"
        assert loc["path"] == "/mnt/source"
        assert loc["type"] == "source"

    async def test_create_location_duplicate_name_raises(self):
        await create_location("Unique Name", "/mnt/a", "source")
        with pytest.raises(ValueError, match="already exists"):
            await create_location("Unique Name", "/mnt/b", "output")

    async def test_list_locations_type_filter_source(self):
        await create_location("Src Only", "/mnt/s1", "source")
        await create_location("Out Only", "/mnt/o1", "output")
        await create_location("Both Way", "/mnt/b1", "both")

        sources = await list_locations(type_filter="source")
        names = {l["name"] for l in sources}
        assert "Src Only" in names
        assert "Both Way" in names
        assert "Out Only" not in names

    async def test_list_locations_type_filter_output(self):
        await create_location("Src2", "/mnt/s2", "source")
        await create_location("Out2", "/mnt/o2", "output")
        await create_location("Both2", "/mnt/b2", "both")

        outputs = await list_locations(type_filter="output")
        names = {l["name"] for l in outputs}
        assert "Out2" in names
        assert "Both2" in names
        assert "Src2" not in names

    async def test_update_location(self):
        loc_id = await create_location("Old Name", "/mnt/old", "source")
        await update_location(loc_id, name="New Name", path="/mnt/new")
        loc = await get_location(loc_id)
        assert loc["name"] == "New Name"
        assert loc["path"] == "/mnt/new"

    async def test_update_location_conflicting_name(self):
        await create_location("Name A", "/mnt/a", "source")
        loc_b = await create_location("Name B", "/mnt/b", "source")
        with pytest.raises(ValueError, match="already exists"):
            await update_location(loc_b, name="Name A")

    async def test_delete_location(self):
        loc_id = await create_location("To Delete", "/mnt/del", "source")
        await delete_location(loc_id)
        assert await get_location(loc_id) is None


# ── API tests ────────────────────────────────────────────────────────────────


class TestCreateLocationAPI:
    async def test_create_returns_201(self, client):
        resp = await client.post("/api/locations", json={
            "name": "API Source",
            "path": "/mnt/api-source",
            "type": "source",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "API Source"
        assert data["path"] == "/mnt/api-source"
        assert data["type"] == "source"
        assert "id" in data

    async def test_create_duplicate_name_returns_409(self, client):
        await client.post("/api/locations", json={
            "name": "Dup Name",
            "path": "/mnt/dup1",
            "type": "source",
        })
        resp = await client.post("/api/locations", json={
            "name": "Dup Name",
            "path": "/mnt/dup2",
            "type": "output",
        })
        assert resp.status_code == 409

    async def test_create_windows_path_returns_422(self, client):
        resp = await client.post("/api/locations", json={
            "name": "Win Path",
            "path": "C:\\Users\\foo",
            "type": "source",
        })
        assert resp.status_code == 422
        assert "container path" in resp.json()["detail"].lower()

    async def test_create_invalid_type_returns_422(self, client):
        resp = await client.post("/api/locations", json={
            "name": "Bad Type",
            "path": "/mnt/bt",
            "type": "invalid",
        })
        assert resp.status_code == 422

    async def test_create_with_notes(self, client):
        resp = await client.post("/api/locations", json={
            "name": "With Notes",
            "path": "/mnt/noted",
            "type": "source",
            "notes": "Read-only SMB share",
        })
        assert resp.status_code == 201
        assert resp.json()["notes"] == "Read-only SMB share"


class TestListLocationsAPI:
    async def test_list_all(self, client):
        await client.post("/api/locations", json={
            "name": "List All 1", "path": "/mnt/la1", "type": "source"
        })
        resp = await client.get("/api/locations")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(l["name"] == "List All 1" for l in data)

    async def test_list_filter_source(self, client):
        await client.post("/api/locations", json={
            "name": "Filter Src", "path": "/mnt/fs", "type": "source"
        })
        await client.post("/api/locations", json={
            "name": "Filter Out", "path": "/mnt/fo", "type": "output"
        })
        resp = await client.get("/api/locations?type=source")
        assert resp.status_code == 200
        data = resp.json()
        names = {l["name"] for l in data}
        assert "Filter Src" in names
        assert "Filter Out" not in names

    async def test_list_filter_output(self, client):
        await client.post("/api/locations", json={
            "name": "Filt Src2", "path": "/mnt/fs2", "type": "source"
        })
        await client.post("/api/locations", json={
            "name": "Filt Out2", "path": "/mnt/fo2", "type": "output"
        })
        resp = await client.get("/api/locations?type=output")
        data = resp.json()
        names = {l["name"] for l in data}
        assert "Filt Out2" in names
        assert "Filt Src2" not in names


class TestGetLocationAPI:
    async def test_get_existing(self, client):
        r = await client.post("/api/locations", json={
            "name": "Get Me", "path": "/mnt/gm", "type": "source"
        })
        loc_id = r.json()["id"]
        resp = await client.get(f"/api/locations/{loc_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Get Me"

    async def test_get_nonexistent_returns_404(self, client):
        resp = await client.get("/api/locations/nonexistent")
        assert resp.status_code == 404


class TestUpdateLocationAPI:
    async def test_update_name_and_path(self, client):
        r = await client.post("/api/locations", json={
            "name": "Before Update", "path": "/mnt/bu", "type": "source"
        })
        loc_id = r.json()["id"]
        resp = await client.put(f"/api/locations/{loc_id}", json={
            "name": "After Update", "path": "/mnt/au"
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "After Update"
        assert resp.json()["path"] == "/mnt/au"

    async def test_update_conflicting_name_returns_409(self, client):
        await client.post("/api/locations", json={
            "name": "Existing Name", "path": "/mnt/en", "type": "source"
        })
        r = await client.post("/api/locations", json={
            "name": "Other Name", "path": "/mnt/on", "type": "source"
        })
        loc_id = r.json()["id"]
        resp = await client.put(f"/api/locations/{loc_id}", json={
            "name": "Existing Name"
        })
        assert resp.status_code == 409


class TestDeleteLocationAPI:
    async def test_delete_returns_204(self, client):
        r = await client.post("/api/locations", json={
            "name": "Delete Me", "path": "/mnt/dm", "type": "source"
        })
        loc_id = r.json()["id"]
        resp = await client.request("DELETE", f"/api/locations/{loc_id}")
        assert resp.status_code == 204

    async def test_delete_in_use_returns_409(self, client):
        r = await client.post("/api/locations", json={
            "name": "In Use Loc", "path": "/mnt/inuse", "type": "source"
        })
        loc_id = r.json()["id"]
        # Create a bulk job that uses this path
        await create_bulk_job("/mnt/inuse", "/out")

        resp = await client.request("DELETE", f"/api/locations/{loc_id}")
        assert resp.status_code == 409
        data = resp.json()
        assert data["detail"]["error"] == "location_in_use"
        assert data["detail"]["job_count"] >= 1

    async def test_delete_force_in_use(self, client):
        r = await client.post("/api/locations", json={
            "name": "Force Del", "path": "/mnt/forcedel", "type": "source"
        })
        loc_id = r.json()["id"]
        await create_bulk_job("/mnt/forcedel", "/out")

        resp = await client.request("DELETE", f"/api/locations/{loc_id}?force=true")
        assert resp.status_code == 204


class TestValidateAPI:
    async def test_validate_windows_path(self, client):
        resp = await client.get("/api/locations/validate?path=C:\\foo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["accessible"] is False
        assert data["error"] == "not_a_container_path"

    async def test_validate_nonexistent_path(self, client):
        resp = await client.get("/api/locations/validate?path=/nonexistent/path/abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is False

    async def test_validate_accessible_path(self, client, tmp_path):
        # tmp_path exists and is writable — but it's not a /... path on Windows
        # This test works in the container where paths start with /
        # On Windows in test, we test the structure of the response
        resp = await client.get(f"/api/locations/validate?path=/tmp")
        assert resp.status_code == 200
        data = resp.json()
        assert "exists" in data
        assert "readable" in data
        assert "writable" in data


# ── Bulk job integration ──────────────────────────────────────────────────


class TestBulkJobLocationIntegration:
    async def test_create_job_with_location_ids(self, client, tmp_path):
        source = tmp_path / "bulk_src"
        source.mkdir()
        output = tmp_path / "bulk_out"

        r1 = await client.post("/api/locations", json={
            "name": "BulkSrc", "path": str(source), "type": "source"
        })
        r2 = await client.post("/api/locations", json={
            "name": "BulkOut", "path": str(output), "type": "output"
        })
        src_id = r1.json()["id"]
        out_id = r2.json()["id"]

        from unittest.mock import AsyncMock, patch, MagicMock
        with patch("api.routes.bulk.BulkJob") as MockJob:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock()
            MockJob.return_value = mock_instance

            resp = await client.post("/api/bulk/jobs", json={
                "source_location_id": src_id,
                "output_location_id": out_id,
                "worker_count": 2,
            })

        assert resp.status_code == 200
        assert "job_id" in resp.json()

    async def test_create_job_nonexistent_location_returns_422(self, client):
        resp = await client.post("/api/bulk/jobs", json={
            "source_location_id": "nonexistent",
            "output_location_id": "also_nonexistent",
        })
        assert resp.status_code == 422

    async def test_create_job_no_source_returns_422(self, client):
        resp = await client.post("/api/bulk/jobs", json={
            "output_path": "/tmp/out",
        })
        assert resp.status_code == 422

    async def test_create_job_backwards_compat_raw_paths(self, client, tmp_path):
        """Raw source_path/output_path still work (backwards compatible)."""
        source = tmp_path / "raw_src"
        source.mkdir()

        from unittest.mock import AsyncMock, patch, MagicMock
        with patch("api.routes.bulk.BulkJob") as MockJob:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock()
            MockJob.return_value = mock_instance

            resp = await client.post("/api/bulk/jobs", json={
                "source_path": str(source),
                "output_path": str(tmp_path / "raw_out"),
                "worker_count": 2,
            })

        assert resp.status_code == 200
        assert "job_id" in resp.json()
