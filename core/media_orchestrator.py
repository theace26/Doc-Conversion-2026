"""
Media orchestrator — top-level coordinator for media file conversion.

For audio files: transcription → formatting
For video files: transcription + (optional) visual enrichment → formatting

Pipelines are SEPARATE — transcription and visual enrichment run independently.
They are combined at the formatting step only.
"""

import shutil
import tempfile

import structlog
from dataclasses import dataclass
from pathlib import Path

from core.audio_extractor import AudioExtractor
from core.media_probe import MediaProbe, MediaProbeResult
from core.transcription_engine import TranscriptionEngine
from core.transcript_formatter import (
    FormatterOutput,
    SceneDescription,
    TranscriptFormatter,
)
from core.whisper_transcriber import TranscriptionResult

log = structlog.get_logger(__name__)


@dataclass
class MediaConversionResult:
    """Complete result from media conversion."""

    formatter_output: FormatterOutput
    transcription: TranscriptionResult
    probe: MediaProbeResult
    scenes: list[SceneDescription] | None = None


class MediaOrchestrator:
    """
    Top-level coordinator for media file conversion.

    For audio files: transcription → formatting
    For video files: transcription + (optional) visual enrichment → formatting
    """

    @staticmethod
    async def convert(
        source_path: Path,
        output_dir: Path,
        preferences: dict,
    ) -> MediaConversionResult:
        """
        Convert a media file to .md + .srt + .vtt.

        Args:
            source_path: Path to the media file
            output_dir: Directory for output files
            preferences: User preferences dict
        """
        # Step 1: Probe the file
        probe = await MediaProbe.probe(source_path)
        log.info(
            "media_probe_complete",
            file=source_path.name,
            type=probe.media_type,
            duration=probe.duration_secs,
            has_audio=probe.has_audio,
            has_video=probe.has_video,
        )

        if not probe.has_audio:
            raise ValueError(
                f"No audio track in {source_path.name} — cannot transcribe"
            )

        # Step 2: Extract audio + transcribe
        temp_dir = Path(tempfile.mkdtemp(prefix="markflow_media_"))
        try:
            # Extract audio for Whisper
            audio_path = await AudioExtractor.extract(source_path, probe, temp_dir)

            # Run transcription fallback chain
            transcription = await TranscriptionEngine.transcribe(
                audio_path=audio_path,
                original_path=source_path,
                probe=probe,
                preferences=preferences,
            )
            transcription.duration_seconds = probe.duration_secs

            # Step 3: Visual enrichment (video only, if enabled)
            scenes = None
            if probe.has_video:
                scenes = await _run_visual_enrichment(
                    source_path, probe, temp_dir, output_dir
                )

            # Step 4: Format output
            output_dir.mkdir(parents=True, exist_ok=True)
            formatter_output = TranscriptFormatter.format_all(
                transcription=transcription,
                output_dir=output_dir,
                filename_stem=source_path.stem,
                source_format=source_path.suffix.lstrip("."),
                source_path=str(source_path),
                scenes=scenes,
            )

            return MediaConversionResult(
                formatter_output=formatter_output,
                transcription=transcription,
                probe=probe,
                scenes=scenes,
            )
        finally:
            # Clean up temp files
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)


async def _run_visual_enrichment(
    source_path: Path,
    probe: MediaProbeResult,
    tmp_dir: Path,
    output_dir: Path,
) -> list[SceneDescription] | None:
    """
    Run visual enrichment on video file using the EXISTING pipeline.
    Returns scene descriptions or None if enrichment is disabled/fails.
    """
    try:
        from core.visual_enrichment_engine import VisualEnrichmentEngine

        engine = VisualEnrichmentEngine()
        result = await engine.enrich(
            video_path=source_path,
            duration_seconds=probe.duration_secs or 0,
            tmp_dir=tmp_dir,
            output_dir=output_dir,
        )

        if not result or not result.scenes:
            return None

        # Convert enrichment result to SceneDescription list
        scenes: list[SceneDescription] = []
        for i, scene in enumerate(result.scenes):
            # Find matching description if available
            desc_text = None
            keyframe_path = None

            if result.descriptions:
                for d in result.descriptions:
                    if d.scene_index == scene.index:
                        desc_text = d.description if not d.error else None
                        break

            if result.keyframes:
                for kf in result.keyframes:
                    if kf.scene.index == scene.index:
                        keyframe_path = str(kf.image_path) if kf.image_path else None
                        break

            scenes.append(
                SceneDescription(
                    scene_index=scene.index,
                    start_seconds=scene.start_seconds,
                    end_seconds=scene.end_seconds,
                    description=desc_text,
                    keyframe_path=keyframe_path,
                )
            )

        return scenes if scenes else None

    except Exception as e:
        log.warning(
            "visual_enrichment_failed",
            error=str(e),
            file=source_path.name,
        )
        return None
