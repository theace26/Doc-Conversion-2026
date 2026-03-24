"""Tests for core/vision_adapter.py — VisionAdapter."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.vision_adapter import FrameDescription, VisionAdapter


def _make_adapter(provider="openai", model="gpt-4o", api_key="sk-test", base_url=""):
    return VisionAdapter(
        {
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "api_base_url": base_url,
        }
    )


class TestSupportsVision:
    def test_openai(self):
        assert _make_adapter("openai").supports_vision() is True

    def test_anthropic(self):
        assert _make_adapter("anthropic").supports_vision() is True

    def test_gemini(self):
        assert _make_adapter("gemini").supports_vision() is True

    def test_ollama(self):
        assert _make_adapter("ollama").supports_vision() is True

    def test_custom_not_supported(self):
        assert _make_adapter("custom").supports_vision() is False

    def test_unknown_not_supported(self):
        assert _make_adapter("foo").supports_vision() is False


class TestDescribeFrame:
    @pytest.fixture
    def fake_image(self, tmp_path):
        """Create a tiny JPEG file for testing."""
        p = tmp_path / "frame.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        return p

    async def test_unsupported_provider_returns_error(self, fake_image):
        adapter = _make_adapter("custom")
        result = await adapter.describe_frame(fake_image, "describe", 0)
        assert isinstance(result, FrameDescription)
        assert result.error is not None
        assert "does not support" in result.error
        assert result.scene_index == 0

    @patch("core.vision_adapter.httpx.AsyncClient")
    async def test_openai_success(self, mock_client_cls, fake_image):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "A slide with charts"}}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = _make_adapter("openai")
        result = await adapter.describe_frame(fake_image, "describe", 3)
        assert result.error is None
        assert result.description == "A slide with charts"
        assert result.scene_index == 3
        assert result.provider_id == "openai"

    @patch("core.vision_adapter.httpx.AsyncClient")
    async def test_anthropic_success(self, mock_client_cls, fake_image):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "Title slide"}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = _make_adapter("anthropic", "claude-sonnet-4-6", "sk-ant-test")
        result = await adapter.describe_frame(fake_image, "describe", 1)
        assert result.error is None
        assert result.description == "Title slide"
        assert result.provider_id == "anthropic"

    @patch("core.vision_adapter.httpx.AsyncClient")
    async def test_connection_error_graceful(self, mock_client_cls, fake_image):
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = _make_adapter("openai")
        result = await adapter.describe_frame(fake_image, "describe", 0)
        assert result.error is not None
        assert result.description == ""

    @patch("core.vision_adapter.httpx.AsyncClient")
    async def test_timeout_graceful(self, mock_client_cls, fake_image):
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = _make_adapter("gemini", "gemini-1.5-flash", "key")
        result = await adapter.describe_frame(fake_image, "describe", 5)
        assert result.error is not None
        assert "ReadTimeout" in result.error

    async def test_never_raises(self, fake_image):
        """describe_frame must never raise, even with absurd input."""
        adapter = _make_adapter("openai")
        # Corrupt image path that doesn't exist
        result = await adapter.describe_frame(Path("/nonexistent.jpg"), "test", 0)
        assert result.error is not None


class TestHealthCheck:
    @patch("core.vision_adapter.httpx.AsyncClient")
    async def test_ollama_unreachable(self, mock_client_cls):
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = _make_adapter("ollama", "llava", "", "http://localhost:11434")
        ok, msg = await adapter.health_check()
        assert ok is False
        assert "unreachable" in msg

    @patch("core.vision_adapter.httpx.AsyncClient")
    async def test_openai_invalid_key(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = _make_adapter("openai")
        ok, msg = await adapter.health_check()
        assert ok is False
        assert "Invalid" in msg

    @patch("core.vision_adapter.httpx.AsyncClient")
    async def test_anthropic_rate_limited(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 429

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = _make_adapter("anthropic", "claude-sonnet-4-6", "sk-test")
        ok, msg = await adapter.health_check()
        assert ok is True
        assert "rate limited" in msg
