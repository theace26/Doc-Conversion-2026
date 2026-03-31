"""
Tests for core/transcription_engine.py — fallback chain orchestration.

Tests verify the three-step chain: caption → Whisper → cloud.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.transcription_engine import TranscriptionEngine
from core.whisper_transcriber import TranscriptionResult, TranscriptionSegment
from core.media_probe import MediaProbeResult


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_probe():
    """MediaProbeResult for a generic audio file."""
    return MediaProbeResult(
        path=Path("/tmp/test.mp3"),
        container="mp3",
        media_type="audio",
        has_video=False,
        has_audio=True,
        video_codec=None,
        audio_codec="mp3",
        audio_channels=2,
        audio_sample_rate=44100,
        duration_secs=120.0,
        width=None,
        height=None,
        frame_rate=None,
        needs_transcode=False,
        transcode_reason=None,
    )


@pytest.fixture
def default_preferences():
    """Default user preferences for transcription."""
    return {
        "caption_file_extensions": ".srt,.vtt,.sbv",
        "whisper_model": "base",
        "whisper_language": "auto",
        "whisper_device": "auto",
        "transcription_cloud_fallback": "true",
        "transcription_timeout_seconds": "3600",
    }


@pytest.fixture
def caption_result():
    """TranscriptionResult from caption ingest."""
    return TranscriptionResult(
        segments=[
            TranscriptionSegment(index=0, start_seconds=0, end_seconds=3, text="Hello"),
        ],
        engine="caption_ingest",
        word_count=1,
        raw_text="Hello",
    )


@pytest.fixture
def whisper_result():
    """TranscriptionResult from Whisper."""
    return TranscriptionResult(
        segments=[
            TranscriptionSegment(index=0, start_seconds=0, end_seconds=5, text="Hello world"),
        ],
        engine="whisper_local",
        model_name="base",
        language="en",
        word_count=2,
        raw_text="Hello world",
    )


@pytest.fixture
def cloud_result():
    """TranscriptionResult from cloud provider."""
    return TranscriptionResult(
        segments=[
            TranscriptionSegment(index=0, start_seconds=0, end_seconds=5, text="Hello cloud"),
        ],
        engine="whisper_cloud_openai",
        model_name="whisper-1",
        word_count=2,
        raw_text="Hello cloud",
    )


# ── Caption file priority ────────────────────────────────────────────────────


async def test_caption_file_takes_priority(
    tmp_path, mock_probe, default_preferences, caption_result
):
    """When a .srt exists alongside the media file, use it."""
    media_path = tmp_path / "video.mp4"
    media_path.touch()
    srt_path = tmp_path / "video.srt"
    srt_path.write_text("1\n00:00:00,000 --> 00:00:03,000\nHello\n")

    with patch(
        "core.transcription_engine.CaptionIngestor.parse",
        new_callable=AsyncMock,
        return_value=caption_result,
    ):
        result = await TranscriptionEngine.transcribe(
            audio_path=media_path,
            original_path=media_path,
            probe=mock_probe,
            preferences=default_preferences,
        )

    assert result.engine == "caption_ingest"
    assert result.duration_seconds == 120.0  # set from probe


async def test_caption_parse_failure_falls_through(
    tmp_path, mock_probe, default_preferences, whisper_result
):
    """If caption file exists but fails to parse, fall through to Whisper."""
    media_path = tmp_path / "video.mp4"
    media_path.touch()
    srt_path = tmp_path / "video.srt"
    srt_path.write_text("garbage content")

    with patch(
        "core.transcription_engine.CaptionIngestor.parse",
        new_callable=AsyncMock,
        side_effect=ValueError("bad format"),
    ), patch(
        "core.transcription_engine.WhisperTranscriber.is_available",
        return_value=True,
    ), patch(
        "core.transcription_engine.WhisperTranscriber.transcribe",
        new_callable=AsyncMock,
        return_value=whisper_result,
    ):
        result = await TranscriptionEngine.transcribe(
            audio_path=media_path,
            original_path=media_path,
            probe=mock_probe,
            preferences=default_preferences,
        )

    assert result.engine == "whisper_local"


# ── Whisper fallback ─────────────────────────────────────────────────────────


async def test_whisper_fallback(
    tmp_path, mock_probe, default_preferences, whisper_result
):
    """No caption file → use Whisper."""
    media_path = tmp_path / "audio.mp3"
    media_path.touch()

    with patch(
        "core.transcription_engine.WhisperTranscriber.is_available",
        return_value=True,
    ), patch(
        "core.transcription_engine.WhisperTranscriber.transcribe",
        new_callable=AsyncMock,
        return_value=whisper_result,
    ):
        result = await TranscriptionEngine.transcribe(
            audio_path=media_path,
            original_path=media_path,
            probe=mock_probe,
            preferences=default_preferences,
        )

    assert result.engine == "whisper_local"


# ── Cloud fallback ───────────────────────────────────────────────────────────


async def test_cloud_fallback_when_whisper_fails(
    tmp_path, mock_probe, default_preferences, cloud_result
):
    """When Whisper fails, fall through to cloud."""
    media_path = tmp_path / "audio.mp3"
    media_path.touch()

    with patch(
        "core.transcription_engine.WhisperTranscriber.is_available",
        return_value=True,
    ), patch(
        "core.transcription_engine.WhisperTranscriber.transcribe",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Whisper crashed"),
    ), patch(
        "core.transcription_engine.CloudTranscriber.transcribe",
        new_callable=AsyncMock,
        return_value=cloud_result,
    ):
        result = await TranscriptionEngine.transcribe(
            audio_path=media_path,
            original_path=media_path,
            probe=mock_probe,
            preferences=default_preferences,
        )

    assert result.engine == "whisper_cloud_openai"


async def test_cloud_fallback_when_whisper_unavailable(
    tmp_path, mock_probe, default_preferences, cloud_result
):
    """When Whisper is not installed, skip to cloud."""
    media_path = tmp_path / "audio.mp3"
    media_path.touch()

    with patch(
        "core.transcription_engine.WhisperTranscriber.is_available",
        return_value=False,
    ), patch(
        "core.transcription_engine.CloudTranscriber.transcribe",
        new_callable=AsyncMock,
        return_value=cloud_result,
    ):
        result = await TranscriptionEngine.transcribe(
            audio_path=media_path,
            original_path=media_path,
            probe=mock_probe,
            preferences=default_preferences,
        )

    assert result.engine == "whisper_cloud_openai"


# ── All fail ─────────────────────────────────────────────────────────────────


async def test_all_methods_fail_raises(tmp_path, mock_probe, default_preferences):
    """When all methods fail, raise RuntimeError."""
    media_path = tmp_path / "audio.mp3"
    media_path.touch()

    with patch(
        "core.transcription_engine.WhisperTranscriber.is_available",
        return_value=True,
    ), patch(
        "core.transcription_engine.WhisperTranscriber.transcribe",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Whisper failed"),
    ), patch(
        "core.transcription_engine.CloudTranscriber.transcribe",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Cloud failed"),
    ):
        with pytest.raises(RuntimeError, match="All transcription methods failed"):
            await TranscriptionEngine.transcribe(
                audio_path=media_path,
                original_path=media_path,
                probe=mock_probe,
                preferences=default_preferences,
            )


# ── Cloud disabled ───────────────────────────────────────────────────────────


async def test_cloud_disabled_skips_cloud(tmp_path, mock_probe):
    """When cloud fallback is disabled, don't try cloud providers."""
    preferences = {
        "caption_file_extensions": ".srt,.vtt,.sbv",
        "whisper_model": "base",
        "whisper_language": "auto",
        "whisper_device": "auto",
        "transcription_cloud_fallback": "false",
        "transcription_timeout_seconds": "3600",
    }
    media_path = tmp_path / "audio.mp3"
    media_path.touch()

    with patch(
        "core.transcription_engine.WhisperTranscriber.is_available",
        return_value=False,
    ):
        with pytest.raises(RuntimeError, match="Cloud fallback enabled: False"):
            await TranscriptionEngine.transcribe(
                audio_path=media_path,
                original_path=media_path,
                probe=mock_probe,
                preferences=preferences,
            )


# ── Timeout ──────────────────────────────────────────────────────────────────


async def test_whisper_timeout_falls_to_cloud(
    tmp_path, mock_probe, cloud_result
):
    """Whisper timeout should trigger cloud fallback."""
    import asyncio

    preferences = {
        "caption_file_extensions": ".srt,.vtt,.sbv",
        "whisper_model": "base",
        "whisper_language": "auto",
        "whisper_device": "auto",
        "transcription_cloud_fallback": "true",
        "transcription_timeout_seconds": "1",  # 1 second timeout
    }
    media_path = tmp_path / "audio.mp3"
    media_path.touch()

    async def slow_transcribe(*args, **kwargs):
        await asyncio.sleep(10)
        return None

    with patch(
        "core.transcription_engine.WhisperTranscriber.is_available",
        return_value=True,
    ), patch(
        "core.transcription_engine.WhisperTranscriber.transcribe",
        new_callable=AsyncMock,
        side_effect=slow_transcribe,
    ), patch(
        "core.transcription_engine.CloudTranscriber.transcribe",
        new_callable=AsyncMock,
        return_value=cloud_result,
    ):
        result = await TranscriptionEngine.transcribe(
            audio_path=media_path,
            original_path=media_path,
            probe=mock_probe,
            preferences=preferences,
        )

    assert result.engine == "whisper_cloud_openai"
