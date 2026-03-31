"""
Tests for core/whisper_transcriber.py — Whisper integration.

Most tests use mocked Whisper to avoid the ~1GB model download.
The @slow test exercises real transcription on a silent WAV fixture.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.whisper_transcriber import TranscriptionResult, TranscriptionSegment, WhisperTranscriber


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def silent_wav(tmp_path):
    """Generate a 2-second silent WAV file."""
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


@pytest.fixture(autouse=True)
def reset_whisper_state():
    """Reset class-level state between tests."""
    WhisperTranscriber._model = None
    WhisperTranscriber._model_name = None
    WhisperTranscriber._device = None
    yield
    WhisperTranscriber._model = None
    WhisperTranscriber._model_name = None
    WhisperTranscriber._device = None


# ── Device resolution tests ──────────────────────────────────────────────────


def test_resolve_device_auto_cpu():
    """Auto should resolve to CPU when CUDA is unavailable."""
    with patch("core.whisper_transcriber.torch.cuda.is_available", return_value=False):
        device = WhisperTranscriber._resolve_device("auto")
    assert device == "cpu"


def test_resolve_device_auto_cuda():
    """Auto should resolve to CUDA when available."""
    with patch("core.whisper_transcriber.torch.cuda.is_available", return_value=True):
        device = WhisperTranscriber._resolve_device("auto")
    assert device == "cuda"


def test_resolve_device_cuda_fallback():
    """Requesting CUDA when unavailable should fall back to CPU."""
    with patch("core.whisper_transcriber.torch.cuda.is_available", return_value=False):
        device = WhisperTranscriber._resolve_device("cuda")
    assert device == "cpu"


def test_resolve_device_explicit_cpu():
    """Explicit CPU selection."""
    device = WhisperTranscriber._resolve_device("cpu")
    assert device == "cpu"


# ── Availability check ───────────────────────────────────────────────────────


def test_is_available_true():
    """is_available() returns True when whisper is importable."""
    with patch.dict("sys.modules", {"whisper": MagicMock()}):
        assert WhisperTranscriber.is_available() is True


def test_is_available_false():
    """is_available() returns False when whisper is not installed."""
    import sys
    # Temporarily remove whisper from sys.modules
    saved = sys.modules.pop("whisper", None)
    with patch("builtins.__import__", side_effect=ImportError("no whisper")):
        result = WhisperTranscriber.is_available()
    if saved is not None:
        sys.modules["whisper"] = saved
    assert result is False


# ── Device info ──────────────────────────────────────────────────────────────


def test_get_device_info_shape():
    """get_device_info() should return expected keys."""
    info = WhisperTranscriber.get_device_info()
    assert "whisper_available" in info
    assert "cuda_available" in info
    assert "device" in info
    assert "model_loaded" in info
    assert "gpu_name" in info


# ── Model caching ────────────────────────────────────────────────────────────


def test_model_is_lazy_loaded():
    """Model should not be loaded at import time."""
    assert WhisperTranscriber._model is None
    assert WhisperTranscriber._model_name is None


def test_model_caching():
    """Loading same model twice should reuse the instance."""
    mock_model = MagicMock()
    mock_whisper = MagicMock()
    mock_whisper.load_model.return_value = mock_model

    with patch.dict("sys.modules", {"whisper": mock_whisper}):
        with patch("core.whisper_transcriber.torch.cuda.is_available", return_value=False):
            model1 = WhisperTranscriber._load_model("base", "cpu")
            model2 = WhisperTranscriber._load_model("base", "cpu")

    assert model1 is model2
    assert mock_whisper.load_model.call_count == 1


def test_model_reloads_on_name_change():
    """Changing model name should trigger a reload."""
    mock_model_base = MagicMock()
    mock_model_tiny = MagicMock()
    mock_whisper = MagicMock()
    mock_whisper.load_model.side_effect = [mock_model_base, mock_model_tiny]

    with patch.dict("sys.modules", {"whisper": mock_whisper}):
        with patch("core.whisper_transcriber.torch.cuda.is_available", return_value=False):
            model1 = WhisperTranscriber._load_model("base", "cpu")
            model2 = WhisperTranscriber._load_model("tiny", "cpu")

    assert model1 is not model2
    assert mock_whisper.load_model.call_count == 2


# ── Transcription (mocked) ──────────────────────────────────────────────────


async def test_transcribe_mocked(tmp_path):
    """Transcribe with mocked Whisper model."""
    audio_file = tmp_path / "test.wav"
    audio_file.touch()

    mock_result = {
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.5, "text": " Hello world", "avg_logprob": -0.3},
            {"start": 2.5, "end": 5.0, "text": " Testing one two", "avg_logprob": -0.2},
        ],
    }

    mock_model = MagicMock()
    mock_model.transcribe.return_value = mock_result

    with patch.object(WhisperTranscriber, "_load_model", return_value=mock_model):
        result = await WhisperTranscriber.transcribe(audio_file, model_name="base")

    assert isinstance(result, TranscriptionResult)
    assert result.engine == "whisper_local"
    assert result.model_name == "base"
    assert result.language == "en"
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello world"
    assert result.segments[1].text == "Testing one two"
    assert result.word_count == 5
    assert result.duration_seconds == 5.0


async def test_transcribe_with_language(tmp_path):
    """Language parameter should be passed to Whisper."""
    audio_file = tmp_path / "test.wav"
    audio_file.touch()

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"language": "fr", "segments": []}

    with patch.object(WhisperTranscriber, "_load_model", return_value=mock_model):
        result = await WhisperTranscriber.transcribe(
            audio_file, model_name="base", language="fr"
        )

    mock_model.transcribe.assert_called_once()
    call_kwargs = mock_model.transcribe.call_args
    assert call_kwargs[1].get("language") == "fr"


async def test_transcribe_auto_language_not_passed(tmp_path):
    """Language 'auto' should not be passed to Whisper."""
    audio_file = tmp_path / "test.wav"
    audio_file.touch()

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"language": "en", "segments": []}

    with patch.object(WhisperTranscriber, "_load_model", return_value=mock_model):
        await WhisperTranscriber.transcribe(
            audio_file, model_name="base", language="auto"
        )

    call_kwargs = mock_model.transcribe.call_args
    assert "language" not in call_kwargs[1]


# ── Integration test (real Whisper) ──────────────────────────────────────────


@pytest.mark.slow
async def test_transcribe_real_audio(silent_wav):
    """Real Whisper transcription on a silent WAV file."""
    result = await WhisperTranscriber.transcribe(silent_wav, model_name="tiny")
    assert isinstance(result, TranscriptionResult)
    assert result.engine == "whisper_local"
    assert result.model_name == "tiny"
    # Silent audio may produce 0 segments or segments with empty/filler text
    assert isinstance(result.segments, list)
