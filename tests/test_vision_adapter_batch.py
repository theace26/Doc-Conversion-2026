import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


@pytest.mark.asyncio
async def test_describe_batch_returns_one_result_per_image(tmp_path):
    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": json.dumps([
            {"description": "A white rectangle", "extracted_text": ""},
            {"description": "Another white rectangle", "extracted_text": ""},
        ])}]
    }
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from core.vision_adapter import VisionAdapter
        adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
        results = await adapter.describe_batch([img1, img2])

    assert len(results) == 2
    assert results[0].index == 0
    assert results[1].index == 1
    assert "rectangle" in results[0].description


@pytest.mark.asyncio
async def test_describe_batch_empty():
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
    results = await adapter.describe_batch([])
    assert results == []


@pytest.mark.asyncio
async def test_describe_batch_unsupported_provider(tmp_path):
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "custom", "api_key": "k", "model": "m", "api_base_url": ""})
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n" + b"\x00" * 10)
    results = await adapter.describe_batch([img])
    assert len(results) == 1
    assert results[0].error is not None


def test_parse_batch_response_valid_json():
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
    raw = '[{"description": "cat", "extracted_text": "hello"}]'
    parsed = adapter._parse_batch_response(raw, 1)
    assert parsed[0]["description"] == "cat"


def test_parse_batch_response_json_in_prose():
    from core.vision_adapter import VisionAdapter
    adapter = VisionAdapter({"provider": "anthropic", "api_key": "k", "model": "m", "api_base_url": ""})
    raw = 'Here is the result: [{"description": "cat", "extracted_text": ""}]'
    parsed = adapter._parse_batch_response(raw, 1)
    assert parsed[0]["description"] == "cat"
