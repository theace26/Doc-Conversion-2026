"""
End-to-end API integration tests.

Uses httpx.AsyncClient against the full FastAPI app.
Tesseract calls are mocked to avoid requiring OCR binaries in CI.
"""

import io
import pytest
from pathlib import Path


@pytest.mark.integration
class TestConvertEndpoint:
    """POST /api/convert integration tests."""

    @pytest.mark.anyio
    async def test_convert_docx(self, client, simple_docx):
        content = simple_docx.read_bytes()
        response = await client.post(
            "/api/convert",
            files={"files": ("test.docx", content, "application/octet-stream")},
            data={"direction": "to_md"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "batch_id" in data

    @pytest.mark.anyio
    async def test_convert_pdf(self, client, simple_text_pdf):
        content = simple_text_pdf.read_bytes()
        response = await client.post(
            "/api/convert",
            files={"files": ("test.pdf", content, "application/pdf")},
            data={"direction": "to_md"},
        )
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_convert_pptx(self, client, simple_pptx):
        content = simple_pptx.read_bytes()
        response = await client.post(
            "/api/convert",
            files={"files": ("test.pptx", content, "application/octet-stream")},
            data={"direction": "to_md"},
        )
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_convert_xlsx(self, client, simple_xlsx):
        content = simple_xlsx.read_bytes()
        response = await client.post(
            "/api/convert",
            files={"files": ("test.xlsx", content, "application/octet-stream")},
            data={"direction": "to_md"},
        )
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_convert_csv(self, client, simple_csv):
        content = simple_csv.read_bytes()
        response = await client.post(
            "/api/convert",
            files={"files": ("test.csv", content, "text/csv")},
            data={"direction": "to_md"},
        )
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_oversized_file_rejected(self, client, tmp_path):
        # Create a file that claims to be very large via upload
        large_content = b"x" * (101 * 1024 * 1024)  # 101 MB
        response = await client.post(
            "/api/convert",
            files={"files": ("huge.docx", large_content, "application/octet-stream")},
            data={"direction": "to_md"},
        )
        assert response.status_code == 413

    @pytest.mark.anyio
    async def test_disallowed_extension_rejected(self, client):
        response = await client.post(
            "/api/convert",
            files={"files": ("virus.exe", b"MZ", "application/octet-stream")},
            data={"direction": "to_md"},
        )
        assert response.status_code == 422


@pytest.mark.integration
class TestBatchEndpoint:
    """GET /api/batch/{id} integration tests."""

    @pytest.mark.anyio
    async def test_batch_status_not_found(self, client):
        response = await client.get("/api/batch/nonexistent_batch_999/status")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_batch_invalid_id(self, client):
        response = await client.get("/api/batch/../etc/passwd/status")
        assert response.status_code in (400, 404, 422)


@pytest.mark.integration
class TestHealthEndpoint:
    """GET /api/health integration tests."""

    @pytest.mark.anyio
    async def test_health_returns_200(self, client):
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "components" in data
        assert "database" in data["components"]


@pytest.mark.integration
class TestHistoryEndpoint:
    """GET /api/history integration tests."""

    @pytest.mark.anyio
    async def test_history_returns_200(self, client):
        response = await client.get("/api/history")
        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data


@pytest.mark.integration
class TestDebugEndpoint:
    """Debug dashboard smoke tests."""

    @pytest.mark.anyio
    async def test_debug_returns_200(self, client):
        response = await client.get("/debug")
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_debug_api_health(self, client):
        response = await client.get("/debug/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data

    @pytest.mark.anyio
    async def test_debug_api_activity(self, client):
        response = await client.get("/debug/api/activity")
        assert response.status_code == 200
        data = response.json()
        assert "recent_history" in data
        assert "ocr_flags" in data
        assert "stats" in data

    @pytest.mark.anyio
    async def test_debug_api_logs(self, client):
        response = await client.get("/debug/api/logs?lines=10")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "lines" in data

    @pytest.mark.anyio
    async def test_debug_api_ocr_distribution(self, client):
        response = await client.get("/debug/api/ocr_distribution")
        assert response.status_code == 200
        data = response.json()
        assert "buckets" in data
        assert "mean_confidence" in data
