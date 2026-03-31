"""
Transcript output formatter — produces .md, .srt, and .vtt files from
transcription results.

Optionally weaves in scene descriptions from the visual enrichment engine
at the appropriate timestamps in the .md output.
"""

import structlog
from dataclasses import dataclass
from pathlib import Path

from core.whisper_transcriber import TranscriptionResult, TranscriptionSegment

log = structlog.get_logger(__name__)


@dataclass
class SceneDescription:
    """Scene description from visual enrichment (existing pipeline)."""

    scene_index: int
    start_seconds: float
    end_seconds: float
    description: str | None
    keyframe_path: str | None = None


@dataclass
class FormatterOutput:
    """Output paths from formatting."""

    md_path: Path
    srt_path: Path
    vtt_path: Path
    md_content: str


class TranscriptFormatter:
    """
    Format transcription results into .md, .srt, .vtt files.
    Optionally interleaves scene descriptions (from visual enrichment)
    at the appropriate timestamps in the .md output.
    """

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """Format seconds as HH:MM:SS for .md display."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def format_srt_timestamp(seconds: float) -> str:
        """Format seconds as HH:MM:SS,mmm for .srt."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def format_vtt_timestamp(seconds: float) -> str:
        """Format seconds as HH:MM:SS.mmm for .vtt."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    @classmethod
    def format_all(
        cls,
        transcription: TranscriptionResult,
        output_dir: Path,
        filename_stem: str,
        source_format: str,
        source_path: str | None = None,
        scenes: list[SceneDescription] | None = None,
    ) -> FormatterOutput:
        """
        Produce .md, .srt, .vtt output files.
        If scenes is provided, interleave scene description blocks into the .md.
        """
        md_content = cls._format_md(
            transcription, filename_stem, source_format, source_path, scenes
        )
        srt_content = cls._format_srt(transcription)
        vtt_content = cls._format_vtt(transcription)

        md_path = output_dir / f"{filename_stem}.md"
        srt_path = output_dir / f"{filename_stem}.srt"
        vtt_path = output_dir / f"{filename_stem}.vtt"

        md_path.write_text(md_content, encoding="utf-8")
        srt_path.write_text(srt_content, encoding="utf-8")
        vtt_path.write_text(vtt_content, encoding="utf-8")

        log.info(
            "transcript_formatted",
            stem=filename_stem,
            segments=len(transcription.segments),
            scenes=len(scenes) if scenes else 0,
        )

        return FormatterOutput(
            md_path=md_path,
            srt_path=srt_path,
            vtt_path=vtt_path,
            md_content=md_content,
        )

    @classmethod
    def _format_md(
        cls,
        result: TranscriptionResult,
        filename_stem: str,
        source_format: str,
        source_path: str | None,
        scenes: list[SceneDescription] | None,
    ) -> str:
        """Build Markdown with YAML frontmatter + timestamped transcript."""
        duration_str = cls.format_timestamp(result.duration_seconds or 0)
        lines = [
            "---",
            f'title: "{filename_stem}"',
            f"source_format: {source_format}",
            f'duration: "{duration_str}"',
            f"engine: {result.engine}",
        ]
        if result.model_name:
            lines.append(f"whisper_model: {result.model_name}")
        if result.language:
            lines.append(f"language: {result.language}")
        lines.append(f"word_count: {result.word_count}")
        if source_path:
            lines.append(f'source_path: "{source_path}"')
        lines.append("---")
        lines.append("")
        lines.append(f"# {filename_stem}")
        lines.append("")
        lines.append("## Transcript")
        lines.append("")

        # Build a timeline combining segments and scenes
        if scenes:
            lines.extend(cls._interleave_with_scenes(result.segments, scenes))
        else:
            for seg in result.segments:
                ts = cls.format_timestamp(seg.start_seconds)
                speaker = f"**{seg.speaker}:** " if seg.speaker else ""
                lines.append(f"[{ts}] {speaker}{seg.text}")
                lines.append("")

        return "\n".join(lines)

    @classmethod
    def _interleave_with_scenes(
        cls,
        segments: list[TranscriptionSegment],
        scenes: list[SceneDescription],
    ) -> list[str]:
        """Interleave transcript segments with scene description blocks."""
        lines: list[str] = []
        scene_iter = iter(sorted(scenes, key=lambda s: s.start_seconds))
        next_scene = next(scene_iter, None)

        for seg in segments:
            # Insert scene blocks that start before or at this segment
            while next_scene and next_scene.start_seconds <= seg.start_seconds:
                lines.append("---")
                ts_start = cls.format_timestamp(next_scene.start_seconds)
                ts_end = cls.format_timestamp(next_scene.end_seconds)
                lines.append(
                    f"**[Scene {next_scene.scene_index + 1} "
                    f"\u2014 {ts_start} to {ts_end}]**"
                )
                if next_scene.description:
                    lines.append(f"*{next_scene.description}*")
                lines.append("---")
                lines.append("")
                next_scene = next(scene_iter, None)

            ts = cls.format_timestamp(seg.start_seconds)
            speaker = f"**{seg.speaker}:** " if seg.speaker else ""
            lines.append(f"[{ts}] {speaker}{seg.text}")
            lines.append("")

        # Remaining scenes after last segment
        while next_scene:
            lines.append("---")
            ts_start = cls.format_timestamp(next_scene.start_seconds)
            ts_end = cls.format_timestamp(next_scene.end_seconds)
            lines.append(
                f"**[Scene {next_scene.scene_index + 1} "
                f"\u2014 {ts_start} to {ts_end}]**"
            )
            if next_scene.description:
                lines.append(f"*{next_scene.description}*")
            lines.append("---")
            lines.append("")
            next_scene = next(scene_iter, None)

        return lines

    @classmethod
    def _format_srt(cls, result: TranscriptionResult) -> str:
        """Standard SRT format."""
        lines: list[str] = []
        for seg in result.segments:
            lines.append(str(seg.index + 1))
            lines.append(
                f"{cls.format_srt_timestamp(seg.start_seconds)} --> "
                f"{cls.format_srt_timestamp(seg.end_seconds)}"
            )
            lines.append(seg.text)
            lines.append("")
        return "\n".join(lines)

    @classmethod
    def _format_vtt(cls, result: TranscriptionResult) -> str:
        """WebVTT format."""
        lines = ["WEBVTT", ""]
        for seg in result.segments:
            lines.append(
                f"{cls.format_vtt_timestamp(seg.start_seconds)} --> "
                f"{cls.format_vtt_timestamp(seg.end_seconds)}"
            )
            lines.append(seg.text)
            lines.append("")
        return "\n".join(lines)
