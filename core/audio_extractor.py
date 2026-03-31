"""
Audio extractor — thin wrapper around MediaProbe.extract_audio_for_whisper
with temp file management.

Extracts audio suitable for Whisper from any media file.
Caller is responsible for cleaning up temp_dir.
"""

import structlog
from pathlib import Path

from core.media_probe import MediaProbe, MediaProbeResult

log = structlog.get_logger(__name__)


class AudioExtractor:
    """Extract Whisper-compatible audio from any media file."""

    @staticmethod
    async def extract(
        source: Path,
        probe: MediaProbeResult,
        temp_dir: Path,
    ) -> Path:
        """
        Extract audio suitable for Whisper from any media file.

        Returns path to a WAV file (may be in temp_dir or original source
        if no transcoding is needed).

        Caller is responsible for cleaning up temp_dir.
        """
        if not probe.has_audio:
            raise ValueError(f"No audio stream in {source.name}")

        dest = temp_dir / f"{source.stem}_audio.wav"
        result = await MediaProbe.extract_audio_for_whisper(source, dest, probe)
        log.info(
            "audio_extracted",
            source=str(source),
            dest=str(result),
            duration=probe.duration_secs,
        )
        return result
