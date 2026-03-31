"""
Tests for formats/audio_handler.py and formats/media_handler.py —
format handler registration and integration.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from formats.base import get_handler, list_supported_extensions


# ── Registration tests ───────────────────────────────────────────────────────


def test_audio_handler_registered():
    """AudioHandler should be registered for audio extensions."""
    for ext in ["mp3", "wav", "flac", "ogg", "m4a", "wma", "aac"]:
        handler = get_handler(ext)
        assert handler is not None, f"No handler for .{ext}"
        assert handler.__class__.__name__ == "AudioHandler"


def test_media_handler_registered():
    """MediaHandler should be registered for video extensions."""
    for ext in ["mp4", "mov", "avi", "mkv", "wmv", "m4v", "webm"]:
        handler = get_handler(ext)
        assert handler is not None, f"No handler for .{ext}"
        assert handler.__class__.__name__ == "MediaHandler"


def test_extensions_in_supported_list():
    """Audio and video extensions should appear in the supported list."""
    supported = list_supported_extensions()
    for ext in ["mp3", "mp4", "wav", "mkv", "flac"]:
        assert ext in supported, f".{ext} not in supported extensions"


# ── AudioHandler ─────────────────────────────────────────────────────────────


def test_audio_handler_export_not_supported():
    """AudioHandler.export() should raise NotImplementedError."""
    handler = get_handler("mp3")
    with pytest.raises(NotImplementedError, match="cannot be reconstructed"):
        handler.export(MagicMock(), Path("/tmp/out.mp3"))


def test_audio_handler_extract_styles_empty():
    """AudioHandler.extract_styles() should return empty dict."""
    handler = get_handler("mp3")
    result = handler.extract_styles(Path("/tmp/test.mp3"))
    assert result == {}


# ── MediaHandler ─────────────────────────────────────────────────────────────


def test_media_handler_export_not_supported():
    """MediaHandler.export() should raise NotImplementedError."""
    handler = get_handler("mp4")
    with pytest.raises(NotImplementedError, match="cannot be reconstructed"):
        handler.export(MagicMock(), Path("/tmp/out.mp4"))


def test_media_handler_extract_styles_empty():
    """MediaHandler.extract_styles() should return empty dict."""
    handler = get_handler("mp4")
    result = handler.extract_styles(Path("/tmp/test.mp4"))
    assert result == {}


# ── Handler supports_format ──────────────────────────────────────────────────


def test_audio_handler_supports_format():
    """AudioHandler.supports_format() for registered extensions."""
    from formats.audio_handler import AudioHandler

    assert AudioHandler.supports_format("mp3") is True
    assert AudioHandler.supports_format(".wav") is True
    assert AudioHandler.supports_format("MP3") is True
    assert AudioHandler.supports_format("mp4") is False


def test_media_handler_supports_format():
    """MediaHandler.supports_format() for registered extensions."""
    from formats.media_handler import MediaHandler

    assert MediaHandler.supports_format("mp4") is True
    assert MediaHandler.supports_format(".mov") is True
    assert MediaHandler.supports_format("MKV") is True
    assert MediaHandler.supports_format("mp3") is False
