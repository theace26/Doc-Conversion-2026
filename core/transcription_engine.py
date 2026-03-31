"""
Transcription fallback orchestrator — runs the three-step chain:

  1. Caption file (.srt/.vtt/.sbv alongside media file) → free, instant, perfect
  2. Local Whisper → fast, free, good accuracy
  3. Cloud providers (all configured, priority order) → costs money, best accuracy

Each step is tried in order. First success wins.
"""

import asyncio

import structlog
from pathlib import Path

from core.media_probe import MediaProbeResult
from core.whisper_transcriber import WhisperTranscriber, TranscriptionResult

log = structlog.get_logger(__name__)


class TranscriptionEngine:
    """Orchestrates the transcription fallback chain."""

    @staticmethod
    async def transcribe(
        audio_path: Path,
        original_path: Path,
        probe: MediaProbeResult,
        preferences: dict,
    ) -> TranscriptionResult:
        """
        Run the transcription fallback chain.

        Args:
            audio_path: Path to the audio file (WAV for Whisper, or original
                        for caption check)
            original_path: Path to the original media file (for caption lookup)
            probe: MediaProbeResult from probing the original file
            preferences: User preferences dict
        """
        # Step 1: Check for existing caption file alongside media file
        caption_exts_str = preferences.get(
            "caption_file_extensions", ".srt,.vtt,.sbv"
        )
        caption_exts = [e.strip() for e in caption_exts_str.split(",")]
        for ext in caption_exts:
            caption_path = original_path.with_suffix(ext)
            if caption_path.exists():
                log.info("caption_file_found", path=str(caption_path))
                try:
                    from core.caption_ingestor import CaptionIngestor

                    result = await CaptionIngestor.parse(caption_path)
                    result.duration_seconds = probe.duration_secs
                    return result
                except Exception as e:
                    log.warning(
                        "caption_parse_failed",
                        path=str(caption_path),
                        error=str(e),
                    )
                    # Fall through to Whisper

        # Step 2: Local Whisper
        if WhisperTranscriber.is_available():
            model = preferences.get("whisper_model", "base")
            language = preferences.get("whisper_language", "auto")
            device = preferences.get("whisper_device", "auto")
            timeout = int(preferences.get("transcription_timeout_seconds", "3600"))

            try:
                result = await asyncio.wait_for(
                    WhisperTranscriber.transcribe(
                        audio_path,
                        model_name=model,
                        language=language if language != "auto" else None,
                        device=device,
                    ),
                    timeout=timeout,
                )
                log.info(
                    "whisper_transcription_complete",
                    segments=len(result.segments),
                    words=result.word_count,
                    language=result.language,
                )
                return result
            except asyncio.TimeoutError:
                log.error(
                    "whisper_timeout",
                    timeout=timeout,
                    file=str(audio_path),
                )
            except Exception as e:
                log.error(
                    "whisper_failed",
                    error=str(e),
                    file=str(audio_path),
                )
        else:
            log.info("whisper_not_available")

        # Step 3: Cloud fallback
        cloud_fallback = (
            preferences.get("transcription_cloud_fallback", "true") == "true"
        )
        if cloud_fallback:
            try:
                from core.cloud_transcriber import CloudTranscriber

                language = preferences.get("whisper_language", "auto")
                result = await CloudTranscriber.transcribe(
                    audio_path,
                    language=language if language != "auto" else None,
                )
                log.info(
                    "cloud_transcription_complete",
                    engine=result.engine,
                    segments=len(result.segments),
                )
                return result
            except Exception as e:
                log.error("cloud_transcription_failed", error=str(e))

        raise RuntimeError(
            f"All transcription methods failed for {original_path.name}. "
            f"Whisper available: {WhisperTranscriber.is_available()}, "
            f"Cloud fallback enabled: {cloud_fallback}"
        )
