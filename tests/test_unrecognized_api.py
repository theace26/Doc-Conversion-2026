"""Tests for api/routes/unrecognized.py — unrecognized file endpoints."""

import pytest


class TestUnrecognizedAPI:
    async def test_list_empty(self, client):
        resp = await client.get("/api/unrecognized")
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data
        assert "total" in data
        assert data["total"] >= 0

    async def test_stats_empty(self, client):
        resp = await client.get("/api/unrecognized/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "by_category" in data
        assert "by_format" in data
        assert "total_bytes" in data
        assert "job_ids" in data

    async def test_list_with_category_filter(self, client):
        resp = await client.get("/api/unrecognized?category=disk_image")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["files"], list)

    async def test_list_with_job_filter(self, client):
        resp = await client.get("/api/unrecognized?job_id=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    async def test_export_csv(self, client):
        resp = await client.get("/api/unrecognized/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        content = resp.text
        assert "source_path" in content  # CSV header
        assert "file_category" in content

    async def test_export_csv_with_filters(self, client):
        resp = await client.get("/api/unrecognized/export?category=archive")
        assert resp.status_code == 200

    async def test_pagination(self, client):
        resp = await client.get("/api/unrecognized?page=1&per_page=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 10
        assert "pages" in data

    async def test_stats_with_job_filter(self, client):
        resp = await client.get("/api/unrecognized/stats?job_id=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
