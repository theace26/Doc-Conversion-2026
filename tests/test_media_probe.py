"""
Tests for core/media_probe.py — ffprobe wrapper and transcode decisions.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.media_probe import MediaProbe, MediaProbeError, MediaProbeResult, _parse_frame_rate


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def silent_wav(tmp_path):
    """Generate a 2-second silent WAV file using ffmpeg."""
    path = tmp_path / "silence.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "2", "-acodec", "pcm_s16le", str(path),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg not available")
    return path


@pytest.fixture
def silent_mp4(tmp_path):
    """Generate a 2-second silent video (black + silent audio)."""
    path = tmp_path / "silence.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "2", "-c:v", "libx264", "-c:a", "aac",
            str(path),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg not available")
    return path


@pytest.fixture
def mock_ffprobe_audio():
    """Mock ffprobe JSON output for a pure audio file."""
    return json.dumps({
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "channels": 2,
                "sample_rate": "44100",
                "duration": "120.5",
            }
        ],
        "format": {
            "format_name": "mp3",
            "duration": "120.5",
        },
    })


@pytest.fixture
def mock_ffprobe_video():
    """Mock ffprobe JSON output for a video file with audio."""
    return json.dumps({
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30000/1001",
                "disposition": {"attached_pic": 0},
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "48000",
                "duration": "300.0",
            },
        ],
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "300.0",
        },
    })


# ── Unit tests (mocked ffprobe) ─────────────────────────────────────────────


async def test_probe_audio_file(tmp_path, mock_ffprobe_audio):
    """Probe an audio file (mocked) and verify parsed fields."""
    test_file = tmp_path / "test.mp3"
    test_file.touch()

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (mock_ffprobe_audio.encode(), b"")
    mock_proc.returncode = 0

    with patch("core.media_probe.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await MediaProbe.probe(test_file)

    assert result.media_type == "audio"
    assert result.has_audio is True
    assert result.has_video is False
    assert result.audio_codec == "mp3"
    assert result.duration_secs == 120.5
    assert result.needs_transcode is False  # mp3 is Whisper-native
    assert result.audio_channels == 2
    assert result.audio_sample_rate == 44100


async def test_probe_video_file(tmp_path, mock_ffprobe_video):
    """Probe a video file (mocked) and verify fields."""
    test_file = tmp_path / "test.mp4"
    test_file.touch()

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (mock_ffprobe_video.encode(), b"")
    mock_proc.returncode = 0

    with patch("core.media_probe.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await MediaProbe.probe(test_file)

    assert result.media_type == "video"
    assert result.has_audio is True
    assert result.has_video is True
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert result.width == 1920
    assert result.height == 1080
    assert result.duration_secs == 300.0
    assert result.needs_transcode is True  # video needs audio extraction
    assert result.transcode_reason == "video_file_needs_audio_extraction"
    assert result.frame_rate is not None
    assert abs(result.frame_rate - 29.97) < 0.01


async def test_probe_skips_album_art(tmp_path):
    """Album art video streams should be ignored."""
    data = json.dumps({
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "mjpeg",
                "width": 300,
                "height": 300,
                "disposition": {"attached_pic": 1},
            },
            {
                "codec_type": "audio",
                "codec_name": "flac",
                "channels": 2,
                "sample_rate": "44100",
            },
        ],
        "format": {"format_name": "flac", "duration": "240.0"},
    })

    test_file = tmp_path / "test.flac"
    test_file.touch()

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (data.encode(), b"")
    mock_proc.returncode = 0

    with patch("core.media_probe.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await MediaProbe.probe(test_file)

    assert result.media_type == "audio"
    assert result.has_video is False
    assert result.has_audio is True
    assert result.audio_codec == "flac"
    assert result.needs_transcode is False  # flac is Whisper-native


async def test_probe_error_on_non_media(tmp_path):
    """ffprobe failure should raise MediaProbeError."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("not a media file")

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"Invalid data found")
    mock_proc.returncode = 1

    with patch("core.media_probe.asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(MediaProbeError, match="ffprobe failed"):
            await MediaProbe.probe(test_file)


async def test_probe_unknown_audio_codec_needs_transcode(tmp_path):
    """Unknown audio codec should trigger transcode."""
    data = json.dumps({
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "wmav2",
                "channels": 2,
                "sample_rate": "44100",
            },
        ],
        "format": {"format_name": "asf", "duration": "60.0"},
    })

    test_file = tmp_path / "test.wma"
    test_file.touch()

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (data.encode(), b"")
    mock_proc.returncode = 0

    with patch("core.media_probe.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await MediaProbe.probe(test_file)

    assert result.needs_transcode is True
    assert "wmav2" in result.transcode_reason


# ── frame_rate parser tests ──────────────────────────────────────────────────


def test_parse_frame_rate_fraction():
    assert abs(_parse_frame_rate("30000/1001") - 29.97) < 0.01


def test_parse_frame_rate_integer():
    assert _parse_frame_rate("25") == 25.0


def test_parse_frame_rate_none():
    assert _parse_frame_rate(None) is None


def test_parse_frame_rate_zero_denominator():
    assert _parse_frame_rate("0/0") is None


# ── Integration tests (real ffmpeg) ──────────────────────────────────────────


@pytest.mark.slow
async def test_probe_real_wav(silent_wav):
    """Probe a real WAV file."""
    result = await MediaProbe.probe(silent_wav)
    assert result.media_type == "audio"
    assert result.has_audio is True
    assert result.audio_codec == "pcm_s16le"
    assert result.duration_secs is not None
    assert result.duration_secs >= 1.5  # ~2 seconds


@pytest.mark.slow
async def test_probe_real_mp4(silent_mp4):
    """Probe a real MP4 file."""
    result = await MediaProbe.probe(silent_mp4)
    assert result.media_type == "video"
    assert result.has_video is True
    assert result.has_audio is True
    assert result.needs_transcode is True


@pytest.mark.slow
async def test_extract_audio_from_video(silent_mp4, tmp_path):
    """Extract audio from video produces valid WAV."""
    probe = await MediaProbe.probe(silent_mp4)
    dest = tmp_path / "extracted.wav"
    result_path = await MediaProbe.extract_audio_for_whisper(
        silent_mp4, dest, probe
    )
    assert result_path == dest
    assert dest.exists()
    assert dest.stat().st_size > 0

    # Verify the extracted file is valid audio
    probe2 = await MediaProbe.probe(dest)
    assert probe2.has_audio is True
    assert probe2.audio_codec == "pcm_s16le"
