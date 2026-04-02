import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def client():
    with patch("api.routes.pipeline.get_pipeline_status", return_value={}), \
         patch("api.routes.pipeline.get_coordinator_status", return_value={}), \
         patch("api.routes.pipeline.db_fetch_one", new_callable=AsyncMock, return_value={"cnt": 42}), \
         patch("api.routes.pipeline.get_preference", new_callable=AsyncMock, return_value="true"), \
         patch("api.routes.pipeline.get_analysis_stats",
               new_callable=AsyncMock,
               return_value={"pending": 5, "batched": 2, "completed": 100, "failed": 1}), \
         patch("api.routes.pipeline.get_meili_client", return_value=None):
        from api.routes.pipeline import router
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


def test_pipeline_stats_all_keys(client):
    resp = client.get("/api/pipeline/stats")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("scanned", "pending_conversion", "failed", "unrecognized",
                "pending_analysis", "batched_for_analysis", "analysis_failed", "in_search_index"):
        assert key in data, f"missing key: {key}"
    assert data["pending_analysis"] == 5
    assert data["batched_for_analysis"] == 2
    assert data["analysis_failed"] == 1
