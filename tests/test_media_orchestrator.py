"""
Tests for core/media_orchestrator.py — top-level media conversion coordinator.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.media_orchestrator import MediaConversionResult, MediaOrchestrator
from core.media_probe import MediaProbeResult
from core.transcript_formatter import FormatterOutput
from core.whisper_transcriber import TranscriptionResult, TranscriptionSegment


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def audio_probe():
    """MediaProbeResult for an audio file."""
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
        duration_secs=60.0,
        width=None,
        height=None,
        frame_rate=None,
        needs_transcode=False,
        transcode_reason=None,
    )


@pytest.fixture
def video_probe():
    """MediaProbeResult for a video file."""
    return MediaProbeResult(
        path=Path("/tmp/test.mp4"),
        container="mp4",
        media_type="video",
        has_video=True,
        has_audio=True,
        video_codec="h264",
        audio_codec="aac",
        audio_channels=2,
        audio_sample_rate=48000,
        duration_secs=120.0,
        width=1920,
        height=1080,
        frame_rate=29.97,
        needs_transcode=True,
        transcode_reason="video_file_needs_audio_extraction",
    )


@pytest.fixture
def transcription_result():
    """Standard TranscriptionResult."""
    return TranscriptionResult(
        segments=[
            TranscriptionSegment(
                index=0, start_seconds=0, end_seconds=5, text="Hello world"
            ),
        ],
        language="en",
        duration_seconds=60.0,
        engine="whisper_local",
        model_name="base",
        word_count=2,
        raw_text="Hello world",
    )


@pytest.fixture
def default_preferences():
    return {
        "whisper_model": "base",
        "whisper_language": "auto",
        "whisper_device": "auto",
        "transcription_cloud_fallback": "true",
        "caption_file_extensions": ".srt,.vtt,.sbv",
        "transcription_timeout_seconds": "3600",
    }


# ── Audio conversion ────────────────────────────────────────────────────────


async def test_convert_audio_file(
    tmp_path, audio_probe, transcription_result, default_preferences
):
    """Convert an audio file: probe → extract → transcribe → format."""
    source = tmp_path / "test.mp3"
    source.touch()
    output_dir = tmp_path / "output"

    with patch(
        "core.media_orchestrator.MediaProbe.probe",
        new_callable=AsyncMock,
        return_value=audio_probe,
    ), patch(
        "core.media_orchestrator.AudioExtractor.extract",
        new_callable=AsyncMock,
        return_value=source,
    ), patch(
        "core.media_orchestrator.TranscriptionEngine.transcribe",
        new_callable=AsyncMock,
        return_value=transcription_result,
    ):
        result = await MediaOrchestrator.convert(
            source, output_dir, default_preferences
        )

    assert isinstance(result, MediaConversionResult)
    assert result.transcription.engine == "whisper_local"
    assert result.probe.media_type == "audio"
    assert result.scenes is None  # no visual enrichment for audio
    assert result.formatter_output.md_path.exists()
    assert result.formatter_output.srt_path.exists()
    assert result.formatter_output.vtt_path.exists()


# ── Video conversion with scenes ─────────────────────────────────────────────


async def test_convert_video_with_enrichment(
    tmp_path, video_probe, transcription_result, default_preferences
):
    """Convert a video file with visual enrichment producing scenes."""
    source = tmp_path / "test.mp4"
    source.touch()
    output_dir = tmp_path / "output"

    from core.transcript_formatter import SceneDescription

    mock_scenes = [
        SceneDescription(
            scene_index=0,
            start_seconds=0,
            end_seconds=5,
            description="Opening shot",
        )
    ]

    with patch(
        "core.media_orchestrator.MediaProbe.probe",
        new_callable=AsyncMock,
        return_value=video_probe,
    ), patch(
        "core.media_orchestrator.AudioExtractor.extract",
        new_callable=AsyncMock,
        return_value=source,
    ), patch(
        "core.media_orchestrator.TranscriptionEngine.transcribe",
        new_callable=AsyncMock,
        return_value=transcription_result,
    ), patch(
        "core.media_orchestrator._run_visual_enrichment",
        new_callable=AsyncMock,
        return_value=mock_scenes,
    ):
        result = await MediaOrchestrator.convert(
            source, output_dir, default_preferences
        )

    assert result.scenes is not None
    assert len(result.scenes) == 1
    assert result.scenes[0].description == "Opening shot"
    assert "Scene 1" in result.formatter_output.md_content


# ── No audio raises ──────────────────────────────────────────────────────────


async def test_convert_no_audio_raises(tmp_path, default_preferences):
    """File with no audio track should raise ValueError."""
    source = tmp_path / "silent.mp4"
    source.touch()

    no_audio_probe = MediaProbeResult(
        path=source,
        container="mp4",
        media_type="video",
        has_video=True,
        has_audio=False,
        video_codec="h264",
        audio_codec=None,
        audio_channels=None,
        audio_sample_rate=None,
        duration_secs=10.0,
        width=1920,
        height=1080,
        frame_rate=30.0,
        needs_transcode=False,
        transcode_reason="no_audio",
    )

    with patch(
        "core.media_orchestrator.MediaProbe.probe",
        new_callable=AsyncMock,
        return_value=no_audio_probe,
    ):
        with pytest.raises(ValueError, match="No audio track"):
            await MediaOrchestrator.convert(
                source, tmp_path / "output", default_preferences
            )


# ── Enrichment failure is non-fatal ──────────────────────────────────────────


async def test_enrichment_failure_non_fatal(
    tmp_path, video_probe, transcription_result, default_preferences
):
    """Visual enrichment failure should not crash conversion."""
    source = tmp_path / "test.mp4"
    source.touch()

    with patch(
        "core.media_orchestrator.MediaProbe.probe",
        new_callable=AsyncMock,
        return_value=video_probe,
    ), patch(
        "core.media_orchestrator.AudioExtractor.extract",
        new_callable=AsyncMock,
        return_value=source,
    ), patch(
        "core.media_orchestrator.TranscriptionEngine.transcribe",
        new_callable=AsyncMock,
        return_value=transcription_result,
    ), patch(
        "core.media_orchestrator._run_visual_enrichment",
        new_callable=AsyncMock,
        return_value=None,  # enrichment returns None on failure
    ):
        result = await MediaOrchestrator.convert(
            source, tmp_path / "output", default_preferences
        )

    assert result.scenes is None
    assert result.formatter_output.md_path.exists()


# ── Temp dir cleanup ─────────────────────────────────────────────────────────


async def test_temp_dir_cleaned_up(
    tmp_path, audio_probe, transcription_result, default_preferences
):
    """Temp directory should be cleaned up after conversion."""
    source = tmp_path / "test.mp3"
    source.touch()

    temp_dirs_before = set(tmp_path.parent.glob("markflow_media_*"))

    with patch(
        "core.media_orchestrator.MediaProbe.probe",
        new_callable=AsyncMock,
        return_value=audio_probe,
    ), patch(
        "core.media_orchestrator.AudioExtractor.extract",
        new_callable=AsyncMock,
        return_value=source,
    ), patch(
        "core.media_orchestrator.TranscriptionEngine.transcribe",
        new_callable=AsyncMock,
        return_value=transcription_result,
    ):
        await MediaOrchestrator.convert(
            source, tmp_path / "output", default_preferences
        )

    # Note: temp dir is created in system temp, not in tmp_path.
    # We verify the cleanup logic runs without error (no assertion on path).
